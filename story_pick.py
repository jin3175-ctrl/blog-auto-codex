"""내이야기.md 에서 경험 한 조각을 뽑아 준다 (공통 모듈).

글을 쓸 때마다 클로드 코드가 이걸 불러 '내 경험 한 문장'을 프롬프트에 넣는다.
그래야 AI 초안에 '진짜 내 이야기'가 한 개 이상 들어가고, 채점표에서 그걸 확인한다.

    python story_pick.py          → 경험 한 줄을 무작위로 출력
    python story_pick.py --all    → 전부 출력
"""
import os, sys, random

BASE = os.path.dirname(os.path.abspath(__file__))
STORY = os.path.join(BASE, "내이야기.md")


def items():
    if not os.path.exists(STORY):
        return []
    out = []
    for line in open(STORY, encoding="utf-8"):
        s = line.strip().lstrip("-*0123456789. ").strip()
        # 제목(#)·빈 줄·안내문은 뺀다
        if not s or s.startswith("#") or s.startswith(">") or s.startswith("("):
            continue
        if len(s) >= 6:
            out.append(s)
    return out


def pick():
    it = items()
    return random.choice(it) if it else ""


if __name__ == "__main__":
    if "--all" in sys.argv:
        for s in items():
            print("-", s)
    else:
        s = pick()
        if s:
            print(s)
        else:
            print("[안내] 내이야기.md 가 비어 있습니다. 클로드 코드에게 '내 이야기 5개 질문해줘'라고 해보세요.")
