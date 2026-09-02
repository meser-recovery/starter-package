#!/usr/bin/env python3
"""Small browser smoke suite for the public static site."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

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
    modal = page.locator("#cp-modal")
    if modal.get_attribute("aria-hidden") != "true" or modal.is_visible():
        raise AssertionError("Calculator modal must be initially hidden")
    page.locator("#cp-openPicker").click()
    if modal.get_attribute("aria-hidden") != "false" or not modal.is_visible():
        raise AssertionError("Calculator modal did not open")
    page.wait_for_function("document.activeElement && document.activeElement.id === 'cp-closeModal'")
    page.keyboard.press("Escape")
    if modal.get_attribute("aria-hidden") != "true" or modal.is_visible():
        raise AssertionError("Calculator modal did not close with Escape")
    page.wait_for_function("document.activeElement && document.activeElement.id === 'cp-openPicker'")
    page.locator("#cp-openPicker").click()
    page.locator("#cp-closeBackdrop").click(position={"x": 2, "y": 2})
    if modal.get_attribute("aria-hidden") != "true" or modal.is_visible():
        raise AssertionError("Calculator modal did not close from its backdrop")
    page.locator("#cp-openPicker").click()
    page.locator("#cp-today").click()
    page.wait_for_function("""() => {
        const today = new Date();
        const expected = [String(today.getFullYear()), String(today.getMonth() + 1), String(today.getDate())];
        const selected = ['cp-wheel-year', 'cp-wheel-month', 'cp-wheel-day'].map((id) =>
            document.querySelector(`#${id} .cp-wheel-item.is-active`)?.dataset.value || '');
        return selected.every((value, index) => value === expected[index]);
    }""")
    wheel_values = page.evaluate("""() => {
        const today = new Date();
        return {
        today: [today.getFullYear(), today.getMonth() + 1, today.getDate()].join('-'),
        selected: ['cp-wheel-year', 'cp-wheel-month', 'cp-wheel-day'].map((id) =>
            document.querySelector(`#${id} .cp-wheel-item.is-active`)?.dataset.value || '')
        };
    }""")
    expected_wheels = wheel_values["today"].split("-")
    if wheel_values["selected"] != [expected_wheels[0], str(int(expected_wheels[1])), str(int(expected_wheels[2]))]:
        raise AssertionError(
            f"Calculator Today did not synchronize the date wheels: "
            f"expected={[expected_wheels[0], str(int(expected_wheels[1])), str(int(expected_wheels[2]))]}, "
            f"observed={wheel_values['selected']}"
        )
    page.locator("#cp-save").click()
    if page.locator("#cp-totalDays").inner_text() != "0":
        raise AssertionError("Calculator Today must produce zero elapsed days")
    saved_date = page.evaluate("localStorage.getItem('clean_period_start_date_v4')")
    if not saved_date or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", saved_date):
        raise AssertionError("Calculator Today did not persist a valid YYYY-MM-DD value")
    page.reload(wait_until="domcontentloaded")
    wait_for_page_ready(page)
    if page.evaluate("localStorage.getItem('clean_period_start_date_v4')") != saved_date or page.locator("#cp-totalDays").inner_text() != "0":
        raise AssertionError("Calculator persisted state did not render after reload")
    page.evaluate("localStorage.setItem('clean_period_start_date_v4', '2999-01-01')")
    page.reload(wait_until="domcontentloaded")
    wait_for_page_ready(page)
    if page.locator("#cp-resultLine").inner_text() != "Дата не может быть в будущем" or page.locator("#cp-totalDays").inner_text() != "0":
        raise AssertionError("Calculator future dates must not produce a negative clean period")


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

        goto_ready(page, url(base_url, "/Admin-panel.html"))
        password = page.locator('input[type="password"]')
        password.fill("stage-1-invalid-password")
        page.locator('form a[href="#"]:visible').click()
        page.wait_for_timeout(250)
        if "Admin-panel.html" not in urlparse(page.url).path or "5ab2b48b" in page.url:
            raise AssertionError("invalid admin password granted access")

        goto_ready(page, url(base_url, "/Calendar.html"))
        calendar = page.locator("#gc-frame")
        calendar.wait_for()
        if "mode=WEEK" not in (calendar.get_attribute("src") or ""):
            raise AssertionError("desktop calendar URL did not initialize WEEK mode")
        calendar_page = context.new_page()
        calendar_page.set_viewport_size({"width": 390, "height": 844})
        goto_ready(calendar_page, url(base_url, "/Calendar.html"))
        if "mode=AGENDA" not in (calendar_page.locator("#gc-frame").get_attribute("src") or ""):
            raise AssertionError("mobile calendar URL did not initialize AGENDA mode")
        calendar_page.close()

        goto_ready(page, url(base_url, "/Google-Drive.html"))
        drive_src = page.locator("#gd-frame").get_attribute("src") or ""
        drive_open = page.locator("#gd-open-btn").get_attribute("href") or ""
        if "drive.google.com/embeddedfolderview?id=" not in drive_src:
            raise AssertionError("Drive embed URL did not initialize")
        if not drive_open.startswith("https://accounts.google.com/AccountChooser?continue="):
            raise AssertionError("Drive account chooser URL did not initialize")
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
