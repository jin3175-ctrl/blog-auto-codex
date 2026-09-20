"""1편 처리 파이프라인:
   본문은 _복붙용.txt 그대로 복붙, 제목만 '지금 뜨는 인기글 패턴' 기반으로 AI 생성."""
from __future__ import annotations

import os
import re
import datetime as _dt
from typing import Callable

import blog_related
import config
import image_finder
import keyword_select
import naver
import naver_titles
import parse_post
import posts
import quote_select
import render_assets
import title_gen
from claude_cli import NotLoggedInError

Logger = Callable[[str], None]


def _make_title(body: str, folder: str, post_no: str, log: Logger) -> str:
    """지금 뜨는 인기 제목 30개 → 패턴화 → 제목 생성. 실패 시 manifest 부제로 폴백."""
    try:
        log("네이버 블로그 홈 인기글 제목 수집 중…")
        trending = naver_titles.fetch_trending_titles(count=30)
        log(f"인기 제목 {len(trending)}개 수집. 패턴 분석 후 제목 생성(claude -p)…")
        title = title_gen.generate_title(body, trending)
        if not title.strip():
            log("AI 제목이 비어 있어 한 번 더 시도합니다…")
            title = title_gen.generate_title(body, trending)
        if title.strip():
            log(f"AI 생성 제목: {title}")
            return title.strip()
        log("AI 제목이 계속 비어 폴백을 사용합니다.")
    except NotLoggedInError as e:
        log(f"제목 AI 생성 건너뜀: {e}")
    except Exception as e:  # noqa: BLE001
        log(f"제목 생성 중 오류(폴백 사용): {e}")
    fallback = posts.get_manifest_subtitle(folder, post_no) or "제목 없음"
    log(f"폴백 제목 사용: {fallback}")
    return fallback


# 갤럽 34 테마 목차 순서(강점인사이트 시리즈 제목 순번용)
INSIGHT_THEME_ORDER = [
    "성취", "행동", "적응", "분석", "정리", "신념", "주도력", "커뮤니케이션", "승부", "연결성",
    "공정성", "회고", "심사숙고", "개발", "체계", "공감", "집중", "미래지향", "화합", "발상",
    "포용", "개별화", "수집", "지적사고", "배움", "최상화", "긍정", "절친", "책임", "복구",
    "자기확신", "존재감", "전략", "사교성",
]


def _insight_prefix(folder: str, post_no: str) -> str:
    """강점인사이트 글이면 '[순번. 테마] ' 접두 반환(갤럽 목차 순서)."""
    assets = posts.find_assets(folder, post_no)
    vis = assets.get("강점시각화") or assets.get("장점") or assets.get("맹점")
    if not vis:
        return ""
    m = re.match(r"\d+_(.+?)_(?:강점시각화|장점|맹점)", os.path.basename(vis))
    if not m:
        return ""
    theme = m.group(1)
    try:
        n = INSIGHT_THEME_ORDER.index(theme) + 1
    except ValueError:
        return ""
    return f"[{n}. {theme}] "


#: 문장 끝이 **아닌** 마침표. 숫자 사이(3.9%)·영문 약어(a.m.) 뒤엔 문장이 안 끝난다.
#  🔴실측(2026-08-24): «체지방률 3.9%»에 노랑을 칠했더니 «체지방률 3.» 까지만 칠해졌다.
#    소수점을 문장 끝으로 봐서다. 노랑 배경은 눈에 바로 띄는 서식이라 잘리면 티가 크다.
def _is_sentence_end(text: str, i: int) -> bool:
    if i + 1 < len(text) and text[i + 1].isdigit():
        return False                       # 3.9 → 소수점
    if i > 0 and text[i - 1].isdigit() and i + 1 < len(text) and text[i + 1] not in " \n":
        return False
    return True


def _sentence_span(text: str, idx: int) -> tuple[int, int]:
    """text에서 idx를 포함하는 '한 문장'의 (start,end). 마침표 기준(소수점은 제외)."""
    e = idx
    while True:
        e = text.find(".", e)
        if e < 0:
            e = len(text)
            break
        if _is_sentence_end(text, e):
            e += 1
            break
        e += 1
    s, cur = 0, 0
    while True:
        cur = text.find(".", cur)
        if cur < 0 or cur >= idx:
            break
        if _is_sentence_end(text, cur):
            s = cur + 1
        cur += 1
    while s < len(text) and text[s] == " ":
        s += 1
    return s, e


_RE_SOURCE_LINE = re.compile(r"^\s*@?\s*출처\s*[:：\-–—]\s*(.+)$")


def _normalize_source_line(blocks: list[dict], log: Logger) -> None:
    """맨 끝 출처 줄의 표기를 '@출처 : 매체명'으로 통일한다.

    생성기마다 "@출처 - Gallup, Inc." / "출처: MHN스포츠" 처럼 제각각이라 프롬프트로만
    맞추면 LLM이 흘린다. 여기서 최종 형태를 강제한다.
    (본문 중간의 [사진N - ... / 출처: ...] 마커는 photo 블록이라 여기 안 걸린다.)
    """
    for b in blocks:
        if b.get("type") != "text":
            continue
        m = _RE_SOURCE_LINE.match(b["text"])
        if not m:
            continue
        fixed = f"@출처 : {m.group(1).strip()}"
        if b["text"].strip() != fixed:
            log(f"출처 표기 통일: {b['text'].strip()[:40]} → {fixed[:40]}")
            b["text"] = fixed


# '1단계…' 또는 '첫째,/둘째,/셋째…' 처럼 연속 열거로 시작하는 머리줄
_STEP_RE = re.compile(
    r"^\s*(?:\d+\s*단계\b"
    r"|(?:첫째|둘째|셋째|넷째|다섯째|여섯째|일곱째|첫 번째|두 번째|세 번째|네 번째|다섯 번째)\s*[,，]?)")


def _apply_step_quotes(blocks: list[dict], log: Logger) -> int:
    """'1단계, …' '2단계 …' 같은 단계 머리줄을 인용구2(버티컬 라인)로 바꿔 깔끔하게."""
    n = 0
    for i, b in enumerate(blocks):
        if b.get("type") == "text" and _STEP_RE.match(b.get("text", "")):
            blocks[i] = {"type": "quote", "style": "small",
                         "nstyle": "quotation_line", "text": b["text"].strip()}
            n += 1
    if n:
        log(f"단계 머리줄 {n}곳 → 인용구2(라인형)")
    return n


def _apply_photo_subheads(blocks: list[dict], log: Logger) -> int:
    """사진(또는 사진 대체 이미지) 바로 뒤에 오는 '소주제' 줄을 66박스 인용으로 바꾼다.

    연예 원고는 사진 뒤를 소주제로 여는 패턴이 굳어져 있는데([사진4] → '무엇을 벗어던졌나'),
    프롬프트에 [소주제] 마커가 없어서 평문으로 깔렸다. AI 선정(quote_select)에 맡기면
    놓치므로 규칙으로 고정한다.

    소주제 판정: 사진 직후 첫 text 블록 + 짧음(24자 이하) + 문장부호로 끝나지 않음.
    (마침표로 끝나면 일반 문장이므로 건드리지 않는다.)
    """
    applied = []
    for i, b in enumerate(blocks):
        # 사진 자리표시자(photo) 또는 자동첨부된 본문 이미지(image/kind=body)
        is_photo = b.get("type") == "photo" or (
            b.get("type") == "image" and b.get("kind") == "body")
        if not is_photo:
            continue
        # 뒤쪽 첫 text 블록 찾기(빈 줄 건너뜀)
        j = i + 1
        while j < len(blocks) and blocks[j].get("type") == "blank":
            j += 1
        if j >= len(blocks) or blocks[j].get("type") != "text":
            continue
        t = blocks[j]["text"].strip()
        # 이미 인용/서식이 잡힌 건 건드리지 않음
        if not t or blocks[j].get("spans"):
            continue
        if len(t) > 24 or t[-1] in ".?!…\"'”’)":
            continue          # 길거나 문장부호로 끝나면 일반 문장
        blocks[j] = {"type": "quote", "style": "small", "nstyle": "default", "text": t}
        applied.append(t)
    if applied:
        log(f"사진 뒤 소주제 {len(applied)}곳 → 따옴표(66박스) 인용: {applied}")
    return len(applied)


_YT_CTA_RE = re.compile(r"AI\s*생존기\s*Edi|유튜브\s*@|@AI생존기|유튜브.{0,12}(채널|에서).{0,20}(구독|놀다|이어|보실|오세요|좋아요)")


def _strip_youtube_cta(blocks: list[dict], log: Logger) -> int:
    """연예 글에서 유튜브 채널 홍보 문단을 제거한다(2026-08-02 에디님 지시).

    연예 글은 '순수 홈판 트래픽'용이라 채널 홍보가 붙으면 성격이 흐려진다.
    프롬프트로 금지해도 LLM이 종종 넣어서 업로드 단계에서 한 번 더 걷어낸다.
    """
    keep, removed = [], 0
    for b in blocks:
        if b.get("type") == "text" and _YT_CTA_RE.search(b.get("text") or ""):
            removed += 1
            continue
        keep.append(b)
    if removed:
        blocks[:] = keep
        log(f"유튜브 채널 홍보 {removed}문단 제거(연예 글 규칙)")
    return removed


def _insert_youtube_thumb(blocks: list[dict], workdir: str, log: Logger) -> bool:
    """유튜브 안내 문구 뒤에 '최신 영상 썸네일 이미지'를 넣는다(링크는 넣지 않음).

    네이버가 본문 외부링크를 선호하지 않으므로 링크 대신 썸네일만 붙인다(2026-07-24 에디님 지시).
    실패해도 글은 그대로 진행(베스트 에포트).
    """
    idx = None
    for i, b in enumerate(blocks):
        if b.get("type") != "text":
            continue
        t = b.get("text") or ""
        if "AI생존기Edi" in t or ("유튜브" in t and "채널" in t):
            idx = i          # 마지막으로 언급된 자리에 붙인다
    if idx is None:
        return False
    try:
        import youtube_thumb
        path = youtube_thumb.fetch_thumbnail(workdir, "yt_latest.jpg", log=log)
    except Exception as e:  # noqa: BLE001
        log(f"유튜브 썸네일 실패(건너뜀): {str(e)[:100]}")
        return False
    if not path:
        return False
    blocks.insert(idx + 1, {"type": "image", "kind": "body", "path": path,
                            "label": "유튜브최신", "missing": False})
    log("유튜브 안내 뒤에 최신 영상 썸네일 삽입(링크 없음)")
    return True


def _apply_orphan_subheads(blocks: list[dict], log: Logger) -> int:
    """사진 뒤가 아닌 자리에 '홀로 떨어진' 소주제 줄을 라인형 인용으로 정리한다.

    생성기가 소주제를 [사진N] 바로 뒤가 아닌 곳에도 흘려 놓으면(예: '왜 지금 다들 찾는지',
    '저품질 함정') 평문으로 깔려서 문맥 없는 파편처럼 보인다(2026-07-24 에디님 지적).
    사진 뒤 소주제(66박스)와 구분되도록 여기선 라인형을 쓴다.

    판정(오탐 방지로 빡빡하게): 앞뒤가 모두 빈 줄인 독립 줄 + 22자 이하 +
    문장부호로 끝나지 않음 + 서식 없음.
    """
    applied = []
    for i, b in enumerate(blocks):
        if b.get("type") != "text" or b.get("spans"):
            continue
        # ★제로폭 공백(U+200B 등)은 눈에 안 보이지만 strip()으로 안 지워진다 → '빈 줄'인데도
        #   소주제로 잡혀 '내용을 입력하세요' 빈 인용박스가 대량 생성됐다(2026-08-02, 45곳).
        t = (b.get("text") or "").replace("​", "").replace("﻿", "").strip()
        # ★32자로 완화(2026-08-02): 22자 제한 때문에 목차의 '04 2026년 주의점 — 이건 조심하세요'(23자)만
        #   인용구가 안 걸려 4번 항목만 평문으로 남는 문제가 있었다(에디님 지적).
        if not t or len(t) > 32 or t[-1] in ".?!…\"'”’)":
            continue
        # 장식 기호(◆ ▶ ■ 등)는 소주제 앞에 붙어도 본문에선 지저분하다 → 떼고 쓴다
        t = re.sub(r"^[◆◇▶▷■□●○★☆※]+\s*", "", t).strip()
        if not t:
            continue
        b["text"] = t
        # 출처·해시태그·마커 줄은 소주제가 아니다(2026-07-24: '@출처 : 직접 운영 경험'이
        # 인용구로 바뀌는 버그가 있었음)
        if t.startswith(("@", "#", "[", "★", "※", "·", "-")) or "출처" in t:
            continue
        prev_blank = i == 0 or blocks[i - 1].get("type") == "blank"
        next_blank = i + 1 >= len(blocks) or blocks[i + 1].get("type") == "blank"
        if not (prev_blank and next_blank):
            continue          # 문단 속 짧은 문장은 건드리지 않음
        blocks[i] = {"type": "quote", "style": "small",
                     "nstyle": "quotation_line", "text": t}
        applied.append(t)
    if applied:
        log(f"고아 소주제 {len(applied)}곳 → 인용구2(라인형): {applied}")
    return len(applied)


def _build_spans(blocks: list[dict], folder: str, post_no: str, body: str, log: Logger) -> None:
    """각 text 블록에 서식 spans 부여.
      - 강점 키워드: 모든 등장 → 굵게+빨강
      - 핵심 키워드(첫 등장): 그 '문장'에 노랑 배경 + 키워드만 굵게
    """
    import re
    red = _detect_emphasis(folder, post_no, body)  # 강점 키워드(예: 승부(Competition))
    for b in blocks:
        if b.get("type") == "text":
            spans = []
            for p in red:
                for m in re.finditer(re.escape(p), b["text"]):
                    spans.append((m.start(), m.end(), {"bold": True, "color": naver.EMPH_RED}))
            b["spans"] = spans
    if red:
        log(f"굵게+빨강(강점): {red}")

    try:
        # 글이 길어(사진 8~12장) 6개로는 강조가 3~4곳에 그쳐 '중간중간' 느낌이 안 난다 → 10개로 확대
        kws = keyword_select.select_keywords(body, max_n=10)
    except Exception as e:  # noqa: BLE001
        log(f"핵심 키워드 선정 건너뜀: {e}")
        kws = []
    kws = [k for k in kws if k and k not in red]
    # ★노랑과 빨강을 **겹쳐 쓰지 않는다**(2026-08-24 에디님: "노란색 표시와 빨간색 글자색은
    #   따로 써줘. 노란색 박스는 그것만, 빨간색은 그것만").
    #   이전엔 노랑 문장 **안에** 그 키워드를 빨강으로 얹었다. 한 덩어리에 강조가 두 겹이면
    #   어디를 보라는 건지 흐려지고, 화면에서도 노랑 위 빨강이라 탁해 보인다.
    #   → 키워드를 번갈아 배분한다: 홀수는 **문장 노랑만**, 짝수는 **키워드 빨강만**.
    #     같은 문장에 둘 다 걸리지 않도록 서로의 구간을 피한다.
    def _overlap(a0, a1, ranges):
        return any(not (a1 <= r0 or a0 >= r1) for r0, r1 in ranges)

    # ★역할을 **길이로** 나눈다. 노랑은 '문장'을, 빨강은 '단어'를 짚는 서식이다
    #   (실측: 번갈아 배분했더니 «전 세계 최초 폭염으로 당일 취소»가 통째로 빨강이 됐다 —
    #    그건 키워드가 아니라 문장이라 노랑이 할 일이었다).
    #   빨강은 **단어급**만 — 12자 이내이면서 어절 2개 이하(«추노가 되어 돌아왔다»는 구절이라 노랑).
    _RED_MAX = 12

    def _is_word(k):
        return len(k) <= _RED_MAX and len(k.split()) <= 2

    short = [k for k in kws if _is_word(k)]
    long_ = [k for k in kws if not _is_word(k)]
    half = max(1, len(kws) // 2)
    red_kws = short[:half]
    yellow_kws = long_ + short[half:]
    # 강점 키워드(위에서 이미 빨강으로 칠한 구간)도 노랑이 피해야 할 대상이다
    red_ranges: dict = {}
    for b in blocks:
        red_ranges[id(b)] = [(s0, e0) for s0, e0, st in b.get("spans", []) if st.get("color")]
    yellow_ranges: dict = {}
    y_done, r_done = [], []

    for kw in yellow_kws:                      # ① 문장 노랑만
        for b in blocks:
            if b.get("type") != "text":
                continue
            idx = b["text"].find(kw)
            if idx < 0:
                continue
            s0, e0 = _sentence_span(b["text"], idx)
            ys = yellow_ranges.setdefault(id(b), [])
            if _overlap(s0, e0, ys) or _overlap(s0, e0, red_ranges.get(id(b), [])):
                continue                       # 이미 강조된 문장 → 다음 블록에서 찾는다
            ys.append((s0, e0))
            b.setdefault("spans", []).append((s0, e0, {"bg": naver.EMPH_YELLOW_BG}))
            y_done.append(kw)
            break

    for kw in red_kws:                         # ② 키워드 빨강만
        for b in blocks:
            if b.get("type") != "text":
                continue
            idx = b["text"].find(kw)
            if idx < 0:
                continue
            if _overlap(idx, idx + len(kw), yellow_ranges.get(id(b), [])):
                continue                       # 노랑 문장 안이면 건너뛴다(겹치기 금지)
            rr = red_ranges.setdefault(id(b), [])
            if _overlap(idx, idx + len(kw), rr):
                continue
            rr.append((idx, idx + len(kw)))
            b.setdefault("spans", []).append(
                (idx, idx + len(kw), {"bold": True, "color": naver.EMPH_RED}))
            r_done.append(kw)
            break
    if y_done or r_done:
        log(f"노랑 문장 {len(y_done)}곳: {y_done}")
        log(f"빨강 키워드 {len(r_done)}곳(노랑과 겹치지 않음): {r_done}")


def _detect_emphasis(folder: str, post_no: str, body: str) -> list[str]:
    """강점 키워드 자동 감지 → 굵게+빨강 강조할 문구 목록.

    강점 이름은 '강점시각화' 에셋 파일명(예: 01_승부_강점시각화.html)에서 뽑고,
    본문에서 '승부(Competition)' 같은 '강점(영문)' 패턴을 찾아 반환.
    """
    assets = posts.find_assets(folder, post_no)
    vis = assets.get("강점시각화") or assets.get("장점") or assets.get("맹점")
    if not vis:
        return []
    m = re.match(r"\d+_(.+?)_(?:강점시각화|장점|맹점)", os.path.basename(vis))
    if not m:
        return []
    strength = m.group(1)
    phrases: list[str] = []
    # '강점(영문)' 패턴 (예: 승부(Competition))
    for mm in re.finditer(re.escape(strength) + r"\([A-Za-z][A-Za-z ]*\)", body):
        if mm.group(0) not in phrases:
            phrases.append(mm.group(0))
    # '강점 재능' 도 있으면 강조
    if f"{strength} 재능" in body and f"{strength} 재능" not in phrases:
        phrases.append(f"{strength} 재능")

    # ★ 연예 글은 프롬프트가 '강점명 1~2번, 갤럽 용어 최소화'를 지시하므로
    #   위의 '강점(영문)'·'강점 재능' 교과서식 표기가 거의 안 나온다 → 강조가 통째로 비어버린다.
    #   그래서 영문 병기가 없어도 '강점명' 자체를 굵게+빨강으로 잡는다.
    #   (이미 '강점(영문)'으로 잡힌 구간과 겹치면 _build_spans에서 뒤 span이 덮으므로 무해)
    if not phrases and re.search(r"(?<![가-힣])" + re.escape(strength) + r"(?![가-힣])", body):
        phrases.append(strength)
    return phrases


_RE_SRC_PROGRAM = re.compile(r"@출처\s*[:：]\s*(.+)")


def _yt_title(vid: str) -> str:
    """oEmbed로 영상 제목 — 키가 필요 없다. 실패하면 빈 문자열."""
    import json as _json
    import urllib.parse as _up
    import urllib.request as _ur
    u = ("https://www.youtube.com/oembed?format=json&url="
         + _up.quote(f"https://www.youtube.com/watch?v={vid}", safe=""))
    try:
        req = _ur.Request(u, headers={"User-Agent": "Mozilla/5.0"})
        with _ur.urlopen(req, timeout=12) as r:
            return (_json.loads(r.read().decode("utf-8", "replace")).get("title") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _yt_date(vid: str):
    """영상 업로드 날짜(datetime.date) — 못 구하면 None."""
    import urllib.request as _ur
    try:
        req = _ur.Request(f"https://www.youtube.com/watch?v={vid}",
                          headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ko"})
        with _ur.urlopen(req, timeout=20) as r:
            h = r.read().decode("utf-8", "replace")
        m = re.search(r'"publishDate":\s*"(\d{4})-(\d{2})-(\d{2})', h)
        return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
    except Exception:  # noqa: BLE001
        return None


def _insert_source_video(blocks: list[dict], body: str, log: Logger) -> None:
    """본문 **맨 아래**에 관련 영상 링크 1개(에디님 2026-08-27 지시).

    ★2026-08-07에 끈 건 **본문 사진 자동캡처**(엉뚱한 회차·다른 기수 화면이 붙었다)이고,
      이건 그것과 다르다 — 캡처하지 않고 **링크 카드 하나**만 맨 아래 붙인다.
    ★그래도 같은 사고가 바로 재현됐다: 33기 광수 글에 **31기** 경수·순자 영상이 붙었다.
      제목 뒤쪽에 «나는솔로»가 들어 있어서 프로그램명만 보고 통과시킨 탓이다.
      → 그래서 **기수와 인물이 둘 다 영상 제목에 있어야** 채택한다.
        («나는 솔로»는 기수마다 광수·순자 같은 **같은 가명**을 쓴다 — 2026-08-03 교훈)
      맞는 게 없으면 **아무것도 붙이지 않는다**. 조용히 넘어가는 편이 틀린 영상보다 낫다.
    """
    hashlines = [l for l in body.splitlines() if l.strip().startswith("#")]
    tags = [w[1:] for w in hashlines[-1].split() if w.startswith("#")] if hashlines else []
    if not tags:
        return
    head = body.splitlines()[0] if body.splitlines() else ""      # '제목: …'
    # 인물 = 해시태그 중 **제목에도 나오는** 이름(프로그램명·기수 태그는 제외)
    #   🔴2026-08-27: «유퀴즈»가 인물로 잡혀 샘킴 글에 **이연복·유방녕** 영상이 붙었다.
    #     프로그램명이 인물 자리를 차지하면 그 프로그램 아무 영상이나 통과한다.
    #     → 프로그램명과 겹치는 태그를 빼고, 남은 것 중 **제목에 가장 먼저 나오는 하나**(주인공)를
    #       영상 제목에 요구한다. «아무거나 하나»로는 또 뚫린다.
    gi = re.search(r"(\d+기)", body)
    season = gi.group(1) if gi else ""
    m = _RE_SRC_PROGRAM.search(body)
    program = re.sub(r"[\'\"‘’“”]", " ", m.group(1)) if m else ""
    # 프로그램명은 짧게: 방송사·시즌·부제를 떼야 검색이 걸린다(«동상이몽 시즌2-너는 내 운명» → «동상이몽»)
    # 공동제작이면 «SBS Plus·ENA '나는 SOLO'»처럼 방송사가 겹쳐 붙는다 → 안 붙을 때까지 반복해 뗀다
    _BCAST = re.compile(r"^(SBS(\s*Plus)?|ENA|MBC|KBS\d?|tvN|JTBC|Mnet|채널A|TV조선)[\s·,]*", re.I)
    program = program.strip()
    while True:
        stripped = _BCAST.sub("", program).strip()
        if stripped == program:
            break
        program = stripped
    program = re.split(r"\s*(시즌|[-–—:]|\d)", program.strip())[0].strip()[:14]
    # 프로그램명과 겹치는 태그(«유퀴즈» ⊂ «유퀴즈온더블럭»)는 인물이 아니다
    pflat = program.replace(" ", "")
    cands = [t for t in tags
             if 2 <= len(t) <= 6 and t in head and not re.search(r"\d", t)
             and not (pflat and (t in pflat or pflat in t))]
    if not cands:
        return
    hero = min(cands, key=head.index)      # 제목에 가장 먼저 나오는 이름 = 주인공
    persons = [hero]
    # ★«나는 솔로» 공식 클립은 제목에 기수를 안 쓴다 — «EP.160»처럼 회차만 쓰거나
    #   «33번지»라고 부른다(SBS Plus 스플스 실측). 그래서 33기 == «33기» 또는 «33번지»로 본다.
    #   기수 요구를 빼면 안 된다: EP.160·EP.144에도 광수·현숙이 나오지만 **전혀 다른 기수**다.
    #   표기는 «33기» 또는 «33번지» 둘만 인정한다.
    #   🔴«//ep12-33»도 33기로 쳤다가 **2023-01-26 영상**이 붙었다 — 그 33은 기수가 아니었다.
    #     제목 숫자로 기수를 추측하지 말 것. 대신 아래 «최근 영상만» 조건으로 한 겹 더 막는다.
    _n = re.sub(r"\D", "", season)
    season_re = re.compile(rf"{_n}\s*(?:기|번지)", re.I) if _n else None
    queries = [" ".join(x for x in [program, season, persons[0]] if x).strip()]
    if season:
        queries.append(" ".join(x for x in [program, season.replace("기", "번지")] if x).strip())
    ids: list[str] = []
    try:
        import celeb_image
        for q_ in queries:
            ids += [v for v in celeb_image._yt_search_video_ids(q_, n=6) if v not in ids]
    except Exception as e:  # noqa: BLE001
        log(f"영상 링크 검색 실패(건너뜀): {str(e)[:50]}")
        return
    q = queries[0]
    for vid in ids[:12]:
        title = _yt_title(vid)
        if not title:
            continue
        flat = title.replace(" ", "")
        if season_re and not season_re.search(title):
            continue                      # 기수가 다르면 다른 사람 이야기다
        # ★최근 방송 이야기를 쓰는 글이다 — 몇 해 전 영상이 붙으면 글 전체가 의심스러워진다.
        d = _yt_date(vid)
        if d and (_dt.date.today() - d).days > 60:
            continue
        if not any(p in flat for p in persons):
            continue                      # 인물이 제목에 없으면 채택하지 않는다
        idx = next((i for i, b in enumerate(blocks) if b["type"] == "hashtags"), len(blocks))
        blocks[idx:idx] = [{"type": "oglink",
                            "url": f"https://www.youtube.com/watch?v={vid}",
                            "title": title[:80]}]
        log(f"영상 링크 1개를 맨 아래 배치: {title[:44]}")
        return
    # 인물명이 제목에 없어도, **기수가 맞고 최근 영상**이면 그 기수 이야기가 맞다
    #   («33기_모솔들의 심야 토크»처럼 공식 클립은 인물명을 안 쓰는 경우가 많다).
    if season_re:
        for vid in ids[:12]:
            title = _yt_title(vid)
            if not title or not season_re.search(title):
                continue
            d = _yt_date(vid)
            if not d or (_dt.date.today() - d).days > 60:
                continue
            idx = next((i for i, b in enumerate(blocks) if b["type"] == "hashtags"), len(blocks))
            blocks[idx:idx] = [{"type": "oglink",
                                "url": f"https://www.youtube.com/watch?v={vid}",
                                "title": title[:80]}]
            log(f"영상 링크 1개를 맨 아래 배치(기수 일치): {title[:40]}")
            return
    log(f"소재와 맞는 영상을 못 찾아 링크 생략(검색어: {q[:40]})")


def _insert_related_links(blocks: list[dict], body: str, current_title: str, log: Logger) -> None:
    """내 블로그의 비슷한 글 3개를 '함께 보면 좋은 글' 링크카드로 @출처 앞에 삽입."""
    blog_id = naver.load_meta().get("blog_id")
    if not blog_id:
        return
    hashlines = [l for l in body.splitlines() if l.strip().startswith("#")]
    kws = [w[1:] for w in hashlines[-1].split() if w.startswith("#")] if hashlines else []
    if not kws:
        return
    try:
        mine = blog_related.fetch_my_posts(blog_id)
        rel = blog_related.pick_related(kws, current_title, mine, n=3)
    except Exception as e:  # noqa: BLE001
        log(f"관련글 수집 실패(건너뜀): {e}")
        return
    if not rel:
        # 🔴키워드가 하나도 안 겹치면 **같은 축의 최신 글**로 채운다(2026-09-16 에디님 지적).
        #   9/16 실측: 9편 중 4편(01·07·08·09)이 «관련글을 찾지 못해 링크 섹션 생략»으로 끝났다.
        #   원인은 매칭 실패가 아니라 구조다 — 그 인물을 **처음 다루는 글**은 이전 제목에
        #   그 해시태그가 있을 리 없다. 링크 섹션이 통째로 빠지면 회유가 끊긴다.
        try:
            rel = blog_related.pick_recent_same_axis(mine, current_title, n=3)
        except Exception:  # noqa: BLE001
            rel = []
        if rel:
            log(f"관련글 키워드 0건 → 같은 축 최신 글 {len(rel)}개로 채움: "
                + " / ".join(r["title"][:18] for r in rel))
    if not rel:
        log("관련글을 찾지 못해 링크 섹션 생략")
        return

    section = [{"type": "subhead", "text": "함께 보면 좋은 글"}]
    for r in rel:
        section.append({"type": "oglink", "url": r["url"], "title": r["title"]})

    # @출처 텍스트 블록 앞에 삽입(없으면 해시태그 앞, 그도 없으면 끝)
    idx = next((i for i, b in enumerate(blocks)
                if b["type"] == "text" and b["text"].lstrip().startswith("@출처")), None)
    if idx is None:
        idx = next((i for i, b in enumerate(blocks) if b["type"] == "hashtags"), len(blocks))
    blocks[idx:idx] = section
    log(f"관련글 {len(rel)}개 링크를 출처 앞에 배치: " + " / ".join(r["title"][:18] for r in rel))


_RE_PHOTO_DESC = re.compile(r"\[사진[^\]\-]*-\s*(.*?)\s*/\s*출처", re.S)


_RE_PHOTO_SRC = re.compile(r"출처\s*[:：]\s*(.+?)\s*\]?\s*$")
# 자기/툴 촬영 신호(자동첨부 대상). 이게 아니면 연예/외부 출처로 보고 자리표시자로 남긴다.
_SELF_SHOT_RE = re.compile(r"직접\s*촬영|해당\s*툴|툴\s*화면|화면\s*캡처|직접\s*제작|본인\s*(촬영|제작)|작업\s*화면")
# 연예/외부 출처 신호(사람이 직접 삽입 — 자동첨부 금지)
_CELEB_SRC_RE = re.compile(r"유튜브|인스타|채널|방송|MBC|SBS|KBS|tvN|JTBC|ENA|Mnet|화보|프로그램|드라마|예능|콘서트|공연|기자회견|@\w")


def _is_celeb_photo(text: str) -> bool:
    """[사진N …/출처: XXX] 마커가 '연예인 장면'인가 → 그렇다면 자동첨부하지 않고 자리표시자로 남긴다.

    연예인 사진은 저작권상·정확성상 에디님이 직접 넣는다(예전 연예+강점 방식). 2026-07-24 지시.
    판정: 출처가 '직접 촬영/툴 화면'이면 자기 자료(자동첨부 O). 유튜브·방송·인스타 등이면 연예(자동첨부 X).
    """
    m = _RE_PHOTO_SRC.search(text or "")
    src = (m.group(1) if m else "").strip()
    if not src:
        return False
    if _SELF_SHOT_RE.search(src):
        return False
    return bool(_CELEB_SRC_RE.search(src))


def _fill_celeb_captures(blocks: list[dict], celeb_idxs: list[int], folder: str,
                         post_no: str, log: Logger) -> int:
    """연예인 [사진N] 자리에 '확보해둔 방송 캡처'를 채운다(2026-08-02 에디님 지시).

    예전엔 저작권·정확성 때문에 자리표시자로 두고 직접 넣었지만(7/24), 이제 생성 단계에서
    유튜브 방송 캡처(`{no}_{kw}_연예캡처N.jpg`)를 확보하므로 그걸 순서대로 꽂는다.
    캡처가 모자라면 남은 자리는 그대로 자리표시자로 둔다(없는 사진을 지어내지 않는다).
    """
    import glob, re as _re
    caps = (glob.glob(os.path.join(folder, f"{post_no}_*_연예캡처*.jpg"))
            + glob.glob(os.path.join(folder, f"{post_no}_*_연예캡처*.png")))
    # 연예캡처2 < 연예캡처10 이 되도록 숫자 기준 정렬(문자열 정렬이면 10이 2보다 앞선다)
    caps.sort(key=lambda p: int((_re.search(r"연예캡처(\d+)", p) or _re.match(r"(0)", "0")).group(1)))
    if not caps:
        return 0
    filled = 0
    for n, i in enumerate(celeb_idxs):
        if n >= len(caps):
            break
        blocks[i] = {"type": "image", "kind": "body", "path": caps[n],
                     "missing": False, "label": f"연예캡처{n+1}"}
        filled += 1
    log(f"연예인 방송 캡처 {filled}장 자동 삽입"
        + (f" (자리 {len(celeb_idxs)}곳 중 {len(celeb_idxs)-filled}곳은 캡처 부족으로 자리표시자 유지)"
           if filled < len(celeb_idxs) else ""))
    return filled


def _title_two_lines(title: str) -> list[str]:
    """제목을 인용구 두 줄로 나눈다 — «이것때문에 많이 싸웠어!? / 고지용 허양임 5년전 방송 보니...»(Tom편집장).

    끊는 자리: ①«!?·?·!·…·...» 뒤 ②쉼표 뒤 ③앞머리 따옴표 인용의 닫는 따옴표 뒤 ④가운데에 가까운 띄어쓰기.
    한쪽이 너무 짧아지면(6자 미만) 다음 방법으로 넘어간다. 못 나누면 한 줄 그대로.
    """
    t = re.sub(r"\s+", " ", (title or "").strip())
    cands = []
    for m in re.finditer(r"(!\?|\?!|\?|!|…|\.\.\.)\s+", t):
        cands.append((t[:m.end()].strip(), t[m.end():].strip()))
    if ", " in t:
        i = t.index(", ")
        cands.append((t[:i + 1], t[i + 2:]))
    m = re.match(r'^(["“\'‘][^"”\'’]{2,40}["”\'’][!?…\.]*)\s+(.+)$', t)
    if m:
        cands.append((m.group(1), m.group(2)))
    for a, b in cands:
        if len(a) >= 6 and len(b) >= 6:
            return [a, b]
    sp = [i for i, c in enumerate(t) if c == " "]
    if sp:
        i = min(sp, key=lambda k: abs(k - len(t) / 2))
        if i >= 6 and len(t) - i - 1 >= 6:
            return [t[:i], t[i + 1:]]
    return [t]


def _fill_grok_photos(blocks: list[dict], grok_dir: str, log: Logger) -> int:
    """그록이 만든 사진(photoN.jpg)을 **같은 번호의** [사진N] 자리에 넣는다(2026-09-11 에디님 지시).

    그록 루틴은 «블로그 임시저장 (데일리텐)/날짜/NN_제목.txt»를 읽고 옆에 «NN_제목/» 폴더를 만든다:
    thumb.jpg · photo1.jpg … · captions.json(«@출처 - 채널명»).
    ★번호로 맞춘다(순서로 맞추지 않는다) — 그록이 한 장을 못 만들어도 뒤 사진이 밀리지 않는다.
    ★사진 밑 출처는 «▲ 출처: 채널명»으로 넣는다. «@출처»로 시작하면 `_RE_SOURCE_LINE`이
      **글 끝 출처 줄**로 오인해 관련글 링크가 첫 사진 밑에 들어간다(`_insert_related_links`).
    없는 번호는 마커를 그대로 둔다(지어내지 않는다).
    """
    import json as _json
    caps: dict = {}
    try:
        with open(os.path.join(grok_dir, "captions.json"), encoding="utf-8") as f:
            caps = {p.get("file", ""): (p.get("caption") or "")
                    for p in (_json.load(f).get("photos") or [])}
    except Exception:  # noqa: BLE001
        pass
    out, filled, missing = [], 0, []
    for b in blocks:
        if b.get("type") == "photo":
            m = re.match(r"\s*\[\s*사진\s*(\d+)", b.get("text") or "")
            n = m.group(1) if m else ""
            path = next((os.path.join(grok_dir, f"photo{n}{e}")
                         for e in (".jpg", ".jpeg", ".png", ".webp")
                         if n and os.path.exists(os.path.join(grok_dir, f"photo{n}{e}"))), "")
            if path:
                cap = re.sub(r"^\s*@?\s*출처\s*[:：\-–—]?\s*", "",
                             caps.get(os.path.basename(path), "")).strip()
                cap = cap.replace("[", "").replace("]", "").strip()   # «이지금 [IU Official]» → 대괄호 없이
                # 출처 줄은 여기서 블록으로 넣지 않고 사진에 달아 둔다 → 업로드 직전에 펼친다
                #   (지금 넣으면 `_apply_photo_subheads`가 «사진 뒤 소주제»로 보고 인용구로 바꾼다 — 실측)
                # ★출처는 **이미지 캡션 칸**에 넣는다(2026-09-13 에디님 지시) — 본문 문단이 아니다.
                out.append({"type": "image", "kind": "body", "path": path, "missing": False,
                            "label": f"그록사진{n}", "caption": f"출처: {cap}" if cap else ""})
                filled += 1
                continue
            missing.append(n or "?")
            # 🔴사진이 없는 자리는 **마커를 «빨강 굵게»로 남긴다**(2026-09-16 에디님 지시).
            #   > "이미지나 사진이 없거나 안 나오면 [사진...] 출처는 있어야 되잖아? 그래야지 내가 보고 이미지 올리지?"
            #
            #   9/14엔 이 자리를 **본문에서 뺐다.** `naver`가 photo 블록을 **그대로 타이핑**하기 때문에
            #   (naver.py의 `t == "photo"`) 마커가 검은 평문으로 박힌 채 임시저장됐고, 9/09엔 같은 모양이
            #   공개 발행까지 나갔다. 그런데 **빼 버리면 에디님이 «어디에 무슨 사진을 넣어야 하는지»를 못 본다** —
            #   9/16 실측: 02편 2/11·03편 2/12가 자리 표시 하나 없이 올라갔다.
            #   → 두 요구를 같이 만족시키는 답은 «지우기»가 아니라 **«본문 글자로 안 보이게 남기기»**다.
            #     빨강 굵게 한 줄이면 에디터에서 바로 걸리고, 그대로 발행할 위험도 9/14 때보다 낮다.
            #   ★블록 타입은 `text`가 아니라 **`marker`**다(`naver`가 빨강 굵게로 타이핑한다).
            #     처음엔 text + 빨강 spans로 넣었는데 **노랑 배경이 덧씌워졌다**(9/16 재생 시험, 03편 사진2) —
            #     pipeline의 서식 단계(노랑 문장·빨강 키워드·인용구·소주제)가 전부 «type == "text"»만
            #     보고 돌기 때문이다. 타입을 가르면 그 단계들이 **구조적으로** 못 건드린다.
            #     대괄호 정리는 블록으로 쪼개기 **전에** 끝나므로 여기서 만든 마커는 그 단계를 지나지 않는다.
            #   ★되돌리려면 `GROK_KEEP_EMPTY_MARKERS = False` — 9/14 동작(본문에서 뺌)으로 돌아간다.
            if GROK_KEEP_EMPTY_MARKERS:
                _t = (b.get("text") or "").strip()
                if _t:
                    out.append({"type": "marker", "text": _t})
            continue
        out.append(b)
    blocks[:] = out
    LAST_GROK_FILL.clear()
    LAST_GROK_FILL.update({"filled": filled, "missing": list(missing),
                           "slots": filled + len(missing)})
    if missing:
        _how = ("빨강 마커로 남겼습니다 — 발행 전에 사진을 넣거나 그 줄을 지우세요"
                if GROK_KEEP_EMPTY_MARKERS else "본문에서 뺐다")
        log(f"그록 사진 {filled}장 삽입 · 🔴사진 없는 자리 {len(missing)}곳"
            f"({', '.join(missing)})은 {_how} — 그록에 추가 요청 대상")
    else:
        log(f"그록 사진 {filled}장 삽입")
    return filled


def _attach_stock_images(blocks: list[dict], workdir: str, log: Logger,
                         folder: str = "", post_no: str = "") -> int:
    """[사진N] 자리표시자를 설명에 맞는 Unsplash/Gemini 이미지로 교체.
    연예인 장면은 확보된 방송 캡처로 채우고, 부족분만 자리표시자로 남긴다."""
    celeb_idxs = [i for i, b in enumerate(blocks)
                  if b.get("type") == "photo" and _is_celeb_photo(b.get("text", ""))]
    if celeb_idxs:
        filled = _fill_celeb_captures(blocks, celeb_idxs, folder, post_no, log) if folder else 0
        if not filled:
            log(f"연예인 사진 {len(celeb_idxs)}곳은 자리표시자로 유지(캡처 없음 — 직접 삽입)")
        # 채워진 자리는 photo가 아니게 되므로 아래 스톡 대상에서 자동 제외된다
        celeb_idxs = [i for i in celeb_idxs if blocks[i].get("type") == "photo"]
    photo_idxs = [i for i, b in enumerate(blocks)
                  if b.get("type") == "photo" and i not in celeb_idxs]
    if not photo_idxs:
        return 0
    descs = []
    for i in photo_idxs:
        m = _RE_PHOTO_DESC.search(blocks[i]["text"])
        descs.append(m.group(1).strip() if m else blocks[i]["text"])
    log(f"본문 이미지 {len(descs)}개 검색어 번역 중(claude -p)…")
    queries = image_finder.translate_queries(descs)
    attached = 0
    # ★웹 구독 이미지는 **한 브라우저 세션에서 일괄 생성**(2026-08-04).
    #   장당 브라우저를 새로 띄우던 방식은 5분27초/장이라 6장에 33분이 걸렸다.
    out_paths = [os.path.join(workdir, f"body_{n+1:02d}.jpg") for n in range(len(photo_idxs))]
    web_ok = [False] * len(photo_idxs)
    try:
        import web_image
        # ★로그아웃된 프로필로 시도하면 장당 2.5분씩 헛되이 태운다(2026-08-04 실측: 6장 15분).
        #   먼저 로그인 여부를 한 번만 확인하고, 아니면 즉시 API/스톡으로 넘어간다.
        #   EDI_NO_WEBIMG=1 이면 아예 건너뛴다(급할 때).
        # 🔴배포판 기본값 EDI_NO_WEBIMG=1 → 아래를 건너뛰고 무료 스톡(Unsplash)으로 채운다.
        #   그록(유료)·ChatGPT 웹 이미지는 뺐다. 제미나이 **웹** 이미지는 로그인한 사람만 선택적으로 쓴다.
        if os.environ.get("EDI_NO_WEBIMG"):
            log("웹 구독 이미지 생략(EDI_NO_WEBIMG) → 무료 스톡/Gemini API 사용")
        else:
            # 제미나이 웹에 로그인된 경우에만 웹 이미지를 만든다(아니면 즉시 스톡으로).
            if web_image.session_alive():
                log(f"본문 이미지 {len(descs)}개 제미나이 웹 생성 중…")
                for k, ok in enumerate(web_image.make_many(descs, out_paths, log=log)):
                    web_ok[k] = ok
            else:
                log("제미나이 웹 로그인 없음 → 무료 스톡(Unsplash)으로 진행")
    except Exception as e:  # noqa: BLE001
        log(f"웹 이미지 일괄 생성 실패 → 스톡 폴백({str(e)[:40]})")
    # 🔴중복 금지(2026-08-31 에디님 지시): "실패해도 재사용은 하지 않는다. 재사용 시 업로드 금지."
    #   폴백 스톡이 같은 검색어에 같은 사진을 돌려줘 한 글에 똑같은 모니터·노트 사진이 반복됐다.
    #   → 파일 해시로 판정해 이미 쓴 그림이면 **그 자리를 비운다**(같은 그림을 또 넣지 않는다).
    import hashlib as _hl

    def _digest(path: str) -> str:
        try:
            with open(path, "rb") as f:
                return _hl.md5(f.read()).hexdigest()
        except Exception:  # noqa: BLE001
            return ""

    _used_digests: set = set()

    def _accept(path: str, label: str) -> bool:
        d = _digest(path)
        if not d:
            return False
        # 🔴마지막 방어선(2026-09-09): 생성이 덜 끝난 '흐린 얼룩'은 어느 경로로 왔든 올리지 않는다.
        #   md5 중복검사로는 안 걸린다(파일은 매번 다르다) — 실제로 예약 발행분에 그대로 나갔다.
        try:
            import image_finder as _if
            if _if.is_broken_image(path):
                log(f"{label} 뭉개진 이미지(생성 미완성) → 버리고 이 자리는 비운다")
                try:
                    os.remove(path)
                except Exception:  # noqa: BLE001
                    pass
                return False
        except Exception:  # noqa: BLE001
            pass
        if d in _used_digests:
            log(f"{label} 앞서 쓴 그림과 동일 → 재사용 금지, 이 자리는 비운다")
            try:
                os.remove(path)
            except Exception:  # noqa: BLE001
                pass
            return False
        _used_digests.add(d)
        return True

    for n, i in enumerate(photo_idxs):
        out_path = out_paths[n]
        q = queries[n] if n < len(queries) else descs[n]
        # 웹 생성이 안 된 자리만 Unsplash/Gemini API로 채운다.
        made = bool(web_ok[n]) if n < len(web_ok) else False
        if made and _accept(out_path, f"본문사진{n+1}"):
            blocks[i] = {"type": "image", "kind": "body", "path": out_path,
                         "missing": False, "label": f"본문사진{n+1}"}
            attached += 1
        elif image_finder.search_download(q, out_path) and _accept(out_path, f"본문사진{n+1}"):
            blocks[i] = {"type": "image", "kind": "body", "path": out_path,
                         "missing": False, "label": f"본문사진{n+1}"}
            attached += 1
        elif image_finder.generate_gemini(descs[n], out_path) and _accept(out_path, f"본문사진{n+1}"):
            # Unsplash에서 못 찾으면 설명대로 Gemini API가 사진을 생성해 대체
            blocks[i] = {"type": "image", "kind": "body", "path": out_path,
                         "missing": False, "label": f"본문사진{n+1}"}
            attached += 1
            log(f"본문사진{n+1} Unsplash 실패 → Gemini 생성으로 대체")
        else:
            # Unsplash·Gemini 모두 실패하면 마커 텍스트를 본문에 남기지 않고 제거(빈 줄 대체)
            blocks[i] = {"type": "blank"}
            log(f"본문사진{n+1} 이미지 없음(Unsplash·Gemini 실패) → 마커 제거")
    log(f"본문 이미지 {attached}/{len(descs)}개 자동 첨부 완료")
    return attached


ENUM_RE = re.compile(r"(첫째|둘째|셋째|넷째|다섯째|여섯째|일곱째|여덟째|아홉째|열째)\s*[,，]")


#: 문장 끝. «…습니다.» 뒤에 공백이 와야 문장 끝으로 본다.
#  닫는 따옴표가 바로 뒤에 오면 인용 안이라 자르지 않는다(«"…했습니다." 그랬더니»).
_SENT_END = re.compile(r'(?<=[다요죠까])\.(?=\s)(?![\s]*["\'”’])')

#: 이 길이를 넘고 문장이 둘 이상이면 나눈다.
#  🔴2026-08-26 에디님: "매번 AI 관련 이야기할 때 **띄어쓰기 없이 너무 길게** 나와.
#    한번 띄어서 시각적으로 잘 보이게 해야 될 거 같아."
#    본문 대부분은 한 문단 한 문장인데 **글 끝 AI 문단만** 서너 문장이 한 덩어리로 뭉친다
#    (본문과 다른 프롬프트 조각에서 나와서다). 폰에서 보면 거기만 벽처럼 보인다.
_PARA_LIMIT = 90


_SENT_TAIL = re.compile(r'[.!?…"\u2019\u201d)\]]\s*$|[다요죠까음함임짐네네요]\.?\s*$')


def _rejoin_broken_lines(blocks: list, log: Logger) -> None:
    """문장 중간에서 끊긴 줄을 되붙인다(2026-08-31 사고).

    생성 지시를 «한 줄 15자»로 준 날, LLM이 그걸 **글자 수 규칙**으로 받아
    따옴표 안까지 잘랐다:
        «"난 계속» / «호감 상대가 두 명이었는데,» / «거기에 계속» / «7기 옥순 님이 있었다."»
    프롬프트는 고쳤지만, 생성기가 또 그러면 발행물이 깨지므로 여기서 한 번 더 막는다.
    판정: 줄이 문장부호로 끝나지 않고 다음 줄이 이어지는 말이면 붙인다.
    """
    out: list = []
    joined = 0
    for b in blocks:
        if b.get("type") != "text":
            out.append(b)
            continue
        t = (b.get("text") or "").strip()
        if not t or t.startswith(("[", "@", "#", "-", "·", "제목:")):
            out.append(b)
            continue
        prev = out[-1] if out and out[-1].get("type") == "text" else None
        pt = (prev or {}).get("text", "").strip()
        if (prev and pt and not pt.startswith(("[", "@", "#", "-", "·"))
                and not _SENT_TAIL.search(pt)          # 앞줄이 문장으로 안 끝났고
                and len(pt) + len(t) <= 90):           # 붙여도 과하게 길지 않으면
            prev["text"] = pt + " " + t
            joined += 1
            continue
        out.append(dict(b))
    if joined:
        blocks[:] = out
        log(f"문장 중간에서 끊긴 줄 {joined}곳을 되붙임")


def _split_long_paragraphs(blocks: list[dict], log: Logger) -> None:
    """긴 문단을 문장 단위로 나눈다(문단마다 한 줄 띄니 눈이 쉰다)."""
    out: list[dict] = []
    changed = 0
    for b in blocks:
        t = b.get("text", "") if b.get("type") == "text" else ""
        # 마커·출처·해시태그·목록은 건드리지 않는다
        if (not t or len(t) <= _PARA_LIMIT
                or t.lstrip().startswith(("[", "@", "#", "-", "·", "제목:"))):
            out.append(b)
            continue
        parts, last = [], 0
        for m in _SENT_END.finditer(t):
            seg = t[last:m.end()].strip()
            if seg:
                parts.append(seg)
            last = m.end()
        tail = t[last:].strip()
        if tail:
            parts.append(tail)
        if len(parts) < 2:
            out.append(b)
            continue
        # ★너무 잘게 쪼개지 않는다 — 짧은 문장 둘은 붙여 둔다(한 줄짜리 문단이 줄줄이 나면 산만하다)
        merged: list = []
        for seg in parts:
            if merged and len(merged[-1]) + len(seg) + 1 <= 46:
                merged[-1] = merged[-1] + " " + seg
            else:
                merged.append(seg)
        for seg in merged:
            out.append({"type": "text", "text": seg})
        changed += 1
    if changed:
        blocks[:] = out
        log(f"긴 문단 {changed}곳을 문장 단위로 나눔(90자 초과)")


def _split_enumerations(blocks: list[dict], log: Logger) -> None:
    """'첫째, … 둘째, …'처럼 한 문단에 몰린 열거를 각각 별도 문단으로 분리
    (문단마다 자동으로 한 줄 띄우므로 눈에 잘 보이게 됨)."""
    out: list[dict] = []
    changed = 0
    for b in blocks:
        if b.get("type") != "text":
            out.append(b)
            continue
        text = b["text"]
        starts = [m.start() for m in ENUM_RE.finditer(text)]
        if len(starts) < 2:
            out.append(b)
            continue
        if starts[0] > 0:
            pre = text[:starts[0]].strip()
            if pre:
                out.append({"type": "text", "text": pre})
        for i, s in enumerate(starts):
            e = starts[i + 1] if i + 1 < len(starts) else len(text)
            seg = text[s:e].strip()
            if seg:
                out.append({"type": "text", "text": seg})
        changed += 1
    if changed:
        blocks[:] = out
        log(f"열거(첫째·둘째…) {changed}곳을 줄 나눔")


def _spread_insight_visuals(blocks: list[dict], log: Logger) -> None:
    """강점 시각화 3종(강점시각화·장점·맹점 카드)을 한곳에 몰지 않고 흩어 배치.
    강점시각화 → 첫 소주제 앞(키워드 설명 뒤), 장점 → 표 뒤, 맹점 → 대주제(그림자) 뒤."""
    def pop_card(label):
        for i, b in enumerate(blocks):
            if b.get("type") == "image" and b.get("kind") == "card" and b.get("label") == label:
                return blocks.pop(i)
        return None

    viz = pop_card("강점시각화")
    merit = pop_card("장점카드")
    blind = pop_card("맹점카드")
    if not any([viz, merit, blind]):
        return

    def ins(block, pred, after=False):
        if block is None:
            return
        idx = next((i for i, b in enumerate(blocks) if pred(b)), None)
        if idx is None:
            blocks.append(block)
        else:
            blocks.insert(idx + 1 if after else idx, block)

    ins(viz, lambda b: b.get("type") == "quote" and b.get("style") == "small", after=False)
    ins(merit, lambda b: b.get("type") == "table_paste", after=True)
    ins(blind, lambda b: b.get("type") == "quote" and b.get("style") == "big", after=True)
    log("강점 시각화 3종을 본문에 흩어 배치(시각화→장점→맹점)")


_GREET_RE = re.compile(
    r"^\s*(안녕하세요|안녕하십니까|반갑습니다).*$|"                               # 인사
    r"^\s*여러분.*$|"                                                          # '여러분…'(뒤 조사 '의' 등 포함)
    r"^\s*오늘은[,\s].*$|"                                                     # '오늘은, …'
    r"^\s*.{0,25}(에디|저)\s*입니다[.!]?\s*$|"                                  # '…에디/저입니다'
    r".*(정리해|전해|소개해|안내해|전달해|알려)\s*드리는\s*\S{1,12}(입니다|이에요|예요|에요)[.!~]*\s*\S{0,3}$|"  # '~해 드리는 OO입니다/이에요'
    r".*블로거\s*\S{1,12}(입니다|이에요|예요|에요)[.!~]*\s*\S{0,3}$|"                 # '블로거 OO입니다'
    # 지어낸 페르소나 자기소개: '…OO이에요/예요'로 끝나는 짧은 줄(이모지 허용).
    #  실측: '안녕하세요~ 햄찡이에요 🐹'(08-02), '…정리해 드리는 엘라입니다'(08-01).
    r"^\s*.{0,20}(이에요|예요|에요|입니다)[.!~]*\s*[\U0001F300-\U0001FAFF☀-➿]+\s*$")


#: 마크다운 강조·머리글. 네이버 에디터는 이걸 해석하지 않아 **별표가 그대로 화면에 찍힌다**.
_MD_BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.S)
_MD_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)([^*\n]+?)(?<!\s)\*(?![\w*])")
_MD_HEAD = re.compile(r"(?m)^\s{0,3}#{1,6}\s+")


def _move_table_midway(body: str, log=lambda m: None, limit: float = 0.72,
                       lo: float = 0.0, target: float = 0.48) -> str:
    """표가 글 끝쪽에 몰려 있으면 **본문 한가운데**로 옮긴다.

    ★2026-08-23 에디님 지적: "표가 마지막에 나오는데, 중간에 나오는 게 체류시간을 높이지 않을까?"
      맞다. 표는 정보 밀도가 높아 **스크롤을 붙잡는 장치**인데, 끝에 있으면 거기까지 안 읽고
      나간 독자는 아예 못 본다. 특히 정보형(등장인물 표)은 **그 표가 글의 목적**이다.
      실측(8/21~23 원고 17편): 평균 65% 지점, 정보형은 85~89%.

    ★프롬프트에도 위치를 지시했지만 LLM이 흘린다 → 코드가 마지막 관문(이 저장소의 이중 방어 관례).
    ★**이미 앞·중반에 있으면 건드리지 않는다.** 표 앞뒤 문장이 "아래 표로 정리했습니다"처럼
      이어지는 경우가 있어, 함부로 옮기면 글이 어색해진다. 심하게 뒤쪽인 것만 교정한다.
    """
    lines = body.splitlines()
    idxs = [i for i, l in enumerate(lines) if l.strip() in ("[표]", "[표1]")]
    if len(idxs) != 1:
        return body                     # 표가 없거나 여러 개면 손대지 않는다
    i = idxs[0]
    # 위치 계산은 '내용이 있는 줄' 기준(빈 줄이 많아 단순 인덱스는 왜곡된다)
    solid = [k for k, l in enumerate(lines) if l.strip()]
    if not solid:
        return body
    rank = sum(1 for k in solid if k < i) / len(solid)
    if lo <= rank < limit:
        return body                     # 이미 허용 구간 → 그대로 둔다
    # 목표 지점으로 옮긴다. 단, 사진 마커·해시태그·출처 줄 바로 옆은 피한다.
    target_solid = solid[int(len(solid) * target)]
    while target_solid > 0 and (
            re.match(r"^\s*\[(사진|커넥트)", lines[target_solid])
            or lines[target_solid].lstrip().startswith(("#", "@출처", "출처"))):
        target_solid -= 1
    row = lines.pop(i)
    if target_solid > i:
        target_solid -= 1
    lines.insert(target_solid, row)
    # 앞뒤로 빈 줄을 보장해 파서가 표를 독립 줄로 인식하게 한다
    out = "\n".join(lines)
    out = re.sub(r"\n*(\[표1?\])\n*", r"\n\n\1\n\n", out)
    log(f"표 위치 교정: {rank * 100:.0f}% → {target * 100:.0f}% 지점")
    return re.sub(r"\n{3,}", "\n\n", out)


def _strip_markdown(body: str, log=lambda m: None) -> str:
    """본문에 남은 마크다운 기호를 걷어낸다(발행 직전 백스톱).

    🔴2026-08-14 에디님 지적(발행분 스크린샷): 인용구 박스 안에 «**공개된 줄거리입니다.**»가
      별표째 찍혔다. 소주제도 «**강해라 (주새벽)**» 형태로 그대로 올라갔다.
      생성 프롬프트에 '마크다운 금지'가 있는데도 LLM이 계속 넣는다 —
      실측: 8/13 원고 7줄, 8/14 원고 11줄. 프롬프트로는 못 막으니 코드에서 지운다.

    ★인용구 변환보다 **먼저** 돌아야 한다. 나중에 하면 이미 별표째 인용구 박스에 들어간다.
    ★굵게 표시 자체가 필요하면 파이프라인의 노랑 하이라이트·인용구가 그 역할을 한다
      (네이버 서식으로 들어가므로 화면에 기호가 남지 않는다).
    """
    before = body
    body = _MD_BOLD.sub(lambda m: m.group(1) or m.group(2) or "", body)
    body = _MD_ITALIC.sub(r"\1", body)
    body = _MD_HEAD.sub("", body)
    # ★줄머리 장식 기호도 여기서 한 번에 뗀다(2026-08-17 에디님 지적: 인용구에 «■ 방영 정보»).
    #   예전엔 `_apply_orphan_subheads` 안에서만 지웠는데, 소주제가 **사진 뒤 경로**
    #   (`_apply_photo_subheads`)로 인용구가 되면 그 제거를 안 거쳐 기호가 그대로 남았다.
    #   → 경로마다 지우지 말고 **본문 단계에서 한 번** 지운다.
    body = re.sub(r"(?m)^[ \t]*[◆◇▶▷■□●○★☆※▪▫◾◽]+[ \t]*", "", body)
    # 🔴**줄머리 이모지도 뗀다**(2026-08-26 에디님 지적).
    #   실측: 09_이혼숙려캠프 소주제가 «⚖️ 등급이 왜 올랐나» «🏛️ 방심위 회의에서 나온 말들»
    #   «🤔 반대 의견도 있었습니다» 였고, 인용구 박스로 바뀌면서 깨진 글자처럼 보였다.
    #   에디님: "이게 갑자기 왜 들어가는 거야?" — **홈판 공식이 시킨 게 아니라 못 거른 것이다.**
    #   기존 장식기호 목록은 «◆▶■» 같은 문자만 봐서 이모지가 통과했다.
    body = re.sub("(?m)^[ \t]*["
                  "\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF"
                  "\U0001F1E6-\U0001F1FF\U0000FE0F\U00002190-\U000021FF]+[ \t]*", "", body)
    # 🔴2026-09-10 에디님 지시: **이모티콘을 넣지 마라.**
    #   프롬프트에서 «이모지는 소제목에 한두 개만»을 지웠지만(그게 원인이었다) LLM은 계속 넣는다
    #   → 이 저장소 관례대로 **코드에서 한 번 더 지운다.**
    #   ⚠️`♥`·`♡`는 **빼지 않는다** — 「경수♥22기 옥순」처럼 연예 기사 표준 표기라
    #     지우면 제목·본문이 어색해진다(실측: 9/8 원고 2편이 이 표기를 쓰고 있었다).
    body = re.sub("[\U0001F000-\U0001FAFF\U00002600-\U00002664\U00002667-\U000027BF"
                  "\U00002B00-\U00002BFF\U0001F1E6-\U0001F1FF\U0000FE0F]+", "", body)
    body = re.sub(r"(?m)[ \t]{2,}", " ", body)      # 이모지 자리에 남은 공백 정리
    # 짝이 안 맞아 남은 별표(«**하나.» 처럼 한쪽만 남은 경우)도 지운다
    body = re.sub(r"\*{2,}", "", body)
    if body != before:
        n = len(re.findall(r"\*\*|__|(?m)^\s{0,3}#{1,6}\s", before))
        log(f"마크다운 기호 제거({n}곳) — 네이버는 별표를 그대로 노출한다")
    return body


def _strip_greeting_intro(body: str, log=lambda m: None) -> str:
    """본문 첫 부분의 인사·자기소개 줄을 제거한다(홈판 위너는 인사로 시작 안 함).
    '제목:' 줄은 보존하고, 그 아래 첫 텍스트 줄들 중 인사/자기소개만 걷어낸다."""
    lines = body.splitlines()
    out, removed, scanned = [], 0, 0
    for ln in lines:
        s = ln.strip()
        if re.match(r"^\s*제목\s*[:：]", ln) or not s:
            out.append(ln)
            continue
        # ★도입부 앞 8줄까지 훑는다(2026-08-02): 후킹 2~3줄을 먼저 쓴 뒤 인사를 끼우는
        #   패턴이 있었다("안녕하세요~ 햄찡이에요 🐹"가 3번째 줄). 첫 줄만 보면 놓친다.
        if scanned < 8:
            scanned += 1
            if removed < 3 and _GREET_RE.match(s):
                removed += 1
                continue
        out.append(ln)
    if removed:
        log(f"도입 인사·자기소개 {removed}줄 제거(홈판 규칙)")
    return "\n".join(out)


def process_post(post_no: str, log: Logger, publish: bool = False, folder: str | None = None,
                 category: str = "", reserve_at=None, skip_images: bool = False,
                 grok_dir: str | None = None, archive_only: bool = False) -> dict:
    """원고 한 편을 네이버에 올린다.

    skip_images=True 면 이미지를 **붙이지 않고 `[사진N]` 마커를 그대로 둔다.**
    ★언제 쓰나: 본문이 «출처: 직접 촬영»이라고 말하는 글(현장 취재·수업 후기처럼 실제로
      찍은 사진이 있어야 하는 글). 그 자리에 AI 생성 이미지를 넣으면 **본문이 거짓이 된다.**
      마커만 남겨두고 에디님이 실제 사진을 넣어 발행한다(연예편과 같은 방식).
    """
    folder = folder or config.resolve_date_folder()
    if not folder:
        return {"ok": False, "message": "원고 폴더를 찾을 수 없습니다."}
    date_str = os.path.basename(folder)

    post = posts.get_post(folder, post_no)
    if not post:
        return {"ok": False, "message": f"{post_no}편을 폴더에서 찾지 못했습니다."}

    cat = posts.category(post["body_path"])
    log(f"원고 읽는 중({cat}): {os.path.basename(post['body_path'])}")
    with open(post["body_path"], encoding="utf-8") as f:
        body = f.read()
    # ★보이지 않는 문자 제거(2026-08-02): LLM이 문단 간격용으로 제로폭 공백(U+200B)만 든 줄을
    #   38개 넣었고, strip()으로 안 지워져 '빈 줄'이 아닌 소주제로 잡혀 '내용을 입력하세요'
    #   빈 인용박스가 45곳 생겼다. 파싱 전에 원본에서 걷어낸다.
    _zw = body.count("​") + body.count("﻿")
    if _zw:
        body = body.replace("​", "").replace("﻿", "")
        log(f"보이지 않는 문자(제로폭 공백) {_zw}개 제거")
    # ★LLM이 남긴 편집 지시용 라벨 줄 제거(2026-08-02): '[요약 3줄]'이 본문에 그대로 노출됐다.
    #   [사진N]·[표]·[커넥트]는 실제 마커라 남긴다.
    _lab = re.compile(r"^\s*\[(?!사진|표|커넥트)[^\]]{1,20}\]\s*$", re.M)
    _hits = len(_lab.findall(body))
    if _hits:
        body = _lab.sub("", body)
        log(f"편집 라벨 줄 {_hits}개 제거(예: [요약 3줄])")
    # ★[[경험 보태기: …]] 같은 편집용 자리표시자 제거(2026-08-06 자동 발행 전환).
    #   프롬프트로 금지해도 LLM이 남길 때가 있는데, 공개 발행되면 그대로 노출된다.
    # ★[사진N]·[표]·[커넥트] 마커가 문장 끝/중간에 붙어 있으면 파서(줄 전체 매칭)가 못 잡아
    #   본문에 대괄호 텍스트가 그대로 노출된다(2026-08-06 실측: "…씁니다. [사진7 - …]").
    #   → 마커 앞뒤를 줄바꿈으로 떼어 독립된 줄로 만든다.
    import gen_common as _GC
    body = _GC.flatten_marker_brackets(body)   # «[사진… '이지금 [IU Official]' …]» → 안쪽 대괄호 제거(2026-09-15)
    _fix = len(re.findall(r"(?<!\n)\s*\[(?:사진|표|커넥트)[^\]]*\]", body))
    if _fix:
        body = re.sub(r"[ \t]*(\[(?:사진|표|커넥트)[^\]]*\])[ \t]*", r"\n\n\1\n\n", body)
        body = re.sub(r"\n{3,}", "\n\n", body)
        log(f"본문에 붙어 있던 마커 {_fix}개를 독립 줄로 분리")
    _slot = len(re.findall(r"\[\[[^\]]*\]\]", body))
    if _slot:
        body = re.sub(r"\s*\[\[[^\]]*\]\]\s*", " ", body)
        log(f"편집용 슬롯 {_slot}개 제거(자동 발행 대비)")
    # 🔴대괄호는 마커 말고는 **한 글자도 올리지 않는다**(2026-09-15 에디님: "[......] 이 대괄호가 있는 건 다 지워야 돼").
    #   05편에서 끊긴 마커의 꼬리 «' / 유튜브 검색: … ]»가 사진 밑에 10곳 남았고,
    #   본문 문장에도 «이지금 [IU Official]»·«'[IU TV] 죄목…'»이 그대로 들어갔다.
    #   ①마커 꼬리처럼 생긴 줄(«/ 유튜브 검색:»·«/ 출처:»로 시작해 `]`로 끝남)은 통째로 버리고
    #   ②그 밖의 줄에 남은 `[`·`]`는 글자만 뺀다(«[IU TV] 죄목» → «IU TV 죄목»).
    _keep_marker = re.compile(r"^\s*\[(?:사진|표|커넥트)[^\]]*\]\s*$")
    _marker_tail = re.compile(r"^\s*['’\"]?\s*/\s*(?:유튜브\s*검색|출처|영상)\s*[:：].*\]\s*$")
    _tails = _stripped = 0
    _lines = []
    for _ln in body.split("\n"):
        if _keep_marker.match(_ln):
            _lines.append(_ln)
        elif _marker_tail.match(_ln):
            _tails += 1
        elif "[" in _ln or "]" in _ln:
            _stripped += 1
            _lines.append(_GC.strip_brackets(_ln) if _ln.strip() else _ln)
        else:
            _lines.append(_ln)
    if _tails or _stripped:
        body = "\n".join(_lines)
        log(f"대괄호 정리: 끊긴 마커 꼬리 {_tails}줄 삭제 · 본문 대괄호 {_stripped}줄 제거")
    body = _strip_markdown(body, log)         # 네이버는 마크다운을 안 읽는다 — 별표가 그대로 노출된다
    # 🔴strpia(AI·자동화)는 **홈판 위너를 재서** 구간을 정했다(2026-09-18 에디님 규칙 7:
    #   「중간이 좋을 것 같은데, 이건 직접 홈판 글을 보고 판단해서 작업했으면 좋겠어.」)
    #   IT·전체 위너 24편 실측 — 표를 쓴 글 4편, 첫 표 위치 0%·9%·21%·38%(**전부 앞 40% 안**).
    #   예전 기준(40~55%, 72% 넘어야 교정)은 재서 나온 게 아니라 추론이었고, 우리 글은 41~70%였다.
    #   → 20~40% 구간, 벗어나면 30%로. 맨 앞(0~9%)은 에디님 말대로 도입을 막으니 피한다.
    #   ⚠️표본 4편 — 한 달 뒤 다시 잴 것. 데일리텐은 그쪽 창 기준(72%/48%)을 그대로 둔다.
    if getattr(config, "BLOG", "") == "strpia":
        body = _move_table_midway(body, log, limit=0.40, lo=0.20, target=0.30)
    else:
        body = _move_table_midway(body, log)      # 표가 끝에 몰리면 중간으로(체류시간)
    body = _strip_greeting_intro(body, log)   # 홈판 필수: 인사·자기소개 도입 제거

    workdir = config.work_dir_for(date_str, post_no)

    # 제목: 원고 상단에 '제목:' 줄이 있으면(생성기가 만든 후킹 제목) 그대로 사용,
    # 없으면 인기글 패턴으로 AI 생성.
    _tm = re.search(r"(?m)^\s*제목\s*[:：]\s*(.+)$", body[:600])
    _cand = _tm.group(1).strip() if _tm else ""
    # 🔴 발행 직전 백스톱: LLM 메타응답이 제목으로 나가는 것을 여기서 한 번 더 막는다.
    #    2026-08-12 쇼핑 04편이 「제목만 출력하라는 요청이네요.」라는 제목으로 **공개 발행됐다.**
    #    제목을 만드는 경로가 여럿(title_hook·_make_title·생성기별 프롬프트)이라 최종 관문이 필요하다.
    import gen_common as _G
    if _cand and _G.looks_meta(_cand):
        log(f"[경고] 원고 제목이 LLM 메타응답으로 보임 → 버리고 새로 만듭니다: {_cand[:40]}")
        _cand = ""
    if _cand:
        title = _cand
        log(f"원고 후킹 제목 사용: {title}")
    else:
        title = _make_title(body, folder, post_no, log)
        if _G.looks_meta(title):
            # 여기서 멈추면 '조용한 실패'가 아니라 로그에 남는 실패다(제목 없는 글 발행보다 낫다).
            raise RuntimeError(f"제목이 계속 메타응답입니다(발행 중단): {title[:40]}")
    # 강점인사이트는 제목 앞에 시리즈 순번 '[N. 테마] ' 추가
    if cat == "insight":
        prefix = _insight_prefix(folder, post_no)
        if prefix and not title.lstrip().startswith("["):
            title = prefix + title
            log(f"제목에 시리즈 순번 추가 → {title}")

    log("HTML 카드/표를 이미지로 렌더링 중…")
    html_assets = posts.find_assets(folder, post_no)
    png_map, rlogs = render_assets.render_assets(html_assets, workdir)
    for l in rlogs:
        log("  " + l)
    # ★그록이 만든 대표사진(2026-09-11) — 글마다 폴더의 thumb.jpg를 맨 위 대표사진으로 쓴다.
    if grok_dir:
        _gt = next((os.path.join(grok_dir, f"thumb{e}") for e in (".jpg", ".jpeg", ".png", ".webp")
                    if os.path.exists(os.path.join(grok_dir, f"thumb{e}"))), "")
        if _gt:
            png_map["썸네일"] = _gt
            log(f"그록 대표사진 사용: {os.path.basename(_gt)}")

    # 본문은 원문 그대로 파싱(마커→블록). 제목은 위에서 만든 것을 사용.
    _, blocks = parse_post.parse_rewritten(body, png_map)

    # 비연예 글은 [사진N]을 Unsplash/Gemini 이미지로 자동 교체(연예글은 방송캡처라 자리표시자 유지)
    # AI 실전 글(ai.flag)도 이미지 자동첨부 대상(직접 촬영 자리를 비워두지 않음)
    import glob as _glob
    is_ai = bool(_glob.glob(os.path.join(folder, f"{post_no}_*_ai.flag"))) if folder else False
    if grok_dir:
        _fill_grok_photos(blocks, grok_dir, log)
    elif skip_images:
        log("이미지 자동첨부 생략 — [사진N] 마커를 그대로 둡니다(실제 사진을 직접 넣을 글)")
    elif cat != "celeb" or is_ai:
        _attach_stock_images(blocks, workdir, log, folder=folder, post_no=post_no)
    else:
        # 순수 연예글: 스톡 이미지는 안 붙이되, 확보해둔 '실제 방송 캡처'는 [사진N]에 채운다
        # (2026-08-02 에디님: 연예 글에 사진 10~13장). 캡처가 없으면 자리표시자 그대로.
        _celeb_idxs = [i for i, b in enumerate(blocks)
                       if b.get("type") == "photo" and _is_celeb_photo(b.get("text", ""))]
        if _celeb_idxs and folder and CELEB_INSERT_CAPTURES:
            if not _fill_celeb_captures(blocks, _celeb_idxs, folder, post_no, log):
                log(f"연예인 사진 {len(_celeb_idxs)}곳은 자리표시자로 유지(캡처 없음)")
        elif _celeb_idxs:
            log(f"연예 사진 {len(_celeb_idxs)}곳은 마커 그대로 — 그록이 만듭니다")

    # 표: 이미지 대신 '텍스트 표'로 붙여넣기(더 크고 선명, 복사 가능)
    #   🔴2026-08-27: 이 자리는 `kind == "table"` 블록을 찾았는데 **그런 블록을 만드는 코드가
    #     어디에도 없어** 한 번도 실행되지 않았다. 그래서 `_표.html`은 만들어지기만 하고
    #     본문엔 한 번도 안 붙었다. 대신 원고가 **마크다운 표**(«| 항목 | 내용 |»)를 쓴 글은
    #     그 기호가 그대로 발행됐다(샘킴·이계인 편 실측 — 형광펜까지 칠해져 나갔다).
    #   → 마크다운 표 줄을 찾아 통째로 걷어내고 그 자리에 표를 넣는다.
    # 🔴Tom편집장 «완전판» 1편(`NN_tom.flag` 내용이 full) — 레퍼런스 글과 **똑같은 모양**으로 올린다
    #   (2026-09-19 에디님: "10편 중 한 편은 완전 똑같이 하자. 사진도 많이 넣어서").
    #   실측(Tom 3편): 대표사진 → 제목 인용구 1개 → [짧은 줄 3~6개 → 사진 1~2장] 반복 · 가운데 정렬 ·
    #   **굵게·색·노랑 강조 0 · 표 0 · 소제목 0 · 관련글 0 · 끝 출처 줄 0**. 그래서 우리 서식 단계를 전부 건너뛴다.
    #   ★특히 소제목 변환을 꼭 꺼야 한다 — Tom은 문장 중간에서 줄을 끊어 마침표 없는 짧은 줄이 많은데,
    #     `_apply_orphan_subheads`가 그걸 전부 «소제목»으로 보고 인용구 박스로 바꾼다.
    tom_full = False
    if cat == "celeb" and folder:
        try:
            tom_full = open(os.path.join(folder, f"{post_no}_tom.flag"), encoding="utf-8").read().strip() == "full"
        except OSError:
            pass
    if tom_full:
        log("[Tom 완전판] 표·소제목·자동 인용구·강조색·관련글·끝 출처 줄을 넣지 않는다")
        # ★빈 줄 없이 이어진 짧은 줄들은 **한 덩어리**로 묶는다. 업로드는 블록마다 빈 줄을 하나씩 넣는데
        #   (naver: 문단 끝 Enter 두 번), Tom은 «짧은 줄 2~5개 → 빈 줄» 리듬이다. 안 묶으면 줄마다 벌어진다.
        #   덩어리 안 줄바꿈은 «\n» → `_type_rich`가 Enter 한 번(빈 줄 없는 새 문단)으로 친다.
        _m, _n0 = [], len(blocks)
        for b in blocks:
            if (b.get("type") == "text" and _m and _m[-1].get("type") == "text"
                    and not b.get("spans") and not _m[-1].get("spans")):
                _m[-1] = {"type": "text", "text": _m[-1]["text"] + "\n" + b["text"]}
            else:
                _m.append(dict(b))
        blocks[:] = _m
        log(f"[Tom 완전판] 이어진 줄 묶기: 블록 {_n0} → {len(blocks)}")
    if html_assets.get("표") and not tom_full:
        placed = False
        for i, b in enumerate(blocks):
            if b.get("type") == "image" and b.get("kind") == "table":
                blocks[i] = {"type": "table_paste", "html_path": html_assets["표"]}
                log("표를 텍스트 표(붙여넣기)로 전환")
                placed = True
                break
        if not placed:
            start = end = None
            for i, b in enumerate(blocks):
                if b.get("type") == "text" and (b.get("text") or "").lstrip().startswith("|"):
                    if start is None:
                        start = i
                    end = i
                elif start is not None:
                    break                      # 표는 붙어 있는 줄들이다 — 첫 덩어리만
            if start is not None and end - start >= 1:
                blocks[start:end + 1] = [{"type": "table_paste", "html_path": html_assets["표"]}]
                log(f"본문의 마크다운 표 {end - start + 1}줄을 표로 교체")
    else:
        # 표 파일이 없는 글이라도 «|» 기호가 그대로 나가면 안 된다 → 줄글로 편다.
        out, hit = [], 0
        for b in blocks:
            t = (b.get("text") or "").strip()
            if b.get("type") == "text" and t.startswith("|"):
                cells = [c.strip() for c in t.strip("|").split("|")]
                if all(set(c) <= set("-: ") for c in cells):   # |---|---| 구분선은 버린다
                    hit += 1
                    continue
                out.append({**b, "text": " — ".join(c for c in cells if c)})
                hit += 1
                continue
            out.append(b)
        if hit:
            blocks[:] = out
            log(f"표 파일이 없어 마크다운 표 {hit}줄을 줄글로 폈다")

    # 인사이트: 강점 시각화 3종을 한곳에 몰지 않고 본문에 흩어 배치
    if cat == "insight":
        _spread_insight_visuals(blocks, log)

    # 썸네일 배치: 항상 맨 위 대표사진으로(네이버가 첫 이미지를 대표사진으로 잡음).
    # (강점 카드가 있던 시절엔 그 앞에 뒀으나, 셀럽 실용정보 전환으로 강점 카드가 없어져 맨 위로 통일)
    thumb = png_map.get("썸네일")
    if thumb:
        tb = {"type": "image", "kind": "thumb", "path": thumb, "label": "대표썸네일", "missing": False}
        blocks.insert(0, tb)
        log("썸네일을 맨 위 대표사진으로 배치")

    # 열거(첫째·둘째…)는 각각 줄 나눠 눈에 잘 보이게
    if not tom_full:
        _split_enumerations(blocks, log)
        _rejoin_broken_lines(blocks, log)     # ★완전판은 끊은 줄을 다시 잇지 않는다(그게 Tom 문체다)
        _split_long_paragraphs(blocks, log)   # 긴 문단(특히 글 끝 AI 이야기)을 문장으로 나눈다

        # '1단계, 2단계…' 머리줄 → 인용구2(라인형)로 깔끔하게
        _apply_step_quotes(blocks, log)

        # 사진 뒤 소주제 → 따옴표(66박스) 인용. quote_select보다 먼저 돌려서
        # 소주제가 quote로 바뀌면, 평문만 고르는 quote_select가 중복 선택하지 않는다.
        _apply_photo_subheads(blocks, log)

        # 사진 뒤가 아닌 곳에 홀로 남은 소주제 → 라인형 인용(평문 파편 방지)
        _apply_orphan_subheads(blocks, log)

    # ★유튜브 채널 홍보는 모든 글에서 뺀다(2026-08-02 에디님: "에디 채널 이야기 넣지 말라니까").
    #  전엔 연예편만 제거하고 AI·쇼핑편엔 썸네일까지 붙였는데, 그것도 빼라는 지시.
    _strip_youtube_cta(blocks, log)
    # '@출처 : 직접 운영 경험' 류도 뺀다(내 경험 글엔 불필요). 단 연예글은 방송/매체 출처가 필요해 유지.
    if cat != "celeb" or tom_full:           # 완전판도 끝 출처 줄이 없다(출처는 사진 캡션에 있다)
        _n = len(blocks)
        blocks[:] = [b for b in blocks
                     if not (b.get("type") == "text"
                             and re.match(r"^\s*@?\s*출처\s*[:：]", b.get("text") or ""))]
        if len(blocks) < _n:
            log(f"'@출처' 줄 {_n - len(blocks)}개 제거")

    # 중간중간 가독성 인용(질문/반전/강조) — AI가 본문 문장 선정 → 인용구 변환
    # (단, 열거 항목에는 인용을 넣지 않음)
    try:
        picks = [] if tom_full else quote_select.select_quotes(body, max_n=4)
        n = quote_select.apply_quotes(blocks, picks) if picks else 0
        if n:
            log(f"가독성 인용 {n}곳 추가(질문/반전/강조 자동 선정)")
    except Exception as e:  # noqa: BLE001
        log(f"가독성 인용 건너뜀: {e}")

    log(f"파싱 완료: 블록 {len(blocks)}개 (본문 원문 유지)")

    # 처리 결과 미리보기 저장
    with open(os.path.join(workdir, "제목.txt"), "w", encoding="utf-8") as f:
        f.write(title + "\n")

    # 출처 표기를 '@출처 : 매체명'으로 통일.
    # (_insert_related_links가 '@출처'로 시작하는 블록을 찾아 그 앞에 링크를 넣으므로 반드시 먼저 실행)
    _normalize_source_line(blocks, log)

    if not tom_full:
        # '함께 보면 좋은 글' 관련글 링크 카드를 출처 앞에 삽입
        _insert_related_links(blocks, body, title, log)
        _insert_source_video(blocks, body, log)

        # 서식 스팬 구성: 강점=굵게+빨강(모든 등장), 중요문장=노랑배경+키워드굵게(첫 등장)
        _build_spans(blocks, folder, post_no, body, log)

    # 🔴글 끝 출처에 **사진 출처(유튜브 채널)**를 함께 적는다(2026-09-12 에디님: "출처는 확실하게
    #   남겨줘. @출처 : 한국경제TV 이거 말고, 유튜브 출처 다 만들어야 돼").
    #   기사 매체만 적으면 사진이 어디서 왔는지 글에 없다. 그록 captions.json에 채널명과 영상 번호가 있다.
    #   ⚠️**영상 주소는 본문에 넣지 않는다** — 네이버가 링크 카드로 바꿔 문장을 두 동강 낸다(2026-08-17 사고).
    #     주소는 그록 폴더의 «사진출처.txt»에 초 단위 위치까지 적어 둔다(클릭하면 그 장면).
    if grok_dir and not tom_full:
        _credit_photo_sources(blocks, grok_dir, log)

    # 🔴Tom편집장 방식 실험 편(`NN_tom.flag`)은 **대표사진 바로 밑에 제목을 인용구로** 둔다(2026-09-19).
    #   레퍼런스 실측: 대표사진 → 제목 인용구(두 줄) → 본론. 4편 모두 같은 구조였다.
    #   ★서식 단계가 **다 끝난 뒤**에 넣는다 — 앞에서 넣으면 인용구 자동 선택이 본문 첫 문장까지 인용구로
    #     바꿔 **인용구가 두 개 연달아** 붙었다(재생 시험). 바로 뒤가 인용구면 평문으로 되돌린다.
    #   ★최종 제목으로 만든다 — 제목 교체·③재작성이 다 끝난 뒤라 파일 제목과 어긋나지 않는다.
    if cat == "celeb" and folder and title and os.path.exists(os.path.join(folder, f"{post_no}_tom.flag")):
        _at = 1 if (blocks and blocks[0].get("type") == "image" and blocks[0].get("kind") == "thumb") else 0
        _nx = next((i for i in range(_at, len(blocks)) if blocks[i].get("type") != "blank"), None)
        if _nx is not None and blocks[_nx].get("type") == "quote":
            blocks[_nx] = {"type": "text", "text": blocks[_nx].get("text", "")}
            # 완전판은 바로 뒤 줄과 한 덩어리였다(첫 줄이 인용구로 빠져 있어 묶기에서 떨어졌다)
            if tom_full and _nx + 1 < len(blocks) and blocks[_nx + 1].get("type") == "text" \
                    and not blocks[_nx + 1].get("spans"):
                blocks[_nx]["text"] += "\n" + blocks.pop(_nx + 1)["text"]
        _q = "\n".join(_title_two_lines(title))
        blocks.insert(_at, {"type": "quote", "style": "default", "nstyle": "default", "text": _q})
        log(f"[Tom 방식] 제목 인용구 도입: {_q.replace(chr(10), ' / ')}")

    # (옛 방식) 사진 밑에 «▲ 출처: …» 문단을 따로 넣던 코드는 **뺐다**(2026-09-13) —
    #   에디님 지시대로 출처는 이미지 **캡션 칸**에 들어간다(`naver._type_caption`).

    # 🔴연예 글은 새벽에 **네이버에 올리지 않고 파일만** 쓴다(2026-09-11 에디님).
    #   "처음에 네이버에 임시저장을 할 필요가 없네? 폴더에 글을 올려놓으면 그록이 이미지 뽑을 거고,
    #    넌 그걸 가지고 임시저장을 하면 되네." → 사진 없는 임시저장본이 매일 쌓이지 않고,
    #    에디터를 여는 횟수도 절반이 된다. 올리는 건 run_grok_insert.py가 사진과 함께 한 번만.
    if archive_only:
        path = _archive_draft(title, blocks, folder, post_no, log)
        return {"ok": bool(path), "title": title, "notes": [],
                "message": "파일만 저장(네이버에는 그록 사진과 함께 나중에 올림)" if path else "파일 저장 실패"}

    action = "공개 발행" if publish else "임시저장"
    log(f"네이버 스마트에디터로 {action}을 시작합니다…")
    # ★연예 글만 가운데정렬(2026-08-31 에디님 지시). 홈판 연예 위너의 짧은 문단 글이
    #   예외 없이 가운데정렬이었다 — 14자/96% 글은 211문단이 전부 가운데였다.
    _align = "center" if cat == "celeb" else ""
    result = naver.save_draft(title, blocks, png_map.get("썸네일"), log, publish=publish,
                              category=category, reserve_at=reserve_at, align=_align,
                              ai_mark=(cat != "celeb" or is_ai))   # 연예 사진은 방송 캡처 → AI 표기 X

    result.setdefault("notes", [])
    result["title"] = title
    # 그록 사진을 끼워 다시 올린 경우엔 파일을 덮어쓰지 않는다 — 그록이 읽은 원본이라 그대로 둔다.
    if result.get("ok") and not grok_dir:
        _archive_draft(title, blocks, folder, post_no, log)
    return result


#: 연예 글에 방송 캡처를 끼울 것인가. 🔴2026-09-11 에디님: "너가 이미지는 직접 넣지 마. 그록이 모두 만들 거야."
#   폴더에 옛 캡처 파일(`_연예캡처N`)이 남아 있어도 끼우지 않는다 — 마커만 올린다.
# 🔴그록 사진이 없는 [사진N] 자리를 **본문에 빨강 마커로 남긴다**(2026-09-16 에디님 지시).
#   False로 두면 9/14 동작(본문에서 뺌)이다. `_fill_grok_photos` 주석 참고.
GROK_KEEP_EMPTY_MARKERS = True
# 마지막 `_fill_grok_photos` 결과 — 러너가 «사진이 절반도 안 찼다» 알림에 쓴다
#   (`naver.LAST_CHECK_NET_ERROR`와 같은 관례).
LAST_GROK_FILL: dict = {}

CELEB_INSERT_CAPTURES = False

#: 네이버에 올린 글을 **올린 그대로** 남기는 곳(2026-09-11 에디님 지시).
#: 임시저장·단계 신호가 쌓이는 폴더 — **패키지 안**에 둔다(수강생 PC 어디서나 동작).
DRAFT_ARCHIVE = os.path.join(config.BASE_DIR, "임시저장")


def _blocks_to_text(blocks: list) -> str:
    """네이버에 넣은 블록을 사람이 읽는 텍스트로 되돌린다(사진 마커는 그대로 둔다)."""
    out: list[str] = []
    for b in blocks:
        t = b.get("type")
        if t == "blank":
            out.append("")
        elif t in ("text", "quote", "quote2", "subhead", "photo", "marker", "hashtags"):
            # marker = 그록 사진이 아직 없는 [사진N] 자리(빨강으로 올라간다) — 파일에도 마커 그대로 남긴다
            out.append((b.get("text") or "").strip())
        elif t == "image":
            if b.get("kind") == "thumb":
                out.append("[대표사진 - 썸네일 첨부됨]")
            else:
                out.append(f"[사진 - 첨부됨: {os.path.basename(b.get('path') or '')}]")
        elif t == "table_paste":
            try:
                html = open(b.get("html_path") or "", encoding="utf-8").read()
                rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S)
                for r in rows:
                    cells = [re.sub(r"<[^>]+>|\s+", " ", c).strip()
                             for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r, re.S)]
                    out.append(" | ".join(c for c in cells if c))
            except Exception:  # noqa: BLE001
                out.append("[표]")
        elif t == "oglink":
            out.append(f"관련글: {b.get('title') or b.get('url') or ''}")   # 대괄호 없이 — 코덱스·그록이 이 파일을 읽는다
        elif t == "connect":
            out.append(f"[커넥트 - {b.get('query') or ''}]")
    text = "\n\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def _credit_photo_sources(blocks: list, grok_dir: str, log: Logger) -> None:
    """글 끝 «@출처» 줄에 **사진 출처(유튜브 채널)**를 붙이고, 영상 주소는 파일로 남긴다.

    🔴2026-09-12 에디님: "출처는 확실하게 남겨줘. «@출처 : 한국경제TV» 이거 말고, 유튜브 출처 다 만들어야 돼."
      기사 매체만 적으면 **사진이 어디서 왔는지 글에 없다.** 그록 `captions.json`에 채널명과
      영상 번호(`yt:ID`)·초(`ts`)가 들어 있으니 그걸 쓴다.
    ⚠️**주소는 본문에 절대 넣지 않는다**(2026-08-17 사고: 네이버가 본문 URL을 링크 카드로 바꾸며
      문장을 두 동강 냈다). 주소는 그록 폴더의 «사진출처.txt»에 적는다 — 초 단위 위치까지 붙여
      클릭하면 그 장면으로 바로 간다.
    """
    import json as _json
    try:
        with open(os.path.join(grok_dir, "captions.json"), encoding="utf-8") as f:
            photos = _json.load(f).get("photos") or []
    except Exception:  # noqa: BLE001
        return
    chans, lines = [], []
    for p in photos:
        ch = re.sub(r"^\s*@?\s*출처\s*[:：\-–—]?\s*", "", (p.get("caption") or "")).strip()
        ch = ch.replace("[", "").replace("]", "").strip()
        if ch and ch not in chans:
            chans.append(ch)
        vid = re.sub(r"^yt:", "", (p.get("source") or "")).strip()
        if vid:
            ts = int(float(p.get("ts") or 0))
            lines.append(f"{p.get('file','')}  {ch}  https://youtu.be/{vid}"
                         + (f"?t={ts}" if ts else ""))
    if not chans:
        return
    credit = "사진 " + " · ".join(chans[:6])
    done = False
    for b in blocks:
        if b.get("type") == "text" and re.match(r"^\s*@?\s*출처\s*[:：]", b.get("text") or ""):
            if "사진" not in b["text"]:
                b["text"] = f"{b['text'].rstrip()} / {credit}"
            done = True
            break
    if not done:                      # 출처 줄이 없으면 해시태그 앞에 새로 넣는다
        idx = next((i for i, b in enumerate(blocks) if b.get("type") == "hashtags"), len(blocks))
        blocks.insert(idx, {"type": "text", "text": f"@출처 : {credit}"})
    log(f"출처에 사진 출처 {len(chans)}곳 추가: {credit[:60]}")
    if lines:
        try:
            with open(os.path.join(grok_dir, "사진출처.txt"), "w", encoding="utf-8") as f:
                f.write("사진별 원본 영상(클릭하면 그 장면). 본문에는 주소를 넣지 않는다.\n\n"
                        + "\n".join(lines) + "\n")
        except Exception:  # noqa: BLE001
            pass


def _archive_draft(title: str, blocks: list, folder: str | None, post_no: str, log) -> str:
    """네이버에 저장한 글을 날짜별 폴더에 파일로 남긴다(2026-09-11 에디님 지시).

    에디님: "내일부터 블로그 임시저장에 돌리는 글은 모두 파일도 똑같은 것으로 저장해줘.
      날짜별로 폴더 만들어서. 그걸로 그록에서 사진 만들게 할 거야."
    ★원고 파일(`_복붙용.txt`)을 복사하면 안 된다 — 업로드 직전에 제목 교체·인사말/기호/이모지 제거·
      표 변환이 일어나서 **네이버에 올라간 글과 다르다.** 그래서 실제로 올린 블록에서 다시 쓴다.
    ★사진 마커(`[사진N - 장면 / 출처 …]`)는 그대로 남긴다 — 그록이 그 설명으로 사진을 만든다.
    날짜는 원고 폴더(gen_YYYYMMDD) 기준 — 새벽 배치 글이 그날 폴더로 간다. 실패해도 업로드는 그대로다.
    """
    try:
        m = re.search(r"gen_(\d{4})(\d{2})(\d{2})", folder or "")
        day = (f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m
               else __import__("datetime").date.today().isoformat())
        d = os.path.join(DRAFT_ARCHIVE, day)
        os.makedirs(d, exist_ok=True)
        safe = re.sub(r'[\\/:*?"<>|\n]', "", title).strip()[:50] or "제목없음"
        # 같은 편을 다시 올리면 옛 파일을 지우고 새로 쓴다(편 번호로 찾는다)
        for fn in os.listdir(d):
            if fn.startswith(f"{post_no}_") and fn.endswith(".txt"):
                os.remove(os.path.join(d, fn))
        path = os.path.join(d, f"{post_no}_{safe}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"제목: {title}\n\n" + _blocks_to_text(blocks))
        log(f"   파일로도 저장 → {path}")
        return path
    except Exception as e:  # noqa: BLE001
        log(f"   [경고] 파일 저장 실패(업로드는 정상): {str(e)[:80]}")
        return ""
