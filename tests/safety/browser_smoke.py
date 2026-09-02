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
        homepage_destinations = (
            "Offline-meetings.html", "Literature.html", "AudioBook.html",
            "Calculator.html", "Admin-panel.html",
            "https://na-tranzit.org/gruppy/onlajn-gruppy",
            "https://na-russia.org/meditation-today", "https://radio-na.ru/",
            "https://nam-poputi.ucoz.ru/load/audio_vystuplenija_anonimnykh/polnyj_spisok_perevedjonnykh_spikerskikh_s_ivrita/11-1-0-751",
        )
        for href in homepage_destinations:
            if page.locator(f'a[href="{href}"]').count() != 1:
                raise AssertionError(f"homepage destination must appear exactly once: {href}")
        if page.locator("h1").count() != 1:
            raise AssertionError("homepage must contain exactly one H1")
        page.get_by_role("heading", name="Проект Мэсэр", level=1).wait_for()
        if page.locator('a[href="#main-content"]').count() != 1:
            raise AssertionError("homepage skip link is missing")
        if page.locator('a[href="Admin-panel.html"]').count() != 1:
            raise AssertionError("desktop service navigation link is missing or duplicated")
        desktop_service = page.get_by_role("link", name="Для служащих")
        desktop_heading_box = page.get_by_role("heading", name="Проект Мэсэр", level=1).bounding_box()
        desktop_header_box = page.locator(".site-header__content").bounding_box()
        if (not desktop_heading_box or not desktop_header_box or
                abs((desktop_heading_box["x"] + desktop_heading_box["width"] / 2) -
                    (desktop_header_box["x"] + desktop_header_box["width"] / 2)) > 1):
            raise AssertionError("desktop H1 is no longer centered in the header")
        if not desktop_service.evaluate("""el => {
            const style = getComputedStyle(el);
            return style.flexDirection === 'row' && style.whiteSpace === 'nowrap' &&
                style.textDecorationLine === 'none' && style.backgroundColor !== 'rgba(0, 0, 0, 0)';
        }"""):
            raise AssertionError("desktop service control lacks its compact control treatment")
        desktop_actions = page.locator(".resource-action")
        if desktop_actions.count() != 8:
            raise AssertionError("desktop homepage must retain eight resource actions")
        if not desktop_actions.nth(0).evaluate("""el => {
            const style = getComputedStyle(el);
            return style.minHeight === '92px' && style.borderRadius === '17px' &&
                style.transitionDuration.split(', ').every(duration => duration === '0.18s');
        }"""):
            raise AssertionError("desktop resource action treatment is not the compact refined style")
        newcomer_heading = page.get_by_role("heading", name="Кто такой зависимый?", level=2)
        heading_box = newcomer_heading.bounding_box()
        if not heading_box or heading_box["y"] >= 900:
            raise AssertionError("newcomer content begins below the initial desktop viewport")
        click_viewport_link(page, "Offline-meetings.html", "/Offline-meetings.html")

        mobile = context.new_page()
        for width in (320, 390):
            mobile.set_viewport_size({"width": width, "height": 844})
            mobile.goto(url(base_url, "/"), wait_until="domcontentloaded")
            if mobile.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
                raise AssertionError(f"homepage has horizontal overflow at {width}px")
            mobile.get_by_role("heading", name="Проект Мэсэр", level=1).wait_for(state="visible")
            service = mobile.locator('a[href="Admin-panel.html"]')
            service.wait_for(state="visible")
            heading_box = mobile.get_by_role("heading", name="Проект Мэсэр", level=1).bounding_box()
            service_box = service.bounding_box()
            if not heading_box or not service_box:
                raise AssertionError(f"header controls missing at {width}px")
            if (heading_box["x"] < service_box["x"] + service_box["width"] and
                    service_box["x"] < heading_box["x"] + heading_box["width"] and
                    heading_box["y"] < service_box["y"] + service_box["height"] and
                    service_box["y"] < heading_box["y"] + heading_box["height"]):
                raise AssertionError(f"header H1 and service link overlap at {width}px")
            horizontal_gap = service_box["x"] - (heading_box["x"] + heading_box["width"])
            if horizontal_gap < 4:
                raise AssertionError(f"header H1 and service link gap is too small at {width}px: {horizontal_gap}px")
            if service.locator("span").count() != 2 or [service.locator("span").nth(i).inner_text() for i in range(2)] != ["Для", "служащих"]:
                raise AssertionError(f"service link does not have the required two lines at {width}px")
            line_boxes = [service.locator("span").nth(i).bounding_box() for i in range(2)]
            if not line_boxes[0] or not line_boxes[1] or line_boxes[1]["y"] <= line_boxes[0]["y"]:
                raise AssertionError(f"service link lines are not stacked at {width}px")
            if not service.evaluate("el => getComputedStyle(el).whiteSpace === 'nowrap' && el.scrollWidth <= el.clientWidth"):
                raise AssertionError(f"header service link wraps unexpectedly at {width}px")
            if abs(heading_box["y"] - service_box["y"]) > max(heading_box["height"], service_box["height"]):
                raise AssertionError(f"header controls are not in the same row at {width}px")
            header_box = mobile.locator(".site-header__content").bounding_box()
            if not header_box or abs((heading_box["x"] + heading_box["width"] / 2) - (header_box["x"] + header_box["width"] / 2)) > 20:
                raise AssertionError(f"H1 is not centered in the mobile header at {width}px")
            if not mobile.evaluate("""() => {
                const columns = getComputedStyle(document.querySelector('.site-header__content')).gridTemplateColumns.split(' ');
                return columns.length === 3 && Math.abs(parseFloat(columns[0]) - parseFloat(columns[2])) <= 1;
            }"""):
                raise AssertionError(f"mobile header side tracks are not symmetric at {width}px")
            if not header_box or header_box["height"] > 96:
                raise AssertionError(f"mobile header is too tall at {width}px")
        if mobile.locator('a[href="Literature.html"]').count() != 1:
            raise AssertionError("homepage Literature destination must appear exactly once")
        mobile.locator('a[href="Literature.html"]').click()
        mobile.wait_for_url("**/Literature.html", timeout=1500)
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
