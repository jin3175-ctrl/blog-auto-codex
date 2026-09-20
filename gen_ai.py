"""홈판 글 '반자동' 생성기 (수강생 배포판).

셀럽/강점 아님. 축=AI 실전(자동화·수익화·부업). 화자=40대 밑바닥서 AI로 산 에디.
- 소재는 소재뱅크(~/홈판자료/AI실전_소재뱅크30.md) 또는 인자로 받은 topic.
- 완전 무인 X → 초안 + [[경험 슬롯]]을 남긴다. 에디님이 경험 채우고 검토 후 발행(저품질 회피 필수).
- 넓은 후킹 제목(직장인·결과·초보). 연예인 후킹 X.

사용: python3 gen_ai.py "AI로 블로그 글 자동 발행, 진짜 되는지 3개월 해봤습니다"
"""
from __future__ import annotations

import json
import os
import re
import sys

from claude_cli import run_claude_p, run_claude_p_retry
import celeb_sources as S
import config
import formula
import gen_common as G
import gen_templates as T
import gemini_thumb

# 네이버 블로그 주제 디렉토리(2026-07 실측): 30 = IT·컴퓨터(AI 주제축) / 0 = 전체 주제(홈판 전체).
# 주제는 AI축(dir=30)에서, '제목·본문·썸네일 공식'은 전체 홈판(dir=0) 지금 잘 나가는 것에서 뽑는다.
DIR_IT = 30
DIR_HOME = 0

#: 화자 프로필 — 정체성은 코드에 박지 않고 내정보.txt·블로그분석.md 에서 온다(수강생 배포판).
def _profile() -> str:
    try:
        import myinfo
        topic = myinfo.topic() or "내 블로그 주제"
        name = myinfo.blog_name()
    except Exception:  # noqa: BLE001
        topic, name = "내 블로그 주제", "내 블로그"
    return f"""[화자 — 1인칭, 블로그 «{name}»]
- 내 블로그 주제는 «{topic}»이다. 이 주제를 직접 겪고 정리하는 사람의 1인칭으로 쓴다.
- 목적: 자기 홍보·판매가 아니라, 검색·홈피드에서 만난 독자에게 '직접 해보고 남은 쓸모'를 주는 것.
- 톤: 과장 없음. "해봤더니 이렇더라" 같은 담백한 태도. 어투는 항상 **존댓말**.
- 🔴 수익·효과를 약속하지 않는다("제 경우"와 기간을 붙인다)."""


#: gen_ai_news 등이 이 이름을 import 하므로 상수로도 남긴다(내용은 generate 에서 동적으로 덮어쓴다).
EDI_AI_PROFILE = _profile()

# 경험 문단 재료 = 내이야기.md (story_pick). 코드에 개인 서사를 박지 않는다.
# ★과장·지어내기 금지: 없는 수치·날짜·매출은 만들지 말 것.
# ★비어 있으면 **글을 멈추지 말고**, 경험 문단 없이 정보·해석 중심으로 쓴다(지어내지 않는다).
EDI_STORY = """[내 이야기 — 아직 등록된 개인 경험이 없다]
- 경험담을 지어내지 말 것. 이번 글은 1인칭 경험 문단 없이 **정보·해석·비교 중심**으로 쓴다.
- (나중에 내이야기.md 를 채우면 다음 글부터 내 경험이 한 문장씩 들어간다.)"""


def _my_story() -> str:
    """내이야기.md 의 경험 문장들을 경험 문단 재료로 넘긴다(없으면 기본 안내)."""
    try:
        import story_pick
        items = story_pick.items()
        if items:
            head = ("[내 이야기 — 경험 문단은 아래 내 실제 경험에만 뿌리를 둔다. "
                    "이 밖의 수치·날짜·실적은 지어내지 말 것. 주제와 자연스럽게 맞는 1개를 짧게]\n")
            return head + "\n".join(f"- {s}" for s in items[:8])
    except Exception:  # noqa: BLE001
        pass
    return EDI_STORY

#: ★★제목 규칙은 **코드에 박지 않는다**(2026-08-17 에디님 지시).
#
#  에디님 말: "제목은 강제규정을 짓지 말고, 매일 그날의 홈판 제목 30개를 분석하고
#             공식화·패턴화한 다음, 그 패턴화한 것이 공식이 되는 거잖아?
#             그러니까 매일 홈판의 패턴에 따라 공식이 달라지는 거지."
#
#  왜 이 지시가 맞나 — 실패로 증명됐다. 예전 프롬프트는 「오늘의 공식」을 넣어두고도
#  바로 아래에 «2026-08-06 실측 구조를 **최우선으로** 따른다»는 고정 블록을 뒀다.
#  뒤에 나온 '최우선'이 이겨서, 매일 새로 뽑은 공식은 사실상 무시됐다.
#  그 결과 8/17 AI 실전 3편이 전부 «…딴판이었습니다»로 나갔다(조회수 0·2·2).
#  고정 구조를 하나 박으면 **그 틀로 수렴**하고, 홈판이 바뀌어도 따라가지 못한다.
#
#  → 여기 남기는 것은 **위생 규칙만**이다(길이·금지어·형식). '어떻게 후킹하냐'는
#    전부 `{title_formula}`(그날 홈판 30개에서 추출)와 `{live_titles}`(실제 위너)가 정한다.
#    중복 회피는 `{history_block}`이 담당한다(남용된 마무리 표현을 자동으로 금지).
# 🔴2026-08-29: AI 글 제목을 **검색용**으로 바꿨다(에디님 결정).
#   왜: 유입 실측이 «홈판 77.9% / 검색 2%»였고, AI 글은 편당 **1회**였다.
#   원인은 AI 글을 홈판 공식(궁금하게 끝내기)으로 썼기 때문이다 —
#   홈판은 AI를 안 밀어주고(연예를 민다), 제목에 검색어가 없어 검색에도 안 걸렸다.
#   두 판 사이에 떨어져 있었던 것이다.
#   → 연예 7편은 홈판용 그대로 두고, **AI 1편만 검색용**으로 돌린다.
#     C-RANK는 «한 주제를 꾸준히»가 근거라 주제도 «AI로 블로그·업무 자동화» 한 갈래로 좁힌다.
#     조회수는 당장 안 늘어도 된다. 이 한 편은 **쌓으려고** 쓰는 글이다.
TITLE_PROMPT = """너는 네이버 검색에 걸리는 제목을 만드는 사람이다. 아래 주제로 제목 5개.

[이 제목의 목적 — 홈판이 아니라 **검색**이다]
이 글은 홈피드 조회수를 노리지 않는다. 사람들이 **실제로 검색창에 치는 말**로 시작해서,
그 검색에서 잡히는 게 목적이다. 궁금증만 남기고 끝나는 홈판식 제목은 여기서 쓰지 않는다.

[규칙 — 이게 전부다]
- **앞머리에 검색어를 박는다.** 사람이 진짜 칠 법한 말이어야 한다.
  좋은 예: "챗GPT 식단표 만드는 법" / "블로그 자동화 프로그램" / "AI 글쓰기 무료 도구 비교"
  나쁜 예: "냉장고 사진 한 장이 핵심?" (아무도 이렇게 검색하지 않는다)
- 검색어 뒤에 **뭘 얻는지**를 붙인다. 궁금증이 아니라 **결과**를 적는다.
  "챗GPT 식단표 만드는 법, 냉장고 사진 한 장으로 일주일 짜기"
- 40자 이내 한 줄. 연예인 이름 X.
- 없는 수치를 지어내지 말 것.
- 기호·마크다운(★ ■ **) 금지.
- 설명·번호·머리말 없이 **제목만 한 줄씩**.
- 5개는 **검색어를 서로 다르게** 잡는다(같은 키워드를 다섯 번 변주하지 말 것).

[오늘 홈판에서 실제로 뜨고 있는 제목의 공식 — 매일 새로 뽑은 것이다]
{formula}

[오늘 홈판 위너 제목 실물]
{live}

★위 공식은 «참고»가 아니라 «맞춰야 할 틀»이다. 홈판 위너의 대부분은
  **고유명사 + 검색어가 될 속성 나열 + 숫자 + 총정리/후기 같은 종결**을 쓴다.
  이 글 주제로도 그 틀에 맞는 제목이 나와야 한다.
  ⚠️단, 위 실물을 그대로 베끼거나 «총정리»만 기계적으로 붙이지 말 것.
    오늘 공식이 어제와 다르면 오늘 것을 따른다.

[주제] {topic}
"""

BODY_PROMPT = """당신은 'AI 실전' 블로거 '에디'입니다. 아래 주제로 네이버 블로그 글을 씁니다.
검색하는 사람이 진짜 궁금한 '실용 정보'를 주되, 과장 없이 직접 해본 톤으로.
2026년 네이버는 'AI가 다 쓴 대량 글'을 저품질로 잡는다 — 그래서 실전 정보 + 경험이 핵심이다.

{profile}

{story}

[이 글 주제] {topic}
[타겟] 불안한 직장인·부업 희망자·AI 초보(넓게). "40대"는 화자 신뢰 근거지 타겟 필터 아님.

[★오늘의 본문 공식 — 지금 네이버가 밀어주는 글들에서 실시간 추출. 이 흐름을 따라 쓴다]
{body_formula}

★구조를 매번 똑같이 찍어내지 말 것. 위 '오늘의 공식'이 최우선이고,
   아래 기본 뼈대는 공식이 비어 있을 때만 쓰는 폴백이다.
★★도입부 규칙(홈판 필수): **첫 문장부터 후킹으로 바로 들어간다.** 인사·자기소개 절대 금지 —
   '안녕하세요', '~입니다', '에디입니다', '여러분', '오늘은' 으로 시작하지 말 것. 홈판 위너는 인사로 시작 안 한다.
[폴백 뼈대]
1. 도입 후킹 2~4줄: 지금 왜 이게 궁금한지 + "그런데 해보니 이렇더라" (인사·자기소개 금지, 첫 줄부터 후킹)
2. 이게 뭔지 / 왜 지금 중요한지 (짧게)
3. ★핵심 실전 정보: 단계·방법·비교를 구체적으로 (검색자가 원하는 답)
4. 2026 현실·주의점: 함정도 알려준다 (신뢰 = 파는 사람이 아니라 겪은 사람)
5. 정리(불릿 3개)
6. 질문형 CTA(댓글 유도)로 마무리. ★유튜브 채널 언급·홍보 금지(2026-08-02 에디님 지시).

[반드시 지킬 것]
- ★★어투 고정: **존댓말('~합니다/~습니다/~됩니다')로 끝까지 통일.** 반말·평서체(`~다`, `~더라`, `~하자`) 절대 금지.
  위 '오늘의 공식'은 **구조·전개만** 참고하는 것이고, 어투까지 따라가지 말 것(레퍼런스 블로그가 반말이어도 우리는 존댓말).
- ★지어내기 금지: 툴 기능·수치·가격은 확실한 것만. 불확실하면 '알려진 바로는'·'제 경우엔' 톤. 단정 금지.
- ★문단 규칙(홈판 실측 2026-08-29 · 2026-08-31 수정): **문장을 짧게 쓰고, 한 문장을 한 줄로** 놓는다.
  🔴**문장 중간을 자르지 마라.** 글자 수로 끊는 게 아니다.
     특히 따옴표·인용문은 **아무리 길어도 통째로 한 줄**에 둔다.
     나쁜 예(실제 사고): `"난 계속` / `호감 상대가 두 명이었는데,` / `거기에 계속` / `7기 옥순 님이 있었다."`
     좋은 예: `"난 계속 호감 상대가 두 명이었는데, 거기에 계속 7기 옥순 님이 있었다."`
  · 짧게 쓰는 방법은 **문장을 나누는 것**이지 자르는 게 아니다.
     좋은 예: `경수가 순자를 찍고.` / `순자가 경수를 찍고.` / `그렇게 하루가 갔습니다.`
  · 왜: 홈판 위너 16편은 문단 길이 중앙값 **14자**·20자 이하 **71%**였다(에디 글은 31자·20%).
     모바일 스크롤이라 글 덩어리로 보이면 그 자리에서 이탈하고, 체류시간이 홈판 확산을 정한다.
     다만 그건 **짧은 문장을 한 줄씩 쓴 결과**지 긴 문장을 토막 낸 결과가 아니다.
  · 🔴**분량 목표는 «공백 제외 2,000자 이상»이다**(2026-09-07 전체 홈판 실측 기준).
    전체 홈판 22편을 재보니 **중앙값 2,428자**였다. AI 글은 연예판이 아니라
    이 전체 홈판 자리에서 경쟁하므로 연예글(1,300자)보다 길어야 한다.
    글자 수만 말하면 안 지켜진다 → **본문 문단을 125개 이상** 쓴다(한 문단 평균 16자).
    ★문단 수만 채우면 안 된다. 다 쓰고 글자 수를 세어 모자라면 내용을 더 넣는다.
    짧은 문단으로 끊는 것과 **글을 짧게 쓰는 것은 다르다.** 내용을 줄이지 말고 문단을 나눠라.
    소주제마다 **5~8문단**씩 붙여 채운다(장면 묘사·인물 반응·앞뒤 맥락·시청자 반응).
  · 마크다운 금지. **이모지·특수기호 절대 금지**(소제목에도 쓰지 마라).

★★★'AI가 쓴 티' 제거 — 지금 홈판에서 실제로 뜨는 글은 이렇게 씁니다(2026-08-06 실측 수집).
  이건 문체 규칙이지 어투 규칙이 아닙니다. **존댓말은 그대로 유지**하되, 아래를 지키세요.
  [따라야 할 것]
   · 문장을 짧게, 툭툭 끊습니다. 길이를 일부러 들쭉날쭉하게(한 줄짜리 문장도 섞어서).
   · **구체적인 숫자·이름·상황**을 넣습니다. "빠르다"(X) → "3분 만에 나왔습니다"(O).
     두루뭉술한 형용사 대신 실제 겪은 장면을 적습니다.
   · 잘 모르는 건 모른다고 씁니다("이건 저도 확실치 않은데", "제 경우엔 이랬습니다").
   · 곁가지·군더더기를 조금 남깁니다. 사람 글은 완벽하게 정돈돼 있지 않습니다.
  [절대 쓰지 말 것 — 이게 'AI 냄새'의 정체]
   · 매끄러운 연결어: "또한", "따라서", "이처럼", "뿐만 아니라", "결론적으로", "정리하자면"
   · 교과서식 마무리: "~해보시기 바랍니다", "도움이 되셨길 바랍니다", "지금 바로 시작해보세요"
   · 모든 문단이 같은 길이·같은 리듬으로 반복되는 것
   · 속 빈 수식어: "정말 유용한", "매우 효과적인", "혁신적인", "놀라운"
   · 항목마다 균일하게 3개씩 딱 떨어지는 나열(사람은 2개나 4개도 씁니다)
- 본문에 마커 포함:
  [사진N - 화면/장면 설명 / 출처: 직접 촬영 또는 해당 툴 화면] **10~12개**
  🔴사진 소재를 **분산할 것**(2026-09-09 에디님: "이미지가 너무 비슷해").
    실측 — 9/8 글은 12개 설명 중 **10개가 「~화면」**이라 12장이 전부 같은 결이 됐다.
    · 「~화면」으로 끝나는 설명은 **전체의 절반을 넘기지 마라.**
    · 나머지는 화면 밖으로: 손·종이·인쇄물·필기·사물·작업 공간·이동 중·정리된 책상 등.
    · **같은 소재를 연달아 두 번 쓰지 마라**(화면 다음엔 화면이 아닌 것).
    · 클로즈업만 쓰지 말고 넓은 컷·부감·접사가 섞이게 설명을 쓴다.
  [표] (비교/단계 표 1개. 내용은 아래 카드 JSON의 '표')
  ★★표는 **본문의 20~40% 지점**(첫 소주제 한두 개 뒤)에 둔다 — 홈판 위너 실측(2026-09-18): 표를 쓴 글은 전부 앞 40% 안에 뒀다. 끝에 몰면 거기까지 안 읽고 나간 독자는
     표를 아예 못 본다 — 표는 정보 밀도가 높아 **스크롤을 붙잡는 장치**다(2026-08-23 에디님 지적).
  ★경험 문단(중요): 빈 슬롯을 남기지 말고, 위 [에디의 실제 이야기]를 이 글 주제와 자연스럽게 이은
    1인칭 경험 문단을 본문 1~2곳에 **직접 써 넣는다**(2~4문장). 예: 실직·폐업하고 코딩도 몰랐던 내가
    이 주제(예: AI 이미지)를 처음 만났을 때 어땠는지 → 지금은 어떻게 쓰는지.
    · 단, [에디의 실제 이야기] 밖의 구체 수치·날짜·사건은 지어내지 말 것(예: '조회수 3배' 같은 가짜 숫자 금지).
    · ★**빈 슬롯([[경험 보태기: …]] 같은 것)을 절대 남기지 마라**(2026-08-06 에디님: 자동 발행으로 전환).
      경험 문단은 위 [에디의 실제 이야기] 범위 안에서 **완성된 문장으로 끝맺는다**. 대괄호 자리표시자 금지.
- ★소주제 규칙(엄수): 소주제는 **[사진N] 바로 다음 줄에만** 놓는다. 5~7개, 짧은 명사형/의문형 한 줄(20자 이내, 마침표 없이).
  · 사진과 상관없는 자리에 소주제를 흘리지 말 것. 소주제를 두 줄 연속으로 붙이지 말 것.
  · 소주제 뒤에는 반드시 그 소주제를 설명하는 본문이 이어져야 한다(제목만 덩그러니 두지 말 것).
- 마지막: 해시태그 10개(#로 시작, 검색키워드 포함). ★'@출처' 줄은 넣지 말 것(2026-08-02 에디님: 내 경험 글엔 불필요).

[출력 형식 — 정확히 이 구분자]
===본문===
제목: (임시 제목 한 줄 - 뒤에서 교체됨)
(본문)
===카드===
(JSON 한 개. 큰따옴표)
{{"표제목":"{table_title}","표":[["기준/단계","내용"],["...","..."],["...","..."],["...","..."]],
 "썸네일":{{"intro":"짧은 후킹 도입구","big":"핵심 키워드(3~6자)","tail":"짧은 마무리","badge":"AI 실전"}}}}
"""


def _clean_title(line: str) -> str:
    """제목 후보 한 줄 정리: 앞의 번호/불릿/대괄호 라벨([셀럽 후킹] 등)·따옴표 제거."""
    t = re.sub(r"^\s*(?:\d+[.)]|[-–—•*·])\s*", "", line)
    t = re.sub(r"^\s*\[[^\]]{0,20}\]\s*", "", t)   # 프롬프트 라벨 누수 제거
    # ★LLM이 붙이는 장식 기호 제거(2026-08-04: '★넷플릭스…', '★[AI 프사]★ …'가 그대로 업로드됨).
    #   홈판 제목에 이런 기호가 있으면 광고글처럼 보인다.
    t = re.sub(r"[★☆✔✅◆■▶▲※]+", " ", t)
    t = re.sub(r"[*_`#]+", "", t)                  # 마크다운 강조(**제목**, *제목) 누수 제거
    t = re.sub(r"^\s*\[[^\]]{0,20}\]\s*", "", t)   # 기호 제거 후 드러난 라벨도 한 번 더
    t = re.sub(r"\s{2,}", " ", t)
    t = t.strip()
    # ★따옴표는 '제목 전체를 감싼 경우'에만 벗긴다(2026-08-06 버그 수정).
    #   기존 strip("\"'")는 «'코인 부부', 이호선 앞에서…»처럼 **앞부분만 인용**한 제목에서
    #   여는 따옴표만 떼어내 «코인 부부', 이호선…»으로 깨뜨렸다(홈판 제목이 오타처럼 보인다).
    while len(t) >= 2 and t[0] in "\"'" and t[-1] == t[0]:
        t = t[1:-1].strip()
    # 한쪽만 남아 홀수 개면(과거 산출물·LLM 누수) 여는 따옴표를 복원
    for q in ("'", '"'):
        if q in t and t.count(q) % 2 == 1 and not t.startswith(q):
            t = q + t
            break
    return t.strip()


def _parse_json(out: str) -> dict:
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return {}


def _parse_body(out: str) -> tuple[str, dict]:
    body, cards = "", {}
    bm = re.search(r"===본문===\s*(.*?)\s*===카드===", out, re.S)
    if bm:
        body = bm.group(1).strip()
    cm = re.search(r"===카드===\s*(\{.*\})", out, re.S)
    if cm:
        try:
            cards = json.loads(cm.group(1))
        except Exception:  # noqa: BLE001
            cards = {}
    return body, cards


def _set_title_line(body: str, title: str) -> str:
    lines = body.splitlines()
    for i, ln in enumerate(lines[:5]):
        if re.match(r"^\s*제목\s*[:：]", ln):
            lines[i] = f"제목: {title}"
            return "\n".join(lines)
    return f"제목: {title}\n\n" + body


def _sanitize(topic: str) -> str:
    kw = re.sub(r"[^가-힣0-9A-Za-z]", "", topic)
    return kw[:20] or "AI실전"


def collect_live_context(log=print) -> dict:
    """지금 홈판(IT·컴퓨터)이 밀어주는 제목·본문을 읽어 '오늘의 공식'을 추출.

    구조가 매일 똑같이 찍혀 나오던 문제(2026-07-24 에디님 지적)의 해결책.
    여러 편을 생성할 땐 이 결과를 공유해 수집·추출을 1회만 한다.
    실패해도 빈 공식으로 진행(생성기는 폴백 뼈대를 씀).
    """
    ctx = {"titles": [], "home_titles": [], "title_formula": "", "body_formula": "", "thumb_formula": ""}
    # (1) AI 주제 도출용 = IT·컴퓨터(dir=30) 트렌드(축을 AI로 유지)
    try:
        log("AI 주제 트렌드(IT·컴퓨터) 수집 중…")
        ctx["titles"] = S.fetch_theme_titles(DIR_IT, 30)
    except Exception as e:  # noqa: BLE001
        log(f"AI 주제 트렌드 수집 실패(폴백 진행): {str(e)[:100]}")
    # (2) 제목·썸네일·본문 '공식' = 전체 홈판에서 지금 잘 나가는 것으로 뽑는다(에디님 지시)
    #   🔴2026-09-07 소스 교체: `fetch_theme_titles(0, 30)` → `fetch_recommend_titles(90)`.
    #     에디님이 찾아주신 m.blog.naver.com/Recommendation.naver 는 스크롤만 내리면
    #     제목이 훨씬 많이 나온다(실측 63~90개 대 30개). 공식은 표본이 많을수록 정확해진다 —
    #     30개로 뽑은 «공식»은 그 30개의 버릇일 수 있다.
    #     실패하면 옛 경로로 폴백한다(공식이 비면 제목 규칙이 통째로 사라진다).
    try:
        log("전체 홈판 위너 제목 수집 중(추천 피드)…")
        ctx["home_titles"] = S.fetch_recommend_titles(90)
        log(f"  홈판 제목 {len(ctx['home_titles'])}개 확보")
    except Exception as e:  # noqa: BLE001
        log(f"추천 피드 수집 실패({str(e)[:70]}) → 옛 경로로 폴백")
        try:
            ctx["home_titles"] = S.fetch_theme_titles(DIR_HOME, 30)
        except Exception as e2:  # noqa: BLE001
            log(f"전체 홈판 제목 수집 실패: {str(e2)[:100]}")
    try:
        log("전체 홈판 썸네일 레퍼런스 수집·공식 추출 중…")
        ctx["thumb_formula"] = gemini_thumb.extract_thumb_formula(
            S.fetch_theme_thumbnails(DIR_HOME, 6), log=log)
    except Exception as e:  # noqa: BLE001
        log(f"썸네일 공식 추출 실패(자유 디자인): {str(e)[:100]}")
    samples = []
    try:
        # ★본문 공식은 '같은 쪽 잘되는 글'에서 — AI 글이니 AI/IT(dir=30) 위너 본문을 공식화
        for post in S.fetch_theme_posts(DIR_IT, 3):
            bt = S.fetch_blog_body(post["url"], 1400)
            if bt:
                samples.append(bt)
    except Exception as e:  # noqa: BLE001
        log(f"위너 본문 수집 실패(폴백 진행): {str(e)[:100]}")
    # 🔴레퍼런스 **한 편**(2026-09-18 에디님 규칙 2): 「매일 뜨고 있는 나의 주제와 연관 있는 블로그
    #   하나를 레퍼런스로 삼고, 그 글의 공식으로 나의 글을 쓴다.」
    #   위 samples는 IT 위너 3편의 앞 1,400자를 섞은 것이라 «한 편의 설계도»가 아니다.
    #   → 오늘 IT 홈판 위너 중 본문이 충분한(1,500자+) 첫 글을 **끝까지** 읽고 그 설계도를 뽑는다.
    ctx["ref_post"], ctx["ref_formula"] = {}, ""
    try:
        for post in S.fetch_theme_posts(DIR_IT, 6):
            bt = S.fetch_blog_body(post["url"], 7000)
            if len(bt) < 1500:
                continue
            ctx["ref_formula"] = formula.extract_ref_formula(post["title"], bt)
            if ctx["ref_formula"]:
                ctx["ref_post"] = {"title": post["title"], "url": post["url"], "chars": len(bt)}
                log(f"오늘의 레퍼런스 글: «{post['title'][:40]}» ({len(bt)}자) → 설계도 추출")
                for ln in ctx["ref_formula"].splitlines()[:8]:
                    log(f"   {ln[:110]}")
                break
    except Exception as e:  # noqa: BLE001
        log(f"레퍼런스 글 수집 실패(여러 편 평균 공식으로 진행): {str(e)[:90]}")
    formula_titles = ctx["home_titles"] or ctx["titles"]
    if formula_titles or samples:
        try:
            log(f"오늘의 제목·본문 공식 추출 중(전체 홈판 제목 {len(formula_titles)}개 기준, claude -p)…")
            fx = formula.extract_formulas(formula_titles, samples)
            ctx["title_formula"] = fx.get("title", "")
            ctx["body_formula"] = fx.get("body", "")
            # ★★공식을 눈에 보이게 남긴다(2026-08-17 에디님 방침: "매일 홈판 패턴에 따라 공식이 달라진다").
            #   제목 규칙을 코드에서 빼고 **이 공식에 전적으로 맡겼기 때문에**, 공식이 제대로 나왔는지
            #   확인할 수 없으면 아무것도 확인할 수 없다. 예전엔 «추출 중…» 로그만 있고 결과가 없었다.
            _tf = (ctx["title_formula"] or "").strip()
            if _tf:
                log("── 오늘의 제목 공식 ──")
                for _l in _tf.splitlines()[:8]:
                    if _l.strip():
                        log(f"   {_l.strip()[:110]}")
                try:
                    import config as _cfg
                    _p = os.path.join(_cfg.WORK_DIR, f"formula_{_cfg.today_str()}.txt")
                    with open(_p, "w", encoding="utf-8") as _f:
                        _f.write("[제목 공식]\n" + _tf
                                 + "\n\n[본문 공식]\n" + (ctx["body_formula"] or "")
                                 + "\n\n[분석에 쓴 홈판 제목]\n"
                                 + "\n".join(f"- {t}" for t in formula_titles[:35]))
                except Exception:  # noqa: BLE001
                    pass
            else:
                # 제목 규칙이 공식에만 의존하므로, 비면 반드시 알려야 한다(위너 제목만으로 진행됨)
                log("[경고] 오늘의 제목 공식이 비었습니다 → 수집한 위너 제목만 보고 씁니다")
        except Exception as e:  # noqa: BLE001
            log(f"공식 추출 실패(폴백 뼈대 사용): {str(e)[:100]}")
    return ctx


# 🔴2026-08-29 에디님 정정: 축은 «블로그 글쓰기»가 아니라 **«1인 자동화 시스템»**이다.
#   에디님이 실제로 굴리는 것 — 블로그 3개·유튜브·네이버 클립·문자 자동발송·AI 글쓰기 웹·오프라인 모임.
#   블로그 글쓰기는 그중 하나일 뿐이다. C-RANK는 «한 주제를 꾸준히»가 근거이므로
#   주제를 이 한 축으로 모은다. 검색 수요도 이쪽이 넓고(문자발송·영상·고객관리…),
#   강의 상품과도 정확히 겹친다.
DAILY_TOPIC_PROMPT = """AI 글 {n}개의 주제를 뽑는다. 🔴이 글들은 **홈판**을 노린다 — 지금 사람들이 궁금해서 클릭하는 이슈를 탄다.

[에디님 규칙 — 반드시 지킨다]
1. 주제는 **지금 뜨고 있는 이슈**에서 고른다. 아래 [지금 홈판 IT 위너]·[오늘 네이버 IT 뉴스]에 **실제로 있는 것**만.
2. 주제 **맨 앞에** 그 이슈의 권위 있는 고유명사(사람들이 검색창에 그대로 치는 제품·회사·서비스 이름)를 박는다.
3. 그 이슈를 **에디의 각도**로 푼다 — 코딩 모르는 40대가 AI로 자기 일을 자동화하며 겪은 것.
   독자가 묻는 「그래서 내 일·내 시간·내 돈에 뭐가 달라지나」에 답하는 주제여야 한다.
4. 지어내지 않는다 — 위 목록에 없는 신제품·기능·수치를 만들지 않는다.

[지금 홈판 IT 위너 — 사람들이 지금 누르는 것]
{it}

[지금 전체 홈판 위너]
{home}

[오늘 네이버 IT·과학 뉴스]
{news}

[형식 예 — 이슈는 반드시 위 목록에서 가져올 것]
- iOS 27 단축어로 매일 30분 줄인 업무 자동화 3가지
- GPT-6 나오고 1인 사업자가 바로 바꾼 것
- 아이폰 18 프로로 바꾸면 업무 자동화가 달라지는 지점

[탈락 — 넣지 마라]
- 위 목록에 없는 상시형 사용법(강의안 만들기·명함 정리·재고 발주 같은 것).
  실측(2026-09-18): 「강의안·발표자료 AI」 검색량 0.1 대 「GPT-6·챗GPT 업데이트」 66 — 약 660배.
- 개발자 니치 / 내 시스템 자랑·홍보형 / 연예인

[최근에 쓴 주제 — 겹치지 말 것]
{used}

정확히 {n}개. 설명·번호 없이 주제만 한 줄씩.
"""


def topic_grounded(topic: str, sources: list) -> bool:
    """주제 **맨 앞 고유명사**가 실제 재료(홈판 위너·뉴스 제목)에 있는가(2026-09-18).

    프롬프트에 「목록에 없는 신제품을 지어내지 마라」고 적어도 «갤럭시S27 울트라»가 나왔다
    (뉴스엔 S26뿐). 띄어쓰기를 지우고 첫 낱말이 재료 어딘가에 들어 있어야 통과.
    """
    import re as _re
    toks = _re.findall(r"[A-Za-z0-9가-힣]+", topic or "")
    if not toks:
        return False
    # 회사 이름은 기사마다 한글·영문·약칭이 섞인다(2026-09-18: 뉴스엔 «MS», 주제엔 «마이크로소프트» →
    #   멀쩡한 이슈를 지어낸 걸로 버렸다). 같은 회사로 본다 — 문구가 아니라 표기 통일이다.
    _AL = {"마이크로소프트": "ms", "microsoft": "ms", "오픈ai": "openai", "구글": "google",
           "애플": "apple", "삼성전자": "삼성", "samsung": "삼성", "엔비디아": "nvidia",
           "앤트로픽": "anthropic", "앤스로픽": "anthropic", "메타": "meta"}
    def _norm(x: str) -> str:
        x = x.lower()
        for k, v in _AL.items():
            x = x.replace(k, v)
        return x
    blob = _norm(_re.sub(r"\s", "", " ".join(sources or [])))
    head = _norm(toks[0])
    if len(head) >= 2 and head in blob:
        return True
    # «iOS 27»처럼 이름과 번호가 띄어 쓰인 경우 — 앞 두 낱말을 붙여서도 본다
    if len(toks) >= 2 and _norm(toks[0] + toks[1]) in blob:
        return True
    return False


def derive_topics(ctx: dict, n: int, used: list | None = None, log=print) -> list:
    """오늘 '전체 홈판(dir=0)' + AI 트렌드에서 '홈판에 뜰' 글감 n개를 뽑는다(니치·전문 주제 제외).
    실패하거나 부족하면 빈/부분 리스트 반환 → 호출측이 소재뱅크로 폴백."""
    titles = (ctx or {}).get("titles") or []
    home = (ctx or {}).get("home_titles") or []
    # 🔴2026-09-18 뒤집음. 예전엔 «1인 자동화» 고정 축에서 주제를 지어냈고, 아래 tl·hl을
    #   **만들어 놓고 프롬프트에 넘기지 않았다.** 그래서 실전편은 홈판·뉴스와 무관한 상시형
    #   사용법(강의안·명함·재고)이 됐고 검색량이 뜨는 이슈의 1/660이었다.
    #   에디님 규칙 2·3·4 — 지금 뜨는 이슈 + 고유명사 + 내 각도. 뉴스 헤드라인도 재료로 넣는다.
    if "news_heads" not in (ctx or {}):
        try:
            import gen_ai_news as _N
            ctx["news_heads"] = [h["title"] for h in _N.fetch_ai_headlines(16, log)]
        except Exception as e:  # noqa: BLE001
            log(f"주제 재료용 뉴스 헤드라인 수집 실패: {str(e)[:70]}")
            ctx["news_heads"] = []
    nl = "\n".join(f"- {t}" for t in (ctx.get("news_heads") or [])[:16]) or "(수집 실패)"
    used = used or []
    tl = "\n".join(f"- {t}" for t in titles[:25])
    hl = "\n".join(f"- {t}" for t in home[:25]) or "(수집 실패)"
    ul = "\n".join(f"- {t}" for t in used[-40:]) or "(없음)"
    try:
        # ★중복 방지(2026-08-10): 'used'(내부 이력)만으로는 표현이 조금 달라진 재탕을 못 막는다.
        #   블로그에 **실제로 발행된 제목**과 최근 남용한 제목 틀을 같이 보여준다.
        import history
        _recent = history.with_session(history.recent_titles(60, log))
        out = run_claude_p_retry(
            # 🔴필요한 개수만 받으면 하나만 걸러져도 0개가 된다(2026-09-18: 1개 요청 → 1개 버림 → 0개).
            #   넉넉히(n+3) 받아서 대조를 통과한 앞의 n개를 쓴다.
            DAILY_TOPIC_PROMPT.format(n=n + 3, used=ul, it=tl or "(수집 실패)", home=hl, news=nl)
            + "\n\n" + history.prompt_block(_recent), timeout=180,
            ok=lambda o: len(o.strip()) >= 20, log=log, label="오늘의 주제 도출")
    except Exception as e:  # noqa: BLE001
        log(f"오늘의 주제 도출 실패(뱅크 폴백): {str(e)[:100]}")
        return []
    # 🔴2026-09-18: 주제가 0개로 나와 배치가 멈췄다 — 버린 이유가 로그에 하나도 없었다.
    #   ①길이 60자 제한: 새 주제는 «이슈 + 에디 각도»라 길다 → 80자까지
    #   ②금지어가 «공식»«트렌드»를 **어디든** 잡아 「애플 공식 발표」 같은 정상 주제까지 버렸다
    #     → LLM의 설명 문장(줄 첫머리)만 거른다
    #   ③버릴 때마다 이유를 남긴다(조용한 실패 금지)
    bad = re.compile(r"^(주제|다음|규칙|출력|글감\s*\d|아래|위\s)|^\[|^#")
    topics = []
    for l in out.splitlines():
        t = re.sub(r"^\s*(?:\d+[.)]|[-–—•*·])\s*", "", l).strip().strip("\"'")
        if not t:
            continue
        if not 8 <= len(t) <= 80:
            log(f"  [길이 {len(t)}자] 주제 버림: {t[:40]}")
            continue
        if bad.search(t):
            log(f"  [설명 문장] 버림: {t[:40]}")
            continue
        if t in used or t in topics:
            log(f"  [이미 씀] 주제 버림: {t[:40]}")
            continue
        if True:
            _dup = history.too_similar(t, _recent, 0.5)
            if _dup:
                log(f"  [중복] 주제 버림: {t[:32]} ↔ 발행분 '{_dup[:32]}'")
                continue
            _src = (titles or []) + (home or []) + ((ctx or {}).get("news_heads") or [])
            if _src and not topic_grounded(t, _src):
                log(f"  🔴[지어낸 이슈] 주제 버림(맨 앞 고유명사가 오늘 재료에 없음): {t[:40]}")
                continue
            topics.append(t)
    log(f"오늘의 주제 {len(topics)}개 도출(지금 뜨는 이슈 × 에디 각도)")
    if not topics and not (ctx or {}).get("_topic_retry"):
        # 🔴0개면 그날 실전편이 0편이 된다(소재뱅크는 소진 상태). 한 번 더 뽑는다.
        log("🔴주제 0개 → 한 번 더 뽑습니다")
        ctx["_topic_retry"] = True
        try:
            return derive_topics(ctx, n, used=used, log=log)
        finally:
            ctx.pop("_topic_retry", None)
    return topics[:n]


# ---------------------------------------------------------------------------
# 🔴제목이 «오늘의 홈판 공식»을 실제로 따랐는지 대조 — 2026-09-09 신설
# ---------------------------------------------------------------------------
#  ★왜 필요한가: 공식을 뽑아 프롬프트에 넣어도 LLM이 안 지키면 아무도 모른다.
#    2026-09-09 실측 — 공식은 00:02에 제대로 뽑혔는데 그날 나간 제목 3개는 홈판 장치가
#    **하나도 없었다**(같은 시각 홈판 64개 중 72%는 하나 이상 가지고 있었다).
#    "프롬프트에 썼으니 지켜지겠지"가 두 번 틀렸다(사진 개수·분량에 이어 세 번째다).
#  ★장치 목록을 코드에 박는 게 아니라, **그날 홈판 제목에서 비율을 재서** 기준을 만든다.
#    오늘 홈판이 숫자를 안 쓰면 우리도 숫자를 강요받지 않는다.
_HOOK_QUOTE = re.compile("[\"“”‘’']")
_HOOK_DEM = re.compile(r"이거|이렇게|그거|이런|저거|이곳|여기|정체|이것")
_HOOK_NUM = re.compile(r"\d")
_HOOK_END = re.compile(r"(총정리|후기|리뷰|정리|추천|비교|\?|\.\.\.|…|한다고|있었네|일까|맞나)\s*$")


def title_hooks(t: str) -> list:
    """제목이 쓰고 있는 홈판 후킹 장치 이름들."""
    got = []
    if _HOOK_QUOTE.search(t or ""):
        got.append("따옴표")
    if _HOOK_DEM.search(t or ""):
        got.append("지시어")
    if _HOOK_NUM.search(t or ""):
        got.append("숫자")
    if _HOOK_END.search(t or ""):
        got.append("후킹종결")
    return got


def pick_by_formula(titles: list, home_titles: list, log=print, tag: str = "") -> list:
    """홈판이 장치를 많이 쓰는 날이면, **장치가 있는 후보를 앞으로** 올린다.

    반환: 재정렬된 후보 목록(버리지 않는다 — 후보가 없어지는 게 더 나쁘다).
    """
    homes = [t for t in (home_titles or []) if t]
    if not titles or len(homes) < 15:
        return titles
    rate = sum(1 for t in homes if title_hooks(t)) / len(homes)
    withh = [t for t in titles if title_hooks(t)]
    log(f"{tag}[제목대조] 오늘 홈판 후킹 장치 사용률 {rate*100:.0f}% "
        f"· 우리 후보 {len(withh)}/{len(titles)}개가 장치 있음")
    if rate < 0.5:
        return titles                      # 오늘 홈판이 안 쓰는 날이면 강요하지 않는다
    if not withh:
        log(f"{tag}🔴[제목대조] 홈판은 {rate*100:.0f}%가 쓰는데 우리 후보는 **하나도 없다** "
            f"— 그대로 나가면 홈판에서 안 눌린다: {titles[:2]}")
        return titles
    return withh + [t for t in titles if t not in withh]


def generate(topic: str, out_dir: str, no: str = "20", log=print, ctx: dict | None = None) -> dict:
    """AI 실전 원고 1편(반자동 초안). 제목 후보 3개 + 본문(경험슬롯 포함) + 표 + 썸네일.

    ctx: collect_live_context() 결과. 넘기면 그날의 홈판 공식대로 쓰고, 없으면 직접 수집한다.
    """
    # 🔴2026-09-07: 빈 주제로 부르면 LLM이 «무엇에 대한 글인가요? 예를 들면:» 하고 되묻고,
    #   그 되묻기가 그대로 제목이 된다(실측). 본문은 멀쩡히 나와서 더 알아채기 어렵다.
    #   → 여기서 막는다. 주제 없이 부르는 건 호출부의 실수지 LLM에게 물어볼 일이 아니다.
    topic = (topic or "").strip()
    if len(topic) < 4:
        raise ValueError(
            "주제가 비었습니다. gen_ai.generate(topic=…)에 쓸 주제를 주거나, "
            "derive_topics()로 먼저 뽑아서 넘기세요.")
    log(f"[{no}] AI 실전 초안 생성: {topic[:30]}")
    table_title = f"{_sanitize(topic)[:12]} 핵심 정리"
    if ctx is None:
        ctx = collect_live_context(log)
    # 제목 공식 참고는 '전체 홈판'에서 지금 잘 나가는 제목들(에디님 지시)
    live_titles = "\n".join(f"- {t}" for t in (ctx.get("home_titles") or ctx.get("titles") or [])[:25]) or "(수집 실패)"
    title_formula = ctx.get("title_formula") or "(추출 실패 — 아래 후킹 장치로 대체)"
    body_formula = ctx.get("body_formula") or "(추출 실패 — 아래 폴백 뼈대를 쓸 것)"
    if ctx.get("ref_formula"):
        # 🔴규칙 2 — 오늘 내 주제(IT) 홈판 위너 **한 편**의 설계도를 1순위로 따른다.
        rp = ctx.get("ref_post") or {}
        body_formula = (f"[오늘의 레퍼런스 글 한 편 — «{rp.get('title', '')[:50]}»]\n"
                        f"이 글의 설계도를 **그대로** 따른다(내용·문장은 베끼지 말고 구조만):\n"
                        f"{ctx['ref_formula']}\n\n[참고 — 여러 위너의 평균 공식]\n{body_formula}")

    # 제목 후보 3개
    titles = []
    try:
        import history
        _recent = history.with_session(history.recent_titles(60, log))
        # 🔴2026-09-09 뒤집음. 2026-08-29에 "검색용 제목이라 홈판 공식은 안 넘긴다"고 정해뒀는데
        #   **그 전제가 틀렸다.** 오늘 홈판 위너 64개를 실측하니 1위 제목들이 이렇게 생겼다:
        #     「양주 가볼만한곳 두리랜드 입장료 가격 및 놀이기구 종류 후기」
        #     「2026 수원드론쇼 일정 시간 명당 주차장 총정리 광교호수공원」
        #   홈판에서 뜨는 제목이 **곧 검색 키워드 스태킹**이다 — 둘은 갈라지지 않는다.
        #   공식을 안 넘긴 결과, 우리 글 3편은 홈판 장치(숫자·따옴표·총정리 종결)가 **0개**였다
        #   (같은 시각 홈판 64개 중 72%가 하나 이상 가지고 있었다).
        #   ★공식은 매일 새로 뽑은 것을 넘긴다 — 문구를 코드에 박지 않는다(이 저장소 공통 방침).
        out = run_claude_p(TITLE_PROMPT.format(topic=topic, formula=title_formula,
                                               live=live_titles)
            + "\n\n" + history.prompt_block(_recent), timeout=150)
        titles = [_clean_title(l) for l in out.splitlines() if l.strip()]
        # LLM이 지시문/설명문(프리앰블)을 제목으로 뱉는 경우 제거.
        #  예: "제목만 출력합니다." / "…5개 서로 다른 구조로 뽑았습니다."(← 실제 네이버 업로드 오염 사례)
        bad = re.compile(r"^제목|제목만|제목\s*\d|개입니다|출력|구분자|형식|규칙|^다음|다음과|^아래|번호 없|설명 없|드립니다|나열|"
                         r"뽑았|서로 다른 구조|후보입니다|후보를|버전으로 뽑|개 뽑|개를 뽑|구조로 뽑|골랐습니다|만들었습니다|작성했습니다")
        titles = [t for t in titles if 6 <= len(t) <= 45 and not bad.search(t)]
        # ★최근 발행 제목과 겹치는 후보는 뒤로 밀어낸다(전부 겹치면 그대로 쓰되 경고)
        _fresh = [t for t in titles if not history.too_similar(t, _recent, 0.5)]
        if _fresh:
            titles = _fresh
        elif titles:
            log(f"[{no}] !! 제목 후보가 전부 최근 발행분과 겹침 — 그대로 사용({titles[0][:28]})")
        # ★★'마무리 표현'이 이미 남용된 것과 같은 후보는 버린다(2026-08-17 사고).
        #   내용어가 달라 too_similar에 안 걸리는데도 «…딴판이었습니다»가 3편 연속 나갔다(조회수 0·2·2).
        _tails = [re.sub(r"\s*\(\d+회\)$", "", x) for x in history.overused_tails(_recent)]
        if _tails:
            _diff = [t for t in titles
                     if not any(x and t.replace(" ", "").endswith(x.replace(" ", "")) for x in _tails)]
            if _diff:
                if len(_diff) != len(titles):
                    log(f"[{no}] 남용된 마무리 표현 후보 {len(titles) - len(_diff)}개 제외({_tails[:2]})")
                titles = _diff
            else:
                log(f"[{no}] !! 후보 전부가 남용된 마무리({_tails[:2]}) — 그대로 사용")
        # ★오늘의 홈판 공식을 실제로 따랐는지 대조하고, 따른 후보를 앞으로 올린다.
        titles = pick_by_formula(titles, ctx.get("home_titles") or [], log, tag=f"[{no}] ")
        titles = titles[:3]
    except Exception as e:  # noqa: BLE001
        log(f"[{no}] 제목 생성 실패: {e}")
    best = titles[0] if titles else topic
    log(f"[{no}] 최종 제목: {best}  (홈판 장치: {title_hooks(best) or '없음'})")
    history.note_title(best)      # 같은 배치의 뒷 편이 이 제목·틀을 피하도록 등록

    # 본문 (claude -p가 부하로 가끔 빈 응답을 줘서 최대 3회 재시도)
    body, cards = "", {}
    prompt = BODY_PROMPT.format(profile=_profile(), story=_my_story(), topic=topic,
                                table_title=table_title, body_formula=body_formula)
    prompt += __import__("history").opening_ban_block()   # 오늘 이미 쓴 도입은 피하게
    def _ok(out):
        b, c = _parse_body(out)
        if not (bool(b) and bool(c) and len(b.strip()) >= 300):
            return False
        # ★사진이 글 길이에 비해 모자라면 **다시 받는다**(2026-09-02 에디님: 비율이 안 맞는다).
        #   프롬프트에만 개수를 써두면 두 번 놓친다 — 실제로 놓쳤다.
        # ★분량도 코드가 잰다(2026-09-05 «1,500자 이상»). 프롬프트만으론 안 지켜진다.
        if not G.enough_length(b, 2000):
            return False
        if not G.enough_photos(b):
            return False
        # 🔴같은 배치에서 같은 문장으로 시작하면 다시 받는다(2026-09-09 — 연예편에서 4/8 발생).
        #   ★history는 이 파일에서 지역 임포트라 클로저에 안 잡힐 수 있다 → 여기서 직접 가져온다.
        import history as _H
        if _H.opening_taken(b):
            log(f"[{no}] 도입이 오늘 이미 쓴 것과 같음(«{_H.opening_of(b)[:16]}») → 다시 받음")
            return False
        return True

    body, cards = _parse_body(
        run_claude_p_retry(prompt, timeout=320, ok=_ok, log=log, label=f"[{no}] 본문"))
    if not body or not cards or len(body.strip()) < 300:
        raise RuntimeError(f"본문 생성 실패(재시도 소진, 길이 {len(body.strip())})")
    __import__("history").note_opening(body)   # 뒤 편이 이 도입을 피하도록 등록
    # 🔴규칙 5 — 피드백 한 번 → 다시 쓰기(제목·인트로·썸네일). 규칙 4(고유명사)도 여기서 잰다.
    import feedback as FB
    _t0 = best
    best, body, fb_thumb, fb_report = FB.run(best, body, log, tag=f"[{no}] ")
    if best != _t0 and _t0 in titles:
        titles = [best] + [t for t in titles if t != best]
    body = _set_title_line(body, best)
    # 홈판 규칙: 생성 단계에서도 인사·자기소개 도입을 제거해 복붙용/미리보기까지 깨끗하게.
    #  (업로드 pipeline에도 백스톱이 있으나, LLM이 프롬프트 금지에도 가끔 인사말을 붙여 사이드카에 남았음.)
    from pipeline import _strip_greeting_intro
    body = _strip_greeting_intro(body)

    keyword = _sanitize(topic)
    os.makedirs(out_dir, exist_ok=True)
    G.clear_no(out_dir, no)
    with open(os.path.join(out_dir, f"{no}_{keyword}_복붙용.txt"), "w", encoding="utf-8") as f:
        f.write(body)
    # AI 실전 초안 표식(대시보드가 옛 셀럽/강점 글과 구분)
    open(os.path.join(out_dir, f"{no}_{keyword}_ai.flag"), "w").close()
    if fb_report:
        with open(os.path.join(out_dir, f"{no}_{keyword}_피드백.md"), "w", encoding="utf-8") as f:
            f.write(fb_report)
    # 제목 후보를 사이드카로 저장(에디님이 고르게)
    if titles:
        with open(os.path.join(out_dir, f"{no}_{keyword}_제목후보.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(titles))
    T.write_celeb_table(out_dir, no, keyword, cards.get("표제목", table_title), cards.get("표", []))
    # 썸네일 3단 폴백:
    #  ① 글 전문을 제미나이에 주고 '요약·디자인까지' 맡김(문구 지정 X — 템플릿화 방지)
    #  ② 실패 시 문구 지정형(배지/큰글씨)  ③ 그래도 실패 시 HTML 디자인형
    thumb = cards.get("썸네일", {})
    fn = f"{no}_{keyword}_썸네일.png"
    ref_formula = (ctx or {}).get("thumb_formula", "")
    # 🔴2026-08-18 에디님 지적("왜 또 파란색으로만 나와?"). 폴백 사슬이 **전부 제미나이 API**여서
    #   API가 429(한도 초과)를 뱉으면 두 단계가 함께 죽고 결국 텍스트형(남색 카드)으로 떨어졌다.
    #   실측: 8/17·8/18 이틀 연속 429. 홈판 목록에서 우리 글만 파란 카드로 줄줄이 보였다.
    #   ★같은 시간 **본문 이미지는 멀쩡히 나왔다** — 그건 `web_image`(제미나이 **웹 구독**)를 쓰기 때문이다.
    #     쇼핑편 썸네일도 웹 구독이라 사진이 나왔다. AI편만 API 전용이라 혼자 파랬다.
    #   → API 실패 시 **웹 구독으로 배경 사진을 만들어** 문구를 얹는다(쇼핑편과 같은 방식).
    if not gemini_thumb.make_from_article(out_dir, fn, body, log=log, ref_formula=ref_formula,
                                        copy=fb_thumb):   # 규칙 5: 피드백봇이 고른 문구
        log(f"[{no}] 제미나이 API 썸네일 실패({gemini_thumb.LAST_ERROR or '사유 미상'}) → 웹 구독으로 시도")
        if not _thumb_via_web(out_dir, fn, thumb, topic, log):
            # 🔴2026-08-19 에디님: "또 이렇게 나왔네? 이렇게 하지 말라고 했잖아."
            #   전날 웹 구독 폴백을 넣었는데도 01편이 파란 카드로 나갔다. 로그를 보니
            #   API 429 → 웹 구독도 3회 실패 → **사슬 끝의 텍스트형**으로 떨어졌다(02편은 웹 구독 성공).
            #   사슬 끝에 단색 카드가 남아 있는 한 언제든 또 나온다 → **스톡 사진 단계를 하나 더** 둔다.
            #   Unsplash는 API 한도가 넉넉하고 제미나이와 무관해서 429에 같이 죽지 않는다.
            if not _thumb_via_stock(out_dir, fn, thumb, topic, log):
                log(f"[{no}] 썸네일: 사진 경로가 모두 실패 → 텍스트형으로 나갑니다(사진 없음)")
                T.render_text_thumbnail(out_dir, fn, thumb, footer="")
    # (인포그래픽 자동 첨부는 배포판에서 뺐다 — 사진은 사용법대로 무료 스톡으로 채운다.)
    log(f"[{no}] 완료 → {keyword} (제목후보 {len(titles)}개, 경험슬롯 포함)")
    return {"no": no, "topic": topic, "keyword": keyword, "titles": titles}


def _thumb_via_stock(out_dir: str, fn: str, thumb: dict, topic: str, log=print) -> bool:
    """Unsplash 실사 사진 + 문구 → 썸네일. 제미나이(API·웹)가 다 죽어도 이건 산다.

    ★사슬의 마지막 '사진' 단계다. 여기까지 실패해야 비로소 텍스트형으로 간다.
      Unsplash는 제미나이와 별개 서비스라 429에 함께 죽지 않는다.
    """
    bg = os.path.join(out_dir, os.path.splitext(fn)[0] + "_배경.png")
    try:
        import image_finder
        # 한글 주제로는 스톡 검색이 잘 안 걸린다 → 영문 일반 장면어로 바꿔 던진다
        q = keyword_en = "person working laptop home office desk"
        low = (topic or "") + " " + (thumb.get("big") or "")
        if any(w in low for w in ("사진", "이미지", "그림", "복원")):
            q = "old photo album restoration desk"
        elif any(w in low for w in ("돈", "수익", "부업", "정산", "보험", "환급")):
            q = "korean person calculating money documents desk"
        elif any(w in low for w in ("쇼핑", "구매", "제품", "가전", "선풍기")):
            q = "home appliance product on table daylight"
        if not image_finder.search_download(q, bg):
            return False
    except Exception as e:  # noqa: BLE001
        log(f"  스톡 사진 실패: {str(e)[:60]}")
        return False
    try:
        import photo_thumb
        if photo_thumb.make_face(bg, os.path.join(out_dir, fn), thumb):
            log("  썸네일 = 스톡 사진 + 문구 합성")
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _thumb_via_web(out_dir: str, fn: str, thumb: dict, topic: str, log=print) -> bool:
    """제미나이 **웹 구독**으로 배경 사진을 만들고 문구를 얹어 썸네일을 만든다.

    API(gemini_thumb)가 429로 죽어도 이 경로는 산다 — 구독이라 한도가 다르다.
    쇼핑편(`gen_shopping`)이 쓰던 방식과 같다. 합성 모듈이 없으면 사진만이라도 쓴다.
    """
    # ★배경 파일은 **항상 다른 이름**이어야 한다. 예전엔 fn.replace("_썸네일.png", …)로 만들었는데,
    #   파일명이 그 규약과 다르면 배경과 결과가 같은 경로가 되어 copyfile이 SameFileError로 죽었다.
    bg = os.path.join(out_dir, os.path.splitext(fn)[0] + "_배경.png")
    try:
        import web_image
        desc = (thumb.get("big") or topic or "").strip()
        # ★대기 시간을 넉넉히(2026-08-20 원인 규명). 디버그 스크린샷을 열어 보니 제미나이 웹이
        #   «이미지를 만들고 있습니다» 상태였는데 기본 220초에서 먼저 포기하고 있었다.
        #   429도 세션 문제도 아니고 **덜 기다린 것**이었다. 썸네일은 편당 1장뿐이라 더 기다려도 된다.
        if not web_image.generate(f"{desc} 를 보여주는 현실적인 실사 사진, 글자 없음, 밝고 선명하게",
                                  bg, log=log, timeout_sec=420):
            return False
    except Exception as e:  # noqa: BLE001
        log(f"  웹 구독 배경 실패: {str(e)[:60]}")
        return False
    try:
        import photo_thumb
        if photo_thumb.make_face(bg, os.path.join(out_dir, fn), thumb):
            log("  썸네일 = 웹 구독 사진 + 문구 합성")
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        import shutil
        shutil.copyfile(bg, os.path.join(out_dir, fn))
        log("  썸네일 = 웹 구독 사진(문구 합성 없이)")
        return True
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    topic = sys.argv[1] if len(sys.argv) > 1 else "AI로 블로그 글 자동 발행, 진짜 되는지 3개월 해봤습니다"
    out = os.path.join(config.SOURCE_ROOT, f"gen_{config.today_str()}")
    generate(topic, out, no="20")
