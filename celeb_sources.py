"""연예 글 생성용 실시간 소스 스크래핑.

- 기사(사실 재료): 네이버 연예 랭킹뉴스 목록 + 기사 본문.
- 제목·본문 '공식'(현재 홈판이 밀어주는 여러 연예 블로그): section.blog 스타·연예인(디렉토리12) 피드.
"""
from __future__ import annotations

import re

from playwright.sync_api import sync_playwright

_UA_M = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
         "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148")
RANK_URL = "https://m.entertain.naver.com/ranking"
THEME_URL = ("https://section.blog.naver.com/ThemePost.naver"
             "?directoryNo={d}&activeDirectorySeq=1&currentPage={p}")


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def fetch_news_ranking(limit: int = 20) -> list[dict]:
    """연예 랭킹뉴스 목록 [{rank,title,snippet,url}]."""
    out: list[dict] = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(user_agent=_UA_M)
        try:
            pg.goto(RANK_URL, wait_until="domcontentloaded", timeout=40000)
            pg.wait_for_timeout(1800)
            items = pg.eval_on_selector_all(
                "a",
                """els => els.map(e => ({txt:(e.innerText||'').trim(), h:e.href}))
                    .filter(x => x.txt && /\\/ranking\\/article\\//.test(x.h))""")
        finally:
            b.close()
    seen = set()
    for it in items:
        url = it["h"].split("?")[0]
        if url in seen:
            continue
        seen.add(url)
        lines = [l.strip() for l in it["txt"].splitlines() if l.strip()]
        # 첫 줄이 'N위'면 제거
        if lines and re.match(r"^\d+위$", lines[0]):
            lines = lines[1:]
        if not lines:
            continue
        out.append({"rank": len(out) + 1, "title": lines[0],
                    "snippet": _clean(" ".join(lines[1:]))[:120], "url": url})
        if len(out) >= limit:
            break
    return out


def parse_news_date(text: str, strict: bool = True):
    """기사 날짜 문자열 → date. 모르면 None.

    strict=True(검색 결과 화면): «3분 전»·«2일 전»·«2026.04.02.» 처럼 **날짜만 있는 줄**만 받는다
      (제목 안의 숫자를 날짜로 오인하지 않게).
    strict=False(기사 본문 화면): «입력 2026.04.02 오후 3:56»·«2026-04-02 15:56:00» 안에서 찾는다.
    """
    from datetime import date, timedelta
    t = (text or "").strip()
    today = date.today()
    m = re.match(r"^(\d+)\s*(분|시간|일|주|개월|달|년)\s*전$", t)
    if m:
        n, u = int(m.group(1)), m.group(2)
        days = {"분": 0, "시간": 0, "일": n, "주": 7 * n, "개월": 30 * n, "달": 30 * n,
                "년": 365 * n}[u]
        if u == "시간" and n >= 24:
            days = n // 24
        return today - timedelta(days=days)
    if t == "어제":
        return today - timedelta(days=1)
    pat = (r"^(\d{4})[.\-]\s*(\d{1,2})[.\-]\s*(\d{1,2})\.?$" if strict
           else r"(\d{4})[.\-]\s*(\d{1,2})[.\-]\s*(\d{1,2})")
    m = re.search(pat, t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


_NEWS_SEARCH = "https://m.search.naver.com/search.naver?where=m_news&sort=1&query={q}"


def fetch_news_search(query: str, limit: int = 5) -> list[dict]:
    """네이버 뉴스 검색(최신순)에서 [{title, snippet, body, url}]. 특정 소재(나솔·이혼숙려 등) 능동 확보용.
    ★기사 링크가 최신 DOM에서 불안정해, 검색 스니펫(문단)을 body 소재로 함께 담는다(url='' 가능)."""
    import urllib.parse
    texts: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(user_agent=_UA_M)
        try:
            pg.goto(_NEWS_SEARCH.format(q=urllib.parse.quote(query)),
                    wait_until="domcontentloaded", timeout=35000)
            pg.wait_for_timeout(2200)
            texts = pg.eval_on_selector_all(
                ".sds-comps-text",
                "els => els.map(e => (e.innerText||'').trim()).filter(t => t.length >= 2)")
        finally:
            b.close()
    texts = [_clean(t) for t in texts]
    # 짧은 줄(제목, ~55자, 문장부호로 안 끝남) 뒤에 오는 긴 줄(스니펫 문단)을 짝짓는다.
    # 🔴**날짜를 버리지 않는다**(2026-09-11 사고). 예전엔 12자 미만 줄을 전부 버려서
    #   «3분 전»·«2026.04.02.» 같은 날짜 줄이 사라졌다. 그래서 **5개월 전 기사**
    #   («금쪽같은 내 새끼» 4월 3일 방송)가 오늘 소재로 올라왔고, 본문은 «3일 방송된»을
    #   9월 3일로 읽었다. 화면 순서는 «언론사 → 날짜 → 제목 → 스니펫»이라,
    #   제목 바로 앞에 나온 날짜를 그 기사의 날짜로 붙인다.
    out: list[dict] = []
    seen: set = set()
    i = 0
    cur_date = None
    while i < len(texts) and len(out) < limit:
        t = texts[i]
        d = parse_news_date(t) if len(t) <= 25 else None
        if d:
            cur_date = d
            i += 1
            continue
        if len(t) < 12:
            i += 1
            continue
        is_title = 12 <= len(t) <= 60
        item_date = cur_date if is_title else None
        if is_title:
            cur_date = None            # 다음 기사는 자기 날짜를 새로 받는다
        snip = ""
        if is_title and i + 1 < len(texts) and len(texts[i + 1]) > 60:
            snip = texts[i + 1]
            i += 2
        else:
            i += 1
        # ★관련도: 소재가 '제목'에 있어야 채택(스니펫만 걸치는 오탐 제거).
        #   🔴2026-08-27: 예전엔 **쿼리 전체 문자열**이 제목에 통째로 있어야 통과시켰다.
        #     그래서 «나는솔로 33기 광수» 같은 여러 낱말 쿼리는 «나는솔로33기광수»를 찾다가
        #     **항상 0건**이 됐다(페이지는 30건을 정상으로 돌려주는데 파서가 다 버렸다).
        #     지금까지 안 드러난 건 `build_pure_pool`이 «나는솔로»·«이혼숙려캠프»처럼
        #     **낱말 하나짜리 쿼리만** 써서다. 소재를 좁혀 찾으려는 순간 못 쓰게 된다.
        #   → 낱말로 쪼개 **절반 이상**이 제목에 있으면 채택한다(한 낱말 쿼리는 전과 동일).
        qwords = [w for w in query.split() if len(w) >= 2]
        tkey = t.replace(" ", "")
        hits = sum(1 for w in qwords if w.replace(" ", "") in tkey)
        if not is_title or hits < max(1, (len(qwords) + 1) // 2):
            continue
        key = t[:30]
        if key in seen:
            continue
        seen.add(key)
        out.append({"title": t[:90], "snippet": snip[:160],
                    "body": (t + " " + snip)[:1200], "url": "",
                    "date": item_date.isoformat() if item_date else ""})
    return out


def fetch_article(url: str) -> dict:
    """기사 본문 {title, body}."""
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(user_agent=_UA_M)
        title, body, raw_date = "", "", ""
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=40000)
            pg.wait_for_timeout(1500)
            for sel in ["h2.end_tit", ".media_end_head_headline", "h2", "title"]:
                try:
                    title = _clean(pg.locator(sel).first.inner_text(timeout=2500))
                    if title:
                        break
                except Exception:  # noqa: BLE001
                    pass
            for sel in ["#comp_news_article ._article_content", "#dic_area",
                        ".article_body", "#newsEndContents", "article"]:
                try:
                    body = pg.locator(sel).first.inner_text(timeout=3500)
                    if body.strip():
                        break
                except Exception:  # noqa: BLE001
                    pass
            # ★발행일도 읽는다(2026-09-11 사고: 날짜 없이 «3일 방송»만 보고 달을 추측했다).
            #   네이버 뉴스는 data-date-time, 연예·언론사 페이지는 .date 류에 «2026.04.04. 오전 7:00».
            try:
                raw_date = pg.evaluate("""() => {
                    const d = document.querySelector('[data-date-time]');
                    if (d) return d.getAttribute('data-date-time');
                    const e = document.querySelector('.date, ._ARTICLE_DATE_TIME, '
                        + '.media_end_head_info_datestamp_time, .info_date, .article_info, time');
                    return e ? (e.getAttribute('datetime') || e.innerText || '') : '';
                }""") or ""
            except Exception:  # noqa: BLE001
                raw_date = ""
        finally:
            b.close()
    body = re.sub(r"원본 이미지 보기", "", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    d = parse_news_date(raw_date, strict=False)
    return {"title": title, "body": body, "date": d.isoformat() if d else ""}


def fetch_theme_titles(directory: int = 12, n: int = 40, max_pages: int = 3) -> list[str]:
    """현재 밀어주는 연예 블로그 글 제목(여러 블로그). directory=12: 스타·연예인."""
    titles: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": 1280, "height": 2400})
        try:
            for pno in range(1, max_pages + 1):
                pg.goto(THEME_URL.format(d=directory, p=pno), wait_until="domcontentloaded", timeout=35000)
                pg.wait_for_timeout(2000)
                loc = pg.locator(".title_post")
                for i in range(loc.count()):
                    t = _clean(loc.nth(i).inner_text())
                    if t and len(t) >= 6 and t not in titles:
                        titles.append(t)
                if len(titles) >= n:
                    break
        finally:
            b.close()
    return titles[:n]


RECOMMEND_URL = "https://m.blog.naver.com/Recommendation.naver"


def fetch_recommend_titles(n: int = 90, scrolls: int = 8) -> list[str]:
    """지금 홈판(추천 피드)에 떠 있는 글 제목. 주제 구분 없이 **전체**를 준다.

    🔴2026-09-07 에디님이 찾아주신 소스다. 기존 `fetch_theme_titles(0, 30)`은
      한 페이지에 30개뿐인데 여기는 **스크롤만 내리면 90개 넘게** 나온다(실측 90개).
      제목 공식은 표본이 많을수록 정확해진다 — 30개로 뽑은 «공식»은 그 30개의 버릇일 수 있다.

    ⚠️분야를 못 고른다(directoryNo 같은 인자가 없다). 그래서 **전체 홈판 공식 전용**이다.
      연예(dir=12)·IT(dir=30)처럼 결이 필요한 곳은 `fetch_theme_titles`를 그대로 쓴다.
    """
    titles: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(user_agent=_UA_M, viewport={"width": 420, "height": 900})
        try:
            pg.goto(RECOMMEND_URL, wait_until="domcontentloaded", timeout=45000)
            pg.wait_for_timeout(3000)
            for _ in range(scrolls):
                pg.mouse.wheel(0, 4000)
                pg.wait_for_timeout(900)
            got = pg.evaluate(r"""() => {
                const out = [];
                document.querySelectorAll('a').forEach(a => {
                  const t = (a.innerText || '').trim().split('\n')[0];
                  // 글 주소(/블로그id/로그번호)를 가진 링크의 첫 줄만 제목으로 본다
                  if (/\/\d{9,}/.test(a.href || '') && t.length >= 8) out.push(t);
                });
                return [...new Set(out)];
            }""")
            for t in got:
                t = _clean(t)
                if t and len(t) >= 8 and t not in titles:
                    titles.append(t)
        finally:
            b.close()
    return titles[:n]


def fetch_theme_posts(directory: int = 12, n: int = 6) -> list[dict]:
    """현재 밀어주는 연예 블로그 글 [{title,url}] (본문 구조 샘플용)."""
    out: list[dict] = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": 1280, "height": 2400})
        try:
            pg.goto(THEME_URL.format(d=directory, p=1), wait_until="domcontentloaded", timeout=35000)
            pg.wait_for_timeout(2200)
            items = pg.eval_on_selector_all(
                "a",
                """els => els.map(e => ({t:(e.innerText||'').trim(), h:e.href}))
                    .filter(x => x.t && /blog\\.naver\\.com\\/[^/]+\\/\\d+/.test(x.h))""")
        finally:
            b.close()
    seen = set()
    for it in items:
        url = it["h"].split("?")[0]
        if url in seen or len(it["t"]) < 8:
            continue
        seen.add(url)
        out.append({"title": _clean(it["t"])[:60], "url": url})
        if len(out) >= n:
            break
    return out


def fetch_theme_thumbnails(directory: int = 30, n: int = 6, max_pages: int = 2) -> list[str]:
    """현재 밀어주는 글들의 '대표 썸네일 이미지 URL' 목록. 썸네일 공식 추출용(비전 분석).
    directory=30: IT·컴퓨터."""
    urls: list[str] = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": 1280, "height": 2400})
        try:
            for pno in range(1, max_pages + 1):
                pg.goto(THEME_URL.format(d=directory, p=pno), wait_until="domcontentloaded", timeout=35000)
                pg.wait_for_timeout(2000)
                imgs = pg.eval_on_selector_all(
                    "img",
                    """els => els.map(e => e.currentSrc || e.src || '')
                        .filter(s => /pstatic\\.net|blogthumb|postfiles/.test(s))""")
                for s in imgs:
                    u = s.split("?")[0]
                    if u and u not in urls:
                        urls.append(u)
                if len(urls) >= n:
                    break
        finally:
            b.close()
    return urls[:n]


def fetch_blog_titles(query: str, n: int = 20) -> list[str]:
    """네이버 **블로그 검색** 제목을 긁는다 (2026-09-10 신설).

    🔴왜 필요한가 — 실측(2026-09-10, 같은 검색어):
        「나는솔로 33기 근황」   뉴스 1건  /  블로그 92건
        「나는솔로 33기 인스타」 뉴스 0건  /  블로그 다수
      **나솔 «방송 밖» 이야기(목격담·현커·근황)는 기사화가 거의 안 된다.** 그래서 뉴스만 보던
      기존 경로로는 방송 밖 소재가 풀에 들어올 수가 없었고, 결국 방송 내용만 쓰게 됐다
      (에디님 지적: "방송 밖 이야기를 많이 써야 사람들이 궁금해할 거 아냐?").

    ⚠️**남의 블로그 글을 재료로 베끼지 않는다.** 이건 «지금 무슨 소재가 도는가»를 알아내는
      용도다. 여러 블로거가 같은 소재를 쓰고 있으면 그게 지금 먹히는 소재라는 신호다
      (이서이 강사도 «유사성이 높으면 같이 죽는다»고 경고했다 — 소재만 가져오고 글은 새로 쓴다).
    ★API 키(`NAVER_CLIENT_SECRET`)가 만료돼 있어 공개 검색 화면을 긁는다.
    """
    import urllib.parse
    import urllib.request
    u = ("https://m.search.naver.com/search.naver?ssc=tab.m_blog.all&sm=mtb_jum&query="
         + urllib.parse.quote(query))
    try:
        html = urllib.request.urlopen(urllib.request.Request(
            u, headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                                      "AppleWebKit/605.1.15 Mobile/15E148"}),
            timeout=20).read().decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        return []
    # ★클래스명이 해시(`fender-ui_…`)라 자주 바뀐다 → **의미 클래스 `headline1`**만 본다.
    out, seen = [], set()
    for m in re.finditer(r'sds-comps-text-type-headline1[^"]*"[^>]*>(.*?)</span>', html, re.S):
        t = _clean(re.sub(r"<[^>]+>", "", m.group(1)))     # <mark> 강조 태그 제거
        if len(t) < 8 or t in seen:
            continue
        seen.add(t)
        out.append(t)
        if len(out) >= n:
            break
    return out


def fetch_blog_body(url: str, max_chars: int = 1800) -> str:
    """블로그 글 본문 텍스트(모바일). 구조/톤 샘플용."""
    murl = re.sub(r"^https?://blog\.naver\.com/", "https://m.blog.naver.com/", url)
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(user_agent=_UA_M)
        txt = ""
        try:
            pg.goto(murl, wait_until="domcontentloaded", timeout=40000)
            pg.wait_for_timeout(1500)
            for sel in [".se-main-container", "#postViewArea", ".post_ct"]:
                try:
                    txt = pg.locator(sel).first.inner_text(timeout=4000)
                    if txt.strip():
                        break
                except Exception:  # noqa: BLE001
                    pass
        finally:
            b.close()
    return re.sub(r"\n{3,}", "\n\n", txt).strip()[:max_chars]


if __name__ == "__main__":
    news = fetch_news_ranking(8)
    print(f"[랭킹뉴스 {len(news)}]")
    for a in news:
        print(f"  {a['rank']}. {a['title']}")
    tt = fetch_theme_titles(12, 10)
    print(f"[연예블로그 제목 {len(tt)}]")
    for t in tt:
        print("  -", t)
