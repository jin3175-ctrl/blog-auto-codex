"""지금 뜨는 네이버 인기글 제목 30개의 패턴을 뽑아, 이 글에 맞는 제목 1개를 생성."""
from __future__ import annotations

from claude_cli import run_claude_p

MARKER = "제목>>>"

PROMPT = """당신은 네이버 블로그 제목 카피라이터입니다.

[지금 네이버 블로그 홈에서 인기 있는 제목 {n}개]
{titles}

위 인기 제목들의 공통 후킹 패턴(궁금증 유발, 따옴표 인용, 숫자·리스트, '정체/이유/비밀/비법'
같은 호기심 단어, 반전·대조 등)을 참고해, 아래 [블로그 본문]에 맞는 제목을 1개 만드세요.

제목 규칙:
- 한국어, 이모지·해시태그·마크다운 금지, 40자 이내 한 줄.
- 본문 사실과 어긋나면 안 됨(과장·허위 금지). 핵심 인물/소재/강점 키워드를 살릴 것.

[출력 형식 — 매우 중요]
분석이나 설명은 절대 쓰지 말고, 오직 아래 형식의 '한 줄'만 출력하세요:
{marker} 여기에완성된제목
(이 줄 외에 어떤 텍스트도 출력하지 마세요.)

[블로그 본문]
{body}
"""


def _clean(s: str) -> str:
    s = s.strip().strip("\"'“”`>《》〈〉[] ").strip()
    for pref in ("제목:", "제목 :", "제목"):
        if s.startswith(pref):
            s = s[len(pref):].strip("\"'“”`: ").strip()
    return s


def generate_title(body: str, trending_titles: list[str], timeout: int = 180) -> str:
    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(trending_titles, 1))
    prompt = PROMPT.format(n=len(trending_titles), titles=numbered, body=body, marker=MARKER)
    out = run_claude_p(prompt, timeout=timeout)

    # 1) 구분자 라인에서 추출
    for ln in out.splitlines():
        if MARKER in ln:
            cand = _clean(ln.split(MARKER, 1)[1])
            if cand:
                return cand
    # 2) 폴백: 설명형 머리말을 제외한 마지막 '내용 있는' 줄
    nonempty = [l.strip() for l in out.splitlines() if l.strip()]
    for ln in reversed(nonempty):
        c = _clean(ln)
        # '~습니다/~니다/아래와 같' 같은 설명 문장은 제외
        if c and not c.endswith(("습니다.", "습니다", "같습니다.")) and "아래" not in c:
            return c
    return ""
