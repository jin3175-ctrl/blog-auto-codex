#!/usr/bin/env python3
"""오늘 쓸 기사거리 고르기 (2026-10-18 · 3기 2주차).

글을 쓰고 싶을 때 「오늘 기사거리 줘」 → 내 블로그 주제(내정보.txt)로 네이버 뉴스를 찾아
최근 기사 5개를 보여준다. 하나 고르면 그 기사를 재료로 글을 쓴다(CLAUDE.md §A).

사용:
    python3 기사거리.py              # 내 주제로
    python3 기사거리.py 부천 맛집     # 주제를 직접 줄 때
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

MAX_DAYS = 7        # 이보다 오래된 기사는 빼고 보여준다(날짜 모르는 기사는 남긴다)
SHOW = 5


def _topic_words(topic: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"[/,·|\n]", topic or "") if p.strip()]
    return [p for p in parts if not p.startswith("(")][:4]


def main(argv: list[str]) -> int:
    topic = " ".join(argv).strip()
    if not topic:
        try:
            import myinfo
            topic = myinfo.topic()
        except BaseException:  # noqa: BLE001
            topic = ""
    words = _topic_words(topic)
    if not words:
        print("내정보.txt 의 「내 블로그 주제」가 비어 있습니다. 예) 부천 맛집 / 시니어 건강")
        print("또는: python3 기사거리.py 찾을 말")
        return 1
    import celeb_sources as S
    today = date.today()
    found, seen = [], set()
    for w in words:
        try:
            items = S.fetch_news_search(w, limit=8)
        except Exception as e:  # noqa: BLE001
            print(f"[{w}] 검색 실패: {str(e)[:80]}")
            continue
        for it in items:
            key = it["title"][:30]
            if key in seen:
                continue
            seen.add(key)
            d = it.get("date") or ""
            age = (today - date.fromisoformat(d)).days if d else None
            if age is not None and age > MAX_DAYS:
                continue
            it["주제"] = w
            it["며칠전"] = age
            found.append(it)
    found.sort(key=lambda x: (x["며칠전"] is None, x["며칠전"] or 0))
    found = found[:SHOW]
    if not found:
        print(f"최근 {MAX_DAYS}일 안에 「{' / '.join(words)}」 기사를 못 찾았습니다. 주제 낱말을 바꿔 보세요.")
        return 1
    print(f"오늘 쓸 만한 기사거리 ({' / '.join(words)})\n")
    for i, it in enumerate(found, 1):
        when = "날짜 모름" if it["며칠전"] is None else ("오늘" if it["며칠전"] == 0 else f"{it['며칠전']}일 전")
        print(f"{i}. {it['title']}  [{when}]")
        if it.get("snippet"):
            print(f"   {it['snippet'][:120]}")
    os.makedirs(os.path.join(HERE, "work"), exist_ok=True)
    out = os.path.join(HERE, "work", f"기사거리_{today:%Y%m%d}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(found, f, ensure_ascii=False, indent=1)
    print(f"\n번호를 고르면 그 기사로 글을 씁니다. (저장: work/{os.path.basename(out)})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
