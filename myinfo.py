"""내정보.txt 를 읽어 블로그ID·메일주소를 알려준다 (수강생 배포판).

원본(에디님 시스템)은 값이 코드에 박혀 있었다. 수강생마다 다르니 파일에서 읽는다.
내정보.txt 를 못 찾거나 비어 있으면 프로그램이 멈추고 무엇을 채워야 하는지 알려준다.
"""
import os

_BASE = os.path.dirname(os.path.abspath(__file__))
# 내정보.txt 는 이 폴더 또는 한 단계 위(패키지 루트)에 있다
_CANDIDATES = [os.path.join(_BASE, "내정보.txt"),
               os.path.join(os.path.dirname(_BASE), "내정보.txt")]


def _read():
    data = {}
    for path in _CANDIDATES:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                k, v = line.split(":", 1)
                v = v.strip()
                # "(여기에 ...)" 같은 안내 문구는 미입력으로 본다
                if v.startswith("(") or not v:
                    continue
                data[k.strip()] = v
        break
    return data


_DATA = _read()


def get(key: str, default: str = "") -> str:
    return _DATA.get(key, default)


def blog_id() -> str:
    v = get("내 블로그ID")
    if not v:
        raise SystemExit(
            "\n[멈춤] 내정보.txt 의 '내 블로그ID'가 비어 있습니다.\n"
            "  메모장으로 내정보.txt 를 열어 내 블로그 주소의 아이디를 넣어주세요.\n"
            "  예) blog.naver.com/abcd1234 → abcd1234\n")
    return v


def email() -> str:
    return get("내 메일주소")


def category() -> str:
    return get("내 카테고리")


def topic() -> str:
    return get("내 블로그 주제")


def blog_name() -> str:
    """블로그 이름. 안 적었으면 블로그ID를 그대로 쓴다."""
    return get("내 블로그 이름") or get("내 블로그ID") or "제 블로그"


def blog_who() -> str:
    """이웃신청 인사말에 들어가는 한 줄 소개."""
    return get("내 블로그 한줄소개") or (f"{topic()}을 기록하는 블로그" if topic() else "블로그")


def gemini_key() -> str:
    """제미나이 이미지 생성 키(선택). 없으면 빈 문자열 — 사진은 무료 스톡으로 대체된다."""
    return get("제미나이 키")


def photo_key() -> str:
    """Unsplash 무료 사진 검색 키(선택). 없으면 빈 문자열 — 그 자리는 [사진N]로 남는다."""
    return get("사진 키")
