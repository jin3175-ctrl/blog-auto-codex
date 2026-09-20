"""내 블로그(내정보.txt의 블로그ID) 글 목록 수집 + 현재 글과 유사한 글 N개 선정."""
from __future__ import annotations

import re

from playwright.sync_api import sync_playwright

import config


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


def fetch_my_posts(blog_id: str, limit: int = 150) -> list[dict]:
    """내 글 {logNo, title, url} 수집.

    🔴2026-08-27 사고: 광수 후속편에서 «관련글을 찾지 못해 링크 섹션 생략»이 떴다.
      정작 그 소재의 **조회수 7,584회짜리 이전 편**이 바로 관련글인데 못 찾았다.
      원인은 매칭이 아니라 **수집량**이었다 — 모바일 목록을 한 번만 열고 스크롤하지 않아
      24개(≈2~3일치)만 모았다. 하루 10편씩 올리니 며칠 전 글은 아예 후보에 없었다.
      후속편에서 이전 편 링크가 빠지면 «연속으로 궁금해서 누르는» 흐름이 끊긴다.

    ★그래서 **공개 목록 API**(history.recent_posts)를 먼저 쓴다 — 브라우저·로그인이 필요 없고
      한 번에 150편(≈2주치)을 가져온다. 실패할 때만 옛 브라우저 방식으로 내려간다.
    """
    try:
        import history
        rows = history.recent_posts(limit, log=lambda m: None)
        if rows:
            return [{"logNo": r["logNo"], "title": r["title"],
                     "url": f"https://blog.naver.com/{blog_id}/{r['logNo']}"}
                    for r in rows if r.get("logNo") and r.get("title")]
    except Exception:  # noqa: BLE001
        pass
    return _fetch_my_posts_browser(blog_id, limit)


def _fetch_my_posts_browser(blog_id: str, limit: int = 150) -> list[dict]:
    """폴백 — 모바일 목록을 브라우저로 훑는다(느리고 적게 잡힌다)."""
    posts: list[dict] = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(storage_state=config.SESSION_FILE)
        pg = ctx.new_page()
        pg.set_default_timeout(20000)
        try:
            pg.goto(f"https://m.blog.naver.com/{blog_id}?tab=1", wait_until="domcontentloaded")
            pg.wait_for_timeout(3000)
            raw = pg.evaluate("""() => {
                const out=[];
                document.querySelectorAll("a[href*='logNo=']").forEach(a=>{
                    const m=(a.href||'').match(/logNo=(\\d+)/); if(!m) return;
                    let card=a.closest('li, .item, .post, div'); let title='';
                    if(card){ const el=card.querySelector("strong, .tit, .title, .se-title, .se_title"); if(el) title=(el.textContent||'').replace(/\\s+/g,' ').trim(); }
                    if(!title) title=(a.textContent||'').replace(/\\s+/g,' ').trim();
                    if(title && !/사진 개수|더보기|공감|댓글|이웃|카테고리/.test(title))
                        out.push({logNo:m[1], title:title.slice(0,80)});
                });
                return out;
            }""")
        finally:
            b.close()
    seen = set()
    for o in raw:
        if o["logNo"] in seen:
            continue
        seen.add(o["logNo"])
        title = re.sub(r"^제목\s*[:：]\s*", "", o["title"]).strip()
        posts.append({
            "logNo": o["logNo"],
            "title": title,
            "url": f"https://blog.naver.com/{blog_id}/{o['logNo']}",
        })
        if len(posts) >= limit:
            break
    return posts


def pick_related(keywords: list[str], current_title: str, posts: list[dict], n: int = 3) -> list[dict]:
    """키워드(해시태그 등) 겹침으로 유사 글 상위 n개 선정."""
    cur = _norm(current_title)
    # 너무 일반적인 키워드는 매칭력이 약하므로 그대로 두되 길이 가중
    scored = []
    for post in posts:
        if _norm(post["title"]) == cur:
            continue
        t = _norm(post["title"])
        score = 0
        hits = []
        for kw in keywords:
            k = _norm(kw)
            if len(k) >= 2 and k in t:
                score += len(k)  # 긴(구체적) 키워드에 가중
                hits.append(kw)
        if score > 0:
            scored.append((score, post, hits))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"title": p["title"], "url": p["url"], "hits": h} for _, p, h in scored[:n]]


# 제목만 보고 «나는솔로 계열인가»를 가른다 — 이 블로그의 실제 축이 나솔 7 : 그 외 3이다.
#   «31기 경수 순자와…» / «나는솔로 21기 영철…» / «나솔사계 7기 옥순…» 을 잡는다.
_NASOL_TITLE = re.compile(r"나는\s*솔로|나솔|\d{1,2}\s*기[\s가-힣]")


def pick_recent_same_axis(posts: list[dict], current_title: str, n: int = 3) -> list[dict]:
    """키워드가 하나도 안 겹칠 때 쓰는 폴백 — **같은 축의 최신 글** n개(2026-09-16 에디님 지적).

    > "연관블로그도 마지막에 안 들어가 있는 게 좀 있네"

    `pick_related`는 해시태그가 **이전 글 제목에 글자로 들어 있어야** 후보로 잡는다.
    그래서 그 인물을 처음 다루는 글은 늘 0건이 된다 — 9/16 실측 9편 중 4편이 그랬다
    (01편 박미선·조혜련, 07·08·09편). 나는솔로 글은 제목에 «33기 광수»가 박혀 잘 걸리지만,
    비나솔 인물은 두 번째 글을 쓸 때까지 관련글이 영영 안 붙는다.
    ★그렇다고 아무 글이나 붙이지 않는다 — 나솔 글엔 나솔을, 그 외 연예 글엔 그 외를 붙인다.
      독자가 그 축을 보러 왔기 때문이다. 축 판정은 **제목만** 보므로 카테고리 번호가 필요 없다.
    """
    cur = _norm(current_title)
    want = bool(_NASOL_TITLE.search(current_title or ""))
    out = []
    for post in posts:                      # posts는 최신순이다(history.recent_posts)
        t = post.get("title") or ""
        if _norm(t) == cur or bool(_NASOL_TITLE.search(t)) != want:
            continue
        out.append({"title": t, "url": post["url"], "hits": []})
        if len(out) >= n:
            break
    return out
