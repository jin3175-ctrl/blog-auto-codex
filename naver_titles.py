"""네이버 블로그 홈 인기글에서 '지금 뜨는' 제목 N개를 수집."""
from __future__ import annotations

from playwright.sync_api import sync_playwright

BLOG_HOME = "https://section.blog.naver.com/BlogHome.naver?directoryNo=0&currentPage={page}&groupId=0"

# 제목이 아닌 도움말/푸터 노이즈 제거용
_NOISE = {
    "블로그 아이디가 필요해요!", "내 글 보호하기", "타인의 글 보호하기",
    "글 무단 도용 시 신고하기", "신고대상", "신고방법",
}


def fetch_trending_titles(count: int = 30, max_pages: int = 3) -> list[str]:
    titles: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 2400})
        try:
            for pno in range(1, max_pages + 1):
                page.goto(BLOG_HOME.format(page=pno), wait_until="networkidle", timeout=40000)
                page.wait_for_timeout(2500)
                loc = page.locator(".title_post")
                for i in range(loc.count()):
                    t = loc.nth(i).inner_text().strip()
                    if t and t not in _NOISE and t not in titles and len(t) >= 6:
                        titles.append(t)
                if len(titles) >= count:
                    break
        finally:
            browser.close()
    return titles[:count]


if __name__ == "__main__":
    ts = fetch_trending_titles()
    print(f"수집 {len(ts)}개")
    for i, t in enumerate(ts, 1):
        print(f"{i:2}. {t}")
