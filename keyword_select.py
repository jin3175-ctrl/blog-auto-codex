"""claude -p로 본문에서 '독자가 중요하게 볼 핵심 키워드/짧은 구절'을 선정(굵게+파랑용)."""
from __future__ import annotations

from claude_cli import run_claude_p

PROMPT = """다음 블로그 본문에서, 독자가 중요하게 볼 '핵심 키워드/짧은 구절'을 최대 {n}개 고르세요.

기준:
- 인물 이름처럼 너무 자주 반복되는 단어보다, 의미가 담긴 핵심 표현/개념 위주.
- 각 항목은 짧게(단어~10자 내외 구절).
- 반드시 본문에 있는 '그대로' 복사(새로 쓰지 마세요).
- 출력은 항목만 한 줄에 하나씩, 번호·설명·기호 없이.

[본문]
{body}
"""


def select_keywords(body: str, max_n: int = 6, timeout: int = 120) -> list[str]:
    try:
        out = run_claude_p(PROMPT.format(n=max_n, body=body), timeout=timeout)
    except Exception:  # noqa: BLE001
        return []
    kws: list[str] = []
    for ln in out.splitlines():
        s = ln.strip().lstrip("-•*0123456789. ").strip().strip("\"'“”`")
        if 2 <= len(s) <= 24 and s not in kws:
            kws.append(s)
        if len(kws) >= max_n:
            break
    return kws
