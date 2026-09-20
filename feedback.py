#!/usr/bin/env python3
"""홈판 피드백 한 번 → 다시 쓰기 (2026-09-18 에디님 규칙 5).

「피드백 한번 해보고 다시 작성하기. 특히 제목과 썸네일이 중요하니까, 항상 제목과 썸네일에
 모든 심혈을 기울여야 한다.」

★채점 기준은 에디님이 주신 '서이 경제 피드백봇'(이서이 강사 홈판 원리)이다.
  평가 8항목·배점·감점 규칙·제목 6장치·인트로 규칙은 **그대로** 옮겼다.
  🔴단 하나만 바꿨다 — **「내 돈」 → 「내 일·내 시간·내 돈」.**
  원본은 경제 글용이라 「내 주식·내 대출·내 세금」과 연결되지 않으면 감점한다.
  AI·자동화 글에 그대로 쓰면 모든 글이 그 항목에서 0점이 된다.
  AI 글에서 독자가 묻는 「그래서 나랑 무슨 상관?」은 **내 업무 시간·내 매출·내 비용·
  내 폰/노트북·내 일자리**다.

★프롬프트로 「잘 써라」라고만 하면 안 지켜진다(이 저장소에서 사진 개수·분량·제목 공식·도입부로
  네 번 증명됐다). 그래서 **점수를 받아 코드가 판단**한다:
  총점이 기준 미만이거나 제목에 고유명사가 없으면 → 추천 제목·수정 인트로·썸네일 문구로 바꾼다.
  바꾼 뒤 **한 번 더 채점해** 전후 점수를 남긴다(고쳤다고 말만 하지 않는다).
"""
from __future__ import annotations

import json
import re

from claude_cli import run_claude_p

#: 이 점수 미만이면 다시 쓴다. 🔴2026-09-18 에디님: "80점은 넘어야 되지 않겠어?"
REWRITE_BELOW = 80
#: 80점을 넘을 때까지 최대 몇 번 고쳐 쓰나. 한 번은 제목·인트로만 바꿔 66→68·71에 그쳤다(실측).
MAX_ROUNDS = 3

BODY_PROMPT = """아래 블로그 본문을 **피드백의 우선순위대로** 고쳐 써라. 목표는 홈판 피드백 80점 이상이다.

[반드시 고칠 것 — 우선순위 순]
{fixes}

[한 줄 총평]
{summary}

[지킬 것 — 어기면 고친 글을 버린다]
- `[사진N - …]`·`[표]`·`[표1]`·`[커넥트…]` 마커 줄은 **글자 하나 바꾸지 말고 그대로, 같은 순서로** 둔다.
- 분량은 지금과 비슷하게(±15%). 사실·수치·출처를 새로 지어내지 않는다(없는 건 빼라).
- 한 문장 한 줄, 짧게 끊는다. "안녕하세요 오늘은"·"정리해보겠습니다"·"결론적으로" 금지.
- 마지막은 독자가 댓글을 달고 싶어지는 질문 한 줄.
- 제목 줄(`제목:`)은 쓰지 마라 — 본문만.

[제목] {title}

[지금 본문]
{body}

[출력 — 고친 본문만. 설명·머리말·코드블록 없이]
"""

PROMPT = """당신은 네이버 홈판 **AI·자동화** 수익화 전문 피드백 코치다. 이름은 '서이 피드백봇'이다.
사용자의 목적은 'AI 글을 잘 쓰는 것'이 아니라 **'홈판에서 클릭과 체류를 만드는 글'**이다.
모든 평가는 홈판 적합성 기준으로 한다. 칭찬만 하는 피드백은 금지. 문제를 콕 집고, 고친 제목·문장을 직접 써준다.

[이 블로그]
40대에 모든 걸 잃고 코딩 한 줄 몰랐던 '에디'가 AI로 일을 자동화하며 겪은 것을 쓰는 블로그.
독자는 AI를 써보고 싶은 직장인·1인 사업자·부업러·초보.

[홈판 기준 — AI·자동화]
1. 홈판은 '뉴스 요약'이 아니라 **'내 일·내 시간·내 돈 연결형 해석 글'**이다.
   반드시 "그래서 내 업무 시간, 내 매출, 내 비용, 내 폰/노트북, 내 일자리에 무슨 영향이 있지?"가 보여야 한다.
2. 지금 뜨는 이슈를 잡아야 한다(신제품·새 모델·요금 변화·새 기능). "남들은 이미 아는데 나는 모른다"를 자극.
3. 제목은 심리를 건드린다 — 정보 격차 / 손실 회피 / 타이밍 압박 / 내 일·돈 궁금증.
4. 초보도 이해되게. 어려운 용어는 풀고, 구조·비교·사례·숫자로.
5. 전문성 = 구조 설명 + 리스크 + 일반인이 취할 행동.
6. 숫자와 비교는 신뢰다(금액·퍼센트·기간·버전·기준일·대상).
7. 기사 복붙 느낌 금지. 이슈 → 해석 → 내 일·돈 연결 → 비교 → 전망 → 질문.
8. 🔴**권위 있는 고유명사**(사람들이 실제로 검색창에 치는 제품·회사·서비스·인물 이름)가 제목에 있어야 한다.
   「업무 자동화 도구」 같은 분류어는 아무도 안 친다. 「챗GPT」「아이폰」「클로바노트」를 친다.

[8가지 평가 — 총 100점]
① 홈판 적합성 20 — 스크롤을 멈추게 하나. 기사 요약형·검색 키워드 나열형·이슈 연결 약함은 감점.
② 제목 후킹력 20 — 정보격차·손실회피·타이밍압박·내일돈연결·숫자·비교·반전·질문 중 **최소 2개**. 결론이 다 보이면·키워드 나열이면·이모티콘 남발이면 감점.
③ 내 일·시간·돈 연결력 15 — "그래서 나랑 무슨 상관?"에 답하나.
④ 인트로 흡입력 10 — 첫 3줄이 4번째 줄을 읽게 만드나. "안녕하세요 오늘은", 배경 설명부터, 첫 줄에 결론, 뉴스 브리핑식 시작은 감점. 체감 변화·같은 조건의 차이·"왜 나만?"·숫자로 열면 가점.
⑤ 이슈·정보·해석 균형 10 — 이슈 3 : 해석 4 : 내 일·돈 정보 3.
⑥ 심리 장치 + 반박 제거 10 — 손실회피·정보격차·사회적증거·권위·반박제거("모든 사람에게 해당되진 않습니다")·미래상상.
⑦ 전문성·신뢰도 10 — 구조 설명·리스크·행동 포인트·수치/기준일/대상. 출처 없는 단정·과장 감점.
⑧ AI 문체·가독성·마무리 CTA 5 — "결론적으로 말씀드리면"·"정리해보겠습니다"·긴 문단·반복·질문 없이 끝남은 감점.

[즉시 강한 감점] 기사 요약으로 끝남 / 내 일·돈 연결 없음 / 제목에서 답을 다 줌 / 숫자·비교 없음 /
리스크 언급 없음 / "안녕하세요, 오늘은" / "~에 대해 알아보겠습니다" / "정리해보겠습니다" / 이모티콘 남발.

[썸네일] 제목과 같이 **클릭을 결정하는 한 장**이다. 큰 글씨 3~8자(핵심 고유명사나 숫자), 작은 글씨 8~16자(궁금증·손실회피).
제목과 같은 말을 반복하지 말고, 제목이 못 준 한 방을 준다.

[평가할 글]
제목: {title}

본문:
{body}

[출력 — JSON 하나만. 설명·코드블록 표시 없이]
{{"총점": 0,
 "점수": {{"홈판적합성": 0, "제목후킹력": 0, "내일시간돈연결력": 0, "인트로흡입력": 0,
          "이슈정보해석균형": 0, "심리장치반박제거": 0, "전문성신뢰도": 0, "문체가독성CTA": 0}},
 "한줄총평": "핵심 문제를 직설적으로 한 문장",
 "제목_고유명사": "지금 제목에 든 권위 있는 고유명사(없으면 빈 문자열)",
 "반드시고칠것": ["1순위 — 왜 문제인지 / 어떻게 고치는지", "2순위 …", "3순위 …"],
 "수정제목": [{{"제목": "…", "장치": "정보격차+숫자"}}, … 최소 5개],
 "추천제목": "수정제목 중 가장 강한 것. 반드시 권위 있는 고유명사 포함, 45자 이내",
 "추천제목_고유명사": "추천제목에 든 고유명사",
 "수정인트로": "첫 3~4줄. 줄마다 \\n. 짧게 끊고 내 일·시간·돈 체감이 느껴지게",
 "썸네일": {{"큰글씨": "3~8자", "작은글씨": "8~16자"}},
 "홈판통과확률": {{"현재": 0, "수정후": 0}}}}
"""


def _parse(out: str) -> dict:
    m = re.search(r"\{.*\}", out or "", re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return {}


def review(title: str, body: str, timeout: int = 240) -> dict:
    """제목·본문을 채점한다. 실패하면 빈 dict."""
    clean = re.sub(r"\[\[[^\]]*\]\]", "", body or "")
    clean = re.sub(r"^제목:.*\n", "", clean)
    return _parse(run_claude_p(PROMPT.format(title=title, body=clean[:6000]), timeout=timeout))


_MARK = re.compile(r"^\s*(\[사진\d+[^\]]*\]|\[표1?\]|\[커넥트[^\]]*\])\s*$", re.M)


def _markers(body: str) -> list:
    return [m.group(1).strip() for m in _MARK.finditer(body or "")]


def rewrite_body(title: str, body: str, fb: dict, log=print, tag: str = "") -> str:
    """피드백의 「반드시 고칠 것」대로 본문을 고쳐 쓴다. 조건을 어기면 **원래 본문**을 돌려준다.

    ★사진·표 마커가 하나라도 바뀌거나 순서가 달라지면 버린다 — 업로드 단계가 마커로
      사진·표를 끼우므로, 마커가 틀어지면 글이 깨진다.
    """
    head = body.splitlines()[0] if body.startswith("제목:") else ""
    core = re.sub(r"^제목:.*\n", "", body)
    fixes = "\n".join(f"{i+1}. {x}" for i, x in enumerate(fb.get("반드시고칠것") or [])) or "(없음)"
    out = run_claude_p(BODY_PROMPT.format(fixes=fixes, summary=fb.get("한줄총평", ""),
                                          title=title, body=core[:9000]), timeout=420) or ""
    out = re.sub(r"^```\w*\s*|\s*```$", "", out.strip())
    out = re.sub(r"^제목:.*\n", "", out)
    if not out.strip():
        log(f"{tag}[피드백] 본문 고쳐쓰기 빈 응답 → 원래 본문 유지")
        return body
    if _markers(out) != _markers(core):
        log(f"{tag}[피드백] 🔴고쳐 쓴 본문의 사진·표 마커가 달라짐({len(_markers(core))}→{len(_markers(out))}) → 버림")
        return body
    ratio = len(out) / max(1, len(core))
    if not 0.85 <= ratio <= 1.3:
        log(f"{tag}[피드백] 🔴고쳐 쓴 본문 분량이 {ratio:.0%} → 버림(85~130%만 허용)")
        return body
    return (head + "\n\n" if head else "") + out.strip() + "\n"


def _intro_span(body: str) -> tuple[int, int]:
    """본문에서 '인트로'(제목 줄 뒤 ~ 첫 사진/소제목 마커 전) 줄 범위."""
    lines = body.splitlines()
    start = 1 if lines and lines[0].startswith("제목:") else 0
    end = start
    for k in range(start, len(lines)):
        if re.match(r"^\s*\[(사진|표|인용)", lines[k]):
            break
        end = k + 1
    return start, end


def apply(title: str, body: str, fb: dict, log=print, tag: str = "") -> tuple[str, str, dict, bool]:
    """피드백을 반영해 (제목, 본문, 썸네일문구, 바꿨는지)를 돌려준다.

    바꾸는 조건 — 둘 중 하나라도:
      · 총점 < REWRITE_BELOW
      · 지금 제목에 권위 있는 고유명사가 없다(에디님 규칙 4)
    ★추천 제목에 고유명사가 없으면 제목은 바꾸지 않는다(고유명사 없는 걸로 갈아끼우면 의미가 없다).
    """
    thumb = fb.get("썸네일") or {}
    total = int(fb.get("총점") or 0)
    no_noun = not (fb.get("제목_고유명사") or "").strip()
    if not fb or (total >= REWRITE_BELOW and not no_noun):
        return title, body, thumb, False

    new_title = title
    rec = (fb.get("추천제목") or "").strip()
    if rec and (fb.get("추천제목_고유명사") or "").strip() and 6 <= len(rec) <= 45:
        new_title = rec
    elif no_noun:
        # 추천 제목에도 고유명사가 없으면 **바꾸지 않는다** — 고유명사 없는 제목끼리 갈아끼우는 건
        # 규칙 4를 못 지킨 채 바꿨다는 기록만 남긴다. 대신 눈에 띄게 남긴다.
        log(f"{tag}🔴[피드백] 추천 제목에도 고유명사가 없어 제목은 그대로 둡니다: {rec[:40]}")

    new_body = body
    intro = (fb.get("수정인트로") or "").strip()
    if intro:
        s, e = _intro_span(body)
        lines = body.splitlines()
        if e > s:
            intro_lines = []
            for ln in intro.splitlines():
                ln = ln.strip()
                if ln:
                    intro_lines += [ln, ""]
            new_body = "\n".join(lines[:s] + [""] + intro_lines + lines[e:])
            new_body = re.sub(r"\n{3,}", "\n\n", new_body)

    why = f"총점 {total}" + (" · 제목에 고유명사 없음" if no_noun else "")
    log(f"{tag}[피드백] {why} → 다시 씀")
    if new_title != title:
        log(f"{tag}[피드백]   제목: {title}")
        log(f"{tag}[피드백]      → {new_title}")
    return new_title, new_body, thumb, (new_title != title or new_body != body)


def report(fb: dict, fb2: dict | None, before: str, after: str) -> str:
    """에디님이 볼 피드백 기록(원고 옆에 저장)."""
    sc = fb.get("점수") or {}
    lines = ["# 홈판 피드백 (서이 피드백봇 · AI·자동화판)", "",
             f"**한 줄 총평** — {fb.get('한줄총평', '')}", "",
             f"| 항목 | 점수 |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in sc.items()]
    lines += [f"| **총점** | **{fb.get('총점', '?')}** |", ""]
    if fb2:
        lines += [f"**다시 쓴 뒤 재채점: {fb.get('총점', '?')} → {fb2.get('총점', '?')}점**", ""]
    lines += ["## 반드시 고칠 것"] + [f"{i+1}. {x}" for i, x in enumerate(fb.get("반드시고칠것") or [])]
    lines += ["", "## 제목", f"- 원래: {before}", f"- 최종: {after}", "", "### 수정 제목 후보"]
    lines += [f"- {c.get('제목')}  ({c.get('장치')})" for c in fb.get("수정제목") or []]
    th = fb.get("썸네일") or {}
    lines += ["", f"## 썸네일 문구 — 큰 글씨 「{th.get('큰글씨', '')}」 / 작은 글씨 「{th.get('작은글씨', '')}」"]
    pr = fb.get("홈판통과확률") or {}
    lines += ["", f"홈판 통과 확률(피드백봇 판단): 현재 {pr.get('현재', '?')}% → 수정 후 {pr.get('수정후', '?')}%"]
    return "\n".join(lines) + "\n"


def run(title: str, body: str, log=print, tag: str = "") -> tuple[str, str, dict, str]:
    """채점 → 80점 미만이거나 제목에 고유명사가 없으면 고쳐 쓰기 → 재채점을 **최대 MAX_ROUNDS번**.

    ★가장 높은 점수의 판을 쓴다(고친 게 더 나쁘면 이전 판이 남는다).
    ★끝까지 80점을 못 넘으면 보고서 맨 위와 로그에 🔴로 남긴다 — 조용히 넘기지 않는다.
    반환: (최종 제목, 최종 본문, 썸네일 문구, 보고서)
    """
    fb = review(title, body)
    if not fb:
        log(f"{tag}[피드백] 채점 실패 — 원고 그대로 진행")
        return title, body, {}, ""
    first = fb
    best = (int(fb.get("총점") or 0), title, body, fb)
    hist = [int(fb.get("총점") or 0)]
    log(f"{tag}[피드백] 1차 총점 {hist[0]} · 고유명사 «{fb.get('제목_고유명사') or '없음'}» · "
        f"{fb.get('한줄총평', '')[:50]}")
    cur_t, cur_b, cur_fb = title, body, fb
    for rnd in range(1, MAX_ROUNDS + 1):
        passed = (int(cur_fb.get("총점") or 0) >= REWRITE_BELOW
                  and (cur_fb.get("제목_고유명사") or "").strip())
        if passed:
            break
        t2, b2, _th, _ = apply(cur_t, cur_b, cur_fb, log, tag)   # 제목·인트로
        b2 = rewrite_body(t2, b2, cur_fb, log, tag)               # 본문
        fb2 = review(t2, b2)
        if not fb2:
            log(f"{tag}[피드백] {rnd}회차 재채점 실패 → 중단")
            break
        sc = int(fb2.get("총점") or 0)
        hist.append(sc)
        log(f"{tag}[피드백] {rnd}회차 고쳐 쓰기 → {sc}점")
        if sc > best[0]:
            best = (sc, t2, b2, fb2)
        cur_t, cur_b, cur_fb = t2, b2, fb2
    score, f_title, f_body, f_fb = best
    ok = score >= REWRITE_BELOW and (f_fb.get("제목_고유명사") or "").strip()
    path = " → ".join(str(x) for x in hist)
    if ok:
        log(f"{tag}[피드백] ✅ {path}점 — 80점 통과")
    else:
        log(f"{tag}🔴[피드백] {path}점 — {MAX_ROUNDS}번 고쳐도 80점 미달. 최고점({score}) 판으로 진행")
    rep = report(first, f_fb if len(hist) > 1 else None, title, f_title)
    rep = (f"> {'✅ 통과' if ok else '🔴 80점 미달'} — 점수 흐름 {path}\n\n") + rep
    return f_title, f_body, (f_fb.get("썸네일") or first.get("썸네일") or {}), rep
