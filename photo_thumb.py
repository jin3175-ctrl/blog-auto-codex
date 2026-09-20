#!/usr/bin/env python3
"""실사 사진 + 문구 = 홈판 썸네일 (2026-08-18 신설).

★왜 만들었나
`gen_shopping`·`gen_ai`가 예전부터 `import photo_thumb`를 하고 있었는데 **이 파일이 없었다.**
그래서 매번 except로 떨어져 «썸네일 = 제품 사진(문구 합성 없이)»로 나갔고, AI편은 아예
제미나이 API(429)에 막혀 **텍스트형 남색 카드**로 나갔다(에디님: "왜 또 파란색으로만 나와?").

홈판 썸네일의 조건은 두 가지다:
  · **1:1 정사각형** — 피드에서 잘리지 않는다(가로 사진은 양옆이 잘려 핵심이 사라진다).
  · **문구가 읽혀야 한다** — 사진만으로는 무슨 글인지 몰라 클릭이 안 된다.

그래서 이 모듈은 사진을 1:1로 잘라 아래쪽에 어두운 띠를 깔고 그 위에 문구를 얹는다.
글자를 사진 위에 그냥 얹으면 배경과 섞여 안 읽히므로 **띠(그라데이션)를 반드시 깐다.**
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

SIZE = 1080  # 네이버 썸네일 권장 1:1

#: 맥에 기본 설치된 한글 폰트. 없으면 기본 폰트로 떨어진다(글자는 나오되 두께가 약해진다).
_FONTS = [
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    "/Library/Fonts/AppleSDGothicNeo.ttc",
]


def _font(size: int, bold: bool = False):
    for p in _FONTS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size, index=(2 if bold and p.endswith(".ttc") else 0))
            except Exception:  # noqa: BLE001
                try:
                    return ImageFont.truetype(p, size)
                except Exception:  # noqa: BLE001
                    continue
    return ImageFont.load_default()


def _fit(draw, text: str, font_path_size: int, max_w: int, bold: bool):
    """폭에 맞을 때까지 글자 크기를 줄인다(잘려 나가는 것보다 작게 쓰는 게 낫다)."""
    size = font_path_size
    while size > 20:
        f = _font(size, bold)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 4
    return _font(20, bold)


def make_face(bg_path: str, out_path: str, thumb: dict) -> bool:
    """배경 사진 + 문구 → 1:1 썸네일. 성공하면 True.

    thumb = {"intro": 위 작은 줄, "big": 큰 줄(핵심), "tail": 아래 작은 줄, "badge": 좌상단 배지}
    """
    try:
        img = Image.open(bg_path).convert("RGB")
    except Exception:  # noqa: BLE001
        return False

    # ① 1:1 중앙 크롭 → 확대
    w, h = img.size
    side = min(w, h)
    img = img.crop(((w - side) // 2, (h - side) // 2,
                    (w - side) // 2 + side, (h - side) // 2 + side)).resize((SIZE, SIZE), Image.LANCZOS)

    # ② 아래쪽 어두운 그라데이션 — 글자가 배경에 묻히지 않게 하는 핵심 장치
    grad = Image.new("L", (1, SIZE), 0)
    for y in range(SIZE):
        # 위 38%부터 서서히 어두워지고 아래는 거의 불투명 — 밝은 배경에서도 흰 글씨가 읽혀야 한다
        # (실측: 알파를 낮게 잡았더니 창가·조명이 밝은 사진에서 작은 줄이 묻혔다).
        t = max(0.0, (y - SIZE * 0.38) / (SIZE * 0.62))
        grad.putpixel((0, y), int(252 * (t ** 0.95)))
    img.paste(Image.new("RGB", (SIZE, SIZE), (8, 10, 14)), (0, 0), grad.resize((SIZE, SIZE)))

    d = ImageDraw.Draw(img)
    pad = int(SIZE * 0.065)
    maxw = SIZE - pad * 2

    # ③ 배지(좌상단) — 어느 축의 글인지 한눈에
    badge = (thumb.get("badge") or "").strip()
    if badge:
        bf = _font(38, True)
        tw = d.textlength(badge, font=bf)
        d.rounded_rectangle([pad, pad, pad + tw + 34, pad + 62], 14, fill=(255, 214, 0))
        d.text((pad + 17, pad + 12), badge, font=bf, fill=(26, 26, 26))

    # ④ 문구 — 아래에서 위로 쌓는다(큰 줄이 가장 눈에 띄게)
    y = SIZE - pad
    for text, size, bold, color in (
        ((thumb.get("tail") or "").strip(), 46, False, (232, 236, 242)),
        ((thumb.get("big") or "").strip(), 92, True, (255, 255, 255)),
        ((thumb.get("intro") or "").strip(), 44, False, (206, 214, 226)),
    ):
        if not text:
            continue
        f = _fit(d, text, size, maxw, bold)
        bbox = d.textbbox((0, 0), text, font=f)
        th = bbox[3] - bbox[1]
        y -= th + int(size * 0.42)
        d.text((pad, y), text, font=f, fill=color)

    try:
        img.save(out_path, "PNG", optimize=True)
        return os.path.getsize(out_path) > 5000
    except Exception:  # noqa: BLE001
        return False


if __name__ == "__main__":
    import sys
    ok = make_face(sys.argv[1], sys.argv[2],
                   {"intro": "3개월 직접 해봤습니다", "big": "월 천만원의 진실",
                    "tail": "절반은 사기였습니다", "badge": "AI 실전"})
    print("생성:", ok, "→", sys.argv[2])
