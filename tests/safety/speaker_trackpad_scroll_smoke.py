#!/usr/bin/env python3
"""Real DOM wheel scrolling in a zoomed Speaker timeline (local preview only)."""
import argparse

from playwright.sync_api import sync_playwright

from s09a_smoke import fixture


def check(browser_type, base_url):
    browser = browser_type.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 650})
    try:
        page.goto(base_url + "/Audio-Archive.html")
        page.locator("#admin-password").fill("local-test-password")
        page.locator("#admin-access-form button[type=submit]").click()
        page.wait_for_url("**/Audio-Archive.html")
        page.goto(base_url + "/Audio-Editor.html")
        page.locator("#source-session-mode-device").click()
        page.locator("#processor-file").set_input_files([fixture(330), fixture(660)])
        page.locator("#source-session-use-local").click()
        page.locator("#open-local-speaker").click()
        page.wait_for_function("document.querySelectorAll('.speaker-track').length === 2")
        page.wait_for_function("document.getElementById('speaker-editor-source-audio').duration > 0")
        duration = page.locator("#speaker-editor-source-audio").evaluate("e => e.duration")

        zoom = page.locator("#speaker-editor-zoom")
        zoom.fill("4")
        zoom.dispatch_event("input")
        scrolls = page.locator("#speaker-editor-tracks .speaker-waveform-scroll")
        first = scrolls.first
        first.scroll_into_view_if_needed()
        metrics = first.evaluate("e => ({ overflow: getComputedStyle(e).overflowX, width: e.clientWidth, content: e.scrollWidth, scrollbar: getComputedStyle(e).scrollbarWidth })")
        assert metrics["content"] > metrics["width"] * 2, metrics
        assert metrics["overflow"] in ("auto", "scroll"), metrics
        assert metrics["scrollbar"] == "none", metrics
        box = first.bounding_box()
        x, y = box["x"] + box["width"] * .4, box["y"] + box["height"] * .5
        page.mouse.move(x, y)
        page.mouse.wheel(220, 0)  # Trusted, trackpad-like horizontal input; JS dispatch cannot scroll natively.
        page.wait_for_function("document.querySelector('#speaker-editor-tracks .speaker-waveform-scroll').scrollLeft > 50")
        left = first.evaluate("e => e.scrollLeft")
        page.wait_for_function("expected => [...document.querySelectorAll('#speaker-editor-tracks .speaker-waveform-scroll')].every(e => Math.abs(e.scrollLeft - expected) < 2)", arg=left)
        rail = page.locator("#speaker-editor-source-scrollbar")
        page.wait_for_function("expected => Math.abs(Number(document.querySelector('#speaker-editor-source-scrollbar').getAttribute('aria-valuenow')) - expected) <= 1", arg=left)
        # The ruler is redrawn from the same scroll offset as the tracks.
        assert page.locator("#speaker-source-timeline span").count() > 0
        ruler = page.locator("#speaker-source-timeline span").first.evaluate("e => ({ time: e.textContent, left: parseFloat(e.style.left) })")
        minutes, seconds = ruler["time"].split(":")
        pixels_per_second = first.locator(".speaker-waveform").evaluate("e => e.getBoundingClientRect().width") / duration
        assert abs(ruler["left"] - ((int(minutes) * 60 + float(seconds)) * pixels_per_second - left)) < 3, (ruler, left)

        # Ctrl+wheel still zooms around the pointer's timeline time.
        before_zoom = float(zoom.input_value())
        anchor = (left + box["width"] * .4) / pixels_per_second
        page.keyboard.down("Control")
        page.mouse.wheel(0, -120)
        page.keyboard.up("Control")
        page.wait_for_function("before => Number(document.querySelector('#speaker-editor-zoom').value) > before", arg=before_zoom)
        after_left = first.evaluate("e => e.scrollLeft")
        after_pps = first.locator(".speaker-waveform").evaluate("e => e.getBoundingClientRect().width") / duration
        assert abs((after_left + box["width"] * .4) / after_pps - anchor) < .03
        page.wait_for_function("expected => [...document.querySelectorAll('#speaker-editor-tracks .speaker-waveform-scroll')].every(e => Math.abs(e.scrollLeft - expected) < 2)", arg=after_left)

        # Custom scrollbar click and keyboard navigation remain connected to all tracks.
        rail.scroll_into_view_if_needed()
        rail_box = rail.bounding_box()
        page.mouse.click(rail_box["x"] + rail_box["width"] * .8, rail_box["y"] + rail_box["height"] / 2)
        page.wait_for_function("before => document.querySelector('#speaker-editor-tracks .speaker-waveform-scroll').scrollLeft > before + 50", arg=after_left)
        clicked_left = first.evaluate("e => e.scrollLeft")
        page.wait_for_function("expected => Math.abs(document.querySelectorAll('#speaker-editor-tracks .speaker-waveform-scroll')[1].scrollLeft - expected) < 2", arg=clicked_left)
        rail.focus()
        page.keyboard.press("Home")
        page.wait_for_function("document.querySelector('#speaker-editor-tracks .speaker-waveform-scroll').scrollLeft === 0")
        assert clicked_left > 0
        assert scrolls.nth(1).evaluate("e => e.scrollLeft") == 0
        assert rail.get_attribute("aria-valuenow") == "0"

        # Vertical wheel outside the timeline still scrolls the page.
        page.evaluate("window.scrollTo(0, 0)")
        assert page.evaluate("document.scrollingElement.scrollHeight > innerHeight")
        heading = page.locator("#speaker-editor > .archive-card__heading")
        heading_box = heading.bounding_box()
        page.mouse.move(heading_box["x"] + 20, heading_box["y"] + heading_box["height"] / 2)
        page.mouse.wheel(0, 220)
        page.wait_for_function("window.scrollY > 0")
    finally:
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:4183")
    parser.add_argument("--browser", choices=("chromium", "firefox", "webkit", "all"), default="all")
    args = parser.parse_args()
    with sync_playwright() as playwright:
        for name in ("chromium", "firefox", "webkit") if args.browser == "all" else (args.browser,):
            check(getattr(playwright, name), args.base_url.rstrip("/"))
            print(f"PASS Speaker native wheel, sync, zoom anchor, scrollbar, page scroll: {name}")
