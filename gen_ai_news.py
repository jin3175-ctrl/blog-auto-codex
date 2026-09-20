#!/usr/bin/env python3
"""AI 최신소식 — 오늘의 AI 뉴스를 모아 한 편으로 정리한다 (2026-09-02 에디님 지시).

에디님 말: "AI 최신소식을 하나 발행하는 게 좋겠다. 예전에 퍼플리시티에서 찾아서 준 것처럼 그런 내용들."

퍼플리시티가 주던 것의 정체는 **'오늘 실제로 있었던 일 + 출처 + 그래서 나한테 뭐가 달라지나'**다.
그래서 이 생성기는 LLM에게 "AI 뉴스를 써라"라고 시키지 않는다(그러면 지어낸다).
**네이버 IT·과학 뉴스에서 오늘 기사를 긁어와 재료로 주고, 그걸로만 쓰게 한다.**

- 재료: 네이버 IT·과학 섹션(105) 헤드라인 → AI 관련만 필터 → 상위 기사 본문 수집
        부족하면 뉴스 검색(인공지능·챗GPT·오픈AI…)으로 보충
- 카테고리: 'AI 최신소식'(2026-09-02 에디님이 네이버에 새로 만든 칸)
- 발행: 예약 08:00 (AI 실전 07:00 바로 다음)

🔴본문에 URL을 넣지 않는다 — 네이버 에디터가 링크 카드로 바꾸며 문장을 두 동강 낸다
   (2026-08-17 사고). 출처는 **언론사 이름만** 본문에 적고, 기사 주소는 사이드카
   `NN_뉴스출처.txt`에 따로 남긴다(에디님이 확인용으로 클릭).

사용:
  python3 gen_ai_news.py            # 한 편 생성(번호 90)
  python3 gen_ai_news.py 02         # 번호 지정
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from claude_cli import run_claude_p, run_claude_p_retry
import celeb_sources as S
import config
import gen_common as G
import gen_templates as T
import gemini_thumb
from gen_ai import (EDI_AI_PROFILE, EDI_STORY, _clean_title, _parse_body,
                    _set_title_line, _thumb_via_stock, _thumb_via_web)

IT_SECTION = "https://news.naver.com/section/105"      # IT·과학
_UA_M = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
         "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148")

#: AI 소식으로 볼 낱말. 반도체·통신 일반 기사까지 끌어오면 'AI 최신소식'이 아니게 된다 →
#: **AI 그 자체를 다루는 말**만 넣는다(제품명·회사명 포함).
_AI_HIT = re.compile(
    r"\bAI\b|A\.I|인공지능|생성형|머신러닝|딥러닝|LLM|거대언어|"
    r"챗GPT|ChatGPT|오픈AI|OpenAI|GPT-?\d|"
    r"제미나이|Gemini|클로드|Claude|앤스로픽|Anthropic|"
    r"코파일럿|Copilot|미드저니|Midjourney|퍼플렉시티|Perplexity|"
    r"라마\s*\d|Llama|딥시크|DeepSeek|그록|Grok|소라|Sora|"
    r"에이전트|AGI|하이퍼클로바|엑사원|믿:음|프롬프트", re.I)

#: 🔴사람들이 **실제로 검색창에 치는 기기 이슈**. 2026-09-15 에디님 지적:
#   "아이폰 18이 엄청 인기가 많고, 듀오폰도 그렇고… 이렇게 뜨는 정보들을 하나씩 넣으라니까?"
#   데이터랩 실측(9/7 주, 같은 잣대): 아이폰18·아이폰에어·폴더블아이폰 **100** /
#   갤럭시Z7·S26 10.7 / 우리가 써온 오픈AI·GPT-6·앤트로픽 **9.1** → **11배**.
#   AI 업계 뉴스만 재료로 쓰니 편당 0~2회였다(9/11~9/14 실측). 기기 이슈를 재료에 넣고
#   **맨 앞으로** 정렬한다(제목은 가장 큰 뉴스의 고유명사를 앞에 쓰므로 제목이 검색어가 된다).
#   ⚠️버리지 않고 순서만 바꾼다 — 기기 뉴스가 없는 날엔 AI 모델 뉴스가 그대로 앞에 온다.
_TREND_HIT = re.compile(
    r"아이폰|아이패드|애플워치|에어팟|맥북|비전\s*프로|"
    r"갤럭시|갤럭시\s*Z|플립|폴드|폴더블|듀오폰|버즈|워치\d|"
    r"애플|삼성전자|샤오미|픽셀\s*\d", re.I)

#: 제목만 AI를 스치는 광고·연재성 잡글을 뺀다(실측: 쇼핑성 낚시 제목이 IT 섹션에 섞인다).
_AI_SKIP = re.compile(r"\[포토\]|\[부고\]|\[인사\]|주가|상한가|급등|급락|공시|"
                      r"특징주|개장전|장중|증시|코스피|코스닥|나스닥|목표주가|투자의견|"
                      r"신제품 출시 기념|이벤트|경품|할인 행사")

#: 기사 본문에서 걷어낼 꼬리(기자 이메일·저작권·구독 유도)
_TAIL = re.compile(r"(무단[ ]?전재|재배포 금지|저작권자|기자\s*[\w.-]+@|"
                   r"구독하기|네이버에서.*구독|Copyright)", re.I)


def _log(m: str) -> None:
    print(f"{datetime.now():%H:%M:%S} {m}", flush=True)


def _art_id(url: str) -> str:
    m = re.search(r"/article/(?:\w+/)?(\d+)/(\d+)", url or "")
    return f"{m.group(1)}/{m.group(2)}" if m else (url or "")


def rank_title(t: str) -> int:
    """재료 순서. 🔴**합치고 나서도 반드시 이걸로 다시 정렬한다.**

    2026-09-15 실측: 기기 기사를 맨 앞으로 정렬해 놓고, 뒤이어 모델 검색 결과를
    `heads = extra + heads`로 앞에 끼워 넣는 바람에 기기 기사가 도로 뒤로 밀렸다.
    제목은 첫 기사의 고유명사로 세우므로, 순서가 곧 제목이고 곧 검색 유입이다.
    """
    if _TREND_HIT.search(t) and not _BIZ_HIT.search(t):
        return 0                      # 검색량이 제일 큰 기기 이슈(데이터랩상 AI 업계의 11배)
    if _MODEL_HIT.search(t):
        return 1
    return 3 if _BIZ_HIT.search(t) else 2


def fetch_ai_headlines(limit: int = 16, log=print) -> list:
    """네이버 IT·과학 섹션에서 **AI 관련 헤드라인**만 [{title, url}]로 뽑는다."""
    from playwright.sync_api import sync_playwright
    items = []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(user_agent=_UA_M)
        try:
            pg.goto(IT_SECTION, wait_until="domcontentloaded", timeout=40000)
            pg.wait_for_timeout(2000)
            items = pg.eval_on_selector_all(
                "a",
                """els => els.map(e => ({t:(e.innerText||'').trim(), h:e.href}))
                     .filter(x => x.t.length >= 12 && /\\/(article|mnews)\\//.test(x.h))""")
        finally:
            b.close()
    out, seen = [], set()
    for it in items:
        title = re.sub(r"\s+", " ", it["t"].splitlines()[0]).strip()
        url = it["h"].split("?")[0]
        key = _art_id(url)
        if not title or key in seen:
            continue
        if not (_AI_HIT.search(title) or _TREND_HIT.search(title)) or _AI_SKIP.search(title):
            continue
        seen.add(key)
        out.append({"title": title[:110], "url": url})
        if len(out) >= limit:
            break
    # ★모델·기능 기사를 앞으로, 기업·인프라·정책을 뒤로. (버리지 않는다 — 마른 날이 있다)
    out.sort(key=lambda it: rank_title(it["title"]))
    n_model = sum(1 for it in out if _MODEL_HIT.search(it["title"]))
    n_trend = sum(1 for it in out if _TREND_HIT.search(it["title"]))
    log(f"[뉴스] IT·과학 섹션 {len(out)}건 (기기 이슈 {n_trend}건을 맨 앞, 모델·기능 {n_model}건)")
    return out


#: 🔴**독자가 읽고 싶은 AI 뉴스는 '모델·서비스·기능'이지 '서버·실적·정책'이 아니다.**
#   2026-09-03 에디님: "클로드 Fable 5.1이 나왔는데 성능 비교라든지, 이런 게 AI 최신뉴스 아냐?"
#   실측(9/3 02편 재료 6건): 에퀴닉스 AI 추론망 · 델 서버 실적 · 데이터센터 전력 ·
#   엔비디아 금융지원 · SKT CEO 인터뷰 — **5건이 투자자용**이었고 독자용은 1건뿐이었다.
#   원인: 재료를 네이버 IT·과학 **섹션 헤드라인**에서만 뽑았는데 그 섹션이 기업·정책 위주다.
#   → ①모델·기능 기사를 **앞으로 정렬**하고 ②모델 이름으로 **직접 검색**해 보충한다.
_MODEL_HIT = re.compile(
    r"챗GPT|ChatGPT|GPT-?\d|오픈AI|OpenAI|클로드|Claude|앤스로픽|Anthropic|"
    r"제미나이|Gemini|코파일럿|Copilot|딥시크|DeepSeek|그록|Grok|소라|Sora|"
    r"라마\s*\d|Llama|미드저니|Midjourney|퍼플렉시티|Perplexity|하이퍼클로바|엑사원|"
    r"출시|공개|선보|업데이트|새\s*기능|신규\s*기능|버전|벤치마크|성능|비교|"
    r"무료\s*(공개|배포|전환)|요금|구독료|프롬프트|사용법", re.I)

#: 기업·인프라·정책 기사. **버리지는 않고 뒤로 민다**(그날 모델 뉴스가 없을 수도 있다).
_BIZ_HIT = re.compile(
    r"실적|매출|영업이익|주가|시총|투자\s*유치|수주|공급망|데이터센터|서버|전력|냉각|"
    r"반도체\s*장비|증설|CEO|사장|부총리|장관|국회|규제|법안|간담회|회의|협약|MOU|"
    r"컨퍼런스|포럼|인재\s*양성|채용", re.I)

#: 섹션이 마른 날 보충용 검색어. **모델·서비스 이름 위주**로 던진다.
_BACKUP_Q = ["클로드", "챗GPT", "제미나이", "오픈AI", "인공지능", "AI"]

#: 기기 이슈를 직접 검색할 때 던지는 말. 🔴**브랜드 이름만 넣는다.**
#   「아이폰 18」처럼 모델 번호를 박으면 내년엔 19가 되어 못 따라간다
#   (이 저장소 방침: 문구를 코드에 박지 말 것). 그날 뜬 모델이 뭔지는 검색 결과가 알려준다.
_TREND_Q = ["아이폰", "갤럭시", "폴더블"]


def collect_news(want: int = 6, log=print) -> list:
    """오늘의 AI 뉴스 재료 [{title, media, url, body}] want건.

    ★섹션 → (부족하면) 뉴스 검색 순. 검색은 본문 링크가 없어 스니펫만 오지만,
      '무슨 일이 있었나'를 적기엔 충분하다(지어내는 것보단 훨씬 낫다).
    """
    heads = fetch_ai_headlines(16, log)
    # 🔴기기 이슈를 **선제로** 검색한다(2026-09-15). IT·과학 섹션 헤드라인은 AI 정책·기업
    #   기사로 덮이는 날이 많아 아이폰·폴더블이 통째로 안 들어온다(실측: 16건 중 기기 1건).
    #   데이터랩상 기기 이슈 검색량이 AI 업계 뉴스의 **11배**라, 이걸 놓치면 제목이
    #   아무도 안 치는 말로 세워진다(9/11~9/14 뉴스 4편 조회 0~2회).
    n_trend = sum(1 for h in heads if _TREND_HIT.search(h["title"]))
    if n_trend < 3:
        log(f"[뉴스] 섹션에 기기 이슈가 {n_trend}건뿐 → 기기 이름으로 직접 검색합니다")
        seen_t = {h["title"][:24] for h in heads}
        extra_t = []
        for q in _TREND_Q:
            try:
                for r in S.fetch_news_search(q, limit=3):
                    if (r["title"][:24] in seen_t or not _TREND_HIT.search(r["title"])
                            or _AI_SKIP.search(r["title"])):
                        continue
                    seen_t.add(r["title"][:24])
                    extra_t.append({"title": r["title"], "url": "", "_snip": r.get("body", "")})
                    log(f"[뉴스] 기기 검색({q}): {r['title'][:46]}")
            except Exception as e:  # noqa: BLE001
                log(f"[뉴스] 기기 검색 실패({q}): {str(e)[:50]}")
        heads = extra_t + heads
    # ★섹션에 모델 기사가 적으면 **먼저 검색으로 채운다**(보충이 아니라 선제).
    #   그날 클로드·GPT 새 모델이 나왔는데 섹션 헤드라인에 안 뜨는 경우가 흔하다.
    n_model = sum(1 for h in heads if _MODEL_HIT.search(h["title"]))
    if n_model < max(2, want // 2):
        log(f"[뉴스] 섹션에 모델·기능 기사가 {n_model}건뿐 → 모델 이름으로 직접 검색합니다")
        seen_t = {h["title"][:24] for h in heads}
        extra = []
        for q in ("클로드", "챗GPT", "제미나이", "오픈AI"):
            try:
                for r in S.fetch_news_search(q, limit=3):
                    if r["title"][:24] in seen_t or not _MODEL_HIT.search(r["title"]):
                        continue
                    seen_t.add(r["title"][:24])
                    extra.append({"title": r["title"], "url": "", "_snip": r.get("body", "")})
                    log(f"[뉴스] 모델 검색({q}): {r['title'][:46]}")
            except Exception as e:  # noqa: BLE001
                log(f"[뉴스] 모델 검색 실패({q}): {str(e)[:50]}")
        heads = extra + heads
    # ★보충으로 끼워 넣은 것까지 합쳐 **다시 정렬**한다(위 rank_title 주석 참고).
    heads.sort(key=lambda h: rank_title(h["title"]))
    # 🔴기기 이슈는 **앞 2건까지만** 쓴다(2026-09-15). 검색 유입을 위해 맨 앞에 두는 것이지,
    #   AI·자동화 블로그 글이 기기 뉴스로만 채워지면 이 블로그가 아니게 된다.
    #   (재료가 기기밖에 없는 날엔 그대로 간다 — 아래 2차 루프에서 다시 담는다)
    TREND_CAP = 2
    out, skipped = [], []
    n_tr = 0
    for h in heads:
        if len(out) >= want:
            break
        if _TREND_HIT.search(h["title"]) and n_tr >= TREND_CAP:
            skipped.append(h)
            continue
        if _TREND_HIT.search(h["title"]):
            n_tr += 1
        if not h.get("url"):                     # 검색으로 들어온 건 스니펫이 본문 대신이다
            if len(h.get("_snip", "")) >= 120:
                out.append({"title": h["title"], "url": "", "media": "",
                            "body": h["_snip"][:1200]})
                log(f"[뉴스] 확보 {len(out)}/{want}(검색): {h['title'][:40]}")
            continue
        try:
            art = S.fetch_article(h["url"])
        except Exception as e:  # noqa: BLE001
            log(f"[뉴스] 본문 실패({h['title'][:24]}): {str(e)[:60]}")
            continue
        body = re.sub(r"\n{2,}", "\n", (art.get("body") or "")).strip()
        body = "\n".join(l for l in body.splitlines() if not _TAIL.search(l))
        if len(body) < 200:
            continue
        out.append({"title": art.get("title") or h["title"], "url": h["url"],
                    "media": _media_of(h["url"]), "body": body[:1800]})
        log(f"[뉴스] 확보 {len(out)}/{want}: {out[-1]['title'][:40]}")
    if len(out) < want and skipped:
        log(f"[뉴스] 재료가 모자라 미뤄둔 기기 기사 {len(skipped)}건에서 채웁니다")
        for h in skipped:
            if len(out) >= want:
                break
            if h.get("_snip", "") and len(h["_snip"]) >= 120:
                out.append({"title": h["title"], "url": "", "media": "", "body": h["_snip"][:1200]})
                log(f"[뉴스] 확보 {len(out)}/{want}(기기·보류분): {h['title'][:40]}")
    if len(out) < want:
        seen = {t["title"][:24] for t in out}
        for q in _BACKUP_Q:
            if len(out) >= want:
                break
            try:
                for r in S.fetch_news_search(q, limit=4):
                    if len(out) >= want or r["title"][:24] in seen:
                        continue
                    if not (_AI_HIT.search(r["title"]) or _TREND_HIT.search(r["title"])) \
                            or _AI_SKIP.search(r["title"]):
                        continue
                    seen.add(r["title"][:24])
                    out.append({"title": r["title"], "url": "", "media": "",
                                "body": r.get("body", "")})
                    log(f"[뉴스] 검색 보충({q}) {len(out)}/{want}: {r['title'][:40]}")
            except Exception as e:  # noqa: BLE001
                log(f"[뉴스] 검색 실패({q}): {str(e)[:60]}")
    return out


#: 네이버 기사 URL의 언론사 코드 → 이름. 없으면 빈 문자열(본문에 '한 매체'로 쓰게 둔다).
_MEDIA = {
    "001": "연합뉴스", "003": "뉴시스", "005": "국민일보", "008": "머니투데이",
    "009": "매일경제", "011": "서울경제", "014": "파이낸셜뉴스", "015": "한국경제",
    "016": "헤럴드경제", "018": "이데일리", "020": "동아일보", "021": "문화일보",
    "022": "세계일보", "023": "조선일보", "024": "매경이코노미", "025": "중앙일보",
    "028": "한겨레", "029": "디지털타임스", "030": "전자신문", "031": "아이뉴스24",
    "032": "경향신문", "033": "중앙SUNDAY", "092": "지디넷코리아", "138": "디지털데일리",
    "277": "아시아경제", "293": "블로터", "296": "코메디닷컴", "347": "디지털투데이",
    "421": "뉴스1", "437": "JTBC", "469": "한국일보", "479": "이코노미스트",
}


def _media_of(url: str) -> str:
    m = re.search(r"/article/(?:\w+/)?(\d+)/", url or "")
    return _MEDIA.get(m.group(1), "") if m else ""


TITLE_PROMPT = """아래는 '오늘의 AI 소식' 블로그 글에 들어갈 실제 뉴스 목록입니다.
이 글의 네이버 블로그 제목 후보 8개를 만드세요.

[오늘의 뉴스]
{news_list}

[이 글의 성격]
매일 나가는 'AI 최신소식' 정리 글입니다. 읽는 사람은 두 부류입니다.
 ① 'AI 뉴스' '오늘 AI 소식' '챗GPT 업데이트' 같은 말로 **검색해서** 오는 사람
 ② 홈피드에서 지나가다 제목에 걸려 들어오는 사람
둘 다 잡아야 하므로 **검색어(회사·제품 이름) + 궁금하게 만드는 한 마디**의 조합입니다.

[규칙]
- 40자 이내. 한 줄에 하나씩, 번호·기호·따옴표 없이 제목만.
- 🔴**가장 큰 뉴스의 고유명사(회사명·제품명)를 앞쪽에 넣습니다.** 그게 검색어입니다.
  예: '오픈AI', '제미나이', '챗GPT', 'SKT' — 뉴스에 없는 이름을 지어내면 안 됩니다.
- 결론을 제목에서 다 말하지 않습니다(무엇이 달라졌는지는 본문에서).
- 지어낸 수치 금지. 위 뉴스에 있는 숫자만 씁니다.
- 「~라고 합니다」 같은 전언체, 「정리」로만 끝나는 밋밋한 제목은 피합니다.
- 날짜를 넣어도 좋습니다({today}). 다만 날짜만으로 채우지 마세요.

제목 8개만 출력하세요.
"""

BODY_PROMPT = """당신은 'AI 실전' 블로거 '에디'입니다. 오늘의 AI 소식을 정리하는 글을 씁니다.

{profile}

{story}

🔴🔴**가장 중요한 규칙: 아래 [오늘의 뉴스 재료] 안에 있는 내용만 씁니다.**
재료에 없는 회사·제품·기능·가격·날짜·수치를 **한 글자도 지어내지 마세요.**
이 글은 '소식'이라 틀리면 그냥 거짓말이 됩니다. 모르면 안 씁니다.
재료가 모호하면 「자세한 조건은 아직 공개되지 않았습니다」처럼 **모른다고 적습니다.**

[오늘의 뉴스 재료 — 오늘 {today} 실제 기사]
{news}

[글의 목적]
독자가 이 글 하나만 읽으면 **오늘 AI 판에서 무슨 일이 있었는지** 알게 되는 것.
그리고 각 소식마다 «그래서 나한테 뭐가 달라지나»를 에디의 시선으로 한 마디 붙입니다.
(이게 뉴스 요약봇과 다른 점입니다. 사실은 기사에서, 해석은 직접 써본 사람의 감각에서.)

[구조]
1. 도입 2~4줄 — 오늘 소식 중 **제일 큰 것 하나**를 먼저 던집니다.
   🔴인사·자기소개 금지. '안녕하세요', '에디입니다', '오늘은'으로 시작하지 마세요.
2. 소식 {n}개를 하나씩. 각 소식마다:
   · [사진N] 다음 줄에 소주제(20자 이내, 마침표 없이)
   · 무슨 일이 있었는지 (사실, 재료 그대로)
   · **출처는 언론사 이름만** 문장에 녹입니다. 예: 「전자신문 보도에 따르면」
     🔴주소(http, www, 링크)를 본문에 절대 쓰지 마세요. 네이버가 링크 카드로 바꿔 문장을 부숩니다.
   · 「그래서 뭐가 달라지나」 — 실제로 쓰는 사람 입장에서 2~4문장.
     확실치 않으면 「저도 아직 안 써봐서 단정은 못 하겠습니다」처럼 솔직하게.
3. [표] 오늘 소식 한눈에 (아래 카드 JSON의 '표'). ★본문의 **20~40% 지점**(소식 한두 건 뒤)에 둡니다 — 홈판 위너 실측(2026-09-18): 표를 쓴 글은 전부 앞 40% 안.
   끝에 몰면 거기까지 안 읽고 나간 독자는 표를 못 봅니다.
4. 에디의 경험 문단 1~2곳 — 위 [에디의 실제 이야기] 범위 안에서, 오늘 소식과 이어서.
   범위 밖의 수치·날짜·실적은 지어내지 마세요. 빈 슬롯([[...]])도 남기지 마세요.
5. 마무리: 오늘 중 **딱 하나만 챙긴다면 이것** + 질문형 CTA 한 줄.
   🔴유튜브 채널 언급·홍보 금지(2026-08-02 에디님 지시). 실측에서 LLM이 끝에 슬쩍 붙였다
     — `pipeline._strip_youtube_cta`가 걷어내긴 하지만 애초에 쓰지 않는 게 맞다.

[문단 규칙 — 홈판 실측]
- **문장을 짧게 쓰고, 한 문장을 한 줄로** 놓습니다.
  🔴문장 중간을 자르지 마세요. 따옴표·인용문은 아무리 길어도 통째로 한 줄입니다.
  나쁜 예: `오픈AI는 이번에` / `새 모델을 공개하면서` / `가격을 내렸습니다.`
  좋은 예: `오픈AI가 새 모델을 공개했습니다.` / `가격도 같이 내렸습니다.`
- 🔴**분량 목표는 «공백 제외 2,000자 이상»입니다**(2026-09-07 전체 홈판 실측).
  전체 홈판 22편 중앙값이 2,428자였습니다. 이 글은 소식 여러 건을 담으므로 그 자리에서 겁니다.
  글자 수만 말하면 안 지켜집니다 → **본문 문단 125개 이상**으로 셉니다(한 문단 평균 16자).
  소식 하나마다 **6~10문단**씩 붙입니다. 문단을 나누는 것과 내용을 줄이는 것은 다릅니다.
- 마크다운 금지(별표·샵). 이모지는 소제목에 한두 개만.

[★'AI가 쓴 티' 제거]
 · 금지 연결어: 또한, 따라서, 이처럼, 뿐만 아니라, 결론적으로, 정리하자면
 · 금지 마무리: ~해보시기 바랍니다, 도움이 되셨길 바랍니다, 지금 바로 시작해보세요
 · 금지 수식어: 정말 유용한, 매우 효과적인, 혁신적인, 놀라운
 · 항목마다 3개씩 균일하게 떨어지는 나열 금지(2개나 4개도 씁니다)
 · 문장 길이를 들쭉날쭉하게. 한 줄짜리 문장을 섞습니다.

[마커]
- [사진N - 화면/장면 설명 / 출처: 직접 촬영 또는 해당 툴 화면] **12~14개**
  🔴이 글은 소식 여러 건을 담아 **문단이 120개가 넘는다**. 사진이 7장이면 글만 빽빽해 보인다
     (2026-09-02 에디님 지적: "글은 많아졌는데 사진이 6~7장이니까 이상해졌어").
     소식 하나마다 2장씩, 도입·마무리에 1장씩 놓는다고 생각하면 맞는다.
  ※실제 사진이 아니라 그림으로 채워지는 자리입니다. 인물 사진·로고·기사 캡처를 요구하지 말고,
    «노트북 화면에 떠 있는 채팅 인터페이스», «책상 위 메모와 커피» 같은 **연출 가능한 장면**으로 적으세요.
- [표] 1개
- 소주제는 [사진N] 바로 다음 줄에만. 두 줄 연속 금지.
- 마지막: 해시태그 10개(#로 시작). 검색어(AI뉴스·챗GPT·인공지능 등) 포함.
- '@출처' 줄은 넣지 않습니다(본문 안에서 언론사 이름을 이미 밝혔습니다).

[출력 형식 — 정확히 이 구분자]
===본문===
제목: (임시 제목 한 줄 - 뒤에서 교체됨)
(본문)
===카드===
(JSON 한 개. 큰따옴표)
{{"표제목":"{table_title}","표":[["소식","한 줄 요약"],["...","..."],["...","..."],["...","..."]],
 "썸네일":{{"intro":"짧은 후킹 도입구","big":"핵심 키워드(3~6자)","tail":"짧은 마무리","badge":"AI 최신소식"}}}}
"""


def _keyword(titles: list, today: str) -> str:
    """파일 이름용 키워드. 제목에서 고유명사를 하나 건져 붙인다(없으면 날짜만)."""
    src = " ".join(titles[:2])
    m = re.search(r"(오픈AI|OpenAI|챗GPT|ChatGPT|제미나이|Gemini|클로드|Claude|"
                  r"앤스로픽|구글|네이버|삼성|SKT|카카오|메타|엔비디아|딥시크|그록)", src, re.I)
    tag = re.sub(r"[^가-힣A-Za-z0-9]", "", m.group(1)) if m else ""
    return f"AI최신소식{today.replace('-', '')}{tag}"[:24]


def generate(out_dir: str, no: str = "90", log=print, ctx: dict | None = None,
             want_news: int = 6) -> dict:
    """오늘의 AI 소식 1편. 재료(뉴스)를 못 구하면 **글을 만들지 않고 예외를 낸다**.

    ★재료 없이 쓰게 두면 LLM이 그럴듯한 가짜 뉴스를 만든다 — 그건 안 내보내는 것보다 나쁘다.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    log(f"[{no}] AI 최신소식 생성 시작 ({today})")

    news = collect_news(want_news, log)
    if len(news) < 3:
        raise RuntimeError(f"AI 뉴스 재료 부족({len(news)}건) — 지어내지 않고 중단합니다")
    log(f"[{no}] 재료 {len(news)}건 확보")

    news_list = "\n".join(f"{i+1}. {n['title']}" + (f" ({n['media']})" if n["media"] else "")
                          for i, n in enumerate(news))
    news_blob = "\n\n".join(
        f"[{i+1}] {n['title']}\n출처 언론사: {n['media'] or '(미상)'}\n{n['body'][:1500]}"
        for i, n in enumerate(news))

    # ── 제목 후보 ──
    titles = []
    try:
        import history
        _recent = history.with_session(history.recent_titles(60, log))
        # 🔴규칙 1(2026-09-18) — 이 생성기는 오늘 뽑은 홈판 공식을 **아예 받지 않았다.**
        #   실전편(gen_ai)만 공식을 쓰고 뉴스편은 자기 규칙으로만 제목을 만들었다.
        _ctx = ctx or {}
        _homes = _ctx.get("home_titles") or []
        _fx = ""
        if _ctx.get("title_formula") or _homes:
            _fx = ("\n\n[오늘 홈판에서 실제로 뜨고 있는 제목의 공식 — 매일 새로 뽑은 것. «맞춰야 할 틀»이다]\n"
                   + (_ctx.get("title_formula") or "(추출 실패)")
                   + "\n\n[오늘 홈판 위너 제목 실물]\n" + "\n".join(f"- {t}" for t in _homes[:25])
                   + "\n\n★위 실물을 베끼지 말고, 오늘 뉴스의 가장 큰 고유명사로 이 틀에 맞춘 제목을 만든다.")
        out = run_claude_p(TITLE_PROMPT.format(news_list=news_list, today=today) + _fx
                           + "\n\n" + history.prompt_block(_recent), timeout=150)
        titles = [_clean_title(l) for l in out.splitlines() if l.strip()]
        titles = [t for t in titles if 6 <= len(t) <= 45 and not G.looks_meta(t)]
        _fresh = [t for t in titles if not history.too_similar(t, _recent, 0.5)]
        if _fresh:
            titles = _fresh
        from gen_ai import pick_by_formula
        titles = pick_by_formula(titles, _homes, log, tag=f"[{no}] ")
        titles = titles[:5]
    except Exception as e:  # noqa: BLE001
        log(f"[{no}] 제목 생성 실패: {e}")
    best = titles[0] if titles else f"{today} AI 최신소식 정리"
    try:
        import history
        history.note_title(best)
    except Exception:  # noqa: BLE001
        pass

    # ── 본문 ──
    table_title = f"{today} AI 소식 한눈에"
    prompt = BODY_PROMPT.format(profile=EDI_AI_PROFILE, story=EDI_STORY, today=today,
                                news=news_blob, n=len(news), table_title=table_title)
    if (ctx or {}).get("ref_formula"):
        # 🔴규칙 2 — 오늘 내 주제(IT) 홈판 위너 **한 편**의 설계도. 위 [구성]과 부딪치면 이 설계도의
        #   도입·리듬·시각 장치를 우선한다(재료·사실 규칙은 위를 그대로 지킨다).
        rp = ctx.get("ref_post") or {}
        prompt += (f"\n\n[오늘의 레퍼런스 글 한 편 — «{rp.get('title', '')[:50]}»]\n"
                   f"이 글의 설계도를 따른다(내용·문장은 베끼지 말고 구조만):\n{ctx['ref_formula']}")

    def _ok(out):
        b, c = _parse_body(out)
        if not (bool(b) and bool(c) and len(b.strip()) >= 800):
            return False
        # ★사진이 글 길이에 비해 모자라면 다시 받는다. 이 글은 길어서 min_n을 높게 잡는다.
        # 이 글은 소식 여러 건이라 연예편보다 길다 → 하한을 11로(연예·AI실전은 10).
        if not G.enough_length(b, 2000):
            return False
        if not G.enough_photos(b, min_n=11):
            return False
        return True

    body, cards = _parse_body(
        run_claude_p_retry(prompt, timeout=360, ok=_ok, log=log, label=f"[{no}] 본문"))
    if not body or not cards or len(body.strip()) < 800:
        raise RuntimeError(f"본문 생성 실패(재시도 소진, 길이 {len(body.strip())})")

    # 🔴규칙 5 — 피드백 한 번 → 다시 쓰기(제목·인트로·썸네일). 규칙 4(고유명사)도 여기서 잰다.
    import feedback as FB
    _t0 = best
    best, body, fb_thumb, fb_report = FB.run(best, body, log, tag=f"[{no}] ")
    if best != _t0:
        titles = [best] + [t for t in titles if t != best]
    body = _set_title_line(body, best)
    from pipeline import _strip_greeting_intro
    body = _strip_greeting_intro(body)
    body = _strip_urls(body, log)

    keyword = _keyword(titles or [best], today)
    os.makedirs(out_dir, exist_ok=True)
    G.clear_no(out_dir, no)
    with open(os.path.join(out_dir, f"{no}_{keyword}_복붙용.txt"), "w", encoding="utf-8") as f:
        f.write(body)
    # ★_ai.flag = pipeline이 'AI 글'로 보고 본문 그림을 채워 넣는 표식(연예 글과 구분).
    open(os.path.join(out_dir, f"{no}_{keyword}_ai.flag"), "w").close()
    if fb_report:
        with open(os.path.join(out_dir, f"{no}_{keyword}_피드백.md"), "w", encoding="utf-8") as f:
            f.write(fb_report)
    if titles:
        with open(os.path.join(out_dir, f"{no}_{keyword}_제목후보.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(titles))
    # 🔴기사 주소는 본문이 아니라 **여기에** 남긴다(본문 URL은 링크 카드로 변해 문장을 부순다).
    with open(os.path.join(out_dir, f"{no}_뉴스출처.txt"), "w", encoding="utf-8") as f:
        f.write(f"# {today} AI 최신소식 — 참고 기사\n\n")
        for i, n in enumerate(news):
            f.write(f"{i+1}. {n['title']}\n   {n['media'] or '출처 미상'}  {n['url'] or '(검색 스니펫)'}\n\n")

    T.write_celeb_table(out_dir, no, keyword, cards.get("표제목", table_title), cards.get("표", []))

    # ── 썸네일: API → 웹 구독 → 스톡 → (다 실패해야) 텍스트형 ──
    thumb = cards.get("썸네일", {})
    fn = f"{no}_{keyword}_썸네일.png"
    ref_formula = (ctx or {}).get("thumb_formula", "")
    if not gemini_thumb.make_from_article(out_dir, fn, body, log=log, ref_formula=ref_formula,
                                        copy=fb_thumb):   # 규칙 5: 피드백봇이 고른 문구
        log(f"[{no}] 제미나이 API 썸네일 실패({gemini_thumb.LAST_ERROR or '사유 미상'}) → 웹 구독으로 시도")
        if not _thumb_via_web(out_dir, fn, thumb, best, log):
            if not _thumb_via_stock(out_dir, fn, thumb, best, log):
                log(f"[{no}] 썸네일: 사진 경로가 모두 실패 → 텍스트형(사진 없음)")
                T.render_text_thumbnail(out_dir, fn, thumb, footer="")

    # (인포그래픽 자동 첨부는 배포판에서 뺐다.)
    log(f"[{no}] 완료 → {best} (뉴스 {len(news)}건 · 제목후보 {len(titles)}개)")
    return {"no": no, "keyword": keyword, "titles": titles, "news": len(news)}


_URL_RE = re.compile(r"(https?://\S+|www\.[\w.-]+\.[a-z]{2,}\S*)", re.I)


def _strip_urls(body: str, log=print) -> str:
    """🔴본문 URL 제거 — 프롬프트 금지의 코드 백스톱(2026-08-17 사고).

    네이버 에디터는 본문 URL을 '링크 미리보기 카드'로 바꾸면서 **문장을 두 동강 낸다.**
    길이·형식으로 피할 수 없고, 짧은 단축 주소도 같다. 그래서 남아 있으면 통째로 지운다.
    """
    n = len(_URL_RE.findall(body))
    if n:
        log(f"본문 URL {n}곳 제거(네이버가 링크 카드로 바꿔 문장을 부순다)")
        body = _URL_RE.sub("", body)
        body = re.sub(r"[ \t]{2,}", " ", body)
        body = re.sub(r"\(\s*\)|\[\s*\]", "", body)
    return body


if __name__ == "__main__":
    _no = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].isdigit() else "90"
    _dir = os.path.join(config.SOURCE_ROOT, f"gen_{config.today_str()}")
    generate(_dir, no=_no, log=_log)
    print(_dir)
