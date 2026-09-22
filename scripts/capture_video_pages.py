import os
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = os.getenv("RIVER_VIDEO_BASE_URL", "http://127.0.0.1:8000")
PROJECT_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_DIR / "video_assets" / "screens"
EDGE_PATH = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def capture_desktop(browser) -> None:
    context = browser.new_context(viewport={"width": 1600, "height": 900}, device_scale_factor=1)
    page = context.new_page()
    page.goto(f"{BASE_URL}/login", wait_until="networkidle")
    page.screenshot(path=OUTPUT_DIR / "01_login.png")

    page.fill("#username", "admin")
    page.fill("#password", "admin123456")
    page.click("#submit")
    page.wait_for_url(f"{BASE_URL}/")
    page.wait_for_timeout(1800)
    page.screenshot(path=OUTPUT_DIR / "02_dashboard.png")

    page.locator("#recognize").scroll_into_view_if_needed()
    page.wait_for_timeout(500)
    page.screenshot(path=OUTPUT_DIR / "03_recognize.png")

    page.locator("#camera").scroll_into_view_if_needed()
    page.wait_for_timeout(500)
    page.screenshot(path=OUTPUT_DIR / "04_camera.png")

    page.locator("#events").scroll_into_view_if_needed()
    page.wait_for_timeout(700)
    page.screenshot(path=OUTPUT_DIR / "05_events.png")
    context.close()


def capture_mobile(browser) -> None:
    context = browser.new_context(
        viewport={"width": 430, "height": 860},
        device_scale_factor=1,
        is_mobile=True,
        has_touch=True,
    )
    page = context.new_page()
    page.goto(f"{BASE_URL}/login", wait_until="networkidle")
    page.fill("#username", "admin")
    page.fill("#password", "admin123456")
    page.click("#submit")
    page.wait_for_url(f"{BASE_URL}/")
    page.goto(f"{BASE_URL}/mobile/", wait_until="networkidle")
    page.wait_for_timeout(1200)
    page.screenshot(path=OUTPUT_DIR / "06_mobile_inspect.png")

    page.locator('button[data-page="eventsPage"]').click()
    page.wait_for_timeout(900)
    page.screenshot(path=OUTPUT_DIR / "07_mobile_events.png")
    context.close()


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(EDGE_PATH),
            headless=True,
            args=["--disable-gpu", "--hide-scrollbars"],
        )
        capture_desktop(browser)
        capture_mobile(browser)
        browser.close()
    print(f"Screenshots saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
