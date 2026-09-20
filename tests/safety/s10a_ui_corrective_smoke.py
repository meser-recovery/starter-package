#!/usr/bin/env python3
"""Responsive label/focus regression for the S10A protected UI corrective."""

from __future__ import annotations

import argparse

from playwright.sync_api import Page, sync_playwright


PASSWORD = "local-test-password"
VIEWPORTS = (320, 390, 768, 1280)


def login(page: Page, base_url: str) -> None:
    page.goto(base_url + "/login?return=%2FAudio-Archive.html", wait_until="domcontentloaded")
    page.locator("#admin-password").fill(PASSWORD)
    page.locator("#admin-access-form button[type=submit]").click()
    page.wait_for_url("**/Audio-Archive.html", timeout=10_000)


def assert_no_overflow(page: Page, label: str) -> None:
    dimensions = page.evaluate(
        "() => ({scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth})"
    )
    assert dimensions["scroll"] <= dimensions["client"] + 1, (label, dimensions)


def assert_field(page: Page, label_selector: str, control_selector: str, name: str) -> None:
    result = page.evaluate(
        """([labelSelector, controlSelector]) => {
          const label = document.querySelector(labelSelector);
          const caption = label?.querySelector('.field-label');
          const control = document.querySelector(controlSelector);
          if (!label || !caption || !control) return { missing: true };
          control.focus();
          const captionBox = caption.getBoundingClientRect();
          const controlBox = control.getBoundingClientRect();
          const style = getComputedStyle(control);
          return {
            associated: [...control.labels].includes(label),
            gap: controlBox.top - captionBox.bottom,
            outlineStyle: style.outlineStyle,
            outlineWidth: parseFloat(style.outlineWidth),
            outlineOffset: parseFloat(style.outlineOffset),
            focusVisible: control.matches(':focus-visible'),
            left: controlBox.left,
            right: innerWidth - controlBox.right
          };
        }""",
        [label_selector, control_selector],
    )
    assert not result.get("missing"), (name, result)
    assert result["associated"], (name, "label association")
    assert result["gap"] >= 7, (name, "gap", result["gap"])
    assert result["focusVisible"], (name, "focus-visible")
    assert result["outlineStyle"] not in ("none", "hidden"), (name, result)
    assert result["outlineWidth"] >= 3 and result["outlineOffset"] >= 2, (name, result)
    required_edge = result["outlineWidth"] + result["outlineOffset"]
    assert result["left"] >= required_edge and result["right"] >= required_edge, (name, result)


def assert_status_spacing(page: Page, form_selector: str, status_selector: str, name: str) -> None:
    result = page.evaluate(
        """([formSelector, statusSelector]) => {
          const form = document.querySelector(formSelector);
          const status = document.querySelector(statusSelector);
          if (!form || !status || status.hidden) return { skipped: true };
          const formBox = form.getBoundingClientRect();
          const statusBox = status.getBoundingClientRect();
          return { gap: statusBox.top - formBox.bottom };
        }""",
        [form_selector, status_selector],
    )
    if not result.get("skipped"):
        assert result["gap"] >= 12, (name, result)


def assert_buttons_do_not_overlap(page: Page, selectors: tuple[str, str], name: str) -> None:
    result = page.evaluate(
        """([firstSelector, secondSelector]) => {
          const a = document.querySelector(firstSelector)?.getBoundingClientRect();
          const b = document.querySelector(secondSelector)?.getBoundingClientRect();
          if (!a || !b) return { missing: true };
          const overlapX = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
          const overlapY = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
          return { overlapArea: overlapX * overlapY };
        }""",
        list(selectors),
    )
    assert not result.get("missing") and result["overlapArea"] == 0, (name, result)


def exercise(browser_type, base_url: str) -> None:
    browser = browser_type.launch()
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    login(page, base_url)

    for width in VIEWPORTS:
        page.set_viewport_size({"width": width, "height": 900})
        page.goto(base_url + "/Audio-Archive.html", wait_until="domcontentloaded")
        page.locator("#filters input[name=search]").wait_for(state="visible")
        assert_field(page, "#filters label:has(input[name=search])", "#filters input[name=search]", f"archive search {width}")
        assert_field(page, "#filters label:has(input[name=month])", "#filters input[name=month]", f"archive month {width}")
        page.locator("#filters details").evaluate("element => element.open = true")
        assert_field(page, "#filters label:has(select[name=sort])", "#filters select[name=sort]", f"archive sort {width}")
        assert_status_spacing(page, "#filters", "#matching", f"archive status {width}")
        assert_buttons_do_not_overlap(page, ("#record-picker-search", "#record-picker-recent"), f"archive actions {width}")
        assert_no_overflow(page, f"archive {width}")

        page.goto(base_url + "/Audio-Editor.html", wait_until="domcontentloaded")
        page.locator("#source-session-mode-archive").click()
        page.locator("#source-session-filters input[name=search]").wait_for(state="visible")
        assert_field(
            page,
            "#source-session-filters label:has(input[name=search])",
            "#source-session-filters input[name=search]",
            f"editor search {width}",
        )
        assert_field(
            page,
            "#source-session-filters label:has(input[name=month])",
            "#source-session-filters input[name=month]",
            f"editor month {width}",
        )
        assert_status_spacing(page, "#source-session-filters", "#source-session-count", f"editor status {width}")
        assert_buttons_do_not_overlap(
            page,
            ("#source-session-filters button[type=submit]", "#source-session-recent"),
            f"editor actions {width}",
        )
        assert_no_overflow(page, f"editor {width}")
        page.locator("#source-session-filters input[name=search]").press("Escape")
        assert page.locator("#import-zone").is_hidden()
        assert page.evaluate("document.activeElement?.id") == "source-session-mode-archive"

    page.set_viewport_size({"width": 1280, "height": 900})
    page.goto(base_url + "/Audio-Archive.html", wait_until="domcontentloaded")
    page.locator("#filters input[name=search]").wait_for(state="visible")
    page.evaluate("document.documentElement.style.zoom = '2'")
    assert_no_overflow(page, "archive desktop zoom 200%")
    assert_field(page, "#filters label:has(input[name=search])", "#filters input[name=search]", "archive zoom 200%")

    page.goto(base_url + "/Audio-Editor.html", wait_until="domcontentloaded")
    page.evaluate("document.documentElement.style.zoom = '2'")
    page.locator("#source-session-mode-archive").click()
    assert_no_overflow(page, "editor desktop zoom 200%")
    assert_field(
        page,
        "#source-session-filters label:has(input[name=search])",
        "#source-session-filters input[name=search]",
        "editor zoom 200%",
    )

    context.close()
    browser.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:4173")
    parser.add_argument("--browser", choices=("chromium", "firefox", "webkit", "all"), default="all")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    with sync_playwright() as playwright:
        names = ("chromium", "firefox", "webkit") if args.browser == "all" else (args.browser,)
        for name in names:
            exercise(getattr(playwright, name), base_url)
            print(f"S10A UI corrective geometry/focus smoke passed: {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
