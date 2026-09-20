"""재작성된 원고(마커 보존)를 네이버 에디터가 재생할 블록 리스트로 변환."""
from __future__ import annotations

import re

# 마커 정규식
RE_TITLE = re.compile(r"^\s*제목\s*[:：]\s*(.+)$")
RE_QUOTE_BIG = re.compile(r"^\s*\[대주제\]\s*(.*)$")
RE_QUOTE_SMALL = re.compile(r"^\s*\[소주제\]\s*(.*)$")
RE_PHOTO = re.compile(r"^\s*\[사진[^\]]*\]\s*$")
RE_TABLE = re.compile(r"^\s*\[표\]\s*$")
RE_VIS = re.compile(r"^\s*\[강점시각화\s*삽입[^\]]*\]\s*$")
RE_MERIT = re.compile(r"^\s*\[장점카드\s*삽입[^\]]*\]\s*$")
RE_BLIND = re.compile(r"^\s*\[맹점카드\s*삽입[^\]]*\]\s*$")
RE_HASHTAGS = re.compile(r"^\s*#\S")
# [커넥트 - 제품명 추천 상품 링크] → 쇼핑커넥트 자동 삽입 자리
RE_CONNECT = re.compile(r"^\s*\[커넥트\s*[-–—]?\s*(.*?)\]\s*$")
# 장식용 구분선(━━━, ───, ===, --- 등)만 있는 줄 → 본문에 넣지 않고 버림.
# (연예 원고가 참고 글의 소제목 장식선을 따라 써서 생기는 artifact. 그대로 두면
#  첫 줄 인용 변환에 걸려 '가로줄만 든 빈 66박스'가 만들어진다.)
RE_DIVIDER = re.compile(r"^\s*[━─—―＝=\-–_·•]{3,}\s*$")


def _connect_query(inside: str) -> str:
    """마커 안쪽 문구에서 검색어만 추출: '추천 상품 링크'·괄호 부가설명 제거."""
    s = re.sub(r"추천\s*상품\s*링크", "", inside)
    s = re.sub(r"\([^)]*\)", " ", s)      # (넥밴드형) 등 제거
    s = re.sub(r"[-–—]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_rewritten(text: str, asset_map: dict) -> tuple[str, list[dict]]:
    """returns (title, blocks)

    asset_map keys(있으면): '표','강점시각화','장점','맹점' -> PNG 절대경로
    각 block:
      {"type":"text","text":str}
      {"type":"blank"}
      {"type":"quote","style":"big|small","text":str}
      {"type":"photo","text":str}          # [사진N] 자리표시자 (그대로 남김)
      {"type":"image","kind":str,"path":str,"missing":bool,"label":str}
      {"type":"hashtags","text":str}
    """
    lines = text.replace("\r\n", "\n").split("\n")
    title = ""
    blocks: list[dict] = []

    def add_image(kind: str, key: str, label: str):
        path = asset_map.get(key)
        blocks.append({
            "type": "image", "kind": kind, "path": path,
            "missing": path is None, "label": label,
        })

    for raw in lines:
        line = raw.rstrip()

        m = RE_TITLE.match(line)
        if m and not title:
            title = m.group(1).strip()
            continue

        if not line.strip():
            blocks.append({"type": "blank"})
            continue

        # 장식용 구분선 줄은 버린다(빈 줄로 대체) — 인용 변환·본문 오염 방지
        if RE_DIVIDER.match(line):
            blocks.append({"type": "blank"})
            continue

        m = RE_QUOTE_BIG.match(line)
        if m:
            # 대주제 = 기본 66박스 스타일
            blocks.append({"type": "quote", "style": "big", "nstyle": "default", "text": m.group(1).strip()})
            continue
        m = RE_QUOTE_SMALL.match(line)
        if m:
            # 소주제 = 라인 스타일
            blocks.append({"type": "quote", "style": "small", "nstyle": "quotation_line", "text": m.group(1).strip()})
            continue

        if RE_TABLE.match(line):
            add_image("table", "표", "표")
            continue
        if RE_VIS.match(line):
            add_image("card", "강점시각화", "강점시각화")
            continue
        if RE_MERIT.match(line):
            add_image("card", "장점", "장점카드")
            continue
        if RE_BLIND.match(line):
            add_image("card", "맹점", "맹점카드")
            continue

        if RE_PHOTO.match(line):
            blocks.append({"type": "photo", "text": line.strip()})
            continue

        m = RE_CONNECT.match(line)
        if m:
            blocks.append({"type": "connect", "query": _connect_query(m.group(1))})
            continue

        if RE_HASHTAGS.match(line):
            blocks.append({"type": "hashtags", "text": line.strip()})
            continue

        blocks.append({"type": "text", "text": line.strip()})

    # 제목이 없으면 첫 텍스트 블록에서 유추
    if not title:
        for b in blocks:
            if b["type"] == "text":
                title = b["text"][:40]
                break

    _mark_first_line_quote(blocks)
    _mark_closing_question(blocks)
    return title, _collapse_blanks(blocks)


def _mark_first_line_quote(blocks: list[dict]) -> None:
    """가장 첫 문단 한 줄을 따옴표(66박스) 인용으로 변환(굵게는 삽입 시 처리)."""
    for i, b in enumerate(blocks):
        if b["type"] == "text":
            blocks[i] = {"type": "quote", "style": "first", "nstyle": "default", "text": b["text"]}
            break


def _mark_closing_question(blocks: list[dict]) -> None:
    """마지막의 독자 대상 질문('...보시나요?')을 말풍선 인용구로 변환.
    (본문 대사의 '?'가 아니라, 뒤쪽에 있는 마지막 물음표 문단만.)"""
    last_idx = None
    for i, b in enumerate(blocks):
        if b["type"] == "text" and b["text"].rstrip().endswith("?"):
            last_idx = i
    if last_idx is not None:
        b = blocks[last_idx]
        blocks[last_idx] = {
            "type": "quote", "style": "closing",
            "nstyle": "quotation_bubble", "text": b["text"],
        }


def _collapse_blanks(blocks: list[dict]) -> list[dict]:
    """연속 blank를 1개로, 앞뒤 blank 제거."""
    out: list[dict] = []
    for b in blocks:
        if b["type"] == "blank":
            if not out or out[-1]["type"] == "blank":
                continue
        out.append(b)
    while out and out[-1]["type"] == "blank":
        out.pop()
    while out and out[0]["type"] == "blank":
        out.pop(0)
    return out
