#!/usr/bin/env python3
"""네이버 블로그 카테고리 칸을 **한 번에 하나씩** 만든다 (2026-09-08 신설).

사용:
  python3 make_category.py 건강정보            # 확인만(저장 안 함)
  python3 make_category.py 건강정보 --submit   # 실제로 만든다

만든 뒤 반드시 대조할 것 — 이름이 한 글자만 달라도 naver._select_category가
**조용히 기본 칸**에 저장한다:
  python3 -c "import run_ai_daily as R; R.check_categories()"


★한 페이지에서 '카테고리 추가'를 3번 누르면 3번째가 조용히 안 먹는다(실측).
  그래서 칸 하나마다 페이지를 새로 열고 저장까지 끝낸다 — 느리지만 확실하다.
★새 칸의 기본 이름은 '게시판'이다. 선택 후 fill('')로 **비우고** 타이핑해야 한다
  (Meta+a/Delete는 선택이 안 잡혀 '자동화시판'처럼 섞였다 — 실측).
  타이핑이어야 하는 이유: onkeyup 으로 트리 라벨이 갱신된다.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright
import naver, config

SHOT_DIR = config.WORK_DIR


def tree(fr):
    return fr.eval_on_selector_all("ul#tree li label",
                                   "els=>els.map(e=>e.innerText.replace(/\\s+/g,' ').trim())")


def main():
    if len(sys.argv) < 2:
        print("사용법: python make_category.py <카테고리이름> [--submit]")
        sys.exit(1)
    NAME = sys.argv[1]   # 만들 칸 이름
    SUBMIT = "--submit" in sys.argv
    with sync_playwright() as p:
        ctx, close = naver.open_browser(p, print, headless=True)
        pg = ctx.pages[0] if ctx.pages else ctx.new_page()
        pg.set_viewport_size({"width": 1500, "height": 1100})
        dialogs = []
        pg.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
        pg.goto(f"https://admin.blog.naver.com/{config.EXPECT_BLOG_ID}/config/blog",
                wait_until="domcontentloaded", timeout=40000)
        pg.wait_for_timeout(4000)
        fr = next(f for f in pg.frames if "AdminCategoryView" in f.url)
        before = tree(fr)
        print("시작:", before)
        if any(g.startswith(NAME) for g in before):
            print(f"이미 «{NAME}» 칸이 있습니다 — 아무것도 하지 않음."); close(); sys.exit(0)

        fr.locator("a:has(img._addCategoryView)").first.click()
        pg.wait_for_timeout(1800)
        if len(tree(fr)) <= len(before):
            print("!! 칸 추가가 안 됨"); close(); sys.exit(1)

        inp = fr.locator("#category_name")
        inp.click()
        inp.fill("")                       # ★기본값 '게시판' 제거
        pg.wait_for_timeout(300)
        inp.type(NAME, delay=80)           # ★onkeyup 이 트리 라벨을 갱신한다
        pg.wait_for_timeout(800)
        got = tree(fr)
        print(f"입력값 {inp.input_value()!r} / 목록 {got}")
        ok = inp.input_value() == NAME and any(g.startswith(NAME + "(") for g in got) \
             and len(got) == len(before) + 1
        print("정상:", ok)
        if not ok:
            print("!! 예상과 달라 저장하지 않습니다."); close(); sys.exit(1)

        if SUBMIT:
            fr.locator("#submit_button").click()
            pg.wait_for_timeout(7000)
            print("저장 완료. 다이얼로그:", dialogs)
            pg.screenshot(path=os.path.join(SHOT_DIR, f"category_saved_{NAME}.png"), full_page=True)
        else:
            print("(저장 안 함)")
        close()


if __name__ == "__main__":
    main()
