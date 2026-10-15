#!/usr/bin/env python3
"""One-off helper: confirm where the Connect2Concepts widget gets its data.

`scrape.py` calls a JSON API directly and needs no browser. This script exists
to re-derive that API URL with a real headless browser, and to check that the
numbers we compute still match what the widget actually draws on screen. Run it
if the widget ever changes and `scrape.py` starts looking wrong.

    pip install playwright && python -m playwright install chromium
    python discover_widget_api.py
"""

from playwright.sync_api import sync_playwright

WIDGET_URL = (
    "https://www.connect2mycloud.com/Widgets/Data/locationCount"
    "?type=circle&key=9f320719-e415-46d7-b233-a89d85ba6d97"
)
FACILITIES = ("AOERC - Fitness Center", "ACSR - Fitness Center")


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        # Pacific, so the widget's `new Date()` renders what a Stanford visitor sees.
        page = browser.new_page(timezone_id="America/Los_Angeles")

        api_calls: list[str] = []
        page.on(
            "request",
            lambda r: api_calls.append(r.url) if "goboardapi" in r.url else None,
        )

        page.goto(WIDGET_URL, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(3_000)  # let the AJAX callback paint the cards

        print("Data URL(s) the widget requested:")
        for url in api_calls or ["  (none seen)"]:
            print(f"  {url}")

        print("\nWhat the widget renders for our facilities:")
        for card in page.locator("div.col-md-3.col-sm-6").all():
            text = " ".join(card.inner_text().split())
            if any(name in text for name in FACILITIES):
                print(f"  {text}")

        browser.close()


if __name__ == "__main__":
    main()
