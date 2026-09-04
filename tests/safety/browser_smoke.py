#!/usr/bin/env python3
"""Small browser smoke suite for the public static site."""

from __future__ import annotations

import argparse
import io
import json
import math
import re
import struct
import sys
import time
import wave
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import Error, sync_playwright


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
    )
    if actions.count() != len(expected):
        raise AssertionError(f"Service landing must have three actions at {width}px")
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
    if width > 576 and any(abs(box["y"] - boxes[0]["y"]) > 1 for box in boxes[1:]):
        raise AssertionError(f"Service landing desktop actions are not balanced in one row at {width}px: {boxes}")
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
    if page.locator("h2").all_text_contents() != ["Обработка аудио", "Архив отредактированных аудио"]:
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
    page.locator('#processor-heading[data-ready="true"]').wait_for()
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
    file_input = page.locator("#processor-file")
    file_input.focus()
    page.keyboard.press("Shift+Tab")
    page.keyboard.press("Tab")
    if not file_input.evaluate("element => document.activeElement === element"):
        raise AssertionError(f"Processor file input is not keyboard accessible at {width}px")
    for selector in (".processor-card", ".archive-card:not(.processor-card)", "#processor-file", "#processor-run", "#archive-controls", "#archive-audio"):
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
        for width in (390, 768, 1280):
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


def wav_payload(name: str, segments: tuple[tuple[float, bool], ...], channels: int = 1) -> dict:
    """Generate PCM in memory; never commit or serve an audio test fixture."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setparams((channels, 2, 44100, 0, "NONE", "not compressed"))
        for duration, audible in segments:
            frames = b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * 440 * n / 44100)) if audible else 0) * channels
                              for n in range(round(duration * 44100)))
            wav.writeframes(frames)
    # Empty MIME intentionally proves extension-based validation.
    return {"name": name, "mimeType": "", "buffer": buffer.getvalue()}


def wait_processor_status(page, text: str) -> None:
    page.wait_for_function("text => document.getElementById('processor-status').textContent === text", arg=text, timeout=180000)
    page.wait_for_function("!document.getElementById('processor-file').disabled", timeout=30000)


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
            filter: m.makeFilter([[3.175, 5.825]])
        };
    }""")
    assert result["boundaries"] == [[0, 2.65], [4.175, 6.825], [8.35, 10]], result
    assert result["allSilent"] == [[.35, 10]], result
    assert result["eof"] == [[7, 10]] and result["short"] == [] and result["exact"] == [[1, 3]], result
    assert result["clamped"] == [[0, 4], [8, 10]] and result["invalid"] == [] and result["unknownDuration"] == [], result
    assert result["merged"] == [[1, 6]] and result["formats"] == ["", "", ""], result
    assert result["oversize"] == "Файл слишком большой для обработки в браузере. Максимальный размер — 500 МБ.", result
    assert "gte(t,3.175000)*lt(t,5.825000)" in result["filter"], result


def check_audio_processor(browser, base_url: str, screenshot_dir: Path | None) -> None:
    """UI/asset checks everywhere; real WASM only for the local/PR HTTP server."""
    context = browser.new_context(viewport={"width": 390, "height": 900}, accept_downloads=True)
    requests = []
    errors = []
    context.on("request", lambda request: requests.append((request.method, request.url, request.post_data)))
    site_host = urlparse(base_url).netloc
    context.route("**/*", lambda route: route.continue_() if urlparse(route.request.url).netloc in {"", site_host} else route.abort())
    # Observe native workers and object URLs without replacing the engine or its work.
    context.add_init_script("""(() => {
        window.processorProbe = {workers: 0, terminated: 0, messages: [], urls: [], revoked: [], phases: []};
        const NativeWorker = window.Worker;
        window.Worker = class extends NativeWorker {
            constructor(...args) { super(...args); window.processorProbe.workers++; }
            postMessage(message, ...args) {
                window.processorProbe.messages.push({type: message.type, path: message.data?.path, args: message.data?.args});
                return super.postMessage(message, ...args);
            }
            terminate() { window.processorProbe.terminated++; return super.terminate(); }
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
        page.locator('#processor-heading[data-ready="true"]').wait_for()
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
        wait_processor_status(page, "Файл слишком большой для обработки в браузере. Максимальный размер — 500 МБ.")
        assert not any("/vendor/ffmpeg/" in request_url for method, request_url, _ in requests if method != "HEAD")

        # Cancel a genuinely pending lazy import; release its request only after cancellation.
        held = []
        page.route("**/vendor/ffmpeg/ffmpeg/index.js", lambda route: held.append(route))
        page.locator("#processor-file").set_input_files(primary)
        page.locator("#processor-run").click()
        page.wait_for_function("document.getElementById('processor-status').textContent === 'Подготовка обработчика…'")
        assert page.locator("#processor-file").is_disabled() and page.locator("#processor-run").is_disabled()
        assert page.locator("#processor-progress").is_visible()
        page.locator("#processor-cancel").click()
        wait_processor_status(page, "Обработка отменена.")
        assert_processor_no_result(page)
        for route in held:
            route.continue_()
        page.unroute("**/vendor/ffmpeg/ffmpeg/index.js")

        # Also cancel with an actual FFmpeg worker awaiting core initialization.
        held_core = []
        context.route("**/vendor/ffmpeg/core/ffmpeg-core.js", lambda route: held_core.append(route))
        with page.expect_worker():
            page.locator("#processor-run").click()
        page.wait_for_function("window.processorProbe.messages.some(message => message.type === 'LOAD')")
        page.locator("#processor-cancel").click()
        wait_processor_status(page, "Обработка отменена.")
        assert page.evaluate("window.processorProbe.terminated") == 1
        assert_processor_no_result(page)
        for route in held_core:
            route.abort()
        context.unroute("**/vendor/ffmpeg/core/ffmpeg-core.js")

        page.locator("#processor-run").click()
        wait_processor_status(page, "Готово.")
        assert page.locator("#processor-file-info").inner_text().startswith("fixture.wav · ")
        assert page.locator("#processor-source-audio").evaluate("audio => audio.paused && audio.src.startsWith('blob:')")
        source_duration = float(page.locator("#processor-original-duration").get_attribute("data-value"))
        output_duration = float(page.locator("#processor-processed-duration").get_attribute("data-value"))
        count = int(page.locator("#processor-pause-count").inner_text())
        assert abs(source_duration - 7) < .05 and abs(output_duration - 4.35) < .12 and count == 1
        assert abs(float(page.locator("#processor-removed-duration").get_attribute("data-value")) - 2.65) < .12
        assert page.locator("#processor-result-audio").evaluate("audio => audio.paused && audio.src.startsWith('blob:')")
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
        assert probe["workers"] == 2, probe
        for phase in ("Подготовка обработчика…", "Поиск длинных пауз…", "Сокращение пауз и создание MP3…", "Готово."):
            assert phase in probe["phases"], probe
        assert any("/core/ffmpeg-core.wasm" in request_url for method, request_url, _ in requests if method == "GET")
        for path in ("processor-input", "processor-output.mp3", "processor-analysis.txt", "processor-filter.txt"):
            assert any(message["type"] == "DELETE_FILE" and message["path"] == path for message in probe["messages"]), probe
        print(f"Real FFmpeg fixture passed: input={source_duration:.6f}s output={output_duration:.6f}s shortened={count}; MP3={result_info['size']} bytes; short pause preserved.")
        page.evaluate("document.activeElement.blur(); window.scrollTo(0, 0)")
        page.mouse.move(0, 0)
        for width in (390, 768, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
            for selector in ("#processor-source-audio", "#processor-result-audio", "#processor-download"):
                box = page.locator(selector).bounding_box()
                assert box and box["x"] >= 0 and box["x"] + box["width"] <= width + 1, (selector, box)
            if screenshot_dir:
                page.screenshot(path=str(screenshot_dir / f"processor-result-{width}.png"), full_page=True)
        prior_urls = page.evaluate("window.processorProbe.urls.slice()")
        exec_before = len([message for message in probe["messages"] if message["type"] == "EXEC"])
        page.locator("#processor-file").set_input_files(wav_payload("no-pauses.WAV", ((.5, True), (.5, False), (.5, True))))
        assert_processor_no_result(page)
        revoked = page.evaluate("window.processorProbe.revoked")
        assert all(value in revoked for value in prior_urls), (prior_urls, revoked)
        page.locator("#processor-run").click()
        wait_processor_status(page, "Длинные паузы не найдены. Файл не изменён.")
        assert_processor_no_result(page)
        probe = page.evaluate("window.processorProbe")
        assert probe["workers"] == 2 and len([message for message in probe["messages"] if message["type"] == "EXEC"]) == exec_before + 1
        print("No-long-pause fixture passed: exact unchanged status, analysis only, no re-encode/result/download; loaded engine reused.")

        # Cancel once the real worker has started analysis; the next run must recreate it.
        page.locator("#processor-file").set_input_files(primary)
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
        assert page.evaluate("window.processorProbe.terminated") == 2
        assert page.locator("#processor-source-audio").get_attribute("src").startswith("blob:")
        page.locator("#processor-run").click()
        wait_processor_status(page, "Готово.")
        assert page.evaluate("window.processorProbe.workers") == 3

        # Real leading/trailing EOF handling and stereo preservation, plus a Unicode filename.
        page.locator("#processor-file").set_input_files(wav_payload("Спикерское.wav", ((3, False), (1, True), (3, False)), channels=2))
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
        page.locator("#processor-run").click()
        wait_processor_status(page, "Не удалось прочитать аудио. Проверьте исходный файл.")
        assert_processor_no_result(page)
        assert not page.locator("#processor-run").is_disabled()
        long_name = "Очень-длинное-название-спикерского-" * 6 + ".wav"
        page.locator("#processor-file").set_input_files(wav_payload(long_name, ((.1, True),)))
        for width in (390, 768, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
            assert not page.locator("#processor-file-info").evaluate("el => el.scrollWidth > el.clientWidth")
        assert not errors, errors
        assert all(method in {"GET", "HEAD"} and body is None for method, _, body in requests), requests
        assert all(urlparse(request_url).netloc in {"", site_host} for _, request_url, _ in requests), requests
        assert page.locator(".archive-item").count() == 0
        goto_ready(page, url(base_url, "/Admin-panel.html"))
    finally:
        context.close()

    unsupported_context = browser.new_context()
    unsupported_context.add_init_script("Object.defineProperty(window, 'WebAssembly', {value: undefined})")
    unsupported_page = unsupported_context.new_page()
    try:
        seed_service_access(unsupported_page, base_url)
        unsupported_page.route(ARCHIVE_MANIFEST_PATTERN, fixture_manifest_route)
        goto_ready(unsupported_page, url(base_url, AUDIO_EDITOR_PATH))
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
        check_audio_editor(page, base_url)
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
        raise SystemExit(1)
