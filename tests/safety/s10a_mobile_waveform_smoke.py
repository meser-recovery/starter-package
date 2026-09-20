#!/usr/bin/env python3
"""Real bundled FFmpeg regression in desktop Chromium, Firefox and WebKit.

This is browser-engine evidence only. It is not labeled as a real iPhone or
Android result; those require the physical-device harness beside this file.
"""

from __future__ import annotations

import argparse
from playwright.sync_api import sync_playwright


def exercise(browser_type, base_url: str) -> None:
    browser = browser_type.launch()
    page = browser.new_page(viewport={"width": 390, "height": 844})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(base_url.rstrip("/") + "/tests/safety/s10a-mobile-waveform-harness.html", wait_until="domcontentloaded")
        page.get_by_role("heading", name="S10A mobile long-audio waveform").wait_for()
        result = page.evaluate("""async () => {
          await window.__s10aMobileWaveformHarness.run(1);
          return document.getElementById('report').textContent;
        }""")
        assert '"result":"PASS"' in result, result
        assert '"peaks":65536' in result, result
        assert '"archiveMutations":0' in result, result
        assert not errors, errors
    finally:
        browser.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--browser", choices=("chromium", "firefox", "webkit", "all"), default="all")
    args = parser.parse_args()
    with sync_playwright() as playwright:
        names = ("chromium", "firefox", "webkit") if args.browser == "all" else (args.browser,)
        for name in names:
            exercise(getattr(playwright, name), args.base_url)
            print(f"S10A bounded long AAC-LC waveform browser regression: {name} PASS", flush=True)
    print("Playwright engines are not real-device iPhone/Android acceptance evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
