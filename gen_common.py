"""생성(원고 자동 작성) 공통: 테마 목록, 리소스 가이드 추출, 에디 프로필."""
from __future__ import annotations

import os
import re

# 갤럽 34테마 (한국어, 영문) — 목차 순서
THEMES = [
    ("성취", "ACHIEVER"), ("행동", "ACTIVATOR"), ("적응", "ADAPTABILITY"), ("분석", "ANALYTICAL"),
    ("정리", "ARRANGER"), ("신념", "BELIEF"), ("주도력", "COMMAND"), ("커뮤니케이션", "COMMUNICATION"),
    ("승부", "COMPETITION"), ("연결성", "CONNECTEDNESS"), ("공정성", "CONSISTENCY"), ("회고", "CONTEXT"),
    ("심사숙고", "DELIBERATIVE"), ("개발", "DEVELOPER"), ("체계", "DISCIPLINE"), ("공감", "EMPATHY"),
    ("집중", "FOCUS"), ("미래지향", "FUTURISTIC"), ("화합", "HARMONY"), ("발상", "IDEATION"),
    ("포용", "INCLUDER"), ("개별화", "INDIVIDUALIZATION"), ("수집", "INPUT"), ("지적사고", "INTELLECTION"),
    ("배움", "LEARNER"), ("최상화", "MAXIMIZER"), ("긍정", "POSITIVITY"), ("절친", "RELATOR"),
    ("책임", "RESPONSIBILITY"), ("복구", "RESTORATIVE"), ("자기확신", "SELF-ASSURANCE"),
    ("존재감", "SIGNIFICANCE"), ("전략", "STRATEGIC"), ("사교성", "WOO"),
]
THEME_KO = [t[0] for t in THEMES]
THEME_EN = {ko: en for ko, en in THEMES}

# ─────────────────────────────────────────────────────────────────────────────
# 🔴 메타응답 판정 — LLM이 '제목' 대신 **자기 소감·확인 멘트**를 뱉는 것을 걸러낸다.
#
# ★2026-08-12 실제 사고: 쇼핑 04편이 「제목만 출력하라는 요청이네요.」라는 제목으로
#   **공개 발행됐다**(14:52 예약). title_hook._first_title_line 이 '6자 이상 첫 줄'을
#   그대로 제목으로 썼고, 발행 직전 백스톱도 없었다.
#   → 제목을 만드는 모든 경로와 pipeline 발행 직전, **양쪽에서** 이 함수로 막는다.
#
# 판정 기준: '제목/한 줄/문장' + '출력·요청·작성' 류가 붙은 문장, 대화 응답 서두,
#           그리고 지시문을 되풀이하는 말투. 실제 제목에 잘 안 나오는 조합만 골랐다.
_META_TITLE = [
    re.compile(r"(제목|한\s*줄|한줄|문장|본문)[^.!?]{0,14}"
               r"(출력|요청|드릴|드립니|쓰겠|쓰면|작성|만들|뽑|알려)"),
    re.compile(r"(라는\s*요청|하라는|말씀하신|말씀대로|요청하신|요청대로|지시(하신|대로)|"
               r"규칙(대로|에\s*따라)|공식에\s*따라|프롬프트)"),
    # ★2026-08-16 실측: 「작품 정보글 제목 후보 10개입니다.」가 제목으로 임시저장됐다.
    #   LLM이 목록 앞에 붙인 **머리말**이다. 위 패턴들은 '제목' 뒤 14자 안에 출력/요청류를
    #   찾는데 여기엔 '후보 10개입니다'가 와서 빗나갔고, 정보형의 `^(제목|출력|규칙…)` 검사도
    #   '작품'으로 시작해 통과했다. → 목록을 소개하는 말투 자체를 잡는다.
    re.compile(r"(제목|후보|목록|리스트|버전|안)\s*\d{1,2}\s*개?\s*(입니다|이에요|예요|드립니다|드려요)"),
    re.compile(r"\d{1,2}\s*개\s*(입니다|이에요|예요|드립니다|드려요)\s*[.!]?$"),
    re.compile(r"(다음|아래)\s*(과|와)?\s*같습니다|참고하세요|골라\s*보세요"),
    # '네,' '예.' 처럼 **구두점이 따라오는 경우만** 대화 서두로 본다.
    #  (그냥 ^예 로 하면 「'예약' 지금 걸어야…」 같은 정상 제목이 걸린다 — 실측 오탐)
    re.compile(r"^(?:(?:네|예)\s*[,.…]|알겠습니다|알겠어요|물론|좋습니다|죄송합|확인했)"),
    # ★2026-08-12 실측: 중첩 실행된 claude -p 가 **자기를 '승인이 필요한 에이전트'로 착각**해
    #   「실행하려면 권한 승인이 필요합니다…」 같은 답을 준다. 이건 위 말투 규칙에 안 걸린다.
    re.compile(r"(승인|권한|실행하려면|스크립트|subprocess|python|claude\s*-p|터미널|"
               r"붙여넣|명령|커맨드|코드\s*경로)"),
    # ★'주세요'는 넣지 않는다 — 「"아내를 없애주세요" 다음 날…」처럼 **인용 대사**에 흔하다(실측 오탐).
    re.compile(r"(주시면|드릴게요|드리겠습니다|보여드리|진행할\s*수\s*있|다음과\s*같이)"),
]

#: 제목이 지켜야 할 물리 규격. 홈판 제목은 40자 내외 한 줄이다(프롬프트 규칙과 같은 값).
_TITLE_MAX = 60


def looks_meta(t: str) -> bool:
    """제목 후보가 'LLM이 사람에게 하는 말'이거나 제목 규격을 벗어나면 True.

    말투(위 패턴)만으로는 새로운 헛소리 유형을 다 못 잡는다 → **구조**도 같이 본다:
    여러 줄, 백틱/코드블록, 60자 초과는 어떤 경우에도 블로그 제목이 아니다.
    """
    t = (t or "").strip()
    if not t:
        return True
    if "\n" in t or "`" in t or len(t) > _TITLE_MAX:
        return True
    # 🔴2026-09-07: LLM이 «주제를 안 줬으니 되묻는» 응답도 제목으로 새어 나왔다.
    #   실제로 나온 것 — «무엇에 대한 글인가요? 예를 들면:» /
    #   «AI 최신소식 — 오늘 다루는 뉴스 한 줄» / «연예/정보형 — 작품명이나 인물»
    #   앞의 말투 패턴(_META_TITLE)은 «~네요/~하겠습니다» 계열만 잡아서 전부 통과했다.
    #   ★콜론으로 끝나는 줄은 제목이 아니라 **안내문의 머리말**이다. 실제 발행 제목 중엔 없다.
    if t.endswith((":", "：")):
        return True
    if re.search(r"무엇에 대한|어떤 주제|어떤 글인|어떤 내용|예를 들면|예시\s*[:：]|"
                 r"작품명이나|주제를 (?:알려|정해|말씀)", t):
        return True
    # 🔴2026-09-08: «1. (구어 인용 + 반전)»이 제목으로 발행 직전까지 갔다.
    #   LLM이 후보 목록을 «번호 + 장치 라벨 + 줄바꿈 + 실제 제목»으로 내놨는데
    #   첫 줄(라벨)을 제목으로 집었다. 말투 패턴엔 안 걸린다 — **구조**로 잡아야 한다.
    #   ★괄호로만 이뤄진 줄은 제목이 아니라 **라벨**이다(본문 임시 제목
    #     «(임시 제목 한 줄 - 뒤에서 교체됨)»도 같이 걸린다).
    #   ⚠️좁게 잡는다: «번호 + 괄호뿐» 또는 «통째로 괄호뿐»만. 실제 제목에 괄호가
    #     들어가는 경우(«'나는 솔로'(SBS)…»)를 잡아먹으면 안 된다.
    if re.match(r"^\s*\d+\s*[.)]\s*[(\[（]", t) or re.fullmatch(r"\s*[(\[（].*[)\]）]\s*", t):
        return True
    # 🔴🔴2026-09-09 사고: «You've hit your session limit · resets 5am (Asia/Seoul)» 이
    #   제목이 되어 **예약 발행까지 나갔다.** `claude -p` 가 한도에 걸리면 종료코드 0으로
    #   영문 안내를 뱉는데, 위 패턴은 전부 한글이라 하나도 안 걸렸다.
    #   ★우리 블로그 제목은 **반드시 한글을 포함한다** — 한글이 한 글자도 없으면 제목이 아니다.
    #     실측: 발행 제목 200개 오탐 0. (1차 방어는 `claude_cli.UsageLimitError`이고 이건 그물이다)
    if not re.search(r"[가-힣]", t):
        return True
    # 🔴2026-09-12 사고: «"누구였지?"는 이미 쓴 꼬리라 피하고, 서로 다른 후킹 장치로 5개 뽑았습니다.»
    #   가 02편 제목이 되어 네이버에 임시저장됐다. LLM이 **자기 작업을 설명한 문장**인데,
    #   따옴표로 시작하고 «~습니다»로 끝나 기존 말투 패턴에 하나도 안 걸렸다.
    #   ★좁게 잡는다 — «N개 뽑았습니다» / «후킹·장치·후보 … N개» / «…피하고 …뽑/골랐» 형태만.
    #     실제 제목에 흔한 «…뽑혔습니다»(수동)·«…골랐습니다»(출연자가 고름)는 건드리지 않는다.
    if (re.search(r"\d+\s*개\s*(?:를\s*)?(?:뽑았|골랐|만들었|정리했|준비했)습니다", t)
            or re.search(r"(?:후킹|장치|제목\s*후보|후보)\S*\s*(?:로|으로)?\s*\d+\s*개", t)
            or re.search(r"(?:피하고|제외하고|빼고)\s*[^\n]{0,24}(?:뽑았|골랐|만들었)", t)):
        return True
    return any(p.search(t) for p in _META_TITLE)


# 강점코칭(갤럽) 리소스는 수강생 배포판에 넣지 않는다 — 없으면 아래 함수가 빈 문자열을 준다.
GUIDE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "docs", "리소스_가이드.txt")

#: 배포판의 화자는 '수강생 자신'이다 — 정체성은 내정보.txt·블로그분석.md·내이야기.md 에서 온다.
EDDIE_PROFILE = """[블로거 — 1인칭 화자]
- 정체성·말투·경험은 내정보.txt·블로그분석.md·내이야기.md 에서 온다(코드에 박지 않는다).
- 톤: 솔직하고 꾸밈없음. 직접 해본 사람의 담백한 1인칭.
- 규칙: 내 경험 앵커는 주제와 자연스럽게 맞을 때 1개 정도 짧게. 억지로 매번 넣지 말 것.
- 🔴 수익·효과를 약속하지 않는다("제 경우"와 기간을 붙인다)."""


def clear_no(out_dir: str, no: str) -> None:
    """재생성 시 같은 편 번호의 기존 산출물({no}_*)을 지운다(중복 누적 방지)."""
    import glob
    for f in glob.glob(os.path.join(out_dir, f"{no}_*")):
        try:
            os.remove(f)
        except OSError:
            pass


def extract_theme_section(theme_ko: str, max_chars: int = 6000) -> str:
    """리소스 가이드에서 해당 테마 섹션 텍스트 추출(다음 테마 전까지, 길면 잘라냄)."""
    try:
        with open(GUIDE_PATH, encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except Exception:  # noqa: BLE001
        return ""
    en = THEME_EN.get(theme_ko, "")
    # 실제 본문 섹션 시작 앵커: "테마명(ENGLISH) 테마가 특히 강한 사람" (목차·이미지 건너뜀)
    anchor = rf"{re.escape(theme_ko)}\({re.escape(en)}\)\s*테마가 특히 강한 사람"
    start_m = re.search(anchor, text)
    if not start_m:
        # 폴백: 트레이드마크 헤더
        start_m = re.search(rf"{re.escape(theme_ko)}\({re.escape(en)}\)\s*[™®]", text)
    if not start_m:
        return ""
    start = start_m.start()
    # 다음 테마의 같은 앵커까지
    idx = THEME_KO.index(theme_ko)
    end = len(text)
    for nxt_ko, nxt_en in THEMES[idx + 1:]:
        m = re.search(rf"{re.escape(nxt_ko)}\({re.escape(nxt_en)}\)\s*테마가 특히 강한 사람", text[start + 50:])
        if m:
            end = start + 50 + m.start()
            break
    section = text[start:end].strip()
    return section[:max_chars]


if __name__ == "__main__":
    import sys
    t = sys.argv[1] if len(sys.argv) > 1 else "집중"
    sec = extract_theme_section(t)
    print(f"[{t}({THEME_EN.get(t)})] 추출 {len(sec)}자")
    print(sec[:600])


_PHOTO_MARK = re.compile(r"\[사진\d+")


def enough_photos(body: str, min_n: int = 10, per_paras: int = 11, cap: int = 14) -> bool:
    """사진 마커가 **글 길이에 맞게** 들어갔는지. 본문 검증(`_ok`)에서 쓴다.

    🔴2026-09-02 에디님 지적: "글은 많아졌는데 사진이 6~7장이니까 이상해졌어."
      문제는 개수가 아니라 **비율**이다. 실측(9/2) — 연예 8편은 문단 92~115에 사진 10~12장
      (문단/사진 6.6~11.2)인데, AI 최신소식만 문단 123에 사진 7장(17.6)이라 혼자 성겼다.

    ★프롬프트만으로는 두 번 놓쳤다(8/31 연예 7장, 9/2 뉴스 7장). 그래서 **받은 응답을
      검사해서 모자라면 다시 받는다**(run_claude_p_retry의 ok 콜백). 재시도가 소진되면
      마지막 응답을 그대로 쓰므로 글이 죽지는 않는다 — 손해 없이 세 번 더 시도하는 장치다.

    ★min_n 기본값은 **10**이다(2026-09-02 에디님: "연예, 9개 이상 맞아?").
      프롬프트가 «10~12개»라고 지시하는데 코드 하한이 9면 **지시보다 느슨해서** 9장짜리가
      그냥 통과한다. 검증할 값은 지시한 값과 같아야 한다.
      실측(9/2 연예 8편): 사진 10·11·11·11·11·11·12·12장 — 하한을 10으로 올려도 전부 통과한다.

    per_paras: 몇 문단마다 사진 한 장인지. cap: 아무리 길어도 이 장수를 넘겨 요구하지 않는다
    (그림 한 장에 그록 기준 50초라 무한정 늘리면 새벽 배치가 아침 예약을 못 맞춘다).
    """
    n = len(_PHOTO_MARK.findall(body or ""))
    paras = len([l for l in (body or "").splitlines() if l.strip()])
    want = min(cap, max(min_n, round(paras / per_paras)))
    return n >= want


_PHOTO_FULL = re.compile(r"\[사진\d+[^\]]*\]")


def enough_length(body: str, min_chars: int = 1300) -> bool:
    """본문이 목표 분량을 넘겼는지. **공백과 사진 마커를 뺀 글자 수**로 센다.

    🔴글 종류마다 기준이 다르다(2026-09-07 홈판 실측으로 갈랐다).
      · 연예글 **1,300자** — 연예 홈판 18편 중앙값이 **1,272자**였다
      · AI글  **2,000자** — 전체 홈판 22편 중앙값이 **2,428자**였다. AI글은 그 자리에서 경쟁한다
      처음엔 둘 다 1,500이었는데, 연예엔 과하고(멀쩡한 글이 재시도로 걸렸다) AI엔 모자랐다.
      ★기준은 «에디님이 정한 숫자»가 아니라 **그 판을 재서 나온 숫자**여야 한다.
    ★왜 코드로도 재나 — 분량은 이 저장소에서 **제일 자주 어긋나는 값**이다.
      «3,000자»라고 프롬프트에 써도 1,300자로 나왔고(2026-09-01), «문단 100개 이상»으로
      바꿔 써도 90문단·1,429자가 나왔다(2026-09-05 81편). 프롬프트만으로는 안 지켜진다.
    ★사진 마커를 빼고 세는 이유: 마커는 업로드하면 사진으로 바뀌어 **본문 글자가 아니다.**
      에디님도 «[사진…] 빼니까 공백 제외 1169자밖에 안 된다»고 그렇게 세셨다(2026-09-01).
    """
    t = _PHOTO_FULL.sub("", body or "")
    return len(re.sub(r"\s", "", t)) >= min_chars


# ─────────────────────────────────────────────────────────────
#  대괄호 정리 (2026-09-15 에디님: "[......] 이 대괄호가 있는 건 다 지워야 돼")
# ─────────────────────────────────────────────────────────────
_MARKER_OPEN = re.compile(r"\[(?=사진|표|커넥트)")


def flatten_marker_brackets(text: str) -> str:
    """마커(`[사진…]`·`[표]`·`[커넥트…]`) **안쪽의** 대괄호를 지운다.

    🔴2026-09-15 05편: 유튜브 채널 이름이 «이지금 [IU Official]»이라 마커 안에 `]`가 하나 더 생겼고,
      마커를 떼는 정규식(`[^\]]*\]`)이 **첫 `]`에서 끊어** 뒤쪽
      «' / 유튜브 검색: 아이유 이지금 크레이지 소울메이트 떡집 오픈런]»이 본문 글자로 10곳 남았다.
    ★마커의 끝은 «다음 마커가 시작하기 전(또는 줄 끝)까지의 **마지막** `]`»로 본다.
      괄호 짝으로 세지 않는 이유: 이미 한 번 깨진 마커는 `[`가 `]`보다 많아 짝이 영영 안 맞는다(실측).
    """
    if not text or "[" not in text:
        return text
    lines = []
    for line in text.split("\n"):
        starts = [m.start() for m in _MARKER_OPEN.finditer(line)]
        if not starts:
            lines.append(line)
            continue
        buf = [line[:starts[0]]]
        for k, st in enumerate(starts):
            seg = line[st: starts[k + 1] if k + 1 < len(starts) else len(line)]
            end = seg.rfind("]")
            if end <= 0:
                buf.append(seg)
                continue
            inner = seg[1:end].replace("[", "").replace("]", "")
            buf.append("[" + inner + "]" + seg[end + 1:])
        lines.append("".join(buf))
    return "\n".join(lines)


def strip_brackets(s: str) -> str:
    """이름·캡션에서 대괄호만 뺀다 — «이지금 [IU Official]» → «이지금 IU Official»."""
    return re.sub(r"[ \t]{2,}", " ", (s or "").replace("[", "").replace("]", "")).strip()

