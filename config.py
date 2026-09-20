"""공통 설정 및 경로 유틸 (수강생 배포판).

원본(에디님 시스템)은 블로그ID·키·경로가 코드에 박혀 있었다. 수강생마다 다르므로
**내정보.txt** 에서 읽는다(myinfo). 이 파일에는 개인정보를 넣지 않는다.

- 블로그ID = 내정보.txt 의 '내 블로그ID' (myinfo.blog_id)
- 모든 폴더(session/ work/ 원고/)는 **이 패키지 폴더 기준 상대경로**다.
"""
from __future__ import annotations

import os
import re
from datetime import date

import myinfo

# 이 프로젝트(패키지) 루트
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# 블로그 정보 — 전부 내정보.txt 에서 읽는다
# ---------------------------------------------------------------------------
#: 원본은 EDI_BLOG 환경변수로 블로그 두 개(연예/AI)를 갈랐다. 수강생 배포판은 블로그 하나다.
#  일부 코드가 `config.BLOG == "..."` 로 분기하므로, 그 분기들이 전부 '기본 경로'를 타도록
#  등록되지 않은 값을 둔다(연예/AI 전용 분기는 수강생에게 해당 없음).
BLOG = "my"

#: 사람이 읽는 이름(로그용) — 내 블로그 이름
BLOG_NAME = myinfo.blog_name()

#: 🔴 이 실행이 글을 올려도 되는 단 하나의 블로그. naver.py·run_ai_daily.py 가
#   로그인 저장 시점과 업로드 직전에 이 값과 대조한다(다른 계정 방지).
EXPECT_BLOG_ID = myinfo.blog_id()

# 원고·산출물이 저장되는 루트 (패키지 안 '원고' 폴더)
SOURCE_ROOT = os.path.join(BASE_DIR, "원고")

SESSION_DIR = os.path.join(BASE_DIR, "session")
WORK_DIR = os.path.join(BASE_DIR, "work")
SESSION_FILE = os.path.join(SESSION_DIR, "naver_state.json")
BLOG_META_FILE = os.path.join(SESSION_DIR, "naver_meta.json")

#: 실제 크롬 전용 프로필 경로(EDI_PREFER_CHROME=1 일 때만 쓰임 — naver.open_browser 참고).
CHROME_PROFILE = os.path.join(SESSION_DIR, "naver_profile")

os.makedirs(SESSION_DIR, exist_ok=True)
os.makedirs(WORK_DIR, exist_ok=True)
os.makedirs(SOURCE_ROOT, exist_ok=True)


def today_str() -> str:
    return date.today().strftime("%Y%m%d")


def resolve_date_folder(date_str: str | None = None) -> str | None:
    """오늘 폴더가 있으면 그걸, 없으면 가장 최신 YYYYMMDD 폴더를 반환."""
    if date_str:
        cand = os.path.join(SOURCE_ROOT, date_str)
        return cand if os.path.isdir(cand) else None

    today = os.path.join(SOURCE_ROOT, today_str())
    if os.path.isdir(today):
        return today

    if not os.path.isdir(SOURCE_ROOT):
        return None
    dated = [
        d for d in os.listdir(SOURCE_ROOT)
        if re.fullmatch(r"\d{8}", d) and os.path.isdir(os.path.join(SOURCE_ROOT, d))
    ]
    if not dated:
        return None
    dated.sort(reverse=True)
    return os.path.join(SOURCE_ROOT, dated[0])


def work_dir_for(date_str: str, post_no: str) -> str:
    d = os.path.join(WORK_DIR, date_str, post_no)
    os.makedirs(d, exist_ok=True)
    return d
