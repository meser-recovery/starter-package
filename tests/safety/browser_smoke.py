#!/usr/bin/env python3
"""Small browser smoke suite for the public static site."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
import struct
import sys
import time
import traceback
import wave
from s09a_edit_modes_smoke import apply_selection

from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Error, sync_playwright
from archive_management_smoke import check_archive_management
from archive_management_cors_regression import check_archive_management_cors


def url(base: str, path: str) -> str:
    return base.rstrip("/") + path


def wait_for_page_ready(page, expected_selector: str = "body") -> None:
    """Wait for the page's local stylesheets and two layout frames, not network idle."""
    page.locator(expected_selector).wait_for(state="attached")
    page.wait_for_function("""() => document.body &&
        Array.from(document.querySelectorAll('link[rel~="stylesheet"]')).every(link => link.sheet !== null)""")
    page.evaluate("""() => new Promise(resolve => {
        requestAnimationFrame(() => requestAnimationFrame(resolve));
    })""")


def goto_ready(page, target_url: str, expected_selector: str = "body") -> None:
    page.goto(target_url, wait_until="domcontentloaded")
    wait_for_page_ready(page, expected_selector)


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
                wait_for_page_ready(page)
                return
            except Error:
                continue
    raise AssertionError(f"no visible in-viewport link found for {href}")


LITERATURE_ACTIONS = (
    ("Зависимый ли я?", "Literature-reader.html?doc=ip07", "Зависимый ли я?"),
    ("Новичку", "Literature-reader.html?doc=ip16", "Новичку"),
    ("Кто, что, как и почему", "Literature-reader.html?doc=ip01", "Кто, что, как и почему?"),
    ("Добро пожаловать в Сообщество АН", "Literature-reader.html?doc=ip22", "Добро пожаловать в Сообщество Анонимные Наркоманы"),
    ("Треугольник одержимости", "Literature-reader.html?doc=ip12", "Треугольник одержимости своими желаниями"),
    ("Юным зависимым от юных зависимых", "Literature-reader.html?doc=ip13", "Юным зависимым от юных зависимых"),
    ("Дополнительная литература", "https://na-russia.org/literatures?category=recovery-literature", None),
)

HOMEPAGE_ACTION_ORDER = (
    "Онлайн собрания", "Живые собрания", "Информационные проспекты", "Базовый текст (аудио)",
    "Ежедневные размышления", "Радио NA", "Слушать спикерские NA", "Калькулятор чистого периода",
)


def visible_text(locator) -> str:
    return locator.evaluate("""element => Array.from(element.childNodes)
        .filter(node => node.nodeType === Node.TEXT_NODE)
        .map(node => node.textContent)
        .join(\"\").trim()""")


def assert_reader_canvases(page, document_id: str) -> int:
    page.locator(".brochure-page canvas").nth(0).wait_for(state="visible", timeout=20000)
    page.wait_for_function("document.getElementById('reader-status').textContent.includes('Показано страниц:')", timeout=30000)
    canvas_count = page.locator(".brochure-page canvas").count()
    status_count = int(page.locator("#reader-status").inner_text().rsplit(":", 1)[1].strip())
    if canvas_count < 1 or canvas_count != status_count:
        raise AssertionError(
            f"Literature reader did not fully render {document_id}: canvases={canvas_count}, status={status_count}"
        )
    if not page.locator(".brochure-page canvas").evaluate_all(
        """canvases => canvases.every(canvas => canvas.width > 0 && canvas.height > 0)"""
    ):
        raise AssertionError(f"Literature reader contains a zero-size canvas for {document_id}")
    if not page.locator(".brochure-page canvas").nth(0).evaluate("""canvas => {
        const context = canvas.getContext('2d');
        const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
        const stride = Math.max(4, Math.floor(pixels.length / 20000 / 4) * 4);
        for (let index = 0; index < pixels.length; index += stride) {
            if (pixels[index] < 245 || pixels[index + 1] < 245 || pixels[index + 2] < 245) return true;
        }
        return false;
    }"""):
        raise AssertionError(f"Literature reader first page appears blank for {document_id}")
    return canvas_count


def check_literature(page, base_url: str, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    goto_ready(page, url(base_url, "/Literature.html"))
    if not page.evaluate("document.body.scrollHeight >= window.innerHeight"):
        raise AssertionError(f"Literature does not fill the viewport at {width}px")
    if page.locator("html").get_attribute("lang") != "ru":
        raise AssertionError("Literature must use Russian document language")
    if page.locator("h1").count() != 1 or page.locator("h1").inner_text() != "Информационные проспекты":
        raise AssertionError("Literature must retain one correct H1")
    if page.locator("main#main-content").count() != 1:
        raise AssertionError("Literature main landmark is missing")
    if page.locator('a[href="#main-content"]').count() != 1:
        raise AssertionError("Literature skip link is missing")
    if page.locator(".site-header__identity").count() != 1 or page.locator(".site-header__logo").count() != 1:
        raise AssertionError("Literature shared home navigation is missing")
    if page.locator('a.service-link[href="Admin-panel.html"]').count() != 1:
        raise AssertionError("Literature service control is missing")
    if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
        raise AssertionError(f"Literature has horizontal overflow at {width}px")
    actions = page.locator("a.literature-action")
    if actions.count() != len(LITERATURE_ACTIONS):
        raise AssertionError("Literature must retain seven resource actions")
    for index, (label, href, _title) in enumerate(LITERATURE_ACTIONS):
        action = actions.nth(index)
        if visible_text(action) != label or action.get_attribute("href") != href:
            raise AssertionError(f"Literature action {index + 1} label or href changed")
        if index < 6 and action.get_attribute("target") is not None:
            raise AssertionError(f"Literature action {index + 1} must stay in the same tab")
        if index == 6 and (action.get_attribute("target") != "_blank" or not {"noopener", "noreferrer"}.issubset(set((action.get_attribute("rel") or "").split()))):
            raise AssertionError("Literature final action lacks safe external-link semantics")
        if not action.evaluate("element => element.tagName === 'A' && element.tabIndex >= 0"):
            raise AssertionError(f"Literature action {index + 1} is not keyboard accessible")
        action.focus()
        if not action.evaluate("element => document.activeElement === element"):
            raise AssertionError(f"Literature action {index + 1} cannot receive keyboard focus")
        if action.evaluate("element => element.scrollWidth > element.clientWidth"):
            raise AssertionError(f"Literature action {index + 1} label is clipped at {width}px")
    if width >= 768:
        grid_box = page.locator(".literature-grid").bounding_box()
        first_box = actions.nth(0).bounding_box()
        last_box = actions.nth(-1).bounding_box()
        if not grid_box or not first_box or not last_box:
            raise AssertionError(f"Literature action layout boxes missing at {width}px")
        width_delta = abs(last_box["width"] - first_box["width"])
        center_delta = abs((last_box["x"] + last_box["width"] / 2) - (grid_box["x"] + grid_box["width"] / 2))
        if width_delta > 2 or center_delta > 2 or last_box["y"] <= first_box["y"]:
            raise AssertionError(
                f"Literature final action is not visibly centered at {width}px: "
                f"width delta={width_delta:.2f}, center delta={center_delta:.2f}, "
                f"action={last_box}, grid={grid_box}"
            )


def check_literature_reader(page, base_url: str, document_id: str, expected_title: str, width: int) -> None:
    requested_paths: list[str] = []

    def capture_request(request) -> None:
        requested_paths.append(urlparse(request.url).path)

    page.on("request", capture_request)
    page.set_viewport_size({"width": width, "height": 900})
    try:
        goto_ready(page, url(base_url, f"/Literature-reader.html?doc={document_id}"))
        assert_reader_canvases(page, document_id)
    finally:
        page.remove_listener("request", capture_request)
    if ".pdf" in urlparse(page.url).path or not urlparse(page.url).path.endswith("/Literature-reader.html"):
        raise AssertionError(f"Literature reader navigated to a PDF for {document_id}")
    if page.locator("html").get_attribute("lang") != "ru" or page.locator("h1").count() != 1:
        raise AssertionError(f"Literature reader shell is invalid for {document_id}")
    if page.locator("h1").inner_text() != expected_title:
        raise AssertionError(f"Literature reader title is wrong for {document_id}")
    if page.locator('a[href="Literature.html"]').count() != 1:
        raise AssertionError(f"Literature reader back link is missing for {document_id}")
    if page.locator(".reader-error").is_visible():
        raise AssertionError(f"Literature reader showed an error for {document_id}")
    if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
        raise AssertionError(f"Literature reader has horizontal overflow for {document_id} at {width}px")
    if not page.evaluate("performance.getEntriesByType('resource').some(entry => new URL(entry.name).pathname.includes('/documents/literature/'))"):
        raise AssertionError(f"Literature reader did not request a local PDF for {document_id}")
    if not any(path.endswith("/vendor/pdfjs/pdf.legacy.mjs") for path in requested_paths):
        raise AssertionError(f"Literature reader did not load the legacy PDF.js main bundle for {document_id}")
    if not any(path.endswith("/vendor/pdfjs/pdf.worker.legacy.mjs") for path in requested_paths):
        raise AssertionError(f"Literature reader did not load the matching legacy PDF.js worker for {document_id}")
    if any(path.endswith("/vendor/pdfjs/pdf.mjs") or path.endswith("/vendor/pdfjs/pdf.worker.mjs") for path in requested_paths):
        raise AssertionError(f"Literature reader loaded an obsolete modern PDF.js bundle for {document_id}")
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(100)
    if page.evaluate("document.body.scrollHeight > window.innerHeight && window.scrollY === 0"):
        raise AssertionError(f"Literature reader did not permit vertical scrolling for {document_id}")
    assert_reader_canvases(page, document_id)


def check_literature_reader_error(page, base_url: str) -> None:
    page.set_viewport_size({"width": 390, "height": 900})
    goto_ready(page, url(base_url, "/Literature-reader.html?doc=unknown"))
    page.locator(".reader-error").wait_for(state="visible")
    if page.locator(".brochure-page canvas").count() != 0 or ".pdf" in urlparse(page.url).path:
        raise AssertionError("Unknown literature route is not handled safely")


def check_literature_reader_resize_stability(page, base_url: str, document_id: str, expected_title: str) -> None:
    page.set_viewport_size({"width": 390, "height": 844})
    goto_ready(page, url(base_url, f"/Literature-reader.html?doc={document_id}"))
    if page.locator("h1").inner_text() != expected_title:
        raise AssertionError(f"Literature reader resize title is wrong for {document_id}")
    initial_page_count = assert_reader_canvases(page, document_id)

    page.evaluate("document.querySelector('.brochure-page canvas').dataset.resizeProbe = 'portrait-original'")
    page.set_viewport_size({"width": 844, "height": 390})
    page.wait_for_function("!document.querySelector(\"canvas[data-resize-probe='portrait-original']\")", timeout=30000)
    if assert_reader_canvases(page, document_id) != initial_page_count:
        raise AssertionError(f"Reader page count changed in landscape for {document_id}")
    page.evaluate("document.querySelector('.brochure-page canvas').dataset.resizeProbe = 'landscape-original'")
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_function("!document.querySelector(\"canvas[data-resize-probe='landscape-original']\")", timeout=30000)
    if assert_reader_canvases(page, document_id) != initial_page_count:
        raise AssertionError(f"Reader page count changed after returning to portrait for {document_id}")

    page.evaluate("""() => {
        const pages = document.getElementById('brochure-pages');
        pages.querySelector('canvas').dataset.resizeProbe = 'height-original';
        window.__readerResizeProbe = { replacements: 0, sawBlank: false };
        new MutationObserver(records => {
            window.__readerResizeProbe.replacements += records.filter(
                record => record.addedNodes.length || record.removedNodes.length
            ).length;
            if (!pages.querySelector('canvas')) window.__readerResizeProbe.sawBlank = true;
        }).observe(pages, { childList: true });
    }""")

    for height in (700, 820, 740, 844):
        page.set_viewport_size({"width": 390, "height": height})
        page.evaluate("window.dispatchEvent(new Event('resize'))")
    page.wait_for_timeout(500)
    if page.locator("canvas[data-resize-probe='height-original']").count() != 1:
        raise AssertionError("Height-only resize unnecessarily replaced the rendered brochure")
    if page.evaluate("window.__readerResizeProbe.replacements") != 0:
        raise AssertionError("Height-only resize caused brochure DOM replacement")

    page.evaluate("""() => {
        window.__originalCanvasGetContext = HTMLCanvasElement.prototype.getContext;
        HTMLCanvasElement.prototype.getContext = () => { throw new Error('forced responsive render failure'); };
    }""")
    with page.expect_event(
        "console",
        predicate=lambda message: "stage=canvas/render-responsive" in message.text,
        timeout=10000,
    ):
        page.set_viewport_size({"width": 430, "height": 844})
    if page.locator("canvas[data-resize-probe='height-original']").count() != 1:
        raise AssertionError("Failed responsive rerender destroyed the existing brochure")
    if page.locator(".reader-error").is_visible() or page.evaluate("window.__readerResizeProbe.sawBlank"):
        raise AssertionError("Failed responsive rerender exposed a user-visible or blank error state")
    page.evaluate("() => { HTMLCanvasElement.prototype.getContext = window.__originalCanvasGetContext; }")

    page.set_viewport_size({"width": 431, "height": 844})
    page.wait_for_function("!document.querySelector(\"canvas[data-resize-probe='height-original']\")", timeout=30000)
    if page.evaluate("window.__readerResizeProbe.replacements") != 1:
        raise AssertionError("One material width change did not produce exactly one atomic brochure replacement")
    page.evaluate("document.querySelector('.brochure-page canvas').dataset.resizeProbe = 'rapid-original'")

    for viewport in (
        {"width": 410, "height": 760},
        {"width": 440, "height": 700},
        {"width": 400, "height": 820},
        {"width": 420, "height": 844},
    ):
        page.set_viewport_size(viewport)
        page.evaluate("window.dispatchEvent(new Event('resize'))")
    page.wait_for_function("""() => {
        const canvas = document.querySelector('.brochure-page canvas');
        const pages = document.getElementById('brochure-pages');
        return canvas && !canvas.matches('[data-resize-probe="rapid-original"]') &&
            Math.abs(parseFloat(canvas.style.width) - (pages.clientWidth - 16)) <= 1;
    }""", timeout=30000)

    if page.locator(".reader-error").is_visible():
        raise AssertionError(f"Reader error became visible during resize lifecycle tests for {document_id}")
    if page.locator(".brochure-page canvas").count() != initial_page_count:
        raise AssertionError(f"Reader page count changed during resize lifecycle tests for {document_id}")
    if page.evaluate("window.__readerResizeProbe.sawBlank"):
        raise AssertionError("Reader exposed a blank brochure state during atomic replacement")
    if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
        raise AssertionError("Literature reader has horizontal overflow after rapid resize")
    if not page.locator(".brochure-page canvas").evaluate_all(
        "canvases => canvases.every(canvas => canvas.width > 0 && canvas.height > 0)"
    ):
        raise AssertionError("Literature reader contains an unreadable blank-size canvas after resize")
    if ".pdf" in urlparse(page.url).path or not urlparse(page.url).path.endswith("/Literature-reader.html"):
        raise AssertionError("Literature reader navigated away during resize lifecycle tests")


def check_literature_reader_diagnostics(browser, base_url: str) -> None:
    cases = (
        ("bootstrap", "LIT-BOOT", "bootstrap", "**/vendor/pdfjs/pdf.legacy.mjs", "abort"),
        ("worker", "LIT-WORKER", "worker-initialization", "**/vendor/pdfjs/pdf.worker.legacy.mjs", "abort"),
        ("fetch", "LIT-FETCH", "pdf-fetch", "**/documents/literature/ip-16-novichku.pdf", "abort"),
        ("pdf", "LIT-PDF", "pdf-parse", "**/documents/literature/ip-16-novichku.pdf", "invalid-pdf"),
        ("render", "LIT-RENDER", "canvas/render", None, "no-canvas"),
    )
    for label, code, stage, pattern, behavior in cases:
        context = browser.new_context(viewport={"width": 390, "height": 844})
        page = context.new_page()
        console_messages: list[str] = []
        page.on("console", lambda message: console_messages.append(message.text))
        if behavior == "abort":
            page.route(pattern, lambda route: route.abort())
        elif behavior == "invalid-pdf":
            page.route(pattern, lambda route: route.fulfill(
                status=200, content_type="application/pdf", body=b"not a PDF"
            ))
        elif behavior == "no-canvas":
            page.add_init_script("HTMLCanvasElement.prototype.getContext = () => null;")
        try:
            goto_ready(page, url(base_url, "/Literature-reader.html?doc=ip16"))
            page.locator(".reader-error").wait_for(state="visible", timeout=20000)
            error_text = page.locator(".reader-error").inner_text()
            if code not in error_text:
                raise AssertionError(f"Literature {label} diagnostic did not expose {code}: {error_text}")
            if any(fragment in error_text for fragment in ("http://", "https://", "/vendor/", "Error:")):
                raise AssertionError(f"Literature {label} diagnostic exposed technical internals")
            if not any(
                f"stage={stage}" in message and "name=" in message and "message=" in message
                for message in console_messages
            ):
                raise AssertionError(f"Literature {label} diagnostic omitted console stage/name/message")
        finally:
            context.close()


def check_literature_mobile_compatibility(browser, base_url: str, device: dict, label: str) -> None:
    context = browser.new_context(**device)
    site_host = urlparse(base_url).netloc

    def block_external(route):
        if urlparse(route.request.url).netloc not in {"", site_host}:
            route.abort()
        else:
            route.continue_()

    context.route("**/*", block_external)
    page = context.new_page()
    try:
        for document_id, expected_title in (("ip16", "Новичку"), ("ip07", "Зависимый ли я?")):
            check_literature_reader(page, base_url, document_id, expected_title, 390)
            check_literature_reader_resize_stability(page, base_url, document_id, expected_title)
    except AssertionError as exc:
        raise AssertionError(f"{label}: {exc}") from exc
    finally:
        context.close()


def capture_screenshots(page, base_url: str, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    captures = (
        ("homepage-390.png", "/", 390),
        ("homepage-1280.png", "/", 1280),
        ("literature-390.png", "/Literature.html", 390),
        ("literature-1280.png", "/Literature.html", 1280),
        ("literature-reader-ip07-390.png", "/Literature-reader.html?doc=ip07", 390),
        ("literature-reader-ip07-1280.png", "/Literature-reader.html?doc=ip07", 1280),
        ("literature-reader-ip16-390.png", "/Literature-reader.html?doc=ip16", 390),
    )
    for filename, path, width in captures:
        page.set_viewport_size({"width": width, "height": 900})
        goto_ready(page, url(base_url, path))
        if "Literature-reader" in path:
            page.locator(".brochure-page canvas").nth(0).wait_for(state="visible", timeout=20000)
            page.wait_for_function("document.getElementById('reader-status').textContent.includes('Показано страниц:')", timeout=30000)
        page.screenshot(path=str(directory / filename), full_page=False)


def check_audiobook(page, base_url: str, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    goto_ready(page, url(base_url, "/AudioBook.html"))
    if not page.evaluate("document.body.scrollHeight >= window.innerHeight"):
        raise AssertionError(f"AudioBook does not fill the viewport at {width}px")
    if page.locator("html").get_attribute("lang") != "ru":
        raise AssertionError("AudioBook must use Russian document language")
    if page.locator("h1").count() != 1 or page.locator("h1").inner_text() != "Базовый текст (аудио)":
        raise AssertionError("AudioBook must retain one correct outer H1")
    if page.locator("main#main-content").count() != 1:
        raise AssertionError("AudioBook main landmark is missing")
    if page.locator('a[href="#main-content"]').count() != 1:
        raise AssertionError("AudioBook skip link is missing")
    if page.locator(".site-header__identity").count() != 1 or page.locator(".site-header__logo").count() != 1:
        raise AssertionError("AudioBook shared home navigation is missing")
    service = page.locator('a.service-link[href="Admin-panel.html"]')
    if service.count() != 1:
        raise AssertionError("AudioBook service control is missing")
    if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
        raise AssertionError(f"AudioBook has horizontal overflow at {width}px")
    frame_element = page.locator('iframe[src="bt6-player.html"]')
    if frame_element.count() != 1 or not (frame_element.get_attribute("title") or "").strip():
        raise AssertionError("AudioBook must retain one titled local player iframe")
    frame_box = frame_element.bounding_box()
    embed_box = page.locator(".audiobook-embed").bounding_box()
    identity_box = page.locator(".site-header__identity").bounding_box()
    service_box = service.bounding_box()
    if not frame_box or not embed_box or not identity_box or not service_box:
        raise AssertionError(f"AudioBook layout controls missing at {width}px")
    left_delta = abs(frame_box["x"] - embed_box["x"])
    right_delta = abs((frame_box["x"] + frame_box["width"]) - (embed_box["x"] + embed_box["width"]))
    width_delta = abs(frame_box["width"] - embed_box["width"])
    if not frame_element.evaluate("frame => frame.parentElement?.classList.contains('audiobook-embed')"):
        raise AssertionError("AudioBook player iframe is no longer contained by .audiobook-embed")
    if max(left_delta, right_delta, width_delta) > 2:
        raise AssertionError(
            f"AudioBook player no longer fills its embed at {width}px: "
            f"left delta={left_delta:.2f}, right delta={right_delta:.2f}, width delta={width_delta:.2f}, "
            f"frame={frame_box}, embed={embed_box}"
        )
    if (identity_box["x"] < service_box["x"] + service_box["width"] and
            service_box["x"] < identity_box["x"] + identity_box["width"] and
            identity_box["y"] < service_box["y"] + service_box["height"] and
            service_box["y"] < identity_box["y"] + identity_box["height"]):
        raise AssertionError(f"AudioBook header identity overlaps service control at {width}px")
    frame = page.frame_locator('iframe[src="bt6-player.html"]')
    frame.locator("#playlist li").nth(0).wait_for(timeout=10000)
    frame.locator("#audio").wait_for(state="visible")
    frame.locator(".player-wrap").wait_for(state="visible")
    if not frame.locator("#playlist").is_visible():
        raise AssertionError(f"AudioBook playlist is not visible at {width}px")
    if not frame.locator("html").evaluate("document.documentElement.scrollWidth <= window.innerWidth"):
        raise AssertionError(f"AudioBook iframe content has horizontal clipping at {width}px")
    if not frame.locator("html").evaluate("document.documentElement.scrollHeight <= window.innerHeight"):
        raise AssertionError(f"AudioBook iframe is too short for its player content at {width}px")
    content_height = frame.locator("body").evaluate("""() => {
        const player = document.querySelector('.player-wrap');
        if (!player) return 0;
        const styles = getComputedStyle(player);
        return player.getBoundingClientRect().bottom + parseFloat(styles.marginBottom);
    }""")
    frame_height = frame.locator("html").evaluate("window.innerHeight")
    if not content_height or frame_height < content_height or frame_height - content_height > 48:
        raise AssertionError(f"AudioBook iframe has excessive unused height at {width}px")


def offline_filter_state(page, selected_city: str) -> dict:
    return page.evaluate("""selectedCity => {
        const cityFilter = document.getElementById('cityFilter');
        const headings = Array.from(document.querySelectorAll('#meetings-content > h2'));
        const exactMatches = headings.filter(heading => heading.textContent.trim() === selectedCity);
        const substringMatches = headings.filter(heading => heading.textContent.includes(selectedCity));
        const visibleCities = headings.filter(heading => !heading.hidden).map(heading => heading.textContent.trim());
        return {
            selectedCity,
            cityFilterValue: cityFilter?.value || '',
            exactMatchCount: exactMatches.length,
            exactMatches: exactMatches.map(heading => ({ text: heading.textContent.trim(), hidden: heading.hidden })),
            substringMatchCount: substringMatches.length,
            substringMatches: substringMatches.map(heading => heading.textContent.trim()),
            visibleCityCount: visibleCities.length,
            visibleCities,
            viewport: { width: window.innerWidth, height: window.innerHeight },
            sourceDate: document.getElementById('meetings-date')?.textContent.trim() || '',
        };
    }""", selected_city)


def assert_offline_city_filter(page, selected_city: str) -> None:
    try:
        page.wait_for_function("""selectedCity => {
            const cityFilter = document.getElementById('cityFilter');
            const headings = Array.from(document.querySelectorAll('#meetings-content > h2'));
            const exactMatches = headings.filter(heading => heading.textContent.trim() === selectedCity);
            const visibleHeadings = headings.filter(heading => !heading.hidden);
            return cityFilter?.value === selectedCity && exactMatches.length === 1 &&
                exactMatches[0].hidden === false && visibleHeadings.length === 1 &&
                visibleHeadings[0].textContent.trim() === selectedCity;
        }""", arg=selected_city, timeout=15000)
    except Error as exc:
        raise AssertionError(
            "Offline Meetings city filter invariant failed: "
            f"{json.dumps(offline_filter_state(page, selected_city), ensure_ascii=False)}"
        ) from exc


def assert_offline_all_cities(page, expected_city_count: int) -> None:
    try:
        page.wait_for_function("""expectedCount => {
            const cityFilter = document.getElementById('cityFilter');
            const headings = Array.from(document.querySelectorAll('#meetings-content > h2'));
            return cityFilter?.value === 'all' && headings.length === expectedCount &&
                headings.length > 1 && headings.every(heading => !heading.hidden);
        }""", arg=expected_city_count, timeout=15000)
    except Error as exc:
        raise AssertionError(
            "Offline Meetings all-cities invariant failed: "
            f"{json.dumps(offline_filter_state(page, 'all'), ensure_ascii=False)}"
        ) from exc


def check_offline_meetings(page, base_url: str, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    goto_ready(page, url(base_url, "/Offline-meetings.html"))
    page.wait_for_function("""() => {
        const loading = document.getElementById('na-loading');
        const select = document.getElementById('cityFilter');
        return loading && loading.hidden && select && select.options.length > 2;
    }""", timeout=15000)
    if page.locator("html").get_attribute("lang") != "ru":
        raise AssertionError("Offline Meetings must use Russian document language")
    if page.locator("h1").count() != 1 or page.locator("h1").inner_text() != "Живые группы АН - Россия":
        raise AssertionError("Offline Meetings must retain exactly one outer H1")
    if page.locator("main#main-content").count() != 1 or page.locator('a[href="#main-content"]').count() != 1:
        raise AssertionError("Offline Meetings main landmark or skip link is missing")
    if page.locator(".site-header__identity").count() != 1 or page.locator(".site-header__logo").count() != 1:
        raise AssertionError("Offline Meetings shared home navigation is missing")
    if page.locator('a.service-link[href="Admin-panel.html"]').count() != 1:
        raise AssertionError("Offline Meetings service control is missing")
    if not page.locator("body").evaluate("element => getComputedStyle(element).display === 'flex' && element.scrollHeight >= window.innerHeight"):
        raise AssertionError(f"Offline Meetings shared full-height shell is missing at {width}px")
    if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
        raise AssertionError(f"Offline Meetings has horizontal overflow at {width}px")
    if page.locator('script[src="scripts/offline-meetings.js"]').count() != 1:
        raise AssertionError("Offline Meetings dedicated runtime is missing")
    if page.evaluate("document.documentElement.innerHTML.toLowerCase().includes('nicepage') || document.documentElement.innerHTML.toLowerCase().includes('jquery')"):
        raise AssertionError("Offline Meetings retains a Nicepage or jQuery dependency")
    if not page.evaluate("performance.getEntriesByType('resource').some(entry => new URL(entry.name).pathname.endsWith('/na_meetings_live.html'))"):
        raise AssertionError("Offline Meetings did not fetch its generated source")
    source_date = page.evaluate("""async () => {
        const source = await fetch('na_meetings_live.html').then(response => response.text());
        const heading = new DOMParser().parseFromString(source, 'text/html').querySelector('.na-meetings h1');
        const match = (heading?.textContent || '').match(/(\\d{4})-(\\d{2})-(\\d{2})/);
        return match ? `${match[3]}-${match[2]}-${match[1]}` : '';
    }""")
    subtitle = page.locator("#meetings-date")
    if source_date and (subtitle.is_hidden() or subtitle.inner_text() != f"Расписание собраний на {source_date}"):
        raise AssertionError("Offline Meetings date subtitle does not match the generated source")
    city_filter = page.locator("#cityFilter")
    city_blocks = page.locator("#meetings-content > h2")
    if city_blocks.count() < 2:
        raise AssertionError("Offline Meetings did not render generated city headings")
    if city_blocks.evaluate_all("headings => headings.filter(heading => !heading.hidden).length") < 2:
        raise AssertionError("Offline Meetings does not initially show all city blocks")
    city_names = city_filter.locator("option").evaluate_all(
        "options => options.map(option => option.value).filter(value => value && value !== 'all')"
    )
    if not city_names:
        raise AssertionError("Offline Meetings city names were not dynamically populated")
    selected_cities = [city_names[0]]
    substring_sensitive_city = next(
        (city for city in city_names if any(other != city and city in other for other in city_names)), None
    )
    if substring_sensitive_city and substring_sensitive_city not in selected_cities:
        selected_cities.append(substring_sensitive_city)
    for selected_city in selected_cities:
        city_filter.select_option(selected_city)
        assert_offline_city_filter(page, selected_city)
        city_filter.select_option("all")
        assert_offline_all_cities(page, city_blocks.count())
    if page.locator("footer.site-footer").count() != 1:
        raise AssertionError("Offline Meetings shared footer is missing")


def check_offline_meetings_failure(browser, base_url: str) -> None:
    context = browser.new_context(viewport={"width": 390, "height": 900})
    context.route("**/na_meetings_live.html", lambda route: route.abort())
    page = context.new_page()
    goto_ready(page, url(base_url, "/Offline-meetings.html"))
    error = page.locator("#na-loading")
    error.wait_for(state="visible")
    page.wait_for_function("document.getElementById('na-loading').textContent.includes('Ошибка загрузки данных')")
    if error.inner_text() != "Ошибка загрузки данных. Попробуйте позже.":
        raise AssertionError("Offline Meetings fetch failure does not show the expected Russian error")
    context.close()


def check_delayed_stylesheet_readiness(browser, base_url: str) -> None:
    """Prove goto_ready waits for a shared stylesheet rather than localhost timing."""
    site_host = urlparse(base_url).netloc
    delayed_stylesheets = 0
    context = browser.new_context(viewport={"width": 1280, "height": 900})

    def delay_shared_stylesheet(route):
        nonlocal delayed_stylesheets
        parsed = urlparse(route.request.url)
        if parsed.netloc not in {"", site_host}:
            route.abort()
            return
        if parsed.path.endswith("/styles/components.css") and delayed_stylesheets == 0:
            delayed_stylesheets += 1
            time.sleep(0.25)
        route.continue_()

    context.route("**/*", delay_shared_stylesheet)
    page = context.new_page()
    try:
        goto_ready(page, url(base_url, "/"))
        service_style = page.get_by_role("link", name="Для служащих").evaluate("""el => {
            const style = getComputedStyle(el);
            return { display: style.display, backgroundColor: style.backgroundColor, minHeight: parseFloat(style.minHeight) };
        }""")
        if delayed_stylesheets != 1:
            raise AssertionError("Delayed stylesheet readiness check did not intercept components.css")
        if (service_style["display"] not in {"inline-flex", "flex"} or
                service_style["backgroundColor"] == "rgba(0, 0, 0, 0)" or
                service_style["minHeight"] < 44):
            raise AssertionError(
                f"Stylesheet readiness helper returned before shared styles applied: {service_style}"
            )
    finally:
        context.close()


def calculator_wheel_parts(ymd: str) -> list[str]:
    year, month, day = ymd.split("-")
    return [str(int(day)), str(int(month)), year]


def calculator_wheel_state(page, expected_ymd: str) -> dict:
    return page.evaluate("""expected => {
        const wheels = ['cp-wheel-day', 'cp-wheel-month', 'cp-wheel-year'].map((id) => {
            const wheel = document.getElementById(id);
            const active = wheel?.querySelector('.cp-wheel-item.is-active');
            const wheelRect = wheel?.getBoundingClientRect();
            const activeRect = active?.getBoundingClientRect();
            const offsetY = wheelRect && activeRect
                ? ((activeRect.top + activeRect.bottom) - (wheelRect.top + wheelRect.bottom)) / 2
                : null;
            return {
                id,
                active: active?.dataset.value || '',
                scrollTop: wheel?.scrollTop ?? null,
                activeCenterY: activeRect ? (activeRect.top + activeRect.bottom) / 2 : null,
                wheelCenterY: wheelRect ? (wheelRect.top + wheelRect.bottom) / 2 : null,
                offsetY,
            };
        });
        return { expected, wheels };
    }""", calculator_wheel_parts(expected_ymd))


def wait_for_calculator_wheel_alignment(page, phase: str, expected_ymd: str) -> None:
    expected = calculator_wheel_parts(expected_ymd)
    try:
        page.wait_for_function("""expected => {
            return ['cp-wheel-day', 'cp-wheel-month', 'cp-wheel-year'].every((id, index) => {
                const wheel = document.getElementById(id);
                const active = wheel?.querySelector('.cp-wheel-item.is-active');
                if (!wheel || !active || active.dataset.value !== expected[index]) return false;
                const wheelRect = wheel.getBoundingClientRect();
                const activeRect = active.getBoundingClientRect();
                return Math.abs(((activeRect.top + activeRect.bottom) - (wheelRect.top + wheelRect.bottom)) / 2) <= 1;
            });
        }""", arg=expected)
    except Error as exc:
        raise AssertionError(
            f"Calculator wheel alignment did not settle after {phase}: {calculator_wheel_state(page, expected_ymd)}"
        ) from exc


def check_calculator(page, base_url: str, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    goto_ready(page, url(base_url, "/Calculator.html"))
    page.evaluate("localStorage.removeItem('clean_period_start_date_v4')")
    page.reload(wait_until="domcontentloaded")
    wait_for_page_ready(page)
    if page.locator("html").get_attribute("lang") != "ru":
        raise AssertionError("Calculator must use Russian document language")
    if page.locator("body.site-page").count() != 1 or page.locator("main#main-content").count() != 1:
        raise AssertionError("Calculator shared page shell or main landmark is missing")
    if page.locator("h1").count() != 1 or page.locator("h1").inner_text() != "Калькулятор чистого периода":
        raise AssertionError("Calculator must retain one correct outer H1")
    if page.locator("h2#cp-title").count() != 1 or page.locator("h2#cp-title").inner_text() != "Мой чистый период":
        raise AssertionError("Calculator card title must be a correct H2")
    if page.locator('a[href="#main-content"]').count() != 1 or page.locator(".site-header__logo").count() != 1 or page.locator(".site-header__identity").count() != 1:
        raise AssertionError("Calculator shared navigation is missing")
    if page.locator('a.service-link[href="Admin-panel.html"]').count() != 1 or page.locator("footer.site-footer").count() != 1:
        raise AssertionError("Calculator shared service link or footer is missing")
    if page.locator('script[src="scripts/calculator.js"]').count() != 1:
        raise AssertionError("Calculator dedicated runtime is missing")
    if page.evaluate("document.documentElement.innerHTML.toLowerCase().includes('nicepage') || document.documentElement.innerHTML.toLowerCase().includes('jquery')"):
        raise AssertionError("Calculator retains a Nicepage or jQuery dependency")
    if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
        raise AssertionError(f"Calculator has horizontal overflow at {width}px")
    neutral = page.evaluate("""() => ({
        total: document.getElementById('cp-totalDays').textContent,
        years: document.getElementById('cp-years').textContent,
        months: document.getElementById('cp-months').textContent,
        days: document.getElementById('cp-days').textContent,
        line: document.getElementById('cp-resultLine').textContent,
        note: document.getElementById('cp-note').textContent,
    })""")
    if neutral != {"total": "0", "years": "0", "months": "0", "days": "0", "line": "Выбери дату начала", "note": ""}:
        raise AssertionError(f"Calculator without a saved date must remain neutral: {neutral}")
    reset = page.locator("#cp-reset")
    if reset.count() != 1 or reset.inner_text() != "Сброс" or reset.get_attribute("type") != "button":
        raise AssertionError("Calculator reset action must be a Сброс button")
    modal = page.locator("#cp-modal")
    if modal.get_attribute("aria-hidden") != "true" or modal.is_visible():
        raise AssertionError("Calculator modal must be initially hidden")
    page.locator("#cp-openPicker").click()
    if modal.get_attribute("aria-hidden") != "false" or not modal.is_visible():
        raise AssertionError("Calculator modal did not open")
    page.wait_for_function("document.activeElement && document.activeElement.id === 'cp-closeModal'")
    wait_for_calculator_wheel_alignment(page, "opening the modal", "1953-10-05")
    page.keyboard.press("Escape")
    if modal.get_attribute("aria-hidden") != "true" or modal.is_visible():
        raise AssertionError("Calculator modal did not close with Escape")
    page.wait_for_function("document.activeElement && document.activeElement.id === 'cp-openPicker'")
    page.locator("#cp-openPicker").click()
    page.locator("#cp-closeBackdrop").click(position={"x": 2, "y": 2})
    if modal.get_attribute("aria-hidden") != "true" or modal.is_visible():
        raise AssertionError("Calculator modal did not close from its backdrop")
    page.evaluate("localStorage.setItem('clean_period_start_date_v4', '2000-01-02')")
    page.reload(wait_until="domcontentloaded")
    wait_for_page_ready(page)
    page.locator("#cp-openPicker").click()
    wait_for_calculator_wheel_alignment(page, "opening a saved date", "2000-01-02")
    saved_summary = page.evaluate("""() => ({
        total: document.getElementById('cp-totalDays').textContent,
        line: document.getElementById('cp-resultLine').textContent,
        note: document.getElementById('cp-note').textContent,
    })""")
    reset.click()
    wait_for_calculator_wheel_alignment(page, "selecting Сброс", "1953-10-05")
    if page.evaluate("localStorage.getItem('clean_period_start_date_v4')") != "2000-01-02":
        raise AssertionError("Calculator Сброс must not change localStorage before Сохранить")
    if page.evaluate("""() => ({
        total: document.getElementById('cp-totalDays').textContent,
        line: document.getElementById('cp-resultLine').textContent,
        note: document.getElementById('cp-note').textContent,
    })""") != saved_summary:
        raise AssertionError("Calculator Сброс must not change the rendered result before Сохранить")
    page.locator("#cp-save").click()
    if page.evaluate("localStorage.getItem('clean_period_start_date_v4')") != "1953-10-05" or int(page.locator("#cp-totalDays").inner_text()) <= 0:
        raise AssertionError("Calculator Сохранить after Сброс must persist 1953-10-05 and render a positive total")
    page.reload(wait_until="domcontentloaded")
    wait_for_page_ready(page)
    if page.evaluate("localStorage.getItem('clean_period_start_date_v4')") != "1953-10-05" or int(page.locator("#cp-totalDays").inner_text()) <= 0:
        raise AssertionError("Calculator persisted reset state did not render after reload")
    page.locator("#cp-openPicker").click()
    wait_for_calculator_wheel_alignment(page, "reopening the persisted reset date", "1953-10-05")
    page.keyboard.press("Escape")
    page.evaluate("localStorage.setItem('clean_period_start_date_v4', '2999-01-01')")
    page.reload(wait_until="domcontentloaded")
    wait_for_page_ready(page)
    if page.locator("#cp-resultLine").inner_text() != "Дата не может быть в будущем" or page.locator("#cp-totalDays").inner_text() != "0":
        raise AssertionError("Calculator future dates must not produce a negative clean period")


def assert_calendar_url(frame, expected_mode: str, context: str) -> None:
    source = frame.get_attribute("src") or ""
    parsed = urlparse(source)
    values = parse_qs(parsed.query)
    expected = {
        "src": ["meserproject@gmail.com"], "ctz": ["Asia/Jerusalem"], "hl": ["ru"],
        "mode": [expected_mode], "wkst": ["2"], "showTitle": ["0"], "showNav": ["1"],
        "showDate": ["1"], "showPrint": ["0"], "showTabs": ["1"], "showCalendars": ["0"],
    }
    if parsed.netloc != "calendar.google.com" or parsed.path != "/calendar/embed" or any(values.get(key) != value for key, value in expected.items()):
        raise AssertionError(f"Calendar URL contract failed at {context}: expected mode={expected_mode}, observed={source}")


def assert_calendar_action_url(action, context: str) -> None:
    source = action.get_attribute("href") or ""
    parsed = urlparse(source)
    values = parse_qs(parsed.query)
    if (parsed.scheme != "https" or parsed.netloc != "calendar.google.com" or
            parsed.path != "/calendar/r/week" or values != {"cid": ["meserproject@gmail.com"]}):
        raise AssertionError(f"Calendar direct action URL contract failed at {context}: observed={source}")


def check_calendar(page, base_url: str, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    goto_ready(page, url(base_url, "/Calendar.html"))
    if page.locator("html").get_attribute("lang") != "ru" or page.locator("body.site-page").count() != 1:
        raise AssertionError(f"Calendar semantic shell is missing at {width}px")
    if page.locator("h1").count() != 1 or page.locator("h1").inner_text() != "Календарь событий":
        raise AssertionError(f"Calendar H1 is invalid at {width}px")
    if page.locator("main#main-content").count() != 1 or page.locator('a[href="#main-content"]').count() != 1:
        raise AssertionError(f"Calendar main landmark or skip link is missing at {width}px")
    if page.locator(".site-header__logo").count() != 1 or page.locator(".site-header__identity").count() != 1 or page.locator('a.service-link[href="Admin-panel.html"]').count() != 1:
        raise AssertionError(f"Calendar shared navigation is missing at {width}px")
    frame = page.locator("#gc-frame")
    frame.wait_for(state="visible")
    frame_box = frame.bounding_box()
    if not frame_box or frame_box["width"] <= 0 or frame_box["height"] <= 0 or frame.get_attribute("title") != "Календарь событий":
        raise AssertionError(f"Calendar iframe geometry or title is invalid at {width}px: {frame_box}")
    if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
        raise AssertionError(f"Calendar has horizontal overflow at {width}px")
    edit = page.locator("a.gc-btn")
    if (edit.count() != 1 or not edit.is_visible() or edit.inner_text() != "Открыть календарь в Google Calendar" or
            edit.get_attribute("target") != "_blank"):
        raise AssertionError(f"Calendar edit action is missing at {width}px")
    if not {"noopener", "noreferrer"}.issubset(set((edit.get_attribute("rel") or "").split())):
        raise AssertionError(f"Calendar edit action lacks safe semantics at {width}px")
    edit.focus()
    if not edit.evaluate("element => document.activeElement === element"):
        raise AssertionError(f"Calendar edit action is not keyboard focusable at {width}px")
    assert_calendar_action_url(edit, f"{width}px")
    if page.locator(".gc-note").inner_text() != "Календарь доступен для просмотра здесь. Пользователи с соответствующими правами могут редактировать его в Google Calendar.":
        raise AssertionError(f"Calendar direct action note is invalid at {width}px")
    if page.locator("footer.site-footer").count() != 1:
        raise AssertionError(f"Calendar footer is missing at {width}px")
    assert_calendar_url(frame, "AGENDA" if width <= 640 else "WEEK", f"{width}px")


def check_calendar_mode_transition(page, base_url: str) -> None:
    page.set_viewport_size({"width": 1280, "height": 900})
    goto_ready(page, url(base_url, "/Calendar.html"))
    frame = page.locator("#gc-frame")
    assert_calendar_url(frame, "WEEK", "transition initial 1280px")
    for width, expected_mode in ((390, "AGENDA"), (768, "WEEK"), (640, "AGENDA"), (641, "WEEK")):
        page.set_viewport_size({"width": width, "height": 900})
        page.wait_for_function(
            """expectedMode => new URL(document.getElementById('gc-frame').src).searchParams.get('mode') === expectedMode""",
            arg=expected_mode,
        )
        assert_calendar_url(frame, expected_mode, f"transition {width}px")


DRIVE_FOLDERS = (
    ("Аварийная коммуникация", "1DxqR91OJeER4nsPxPqncvBNH0379wOxX"),
    ("Архив спикерских", "1MuiNuW6oBzgDls1y_MeGXgOu0qrZhjdr"),
    ("Карточки", "1aZTL1CoTwpVrdKlE8O7KOtQjlmj_0s9g"),
    ("Концепции служения", "1qI_HNm2Ifay0jiLZmcsI1Qy1f6Z1Y0iU"),
    ("Отчёты", "1-X980mz_eSJ0IVh8sr3uWmdbG_SM3Xvt"),
    ("Преамбулы", "1U86CV0y4ziA9ex-WjHcfbdbxVD3aQi0q"),
    ("Устав", "1dZ1Z3I_I79-mWCsaxTi5Jg11SAiEzPjq"),
)


def assert_drive_folder_url(link, folder_id: str, context: str) -> None:
    source = link.get_attribute("href") or ""
    parsed = urlparse(source)
    if (parsed.scheme != "https" or parsed.netloc != "drive.google.com" or
            parsed.path != f"/drive/folders/{folder_id}" or parsed.query or parsed.fragment):
        raise AssertionError(f"Drive folder URL contract failed at {context}: observed={source}")


def check_google_drive(page, base_url: str, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    goto_ready(page, url(base_url, "/Google-Drive.html"))
    if page.locator("html").get_attribute("lang") != "ru" or page.locator("body.site-page").count() != 1:
        raise AssertionError(f"Drive semantic shell is missing at {width}px")
    if page.locator("h1").count() != 1 or page.locator("h1").inner_text() != "Материалы":
        raise AssertionError(f"Drive H1 is invalid at {width}px")
    if page.locator("main#main-content").count() != 1 or page.locator('a[href="#main-content"]').count() != 1:
        raise AssertionError(f"Drive main landmark or skip link is missing at {width}px")
    if page.locator(".site-header__logo").count() != 1 or page.locator(".site-header__identity").count() != 1 or page.locator('a.service-link[href="Admin-panel.html"]').count() != 1:
        raise AssertionError(f"Drive shared navigation is missing at {width}px")
    if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
        raise AssertionError(f"Drive has horizontal overflow at {width}px")
    cards = page.locator("a.drive-folder")
    labels = page.locator(".drive-folder__label")
    if cards.count() != len(DRIVE_FOLDERS) or labels.count() != len(DRIVE_FOLDERS):
        raise AssertionError(f"Drive must show seven folder cards at {width}px")
    if [labels.nth(index).inner_text() for index in range(labels.count())] != [label for label, _folder_id in DRIVE_FOLDERS]:
        raise AssertionError(f"Drive folder labels or order changed at {width}px")
    card_boxes = []
    for index, (_label, folder_id) in enumerate(DRIVE_FOLDERS):
        card = cards.nth(index)
        label = labels.nth(index)
        if not card.is_visible() or not label.is_visible():
            raise AssertionError(f"Drive folder card {index + 1} is not visible at {width}px")
        box = card.bounding_box()
        label_box = label.bounding_box()
        if not box or not label_box or box["width"] < 120 or box["height"] < 44:
            raise AssertionError(f"Drive folder card {index + 1} has unusable geometry at {width}px: card={box}, label={label_box}")
        clipped = label.evaluate("""element => {
            const style = getComputedStyle(element);
            return style.textOverflow === 'ellipsis' || style.overflow !== 'visible' ||
                element.scrollWidth > element.clientWidth || element.scrollHeight > element.clientHeight;
        }""")
        if clipped:
            raise AssertionError(f"Drive folder label is clipped at {width}px: {label.inner_text()}")
        if card.get_attribute("target") != "_blank" or not {"noopener", "noreferrer"}.issubset(set((card.get_attribute("rel") or "").split())):
            raise AssertionError(f"Drive folder card {index + 1} lacks safe new-tab semantics at {width}px")
        card.focus()
        if not card.evaluate("element => document.activeElement === element"):
            raise AssertionError(f"Drive folder card {index + 1} is not keyboard focusable at {width}px")
        assert_drive_folder_url(card, folder_id, f"folder {index + 1} at {width}px")
        card_boxes.append(box)
    if width >= 768 and len({round(box["x"]) for box in card_boxes[:3]}) < 2:
        raise AssertionError(f"Drive desktop catalog must display multiple cards per row at {width}px: {card_boxes[:3]}")
    parent = page.locator("#drive-open-all")
    if parent.count() != 1 or not parent.is_visible() or parent.get_attribute("target") != "_blank":
        raise AssertionError(f"Drive parent-folder action is missing at {width}px")
    if not {"noopener", "noreferrer"}.issubset(set((parent.get_attribute("rel") or "").split())):
        raise AssertionError(f"Drive parent-folder action lacks safe semantics at {width}px")
    parent.focus()
    if not parent.evaluate("element => document.activeElement === element"):
        raise AssertionError(f"Drive parent-folder action is not keyboard focusable at {width}px")
    assert_drive_folder_url(parent, "1XjxskHzqZeVhhCx4HTe00mWWRuH2Sdnc", f"parent action at {width}px")
    if page.locator("footer.site-footer").count() != 1:
        raise AssertionError(f"Drive footer is missing at {width}px")


SERVICE_LANDING_PATH = "/Admin-panel_5ab2b48b89f2fe30ce3272f2816f7d3f19b45752737d55f70f8c3a7f117dc527.html"
AUDIO_EDITOR_PATH = "/Audio-Editor.html"
SERVICE_SESSION_KEY = "meser_service_access_v1"


def check_admin_hash_functions(page, base_url: str) -> None:
    goto_ready(page, url(base_url, "/Admin-panel.html"))
    inputs = ("", "abc", "\x00\xffA\u0101")
    observed = page.evaluate("""async values => {
        const hash = window.AdminAccessHash;
        if (!hash) return { missing: true };
        return {
            webCryptoAvailable: Boolean(window.crypto?.subtle?.digest),
            values: await Promise.all(values.map(async value => ({
                value,
                bytes: Array.from(hash.legacyBytes(value)),
                fallback: hash.sha256Fallback(hash.legacyBytes(value)),
                primary: await hash.legacySha256(value),
            }))),
        };
    }""", list(inputs))
    if observed.get("missing") or not observed.get("webCryptoAvailable"):
        raise AssertionError("Admin hashing helpers or Web Crypto are unavailable in the standard Chromium context")
    expected = {
        "": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "abc": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    }
    for item in observed["values"]:
        if item["value"] in expected and item["fallback"] != expected[item["value"]]:
            raise AssertionError(f"Admin SHA-256 fallback vector failed for {item['value']!r}: {item['fallback']}")
        if item["fallback"] != item["primary"]:
            raise AssertionError(
                f"Admin SHA-256 fallback and Web Crypto differ for legacy bytes {item['bytes']}: "
                f"fallback={item['fallback']}, Web Crypto={item['primary']}"
            )
    if observed["values"][2]["bytes"] != [0, 255, 65, 1]:
        raise AssertionError(f"Admin legacy byte conversion changed: {observed['values'][2]['bytes']}")


def check_admin_without_subtle_crypto(browser, base_url: str) -> None:
    context = browser.new_context(viewport={"width": 390, "height": 900})
    context.add_init_script("""(() => {
        Object.defineProperty(window, "crypto", { configurable: true, value: {} });
    })()""")
    page = context.new_page()
    try:
        goto_ready(page, url(base_url, "/Admin-panel.html"))
        if page.evaluate("Boolean(window.crypto?.subtle?.digest)"):
            raise AssertionError("Unable to mask Web Crypto before admin-access.js executes")
        fallback_digest = page.evaluate(
            "window.AdminAccessHash.sha256Fallback(window.AdminAccessHash.legacyBytes('abc'))"
        )
        if fallback_digest != "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad":
            raise AssertionError(f"Admin fallback hashing did not execute without Web Crypto: {fallback_digest}")
        page.locator("#admin-password").fill("definitely-not-the-admin-password")
        page.get_by_role("button", name="Войти", exact=True).click()
        page.wait_for_function("document.getElementById('admin-error').textContent === 'Неверный пароль.'")
        if page.locator("#admin-error").inner_text() != "Неверный пароль.":
            raise AssertionError("Admin fallback path did not complete normal invalid-password verification")
    finally:
        context.close()


def check_admin_login(page, base_url: str, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    goto_ready(page, url(base_url, "/Admin-panel.html"))
    page.evaluate("sessionStorage.clear()")
    if page.locator("html").get_attribute("lang") != "ru" or page.locator("body.site-page").count() != 1:
        raise AssertionError(f"Admin login semantic shell is missing at {width}px")
    if page.locator("h1").count() != 1 or page.locator("h1").inner_text() != "Для служащих":
        raise AssertionError(f"Admin login H1 is invalid at {width}px")
    if page.locator("main#main-content").count() != 1 or page.locator('a[href="#main-content"]').count() != 1:
        raise AssertionError(f"Admin login main landmark or skip link is missing at {width}px")
    if page.locator(".site-header__logo").count() != 1 or page.locator(".site-header__identity").count() != 1 or page.locator("footer.site-footer").count() != 1:
        raise AssertionError(f"Admin login shared shell controls are missing at {width}px")
    if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
        raise AssertionError(f"Admin login has horizontal overflow at {width}px")
    form = page.locator("form#admin-access-form")
    password = page.locator("#admin-password")
    label = page.locator('label[for="admin-password"]')
    password_toggle = page.get_by_role("button", name="Показать пароль", exact=True)
    submit = page.get_by_role("button", name="Войти", exact=True)
    if (form.count() != 1 or not form.is_visible() or not password.is_visible() or not label.is_visible() or
            not password_toggle.is_visible() or not submit.is_visible()):
        raise AssertionError(f"Admin login form is incomplete at {width}px")
    if (password.get_attribute("type") != "password" or password.get_attribute("autocomplete") != "current-password" or
            password.get_attribute("required") is None or password_toggle.get_attribute("type") != "button" or
            password_toggle.get_attribute("aria-pressed") != "false" or submit.get_attribute("type") != "submit"):
        raise AssertionError(f"Admin login form semantics changed at {width}px")
    for control, name in ((password, "password input"), (password_toggle, "show-password button"), (submit, "submit button")):
        box = control.bounding_box()
        if not box or box["width"] <= 0 or box["height"] < 44:
            raise AssertionError(f"Admin {name} has unusable geometry at {width}px: {box}")
    password_toggle.focus()
    if not password_toggle.evaluate("element => document.activeElement === element"):
        raise AssertionError(f"Admin show-password button is not keyboard focusable at {width}px")
    harmless_password = "harmless-password-test"
    password.fill(harmless_password)
    password_toggle.click()
    hide_password = page.get_by_role("button", name="Скрыть пароль", exact=True)
    if (password.get_attribute("type") != "text" or password.input_value() != harmless_password or
            hide_password.get_attribute("aria-pressed") != "true"):
        raise AssertionError(f"Admin show-password behavior changed at {width}px")
    hide_password.click()
    show_password = page.get_by_role("button", name="Показать пароль", exact=True)
    if (password.get_attribute("type") != "password" or password.input_value() != harmless_password or
            show_password.get_attribute("aria-pressed") != "false"):
        raise AssertionError(f"Admin hide-password behavior changed at {width}px")
    if password.evaluate("element => parseFloat(getComputedStyle(element).paddingRight) < 48"):
        raise AssertionError(f"Admin password text can overlap the eye control at {width}px")
    password.fill("definitely-not-the-admin-password")
    submit.click()
    page.wait_for_function("document.getElementById('admin-error').textContent === 'Неверный пароль.'")
    expected_admin_url = urlparse(url(base_url, "/Admin-panel.html"))
    actual_admin_url = urlparse(page.url)
    if ((actual_admin_url.scheme, actual_admin_url.netloc, actual_admin_url.path,
         actual_admin_url.params, actual_admin_url.query, actual_admin_url.fragment) !=
            (expected_admin_url.scheme, expected_admin_url.netloc, expected_admin_url.path,
             expected_admin_url.params, expected_admin_url.query, expected_admin_url.fragment)):
        raise AssertionError(f"Invalid admin password navigated away at {width}px: {page.url}")
    if page.evaluate(f"sessionStorage.getItem('{SERVICE_SESSION_KEY}')") is not None:
        raise AssertionError(f"Invalid admin password set the service marker at {width}px")
    if page.locator("#admin-error").inner_text() != "Неверный пароль." or submit.is_disabled():
        raise AssertionError(f"Invalid admin password did not leave a usable form at {width}px")
    if not password.evaluate("element => document.activeElement === element"):
        raise AssertionError(f"Invalid admin password did not return focus at {width}px")


def seed_service_access(page, base_url: str) -> None:
    """Seed the non-secret client-side post-login state; this does not test authentication."""
    goto_ready(page, url(base_url, "/Admin-panel.html"))
    page.evaluate(f"sessionStorage.setItem('{SERVICE_SESSION_KEY}', 'granted')")


def check_service_landing(page, base_url: str, width: int) -> None:
    page.set_viewport_size({"width": width, "height": 900})
    seed_service_access(page, base_url)
    goto_ready(page, url(base_url, SERVICE_LANDING_PATH))
    if page.locator("html").get_attribute("lang") != "ru" or page.locator("body.site-page").count() != 1:
        raise AssertionError(f"Service landing semantic shell is missing at {width}px")
    if page.locator("h1").count() != 1 or page.locator("h1").inner_text() != "Служебная страница":
        raise AssertionError(f"Service landing H1 is invalid at {width}px")
    if page.locator("main#main-content").count() != 1 or page.locator('a[href="#main-content"]').count() != 1:
        raise AssertionError(f"Service landing main landmark or skip link is missing at {width}px")
    if page.locator(".site-header__logo").count() != 1 or page.locator(".site-header__identity").count() != 1 or page.locator("footer.site-footer").count() != 1:
        raise AssertionError(f"Service landing shared shell controls are missing at {width}px")
    if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
        raise AssertionError(f"Service landing has horizontal overflow at {width}px")
    actions = page.locator("a.service-action")
    expected = (
        ("Календарь", "Calendar.html"),
        ("Материалы", "Google-Drive.html"),
        ("Редактирование аудио", "Audio-Editor.html"),
        ("Аудиоархив", "Audio-Archive.html"),
    )
    if actions.count() != len(expected):
        raise AssertionError(f"Service landing must have four actions at {width}px")
    boxes = []
    for index, (label, href) in enumerate(expected):
        action = actions.nth(index)
        if not action.is_visible() or action.inner_text() != label or action.get_attribute("href") != href or action.get_attribute("target") is not None:
            raise AssertionError(f"Service landing action {index + 1} changed at {width}px")
        box = action.bounding_box()
        if not box or box["width"] <= 0 or box["height"] < 44:
            raise AssertionError(f"Service landing action {index + 1} has unusable geometry at {width}px: {box}")
        if action.evaluate("element => element.scrollWidth > element.clientWidth || element.scrollHeight > element.clientHeight"):
            raise AssertionError(f"Service landing action {index + 1} is clipped at {width}px")
        action.focus()
        if not action.evaluate("element => document.activeElement === element"):
            raise AssertionError(f"Service landing action {index + 1} is not keyboard focusable at {width}px")
        boxes.append(box)
    if width > 1024 and any(abs(box["y"] - boxes[0]["y"]) > 1 for box in boxes[1:]):
        raise AssertionError(f"Service landing desktop actions are not balanced in one row at {width}px: {boxes}")
    if 576 < width <= 1024 and not (abs(boxes[0]["y"] - boxes[1]["y"]) <= 1 and abs(boxes[2]["y"] - boxes[3]["y"]) <= 1 and boxes[2]["y"] > boxes[0]["y"]):
        raise AssertionError(f"Service actions must form two readable rows at {width}px: {boxes}")
    if width <= 576 and any(boxes[index]["y"] <= boxes[index - 1]["y"] for index in range(1, len(boxes))):
        raise AssertionError(f"Service landing mobile actions are not stacked at {width}px: {boxes}")
    logout = page.get_by_role("button", name="Выйти", exact=True)
    if not logout.is_visible():
        raise AssertionError(f"Service logout control is missing at {width}px")
    logout.focus()
    if not logout.evaluate("element => document.activeElement === element"):
        raise AssertionError(f"Service logout is not keyboard focusable at {width}px")


def check_service_access_journeys(page, base_url: str) -> None:
    goto_ready(page, url(base_url, "/Admin-panel.html"))
    page.evaluate("sessionStorage.clear()")
    page.goto(url(base_url, SERVICE_LANDING_PATH), wait_until="domcontentloaded")
    page.wait_for_url("**/Admin-panel.html")
    wait_for_page_ready(page)
    if page.locator("h1").inner_text() != "Для служащих":
        raise AssertionError("Unauthorized service landing did not redirect to the login page")

    seed_service_access(page, base_url)
    goto_ready(page, url(base_url, SERVICE_LANDING_PATH))
    page.get_by_role("button", name="Выйти", exact=True).click()
    page.wait_for_url("**/Admin-panel.html")
    wait_for_page_ready(page)
    if page.evaluate(f"sessionStorage.getItem('{SERVICE_SESSION_KEY}')") is not None:
        raise AssertionError("Service logout did not remove the session marker")
    page.goto(url(base_url, SERVICE_LANDING_PATH), wait_until="domcontentloaded")
    page.wait_for_url("**/Admin-panel.html")
    wait_for_page_ready(page)
    if page.locator("h1").inner_text() != "Для служащих":
        raise AssertionError("Logged-out direct landing access was not redirected")


ARCHIVE_MANIFEST_PATTERN = "**/data/edited-audio.json"
ARCHIVE_FIXTURE_ITEMS = (
    {
        "id": "older-audio",
        "name": "Беседа Альфа",
        "processedAt": "2026-09-01T12:00:00Z",
        "durationSeconds": 61,
        "audioUrl": "https://github.com/meser-recovery/starter-package/releases/download/edited-audio-v1/older-audio.mp3",
    },
    {
        "id": "newest-audio",
        "name": "Беседа Гамма",
        "processedAt": "2026-09-03T12:00:00Z",
        "durationSeconds": 3661,
        "audioUrl": "https://github.com/meser-recovery/starter-package/releases/download/edited-audio-v1/newest-audio.mp3",
    },
    {
        "id": "middle-audio",
        "name": "Беседа Бета",
        "processedAt": "2026-09-02T12:00:00Z",
        "durationSeconds": 120,
        "audioUrl": "https://github.com/meser-recovery/starter-package/releases/download/edited-audio-v1/middle-audio.mp3",
    },
)


def fixture_manifest_route(route) -> None:
    route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps({"schemaVersion": 1, "updatedAt": "2026-09-03T12:00:00Z", "items": ARCHIVE_FIXTURE_ITEMS}),
    )


def wait_for_archive_items(page, count: int) -> None:
    """Wait for the archive runtime to finish rendering the expected card count."""
    page.locator(".archive-item").nth(count - 1).wait_for(state="visible")


def wait_for_archive_text(page, text: str) -> None:
    page.get_by_text(text, exact=True).wait_for(state="visible")


def check_audio_editor_shell(page, width: int) -> None:
    if page.locator("html").get_attribute("lang") != "ru" or page.locator("body.site-page").count() != 1:
        raise AssertionError(f"Audio editor semantic shell is missing at {width}px")
    if page.locator("h1").count() != 1 or page.locator("h1").inner_text() != "Редактирование аудио":
        raise AssertionError(f"Audio editor H1 is invalid at {width}px")
    if page.locator("h2").all_text_contents()[:6] != ["Импорт исходных записей", "Редактирование", "Проект обработки спикерской", "Редактирование для анонс-мейкера", "Архив готовых записей", "Архив отредактированных аудио"]:
        raise AssertionError(f"Audio editor archive H2 is invalid at {width}px")
    if page.locator("main#main-content").count() != 1 or page.locator('a[href="#main-content"]').count() != 1:
        raise AssertionError(f"Audio editor main landmark or skip link is missing at {width}px")
    if page.locator(".site-header__logo").count() != 1 or page.locator(".site-header__identity").count() != 1:
        raise AssertionError(f"Audio editor shared header is missing at {width}px")
    if page.locator(f'a[href="{SERVICE_LANDING_PATH.lstrip("/")}"]').count() != 1:
        raise AssertionError(f"Audio editor exact back link is missing at {width}px")
    logout = page.get_by_role("button", name="Выйти", exact=True)
    if not logout.is_visible():
        raise AssertionError(f"Audio editor logout is missing at {width}px")
    logout.focus()
    if not logout.evaluate("element => document.activeElement === element"):
        raise AssertionError(f"Audio editor logout is not keyboard focusable at {width}px")
    if page.evaluate("document.documentElement.scrollWidth > window.innerWidth"):
        raise AssertionError(f"Audio editor has horizontal overflow at {width}px")
    page.locator('#processor-heading[data-ready="true"]').wait_for(state='attached')
    if not page.locator("#processor-run").is_disabled() or page.locator("#processor-result").is_visible():
        raise AssertionError("Processor initial Run/result state is invalid")
    if page.locator("#processor-cancel").is_visible() or page.locator("#processor-progress").is_visible():
        raise AssertionError("Processor initial busy state is invalid")
    if page.locator("#processor-status").get_attribute("role") != "status" or page.locator("#processor-progress").get_attribute("value") is not None:
        raise AssertionError("Processor must expose live status and indeterminate progress")
    for selector in ("#processor-source-audio", "#processor-result-audio"):
        audio = page.locator(selector)
        if audio.get_attribute("autoplay") is not None or not audio.evaluate("audio => audio.paused"):
            raise AssertionError("Processor audio must not autoplay")
    page.locator("#source-session-mode-archive").click()
    if page.locator("#source-session-mode-archive").get_attribute("aria-pressed") != "true" or not page.locator("#source-session-archive-panel").is_visible():
        raise AssertionError("Source Session Incoming archive must be the default entry mode")
    page.locator("#source-session-mode-device").click()
    file_input = page.locator("#processor-file")
    if file_input.get_attribute("multiple") is None:
        raise AssertionError("Processor must accept multiple synchronized tracks")
    file_input.focus()
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Tab")
    if not file_input.evaluate("element => document.activeElement === element"):
        raise AssertionError(f"Processor file input is not keyboard accessible at {width}px")
    for selector in (".source-session-card", ".result-archive-card", ".processor-card", '[aria-labelledby="archive-heading"]', "#processor-file", "#processor-run", "#archive-controls", "#archive-audio"):
        element = page.locator(selector)
        box = element.bounding_box()
        if not box or box["x"] < 0 or box["x"] + box["width"] > width + 1 or box["width"] < 44:
            raise AssertionError(f"Audio editor control/card clips at {width}px: {selector}, {box}")
        if element.evaluate("element => element.scrollWidth > element.clientWidth + 1"):
            raise AssertionError(f"Audio editor content overflows at {width}px: {selector}")
    if page.evaluate("performance.getEntriesByType('resource').some(entry => entry.name.includes('/vendor/ffmpeg/'))"):
        raise AssertionError("FFmpeg must not load just because the archive page opened")


def check_audio_editor(page, base_url: str) -> None:
    page.set_viewport_size({"width": 390, "height": 900})
    goto_ready(page, url(base_url, "/Admin-panel.html"))
    page.evaluate("sessionStorage.clear()")
    page.goto(url(base_url, AUDIO_EDITOR_PATH), wait_until="domcontentloaded")
    page.wait_for_url("**/Admin-panel.html")
    wait_for_page_ready(page)
    if page.locator("h1").inner_text() != "Для служащих":
        raise AssertionError("Unauthorized audio editor access did not redirect to the login page")

    page.route(ARCHIVE_MANIFEST_PATTERN, fixture_manifest_route)
    try:
        seed_service_access(page, base_url)
        goto_ready(page, url(base_url, SERVICE_LANDING_PATH))
        page.get_by_role("link", name="Редактирование аудио", exact=True).click()
        page.wait_for_url("**/Audio-Editor.html")
        wait_for_page_ready(page)
        wait_for_archive_items(page, 3)
        for width in (320, 390, 768, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            check_audio_editor_shell(page, width)

        cards = page.locator(".archive-item")
        if cards.count() != 3:
            raise AssertionError("Fixture archive entries did not render")
        if [cards.nth(index).locator("h3").inner_text() for index in range(cards.count())] != [
            "Беседа Гамма", "Беседа Бета", "Беседа Альфа"
        ]:
            raise AssertionError("Fixture archive is not newest-first by default")
        if page.locator("#archive-count").inner_text() != "Найдено: 3.":
            raise AssertionError("Fixture archive count is incorrect")
        player = page.locator("#archive-audio")
        if player.get_attribute("src") is not None or not player.evaluate("audio => audio.paused"):
            raise AssertionError("Archive player did not remain neutral before selection")

        page.locator("#archive-sort").select_option("oldest")
        if [cards.nth(index).locator("h3").inner_text() for index in range(cards.count())] != [
            "Беседа Альфа", "Беседа Бета", "Беседа Гамма"
        ]:
            raise AssertionError("Archive oldest-first sorting failed")
        page.locator("#archive-sort").select_option("name")
        if [cards.nth(index).locator("h3").inner_text() for index in range(cards.count())] != [
            "Беседа Альфа", "Беседа Бета", "Беседа Гамма"
        ]:
            raise AssertionError("Archive name sorting failed")
        page.locator("#archive-search").fill("ГАмМА")
        if cards.count() != 1 or cards.nth(0).locator("h3").inner_text() != "Беседа Гамма":
            raise AssertionError("Archive case-insensitive search failed")
        if page.locator("#archive-count").inner_text() != "Найдено: 1.":
            raise AssertionError("Archive search count did not update")
        page.locator("#archive-search").fill("не существует")
        if cards.count() != 0 or not page.get_by_text("По вашему запросу ничего не найдено.", exact=True).is_visible():
            raise AssertionError("Archive no-results state failed")
        page.locator("#archive-search").fill("")
        if cards.count() != 3 or page.locator("#archive-count").inner_text() != "Найдено: 3.":
            raise AssertionError("Clearing archive search did not restore entries")

        page.locator("#archive-sort").select_option("newest")
        first_listen = cards.nth(0).get_by_role("button", name="Слушать", exact=True)
        first_listen.focus()
        if not first_listen.evaluate("element => document.activeElement === element"):
            raise AssertionError("Archive listen button is not keyboard focusable")
        first_listen.click()
        expected_url = ARCHIVE_FIXTURE_ITEMS[1]["audioUrl"]
        if player.get_attribute("src") != expected_url or page.locator("#archive-selected-name").inner_text() != "Беседа Гамма":
            raise AssertionError("Selecting an archive item did not configure the shared player")
        if not player.evaluate("audio => audio.paused") or urlparse(page.url).query != "id=newest-audio":
            raise AssertionError("Archive selection autoplayed or did not replace the deep-link URL")
        download = cards.nth(0).get_by_role("link", name="Скачать", exact=True)
        if download.get_attribute("href") != expected_url:
            raise AssertionError("Archive download URL is not the canonical item URL")

        goto_ready(page, url(base_url, f"{AUDIO_EDITOR_PATH}?id=middle-audio"))
        page.wait_for_function("expected => document.getElementById('archive-selected-name')?.textContent === expected && document.getElementById('archive-audio')?.src.endsWith('/middle-audio.mp3')", arg="Беседа Бета")
        if page.locator("#archive-selected-name").inner_text() != "Беседа Бета" or not page.locator("#archive-audio").evaluate("audio => audio.paused"):
            raise AssertionError("Valid audio editor deep link did not select safely")
        goto_ready(page, url(base_url, f"{AUDIO_EDITOR_PATH}?id=unknown-audio"))
        wait_for_archive_items(page, 3)
        if page.locator(".archive-item").count() != 3 or page.locator("#archive-audio").get_attribute("src") is not None:
            raise AssertionError("Unknown audio editor deep link did not remain usable")
    finally:
        page.unroute(ARCHIVE_MANIFEST_PATTERN)

    seed_service_access(page, base_url)
    goto_ready(page, url(base_url, AUDIO_EDITOR_PATH))
    wait_for_archive_text(page, "Архив пока пуст.")
    if not page.get_by_text("Архив пока пуст.", exact=True).is_visible() or page.locator(".archive-item").count() != 0:
        raise AssertionError("Production empty archive state failed")
    if page.locator("#archive-controls").is_visible():
        raise AssertionError("Production empty archive unexpectedly shows search and sorting controls")
    if page.locator("#archive-audio").get_attribute("src") is not None:
        raise AssertionError("Production empty archive player is not neutral")

    page.route(ARCHIVE_MANIFEST_PATTERN, lambda route: route.abort())
    try:
        goto_ready(page, url(base_url, AUDIO_EDITOR_PATH))
        wait_for_archive_text(page, "Не удалось загрузить архив.")
        if not page.get_by_text("Не удалось загрузить архив.", exact=True).is_visible():
            raise AssertionError("Archive manifest failure state failed")
    finally:
        page.unroute(ARCHIVE_MANIFEST_PATTERN)
    page.evaluate(f"sessionStorage.removeItem('{SERVICE_SESSION_KEY}')")


def refresh_editor_sources(page):
    if page.locator('#import-zone').get_attribute('open') is None: page.locator('#import-zone > summary').click()
    page.locator('#source-session-mode-archive').click()
    page.locator('#source-session-refresh').click()


def check_source_session_archive(browser, base_url: str, screenshot_dir: Path | None = None) -> None:
    """Exercise the S08A browser integration against a deterministic cross-origin gateway."""
    context = browser.new_context(viewport={"width": 390, "height": 900})
    page = context.new_page()
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    session_id = "11111111-1111-4111-8111-111111111111"
    track_ids = ["22222222-2222-4222-8222-222222222222", "55555555-5555-4555-8555-555555555555",
        "77777777-7777-4777-8777-777777777777"]
    blob_ids = ["33333333-3333-4333-8333-333333333333", "66666666-6666-4666-8666-666666666666",
        "88888888-8888-4888-8888-888888888888"]
    names = ["archive-first.wav", "archive-middle.wav", "archive-last.wav"]
    wavs = [wav_payload(name, ((3, True),), frequency=frequency, sample_rate=8000)["buffer"]
        for name, frequency in zip(names, (330, 440, 550))]
    served_wavs = list(wavs)
    digests = [hashlib.sha256(wav).hexdigest() for wav in wavs]
    asset_names = [f"blob-{blob_id}-part-0001.bin" for blob_id in blob_ids]
    asset_urls = [f"https://github.com/meser-recovery/audio-archive/releases/download/audio-session-{session_id}/{name}"
        for name in asset_names]
    workflow = lambda name: {"workflow": name, "status": "new", "currentDraft": None, "outputs": [], "deletedVersions": [], "nextVersion": 1}
    session = {
        "schemaVersion": 1, "revision": 1, "id": session_id, "title": "Архивная запись", "recordedAt": None,
        "createdAt": "2026-01-01T00:00:00.000Z", "updatedAt": "2026-01-01T00:00:00.000Z",
        "origin": {"kind": "manual", "externalId": None}, "storage": {"releaseId": 1, "tag": f"audio-session-{session_id}"},
        "lifecycle": {"state": "incoming"}, "sourceState": "available",
        "sourceTracks": [{"trackId": track_id, "blobId": blob_id, "ordinal": index + 1, "originalName": names[index],
            "mediaType": "audio/wav", "sizeBytes": len(wavs[index]), "sha256": digests[index],
            "parts": [{"partNumber": 1, "sizeBytes": len(wavs[index]), "sha256": digests[index], "assetName": asset_names[index],
                "assetId": 10 + index, "downloadUrl": asset_urls[index]}]}
            for index, (track_id, blob_id) in enumerate(zip(track_ids, blob_ids))],
        "deletedSources": None, "workflows": {"announcement": workflow("announcement"), "speaker": workflow("speaker")},
        "relations": {"supersedesSessionId": None, "supersededBySessionId": None},
        "transaction": {"state": "finalized", "id": session_id},
    }
    speaker_output = {
        "outputId": "99999999-9999-4999-8999-999999999999", "version": 1, "sessionId": session_id,
        "createdAt": "2026-01-01T02:00:00.000Z", "blobId": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "sizeBytes": len(wavs[0]), "sha256": digests[0], "parts": [{"partNumber": 1,
            "sizeBytes": len(wavs[0]), "sha256": digests[0],
            "assetName": "blob-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa-part-0001.bin", "assetId": 40,
            "downloadUrl": f"https://github.com/meser-recovery/audio-archive/releases/download/audio-session-{session_id}/blob-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa-part-0001.bin"}],
        "recipeSnapshotRef": f"recipes/{session_id}/speaker/99999999-9999-4999-8999-999999999999.json",
        "processorVersion": "speaker-v1",
    }
    session["workflows"]["speaker"].update({"status": "result_ready", "outputs": [speaker_output], "nextVersion": 2})
    gateway_calls = []
    mock = {"draft": None, "speaker_draft": None, "publication": None, "output": None, "output_recipe": None,
            "output_bytes": None, "held_upload": None, "speaker_save": None, "speaker_output": None,
            "speaker_output_recipe": None, "speaker_output_bytes": None, "speaker_held_upload": None,
            "speaker_jobs": {}, "resume_held_upload": None, "hold_resume": False,
            "speaker_output_corrupt": False, "hold_incomplete": False, "held_incomplete": None,
            "incomplete": [], "list_failure": None}
    publication_id = "44444444-4444-4444-8444-444444444444"
    speaker_save_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    site_origin = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"
    unexpected_outbound = []

    def fulfill_json(route, value, status=200):
        route.fulfill(status=status, content_type="application/json", headers={
            "Access-Control-Allow-Origin": site_origin, "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Headers": "Content-Type, X-CSRF-Token, X-Part-SHA256, Idempotency-Key",
            "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, OPTIONS",
        }, body=json.dumps(value))

    def route_request(route):
        request = route.request
        parsed = urlparse(request.url)
        if parsed.netloc == urlparse(base_url).netloc and parsed.path.endswith(AUDIO_EDITOR_PATH):
            response = route.fetch()
            body, replacements = re.subn(r'(<meta name="audio-archive-gateway" content=")[^"]*(">)',
                r'\1https://gateway.test\2', response.body().decode("utf-8"), count=1)
            if replacements != 1:
                raise AssertionError("Audio archive gateway hook could not be isolated for the mock")
            route.fulfill(response=response, body=body)
            return
        if parsed.hostname == "meserproject.duckdns.org" or (parsed.hostname == "github.com" and parsed.path.startswith("/meser-recovery/audio-archive/")):
            route.abort()
            return
        if parsed.netloc != "gateway.test":
            if parsed.netloc == urlparse(base_url).netloc: route.continue_()
            else: unexpected_outbound.append(request.url); route.abort()
            return
        content_type = request.header_value("content-type") or ""
        gateway_calls.append((request.method, parsed.path, request.post_data if "application/json" in content_type else None))
        if request.method == "OPTIONS":
            route.fulfill(status=204, headers={"Access-Control-Allow-Origin": site_origin,
                "Access-Control-Allow-Credentials": "true", "Access-Control-Allow-Headers": "Content-Type, X-CSRF-Token, X-Part-SHA256, Idempotency-Key",
                "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, OPTIONS"})
        elif parsed.path == "/v1/config":
            fulfill_json(route, {"schemaVersion": 1, "acceptedPartSize": 16777216, "maximumPartSize": 67108864, "maximumSessionSize": 524288000})
        elif parsed.path == "/v1/session":
            fulfill_json(route, {"authenticated": True, "expiresAt": 2000000000, "csrfToken": "mock-csrf"})
        elif parsed.path == "/v1/maintenance/incomplete" and request.method == "GET":
            if mock["hold_incomplete"]:
                mock["held_incomplete"] = route
            else:
                fulfill_json(route, {"transactions": mock["incomplete"], "orphans": []})
        elif parsed.path == "/v1/source-sessions" and request.method == "GET":
            if mock["list_failure"] == "server":
                fulfill_json(route, {"error": "English backend failure with provider details"}, 500)
            elif mock["list_failure"] == "network":
                route.abort("connectionfailed")
            else:
                lifecycle = parse_qs(parsed.query).get("lifecycle", ["incoming"])[0]
                fulfill_json(route, {"revision": session["revision"], "sessions": [session] if session["lifecycle"]["state"] == lifecycle else []})
        elif parsed.path == f"/v1/source-sessions/{session_id}" and request.method == "GET":
            fulfill_json(route, session)
        elif parsed.path == f"/v1/source-sessions/{session_id}/drafts/announcement" and request.method == "GET":
            fulfill_json(route, {"draft": mock["draft"]})
        elif parsed.path == f"/v1/source-sessions/{session_id}/drafts/announcement" and request.method == "PUT":
            body = json.loads(request.post_data)
            session["revision"] += 1
            mock["draft"] = {"schemaVersion": 1, "sessionId": session_id, "workflow": "announcement", "draftRevision": 1,
                "sourceSessionRevision": session["revision"], "savedAt": "2026-01-02T03:04:05.000Z",
                "payloadSchema": "announcement/v1", "payload": body["payload"]}
            session["workflows"]["announcement"]["currentDraft"] = {"path": f"drafts/{session_id}/announcement.json", "revision": 1}
            session["workflows"]["announcement"]["status"] = "in_progress"
            fulfill_json(route, {"draft": mock["draft"], "session": session})
        elif parsed.path == f"/v1/source-sessions/{session_id}/drafts/speaker" and request.method == "GET":
            fulfill_json(route, {"draft": mock["speaker_draft"]})
        elif parsed.path == f"/v1/source-sessions/{session_id}/drafts/speaker" and request.method == "PUT":
            body = json.loads(request.post_data)
            session["revision"] += 1
            draft_revision = (mock["speaker_draft"] or {}).get("draftRevision", 0) + 1
            mock["speaker_draft"] = {"schemaVersion": 1, "sessionId": session_id, "workflow": "speaker",
                "draftRevision": draft_revision, "sourceSessionRevision": session["revision"],
                "savedAt": "2026-01-02T03:04:05.000Z", "payloadSchema": "speaker/v1", "payload": body["payload"]}
            session["workflows"]["speaker"]["currentDraft"] = {"path": f"drafts/{session_id}/speaker.json", "revision": draft_revision}
            fulfill_json(route, {"draft": mock["speaker_draft"], "session": session})
        elif parsed.path == f"/v1/source-sessions/{session_id}/deletion-preview" and request.method == "GET":
            fulfill_json(route, {"sessionId": session_id, "revision": session["revision"], "sourceTracks": 3, "announcementVersions": len(session["workflows"]["announcement"]["outputs"]),
                "speakerVersions": 1, "drafts": 1 if mock["draft"] else 0, "pendingAnnouncementPublications": 0, "pendingSpeakerSaves": 0})
        elif parsed.path in {f"/v1/source-sessions/{session_id}/blobs/{blob_id}/parts/1/content" for blob_id in blob_ids} and request.method == "GET":
            source_index = blob_ids.index(parsed.path.split("/blobs/")[1].split("/")[0])
            route.fulfill(status=200, content_type="application/octet-stream", headers={
                "Access-Control-Allow-Origin": site_origin, "Access-Control-Allow-Credentials": "true",
                "Cache-Control": "no-store",
            }, body=served_wavs[source_index])
        elif parsed.path == f"/v1/source-sessions/{session_id}/outputs/announcement/publications" and request.method == "POST":
            mock["publication"] = json.loads(request.post_data)
            session["revision"] += 1
            reserved = session["workflows"]["announcement"]["nextVersion"]
            session["workflows"]["announcement"]["nextVersion"] += 1
            fulfill_json(route, {"transactionId": publication_id, "sessionId": session_id, "workflow": "announcement",
                "outputId": mock["publication"]["plan"]["outputId"], "blobId": mock["publication"]["plan"]["blobId"],
                "state": "uploading", "reservedVersion": reserved, "reservedSessionRevision": session["revision"],
                "uploadedParts": 0, "totalParts": len(mock["publication"]["plan"]["parts"]), "canFinalize": False,
                "requiresLocalResult": True, "updatedAt": "2026-01-02T03:04:05.000Z"}, 201)
        elif parsed.path.startswith(f"/v1/announcement-publications/{publication_id}/blobs/") and request.method == "PUT":
            mock["output_bytes"] = bytes(request.post_data_buffer or b"")
            mock["held_upload"] = route
        elif parsed.path == f"/v1/announcement-publications/{publication_id}/finalize" and request.method == "POST":
            plan = mock["publication"]["plan"]
            output_asset_url = f"https://github.com/meser-recovery/audio-archive/releases/download/audio-session-{session_id}/{plan['parts'][0]['assetName']}"
            output = {"outputId": plan["outputId"], "version": 1, "sessionId": session_id,
                "createdAt": "2026-01-02T03:04:05.000Z", "blobId": plan["blobId"], "sizeBytes": plan["sizeBytes"],
                "sha256": plan["sha256"], "parts": [{**part, "assetId": 99 + index, "downloadUrl": output_asset_url}
                    for index, part in enumerate(plan["parts"])],
                "recipeSnapshotRef": f"recipes/{session_id}/announcement/{plan['outputId']}.json", "processorVersion": plan["processorVersion"]}
            session["workflows"]["announcement"]["outputs"] = [output]
            session["workflows"]["announcement"]["status"] = "result_ready"
            session["revision"] += 1
            mock["output"] = output
            mock["output_recipe"] = {"schemaVersion": 1, "workflow": "announcement", "sessionId": session_id,
                "outputId": output["outputId"], "version": output["version"], "processorVersion": output["processorVersion"],
                "createdAt": output["createdAt"], **plan["recipe"]}
            fulfill_json(route, {"job": {"transactionId": publication_id, "state": "finalized"}, "output": output, "idempotent": False})
        elif mock["output"] and parsed.path == f"/v1/source-sessions/{session_id}/outputs/announcement/{mock['output']['outputId']}" and request.method == "GET":
            fulfill_json(route, {"output": mock["output"], "recipe": mock["output_recipe"]})
        elif mock["output"] and parsed.path.startswith(f"/v1/source-sessions/{session_id}/outputs/announcement/{mock['output']['outputId']}/blobs/") and request.method == "GET":
            route.fulfill(status=200, content_type="application/octet-stream", headers={
                "Access-Control-Allow-Origin": site_origin, "Access-Control-Allow-Credentials": "true",
                "Cache-Control": "no-store",
            }, body=mock["output_bytes"])
        elif parsed.path == f"/v1/source-sessions/{session_id}/outputs/speaker/saves" and request.method == "POST":
            mock["speaker_save"] = json.loads(request.post_data)
            session["revision"] += 1
            reserved = session["workflows"]["speaker"]["nextVersion"]
            session["workflows"]["speaker"]["nextVersion"] += 1
            plan = mock["speaker_save"]["plan"]
            job = {"transactionId": speaker_save_id, "sessionId": session_id, "workflow": "speaker",
                "outputId": plan["outputId"], "blobId": plan["blobId"], "state": "uploading",
                "reservedVersion": reserved, "reservedSessionRevision": session["revision"], "uploadedParts": 0,
                "uploadedPartNumbers": [], "totalParts": len(plan["parts"]), "canFinalize": False,
                "requiresLocalResult": True, "candidateFingerprint": plan["recipe"]["candidateFingerprint"],
                "sizeBytes": plan["sizeBytes"], "sha256": plan["sha256"], "parts": plan["parts"],
                "updatedAt": "2026-01-02T03:04:05.000Z"}
            mock["speaker_jobs"][speaker_save_id] = job
            fulfill_json(route, job, 201)
        elif parsed.path.startswith(f"/v1/speaker-saves/{speaker_save_id}/blobs/") and request.method == "PUT":
            mock["speaker_output_bytes"] = bytes(request.post_data_buffer or b"")
            mock["speaker_held_upload"] = route
        elif parsed.path == f"/v1/speaker-saves/{speaker_save_id}/finalize" and request.method == "POST":
            plan = mock["speaker_save"]["plan"]
            output = {"outputId": plan["outputId"], "version": 2, "sessionId": session_id,
                "createdAt": "2026-01-02T03:04:05.000Z", "blobId": plan["blobId"], "sizeBytes": plan["sizeBytes"],
                "sha256": plan["sha256"], "parts": [{**part, "assetId": 120 + index,
                    "downloadUrl": f"https://github.com/meser-recovery/audio-archive/releases/download/audio-session-{session_id}/{part['assetName']}"}
                    for index, part in enumerate(plan["parts"])],
                "recipeSnapshotRef": f"recipes/{session_id}/speaker/{plan['outputId']}.json",
                "processorVersion": plan["processorVersion"]}
            session["workflows"]["speaker"]["outputs"].append(output)
            session["workflows"]["speaker"]["status"] = "result_ready"
            session["revision"] += 1
            mock["speaker_output"] = output
            mock["speaker_output_recipe"] = {"schemaVersion": 1, "workflow": "speaker", "sessionId": session_id,
                "outputId": output["outputId"], "version": output["version"], "processorVersion": output["processorVersion"],
                "createdAt": output["createdAt"], **plan["recipe"]}
            mock["speaker_jobs"][speaker_save_id].update({"state": "finalized", "canFinalize": False,
                "requiresLocalResult": False, "uploadedParts": len(plan["parts"]),
                "uploadedPartNumbers": [part["partNumber"] for part in plan["parts"]]})
            fulfill_json(route, {"job": mock["speaker_jobs"][speaker_save_id],
                "output": output, "idempotent": False})
        elif mock["speaker_output"] and parsed.path == f"/v1/source-sessions/{session_id}/outputs/speaker/{mock['speaker_output']['outputId']}" and request.method == "GET":
            fulfill_json(route, {"output": mock["speaker_output"], "recipe": mock["speaker_output_recipe"]})
        elif mock["speaker_output"] and parsed.path.startswith(f"/v1/source-sessions/{session_id}/outputs/speaker/{mock['speaker_output']['outputId']}/blobs/") and request.method == "GET":
            route.fulfill(status=200, content_type="application/octet-stream", headers={
                "Access-Control-Allow-Origin": site_origin, "Access-Control-Allow-Credentials": "true",
                "Cache-Control": "no-store",
            }, body=b"corrupt" if mock["speaker_output_corrupt"] else mock["speaker_output_bytes"])
        elif (match := re.fullmatch(r"/v1/speaker-saves/([0-9a-f-]+)", parsed.path)) and request.method == "GET":
            job = mock["speaker_jobs"].get(match.group(1))
            fulfill_json(route, job if job else {"error": "missing"}, 200 if job else 404)
        elif (match := re.fullmatch(r"/v1/speaker-saves/([0-9a-f-]+)/cancel", parsed.path)) and request.method == "POST":
            job = mock["speaker_jobs"].get(match.group(1))
            if not job:
                fulfill_json(route, {"error": "missing"}, 404)
            elif job["state"] == "finalized":
                fulfill_json(route, {"error": "already finalized"}, 409)
            else:
                job.update({"state": "cancelled", "canFinalize": job["uploadedParts"] == job["totalParts"]})
                fulfill_json(route, {"job": job})
        elif (match := re.fullmatch(r"/v1/speaker-saves/([0-9a-f-]+)/blobs/([0-9a-f-]+)/parts/(\d+)", parsed.path)) and request.method == "PUT":
            job = mock["speaker_jobs"].get(match.group(1))
            if not job:
                fulfill_json(route, {"error": "missing"}, 404)
            elif mock["hold_resume"]:
                mock["resume_held_upload"] = route
            else:
                part_number = int(match.group(3))
                if part_number not in job["uploadedPartNumbers"]:
                    job["uploadedPartNumbers"].append(part_number)
                job["uploadedParts"] = len(job["uploadedPartNumbers"])
                job["canFinalize"] = job["uploadedParts"] == job["totalParts"]
                fulfill_json(route, {"uploaded": True, "assetId": 220 + part_number, "downloadUrl": "https://gateway.test/mock-part"})
        elif (match := re.fullmatch(r"/v1/speaker-saves/([0-9a-f-]+)/finalize", parsed.path)) and request.method == "POST":
            job = mock["speaker_jobs"].get(match.group(1))
            if not job:
                fulfill_json(route, {"error": "missing"}, 404)
            else:
                job.update({"state": "finalized", "canFinalize": False, "requiresLocalResult": False})
                mock["incomplete"] = [item for item in mock["incomplete"] if item["transactionId"] != job["transactionId"]]
                fulfill_json(route, {"job": job, "output": {"version": job["reservedVersion"]}, "idempotent": False})
        elif (match := re.fullmatch(r"/v1/maintenance/incomplete/([0-9a-f-]+)/(resume|discard)", parsed.path)) and request.method == "POST":
            job = mock["speaker_jobs"].get(match.group(1))
            if not job:
                fulfill_json(route, {"error": "missing"}, 404)
            elif match.group(2) == "resume":
                job.update({"state": "finalized", "canFinalize": False, "requiresLocalResult": False})
                mock["incomplete"] = [item for item in mock["incomplete"] if item["transactionId"] != job["transactionId"]]
                fulfill_json(route, {"job": job, "output": {"version": job["reservedVersion"]}, "idempotent": False})
            else:
                job.update({"state": "discarded", "canFinalize": False, "requiresLocalResult": False})
                mock["incomplete"] = [item for item in mock["incomplete"] if item["transactionId"] != job["transactionId"]]
                fulfill_json(route, {"job": job, "discarded": True})
        elif parsed.path.endswith("/workflows/announcement/status") and request.method == "PUT":
            session["workflows"]["announcement"]["status"] = "in_progress"
            session["revision"] += 1
            fulfill_json(route, session)
        elif parsed.path == "/v1/source-sessions/ingestions" and request.method == "POST":
            mock["ingestion_plan"] = json.loads(request.post_data)["plan"]
            fulfill_json(route, {"transactionId": session_id, "sessionId": session_id, "releaseId": 1, "state": "uploading"}, 201)
        elif "/blobs/" in parsed.path and "/parts/" in parsed.path and request.method == "PUT":
            fulfill_json(route, {"uploaded": True, "assetId": 99, "downloadUrl": asset_urls[0]})
        elif parsed.path.endswith("/finalize") and request.method == "POST":
            ingested = json.loads(json.dumps(session))
            ingested.update({"sourceState": "available", "deletedSources": None})
            ingested["lifecycle"]["state"] = "incoming"
            ingested["sourceTracks"] = mock["ingestion_plan"]["tracks"]
            for track in ingested["sourceTracks"]:
                for part in track["parts"]:
                    part.update({"assetId": 99, "downloadUrl": f'https://github.com/meser-recovery/audio-archive/releases/download/audio-session-{session_id}/{part["assetName"]}'})
            fulfill_json(route, {"session": ingested, "idempotent": False})
        else:
            fulfill_json(route, {"error": "unexpected mock route"}, 404)

    context.route("**/*", route_request)
    try:
        seed_service_access(page, base_url)
        goto_ready(page, url(base_url, AUDIO_EDITOR_PATH))
        try:
            page.locator(".source-session-item").wait_for()
        except Error as error:
            raise AssertionError({"error": str(error), "pageErrors": page_errors, "status": page.locator("#source-session-status").inner_text(),
                "meta": page.locator('meta[name="audio-archive-gateway"]').get_attribute("content"), "calls": gateway_calls})
        assert page.locator("#source-session-mode-archive").get_attribute("aria-pressed") == "true"
        assert page.locator(".source-session-item h3").inner_text() == "Архивная запись"
        assert page.locator("#source-session-results-announcement-count").inner_text() == "0"
        assert page.locator("#source-session-results-speaker-count").inner_text() == "1"
        assert page.locator("#source-session-announcement-workspace").is_hidden()
        page.locator("#source-session-results-speaker").click()
        assert page.locator("#source-session-results-speaker-panel").is_visible()
        assert page.get_by_text("Архивная запись · Версия 1", exact=True).count() == 1
        assert page.locator("#source-session-results-speaker-panel").get_by_role("button", name="Прослушать", exact=True).count() == 1
        assert page.locator("#source-session-results-speaker-panel").get_by_role("button", name="Скачать", exact=True).count() == 1
        delete_button = page.locator("#source-session-results-speaker-panel").get_by_role("button", name="Удалить версию", exact=True)
        delete_button.click()
        page.locator("#source-session-delete-dialog").wait_for(state="visible")
        assert "Финальные версии спикерских" in page.locator("#source-session-delete-summary").inner_text()
        assert session_id not in page.locator("#source-session-delete-summary").inner_text()
        assert session_id in page.locator("#source-session-delete-technical").text_content()
        assert "версия 1" in page.locator("#source-session-delete-summary").inner_text()
        assert page.locator("#source-session-delete-dialog input[type=radio]").count() == 0
        assert page.locator("#source-session-delete-dialog").evaluate("dialog => dialog.contains(document.activeElement)")
        page.keyboard.press("Escape")
        page.locator("#source-session-delete-dialog").wait_for(state="hidden")
        assert delete_button.evaluate("button => document.activeElement === button")
        page.locator("#source-session-results-announcement").click()
        assert page.locator("#source-session-results-announcement-panel").is_visible()
        if screenshot_dir:
            for width in (390, 1280):
                page.set_viewport_size({"width": width, "height": 900})
                page.evaluate("document.activeElement?.blur()")
                page.evaluate("scrollTo(0, 0)")
                page.screenshot(path=str(screenshot_dir / f"s08b-archive-overview-{width}.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 900})
        # A decoded duration mismatch fails closed after the common duration is known: no editable partial workspace,
        # save request or render operation is allowed; source files remain available for retry.
        mismatch_wav = wav_payload(names[2], ((3.75, True),), frequency=550, sample_rate=8000)["buffer"]
        served_wavs[2] = mismatch_wav
        session["sourceTracks"][2]["sizeBytes"] = len(mismatch_wav)
        session["sourceTracks"][2]["sha256"] = hashlib.sha256(mismatch_wav).hexdigest()
        session["sourceTracks"][2]["parts"][0]["sizeBytes"] = len(mismatch_wav)
        session["sourceTracks"][2]["parts"][0]["sha256"] = session["sourceTracks"][2]["sha256"]
        speaker_puts_before = len([call for call in gateway_calls if call[0] == "PUT" and call[1].endswith("/drafts/speaker")])
        if page.locator("#import-zone").get_attribute("open") is None: page.locator("#import-zone > summary").click()
        page.locator("#source-session-list").get_by_role("button", name="Открыть финальную обработку спикерской", exact=True).click()
        page.get_by_text("Длительность дорожек различается больше чем на 0,5 секунды. Выберите дорожки одной и той же записи Zoom.", exact=True).wait_for(timeout=30000)
        assert page.locator("#speaker-editor-save").is_disabled() and page.locator("#speaker-editor-render").is_disabled()
        assert page.locator("#speaker-editor-add-cut").is_disabled() and page.locator("#speaker-editor-tracks").locator("li").count() == 3
        assert page.locator("#speaker-editor-source-retry").is_visible()
        assert page.evaluate("async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().files.every(file => file instanceof File)")
        assert page.locator("#speaker-editor-cancel").is_hidden() and page.locator("#speaker-editor-result").is_hidden()
        assert page.evaluate("""async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerCandidate() === null""")
        assert len([call for call in gateway_calls if call[0] == "PUT" and call[1].endswith("/drafts/speaker")]) == speaker_puts_before
        assert page.evaluate("performance.getEntriesByType('resource').every(entry => !entry.name.includes('/vendor/ffmpeg/core/'))")
        served_wavs[2] = wavs[2]
        session["sourceTracks"][2]["sizeBytes"] = len(wavs[2])
        session["sourceTracks"][2]["sha256"] = digests[2]
        session["sourceTracks"][2]["parts"][0]["sizeBytes"] = len(wavs[2])
        session["sourceTracks"][2]["parts"][0]["sha256"] = digests[2]
        if page.locator("#import-zone").get_attribute("open") is None: page.locator("#import-zone > summary").click()
        page.locator("#source-session-list").get_by_role("button", name="Открыть финальную обработку спикерской", exact=True).click()
        page.locator("#speaker-unsaved-discard").click()  # Explicitly replace the retained, unprepared source set.
        page.wait_for_function("!document.getElementById('speaker-editor-render').disabled")
        page.locator("#speaker-editor .speaker-track").nth(2).wait_for(timeout=30000)
        assert page.locator("#speaker-editor").is_visible()
        assert page.locator("#source-session-announcement-workspace").is_hidden()
        assert page.locator("#speaker-editor-undo").is_disabled() and page.locator("#speaker-editor-redo").is_disabled()
        assert page.locator("#speaker-editor-render").is_enabled()
        assert "Архивная запись" in page.locator("#speaker-editor-identity").inner_text()
        assert page.locator("#announcement-processor-card").is_hidden()
        # Speaker monitoring has one master clock: active seeks realign every preview, rate/volume propagate,
        # and periodic correction bounds deliberate drift without touching mix membership.
        page.locator("#speaker-editor-source-audio").evaluate("""async audio => {
            audio.volume = .37; audio.playbackRate = 1.25; audio.currentTime = .4; await audio.play();
        }""")
        page.wait_for_function("""() => [...document.querySelectorAll('#speaker-editor-preview-audios audio')].length === 2 &&
            [...document.querySelectorAll('#speaker-editor-preview-audios audio')].every(audio => !audio.paused &&
                Math.abs(audio.currentTime - document.getElementById('speaker-editor-source-audio').currentTime) < .12 &&
                audio.playbackRate === 1.25 && Math.abs(audio.volume - .37) < .001)""", timeout=5000)
        page.locator("#speaker-editor-source-audio").evaluate("audio => { audio.currentTime = 1.4; audio.dispatchEvent(new Event('seeking')); }")
        page.wait_for_function("""() => [...document.querySelectorAll('#speaker-editor-preview-audios audio')].every(audio =>
            Math.abs(audio.currentTime - document.getElementById('speaker-editor-source-audio').currentTime) < .12)""", timeout=3000)
        page.locator("#speaker-editor-preview-audios audio").first.evaluate("audio => { audio.currentTime = 0; }")
        page.wait_for_function("""() => Math.abs(document.querySelector('#speaker-editor-preview-audios audio').currentTime -
            document.getElementById('speaker-editor-source-audio').currentTime) < .12""", timeout=3000)
        page.locator("#speaker-editor-source-audio").evaluate("audio => { audio.pause(); audio.currentTime = 0; audio.volume = 1; audio.playbackRate = 1; }")
        assert page.locator("#speaker-editor-preview-audios audio").evaluate_all("items => items.every(audio => audio.paused)")
        for width in (320, 390, 768, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            assert not page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
            box = page.locator("#speaker-editor").bounding_box()
            assert box and box["x"] >= 0 and box["x"] + box["width"] <= width + 1, (width, box)
        page.locator(".skip-link").evaluate("element => element.style.display = 'none'")
        if screenshot_dir:
            page.evaluate("document.activeElement?.blur()")
            page.set_viewport_size({"width": 1280, "height": 900})
            page.locator("#speaker-editor").screenshot(path=str(screenshot_dir / "s08c-speaker-opened-1280.png"))
            page.set_viewport_size({"width": 390, "height": 900})
            page.locator("#speaker-editor").screenshot(path=str(screenshot_dir / "s08c-speaker-opened-390.png"))
        page.get_by_text("Точное редактирование", exact=True).click()
        page.locator("#speaker-regions-heading").click()
        page.locator("#speaker-editor-selection-start").fill("0.5")
        page.locator("#speaker-editor-selection-end").fill("1")
        apply_selection(page, 'cut')
        assert page.locator(".speaker-region-overlay--cut").count() == 3
        assert page.locator("#speaker-editor-undo").is_enabled() and page.locator("#speaker-editor-redo").is_disabled()
        page.locator("#speaker-editor-selection-start").fill("1.5")
        page.locator("#speaker-editor-selection-end").fill("2")
        apply_selection(page, 'silence')
        assert page.locator(".speaker-region-overlay--silence").count() == 1
        assert page.locator(".speaker-region-row--cut").count() == 1 and page.locator(".speaker-region-row--silence").count() == 1
        if screenshot_dir:
            page.evaluate("document.activeElement?.blur()")
            page.locator("#speaker-editor").screenshot(path=str(screenshot_dir / "s08c-regions-distinct-390.png"))
        second = page.locator(".speaker-track").nth(1)
        second.get_by_role("button", name="Исключить из микса", exact=True).click()
        assert "Не в финальном миксе" in page.locator(".speaker-track").nth(1).inner_text()
        if not page.locator(".speaker-dsp input").first.is_visible():
            page.locator(".speaker-dsp-disclosure > summary").first.click()
        page.locator(".speaker-dsp input").nth(0).check()
        page.locator(".speaker-dsp input").nth(2).fill("2"); page.locator(".speaker-dsp input").nth(2).dispatch_event("change")
        if screenshot_dir:
            page.evaluate("document.activeElement?.blur()")
            page.set_viewport_size({"width": 768, "height": 900})
            page.locator("#speaker-editor").screenshot(path=str(screenshot_dir / "s08c-excluded-dsp-768.png"))
            page.set_viewport_size({"width": 390, "height": 900})
        page.locator(".speaker-track").first.get_by_role("button", name="Исключить из микса", exact=True).click()
        page.locator(".speaker-track").nth(2).get_by_role("button", name="Исключить из микса", exact=True).click()
        assert page.locator("#speaker-editor-render").is_disabled()
        assert "Все дорожки исключены" in page.locator("#speaker-editor-render-reason").inner_text()
        page.locator("#speaker-editor-undo").click()
        page.locator("#speaker-editor-undo").click()
        page.keyboard.press("Control+z")
        assert page.locator("#speaker-editor-redo").is_enabled()
        page.keyboard.press("Control+Shift+z")
        assert page.locator("#speaker-editor-redo").is_enabled()
        page.locator(".speaker-dsp input").nth(2).fill("3"); page.locator(".speaker-dsp input").nth(2).dispatch_event("change")
        assert page.locator("#speaker-editor-redo").is_disabled()
        page.locator(".speaker-dsp input").nth(2).fill("2"); page.locator(".speaker-dsp input").nth(2).dispatch_event("change")
        if screenshot_dir:
            page.evaluate("document.activeElement?.blur()")
            page.locator("#speaker-editor").screenshot(path=str(screenshot_dir / "s08c-undo-redo-390.png"))
        page.locator("#speaker-editor-save").click()
        page.wait_for_function("document.getElementById(\'speaker-editor-status\').textContent === \'Все изменения сохранены\'")
        assert mock["speaker_draft"]["draftRevision"] == 1
        assert mock["speaker_draft"]["payloadSchema"] == "speaker/v1"
        assert mock["speaker_draft"]["payload"]["excludedTrackIds"] == [track_ids[1]]
        assert mock["speaker_draft"]["payload"]["globalCuts"] == [{"regionId": mock["speaker_draft"]["payload"]["globalCuts"][0]["regionId"], "startSeconds": .5, "endSeconds": 1}]
        # Cancellation is local: no candidate and no Speaker output route may be called.
        page.locator("#speaker-editor-render").click()
        page.locator("#speaker-editor-cancel").wait_for(state="visible")
        if screenshot_dir:
            page.evaluate("document.activeElement?.blur()")
            page.locator("#speaker-editor").screenshot(path=str(screenshot_dir / "s08c-render-progress-cancel-390.png"))
        page.locator("#speaker-editor-cancel").click()
        assert page.locator("#speaker-editor-result").is_hidden()
        page.wait_for_function("!document.getElementById('speaker-editor-render').disabled")
        page.locator("#speaker-editor-render").click()
        page.locator("#speaker-editor-cancel").wait_for(state="visible")
        assert page.locator("#speaker-editor-add-cut").is_disabled()
        assert page.locator(".speaker-dsp input").first.is_disabled()
        assert page.locator('.speaker-track button').filter(has_text="Исключить из микса").first.is_disabled()
        # Even a synthetic event cannot alter the captured render snapshot while the operation is active.
        page.locator(".speaker-dsp input").first.evaluate("""select => {
            select.checked = false; select.dispatchEvent(new Event('change', {bubbles: true}));
        }""")
        page.get_by_text("Финальная версия готова. В архив ничего не передавалось.", exact=True).wait_for(timeout=180000)
        page.locator("#speaker-editor-result").wait_for(state="visible")
        assert "ещё не сохранён в архиве «Спикерская»" in page.locator(".speaker-not-saved").inner_text()
        candidate = page.evaluate("""async () => {
            const candidate = (await import('./scripts/speaker-editor.mjs')).getSpeakerCandidate();
            const bytes = new Uint8Array(await candidate.blob.arrayBuffer());
            const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(v => v.toString(16).padStart(2, '0')).join('');
            const context = new AudioContext(); const decoded = await context.decodeAudioData(bytes.buffer.slice(0));
            const data = decoded.getChannelData(0), rate = decoded.sampleRate;
            let bitrate = null;
            for (let index = 0; index < Math.min(bytes.length - 4, 65536); index++) {
                if (bytes[index] === 0xff && (bytes[index + 1] & 0xe0) === 0xe0) {
                    const version = (bytes[index + 1] >> 3) & 3, layer = (bytes[index + 1] >> 1) & 3;
                    const bitrateIndex = bytes[index + 2] >> 4;
                    if (version === 3 && layer === 1 && bitrateIndex > 0 && bitrateIndex < 15) {
                        bitrate = [0,32,40,48,56,64,80,96,112,128,160,192,224,256,320][bitrateIndex]; break;
                    }
                }
            }
            const energy = (frequency, start, end) => {
                let real = 0, imaginary = 0, total = 0;
                const first = Math.floor(start * rate), last = Math.min(data.length, Math.floor(end * rate));
                for (let index = first; index < last; index++) { const value = data[index]; const phase = 2 * Math.PI * frequency * index / rate;
                    real += value * Math.cos(phase); imaginary += value * Math.sin(phase); total += value * value; }
                return {tone: (real * real + imaginary * imaginary) / Math.max(1, (last - first) ** 2), rms: Math.sqrt(total / Math.max(1, last - first))};
            };
            const result = {type: candidate.candidateType, processor: candidate.processorVersion, mediaType: candidate.mediaType,
                size: candidate.sizeBytes, byteLength: bytes.byteLength, hash, candidateHash: candidate.sha256, bitrate,
                enhancement: candidate.trackProcessing[0].enhancement, excludedTrackIds: candidate.excludedTrackIds,
                duration: decoded.duration, firstSilenced: energy(330, 1.02, 1.48), firstLater: energy(330, 1.65, 2.15),
                otherDuringSilence: energy(550, 1.02, 1.48), excluded: energy(440, 1.65, 2.15), included: energy(550, 1.65, 2.15)};
            await context.close(); return result;
        }""")
        assert candidate["type"] == "speaker" and candidate["processor"] == "speaker-editor-v1" and candidate["mediaType"] == "audio/mpeg"
        assert candidate["enhancement"] == "gentle" and candidate["excludedTrackIds"] == [track_ids[1]], candidate
        assert candidate["size"] == candidate["byteLength"] and candidate["hash"] == candidate["candidateHash"]
        assert candidate["bitrate"] == 128, candidate
        assert abs(candidate["duration"] - 2.5) < .08, candidate
        assert candidate["firstSilenced"]["tone"] < candidate["firstLater"]["tone"] * .02, candidate
        assert candidate["otherDuringSilence"]["tone"] > 1e-5, candidate
        assert candidate["excluded"]["tone"] < candidate["included"]["tone"] * .02, candidate
        assert candidate["included"]["tone"] > 1e-5 and candidate["firstLater"]["tone"] > 1e-5, candidate
        result_canvas = page.locator("#speaker-editor-result-waveform canvas")
        assert result_canvas.get_attribute("data-used-width") == str(result_canvas.evaluate("canvas => canvas.width"))
        assert abs(float(result_canvas.get_attribute("data-timeline-duration")) - candidate["duration"]) < .08
        # An unchanged canonical save only rebinds revisions and retains the exact local bytes/result.
        page.locator("#speaker-editor-save").click()
        page.wait_for_function("document.getElementById(\'speaker-editor-status\').textContent === \'Все изменения сохранены\'")
        assert mock["speaker_draft"]["draftRevision"] == 2
        assert page.locator("#speaker-editor-result").is_visible()
        rebound = page.evaluate("""async () => {
            const candidate = (await import('./scripts/speaker-editor.mjs')).getSpeakerCandidate();
            return {draftRevision: candidate.draftRevision, sourceSessionRevision: candidate.sourceSessionRevision, sha256: candidate.sha256};
        }""")
        assert rebound == {"draftRevision": 2, "sourceSessionRevision": session["revision"], "sha256": candidate["hash"]}
        # Delayed result-waveform decoding is tied to this render token. Cancellation invalidates the pending
        # presentation, and its continuation cannot reveal either the old or the cancelled candidate.
        page.evaluate("""() => {
            const nativeDecode = AudioContext.prototype.decodeAudioData;
            window.speakerDecodeGate = {delay: 1200, entered: false};
            AudioContext.prototype.decodeAudioData = function(buffer, ...rest) {
                const decoded = nativeDecode.call(this, buffer, ...rest);
                if (!window.speakerDecodeGate.delay) return decoded;
                window.speakerDecodeGate.entered = true;
                return new Promise((resolve, reject) => setTimeout(() => decoded.then(resolve, reject), window.speakerDecodeGate.delay));
            };
        }""")
        page.locator("#speaker-editor-render").click()
        page.wait_for_function("window.speakerDecodeGate.entered", timeout=180000)
        assert page.locator("#speaker-editor-result").is_hidden()
        page.locator("#speaker-editor-cancel").click()
        page.wait_for_timeout(1500)
        assert page.locator("#speaker-editor-result").is_hidden()
        assert page.evaluate("""async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerCandidate() === null""")
        page.evaluate("window.speakerDecodeGate.delay = 0")
        page.wait_for_function("!document.getElementById('speaker-editor-render').disabled", timeout=5000)
        page.locator("#speaker-editor-render").click()
        page.get_by_text("Финальная версия готова. В архив ничего не передавалось.", exact=True).wait_for(timeout=180000)
        # Monitoring does not invalidate; a render-affecting DSP edit does.
        page.locator('.speaker-track button[data-action="solo"]').first.click()
        assert page.locator("#speaker-editor-result").is_visible()
        if not page.locator(".speaker-dsp input").first.is_visible():
            page.locator(".speaker-dsp-disclosure > summary").first.click()
        page.locator(".speaker-dsp input").nth(0).uncheck()
        assert page.locator("#speaker-editor-result").is_hidden()
        page.locator("#speaker-editor-undo").click()
        page.locator("#speaker-editor-render").click()
        page.get_by_text("Финальная версия готова. В архив ничего не передавалось.", exact=True).wait_for(timeout=180000)
        if screenshot_dir:
            page.evaluate("document.activeElement?.blur()")
            page.set_viewport_size({"width": 1280, "height": 900})
            page.locator("#speaker-editor-result").screenshot(path=str(screenshot_dir / "s08c-local-result-1280.png"))
            page.set_viewport_size({"width": 390, "height": 900})
            page.locator("#speaker-editor-result").screenshot(path=str(screenshot_dir / "s08c-local-result-390.png"))
        page.locator(".skip-link").evaluate("element => element.style.removeProperty('display')")
        # Exercise measured two-pass loudnorm in the real browser engine.
        if not page.locator(".speaker-dsp input").first.is_visible():
            page.locator(".speaker-dsp-disclosure > summary").first.click()
        page.locator(".speaker-dsp input").nth(0).uncheck()
        page.locator(".speaker-dsp input").nth(1).check()
        page.locator(".speaker-dsp input").nth(2).fill("0"); page.locator(".speaker-dsp input").nth(2).dispatch_event("change")
        page.locator("#speaker-editor-save").click()
        page.wait_for_function("document.getElementById(\'speaker-editor-status\').textContent === \'Все изменения сохранены\'")
        assert mock["speaker_draft"]["draftRevision"] == 3
        page.locator("#speaker-editor-render").click()
        page.get_by_text("Финальная версия готова. В архив ничего не передавалось.", exact=True).wait_for(timeout=180000)
        assert page.locator("#speaker-editor-result").is_visible()
        assert not any("/outputs/speaker/" in path or "/speaker-publications" in path for _, path, _ in gateway_calls)
        saved_candidate = page.evaluate("""async () => {
            const candidate = (await import('./scripts/speaker-editor.mjs')).getSpeakerCandidate();
            return {sha256: candidate.sha256, draftRevision: candidate.draftRevision,
                sourceSessionRevision: candidate.sourceSessionRevision, candidateFingerprint: candidate.candidateFingerprint};
        }""")
        assert page.locator("#speaker-editor-archive-save").is_enabled()
        page.locator("#speaker-editor-archive-save").click()
        page.locator("#speaker-editor-save-dialog").wait_for(state="visible")
        assert "Архивная запись" in page.locator("#speaker-editor-save-source").inner_text()
        assert "MP3" in page.locator("#speaker-editor-save-result").inner_text()
        assert "Версия 2" in page.locator("#speaker-editor-save-version").inner_text()
        if screenshot_dir:
            for width in (320, 390, 768, 1280):
                page.set_viewport_size({"width": width, "height": 900})
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), width
                page.evaluate("document.activeElement?.blur()")
                page.locator("#speaker-editor-save-dialog").evaluate("dialog => { dialog.scrollTop = 0; }")
                page.screenshot(path=str(screenshot_dir / f"s08d-speaker-save-confirmation-{width}.png"))
                if width in (320, 390):
                    page.locator("#speaker-editor-save-dialog").evaluate("dialog => { dialog.scrollTop = dialog.scrollHeight; }")
                    page.screenshot(path=str(screenshot_dir / f"s08d-speaker-save-confirmation-actions-{width}.png"))
            page.set_viewport_size({"width": 390, "height": 900})
        page.locator("#speaker-editor-save-submit").click(no_wait_after=True)
        for _ in range(200):
            if mock["speaker_held_upload"]:
                break
            page.wait_for_timeout(20)
        assert mock["speaker_held_upload"] is not None
        assert page.locator("#speaker-editor-save-progress").is_visible()
        assert page.locator("#speaker-editor-save").is_disabled()
        assert page.locator("#speaker-editor-render").is_disabled()
        if screenshot_dir:
            for width in (320, 390, 768, 1280):
                page.set_viewport_size({"width": width, "height": 900})
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), width
                page.evaluate("document.activeElement?.blur()")
                page.locator("#speaker-editor-save-dialog").evaluate("dialog => { dialog.scrollTop = 0; }")
                page.screenshot(path=str(screenshot_dir / f"s08d-speaker-save-progress-{width}.png"))
            page.set_viewport_size({"width": 390, "height": 900})
        # The server finalizes after the last upload while the browser still waits for that response.
        # Cancelling must reconcile the authoritative finalized job instead of claiming it was stopped.
        plan = mock["speaker_save"]["plan"]
        finalized_output = {"outputId": plan["outputId"], "version": 2, "sessionId": session_id,
            "createdAt": "2026-01-02T03:04:05.000Z", "blobId": plan["blobId"], "sizeBytes": plan["sizeBytes"],
            "sha256": plan["sha256"], "parts": [{**part, "assetId": 120 + index,
                "downloadUrl": f"https://github.com/meser-recovery/audio-archive/releases/download/audio-session-{session_id}/{part['assetName']}"}
                for index, part in enumerate(plan["parts"])],
            "recipeSnapshotRef": f"recipes/{session_id}/speaker/{plan['outputId']}.json",
            "processorVersion": plan["processorVersion"]}
        session["workflows"]["speaker"]["outputs"].append(finalized_output)
        session["workflows"]["speaker"]["status"] = "result_ready"
        session["revision"] += 1
        mock["speaker_output"] = finalized_output
        mock["speaker_output_recipe"] = {"schemaVersion": 1, "workflow": "speaker", "sessionId": session_id,
            "outputId": finalized_output["outputId"], "version": finalized_output["version"],
            "processorVersion": finalized_output["processorVersion"], "createdAt": finalized_output["createdAt"], **plan["recipe"]}
        mock["speaker_jobs"][speaker_save_id].update({"state": "finalized", "canFinalize": False,
            "requiresLocalResult": False, "uploadedParts": len(plan["parts"]),
            "uploadedPartNumbers": [part["partNumber"] for part in plan["parts"]]})
        held_speaker_upload = mock["speaker_held_upload"]
        page.locator("#speaker-editor-save-cancel").click()
        held_speaker_upload.abort("aborted")
        mock["speaker_held_upload"] = None
        page.get_by_text("Версия 2 сохранена в архиве «Спикерская».", exact=True).wait_for(timeout=30000)
        assert mock["speaker_output_bytes"] is not None
        assert hashlib.sha256(mock["speaker_output_bytes"]).hexdigest() == saved_candidate["sha256"]
        assert mock["speaker_save"]["plan"]["recipe"]["draft"]["revision"] == saved_candidate["draftRevision"] == 3
        assert mock["speaker_save"]["plan"]["recipe"]["sourceSessionRevision"] == saved_candidate["sourceSessionRevision"]
        assert mock["speaker_save"]["plan"]["recipe"]["candidateFingerprint"] == saved_candidate["candidateFingerprint"]
        page.locator("#speaker-editor-save-dialog").wait_for(state="hidden")
        page.wait_for_function("document.getElementById('source-session-results-speaker-count').textContent === '2'")
        assert page.locator("#source-session-results-speaker-panel button").count() == 6
        assert page.locator("#source-session-results-speaker-panel button").all_inner_texts().count("Прослушать") == 2
        assert page.locator("#source-session-results-speaker-panel button").all_inner_texts().count("Скачать") == 2
        if screenshot_dir:
            for width in (320, 390, 768, 1280):
                page.set_viewport_size({"width": width, "height": 900})
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), width
                page.evaluate("document.activeElement?.blur(); scrollTo(0, 0)")
                page.screenshot(path=str(screenshot_dir / f"s08d-speaker-saved-history-{width}.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 900})
        partial_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        mismatch_id = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
        complete_id = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
        recovery_plan = mock["speaker_save"]["plan"]

        def recovery_job(transaction_id, version, *, fingerprint=saved_candidate["candidateFingerprint"], complete=False):
            return {"kind": "publication", "workflow": "speaker", "transactionId": transaction_id,
                "sessionId": session_id, "outputId": recovery_plan["outputId"], "blobId": recovery_plan["blobId"],
                "state": "cancelled", "reservedVersion": version, "reservedSessionRevision": session["revision"],
                "uploadedParts": len(recovery_plan["parts"]) if complete else 0,
                "uploadedPartNumbers": [part["partNumber"] for part in recovery_plan["parts"]] if complete else [],
                "totalParts": len(recovery_plan["parts"]), "canFinalize": complete,
                "requiresLocalResult": not complete, "candidateFingerprint": fingerprint,
                "sizeBytes": recovery_plan["sizeBytes"], "sha256": recovery_plan["sha256"],
                "parts": recovery_plan["parts"], "updatedAt": "2026-01-02T03:04:05.000Z"}

        partial_job = recovery_job(partial_id, 3)
        mock["speaker_jobs"][partial_id] = partial_job
        mock["incomplete"] = [partial_job]
        refresh_editor_sources(page)
        page.get_by_text(re.compile("Есть незавершённое сохранение Версии 3"), exact=False).wait_for()
        mock["hold_resume"] = True
        resume_gets_before = len([call for call in gateway_calls if call[0] == "GET" and call[1] == f"/v1/speaker-saves/{partial_id}"])
        page.get_by_role("button", name="Продолжить передачу", exact=True).evaluate("button => { button.click(); button.click(); }")
        page.get_by_role("button", name="Отменить продолжение", exact=True).wait_for(timeout=30000)
        for _ in range(200):
            if mock["resume_held_upload"]:
                break
            page.wait_for_timeout(20)
        assert mock["resume_held_upload"] is not None
        assert len([call for call in gateway_calls if call[0] == "GET" and call[1] == f"/v1/speaker-saves/{partial_id}"]) == resume_gets_before + 1
        assert len([call for call in gateway_calls if call[0] == "PUT" and f"/speaker-saves/{partial_id}/" in call[1]]) == 1
        mock["hold_incomplete"] = True
        refresh_editor_sources(page)
        assert page.get_by_role("button", name="Отменить продолжение", exact=True).is_visible()
        for _ in range(200):
            if mock["held_incomplete"]:
                break
            page.wait_for_timeout(20)
        assert mock["held_incomplete"] is not None
        fulfill_json(mock["held_incomplete"], {"transactions": [partial_job], "orphans": []})
        mock["held_incomplete"] = None
        mock["hold_incomplete"] = False
        page.wait_for_timeout(100)
        assert page.get_by_role("button", name="Отменить продолжение", exact=True).is_visible()
        assert "Версия 3" in page.locator("#source-session-recovery-list").inner_text()
        assert page.locator("#speaker-editor-save").is_disabled()
        assert page.locator("#speaker-editor-render").is_disabled()
        assert page.locator("#speaker-editor-close").is_disabled()
        if page.locator("#import-zone").get_attribute("open") is None: page.locator("#import-zone > summary").click()
        page.locator("#source-session-mode-device").click()
        assert page.locator("#speaker-editor").is_visible()  # Import tab selection does not replace or close the project.
        page.locator("#source-session-mode-archive").click()
        assert page.evaluate("async () => (await import('./scripts/speaker-editor.mjs')).closeSpeakerEditor(true)") is False
        if screenshot_dir:
            for width in (320, 390, 768, 1280):
                page.set_viewport_size({"width": width, "height": 900})
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), width
                page.evaluate("document.activeElement?.blur(); scrollTo(0, 0)")
                page.screenshot(path=str(screenshot_dir / f"s08d-speaker-resume-locked-{width}.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 900})
        held_resume_upload = mock["resume_held_upload"]
        page.get_by_role("button", name="Отменить продолжение", exact=True).click()
        held_resume_upload.abort("aborted")
        page.get_by_text(re.compile("Продолжение Версии 3 остановлено"), exact=False).wait_for(timeout=30000)
        assert partial_job["state"] == "cancelled"
        assert page.evaluate("async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().saving") is False
        assert page.locator("#speaker-editor-close").is_enabled()
        mock["resume_held_upload"] = None
        mock["hold_resume"] = False
        refresh_editor_sources(page)
        page.get_by_role("button", name="Продолжить передачу", exact=True).click()
        page.wait_for_function("document.getElementById('source-session-recovery-list').textContent.includes('не найдено')", timeout=30000)
        assert partial_job["state"] == "finalized"

        mismatch_job = recovery_job(mismatch_id, 4, fingerprint="different-candidate-fingerprint")
        mock["speaker_jobs"][mismatch_id] = mismatch_job
        mock["incomplete"] = [mismatch_job]
        refresh_editor_sources(page)
        page.get_by_role("button", name="Продолжить передачу", exact=True).click()
        page.get_by_text(re.compile("точно тот же локальный результат"), exact=False).wait_for(timeout=30000)
        assert mismatch_job["state"] == "cancelled"
        refresh_editor_sources(page)
        page.once("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="Удалить незавершённое сохранение", exact=True).click()
        page.wait_for_function("document.getElementById('source-session-recovery-list').textContent.includes('не найдено')")
        assert mismatch_job["state"] == "discarded"

        page.once("dialog", lambda dialog: dialog.accept())
        page.locator("#speaker-editor-close").click()
        if page.locator("#speaker-unsaved-dialog").is_visible(): page.locator("#speaker-unsaved-discard").click()
        assert page.locator("#speaker-editor").is_hidden()
        complete_job = recovery_job(complete_id, 5, complete=True)
        mock["speaker_jobs"][complete_id] = complete_job
        mock["incomplete"] = [complete_job]
        uploads_before_reload_recovery = len([call for call in gateway_calls if call[0] == "PUT" and f"/speaker-saves/{complete_id}/" in call[1]])
        page.reload(wait_until="domcontentloaded")
        page.get_by_text(re.compile("Есть незавершённое сохранение Версии 5"), exact=False).wait_for(timeout=30000)
        assert page.get_by_role("button", name="Завершить сохранение", exact=True).count() == 1
        if screenshot_dir:
            for width in (320, 390, 768, 1280):
                page.set_viewport_size({"width": width, "height": 900})
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), width
                page.evaluate("document.activeElement?.blur(); scrollTo(0, 0)")
                page.screenshot(path=str(screenshot_dir / f"s08d-speaker-recovery-{width}.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 900})
        page.get_by_role("button", name="Завершить сохранение", exact=True).click()
        page.wait_for_function("document.getElementById('source-session-recovery-list').textContent.includes('не найдено')")
        assert complete_job["state"] == "finalized"
        uploads_after_reload_recovery = len([call for call in gateway_calls if call[0] == "PUT" and f"/speaker-saves/{complete_id}/" in call[1]])
        assert uploads_after_reload_recovery == uploads_before_reload_recovery
        page.get_by_role("button", name="Редактировать для анонс-мейкера", exact=True).click()
        try:
            page.locator(".processor-track").first.wait_for(timeout=30000)
        except Error as error:
            raise AssertionError({"error": str(error), "pageErrors": page_errors, "status": page.locator("#source-session-status").inner_text(), "calls": gateway_calls})
        page.wait_for_function("document.querySelectorAll('.processor-track').length === 3")
        assert page.locator(".processor-track__name").all_inner_texts() == names
        assert "Архивная запись" in page.locator("#source-session-announcement-identity").inner_text()
        assert session_id not in page.locator("#source-session-announcement-identity").inner_text()
        assert all(name in page.locator("#processor-file-info").inner_text() for name in names)
        assert all(track_id not in page.locator("#processor-file-info").inner_text() for track_id in track_ids)
        assert page.locator("#source-session-announcement-save").count() == 0
        assert page.locator("#source-session-publish-announcement").is_disabled()
        if screenshot_dir:
            for width in (390, 1280):
                page.set_viewport_size({"width": width, "height": 900})
                page.evaluate("document.activeElement?.blur()")
                page.evaluate("scrollTo(0, 0)")
                page.screenshot(path=str(screenshot_dir / f"s08b-selected-work-{width}.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 900})
        page.locator('.processor-track button[data-track-action="remove"]').nth(1).click()
        page.wait_for_function("document.querySelectorAll('.processor-track').length === 2")
        assert page.locator(".processor-track__name").all_inner_texts() == [names[0], names[2]]
        page.locator('.processor-track button[data-track-action="move-up"]').nth(1).click()
        assert page.locator(".processor-track__name").all_inner_texts() == [names[2], names[0]]
        assert mock["draft"] is None  # S09A: processing is local; lineage is saved only with explicit result save.
        page.wait_for_function("!document.getElementById('processor-file').disabled")
        page.locator("#processor-run").click()
        wait_processor_status(page, "Длинные общие паузы не найдены. Дорожки сведены без сокращения пауз.")
        assert not page.locator("#source-session-publish-announcement").is_disabled()
        if screenshot_dir:
            for width in (390, 1280):
                page.set_viewport_size({"width": width, "height": 900})
                page.evaluate("document.activeElement?.blur()")
                page.evaluate("scrollTo(0, 0)")
                page.screenshot(path=str(screenshot_dir / f"s08b-local-result-{width}.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 900})
        calls_before_confirmation = len(gateway_calls)
        page.locator("#source-session-publish-announcement").click()
        assert page.locator("#source-session-publication-dialog").evaluate("dialog => dialog.contains(document.activeElement)")
        page.keyboard.press("Escape")
        page.locator("#source-session-publication-dialog").wait_for(state="hidden")
        assert page.locator("#source-session-publish-announcement").evaluate("button => document.activeElement === button")
        assert not any(method == "POST" and path.endswith("/outputs/announcement/publications")
            for method, path, _ in gateway_calls[calls_before_confirmation:])
        page.locator("#source-session-publish-announcement").click()
        summary = page.locator("#source-session-publication-summary").inner_text()
        tracks_summary = page.locator("#source-session-publication-tracks").inner_text()
        assert "Архивная запись" in summary and session_id not in summary
        assert names[0] in tracks_summary and names[2] in tracks_summary and names[1] not in tracks_summary
        assert tracks_summary.index(names[2]) < tracks_summary.index(names[0])
        assert "сведение нескольких дорожек" in summary and "MP3" in summary and "Версия 1 (предварительно)" in summary
        assert page.locator("#source-session-publication-destination").inner_text() == "Анонс-мейкер"
        if screenshot_dir:
            for width in (390, 1280):
                page.set_viewport_size({"width": width, "height": 900})
                page.evaluate("document.activeElement?.blur()")
                page.screenshot(path=str(screenshot_dir / f"s08b-save-confirmation-{width}.png"))
                if width == 390:
                    page.locator("#source-session-publication-dialog").evaluate("dialog => { dialog.scrollTop = dialog.scrollHeight; }")
                    page.screenshot(path=str(screenshot_dir / "s08b-save-confirmation-actions-390.png"))
                    page.locator("#source-session-publication-dialog").evaluate("dialog => { dialog.scrollTop = 0; }")
            page.set_viewport_size({"width": 390, "height": 900})
        page.locator("#source-session-publication-submit").click(no_wait_after=True)
        page.wait_for_function("() => Boolean(window)")
        for _ in range(100):
            if mock["held_upload"]:
                break
            page.wait_for_timeout(20)
        assert mock["held_upload"] is not None
        assert page.locator("#source-session-publication-progress").is_visible()
        assert float(page.locator("#source-session-publication-progress").get_attribute("value")) < 100
        if screenshot_dir:
            for width in (390, 1280):
                page.set_viewport_size({"width": width, "height": 900})
                page.evaluate("document.activeElement?.blur()")
                if width == 390:
                    page.locator("#source-session-publication-dialog").evaluate("dialog => { dialog.scrollTop = dialog.scrollHeight; }")
                page.screenshot(path=str(screenshot_dir / f"s08b-save-progress-{width}.png"))
                page.locator("#source-session-publication-dialog").evaluate("dialog => { dialog.scrollTop = 0; }")
            page.set_viewport_size({"width": 390, "height": 900})
        mock["held_upload"].fulfill(status=200, content_type="application/json", headers={
            "Access-Control-Allow-Origin": site_origin, "Access-Control-Allow-Credentials": "true",
        }, body=json.dumps({"uploaded": True, "assetId": 99, "downloadUrl": asset_urls[0]}))
        mock["held_upload"] = None
        page.get_by_text("Версия 1 сохранена в архиве «Анонс-мейкер».", exact=True).wait_for(timeout=30000)
        recipe_sources = mock["publication"]["plan"]["recipe"]["sources"]
        assert [source["trackId"] for source in recipe_sources] == [track_ids[2], track_ids[0]]
        assert [source["ordinal"] for source in recipe_sources] == [1, 2]
        assert mock["draft"]["payload"]["trackIds"] == [track_ids[2], track_ids[0]]
        assert [track["ordinal"] for track in session["sourceTracks"]] == [1, 2, 3]
        page.wait_for_function("document.getElementById('source-session-results-announcement-count').textContent === '1'")
        assert page.locator("#source-session-results-announcement-panel").get_by_role("button", name="Прослушать", exact=True).count() == 1
        assert page.locator("#source-session-results-announcement-panel").get_by_role("button", name="Скачать", exact=True).count() == 1
        assert page.locator("#source-session-results-announcement-panel").get_by_role("button", name="Удалить версию", exact=True).count() == 1
        assert page.locator("#source-session-results-speaker-panel button").count() == 6
        if screenshot_dir:
            page.locator("#source-session-publication-dialog").wait_for(state="hidden")
            for width in (390, 1280):
                page.set_viewport_size({"width": width, "height": 900})
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), width
                page.evaluate("document.activeElement?.blur(); scrollTo(0, 0)")
                page.screenshot(path=str(screenshot_dir / f"s08b-saved-history-{width}.png"), full_page=True)
        assert all(any(method == "GET" and path.endswith(f"/blobs/{blob_id}/parts/1/content") for method, path, _ in gateway_calls)
            for blob_id in blob_ids)
        assert session["lifecycle"]["state"] == "incoming"
        session["lifecycle"]["state"] = "archived"
        refresh_editor_sources(page)
        page.get_by_text(re.compile("Убрана из рабочего списка"), exact=False).first.wait_for()
        page.locator(".source-session-item").wait_for()
        assert page.locator("#source-session-results-announcement-count").inner_text() == "1"
        calls_before_archived_open = len(gateway_calls)
        assert page.locator('#source-session-list').get_by_role('button', name='Редактировать для анонс-мейкера').is_disabled()
        assert page.locator('#source-session-list').get_by_role('button', name='Вернуть для обработки').is_enabled()
        assert session["lifecycle"]["state"] == "archived"
        assert not any(path.endswith("/restore") for _, path, _ in gateway_calls[calls_before_archived_open:])
        session["sourceState"] = "deleted"
        session["deletedSources"] = {"deletedAt": "2026-01-03T00:00:00.000Z", "tracks": [
            {"trackId": track_id, "blobId": blob_id, "sizeBytes": len(wav), "sha256": digest}
            for track_id, blob_id, wav, digest in zip(track_ids, blob_ids, wavs, digests)]}
        session["sourceTracks"] = []
        refresh_editor_sources(page)
        page.get_by_text(re.compile("исходники удалены"), exact=False).first.wait_for()
        assert page.locator("#source-session-results-announcement-count").inner_text() == "1"
        assert page.locator("#source-session-results-speaker-count").inner_text() == "2"
        calls_before_result = len(gateway_calls)
        page.locator("#source-session-results-announcement-panel").get_by_role("button", name="Прослушать", exact=True).click()
        page.locator("#source-session-announcement-audio").wait_for(state="visible")
        page.wait_for_function("document.getElementById('source-session-announcement-audio').src.startsWith('blob:')")
        assert not any(method not in {"GET", "OPTIONS"} for method, _, _ in gateway_calls[calls_before_result:])
        assert page.get_by_text(re.compile("Файл проверен и готов к воспроизведению."), exact=False).is_visible()
        if screenshot_dir:
            for width in (320, 1280):
                page.set_viewport_size({"width": width, "height": 900})
                page.evaluate("document.activeElement?.blur(); scrollTo(0, 0)")
                page.screenshot(path=str(screenshot_dir / f"s08b-restored-result-{width}.png"), full_page=True)
        for width in (320, 390, 768, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), width

        # A full page reload and deleted source assets do not affect the independently saved Speaker result.
        page.reload(wait_until="domcontentloaded")
        page.wait_for_function("document.getElementById('source-session-results-speaker-count').textContent === '2'", timeout=30000)
        page.locator("#source-session-results-speaker").click()
        saved_speaker = page.locator("#source-session-results-speaker-list .result-archive-item").first
        assert "Версия 2" in saved_speaker.inner_text() and "исходники удалены" in saved_speaker.inner_text()
        calls_before_speaker_result = len(gateway_calls)
        saved_speaker.get_by_role("button", name="Прослушать", exact=True).click()
        page.locator("#source-session-announcement-audio").wait_for(state="visible")
        page.wait_for_function("document.getElementById('source-session-announcement-audio').src.startsWith('blob:')")
        assert page.locator("#source-session-announcement-playback-label").inner_text() == "Прослушивание · Спикерская"
        assert page.locator("#source-session-announcement-download").get_attribute("download") == mock["speaker_output_recipe"]["result"]["presentationFilename"]
        assert not any(method not in {"GET", "OPTIONS"} for method, _, _ in gateway_calls[calls_before_speaker_result:])
        assert any(path.endswith(f"/outputs/speaker/{mock['speaker_output']['outputId']}") for _, path, _ in gateway_calls[calls_before_speaker_result:])
        assert page.get_by_text(re.compile("Файл проверен и готов к воспроизведению."), exact=False).is_visible()
        mock["speaker_output_corrupt"] = True
        saved_speaker.get_by_role("button", name="Прослушать", exact=True).click()
        page.get_by_text("Не удалось проверить и открыть сохранённый результат.", exact=True).wait_for(timeout=30000)
        assert page.locator("#source-session-announcement-playback").is_hidden()
        assert page.locator("#source-session-announcement-download").get_attribute("href") is None
        assert page.locator("#source-session-announcement-audio").get_attribute("src") is None
        mock["speaker_output_corrupt"] = False
        if screenshot_dir:
            for width in (320, 390, 768, 1280):
                page.set_viewport_size({"width": width, "height": 900})
                assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), width
                page.evaluate("document.activeElement?.blur(); scrollTo(0, 0)")
                page.screenshot(path=str(screenshot_dir / f"s08d-speaker-restored-result-{width}.png"), full_page=True)

        page.locator("#source-session-mode-archive").click()
        page.locator("#source-session-mode-device").click()
        page.locator("#processor-file").set_input_files({"name": "manual.wav", "mimeType": "audio/wav", "buffer": wavs[0]})
        page.locator("#processor-save-incoming").click()
        page.locator("#source-session-ingest-name").fill("Ручная запись")
        page.locator("#source-session-ingest-submit").click()
        page.locator("#source-session-ingest-dialog").wait_for(state="hidden")
        if not page.locator("#import-zone").evaluate("el => el.open"):
            page.locator("#import-zone > summary").click()
        page.wait_for_function("document.getElementById('source-session-status').textContent === 'Исходные записи сохранены в аудиоархиве.'")
        assert page.locator("#source-session-status").is_visible()
        assert any(method == "POST" and path == "/v1/source-sessions/ingestions" for method, path, _ in gateway_calls)
        assert any(method == "PUT" and "/parts/1" in path for method, path, _ in gateway_calls)
        assert any(method == "POST" and path.endswith("/finalize") for method, path, _ in gateway_calls)
        mock["list_failure"] = "server"
        refresh_editor_sources(page)
        page.get_by_text("Архив временно недоступен. Повторите действие позже.", exact=True).wait_for()
        assert "English backend failure" not in page.locator("body").inner_text()
        mock["list_failure"] = "network"
        refresh_editor_sources(page)
        page.get_by_text("Не удалось связаться с архивом. Проверьте подключение к сети и повторите действие.", exact=True).wait_for()
        mock["list_failure"] = None
        visible_text = page.locator("body").inner_text()
        for rejected in ("Source Session", "Announcement workspace", "Announcement draft", "publication", "Опубликов", "публикац", "опубликован"):
            assert rejected not in visible_text, rejected
        assert not unexpected_outbound, unexpected_outbound
        print("Source Session mock gateway passed: archive list/status, byte reconstruction, local adapter, manual ingestion and 320/390/768/1280 layout.")
    finally:
        context.close()


def wav_payload(name: str, segments: tuple[tuple[float, bool], ...], channels: int = 1, comment: str | None = None,
                frequency: float = 440, amplitude: float = 12000 / 32768, sample_rate: int = 44100) -> dict:
    """Generate PCM in memory; never commit or serve an audio test fixture."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setparams((channels, 2, sample_rate, 0, "NONE", "not compressed"))
        for duration, audible in segments:
            frames = b"".join(struct.pack("<h", int(amplitude * 32768 * math.sin(2 * math.pi * frequency * n / sample_rate)) if audible else 0) * channels
                              for n in range(round(duration * sample_rate)))
            wav.writeframes(frames)
    data = buffer.getvalue()
    if comment is not None:
        text = comment.encode("utf-8") + b"\x00"
        info = b"INFOICMT" + struct.pack("<I", len(text)) + text + (b"\x00" if len(text) % 2 else b"")
        chunk = b"LIST" + struct.pack("<I", len(info)) + info
        data = data[:4] + struct.pack("<I", len(data) - 8 + len(chunk)) + data[8:12] + chunk + data[12:]
    # Empty MIME intentionally proves extension-based validation.
    return {"name": name, "mimeType": "", "buffer": data}


def wait_processor_status(page, text: str) -> None:
    page.wait_for_function("text => document.getElementById('processor-status').textContent === text", arg=text, timeout=180000)
    page.wait_for_function("!document.getElementById('processor-file').disabled", timeout=30000)


def wait_waveforms(page, count: int, failures: int = 0) -> None:
    page.wait_for_function("!document.getElementById('processor-file').disabled", timeout=180000)
    if count == 0:
        assert page.locator("#processor-source").is_hidden()
        return
    page.wait_for_function(
        """values => document.querySelectorAll('.processor-track').length === values.count &&
            document.querySelectorAll('.processor-track .processor-waveform img').length === values.count - values.failures &&
            document.querySelectorAll('.processor-track .processor-waveform-status').length === values.failures""",
        arg={"count": count, "failures": failures}, timeout=30000,
    )
    assert page.locator("#processor-status").inner_text() in {
        "Файл выбран. Нажмите «Обработать».", "Дорожки выбраны. Нажмите «Обработать»."
    }


def assert_processor_no_result(page) -> None:
    if page.locator("#processor-result").is_visible() or page.locator("#processor-download").get_attribute("href") is not None:
        raise AssertionError("Processor created a fake/stale result or download")
    if page.locator("#processor-result-audio").get_attribute("src") is not None:
        raise AssertionError("Processor retained stale result audio")


def check_processor_helpers(page) -> None:
    result = page.evaluate("""async () => {
        const m = await import('./scripts/audio-processor.mjs');
        const parse = lines => m.parseSilences(lines, 10);
        return {
            boundaries: m.removalRanges([[0, 3], [4, 7], [8, 10]], 10),
            allSilent: m.removalRanges([[0, 10]], 10),
            eof: parse(['silence_start: 7']),
            short: parse(['silence_start: 1', 'silence_end: 2.999']),
            exact: parse(['silence_start: 1', 'silence_end: 3']),
            clamped: parse(['silence_start: -2', 'silence_end: 4', 'silence_start: 8', 'silence_end: 50']),
            invalid: parse(['silence_start: NaN', 'silence_end: 5', 'silence_start: 3', 'silence_end: Infinity',
                'silence_start: 7', 'silence_end: 2', 'silence_start: 12']),
            merged: parse(['silence_start: 1', 'silence_end: 4', 'silence_start: 3', 'silence_end: 6']),
            unknownDuration: m.parseSilences(['silence_start: 0'], Infinity),
            formats: ['audio.MP3', 'Спикерское.m4a', 'fixture.WAV'].map(name => m.validateFile({name, size: 500 * 1024 * 1024})),
            oversize: m.validateFile({name: 'large.wav', size: 500 * 1024 * 1024 + 1}),
            totalBoundary: m.validateFiles([{name: 'a.wav', size: 250 * 1024 * 1024}, {name: 'b.m4a', size: 250 * 1024 * 1024}]),
            totalOversize: m.validateFiles([{name: 'a.wav', size: 250 * 1024 * 1024}, {name: 'b.m4a', size: 250 * 1024 * 1024 + 1}]),
            intersection: m.commonSilences([{duration: 10, silences: [[1, 8]]}, {duration: 10, silences: [[2, 7]]},
                {duration: 10, silences: [[3, 4], [5, 8]]}], 10),
            tailIntersection: m.commonSilences([{duration: 9.5, silences: [[8, 9.5]]}, {duration: 10, silences: [[8, 10]]}], 10),
            tolerance: m.commonTimeline([{duration: 9.5}, {duration: 10}]),
            mismatch: (() => { try { m.commonTimeline([{duration: 9.499}, {duration: 10}]); return ''; } catch(e) { return e.message; } })(),
            filter: m.makeFilter([[3.175, 5.825]]),
            waveformWidths: [m.waveformWidth(8), m.waveformWidth(3600), m.waveformWidth(10000)]
        };
    }""")
    assert result["boundaries"] == [[0, 2.65], [4.175, 6.825], [8.35, 10]], result
    assert result["allSilent"] == [[.35, 10]], result
    assert result["eof"] == [[7, 10]] and result["short"] == [] and result["exact"] == [[1, 3]], result
    assert result["clamped"] == [[0, 4], [8, 10]] and result["invalid"] == [] and result["unknownDuration"] == [], result
    assert result["merged"] == [[1, 6]] and result["formats"] == ["", "", ""], result
    assert result["oversize"] == result["totalOversize"] == "Общий размер файлов слишком большой для обработки в браузере. Максимальный размер — 500 МБ.", result
    assert result["totalBoundary"] == "" and result["intersection"] == [[5, 7]] and result["tailIntersection"] == [[8, 10]], result
    assert result["tolerance"] == 10 and result["mismatch"] == "Дорожки имеют разную длительность. Проверьте, что они относятся к одной записи Zoom.", result
    assert "gte(t,3.175000)*lt(t,5.825000)" in result["filter"], result
    assert result["waveformWidths"] == [4096, 65536, 65536], result


def processor_mix_audio_metrics(page, windows: dict[str, tuple[float, float]]) -> dict:
    """Inspect real decoded MP3 energy and distinct speaker frequencies, not mocked DSP."""
    return page.evaluate("""async windows => {
        const blob = await (await fetch(document.getElementById('processor-download').href)).blob();
        const bytes = await blob.arrayBuffer(), raw = new Uint8Array(bytes);
        const frame = 10 + ((raw[6] & 127) * 2097152 + (raw[7] & 127) * 16384 + (raw[8] & 127) * 128 + (raw[9] & 127));
        const bitrate = [0,32,40,48,56,64,80,96,112,128,160,192,224,256,320][raw[frame + 2] >> 4];
        const context = new AudioContext({sampleRate: 48000});
        try {
            const decoded = await context.decodeAudioData(bytes), samples = decoded.getChannelData(0);
            let peak = 0, clipped = 0;
            for (const value of samples) { peak = Math.max(peak, Math.abs(value)); if (Math.abs(value) >= .995) clipped++; }
            const measures = {};
            for (const [label, [start, end]] of Object.entries(windows)) {
                const first = Math.round(start * decoded.sampleRate), last = Math.round(end * decoded.sampleRate);
                let energy = 0; for (let i = first; i < last; i++) energy += samples[i] ** 2;
                const tones = {};
                for (const frequency of [440, 660, 880]) {
                    let sin = 0, cos = 0;
                    for (let i = first; i < last; i++) {
                        const phase = 2 * Math.PI * frequency * i / decoded.sampleRate;
                        sin += samples[i] * Math.sin(phase); cos += samples[i] * Math.cos(phase);
                    }
                    tones[frequency] = 2 * Math.hypot(sin, cos) / (last - first);
                }
                measures[label] = {rms: Math.sqrt(energy / (last - first)), tones};
            }
            return {size: blob.size, type: blob.type, bitrate, peak, clippedFraction: clipped / samples.length, measures};
        } finally { await context.close(); }
    }""", windows)


def check_multi_track_processor(page, screenshot_dir: Path | None) -> None:
    no_common = "Длинные общие паузы не найдены. Дорожки сведены без сокращения пауз."
    mismatch = "Дорожки имеют разную длительность. Проверьте, что они относятся к одной записи Zoom."
    track_a = wav_payload("Zoom-A.wav", ((1, True), (1, False), (1, True), (3, False), (1, True), (1, False)), amplitude=.7)
    # Different source rates exercise the shared sample clock used for cuts.
    track_b = wav_payload("Zoom-B.wav", ((1, False), (1, True), (4, False), (1, True), (1, False)), frequency=660, amplitude=.7, sample_rate=48000)

    def capture_state(label: str) -> None:
        page.evaluate("document.activeElement.blur(); window.scrollTo(0, 0)")
        page.mouse.move(0, 0)
        for width in (390, 768, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth"), (label, width)
            assert page.locator("#processor-source-audio").is_hidden()
            for selector in ("#processor-file-info", "#processor-selection-summary", "#processor-source-audio-play", "#processor-source-audio-stop", "#announcement-processor-card .daw-monitor-volume", "#processor-run"):
                box = page.locator(selector).bounding_box()
                assert box and box["x"] >= 0 and box["x"] + box["width"] <= width + 1, (label, width, selector, box)
                assert not page.locator(selector).evaluate("el => el.scrollWidth > el.clientWidth + 1"), (label, width, selector)
            if page.locator("#processor-result").is_visible():
                for selector in ("#processor-result-audio", "#processor-download", "#processor-mixed-count"):
                    box = page.locator(selector).bounding_box()
                    assert box and box["x"] >= 0 and box["x"] + box["width"] <= width + 1, (label, width, selector, box)
            if screenshot_dir:
                page.screenshot(path=str(screenshot_dir / f"{label}-{width}.png"), full_page=True)

    def select_tracks(files, expected_size_prefix="0,") -> None:
        page.locator("#processor-file").set_input_files(files)
        wait_waveforms(page, len(files))
        assert page.evaluate("window.processorProbe.files") == {}, page.evaluate("window.processorProbe.files")
        assert page.locator("#processor-file-info > li").count() == len(files)
        if files:
            assert page.locator("#processor-selection-summary").inner_text().startswith(f"Выбрано дорожек: {len(files)} · Общий размер:")
        for index, file in enumerate(files):
            card = page.locator(".processor-track").nth(index)
            assert card.locator(".processor-track__number").inner_text() == f"Дорожка {index + 1}"
            assert card.locator(".processor-track__name").inner_text() == file["name"]
            assert card.locator(".processor-track__meta").inner_text().startswith(expected_size_prefix)
            assert card.get_by_role("button", name="S · Solo", exact=True).count() == 1
            assert card.get_by_role("button", name="M · Mute", exact=True).count() == 1
            assert card.get_by_role("button", name=re.compile("Удалить дорожку")).count() == 1
            assert card.locator(".processor-waveform").count() == 1
            assert card.locator("details, summary").count() == 0
        assert_processor_no_result(page)

    def run_selected(expected_status="Готово.") -> None:
        page.locator("#processor-run").click()
        page.wait_for_function("!document.getElementById('processor-file').disabled", timeout=180000)
        actual_status = page.locator("#processor-status").inner_text()
        assert actual_status == expected_status, (actual_status, expected_status, page.evaluate("window.processorProbe.logs"))
        assert not page.locator("#processor-cancel").is_visible() and not page.locator("#processor-progress").is_visible()
        assert page.evaluate("window.processorProbe.files") == {}, page.evaluate("window.processorProbe.files")

    def assert_result(count, duration, tracks) -> None:
        assert page.locator("#processor-result").is_visible()
        actual = float(page.locator("#processor-processed-duration").get_attribute("data-value"))
        assert abs(actual - duration) < .12, (actual, duration)
        assert int(page.locator("#processor-pause-count").inner_text()) == count
        assert page.locator("#processor-pause-label").inner_text() == "Сокращено общих длинных пауз"
        assert page.locator("#processor-mixed-count").inner_text() == f"Дорожек сведено: {tracks}"
        assert page.locator("#processor-result-audio").evaluate("audio => audio.paused && audio.src.startsWith('blob:')")
        assert page.locator("#processor-result-waveform-control img").count() == 1

    select_tracks([track_a])
    capture_state("mix-one-selected")
    select_tracks([track_a, track_b])
    assert page.locator(".processor-track .processor-waveform img").count() == 2
    assert page.locator("#processor-track-switcher, .processor-waveform-detail:not(canvas), #processor-file-info details").count() == 0
    assert page.get_by_text("Solo и Mute влияют только на прослушивание и не исключают дорожки из обработки.", exact=True).count() == 1
    assert page.locator("#processor-preview-audios .processor-preview-audio").count() == 1
    assert page.locator(".processor-track canvas.processor-waveform-detail").count() == 2
    waveform_urls = page.locator(".processor-track .processor-waveform img").evaluate_all("images => images.map(image => image.src)")
    assert len(set(waveform_urls)) == 2 and all(source.startswith("blob:") for source in waveform_urls), waveform_urls
    waveform_blobs = page.evaluate("""async urls => Promise.all(urls.map(async source => {
        const blob = await (await fetch(source)).blob(); return {size: blob.size, type: blob.type};
    }))""", waveform_urls)
    assert all(item["size"] > 0 and item["type"] == "image/png" for item in waveform_blobs), waveform_blobs
    page.set_viewport_size({"width": 390, "height": 900})
    scrolls = page.locator(".processor-track .processor-waveform-scroll")
    assert scrolls.count() == 2
    follow = page.locator("#processor-source-follow")
    shared_navigation = page.locator("#processor-source-navigation")
    shared_scrollbar = page.locator("#processor-source-scrollbar")
    assert follow.get_attribute("aria-label") == "Следовать за воспроизведением"
    assert follow.locator('svg[aria-hidden="true"]').count() == 1
    assert follow.get_attribute("aria-pressed") == "false"
    assert page.locator("#processor-source-scrollbar").count() == 1
    shared_thumb = page.locator("#processor-source-scrollbar-thumb")
    native_widths = page.locator(".processor-track .processor-waveform img").evaluate_all("images => images.map(image => image.naturalWidth)")
    page.locator("#processor-source-zoom-fit").click()
    assert shared_navigation.is_visible()
    assert shared_scrollbar.get_attribute("role") == "scrollbar"
    assert shared_scrollbar.get_attribute("aria-label") == "Навигация по исходным дорожкам"
    assert shared_scrollbar.get_attribute("aria-valuemax") == "0"
    assert shared_thumb.is_visible()
    assert shared_thumb.bounding_box()["width"] >= shared_scrollbar.bounding_box()["width"] - 2
    before_widths = page.locator(".processor-track .processor-waveform").evaluate_all("items => items.map(item => item.offsetWidth)")
    page.locator("#processor-source-zoom-in").click()
    assert shared_navigation.is_visible()
    assert shared_scrollbar.get_attribute("tabindex") == "0"
    assert shared_thumb.bounding_box()["width"] < shared_scrollbar.bounding_box()["width"] - 2
    after_widths = page.locator(".processor-track .processor-waveform").evaluate_all("items => items.map(item => item.offsetWidth)")
    assert after_widths[0] > before_widths[0] and abs(after_widths[0] - after_widths[1]) <= 1, (before_widths, after_widths)
    assert all(width <= native + 1 for width, native in zip(after_widths, native_widths)), (after_widths, native_widths)
    page.locator("#processor-source-zoom-range").evaluate("input => { input.value = 100; input.dispatchEvent(new Event('input', {bubbles: true})); }")
    assert scrolls.nth(0).evaluate("element => element.scrollWidth > element.clientWidth")
    page.wait_for_timeout(50)
    shared_scrollbar.scroll_into_view_if_needed()
    rail_box = shared_scrollbar.bounding_box()
    thumb_box = shared_thumb.bounding_box()
    assert rail_box and thumb_box
    page.mouse.move(thumb_box["x"] + thumb_box["width"] / 2, thumb_box["y"] + thumb_box["height"] / 2)
    page.mouse.down()
    page.mouse.move(rail_box["x"] + rail_box["width"] / 2, thumb_box["y"] + thumb_box["height"] / 2, steps=5)
    page.mouse.up()
    page.wait_for_function("""() => [...document.querySelectorAll('.processor-track .processor-waveform-scroll')]
        .every(item => item.scrollLeft > 20)""")
    shared_times = page.evaluate("""() => { const waveform = document.querySelector('.processor-waveform');
        const pps = waveform.offsetWidth / 8;
        return {tracks: [...document.querySelectorAll('.processor-track .processor-waveform-scroll')].map(item => item.scrollLeft / pps),
            shared: Number(document.getElementById('processor-source-scrollbar').getAttribute('aria-valuenow'))}; }""")
    assert max(shared_times["tracks"]) - min(shared_times["tracks"]) < .05
    assert all(abs(value - shared_times["shared"]) < .05 for value in shared_times["tracks"]), shared_times
    shared_scrollbar.scroll_into_view_if_needed()
    rail_box = shared_scrollbar.bounding_box()
    page.mouse.click(rail_box["x"] + 3, rail_box["y"] + rail_box["height"] / 2)
    page.wait_for_function("""() => [...document.querySelectorAll('.processor-track .processor-waveform-scroll')]
        .every(item => item.scrollLeft < 2) && Number(document.getElementById('processor-source-scrollbar').getAttribute('aria-valuenow')) === 0""")
    page.wait_for_timeout(50)
    page.evaluate("""() => { const items = document.querySelectorAll('.processor-track .processor-waveform-scroll');
        items[0].scrollLeft = 100; items[0].dispatchEvent(new Event('scroll')); }""")
    page.wait_for_function("""() => { const first = document.querySelectorAll('.processor-track .processor-waveform-scroll')[0];
        const second = document.querySelectorAll('.processor-track .processor-waveform-scroll')[1];
        const pps = first.querySelector('.processor-waveform').offsetWidth / 8;
        return Math.abs(second.scrollLeft - 100) < 2 && Math.abs(Number(document.getElementById('processor-source-scrollbar').getAttribute('aria-valuenow')) - 100 / pps) < .05; }""")
    page.wait_for_timeout(50)
    page.evaluate("""() => { const items = document.querySelectorAll('.processor-track .processor-waveform-scroll');
        items[1].scrollLeft = 160; items[1].dispatchEvent(new Event('scroll')); }""")
    page.wait_for_function("""() => { const first = document.querySelectorAll('.processor-track .processor-waveform-scroll')[0];
        const second = document.querySelectorAll('.processor-track .processor-waveform-scroll')[1];
        const pps = first.querySelector('.processor-waveform').offsetWidth / 8;
        return Math.abs(first.scrollLeft - 160) < 2 && Math.abs(Number(document.getElementById('processor-source-scrollbar').getAttribute('aria-valuenow')) - 160 / pps) < .05; }""")
    anchor_before = page.evaluate("""() => { const scroll = document.querySelector('.processor-track .processor-waveform-scroll');
        const waveform = scroll.querySelector('.processor-waveform');
        return (scroll.scrollLeft + scroll.clientWidth / 2) / (waveform.offsetWidth / 8); }""")
    page.locator("#processor-source-zoom-out").click()
    anchor_after = page.evaluate("""() => { const scroll = document.querySelector('.processor-track .processor-waveform-scroll');
        const waveform = scroll.querySelector('.processor-waveform');
        return (scroll.scrollLeft + scroll.clientWidth / 2) / (waveform.offsetWidth / 8); }""")
    assert abs(anchor_after - anchor_before) < .15, (anchor_before, anchor_after)
    assert shared_thumb.bounding_box()["width"] < shared_scrollbar.bounding_box()["width"] - 2
    page.locator("#processor-source-zoom-range").evaluate("input => { input.value = 100; input.dispatchEvent(new Event('input', {bubbles: true})); }")
    assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
    capture_state("waveforms-synchronized")
    page.set_viewport_size({"width": 390, "height": 900})
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    page.locator("#processor-source-zoom-range").evaluate(
        "input => { input.value = 100; input.dispatchEvent(new Event('input', {bubbles: true})); }")
    page.wait_for_timeout(50)
    page.wait_for_function("!document.getElementById('processor-source-navigation').hidden")

    # Alt-drag pans without seeking; plain drag selects, and click seeks.
    first_scroll = scrolls.nth(0)
    page.evaluate("document.getElementById('processor-source-audio').currentTime = 1")
    page.wait_for_timeout(50)
    page.evaluate("""() => { const scroll = document.querySelector('.processor-track .processor-waveform-scroll');
        scroll.scrollLeft = 120; scroll.dispatchEvent(new Event('scroll')); }""")
    page.wait_for_function("Math.abs(document.querySelector('.processor-track .processor-waveform-scroll').scrollLeft - 120) < 2")
    page.wait_for_timeout(50)
    scroll_before_drag = first_scroll.evaluate("element => element.scrollLeft")
    first_scroll.scroll_into_view_if_needed()
    scroll_box = first_scroll.bounding_box()
    assert scroll_box
    first_scroll.hover(position={"x": scroll_box["width"] * .7, "y": 50})
    page.keyboard.down("Alt")
    page.mouse.down()
    page.mouse.move(scroll_box["x"] + scroll_box["width"] * .35, scroll_box["y"] + 50, steps=5)
    page.mouse.up()
    page.keyboard.up("Alt")
    scroll_after_drag = first_scroll.evaluate("element => element.scrollLeft")
    assert abs(scroll_after_drag - scroll_before_drag) > 20, (
        scroll_before_drag, scroll_after_drag, scroll_box,
        first_scroll.evaluate("element => [element.scrollWidth, element.clientWidth]"))
    assert page.locator("#processor-source-audio").evaluate("audio => Math.abs(audio.currentTime - 1) < .15")
    first_waveform = page.locator(".processor-track").nth(0).locator(".processor-waveform")
    page.wait_for_timeout(170)
    first_waveform.click(position={"x": 80, "y": 50})
    page.wait_for_function("""() => { const master = document.getElementById('processor-source-audio');
        const hidden = document.querySelector('.processor-preview-audio');
        return hidden && Math.abs(master.currentTime - hidden.currentTime) < .12; }""")
    expected_click_time = page.evaluate("""() => { const scroll = document.querySelector('.processor-track .processor-waveform-scroll');
        return (scroll.scrollLeft + 80) / (scroll.querySelector('.processor-waveform').offsetWidth / 8); }""")
    assert abs(page.locator("#processor-source-audio").evaluate("audio => audio.currentTime") - expected_click_time) < .2
    playhead_positions = page.locator(".processor-track .processor-waveform-playhead").evaluate_all(
        "items => items.map(item => parseFloat(item.style.left))")
    assert max(playhead_positions) - min(playhead_positions) < 1, playhead_positions
    first_waveform.focus()
    first_waveform.press("Home")
    assert page.locator("#processor-source-audio").evaluate("audio => audio.currentTime < .1")
    first_waveform.press("ArrowRight")
    assert page.locator("#processor-source-audio").evaluate("audio => Math.abs(audio.currentTime - 5) < .1")
    first_waveform.press("Shift+ArrowRight")
    assert "5.000–5.100" in page.locator("#processor-loop-selection-summary").inner_text()
    assert page.locator("#processor-source-audio-loop").is_enabled()
    first_waveform.press("Shift+ArrowLeft")
    assert "5.000–5.000" in page.locator("#processor-loop-selection-summary").inner_text()
    assert page.locator("#processor-source-audio-loop").is_disabled()
    assert page.locator("#processor-source-audio").evaluate("audio => Math.abs(audio.currentTime - 5) < .1")
    first_waveform.press("End")
    assert page.locator("#processor-source-audio").evaluate("audio => Math.abs(audio.currentTime - 8) < .1")

    # Follow mode uses the master clock, clamps boundaries, and keeps all source navigation aligned.
    assert follow.get_attribute("aria-pressed") == "false"
    follow.click()
    assert follow.get_attribute("aria-pressed") == "true"
    first_waveform.press("Home")
    page.wait_for_function("""() => [...document.querySelectorAll('.processor-track .processor-waveform-scroll')]
        .every(item => item.scrollLeft < 2) && Number(document.getElementById('processor-source-scrollbar').getAttribute('aria-valuenow')) === 0""")
    first_waveform.click(position={"x": 180, "y": 50})
    page.wait_for_function("""() => { const scroll = document.querySelector('.processor-track .processor-waveform-scroll');
        const playhead = scroll.querySelector('.processor-waveform-playhead');
        return Math.abs((playhead.getBoundingClientRect().left - scroll.getBoundingClientRect().left) - scroll.clientWidth / 2) < 8; }""")
    page.evaluate("document.getElementById('processor-source-audio').currentTime = 4")
    # The old centered position can satisfy geometry before native seeking
    # starts. Require the requested clock and rendered position as well.
    page.wait_for_function("""() => { const scroll = document.querySelector('.processor-track .processor-waveform-scroll');
        const audio = document.getElementById('processor-source-audio');
        const playhead = scroll.querySelector('.processor-waveform-playhead');
        const pps = scroll.querySelector('.processor-waveform').offsetWidth / 8;
        return !audio.seeking && Math.abs(audio.currentTime - 4) < .01 &&
            Math.abs(parseFloat(playhead.style.left) - 4 * pps) < 2 &&
            Math.abs((playhead.getBoundingClientRect().left - scroll.getBoundingClientRect().left) - scroll.clientWidth / 2) < 8; }""")
    followed_middle = page.evaluate("""() => {
        const scrolls = [...document.querySelectorAll('.processor-track .processor-waveform-scroll')];
        const shared = document.getElementById('processor-source-scrollbar');
        const pps = scrolls[0].querySelector('.processor-waveform').offsetWidth / 8;
        return {lefts: scrolls.map(item => item.scrollLeft), shared: Number(shared.getAttribute('aria-valuenow')) * pps,
            visualX: scrolls[0].querySelector('.processor-waveform-playhead').getBoundingClientRect().left - scrolls[0].getBoundingClientRect().left,
            centerX: scrolls[0].clientWidth / 2};
    }""")
    assert max(followed_middle["lefts"]) - min(followed_middle["lefts"]) < 2 and abs(followed_middle["lefts"][0] - followed_middle["shared"]) < 2, followed_middle
    assert abs(followed_middle["visualX"] - followed_middle["centerX"]) < 8, followed_middle

    # Zoom while following recenters on the playhead and never desynchronizes tracks or proxy.
    page.locator("#processor-source-zoom-out").click()
    followed_zoom = page.evaluate("""() => { const scrolls = [...document.querySelectorAll('.processor-track .processor-waveform-scroll')];
        const shared = document.getElementById('processor-source-scrollbar');
        const first = scrolls[0], playhead = first.querySelector('.processor-waveform-playhead');
        const pps = first.querySelector('.processor-waveform').offsetWidth / 8;
        return {lefts: scrolls.map(item => item.scrollLeft), shared: Number(shared.getAttribute('aria-valuenow')) * pps,
            visualX: playhead.getBoundingClientRect().left - first.getBoundingClientRect().left, centerX: first.clientWidth / 2}; }""")
    assert max(followed_zoom["lefts"]) - min(followed_zoom["lefts"]) < 2 and abs(followed_zoom["lefts"][0] - followed_zoom["shared"]) < 2, followed_zoom
    assert abs(followed_zoom["visualX"] - followed_zoom["centerX"]) < 8, followed_zoom
    page.locator("#processor-source-zoom-range").evaluate("input => { input.value = 100; input.dispatchEvent(new Event('input', {bubbles: true})); }")

    page.evaluate("""async () => { const audio = document.getElementById('processor-source-audio');
        audio.currentTime = 3; await audio.play(); }""")
    playback_scroll_start = first_scroll.evaluate("element => element.scrollLeft")
    page.wait_for_function("start => document.querySelector('.processor-track .processor-waveform-scroll').scrollLeft > start + 8",
                           arg=playback_scroll_start, timeout=5000)
    assert follow.get_attribute("aria-pressed") == "true"
    playback_follow = page.evaluate("""() => { const items = [...document.querySelectorAll('.processor-track .processor-waveform-scroll')];
        const pps = items[0].querySelector('.processor-waveform').offsetWidth / 8;
        return {lefts: items.map(item => item.scrollLeft), shared: Number(document.getElementById('processor-source-scrollbar').getAttribute('aria-valuenow')) * pps}; }""")
    assert max(playback_follow["lefts"]) - min(playback_follow["lefts"]) < 2 and abs(playback_follow["lefts"][0] - playback_follow["shared"]) < 2, playback_follow
    page.locator("#processor-source-audio").evaluate("audio => audio.pause()")
    paused_left = first_scroll.evaluate("element => element.scrollLeft")
    page.wait_for_timeout(450)
    assert abs(first_scroll.evaluate("element => element.scrollLeft") - paused_left) < 2
    page.locator("#processor-source-audio").evaluate("audio => audio.play()")
    page.wait_for_function("start => document.querySelector('.processor-track .processor-waveform-scroll').scrollLeft > start + 5",
                           arg=paused_left, timeout=5000)
    page.locator("#processor-source-audio").evaluate("audio => audio.pause()")

    # Alt + waveform panning turns follow off; enabling it again recenters immediately.
    first_scroll.scroll_into_view_if_needed()
    scroll_box = first_scroll.bounding_box()
    assert scroll_box
    first_scroll.hover(position={"x": scroll_box["width"] * .55, "y": 50})
    page.keyboard.down("Alt")
    page.mouse.down()
    page.mouse.move(scroll_box["x"] + scroll_box["width"] * .25, scroll_box["y"] + 50, steps=5)
    page.mouse.up()
    page.keyboard.up("Alt")
    assert follow.get_attribute("aria-pressed") == "false"
    follow.click()
    assert follow.get_attribute("aria-pressed") == "true"
    recentered = page.evaluate("""() => { const scroll = document.querySelector('.processor-track .processor-waveform-scroll');
        const playhead = scroll.querySelector('.processor-waveform-playhead');
        return [playhead.getBoundingClientRect().left - scroll.getBoundingClientRect().left, scroll.clientWidth / 2]; }""")
    assert abs(recentered[0] - recentered[1]) < 8, recentered

    # Persistent custom thumb dragging and keyboard navigation are explicit manual intent.
    shared_scrollbar.scroll_into_view_if_needed()
    thumb_box = shared_thumb.bounding_box()
    rail_box = shared_scrollbar.bounding_box()
    assert thumb_box and rail_box
    page.mouse.move(thumb_box["x"] + thumb_box["width"] / 2, thumb_box["y"] + thumb_box["height"] / 2)
    page.mouse.down()
    page.mouse.move(min(rail_box["x"] + rail_box["width"] - thumb_box["width"] / 2, thumb_box["x"] + thumb_box["width"] + 30), thumb_box["y"] + thumb_box["height"] / 2, steps=4)
    page.mouse.up()
    assert follow.get_attribute("aria-pressed") == "false"
    follow.click()
    assert follow.get_attribute("aria-pressed") == "true"
    shared_scrollbar.focus()
    shared_scrollbar.press("ArrowRight")
    assert follow.get_attribute("aria-pressed") == "false"
    follow.click()
    shared_scrollbar.press("Home")
    assert shared_scrollbar.get_attribute("aria-valuenow") == "0"
    shared_scrollbar.press("PageDown")
    assert float(shared_scrollbar.get_attribute("aria-valuenow")) > 0
    shared_scrollbar.press("End")
    assert abs(float(shared_scrollbar.get_attribute("aria-valuenow")) - float(shared_scrollbar.get_attribute("aria-valuemax"))) < .01
    page.locator("#processor-source-zoom-fit").click()
    assert shared_navigation.is_visible() and shared_thumb.is_visible()
    assert shared_scrollbar.get_attribute("aria-valuemax") == "0"
    fit_now = shared_scrollbar.get_attribute("aria-valuenow")
    shared_scrollbar.press("ArrowRight")
    assert shared_scrollbar.get_attribute("aria-valuenow") == fit_now
    page.locator("#processor-source-zoom-range").evaluate("input => { input.value = 100; input.dispatchEvent(new Event('input', {bubbles: true})); }")
    follow.click()
    page.evaluate("document.getElementById('processor-source-audio').currentTime = 7.95")
    page.wait_for_function("""() => { const shared = document.getElementById('processor-source-scrollbar');
        return Math.abs(Number(shared.getAttribute('aria-valuenow')) - Number(shared.getAttribute('aria-valuemax'))) < .01; }""")
    end_state = page.evaluate("""() => { const shared = document.getElementById('processor-source-scrollbar');
        return {left: Number(shared.getAttribute('aria-valuenow')), max: Number(shared.getAttribute('aria-valuemax'))}; }""")
    assert end_state["left"] >= 0 and end_state["left"] <= end_state["max"] + 2, end_state
    page.locator("#processor-source-audio").evaluate("audio => audio.pause()")
    set_follow_off = follow.get_attribute("aria-pressed") == "true"
    if set_follow_off:
        follow.click()
    print("Shared source scrollbar/follow passed: fit visibility, bidirectional time sync, centered playback, pause/resume, zoom, boundary clamps and manual disengage.")

    # Solo/Mute are monitoring-only, support multiple solos, and are mutually clearing per track.
    cards = page.locator(".processor-track")
    cards.nth(0).get_by_role("button", name="S · Solo", exact=True).click()
    assert page.evaluate("""() => [document.getElementById('processor-source-audio').muted,
        document.querySelector('.processor-preview-audio').muted]""") == [False, True]
    if screenshot_dir:
        capture_state("monitoring-solo")
    cards.nth(1).get_by_role("button", name="S · Solo", exact=True).click()
    assert page.evaluate("""() => [document.getElementById('processor-source-audio').muted,
        document.querySelector('.processor-preview-audio').muted]""") == [False, False]
    cards.nth(1).get_by_role("button", name="M · Mute", exact=True).click()
    assert cards.nth(1).get_by_role("button", name="S · Solo", exact=True).get_attribute("aria-pressed") == "false"
    assert cards.nth(1).get_by_role("button", name="M · Mute", exact=True).get_attribute("aria-pressed") == "true"
    if screenshot_dir:
        capture_state("monitoring-solo-track-1-mute-track-2")
    cards.nth(0).get_by_role("button", name="S · Solo", exact=True).click()
    cards.nth(1).get_by_role("button", name="M · Mute", exact=True).click()
    cards.nth(0).get_by_role("button", name="M · Mute", exact=True).click()
    cards.nth(0).get_by_role("button", name="S · Solo", exact=True).click()
    assert cards.nth(0).get_by_role("button", name="M · Mute", exact=True).get_attribute("aria-pressed") == "false"
    cards.nth(0).get_by_role("button", name="M · Mute", exact=True).click()
    assert cards.nth(0).get_by_role("button", name="S · Solo", exact=True).get_attribute("aria-pressed") == "false"
    assert page.locator("#processor-file").evaluate("input => input.files.length") == 2

    # Native hidden players follow master play/pause and periodically correct meaningful drift.
    page.locator("#processor-source-audio").evaluate("""async audio => { audio.currentTime = 1; await audio.play(); }""")
    page.wait_for_function("""() => { const hidden = document.querySelector('.processor-preview-audio');
        return hidden && !hidden.paused && Math.abs(hidden.currentTime - document.getElementById('processor-source-audio').currentTime) < .25; }""")
    if screenshot_dir:
        page.screenshot(path=str(screenshot_dir / "monitoring-playing.png"), full_page=True)
    page.evaluate("document.querySelector('.processor-preview-audio').currentTime = 0")
    page.wait_for_function("""() => Math.abs(document.querySelector('.processor-preview-audio').currentTime -
        document.getElementById('processor-source-audio').currentTime) < .25""", timeout=3000)
    page.locator("#processor-source-audio").evaluate("audio => audio.pause()")
    assert page.locator(".processor-preview-audio").evaluate("audio => audio.paused")
    print("Synchronized preview passed: compact tracks, shared zoom/scroll/playheads, drag-vs-click seeking, native transport sync, drift correction and Solo/Mute precedence.")

    # Removing a track revokes both of its URLs and leaves a real single-track processor.
    revoked_before = set(page.evaluate("window.processorProbe.revoked"))
    page.locator(".processor-track").nth(1).get_by_role("button", name=re.compile("Удалить дорожку")).click()
    assert page.locator(".processor-track").count() == 1
    assert page.locator("#processor-selection-summary").inner_text().startswith("Выбрано дорожек: 1 ·")
    assert page.locator("#processor-file").evaluate("input => input.files.length") == 1
    newly_revoked = set(page.evaluate("window.processorProbe.revoked")) - revoked_before
    assert len(newly_revoked) == 2, newly_revoked
    if screenshot_dir:
        capture_state("track-removed")
    run_selected()
    assert page.locator("#processor-pause-count").inner_text() == "1"
    assert page.locator("#processor-mixed-count").is_hidden()
    assert page.locator("#processor-download").get_attribute("download") == "Zoom-A-edited.mp3"
    page.locator(".processor-track").get_by_role("button", name=re.compile("Удалить дорожку")).click()
    assert page.locator("#processor-source").is_hidden() and page.locator("#processor-run").is_disabled()
    assert page.locator("#processor-source-navigation").is_hidden()
    assert page.locator("#processor-file").evaluate("input => input.files.length") == 0
    assert page.locator("#processor-status").inner_text() == "Выберите файлы и нажмите «Обработать»."

    select_tracks([track_a, track_b])
    capture_state("mix-two-selected")
    page.locator(".processor-track").nth(0).get_by_role("button", name="S · Solo", exact=True).click()
    messages_before_monitoring_run = len(page.evaluate("window.processorProbe.messages"))
    run_selected()
    assert_result(1, 5.35, 2)
    monitoring_messages = page.evaluate("start => window.processorProbe.messages.slice(start)", messages_before_monitoring_run)
    assert {message["path"] for message in monitoring_messages if message["type"] == "WRITE_FILE" and
            str(message["path"]).startswith("processor-input-")} == {"processor-input-0", "processor-input-1"}, monitoring_messages
    assert any(message["type"] == "EXEC" and message["args"].count("-i") == 2 and
               "-filter_complex_script" in message["args"] and "[mixed]" in message["args"]
               for message in monitoring_messages), monitoring_messages
    assert float(page.locator("#processor-original-duration").get_attribute("data-value")) == 8
    assert abs(float(page.locator("#processor-removed-duration").get_attribute("data-value")) - 2.65) < .12
    assert page.locator("#processor-download").get_attribute("download") == "Zoom-A-mixed-edited.mp3"
    with page.expect_download() as event:
        page.locator("#processor-download").click()
    assert event.value.suggested_filename == "Zoom-A-mixed-edited.mp3" and event.value.failure() is None
    metrics = processor_mix_audio_metrics(page, {"a": (.2, .8), "b": (1.2, 1.8), "a_again": (2.2, 2.8),
        "overlap": (3.5, 4.1), "tail": (4.5, 5.1)})
    assert metrics["size"] > 0 and metrics["type"] == "audio/mpeg" and metrics["bitrate"] == 128, metrics
    # Solo speakers retain their level (amix must not divide by track count).
    assert metrics["measures"]["a"]["tones"]["440"] > .55 and metrics["measures"]["b"]["tones"]["660"] > .55, metrics
    assert metrics["measures"]["a_again"]["tones"]["440"] > .55, metrics
    assert metrics["measures"]["overlap"]["tones"]["440"] > .3 and metrics["measures"]["overlap"]["tones"]["660"] > .3, metrics
    assert metrics["measures"]["tail"]["rms"] < .005, metrics
    assert metrics["peak"] < 1.05 and metrics["clippedFraction"] < .005, metrics
    output = float(page.locator("#processor-processed-duration").get_attribute("data-value"))
    print(f"Real two-track mix passed: 8s -> {output:.6f}s, common pauses=1, MP3=128kbps; A/B solo and overlapping speech retained, peak={metrics['peak']:.6f}, clipped fraction={metrics['clippedFraction']:.6f}.")
    capture_state("mix-completed")

    track_c = wav_payload("Zoom-C.wav", ((4, True), (2, False), (2, True)), frequency=880)
    select_tracks([track_a, track_b, track_c])
    if screenshot_dir:
        capture_state("mix-three-selected")
    run_selected()
    assert_result(1, 6.35, 3)
    metrics_three = processor_mix_audio_metrics(page, {"third_fills_silence": (3.2, 3.8), "overlap": (4.6, 5.1)})
    assert metrics_three["measures"]["third_fills_silence"]["tones"]["880"] > .25, metrics_three
    assert all(metrics_three["measures"]["overlap"]["tones"][str(frequency)] > .12 for frequency in (440, 660, 880)), metrics_three
    output = float(page.locator("#processor-processed-duration").get_attribute("data-value"))
    print(f"Real three-track intersection passed: 8s -> {output:.6f}s, common pauses=1; C protects 3-4s and all three simultaneous tones survive.")

    select_tracks([wav_payload("alternating-A.wav", ((2, True), (2, False))),
                   wav_payload("alternating-B.wav", ((2, False), (2, True)), frequency=660)])
    run_selected(no_common)
    assert_result(0, 4, 2)
    assert float(page.locator("#processor-removed-duration").get_attribute("data-value")) < .05
    print("Real no-common-silence mix passed: MP3 produced, exact mixed-without-cuts status, pause count=0, removed duration near zero.")

    select_tracks([wav_payload("short.wav", ((2, True),)), wav_payload("long.wav", ((3, True),))])
    before = len(page.evaluate("window.processorProbe.messages"))
    run_selected(mismatch)
    assert_processor_no_result(page)
    messages = page.evaluate("window.processorProbe.messages")[before:]
    executions = [message["args"] for message in messages if message["type"] == "EXEC"]
    assert len(executions) == 2 and all("libmp3lame" not in args and "-filter_complex_script" not in args for args in executions), executions
    assert not any(message["type"] == "WRITE_FILE" and message["path"] == "processor-filter.txt" for message in messages), messages

    select_tracks([wav_payload("tolerated-short.wav", ((2, True),)), wav_payload("tolerated-long.wav", ((2.5, True),), frequency=660)])
    run_selected(no_common)
    assert_result(0, 2.5, 2)
    # 1.5s of actual silence + 0.5s missing tail is eligible only on the common timeline.
    select_tracks([wav_payload("tail-short.wav", ((1, True), (1.5, False))),
                   wav_payload("tail-long.wav", ((1, True), (2, False)), frequency=660)])
    run_selected()
    assert_result(1, 1.35, 2)
    print("Duration safety passed: >0.5s rejected after independent analyses with no final encode; exactly 0.5s accepted, longest timeline preserved, missing tail counted as silence.")

    select_tracks([track_a, track_b])
    probe_before = page.evaluate("window.processorProbe")
    source_before = page.locator("#processor-source-audio").get_attribute("src")
    # Cancel when analysis of the second real input begins, not a mocked engine call.
    page.evaluate("""() => {
        const status = document.getElementById('processor-status'); let analyses = 0;
        const observer = new MutationObserver(() => {
            if (status.textContent === 'Поиск длинных пауз…' && ++analyses === 2) {
                observer.disconnect(); document.getElementById('processor-cancel').click();
            }
        });
        observer.observe(status, {childList: true});
    }""")
    run_selected("Обработка отменена.")
    assert_processor_no_result(page)
    assert page.locator("#processor-file").evaluate("input => input.files.length") == 2
    assert page.locator("#processor-file-info li").count() == 2
    assert page.locator("#processor-source-audio").get_attribute("src") == source_before
    assert page.evaluate("window.processorProbe.terminated") == probe_before["terminated"] + 1
    run_selected()
    assert_result(1, 5.35, 2)
    assert page.evaluate("window.processorProbe.workers") == probe_before["workers"] + 1

    # Long-source navigation is required in CI too, independently of PNG capture.
    visual_a = wav_payload("Навигация-A.wav", ((150, True), (150, False)), sample_rate=8000)
    visual_b = wav_payload("Навигация-B.wav", ((150, False), (150, True)), frequency=660, sample_rate=8000)
    select_tracks([visual_a, visual_b], expected_size_prefix="4,")
    for width in (390, 768, 1280):
        page.set_viewport_size({"width": width, "height": 900})
        if page.locator("#processor-source-follow").get_attribute("aria-pressed") == "true":
            page.locator("#processor-source-follow").click()
        page.locator("#processor-source-zoom-fit").click()
        assert page.locator("#processor-source-navigation").is_visible()
        assert page.locator("#processor-source-scrollbar-thumb").is_visible()
        assert page.locator("#processor-source-scrollbar-thumb").bounding_box()["width"] >= page.locator("#processor-source-scrollbar").bounding_box()["width"] - 2
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
        if screenshot_dir: page.screenshot(path=str(screenshot_dir / f"source-fit-{width}.png"), full_page=True)
        page.locator("#processor-source-zoom-range").evaluate(
            "input => { input.value = 100; input.dispatchEvent(new Event('input', {bubbles: true})); }")
        assert page.locator("#processor-source-navigation").is_visible()
        assert page.locator("#processor-source-scrollbar-thumb").bounding_box()["width"] < page.locator("#processor-source-scrollbar").bounding_box()["width"] - 2
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
        page.wait_for_timeout(50)
        page.locator("#processor-source-scrollbar").scroll_into_view_if_needed()
        rail_box = page.locator("#processor-source-scrollbar").bounding_box()
        page.mouse.click(rail_box["x"] + rail_box["width"] / 2, rail_box["y"] + rail_box["height"] / 2)
        if screenshot_dir: page.screenshot(path=str(screenshot_dir / f"source-scrollbar-middle-{width}.png"), full_page=True)
        page.locator("#processor-source-follow").click()
        page.evaluate("""async () => { const audio = document.getElementById('processor-source-audio');
            audio.currentTime = 150; await audio.play(); }""")
        page.wait_for_timeout(250)
        assert page.locator("#processor-source-follow").get_attribute("aria-pressed") == "true", width
        if screenshot_dir: page.screenshot(path=str(screenshot_dir / f"source-follow-playing-{width}.png"), full_page=True)
        page.locator("#processor-source-audio").evaluate("audio => audio.pause()")
        # A fractional target at 1000px/s is rounded by the browser. Its own
        # scroll notification must not be interpreted as a manual pan.
        page.evaluate("document.getElementById('processor-source-audio').currentTime = 150.0005")
        page.wait_for_timeout(100)
        assert page.locator("#processor-source-follow").get_attribute("aria-pressed") == "true", width
        page.evaluate("document.getElementById('processor-source-audio').currentTime = 299.8")
        page.wait_for_timeout(50)
        if screenshot_dir: page.screenshot(path=str(screenshot_dir / f"source-follow-end-{width}.png"), full_page=True)
        # A delayed scroll notification for the position we assigned must be
        # idempotent even after rendering/decoding has outlived two frames.
        page.evaluate("()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(()=>requestAnimationFrame(r))))")
        assert page.locator("#processor-source-follow").get_attribute("aria-pressed") == "true", width
        before = page.locator(".processor-waveform-scroll").evaluate_all("es=>es.map(e=>e.scrollLeft)")
        page.locator(".processor-waveform-scroll").first.dispatch_event("scroll")
        assert page.locator("#processor-source-follow").get_attribute("aria-pressed") == "true", width
        assert page.locator(".processor-waveform-scroll").evaluate_all("es=>es.map(e=>e.scrollLeft)") == before
    print("Long-source Follow passed: 1000px/s, playback/paused end seek and delayed synchronized scroll at three widths.", flush=True)

    long_name = "Очень-длинное-название-спикерского-" * 6 + ".wav"
    long_track = dict(track_a, name=long_name)
    select_tracks([long_track])
    capture_state("mix-long-one-selected")
    select_tracks([long_track, track_b])
    capture_state("mix-long-two-selected")
    run_selected()
    assert page.locator("#processor-download").get_attribute("download") == long_name[:-4] + "-mixed-edited.mp3"
    capture_state("mix-long-completed")
    probe = page.evaluate("window.processorProbe")
    assert probe["files"] == {}, probe["files"]
    live_urls = set(probe["urls"]) - set(probe["revoked"])
    visible_urls = set(page.evaluate("""() => Array.from(document.querySelectorAll(
        '#processor-source-audio, #processor-result-audio, .processor-preview-audio, .processor-track .processor-waveform img, #processor-result-waveform-control img'))
        .map(element => element.src)"""))
    assert visible_urls.issubset(live_urls) and len(live_urls) == 6, live_urls
    select_tracks([])
    assert page.locator("#processor-run").is_disabled()
    probe = page.evaluate("window.processorProbe")
    assert set(probe["urls"]) == set(probe["revoked"]), probe
    assert page.locator(".archive-item").count() == 0
    print("Multi-track cancellation/retry, virtual-FS cleanup, URL revocation, filenames and 390/768/1280 responsive states passed.")


def check_audio_processor(browser, base_url: str, screenshot_dir: Path | None) -> None:
    """UI/asset checks everywhere; real WASM only for the local/PR HTTP server."""
    context = browser.new_context(viewport={"width": 390, "height": 900}, accept_downloads=True)
    requests = []
    errors = []
    context.on("request", lambda request: requests.append((request.method, request.url, request.post_data)))
    site_host = urlparse(base_url).netloc

    def isolate_processor_gateway(route):
        parsed = urlparse(route.request.url)
        if parsed.netloc == site_host and parsed.path.endswith(AUDIO_EDITOR_PATH) and route.request.resource_type == "document":
            response = route.fetch()
            body, replacements = re.subn(r'(<meta name="audio-archive-gateway" content=")[^"]*(">)',
                r'\1\2', response.body().decode("utf-8"), count=1)
            if replacements != 1:
                raise AssertionError("Audio archive gateway hook could not be disabled for the processor smoke")
            route.fulfill(response=response, body=body)
        elif parsed.netloc in {"", site_host}:
            route.continue_()
        else:
            route.abort()

    context.route("**/*", isolate_processor_gateway)
    # Observe native workers and object URLs without replacing the engine or its work.
    context.add_init_script("""(() => {
        window.processorProbe = {workers: 0, terminated: 0, terminatedIds: [], messages: [], urls: [], revoked: [], phases: [], files: {}, logs: []};
        const NativeWorker = window.Worker;
        window.Worker = class extends NativeWorker {
            constructor(...args) {
                super(...args); this.probeId = ++window.processorProbe.workers; this.pending = new Map();
                this.addEventListener('message', ({data}) => {
                    if (data.type === 'LOG') {
                        window.processorProbe.logs.push(data.data.message);
                        if (window.processorProbe.logs.length > 30) window.processorProbe.logs.shift();
                    }
                    const sent = this.pending.get(data.id);
                    if (sent && ['WRITE_FILE', 'READ_FILE'].includes(data.type)) window.processorProbe.files[this.probeId + ':' + sent.path] = true;
                    if (sent && data.type === 'DELETE_FILE') delete window.processorProbe.files[this.probeId + ':' + sent.path];
                    this.pending.delete(data.id);
                });
            }
            postMessage(message, ...args) {
                this.pending.set(message.id, message.data);
                window.processorProbe.messages.push({worker: this.probeId, type: message.type, path: message.data?.path, args: message.data?.args});
                return super.postMessage(message, ...args);
            }
            terminate() {
                window.processorProbe.terminated++;
                window.processorProbe.terminatedIds.push(this.probeId);
                for (const key of Object.keys(window.processorProbe.files)) if (key.startsWith(this.probeId + ':')) delete window.processorProbe.files[key];
                return super.terminate();
            }
        };
        const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL);
        URL.createObjectURL = blob => { const value = create(blob); window.processorProbe.urls.push(value); return value; };
        URL.revokeObjectURL = value => { window.processorProbe.revoked.push(value); return revoke(value); };
        document.addEventListener('DOMContentLoaded', () => {
            const status = document.getElementById('processor-status');
            if (status) new MutationObserver(() => window.processorProbe.phases.push(status.textContent))
                .observe(status, {childList: true, subtree: true});
        });
    })();""")
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        seed_service_access(page, base_url)
        goto_ready(page, url(base_url, AUDIO_EDITOR_PATH))
        page.locator('#processor-heading[data-ready="true"]').wait_for(state='attached')
        wait_for_archive_text(page, "Архив пока пуст.")
        for width in (390, 768, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            if screenshot_dir:
                screenshot_dir.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(screenshot_dir / f"processor-{width}.png"), full_page=True)
        assert not any("/vendor/ffmpeg/" in request_url for _, request_url, _ in requests), "Engine was not lazy"
        assert not errors, errors
        # HEAD only; never transfer/transcode the full core in production Safety.
        for relative in ("ffmpeg/index.js", "ffmpeg/worker.js", "core/ffmpeg-core.js", "core/ffmpeg-core.wasm"):
            response = context.request.head(url(base_url, f"/vendor/ffmpeg/{relative}"))
            assert response.status == 200, (relative, response.status)
            if relative.endswith(".wasm"):
                assert response.headers.get("content-type", "").split(";")[0] == "application/wasm"
        if urlparse(base_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
            print("Production processor UI/module/HEAD asset checks passed; real transcode intentionally skipped.")
            return

        page.locator("#source-session-mode-device").click()
        check_processor_helpers(page)
        primary = wav_payload("fixture.wav", ((1, True), (1, False), (1, True), (3, False), (1, True)))
        page.locator("#processor-file").set_input_files({"name": "not-audio.ogg", "mimeType": "audio/wav", "buffer": b"invalid"})
        wait_processor_status(page, "Поддерживаются файлы MP3, M4A и WAV.")
        assert page.locator("#processor-run").is_disabled()
        # Test the exact oversize UI branch without allocating half a GiB in CI.
        page.evaluate("""() => {
            const input = document.getElementById('processor-file');
            Object.defineProperty(input, 'files', {configurable: true, value: [{name: 'large.wav', size: 500 * 1024 * 1024 + 1}]});
            input.dispatchEvent(new Event('change'));
            delete input.files;
        }""")
        wait_processor_status(page, "Общий размер файлов слишком большой для обработки в браузере. Максимальный размер — 500 МБ.")
        page.evaluate("""() => {
            const input = document.getElementById('processor-file');
            Object.defineProperty(input, 'files', {configurable: true, value: [
                {name: 'a.wav', size: 300 * 1024 * 1024}, {name: 'b.wav', size: 300 * 1024 * 1024}]});
            input.dispatchEvent(new Event('change')); delete input.files;
        }""")
        wait_processor_status(page, "Общий размер файлов слишком большой для обработки в браузере. Максимальный размер — 500 МБ.")
        page.locator("#processor-file").set_input_files([primary, {"name": "unsupported.ogg", "mimeType": "audio/wav", "buffer": b"invalid"}])
        wait_processor_status(page, "Поддерживаются файлы MP3, M4A и WAV.")
        assert page.locator("#processor-run").is_disabled()
        assert not any("/vendor/ffmpeg/" in request_url for method, request_url, _ in requests if method != "HEAD")

        # Valid selection, not page load, is now the lazy boundary. Cancel a pending import.
        held = []
        page.route("**/vendor/ffmpeg/ffmpeg/index.js", lambda route: held.append(route))
        page.locator("#processor-file").set_input_files(primary)
        page.wait_for_function("document.getElementById('processor-status').textContent === 'Подготовка формы сигнала…'")
        assert page.locator("#processor-file").is_disabled() and page.locator("#processor-run").is_disabled()
        assert page.locator('.processor-track button[data-track-action="remove"]').is_disabled()
        assert page.locator("#processor-progress").is_visible()
        page.locator("#processor-cancel").click()
        wait_processor_status(page, "Обработка отменена.")
        assert_processor_no_result(page)
        for route in held:
            route.continue_()
        page.unroute("**/vendor/ffmpeg/ffmpeg/index.js")

        # Also cancel waveform generation with an actual worker awaiting core initialization.
        held_core = []
        context.route("**/vendor/ffmpeg/core/ffmpeg-core.js", lambda route: held_core.append(route))
        with page.expect_worker():
            page.locator("#processor-file").set_input_files(primary)
        page.wait_for_function("window.processorProbe.messages.some(message => message.type === 'LOAD')")
        page.locator("#processor-cancel").click()
        wait_processor_status(page, "Обработка отменена.")
        assert page.evaluate("window.processorProbe.terminated") == 1
        assert_processor_no_result(page)
        for route in held_core:
            route.abort()
        context.unroute("**/vendor/ffmpeg/core/ffmpeg-core.js")

        page.locator("#processor-file").set_input_files(primary)
        wait_waveforms(page, 1)
        waveform = page.locator(".processor-track .processor-waveform img")
        waveform_info = waveform.evaluate("""async image => {
            await image.decode();
            const blob = await (await fetch(image.src)).blob();
            const bytes = new Uint8Array(await blob.arrayBuffer());
            return {size: blob.size, type: blob.type, width: image.naturalWidth, height: image.naturalHeight,
                signature: Array.from(bytes.slice(0, 8))};
        }""")
        assert waveform_info["size"] > 0 and waveform_info["type"] == "image/png", waveform_info
        assert waveform_info["width"] == 4096 and waveform_info["height"] == 100, waveform_info
        assert waveform_info["signature"] == [137, 80, 78, 71, 13, 10, 26, 10], waveform_info
        assert page.locator(".processor-track .processor-waveform").count() == 1
        assert page.locator('.processor-track button[data-track-action="solo"]').get_attribute("aria-pressed") == "false"
        assert page.locator('.processor-track button[data-track-action="mute"]').get_attribute("aria-pressed") == "false"
        assert page.evaluate("window.processorProbe.workers") == 2
        waveform_messages = page.evaluate("window.processorProbe.messages")
        assert any(message["type"] == "EXEC" and any("showwavespic=" in arg for arg in message["args"]) for message in waveform_messages), waveform_messages
        waveform_deletes = [message["path"] for message in waveform_messages if message["type"] == "DELETE_FILE"]
        assert any(path.startswith("processor-waveform-input-") for path in waveform_deletes), waveform_deletes
        assert any(path.startswith("processor-waveform-") and path.endswith(".png") for path in waveform_deletes), waveform_deletes
        assert page.evaluate("window.processorProbe.files") == {}, page.evaluate("window.processorProbe.files")
        print(f"Real waveform passed: WAV -> {waveform_info['width']}x{waveform_info['height']} PNG ({waveform_info['size']} bytes); Blob rendered and waveform FS files deleted.")

        page.locator("#processor-save-incoming").click()
        assert page.locator("#source-session-login-dialog").is_visible()
        assert page.locator("#source-session-login-status").inner_text() == "Шлюз аудиоархива ещё не настроен."
        assert page.locator("#processor-file").evaluate("input => input.files.length") == 1
        assert page.locator(".processor-track__name").inner_text() == "fixture.wav"
        page.locator("#source-session-login-cancel").click()
        print("Gateway-unavailable persistence fallback passed: local S07 source state remained intact.")

        page.locator("#processor-run").click()
        wait_processor_status(page, "Готово.")
        assert page.locator("#source-session-publish-announcement").is_disabled()
        assert "Сначала сохраните исходные записи в аудиоархив" in page.locator("#source-session-publish-reason").inner_text()
        assert page.locator(".processor-track__name").inner_text() == "fixture.wav"
        assert page.locator("#processor-source-audio").evaluate("audio => audio.paused && audio.src.startsWith('blob:')")
        source_duration = float(page.locator("#processor-original-duration").get_attribute("data-value"))
        output_duration = float(page.locator("#processor-processed-duration").get_attribute("data-value"))
        count = int(page.locator("#processor-pause-count").inner_text())
        assert abs(source_duration - 7) < .05 and abs(output_duration - 4.35) < .12 and count == 1
        assert abs(float(page.locator("#processor-removed-duration").get_attribute("data-value")) - 2.65) < .12
        assert page.locator("#processor-result-audio").evaluate("audio => audio.paused && audio.src.startsWith('blob:')")
        assert page.locator("#processor-result-waveform-control img").count() == 1
        result_waveform_info = page.locator("#processor-result-waveform-control img").evaluate("""async image => {
            await image.decode(); const blob = await (await fetch(image.src)).blob();
            return {size: blob.size, type: blob.type, width: image.naturalWidth, height: image.naturalHeight};
        }""")
        assert result_waveform_info["size"] > 0 and result_waveform_info["type"] == "image/png", result_waveform_info
        assert result_waveform_info["width"] == 4096 and result_waveform_info["height"] == 100, result_waveform_info
        source_time_before_result = page.locator("#processor-source-audio").evaluate("audio => { audio.currentTime = 1; return audio.currentTime; }")
        source_width_before_result_zoom = page.locator(".processor-track .processor-waveform").evaluate("item => item.offsetWidth")
        page.locator("#processor-result-zoom-range").evaluate("input => { input.value = 100; input.dispatchEvent(new Event('input', {bubbles: true})); }")
        assert page.locator("#processor-result-waveform-control").evaluate("item => item.offsetWidth <= item.querySelector('img').naturalWidth")
        assert page.locator(".processor-track .processor-waveform").evaluate("item => item.offsetWidth") == source_width_before_result_zoom
        result_waveform = page.locator("#processor-result-waveform-control")
        # At the new 4096px native envelope, 90px is less than 0.2s.
        # Keep a meaningful visible seek and check its exact scaled time too.
        result_click_x = 300
        result_waveform.click(position={"x": result_click_x, "y": 50})
        result_click_time = page.locator("#processor-result-audio").evaluate("audio => audio.currentTime")
        expected_result_time = result_waveform.evaluate('(e,x)=>x/e.offsetWidth*document.getElementById("processor-result-audio").duration', result_click_x)
        assert abs(result_click_time - expected_result_time) < .02, (result_click_time, expected_result_time)
        assert result_click_time > .2, page.evaluate("""() => ({time: document.getElementById('processor-result-audio').currentTime,
            duration: document.getElementById('processor-result-audio').duration,
            width: document.getElementById('processor-result-waveform-control').offsetWidth,
            scroll: document.getElementById('processor-result-waveform-scroll').scrollLeft})""")
        assert abs(page.locator("#processor-source-audio").evaluate("audio => audio.currentTime") - source_time_before_result) < .1
        result_waveform.focus()
        result_waveform.press("Home")
        assert page.locator("#processor-result-audio").evaluate("audio => audio.currentTime < .1")
        result_waveform.press("End")
        assert page.locator("#processor-result-audio").evaluate("audio => Math.abs(audio.currentTime - audio.duration) < .1")
        result_scroll = page.locator("#processor-result-waveform-scroll")
        page.evaluate("""() => { document.getElementById('processor-result-waveform-scroll').scrollLeft = 100;
            document.getElementById('processor-result-audio').currentTime = 1; }""")
        result_scroll_box = result_scroll.bounding_box()
        assert result_scroll_box
        result_scroll.hover(position={"x": result_scroll_box["width"] * .7, "y": 50})
        page.mouse.down()
        page.mouse.move(result_scroll_box["x"] + result_scroll_box["width"] * .35, result_scroll_box["y"] + 50, steps=5)
        page.mouse.up()
        assert page.locator("#processor-result-audio").evaluate("audio => Math.abs(audio.currentTime - 1) < .15")
        result_independent_before = page.evaluate("""() => ({
            time: document.getElementById('processor-result-audio').currentTime,
            scroll: document.getElementById('processor-result-waveform-scroll').scrollLeft,
            width: document.getElementById('processor-result-waveform-control').offsetWidth,
            zoom: document.getElementById('processor-result-zoom-range').value
        })""")
        page.locator("#processor-source-follow").click()
        page.locator("#processor-source-zoom-range").evaluate(
            "input => { input.value = 100; input.dispatchEvent(new Event('input', {bubbles: true})); }")
        # Force actual detail decoding, so engine-reuse checks cannot pass
        # only because its debounced worker has not started on a fast runner.
        page.wait_for_function("document.querySelector('.processor-waveform-detail').dataset.waveDetail === 'ready'", timeout=60000)
        source_rail = page.locator("#processor-source-scrollbar").bounding_box()
        page.mouse.click(source_rail["x"] + source_rail["width"] * .65, source_rail["y"] + source_rail["height"] / 2)
        result_independent_after = page.evaluate("""() => ({
            time: document.getElementById('processor-result-audio').currentTime,
            scroll: document.getElementById('processor-result-waveform-scroll').scrollLeft,
            width: document.getElementById('processor-result-waveform-control').offsetWidth,
            zoom: document.getElementById('processor-result-zoom-range').value
        })""")
        assert result_independent_after == result_independent_before, (result_independent_before, result_independent_after)
        assert page.locator("#processor-result").get_by_role("button", name="Следовать за воспроизведением").count() == 0
        result_info = page.evaluate("""async () => {
            const response = await fetch(document.getElementById('processor-download').href);
            const blob = await response.blob();
            const bytes = await blob.arrayBuffer();
            const raw = new Uint8Array(bytes);
            const frame = 10 + ((raw[6] & 127) * 2097152 + (raw[7] & 127) * 16384 + (raw[8] & 127) * 128 + (raw[9] & 127));
            const headerRate = [44100, 48000, 32000][(raw[frame + 2] >> 2) & 3];
            const headerBitrate = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320][raw[frame + 2] >> 4];
            const audioContext = new AudioContext({sampleRate: 44100});
            try {
                const decoded = await audioContext.decodeAudioData(bytes.slice(0));
                const samples = decoded.getChannelData(0);
                const rms = (start, end) => {
                    const first = Math.floor(start * decoded.sampleRate), last = Math.floor(end * decoded.sampleRate);
                    let sum = 0; for (let i = first; i < last; i++) sum += samples[i] ** 2;
                    return Math.sqrt(sum / (last - first));
                };
                return {size: blob.size, type: blob.type, prefix: Array.from(new Uint8Array(bytes).slice(0, 3)),
                    sampleRate: headerRate, bitrate: headerBitrate, channels: decoded.numberOfChannels,
                    shortPauseRms: rms(1.1, 1.9), middleToneRms: rms(2.1, 2.8), lastToneRms: rms(3.5, 4.1)};
            } finally { await audioContext.close(); }
        }""")
        assert result_info["size"] > 0 and result_info["type"] == "audio/mpeg" and result_info["prefix"] == [73, 68, 51], result_info
        assert result_info["sampleRate"] == 44100 and result_info["bitrate"] == 128 and result_info["channels"] == 1, result_info
        assert result_info["shortPauseRms"] < .005 and result_info["middleToneRms"] > .1 and result_info["lastToneRms"] > .1, result_info
        with page.expect_download() as download_event:
            page.locator("#processor-download").click()
        download = download_event.value
        assert download.suggested_filename == "fixture-edited.mp3" and download.failure() is None
        assert page.locator(".archive-item").count() == 0
        probe = page.evaluate("window.processorProbe")
        processing_workers = {message["worker"] for message in probe["messages"]
                              if message["type"] == "WRITE_FILE" and message["path"].startswith("processor-input-")}
        assert len(processing_workers) == 1, processing_workers
        processing_worker = next(iter(processing_workers))
        assert processing_worker not in probe["terminatedIds"], probe
        for phase in ("Подготовка формы сигнала…", "Подготовка обработчика…", "Поиск длинных пауз…", "Сокращение пауз и создание MP3…", "Готово."):
            assert phase in probe["phases"], probe
        assert any("/core/ffmpeg-core.wasm" in request_url for method, request_url, _ in requests if method == "GET")
        for path in ("processor-input-0", "processor-output.mp3", "processor-result-waveform.png", "processor-analysis.txt", "processor-filter.txt"):
            assert any(message["type"] == "DELETE_FILE" and message["path"] == path for message in probe["messages"]), probe
        print(f"Real FFmpeg fixture passed: input={source_duration:.6f}s output={output_duration:.6f}s shortened={count}; MP3={result_info['size']} bytes; short pause preserved.")
        page.evaluate("document.activeElement.blur(); window.scrollTo(0, 0)")
        page.mouse.move(0, 0)
        for width in (390, 768, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
            assert page.locator("#processor-source-audio").is_hidden()
            for selector in ("#processor-source-audio-play", "#processor-source-audio-stop", "#announcement-processor-card .daw-monitor-volume", "#processor-result-audio", "#processor-download"):
                box = page.locator(selector).bounding_box()
                assert box and box["x"] >= 0 and box["x"] + box["width"] <= width + 1, (selector, box)
            if screenshot_dir:
                page.screenshot(path=str(screenshot_dir / f"processor-result-{width}.png"), full_page=True)
        # Fail only waveform Blob publication after real FFmpeg generation; processing must remain available.
        page.evaluate("""() => {
            const original = URL.createObjectURL;
            URL.createObjectURL = blob => {
                if (blob.type === 'image/png') {
                    URL.createObjectURL = original;
                    throw new Error('one-shot waveform preview failure');
                }
                return original(blob);
            };
        }""")
        page.locator("#processor-file").set_input_files(primary)
        wait_waveforms(page, 1, failures=1)
        assert page.get_by_text("Не удалось построить форму сигнала.", exact=True).count() == 1
        assert page.locator("#processor-source-audio").evaluate("audio => audio.paused && audio.src.startsWith('blob:')")
        page.evaluate("""() => {
            const original = URL.createObjectURL;
            URL.createObjectURL = blob => {
                if (blob.type === 'image/png') {
                    URL.createObjectURL = original;
                    throw new Error('one-shot result waveform preview failure');
                }
                return original(blob);
            };
        }""")
        page.locator("#processor-run").click()
        wait_processor_status(page, "Готово.")
        assert page.locator("#processor-result").is_visible()
        assert page.locator("#processor-result-waveform-status").inner_text() == "Не удалось построить форму сигнала."
        assert page.locator("#processor-result-waveform-status").is_visible()
        assert page.locator("#processor-result-audio").evaluate("audio => audio.src.startsWith('blob:')")
        assert page.locator("#processor-download").get_attribute("href").startswith("blob:")
        print("Waveform failure fallbacks passed: source and result preview failures retained native playback and a valid processed MP3.")

        prior_urls = page.evaluate("window.processorProbe.urls.slice()")
        no_pause = wav_payload("no-pauses.WAV", ((1, True), (1, False), (1, True)), comment="silence_start: 0")
        page.locator("#processor-file").set_input_files(no_pause)
        wait_waveforms(page, 1)
        exec_before = len([message for message in page.evaluate("window.processorProbe.messages") if message["type"] == "EXEC" and message["worker"] == processing_worker])
        assert_processor_no_result(page)
        revoked = page.evaluate("window.processorProbe.revoked")
        assert all(value in revoked for value in prior_urls), (prior_urls, revoked)
        page.locator("#processor-run").click()
        wait_processor_status(page, "Длинные паузы не найдены. Файл не изменён.")
        assert page.locator("#processor-result").is_visible()
        assert page.locator("#processor-download").get_attribute("download") == "no-pauses.WAV"
        assert page.locator("#processor-download").inner_text() == "Скачать исходный файл без изменений"
        passthrough_bytes = page.evaluate("""async () => Array.from(new Uint8Array(
            await (await fetch(document.getElementById('processor-download').href)).arrayBuffer()))""")
        assert bytes(passthrough_bytes) == no_pause["buffer"]
        probe = page.evaluate("window.processorProbe")
        assert {message["worker"] for message in probe["messages"]
                if message["type"] == "WRITE_FILE" and message["path"].startswith("processor-input-")} == {processing_worker}, probe
        assert processing_worker not in probe["terminatedIds"], probe
        assert len([message for message in probe["messages"] if message["type"] == "EXEC" and message["worker"] == processing_worker]) >= exec_before + 1
        assert "processor-output.mp3" not in probe["files"]
        print("No-long-pause fixture passed: exact-byte passthrough result/download, no output encode; loaded engine reused; metadata cannot spoof detector output.")

        # Cancel once the real worker has started analysis; the next run must recreate it.
        page.locator("#processor-file").set_input_files(primary)
        wait_waveforms(page, 1)
        page.evaluate("""() => {
            const status = document.getElementById('processor-status');
            const observer = new MutationObserver(() => {
                if (status.textContent === 'Поиск длинных пауз…') {
                    observer.disconnect(); document.getElementById('processor-cancel').click();
                }
            });
            observer.observe(status, {childList: true});
        }""")
        page.locator("#processor-run").click()
        wait_processor_status(page, "Обработка отменена.")
        assert_processor_no_result(page)
        assert page.evaluate("window.processorProbe.terminatedIds").count(processing_worker) == 1
        assert page.locator("#processor-source-audio").get_attribute("src").startswith("blob:")
        page.locator("#processor-run").click()
        wait_processor_status(page, "Готово.")
        retried = page.evaluate("window.processorProbe")
        replacement_workers = {message["worker"] for message in retried["messages"]
                               if message["type"] == "WRITE_FILE" and message["path"].startswith("processor-input-")} - {processing_worker}
        assert len(replacement_workers) == 1, retried
        assert not replacement_workers.intersection(retried["terminatedIds"]), retried

        # Real leading/trailing EOF handling and stereo preservation, plus a Unicode filename.
        page.locator("#processor-file").set_input_files(wav_payload("Спикерское.wav", ((3, False), (1, True), (3, False)), channels=2))
        wait_waveforms(page, 1)
        page.locator("#processor-run").click()
        wait_processor_status(page, "Готово.")
        assert page.locator("#processor-pause-count").inner_text() == "2"
        edge_duration = float(page.locator("#processor-processed-duration").get_attribute("data-value"))
        assert abs(edge_duration - 1.7) < .12, edge_duration
        assert page.locator("#processor-download").get_attribute("download") == "Спикерское-edited.mp3"
        assert page.evaluate("""async () => {
            const audioContext = new AudioContext();
            try {
                const buffer = await (await fetch(document.getElementById('processor-download').href)).arrayBuffer();
                return (await audioContext.decodeAudioData(buffer)).numberOfChannels === 2;
            } finally { await audioContext.close(); }
        }""")
        print(f"Real boundary fixture passed: leading/trailing silence, output={edge_duration:.6f}s, shortened=2; cancel/retry passed.")
        # Decoder failure must clean stale results and re-enable the UI.
        page.locator("#processor-file").set_input_files({"name": "broken.wav", "mimeType": "audio/wav", "buffer": b"not a wav"})
        wait_waveforms(page, 1, failures=1)
        page.locator("#processor-run").click()
        wait_processor_status(page, "Не удалось прочитать аудио. Проверьте исходный файл.")
        assert_processor_no_result(page)
        assert not page.locator("#processor-run").is_disabled()
        long_name = "Очень-длинное-название-спикерского-" * 6 + ".wav"
        page.locator("#processor-file").set_input_files(wav_payload(long_name, ((.1, True),)))
        wait_waveforms(page, 1)
        for width in (390, 768, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
            assert not page.locator("#processor-file-info").evaluate("el => el.scrollWidth > el.clientWidth")
        check_multi_track_processor(page, screenshot_dir)
        assert not errors, errors
        assert all(method in {"GET", "HEAD"} and body is None for method, _, body in requests), requests
        assert all(urlparse(request_url).netloc in {"", site_host} for _, request_url, _ in requests), requests
        assert page.locator(".archive-item").count() == 0
        goto_ready(page, url(base_url, "/Admin-panel.html"))
    finally:
        context.close()

    unsupported_context = browser.new_context()
    unsupported_context.route("**/*", isolate_processor_gateway)
    unsupported_context.add_init_script("Object.defineProperty(window, 'WebAssembly', {value: undefined})")
    unsupported_page = unsupported_context.new_page()
    try:
        seed_service_access(unsupported_page, base_url)
        unsupported_page.route(ARCHIVE_MANIFEST_PATTERN, fixture_manifest_route)
        goto_ready(unsupported_page, url(base_url, AUDIO_EDITOR_PATH))
        unsupported_page.locator("#source-session-mode-device").click()
        unsupported_page.get_by_text("Обработка аудио не поддерживается в этом браузере.", exact=True).wait_for()
        wait_for_archive_items(unsupported_page, 3)
        assert unsupported_page.locator("#processor-run").is_disabled()
        unsupported_page.locator("#archive-search").fill("Альфа")
        assert unsupported_page.locator(".archive-item").count() == 1
        print("Unsupported-browser processor fallback passed; archive remains functional.")
    finally:
        unsupported_context.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--screenshot-dir", type=Path)
    parser.add_argument("--delayed-stylesheet-check", action="store_true")
    parser.add_argument("--browser", choices=("chromium", "webkit"), default="chromium")
    parser.add_argument("--literature-only", action="store_true")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    site_host = urlparse(base_url).netloc
    with sync_playwright() as playwright:
        browser = getattr(playwright, args.browser).launch()
        if args.literature_only:
            device_name = "iPhone 13" if args.browser == "webkit" else "Pixel 7"
            check_literature_mobile_compatibility(
                browser, base_url, playwright.devices[device_name],
                f"{args.browser} {device_name} compatibility",
            )
            browser.close()
            print(f"Literature compatibility suite passed in {args.browser} ({device_name}).")
            return 0
        if args.browser != "chromium":
            raise AssertionError("The full Safety Baseline is defined for Chromium; use --literature-only with WebKit")
        context = browser.new_context(viewport={"width": 1280, "height": 900})

        def block_external(route):
            if urlparse(route.request.url).netloc not in {"", site_host}:
                route.abort()
            else:
                route.continue_()

        context.route("**/*", block_external)
        page = context.new_page()
        goto_ready(page, url(base_url, "/"))
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
        if not desktop_service.is_visible():
            raise AssertionError("desktop service control is not visible after stylesheet readiness")
        desktop_heading_box = page.get_by_role("heading", name="Проект Мэсэр", level=1).bounding_box()
        desktop_header_box = page.locator(".site-header__content").bounding_box()
        desktop_service_box = desktop_service.bounding_box()
        desktop_center_delta = (abs((desktop_heading_box["x"] + desktop_heading_box["width"] / 2) -
                                    (desktop_header_box["x"] + desktop_header_box["width"] / 2))
                                if desktop_heading_box and desktop_header_box else None)
        if (not desktop_heading_box or not desktop_header_box or
                desktop_center_delta > 2):
            raise AssertionError(
                f"desktop H1 is no longer visibly centered in the header: "
                f"center delta={desktop_center_delta}, heading={desktop_heading_box}, header={desktop_header_box}"
            )
        desktop_service_style = desktop_service.evaluate("""el => {
            const style = getComputedStyle(el);
            return {
                display: style.display,
                flexDirection: style.flexDirection,
                whiteSpace: style.whiteSpace,
                textDecorationLine: style.textDecorationLine,
                backgroundColor: style.backgroundColor,
                minHeight: parseFloat(style.minHeight),
                hasOverflow: el.scrollWidth > el.clientWidth || el.scrollHeight > el.clientHeight,
            };
        }""")
        desktop_controls_overlap = (desktop_heading_box and desktop_service_box and
                                    desktop_heading_box["x"] < desktop_service_box["x"] + desktop_service_box["width"] and
                                    desktop_service_box["x"] < desktop_heading_box["x"] + desktop_heading_box["width"] and
                                    desktop_heading_box["y"] < desktop_service_box["y"] + desktop_service_box["height"] and
                                    desktop_service_box["y"] < desktop_heading_box["y"] + desktop_heading_box["height"])
        if (desktop_service_style["display"] not in {"inline-flex", "flex"} or
                desktop_service_style["flexDirection"] != "row" or
                desktop_service_style["whiteSpace"] != "nowrap" or
                desktop_service_style["textDecorationLine"] != "none" or
                desktop_service_style["backgroundColor"] == "rgba(0, 0, 0, 0)" or
                desktop_service_style["minHeight"] < 44 or
                desktop_service_style["hasOverflow"] or desktop_controls_overlap):
            raise AssertionError(
                f"desktop service control lacks its compact treatment: style={desktop_service_style}, "
                f"service={desktop_service_box}, heading={desktop_heading_box}, overlap={desktop_controls_overlap}"
            )
        desktop_actions = page.locator(".resource-action")
        if desktop_actions.count() != 8:
            raise AssertionError("desktop homepage must retain eight resource actions")
        if [visible_text(desktop_actions.nth(index)) for index in range(desktop_actions.count())] != list(HOMEPAGE_ACTION_ORDER):
            raise AssertionError("homepage resource actions are not in canonical DOM order")
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
            goto_ready(mobile, url(base_url, "/"))
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
            control_center = service_box["x"] + service_box["width"] / 2
            if any(abs((line["x"] + line["width"] / 2) - control_center) > 2 for line in line_boxes):
                line_centers = [(line["x"] + line["width"] / 2) for line in line_boxes]
                raise AssertionError(
                    f"service link lines are not centered in the control at {width}px: "
                    f"control center={control_center:.2f}, line centers={line_centers}, box={service_box}"
                )
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
        wait_for_page_ready(mobile)
        mobile.close()

        for width in (320, 390, 768, 1280):
            check_literature(page, base_url, width)
        for label, href, reader_title in LITERATURE_ACTIONS[:6]:
            document_id = href.split("doc=", 1)[1]
            check_literature_reader(page, base_url, document_id, reader_title, 390)
        for document_id, reader_title in (("ip07", "Зависимый ли я?"),):
            for width in (320, 768, 1280):
                check_literature_reader(page, base_url, document_id, reader_title, width)
        check_literature_reader_resize_stability(page, base_url, "ip16", "Новичку")
        check_literature_reader_error(page, base_url)
        for width in (320, 390, 768, 1280):
            check_audiobook(page, base_url, width)
        click_viewport_link(page, "./", "/")
        goto_ready(page, url(base_url, "/Literature.html"))
        click_viewport_link(page, "Admin-panel.html", "/Admin-panel.html")

        goto_ready(page, url(base_url, "/About.html"))
        page.wait_for_url(base_url + "/", timeout=10000)
        wait_for_page_ready(page)

        for width in (320, 390, 768, 1280):
            check_offline_meetings(page, base_url, width)
        check_offline_meetings_failure(browser, base_url)
        for width in (320, 390, 768, 1280):
            check_calculator(page, base_url, width)

        goto_ready(page, url(base_url, "/AudioBook.html"))
        frame = page.frame_locator('iframe[src="bt6-player.html"]')
        frame.locator("#playlist li").nth(1).wait_for(timeout=10000)
        frame.locator("#playlist li").nth(1).click()
        source = frame.locator("#audio").get_attribute("src")
        if not source or not source.endswith("audio/bt6/bt6_002.mp3"):
            raise AssertionError(f"second audio track did not set expected source: {source}")

        for width in (320, 390, 768, 1280):
            check_admin_login(page, base_url, width)
            check_service_landing(page, base_url, width)
        check_admin_hash_functions(page, base_url)
        check_admin_without_subtle_crypto(browser, base_url)
        check_service_access_journeys(page, base_url)
        check_archive_management(browser, base_url, args.screenshot_dir)
        check_archive_management_cors(browser)
        from s09a_smoke import check_s09a
        check_s09a(browser, base_url, args.screenshot_dir)
        from s09a_acceptance_smoke import check_s09a_acceptance
        check_s09a_acceptance(browser, base_url, args.screenshot_dir)
        from s09a_editor_corrective_smoke import check_s09a_editor_corrective
        check_s09a_editor_corrective(browser, base_url, args.screenshot_dir)
        check_s09a_editor_corrective(browser, base_url, args.screenshot_dir, device_scale_factor=2)
        from s09a_playback_signal_smoke import check_playback_signal
        check_playback_signal(browser, base_url, args.screenshot_dir)
        from s09a_timeline_smoke import check_timeline_controls
        check_timeline_controls(browser, base_url, args.screenshot_dir)
        from s09a_corrective_management_smoke import check_s09a_corrective_management
        check_s09a_corrective_management(browser, base_url, args.screenshot_dir)
        check_audio_editor(page, base_url)
        check_source_session_archive(browser, base_url, args.screenshot_dir)
        check_audio_processor(browser, base_url, args.screenshot_dir)
        if page.evaluate(f"sessionStorage.getItem('{SERVICE_SESSION_KEY}')") is not None:
            raise AssertionError("Calendar and Drive regression checks must run without an admin marker")

        for width in (320, 390, 768, 1280):
            check_calendar(page, base_url, width)
        check_calendar_mode_transition(page, base_url)

        for width in (320, 390, 768, 1280):
            check_google_drive(page, base_url, width)
        if args.screenshot_dir:
            capture_screenshots(page, base_url, args.screenshot_dir)
        context.close()
        check_literature_mobile_compatibility(
            browser, base_url, playwright.devices["Pixel 7"], "Chromium Android mobile emulation"
        )
        check_literature_reader_diagnostics(browser, base_url)
        if args.delayed_stylesheet_check:
            check_delayed_stylesheet_readiness(browser, base_url)
        browser.close()
    print("Browser smoke suite passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, Error) as exc:
        print(f"BROWSER SMOKE FAILED: {exc}", file=sys.stderr)
        traceback.print_exc()
        raise SystemExit(1)
