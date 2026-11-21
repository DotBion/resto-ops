"""Verify the locally served dashboard in Chrome. Run after building the frontend."""

import os
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

URL = os.getenv("CAFE_TEST_URL", "http://127.0.0.1:8000")


def smoke():
    with urlopen(f"{URL}/api/config", timeout=5) as response:
        assert response.status == 200
    with sync_playwright() as browser_api:
        browser = browser_api.chromium.launch(channel="chrome", args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(URL)
        expect(page.get_by_role("heading", name="Floor monitor")).to_be_visible()
        page.get_by_role("button", name="Play the synthetic demo").first.click()
        page.locator("video").evaluate("(video) => video.playbackRate = 1.6")
        expect(page.get_by_text("Alert held", exact=True).first).to_be_visible(timeout=16000)
        expect(page.get_by_text("Queue needs attention", exact=True)).to_be_visible(timeout=16000)
        page.get_by_role("button", name="Acknowledge").click()
        expect(page.get_by_text("Acknowledged", exact=True)).to_be_visible()
        expect(page.get_by_text("Resolved", exact=True)).to_be_visible(timeout=18000)
        page.locator(".task .evidence-link").click()
        expect(page.get_by_role("img", name="Evidence frame", exact=False)).to_be_visible()
        page.wait_for_function("document.querySelector('.evidence-frame')?.naturalWidth > 0")
        page.get_by_role("button", name="Evaluation", exact=True).click()
        cells = page.get_by_role("row").filter(has_text="False alerts").get_by_role("cell")
        expect(cells).to_have_text(["1", "0"])
        page.get_by_role("button", name="Run history", exact=True).click()
        page.get_by_role("button").filter(has_text="Counter & seating").first.click()
        expect(page.get_by_text("Task resolved", exact=True)).to_be_visible()
        mobile = browser.new_page(viewport={"width": 380, "height": 844}, is_mobile=True, has_touch=True)
        mobile.goto(URL)
        expect(mobile.get_by_role("heading", name="Floor monitor")).to_be_visible()
        assert mobile.evaluate("document.documentElement.scrollWidth === window.innerWidth")
        assert not errors, errors
        print("Browser checks passed for replay, alert, acknowledgment, resolution, evidence, evaluation, history and mobile.")


if __name__ == "__main__":
    smoke()
