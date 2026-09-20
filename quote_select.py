"""claude -p로 본문에서 '인용구로 뽑으면 가독성 좋은' 짧은 부분(질문/반전/강조)을 선정."""
from __future__ import annotations

import re

from claude_cli import run_claude_p

# 유형 → 네이버 인용 스타일
TYPE_STYLE = {
    "question": "quotation_bubble",  # 질문 → 말풍선
    "reversal": "quotation_line",    # 반전/대조 → 라인
    "emphasis": "quotation_corner",  # 강조 → 「」
}

PROMPT = """다음 블로그 본문에서, 인용구로 시각적으로 강조하면 가독성이 좋아질 '짧은 부분'을 최대 {n}개 고르세요.
대상: (1) 독자에게 묻는 질문, (2) 내용이 반전/대조되는 문장, (3) 핵심 강조 한마디.

아주 중요:
- 문장 전체가 아니라 '한 호흡에 읽히는 짧은 부분'만 고르세요(권장 25자 이내).
- 특히 대사가 있으면 큰따옴표 안의 대사 그 부분만 고르세요.
  (예: 원문이 '광수는 말했습니다. "왜 이렇게 오래 붙잡고 있는 거야?"' 라면 → "왜 이렇게 오래 붙잡고 있는 거야?" 만)
- 반드시 본문에 있는 '그대로'(따옴표 포함) 복사하세요. 새로 쓰지 마세요.
- 출력은 아래 형식의 줄만, 설명 없이:
유형|||부분
  (유형은 question / reversal / emphasis 중 하나)

[본문]
{body}
"""


def select_quotes(body: str, max_n: int = 4, timeout: int = 150) -> list[dict]:
    """returns [{"text": 부분, "style": nstyle}] — 실패 시 빈 리스트."""
    try:
        out = run_claude_p(PROMPT.format(n=max_n, body=body), timeout=timeout)
    except Exception:  # noqa: BLE001
        return []
    picks: list[dict] = []
    for ln in out.splitlines():
        if "|||" not in ln:
            continue
        typ, _, sent = ln.partition("|||")
        typ = typ.strip().lower()
        sent = sent.strip()
        if not sent or typ not in TYPE_STYLE:
            continue
        picks.append({"text": sent, "style": TYPE_STYLE[typ]})
        if len(picks) >= max_n:
            break
    return picks


_QUOTES = " \"'“”`「」"
_ENUM_START = re.compile(r"^\s*(첫째|둘째|셋째|넷째|다섯째|여섯째|일곱째|여덟째|아홉째|열째)\s*[,，]")


def _locate(txt: str, phrase: str):
    """txt 안에서 phrase 위치 찾기(정확→따옴표제거→공백유연). 반환 (start, matched)."""
    p = phrase.strip()
    i = txt.find(p)
    if i >= 0:
        return i, p
    p2 = p.strip(_QUOTES)
    if p2:
        i = txt.find(p2)
        if i >= 0:
            return i, p2
        # 공백 차이 허용 정규식
        pat = re.compile(r"\s*".join(re.escape(ch) for ch in p2 if not ch.isspace()))
        m = pat.search(txt)
        if m:
            return m.start(), m.group(0)
    return -1, ""


#: 문장 끝 — 마침표만 보면 '?'·'!'·'…'로 끝나는 문장을 놓친다(구어체 본문에 흔하다).
_SENT_END = re.compile(r"[.!?…]+[\"\'”’)\]]*")


def _sentence_span(text: str, idx: int) -> tuple[int, int]:
    """idx를 포함하는 **문장 하나**의 [시작, 끝). 문장 부호가 없으면 블록 전체."""
    ends = [m.end() for m in _SENT_END.finditer(text)]
    s = 0
    for e0 in ends:
        if e0 <= idx:
            s = e0
        else:
            break
    e = len(text)
    for e0 in ends:
        if e0 > idx:
            e = e0
            break
    while s < len(text) and text[s] in " \t":
        s += 1
    return s, e


def apply_quotes(blocks: list[dict], picks: list[dict]) -> int:
    """picks의 부분과 일치하는 text 블록을 찾아 인용구로 분리. 앞/뒤 나머지는 본문 유지.
    단, 그 부분이 '문장 중간'에 박혀 있으면(뒤에 한글이 이어지면) 조각이 남지 않도록
    그 '문장 전체'를 인용한다. 변환 개수 반환."""
    converted = 0
    for pk in picks:
        phrase = pk["text"].strip()
        if len(phrase.strip(_QUOTES)) < 4:
            continue
        for i, b in enumerate(blocks):
            if b["type"] != "text":
                continue
            if _ENUM_START.match(b["text"]):
                continue   # 열거(첫째·둘째…) 항목엔 인용 넣지 않음
            start, matched = _locate(b["text"], phrase)
            if start < 0:
                continue
            txt = b["text"]
            end = start + len(matched)
            # ★★문장을 쪼개지 않는다 (2026-08-11 에디님 지적).
            #   예전엔 '뒤에 한글이 이어지는지'만 봤다. 그래서 인용할 부분이 **문장 끝**에 붙어 있으면
            #   (뒤가 비어 embedded=False) 앞부분이 조각으로 남았다 —
            #   «이럴 줄 알았다면 결혼 안 했다.» 가 본문 "이럴 줄" + 인용구 "알았다면 결혼 안 했다."로
            #   갈라져 말이 안 되는 글이 발행됐다.
            #   → 이제 **항상 문장 경계로 잘라** 그 문장 전체를 인용구로 만든다.
            s, e = _sentence_span(txt, start)
            qtext = re.sub(r"[\"'“”]", "", txt[s:e]).strip().strip(_QUOTES).strip()
            before = txt[:s].strip().strip(_QUOTES).strip()
            after = txt[e:].strip().strip(_QUOTES).strip()
            # 그래도 남는 앞/뒤가 '문장 같지 않은 조각'이면(부호 없이 짧게 끊김) 인용구에 붙여 살린다.
            if before and not _SENT_END.search(before) and len(before) <= 20:
                qtext = (before + " " + qtext).strip()
                before = ""
            if after and not _SENT_END.search(after) and len(after) <= 20:
                qtext = (qtext + " " + after).strip()
                after = ""
            new_blocks = []
            if before:
                new_blocks.append({"type": "text", "text": before})
            new_blocks.append({"type": "quote", "style": "auto", "nstyle": pk["style"], "text": qtext})
            if after:
                new_blocks.append({"type": "text", "text": after})
            blocks[i:i + 1] = new_blocks
            converted += 1
            break
    return converted
