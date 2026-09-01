#!/usr/bin/env python3
"""Small browser smoke suite for the public static site."""

from __future__ import annotations

import argparse
import sys
from urllib.parse import urlparse

from playwright.sync_api import Error, sync_playwright


def url(base: str, path: str) -> str:
    return base.rstrip("/") + path


def click_viewport_link(page, href: str, expected_path: str) -> None:
    """Click a visible, interactable link without relying on DOM position/classes."""
    links = page.locator(f'a[href="{href}"]')
    viewport_height = (page.viewport_size or {}).get("height", 900)
    for index in range(links.count()):
        candidate = links.nth(index)
        try:
            candidate.wait_for(state="visible", timeout=1000)
        except Error:
            continue
        box = candidate.bounding_box()
        if box and box["y"] < viewport_height and box["y"] + box["height"] > 0:
            try:
                candidate.click(timeout=750)
                page.wait_for_url(f"**{expected_path}", timeout=1500)
                return
            except Error:
                continue
    raise AssertionError(f"no visible in-viewport link found for {href}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    site_host = urlparse(base_url).netloc
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 900})

        def block_external(route):
            if urlparse(route.request.url).netloc not in {"", site_host}:
                route.abort()
            else:
                route.continue_()

        context.route("**/*", block_external)
        page = context.new_page()
        page.goto(url(base_url, "/"), wait_until="domcontentloaded")
        click_viewport_link(page, "Offline-meetings.html", "/Offline-meetings.html")

        mobile = context.new_page()
        mobile.set_viewport_size({"width": 390, "height": 844})
        mobile.goto(url(base_url, "/"), wait_until="domcontentloaded")
        mobile.get_by_label("Open menu").click()
        click_viewport_link(mobile, "Literature.html", "/Literature.html")
        mobile.close()

        page.goto(url(base_url, "/About.html"), wait_until="domcontentloaded")
        page.wait_for_url(base_url + "/", timeout=10000)

        page.goto(url(base_url, "/Offline-meetings.html"), wait_until="domcontentloaded")
        page.wait_for_function("""() => {
            const section = document.querySelector('.na-meetings');
            const select = document.getElementById('cityFilter');
            return section && !section.querySelector('#na-loading') && select && select.options.length > 2;
        }""", timeout=15000)
        city_filter = page.locator("#cityFilter")
        city_filter.select_option(index=2)
        if city_filter.input_value() == "":
            raise AssertionError("meetings city filter did not accept a real option")

        page.goto(url(base_url, "/Calculator.html"), wait_until="domcontentloaded")
        page.locator("#cp-openPicker").click()
        page.locator("#cp-today").click()
        page.locator("#cp-save").click()
        if page.locator("#cp-totalDays").inner_text() != "0":
            raise AssertionError("today must produce zero elapsed days")
        saved_date = page.evaluate("localStorage.getItem('clean_period_start_date_v4')")
        page.reload(wait_until="domcontentloaded")
        if page.evaluate("localStorage.getItem('clean_period_start_date_v4')") != saved_date:
            raise AssertionError("calculator date did not persist in localStorage")

        page.goto(url(base_url, "/AudioBook.html"), wait_until="domcontentloaded")
        frame = page.frame_locator('iframe[src="bt6-player.html"]')
        frame.locator("#playlist li").nth(1).wait_for(timeout=10000)
        frame.locator("#playlist li").nth(1).click()
        source = frame.locator("#audio").get_attribute("src")
        if not source or not source.endswith("audio/bt6/bt6_002.mp3"):
            raise AssertionError(f"second audio track did not set expected source: {source}")

        page.goto(url(base_url, "/Admin-panel.html"), wait_until="domcontentloaded")
        password = page.locator('input[type="password"]')
        password.fill("stage-1-invalid-password")
        page.locator('form a[href="#"]:visible').click()
        page.wait_for_timeout(250)
        if "Admin-panel.html" not in urlparse(page.url).path or "5ab2b48b" in page.url:
            raise AssertionError("invalid admin password granted access")

        page.goto(url(base_url, "/Calendar.html"), wait_until="domcontentloaded")
        calendar = page.locator("#gc-frame")
        calendar.wait_for()
        if "mode=WEEK" not in (calendar.get_attribute("src") or ""):
            raise AssertionError("desktop calendar URL did not initialize WEEK mode")
        calendar_page = context.new_page()
        calendar_page.set_viewport_size({"width": 390, "height": 844})
        calendar_page.goto(url(base_url, "/Calendar.html"), wait_until="domcontentloaded")
        if "mode=AGENDA" not in (calendar_page.locator("#gc-frame").get_attribute("src") or ""):
            raise AssertionError("mobile calendar URL did not initialize AGENDA mode")
        calendar_page.close()

        page.goto(url(base_url, "/Google-Drive.html"), wait_until="domcontentloaded")
        drive_src = page.locator("#gd-frame").get_attribute("src") or ""
        drive_open = page.locator("#gd-open-btn").get_attribute("href") or ""
        if "drive.google.com/embeddedfolderview?id=" not in drive_src:
            raise AssertionError("Drive embed URL did not initialize")
        if not drive_open.startswith("https://accounts.google.com/AccountChooser?continue="):
            raise AssertionError("Drive account chooser URL did not initialize")
        context.close()
        browser.close()
    print("Browser smoke suite passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, Error) as exc:
        print(f"BROWSER SMOKE FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
