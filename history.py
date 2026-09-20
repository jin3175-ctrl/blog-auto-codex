#!/usr/bin/env python3
"""발행 이력 기반 중복 방지 (2026-08-10 신설).

에디님 지적: "이전에 했던 내용이 계속 중복된다."
실측(최근 40편)으로 확인된 중복의 정체는 '주제'가 아니라 **제목 틀과 인물**이었다.

  · `AI한테 ~시켰더니/물었더니/맡겼더니` 형식이 9/40편(22%).
    8/6은 3편 전부(통신비·정부지원금·사진정리), 8/5도 3편(글감·주가·다이어트)이 같은 틀.
  · 연예는 인물이 돌고 돈다 — 옥순×3, 나는솔로×3, 광수×2. 상투어 '결국'×3, '술렁'×2.

원인: ①주제 중복 검사가 `used` 리스트의 **정확 문자열 비교**뿐이라 틀·인물 반복을 못 잡는다.
      ②연예 `exclude_persons`가 **한 번 실행 안에서만** 유효해 어제 다룬 인물이 오늘 또 나온다.
      ③생성기가 '이미 발행한 제목'을 아예 모른 채 제목을 짓는다.

그래서 **블로그에 실제로 올라간 제목**을 읽어(세션 불필요, 공개 API) 프롬프트에 금지 목록으로
넣고, 생성된 제목이 최근 것과 겹치면 걸러낸다.
"""
from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.parse
import urllib.request

import config

#: 🔴어느 블로그의 최근 제목을 볼지. config에서 받는다(2026-09-08 두 블로그 분리).
#  ⚠️여기가 고정이면 strpia 글의 제목을 뽑을 때 **데일리텐의 연예 제목 60개**가
#    "내가 최근 쓴 글"로 프롬프트에 들어가 AI 글 제목이 연예 결로 끌려간다.
BLOG_ID = getattr(config, "EXPECT_BLOG_ID", "")
_LIST_URL = ("https://blog.naver.com/PostTitleListAsync.naver?blogId={bid}&viewdate="
             "&currentPage={page}&categoryNo=&parentCategoryNo=&countPerPage=30")
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
CACHE = os.path.join(config.WORK_DIR, "recent_titles.json")
CELEB_USED = os.path.join(config.WORK_DIR, "celeb_used.json")
CAT_CELEB_NO = "10"          # 연예이슈강점 카테고리 번호

# 제목 유사도 계산에서 뺄 흔한 말(이게 겹쳐도 중복이 아니다)
_STOP = set("""그리고 그런데 하지만 정말 진짜 이제 결국 다들 요즘 오늘 저는 제가 내가 나도 한번
이거 그거 봤더니 했더니 시켰더니 물었더니 봤습니다 합니다 있습니다 됩니다 뭐가 어떻게 이유 방법
정리 후기 근황 공개 사실 지금 처음 마지막 때문 대해 위해 통해 라고 하는 있는 되는""".split())


def _fetch(page: int) -> str:
    req = urllib.request.Request(_LIST_URL.format(bid=BLOG_ID, page=page), headers={"User-Agent": _UA})
    return urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "ignore")


_MEM: dict = {}          # 한 번 실행 안에서는 재조회하지 않는다(편마다 네트워크 왕복 방지)


def recent_posts(limit: int = 60, log=print) -> list[dict]:
    """최근 발행 글 [{date, cat, title}] — 로그인 불필요. 실패 시 캐시로 폴백."""
    if _MEM.get("rows"):
        return _MEM["rows"][:limit]
    rows: list[dict] = []
    try:
        for page in range(1, limit // 30 + 2):
            raw = _fetch(page)
            for m in re.finditer(r'"logNo":"(\d+)".*?"title":"(.*?)","categoryNo":"(\d*)"'
                                 r'.*?"addDate":"(.*?)"', raw, re.S):
                rows.append({"logNo": m.group(1),
                             "title": html.unescape(urllib.parse.unquote_plus(m.group(2))),
                             "cat": m.group(3), "date": m.group(4)})
            if len(rows) >= limit:
                break
            time.sleep(0.3)
        rows = rows[:limit]
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False)
    except Exception as e:  # noqa: BLE001
        log(f"[중복방지] 발행 이력 수집 실패({str(e)[:50]}) → 캐시 사용")
        try:
            with open(CACHE, encoding="utf-8") as f:
                rows = json.load(f)[:limit]
        except Exception:  # noqa: BLE001
            rows = []
    if rows:
        _MEM["rows"] = rows
    return rows


def recent_titles(limit: int = 60, log=print) -> list[str]:
    """최근 발행 제목만."""
    return [r.get("title", "") for r in recent_posts(limit, log) if r.get("title")]


#: 조사·어미. 이걸 떼지 않으면 '정부지원금이' ≠ '정부지원금,' 이 되어 재탕을 놓친다(실측).
_PARTICLE = re.compile(r"(에서|으로|에게|한테|처럼|보다|까지|부터|이나|이라|라고|은|는|이|가|을|를|의|에|로|와|과|도|만|나)$")


def _norm(w: str) -> str:
    """꼬리 조사를 떼어 같은 낱말로 모은다(정부지원금이 → 정부지원금)."""
    while len(w) > 2:
        w2 = _PARTICLE.sub("", w)
        if w2 == w or len(w2) < 2:
            break
        w = w2
    return w


def _tokens(t: str) -> set:
    t = re.sub(r"[^가-힣A-Za-z0-9 ]", " ", t or "")
    return {_norm(w) for w in t.split() if len(w) > 1 and w not in _STOP} - _STOP


def too_similar(cand: str, titles: list[str], threshold: float = 0.5) -> str | None:
    """cand가 최근 제목 중 하나와 threshold 이상 겹치면 그 제목을 반환(아니면 None)."""
    a = _tokens(cand)
    if not a:
        return None
    # 4자 이상 핵심어(제습기·정부지원금 같은 소재어)는 제목 문자열에 그대로 박혀 있으면 겹친 것으로 본다.
    keys = {w for w in a if len(w) >= 4}
    for t in titles:
        b = _tokens(t)
        if not b:
            continue
        hit = set(a & b) | {k for k in keys if k in t}
        if len(hit) / min(len(a), len(b)) >= threshold:
            return t
    return None


#: 반복되기 쉬운 제목 틀. (이름, 정규식) — 최근 제목에서 몇 번 쓰였는지 세어 금지 목록을 만든다.
_PATTERNS = [
    ("AI한테 ~시켰더니/물었더니 형식", r"AI한테.{0,14}(더니|봤다|시켜|시켰)"),
    ("AI로 ~하는 법 형식", r"AI로 .{0,12}(하는 법|만드는 법)"),
    ("다들 ~인데/했는데 형식", r"다들.{0,16}(는데|한데)"),
    ("~해봤습니다/써봤습니다 형식", r"(해|써|만들어|돌려)봤"),
    ("결국 ~ 형식", r"결국"),
    ("~술렁/발칵 형식", r"(술렁|발칵)"),
    ("숫자+개/가지 나열형", r"\d+\s*(개|가지)\b"),
]


def banned_patterns(titles: list[str], min_hits: int = 2) -> list[str]:
    """최근 제목에서 min_hits회 이상 쓰인 틀 = 이번엔 쓰지 말 것."""
    out = []
    for name, pat in _PATTERNS:
        n = sum(1 for t in titles if re.search(pat, t))
        if n >= min_hits:
            out.append(f"{name} (최근 {n}회 사용)")
    return out


#: 이번 실행에서 방금 만든 제목들. 배치는 한 프로세스에서 8편을 만드는데, 편마다 독립적으로
#  제목을 뽑아서 **서로를 모른다**. 그래서 같은 날 같은 틀이 겹쳤다(2026-08-17 실측: '딴판이었습니다' 3편).
_SESSION_TITLES: list = []


def note_title(title: str) -> None:
    """생성기가 제목을 확정할 때 등록한다 → 뒤에 만드는 편이 이걸 피한다."""
    t = (title or "").strip()
    if t and t not in _SESSION_TITLES:
        _SESSION_TITLES.append(t)


def overused_tails(titles: list[str], min_hits: int = 2) -> list[str]:
    """제목 **마무리 표현**이 몇 번 반복됐는지 센다.

    🔴2026-08-17 에디님 지적("이 두개는 제목이 왜 이렇게 비슷해? 조회수도 안 나오고"):
      「…직접 해보니 **딴판이었습니다**」「…먼저 시켜보니 **딴판이었습니다**」
      「…AI가 찾은 날은 **딴판이었습니다**」 — AI 실전 3편이 같은 꼬리였다(조회수 0·2·2).
      `too_similar`는 **내용어**로 비교하니 부업/40대/성수기가 달라서 안 걸렸고,
      `_PATTERNS`는 **손으로 적은 고정 목록**이라 새 상투어를 모른다.
      → 꼬리 표현을 **자동으로** 세서 금지 목록에 넣는다. 사람이 목록을 갱신하지 않아도 된다.
    """
    import collections
    cnt: collections.Counter = collections.Counter()
    for t in titles:
        w = re.sub(r"[…·,\-–—]", " ", t or "").split()
        if len(w) >= 2:
            cnt[" ".join(w[-2:])] += 1          # 끝 2어절 = 마무리 표현
        if w:
            cnt[w[-1]] += 1                     # 끝 1어절(서술어)도 본다
    out = []
    for k, v in cnt.most_common():
        if v < min_hits or len(k) < 3:
            continue
        # 흔한 명사 마무리('정리', '총정리')는 정보형 글의 검색 키워드라 막지 않는다
        if re.search(r"정리|총정리|관계도|등장인물|줄거리|몇부작", k):
            continue
        out.append(f"{k} ({v}회)")
    return out[:6]


def with_session(titles: list[str]) -> list[str]:
    """발행 이력 + **이번 실행에서 방금 만든 제목**을 합친다(같은 배치 안 중복 방지)."""
    return list(_SESSION_TITLES) + list(titles or [])


def prompt_block(titles: list[str], head: int = 25) -> str:
    """제목 프롬프트에 그대로 끼울 '중복 금지' 블록."""
    if not titles:
        return "(발행 이력 없음)"
    ban = banned_patterns(titles)
    s = "[최근 발행한 제목 — 이것들과 같은 소재·같은 틀·같은 상투어를 쓰지 말 것]\n"
    s += "\n".join(f"- {t}" for t in titles[:head])
    if ban:
        s += "\n\n[★최근에 너무 많이 쓴 틀 — 이번엔 금지]\n" + "\n".join(f"- {b}" for b in ban)
    tails = overused_tails(titles)
    if tails:
        s += ("\n\n[★★이미 남용한 '마무리 표현' — 이번엔 절대 쓰지 말 것]\n"
              + "\n".join(f"- …{t}" for t in tails)
              + "\n같은 뜻이라도 **끝맺음을 완전히 다르게** 해라. 매번 같은 꼬리로 끝나면 "
                "독자에게 '또 그 글'로 보여서 클릭이 안 된다(실측: 같은 꼬리 3편 조회수 0~2).")
    if ban or tails:
        s += "\n같은 뜻이라도 **다른 문장 구조**로 쓸 것(질문형·대화체·수치 제시·비교형 등으로 갈아탈 것)."
    return s


# ── 도입부 반복 방지 (2026-09-09 신설) ──────────────────────────────────
#: 🔴에디님 지적: "처음에 다 아니잠깐으로 시작을 하고 있어?"
#   실측 — 9/9 배치 8편 중 **4편(50%)**이 «아니 잠깐.»으로 시작했다.
#   9/6·9/7·9/8은 0편이었으니 어느 날 갑자기 한 도입에 쏠린 것이다.
#   원인: 제목에는 배치 안 중복 방지(_SESSION_TITLES)가 있는데 **도입부에는 없었다.**
#   편마다 독립적으로 글을 만들어 서로의 첫 줄을 모른다 → 같은 날 같은 문장으로 시작한다.
#   ⚠️도입 «공식»은 매일 홈판에서 새로 뽑는 게 맞다. 막을 것은 공식이 아니라 **같은 문장**이다.
_SESSION_OPENINGS: list = []


def opening_of(body: str) -> str:
    """본문에서 첫 실질 문장(제목·마커 줄 제외)을 뽑는다."""
    for ln in (body or "").splitlines():
        t = ln.strip()
        if not t or t.startswith("[") or t.startswith("제목:"):
            continue
        return t
    return ""


def _norm_open(t: str) -> str:
    return re.sub(r"[\s\.!?…\"“”'‘’]", "", t or "")[:14]


def note_opening(body_or_line: str) -> None:
    """생성기가 본문을 확정할 때 첫 문장을 등록한다 → 뒤 편이 이걸 피한다."""
    t = opening_of(body_or_line) if "\n" in (body_or_line or "") else (body_or_line or "").strip()
    if t and t not in _SESSION_OPENINGS:
        _SESSION_OPENINGS.append(t)


def opening_taken(body: str) -> bool:
    """이번 배치에서 **이미 쓴 도입**과 같은 문장으로 시작하는가."""
    o = _norm_open(opening_of(body))
    return bool(o) and any(_norm_open(x) == o for x in _SESSION_OPENINGS)


def opening_ban_block() -> str:
    """본문 프롬프트에 끼울 '이 도입은 쓰지 말 것' 블록."""
    if not _SESSION_OPENINGS:
        return ""
    return ("\n\n[★오늘 이미 쓴 도입 — **같은 문장으로 시작하지 말 것**]\n"
            + "\n".join(f"- {t}" for t in _SESSION_OPENINGS[-8:])
            + "\n첫 줄은 완전히 다른 방식으로 연다(장면·수치·인용·질문 등 서로 다르게).\n"
              "실측: 한 배치 8편 중 4편이 같은 문장으로 시작한 날이 있었다 — 독자에겐 '또 그 글'이다.")


# ── 연예 인물 반복 방지 ────────────────────────────────────────────────
#: 나는솔로 계열 가명 + 자주 나오는 프로그램/상담가. 제목에서 이 단어가 보이면 '그 인물을 다뤘다'고 본다.
_CELEB_WORDS = ("영수 영식 영철 광수 상철 영호 정수 영자 정숙 영숙 순자 현숙 옥순 국화 "
                "이호선 오은영 서장훈 박하선 진태현 이동건 데프콘 이이경 송해나").split()
_CELEB_PROGRAMS = ("나는솔로", "나솔사계", "나솔", "이혼숙려캠프", "이숙캠", "솔로지옥",
                   "모솔N돌싱", "모솔연애", "돌싱N모솔",
                   "오은영 리포트", "오은영리포트", "결혼 지옥", "결혼지옥",
                   "미운 우리 새끼", "무엇이든 물어보살")


#: '나는 솔로' 계열 가명. 기수마다 같은 이름이 반복되고 **매주 새 회차**가 나온다.
_NASOL_ALIAS = set("영수 영식 영철 영호 광수 상철 경수 동수 정수 "
                   "영자 정숙 영숙 순자 현숙 옥순 영옥 국화".split())

#: 🔴나는솔로 출연자의 제외 창(일). 프로그램이 **주 1회** 방송이라 열흘을 잠그면
#   한 사람을 열흘에 한 번밖에 못 쓴다 — 방송 주기보다 잠금이 길다(2026-09-03 에디님 지적:
#   "어제 방송이 됐으니까, 나는솔로 인물별로 글이 나와야 되는 거 아냐?").
#   실측: 9/3 배치에서 33기 영수·영식·영호·상철·현숙·정숙·순자가 전부 잠겨
#   **연예 8편 중 나는솔로가 2편**뿐이었다(나는솔로는 편당 287회로 제일 두꺼운 축인데).
#   → 같은 날 중복만 막고 다음 날은 연다. **같은 사연 재탕은 story_seen이 따로 막는다.**
NASOL_DAYS = 1
#: 🔴**«기수+가명»으로 적힌 출연자**(«28기 영자»·«7기 옥순»)는 **5일** 잠근다(2026-09-19 에디님:
#   "요즘 너무 똑같은 거를 계속 쓰고 있어. 그러니까 조회수가 안 나오잖아").
#   1일 창이면 다음 날 바로 풀려서, 일주일(9/12~19, 68편)에 **28기 영자 6번 · 7기 옥순 6번 ·
#   31기 경수 4번 · 33기 현숙 4번 · 33기 영식 3번 · 33기 영수 3번**이 나갔다.
#   같은 소재 글은 한 편만 뜬다(9/4 실측: 같은 커플 3편 → 5,734 · 28 · 23회)는 것과 겹쳐 조회수를 깎았다.
#   ★5일인 이유 — 방송은 **주 1회**(33기 수요일 · 나솔사계 목요일)다. 5일이면 **방송 다음 날마다
#     그 사람이 다시 열리고**(9/3 에디님 지적을 그대로 지킨다), 방송 사이에 재탕하는 것만 막는다.
#   ★가명 **단독**(«옥순»)은 종전대로 1일이다 — 그걸 5일 잠그면 프롬프트 제외 목록에 «옥순»이 떠서
#     LLM이 **모든 기수의 옥순**을 피한다(기수가 다르면 다른 사람이다).
NASOL_PERSON_DAYS = 5
#: ★**방영 중 기수**(run_ai_daily.NASOL_CURRENT)는 날짜 수가 아니라 **«방송이 나가면 다시 연다»**.
#   5일 창이면 일요일에 쓴 33기 현숙이 목요일(수요일 방송 다음 날)에도 막힌다 — 9/3 에디님 지시
#   «방송 다음 날엔 인물별로 써야 한다»를 깬다. → 마지막 본방(수 22:30) **이후에 쓴 것만** 잠근다.
#   결과: 방영 중 기수 출연자는 **방송 한 번에 한 편**이다.
NASOL_AIR_WEEKDAY, NASOL_AIR_HOUR = 2, 22      # 월=0 → 수요일 22시(본방 22:30)


def _last_nasol_air_ts(now: float | None = None) -> float:
    """가장 최근 나는솔로 본방 시각(초)."""
    import datetime as _dt
    t = _dt.datetime.fromtimestamp(now or time.time())
    back = (t.weekday() - NASOL_AIR_WEEKDAY) % 7
    air = (t - _dt.timedelta(days=back)).replace(hour=NASOL_AIR_HOUR, minute=30, second=0, microsecond=0)
    if air > t:
        air -= _dt.timedelta(days=7)
    return air.timestamp()


def _nasol_current() -> str:
    try:
        from run_ai_daily import NASOL_CURRENT
        return NASOL_CURRENT
    except Exception:  # noqa: BLE001
        return ""


def _post_age_days(date_str: str) -> float:
    """발행 목록의 날짜 표기('3시간 전' / '2026. 9. 1.')를 '며칠 전'으로.

    ★모르는 표기는 0(오늘)으로 본다 — 모를 때는 **덜 쓰는 쪽**이 안전하다(중복 방지 우선).
    """
    d = (date_str or "").strip()
    if not d or re.match(r"\d+\s*(분|시간)\s*전", d) or d in ("방금 전", "오늘"):
        return 0.0
    if d.startswith("어제"):
        return 1.0
    m = re.match(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})", d)
    if m:
        from datetime import date as _date
        try:
            y, mo, da = (int(x) for x in m.groups())
            return float((_date.today() - _date(y, mo, da)).days)
        except Exception:  # noqa: BLE001
            return 0.0
    return 0.0


def _looks_nasol_person(name: str) -> bool:
    """'나는 솔로 출연자'로 볼 이름인가 — 가명 단독이거나, 가명+프로그램/기수 표기."""
    n = (name or "").replace(" ", "")
    if n in _NASOL_ALIAS:
        return True
    if not any(a in n for a in _NASOL_ALIAS):
        return False
    return bool(re.search(r"나는솔로|나솔|나는SOLO|\d{1,2}기", n, re.I))


def recent_celeb_names(days: int = 10, log=print) -> set:
    """최근 연예 글에서 다룬 인물·프로그램 집합(제목 기반 + 저장 이력 병합)."""
    names: set = set()
    # 🔴제목 기반 검사에 **기간이 없었다**(2026-09-03). `days=10`은 저장 이력에만 걸리고,
    #   여기서는 최근 연예글 60편(≈일주일치)에 한 번이라도 나온 가명을 통째로 잠갔다.
    #   방송이 주 1회인데 잠금이 일주일이라 다음 회차를 쓸 창이 영영 안 열렸다.
    for r in recent_posts(60, log):
        if r.get("cat") != CAT_CELEB_NO:
            continue
        t = r.get("title", "")
        age = _post_age_days(r.get("date", ""))
        for w in _CELEB_WORDS:
            if w in t and age < (NASOL_DAYS if w in _NASOL_ALIAS else days):
                names.add(w)
        for p in _CELEB_PROGRAMS:
            if p in t and age < days:
                names.add(p)
    try:
        with open(CELEB_USED, encoding="utf-8") as f:
            saved = json.load(f)
        now = time.time()
        _cur, _air = _nasol_current(), _last_nasol_air_ts(now)
        for n, ts in saved.items():
            # 나는솔로 가명이 들어간 항목은 짧은 창을 쓴다(«유튜브 채널 김영옥»처럼
            # 실명에 우연히 겹치는 건 제외 — 가명 단독이거나 프로그램·기수가 같이 있을 때만).
            if _looks_nasol_person(n) and _cur and _cur in n.replace(" ", ""):
                if ts >= _air:                      # 방영 중 기수: 마지막 본방 이후에 쓴 것만 잠근다
                    names.add(n)
                continue
            lim = ((NASOL_PERSON_DAYS if re.search(r"\d{1,2}\s*기", n) else NASOL_DAYS)
                   if _looks_nasol_person(n) else days)
            if ts >= now - lim * 86400:
                names.add(n)
    except Exception:  # noqa: BLE001
        pass
    return {n for n in names if n and not _is_recurring_subject(n)}


#: 나는솔로 계열 가명. 기수마다 반복되므로 **기수 없이 이름만으로는 차단하지 않는다**
#  (33기 영숙을 썼다고 26기 영숙까지 막으면 나솔 소재가 통째로 사라진다).
_NASOL_ALIAS = set("""
영숙 옥순 정숙 현숙 순자 영자 영식 영수 영호 상철 광수 경수 종수 국화 정식
""".split())


def _is_recurring_subject(name: str) -> bool:
    """'매일 다시 써야 하는 축'이라 제외 목록에 넣으면 안 되는 이름인가.

    🔴2026-08-14 사고: 그날 연예 3편이 «홈판 연예 이슈 선정 실패»로 통째로 날아갔다.
      `recent_celeb_names`가 **1순위 소재와 방송사까지** '이미 다룬 인물'로 넘겨서다 —
      제외 목록에 `나는솔로`·`나솔`·`나솔사계`·`이혼숙려캠프 라면 부부`·`이호선`·`오은영`·
      `MBC에브리원`·`SBS플러스`가 들어갔고, 그날 랭킹 32건 중 그 프로그램 기사 8건이
      전부 배제돼 **LLM이 "고를 게 없다"**고 판단했다(3연속 실패).
      1순위 소재는 트래픽 엔진이라 매일 다뤄야 한다. 겹치면 안 되는 건 **개별 인물·회차**다.
    """
    # 'ENA·SBS Plus 나는 SOLO 사계'처럼 영문 표기로 오면 1순위 매칭이 빗나간다 → 표기를 통일한다
    n = (name or "").replace(" ", "").replace("SOLO", "솔로").replace("Solo", "솔로")
    if not n:
        return True
    try:
        import gen_celeb_ai as _G
        prio = [p.replace(" ", "") for p in getattr(_G, "PRIORITY_SUBJECTS", [])]
    except Exception:  # noqa: BLE001
        prio = ["나는솔로", "나솔", "나는솔로사계", "나솔사계", "이혼숙려캠프", "이혼숙려",
                "이호선", "오은영", "모솔N돌싱", "모솔연애"]
    # ★**프로그램명 그 자체**만 제외 목록에서 뺀다(방송사 접두는 붙어도 프로그램으로 본다).
    #
    # 🔴2026-08-16 사고: 처음엔 `p in n`(포함)으로 했다가 «이혼숙려캠프 라면 부부»까지 풀려서
    #   같은 소재를 8/13·8/15·8/16 **세 번** 썼다. 8/14 연예 전멸을 고치다 반대편으로 넘어간 것이다.
    #   프로그램은 매일 써야 하지만 **그 안의 개별 소재(라면 부부·22기 옥순)는 한 번뿐**이다.
    #   → 'JTBC 이혼숙려캠프'(접두만) = 프로그램 → 뺀다 / '이혼숙려캠프 라면 부부'(부가어) = 개별 소재 → 차단 유지.
    for p in prio:
        if p and (n == p or re.fullmatch(r"[A-Za-z가-힣·]{0,10}" + re.escape(p), n)):
            return True
    # 방송사·채널만 있는 항목(MBC에브리원 / SBS플러스 / ENA·SBS Plus …)
    if re.fullmatch(r"[A-Za-z가-힣·]*(?:에브리원|플러스|Plus|Joy)|[A-Za-z]{2,6}", n):
        return True
    # 나솔 가명은 기수(숫자+기)가 붙어 있을 때만 유효한 식별자다
    if n in _NASOL_ALIAS and not re.search(r"\d+\s*기", name):
        return True
    return False


#: 기록하면 안 되는 조각. 흔한 낱말·방송사·플랫폼이 '인물'로 등록되면 정상 소재까지 막는다.
#  🔴2026-08-12 실측 사고: 작품명 "이런 엿같은 사랑"을 공백으로 쪼개 저장해서
#  `이런`·`엿같은`·`사랑`이 제외 목록에 들어갔고, 그 결과 '사랑의 이해'·'우리들의 발라드'까지
#  전부 차단됐다(시험 6개 중 5개 차단). 55개 항목 중 35개가 이런 쓰레기였다.
_NOT_A_NAME = set("""
나는 우리 이런 사랑 지옥 새끼 솔로 시즌1 시즌2 시즌3 출연자 출연진 사연자 정체성 고백 근황
유튜브 웨이브 넷플릭스 티빙 쿠팡플레이 방송 예능 드라마 특집 편성 화제 논란
KBS MBC SBS JTBC tvN ENA Joy KBSJoy SBSPlus MBN TVN OTT
무엇이든 엿같은 오리지널 리포트 우발라2 32기 33기 31기 30기 29기 28기 27기 26기 25기 24기 23기
""".split())
#: 기수 표기(23기 등)는 그 자체로 인물이 아니다 — 정규식으로도 막는다
_SEASON_ONLY = re.compile(r"^\d{1,2}\s*기$")


_BCAST = r"SBS(?:\s*PLUS|\s*Plus)?|ENA|MBC|KBS(?:\s*Joy|\s*2TV|\d)?|tvN|JTBC|Mnet|MBN|채널S|채널A|TV조선|넷플릭스"
_BCAST_ONLY = re.compile(rf"^(?:{_BCAST})$", re.I)          # 방송사 하나짜리 조각 = 인물이 아니다
_BCAST_PREFIX = re.compile(rf"^(?:{_BCAST})[\s·,]*", re.I)  # 앞에 붙은 방송사는 뗀다


def mark_celeb_used(name: str) -> None:
    """이번에 다룬 인물·작품을 기록(다음 며칠 제외 대상이 된다).

    ★**전체 이름을 통째로** 저장한다. 공백으로 쪼개 넣으면 흔한 낱말이 제외 목록에 섞여
    정상 소재를 막는다(위 사고). 괄호·따옴표 같은 기호만 정리한다.
    """
    if not name:
        return
    try:
        saved = {}
        if os.path.exists(CELEB_USED):
            with open(CELEB_USED, encoding="utf-8") as f:
                saved = json.load(f)
        # 기호 정리 후 통째로. 사람 이름이 '·'로 이어진 경우만 나눈다(최현서·이한주·한수지).
        clean = re.sub(r"[\"'“”‘’()\[\]]", "", name).strip()
        parts = [p.strip() for p in re.split(r"[·,/]+", clean)] or [clean]
        if clean and clean not in parts:
            parts.append(clean)
        # 🔴2026-08-28: «ENA·SBS Plus 나는 SOLO»가 그대로 들어와 «ENA»가 **인물로** 저장됐다.
        #   방송사가 제외 목록에 앉으면 그 채널 프로그램이 통째로 막힌다.
        #   → 방송사 조각은 버리고, 앞에 붙은 방송사는 떼어 프로그램명만 남긴다.
        def _strip_bcast(x: str) -> str:      # «SBS Plus·ENA 나는 SOLO»처럼 겹쳐 붙는다 → 반복
            prev = None
            while x and x != prev:
                prev, x = x, _BCAST_PREFIX.sub("", x).strip()
            return x
        parts = [_strip_bcast(x) for x in parts]
        for part in parts:
            if (len(part) >= 2 and part not in _NOT_A_NAME
                    and not _SEASON_ONLY.match(part) and not _BCAST_ONLY.match(part)):
                saved[part] = time.time()
        with open(CELEB_USED, "w", encoding="utf-8") as f:
            json.dump(saved, f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass


# ─────────────────────────────────────────────────────────────────────────────
# 사연(에피소드) 단위 중복 방지 — 2026-08-23 신설
# ─────────────────────────────────────────────────────────────────────────────
#: 🔴에디님 지적: "«아들 살리려 뛰어든 아빠 옆, 엄마는 또 낳으면 되지» 지난번에 했던 건데 또 나왔네."
#   실측하니 **같은 사연이 세 번** 나갔다 — 8/20 06편, 8/23 04편, 8/23 09편.
#
#   왜 기존 방어가 다 뚫렸나:
#     · `mark_celeb_used("이호선")`은 저장되지만 `_is_recurring_subject`가 True라 제외되지 않는다.
#       (이건 **의도된 설계**다 — 1순위 소재를 막으면 트래픽 엔진이 꺼진다. 8/14 전멸 사고 참고)
#     · `exclude_urls`는 같은 배치 안 같은 URL만 막는다. 다른 매체가 쓴 같은 사연은 못 막는다.
#     · 제목 유사도(`too_similar`)는 **우리가 지은 제목**끼리 비교한다. 8/23 04편은
#       «아들에게 만지지 마, 3년만 이기적으로 살아»라 제목만 보면 같은 사연인 줄 모른다.
#
#   → 막아야 할 단위는 인물도 프로그램도 아니고 **사연**이다. 그래서 기사 제목·장면검색어를
#     지문으로 남기고, 다음에 고를 때 그 지문과 겹치면 거른다.
STORY_USED = os.path.join(config.WORK_DIR, "celeb_stories.json")

#: 사연 비교에서 **빼야 하는** 말. 프로그램·상담가 이름은 어느 사연에나 들어가서,
#  그대로 두면 짧은 문장끼리 이것만으로 겹쳐 정상 소재까지 막는다(실측:
#  «이호선 상담소 각방» vs «이호선 상담소 물에 빠진 아들» → 2/4 = 0.5로 오탐).
_STORY_STOP = set(_CELEB_PROGRAMS) | set(_CELEB_WORDS) | set("""
상담소 상담 방송 예능 화제 공개 눈물 충격 결국 전격 논란 심경 고백 폭로 출연 시청자
""".split()) | set("""
됐다 됐네 이렇게 저렇게 그렇게 이런 그런 무슨 대체 알고보니 알고 보니 근황 반전 진짜
말했다 밝혔다 전했다 털어놨다 드러났다 나왔다 했다 한다 있다 없다 봤다 됐습니다
모습 순간 이유 이후 다시 처음 마지막 하루 사람 소식 상황 사실 정도 때문 위해 통해
모솔 모태솔로 특집 데이트 첫인상 선택 최종 커플 솔로 남자 여자 출연진 기수
""".split())
#: ↑ 🔴상투어를 빼지 않으면 **다른 사연이 서로 걸린다**(2026-08-27 실측).
#   «오은영, 결국 이렇게 됐다…준가족 부부 반전 근황»이
#   «'나는솔로' 영자, 결국 이렇게 됐다…심경글에 술렁»에 차단됐다.
#   겹친 낱말이 «됐다·이렇게» 둘뿐 — 사연이 아니라 제목 상투어다.
#   연예 기사 제목은 이런 틀을 돌려 쓰기 때문에, 상투어를 남겨두면 사연 판정이 무너진다.


#: 기수 표기·나솔 가명·미스터OO — **사연이 아니라 식별자**다. 남겨두면 다음 회차 글까지 막는다
#  (실측: «7기 옥순 최종 선택»이 «7기 옥순 미스터서 미스터조 삼각구도»에 걸려 차단됐다.
#   그건 같은 사연이 아니라 **그 삼각구도의 결말**이라 반드시 써야 하는 글이다).
_STORY_ID = re.compile(r"^(\d{1,2}기|미스터.{0,3})$")


def _prog_frag(w: str) -> bool:
    """프로그램 이름이 **조사 제거로 깨진 조각**인가.

    🔴2026-08-27 실측: «나는솔로»가 `_norm`에서 끝의 «로»를 조사로 보고 떼어내
      «나는솔»이 됐다. 그 조각은 `_CELEB_PROGRAMS`에 없어서 제외를 빠져나갔고,
      «나는솔로 33기» 기사끼리 «나는솔·모솔» 두 낱말로 서로 차단됐다.
      33기 모솔특집은 어제 시작한 **최신 회차**인데 막힐 뻔했다.
    """
    if len(w) < 3:
        return False
    for p_ in _STORY_STOP:
        if len(p_) >= 3 and (w in p_ or p_ in w):
            return True
    return False


def _story_tokens(t: str) -> set:
    return {w for w in _tokens(t)
            if w not in _STORY_STOP and w not in _NASOL_ALIAS
            and len(w) > 1 and not _STORY_ID.match(w) and not _prog_frag(w)}


# ─────────────────────────────────────────────────────────────────────────────
# 내 블로그에서 **실제로 터진 소재**를 다음 편에 이어 붙인다 — 2026-08-27 신설
# ─────────────────────────────────────────────────────────────────────────────
#: ★에디님: "요 며칠 33기 광수 이야기가 조회수가 제일 많이 나왔거든. 이런 게 있으면
#   어제 새로 나온 걸로 광수 이야기를 새로 쓰면 인기가 많을 거 아냐?
#   연속으로 궁금한 사람들이 클릭할 거고."
#   실측(2026-08-27, 최근 8일): «'나는솔로' 33기 광수, 알고 보니 소속이…» 7,584회로
#   2위(888회)의 **8.5배**였고, 상위 10편 중 6편이 나는솔로였다.
#   홈판 공식이 «지금 남들이 뭘 보나»라면, 이건 «내 독자가 뭘 보러 왔나»다. 후자가 더 확실하다.
_HOT_CACHE: dict = {}


def hot_subjects(days: int = 8, top: int = 4, min_views: int = 150, log=print) -> list[str]:
    """최근 조회수가 잘 나온 글의 **소재**(프로그램·기수·인물)를 뽑는다.

    반환 예: ["나는솔로 33기 광수", "나는솔로 33기 영자", "조현아"]
    ★실패하면 빈 목록 — 이 기능 때문에 배치가 멈추면 안 된다.
    """
    key = (days, top, min_views)
    if key in _HOT_CACHE:
        return _HOT_CACHE[key]
    out: list[str] = []
    try:
        import collections
        import blog_report
        st = blog_report.fetch_stats(days=days, log=lambda m: None)
        agg = collections.Counter()
        for p_ in st.get("posts", []):
            t = (p_.get("title") or "").strip()
            if t:
                agg[t] += int(p_.get("views", 0) or 0)
        for title, v in agg.most_common(30):
            if v < min_views:
                break
            prog = next((p_ for p_ in _CELEB_PROGRAMS if p_ in title.replace(" ", "")), "")
            m = re.search(r"(\d{1,2})\s*기", title)
            who = next((w for w in _CELEB_WORDS + sorted(_NASOL_ALIAS) if w in title), "")
            label = " ".join(x for x in [prog, (m.group(1) + "기") if m else "", who] if x).strip()
            if not label:                      # 프로그램·기수가 없으면 인물만이라도
                label = who
            if label and label not in out:
                out.append(label)
            if len(out) >= top:
                break
        if out:
            log(f"내 블로그 인기 소재(최근 {days}일): {out}")
    except Exception as e:  # noqa: BLE001
        log(f"인기 소재 조회 건너뜀({str(e)[:60]})")
    _HOT_CACHE[key] = out
    return out


def mark_story_used(*parts: str) -> None:
    """이번에 다룬 **사연**의 지문을 남긴다(기사 제목·장면검색어·우리 제목 등 여러 개 가능)."""
    try:
        saved = []
        if os.path.exists(STORY_USED):
            with open(STORY_USED, encoding="utf-8") as f:
                saved = json.load(f) or []
        now = time.time()
        for raw in parts:
            t = re.sub(r"\s+", " ", str(raw or "")).strip()
            # 지문이 너무 짧으면 무의미하게 넓게 걸린다 → 핵심어 2개 이상일 때만 남긴다
            if len(t) >= 6 and len(_story_tokens(t)) >= 2:
                saved.append({"t": t[:120], "ts": now})
        cutoff = now - 90 * 86400
        saved = [r for r in saved if isinstance(r, dict) and r.get("ts", 0) >= cutoff][-1200:]
        with open(STORY_USED, "w", encoding="utf-8") as f:
            json.dump(saved, f, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        pass


def recent_stories(days: int = 30) -> list[str]:
    try:
        with open(STORY_USED, encoding="utf-8") as f:
            saved = json.load(f) or []
        cutoff = time.time() - days * 86400
        return [r["t"] for r in saved if isinstance(r, dict) and r.get("ts", 0) >= cutoff]
    except Exception:  # noqa: BLE001
        return []


def story_seen(cand: str, days: int = 30, threshold: float = 0.4) -> str | None:
    """이미 다룬 사연이면 그 지문을 돌려준다(아니면 None).

    ★threshold 0.4는 실측으로 잡았다. 프로그램·상담가 이름을 뺀 뒤라
      «물에 빠진 아들 / 또 낳으면 되지»는 잡히고, 같은 이호선이라도
      «6년째 각방»·«시댁 김장» 같은 **다른 사연은 통과**한다.
      올리면 재탕을 놓치고, 내리면 새 회차까지 막혀 편수가 준다.
    """
    a = _story_tokens(cand)
    if len(a) < 2:
        return None
    for t in recent_stories(days):
        b = _story_tokens(t)
        if len(b) < 2:
            continue
        # ★겹친 낱말이 **2개 이상**이어야 한다. 지문이 짧으면(«나솔사계 국화 미스터서 반응»
        #   → 유효 토큰 2개) 낱말 하나만 겹쳐도 비율이 0.5가 되어 새 소재를 잡아먹는다(실측).
        common = a & b
        if len(common) >= 2 and len(common) / min(len(a), len(b)) >= threshold:
            return t
    return None


def clean_celeb_used(log=print) -> int:
    """이미 오염된 기록을 청소한다(흔한 낱말·기호 섞인 조각 제거). 제거 개수 반환."""
    try:
        with open(CELEB_USED, encoding="utf-8") as f:
            saved = json.load(f)
    except Exception:  # noqa: BLE001
        return 0
    keep = {}
    for k, v in saved.items():
        bare = re.sub(r"[\"'“”‘’()\[\]]", "", k).strip()
        if (len(bare) >= 2 and bare not in _NOT_A_NAME
                and not _SEASON_ONLY.match(bare) and bare == k):
            keep[k] = v
    removed = len(saved) - len(keep)
    if removed:
        with open(CELEB_USED, "w", encoding="utf-8") as f:
            json.dump(keep, f, ensure_ascii=False)
        log(f"[중복방지] 오염 기록 {removed}개 제거 → {len(keep)}개 유지")
    return removed


if __name__ == "__main__":
    rows = recent_posts(60)
    print(f"최근 {len(rows)}편")
    ts = [r["title"] for r in rows]
    print("\n금지 틀:", banned_patterns(ts) or "(없음)")
    print("\n최근 연예 인물:", ", ".join(sorted(recent_celeb_names())) or "(없음)")

def forget_story(*needles: str, log=print) -> int:
    """사연 기록에서 특정 글의 지문을 지운다 — **잘못 쓴 글을 다시 쓸 때** 쓴다.

    🔴2026-08-28: 사실이 틀린 편(없는 인물 «예찬», 지어낸 숫자)을 다시 쓰려 했더니
      «남은 기사 없음(모두 소진)»으로 막혔다. 그 글을 만들 때 기사들을 «이미 다룬 사연»으로
      기록해 둔 탓이다. 재탕을 막는 장치가 **교정까지 막은 것**이다.
      → 다시 쓰기 전에 그 글이 남긴 지문만 걷어낸다. 되돌리는 길을 막아두면 안 된다.
    """
    try:
        with open(STORY_USED, encoding="utf-8") as f:
            rows = json.load(f)
    except Exception:  # noqa: BLE001
        return 0
    keys = [n.strip() for n in needles if n and n.strip()]
    if not keys:
        return 0
    kept = [r for r in rows
            if not any(k[:18] in (r.get("t") or "") for k in keys)]
    n = len(rows) - len(kept)
    if n:
        with open(STORY_USED, "w", encoding="utf-8") as f:
            json.dump(kept, f, ensure_ascii=False)
        log(f"사연 기록 {n}건 삭제(재작성용)")
    return n

def forget_celeb(*names: str, log=print) -> int:
    """인물 사용 기록을 지운다 — forget_story와 짝. 잘못 쓴 글을 다시 쓸 때만 쓴다.

    🔴2026-08-31 사고: 이 함수가 **dict를 list로 바꿔** 저장했다.
      celeb_used.json은 {이름: 타임스탬프} 형식인데, dict를 그냥 순회하면 키만 남는다.
      그 결과 recent_celeb_names의 `saved.items()`가 예외로 떨어져
      **176건이 통째로 무시**됐고, 7기 옥순이 하루에 서너 번 나왔다.
      → 반드시 **dict 형식을 유지**한다. 타임스탬프를 잃으면 제외가 통째로 죽는다.
    """
    try:
        with open(CELEB_USED, encoding="utf-8") as f:
            saved = json.load(f)
    except Exception:  # noqa: BLE001
        return 0
    if not isinstance(saved, dict):        # 옛 형식이면 여기서 되살린다
        saved = {str(x): time.time() for x in (saved or []) if str(x).strip()}
    keys = [n.strip() for n in names if n and n.strip()]
    if not keys:
        return 0
    drop = [k for k in saved if any(x in k or k in x for x in keys)]
    for k in drop:
        saved.pop(k, None)
    if drop:
        with open(CELEB_USED, "w", encoding="utf-8") as f:
            json.dump(saved, f, ensure_ascii=False)   # ★dict로 저장(형식 유지)
        log(f"인물 기록 {len(drop)}건 삭제(재작성용)")
    return len(drop)


def forget_post(title: str = "", person: str = "", log=print) -> None:
    """재작성 준비 — 그 글이 남긴 **사연·인물 기록을 함께** 걷어낸다.

    🔴2026-08-28: 사실이 틀린 4편을 다시 쓰려 했더니 셋이 각기 다른 이유로 막혔다.
      «남은 기사 없음(모두 소진)» / «홈판 연예 이슈 선정 실패» — 뿌리는 하나였다.
      **그 잘못된 초안이 인물과 사연을 이미 «썼다»고 기록해** 교정을 막은 것이다.
      재탕 방지는 필요하지만 **되돌리는 길까지 막으면 안 된다**.
    """
    if title:
        forget_story(title, log=log)
    if person:
        forget_celeb(person, log=log)
