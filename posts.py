"""원고 폴더에서 편(post) 목록과 편별 에셋 경로를 찾는다."""
from __future__ import annotations

import glob
import json
import os
import re

RE_BODY = re.compile(r"^(\d{2})_(.+)_복붙용\.txt$")


def list_posts(folder: str) -> list[dict]:
    """폴더의 _복붙용.txt 를 스캔해 편 목록 반환 (번호 오름차순)."""
    posts = []
    for path in sorted(glob.glob(os.path.join(folder, "*_복붙용.txt"))):
        name = os.path.basename(path)
        m = RE_BODY.match(name)
        if not m:
            continue
        no, keyword = m.group(1), m.group(2)
        assets = find_assets(folder, no)
        posts.append({
            "no": no,
            "keyword": keyword,
            "body_path": path,
            "thumb_path": assets.get("썸네일"),
            "has_table": bool(assets.get("표")),
            "has_cards": all(assets.get(k) for k in ("강점시각화", "장점", "맹점")),
        })
    posts.sort(key=lambda p: p["no"])
    return posts


def _first(folder: str, pattern: str) -> str | None:
    hits = sorted(glob.glob(os.path.join(folder, pattern)))
    return hits[0] if hits else None


def find_assets(folder: str, post_no: str) -> dict:
    """편 번호에 해당하는 HTML/썸네일 에셋 경로 딕셔너리."""
    return {
        "표": _first(folder, f"{post_no}_*_표.html"),
        "강점시각화": _first(folder, f"{post_no}_*_강점시각화.html"),
        "장점": _first(folder, f"{post_no}_*_장점.html"),
        "맹점": _first(folder, f"{post_no}_*_맹점.html"),
        "썸네일": _first(folder, f"{post_no}_*_썸네일.png"),
    }


def get_post(folder: str, post_no: str) -> dict | None:
    for p in list_posts(folder):
        if p["no"] == post_no:
            return p
    return None


def category(body_path: str) -> str:
    """글 유형 분류: insight(강점인사이트)/shopping(쇼핑커넥트)/ai(AI 실전)/celeb(연예).

    ★celeb이 기본값이라 AI 실전편까지 연예로 잡히던 문제(2026-08-02 실측): 연예 전용 처리
    (유튜브 CTA 제거 등)가 AI편에도 적용됐다. AI편은 생성기가 남기는 `_ai.flag`로 구분한다.
    """
    name = os.path.basename(body_path or "")
    if "강점인사이트" in name:
        return "insight"
    if "쇼핑커넥트" in name:
        return "shopping"
    # gen_ai가 같은 폴더에 `{no}_{keyword}_ai.flag`를 남긴다
    stem = name.replace("_복붙용.txt", "")
    if stem and os.path.exists(os.path.join(os.path.dirname(body_path or ""), f"{stem}_ai.flag")):
        return "ai"
    return "celeb"


def get_manifest_subtitle(folder: str, post_no: str) -> str | None:
    """manifest_{date}.json 의 해당 편 썸네일 subtitle (제목 폴백용)."""
    mf = _first(folder, "manifest_*.json")
    if not mf:
        return None
    try:
        with open(mf, encoding="utf-8") as f:
            data = json.load(f)
        for t in data.get("thumbnails", []):
            if str(t.get("out", "")).startswith(post_no):
                return t.get("subtitle") or t.get("big")
    except Exception:  # noqa: BLE001
        return None
    return None
