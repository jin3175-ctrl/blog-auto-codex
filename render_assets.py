"""편별 HTML 카드/표를 PNG 이미지로 렌더링 (Playwright screenshot)."""
import os

from playwright.sync_api import sync_playwright

# 마커 키 -> (HTML asset_map 키, 스크린샷 셀렉터)
_TARGETS = {
    "표": ("표", "table"),
    "강점시각화": ("강점시각화", "body > div"),
    "장점": ("장점", "body > div"),
    "맹점": ("맹점", "body > div"),
}


def render_assets(html_asset_map: dict, out_dir: str) -> tuple[dict, list[str]]:
    """html_asset_map(HTML 경로들)을 PNG로 렌더.

    returns (png_map, logs)
      png_map: {'표':png, '강점시각화':png, '장점':png, '맹점':png, '썸네일':png}
    """
    png_map: dict = {}
    logs: list[str] = []

    # 썸네일은 이미 PNG → 그대로 통과
    if html_asset_map.get("썸네일"):
        png_map["썸네일"] = html_asset_map["썸네일"]
        logs.append("썸네일 PNG 사용")

    to_render = [
        (key, html_asset_map.get(html_key), selector)
        for key, (html_key, selector) in _TARGETS.items()
        if html_asset_map.get(html_key)
    ]
    if not to_render:
        return png_map, logs

    os.makedirs(out_dir, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 760, "height": 1200},
                                device_scale_factor=2)
        for key, html_path, selector in to_render:
            try:
                out_path = os.path.join(out_dir, f"{key}.png")
                page.goto("file://" + html_path)
                page.wait_for_timeout(150)
                el = page.locator(selector).first
                el.screenshot(path=out_path)
                png_map[key] = out_path
                logs.append(f"{key} 렌더 완료")
            except Exception as e:  # noqa: BLE001
                logs.append(f"{key} 렌더 실패: {e}")
        browser.close()

    return png_map, logs
