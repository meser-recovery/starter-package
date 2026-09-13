#!/usr/bin/env python3
"""Focused S09C browser validation against the real pages and synthetic gateway."""
from __future__ import annotations

import argparse
import importlib.util
import http.server
from pathlib import Path
import threading
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
PREVIEW_PATH = ROOT / "scripts" / "preview-audio-editor.py"


def load_preview_module():
    spec = importlib.util.spec_from_file_location("meser_audio_preview", PREVIEW_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    spec.loader.exec_module(module)
    return module


def assert_no_page_overflow(page, scenario):
    result = page.evaluate("""() => ({
      viewport: innerWidth,
      document: document.documentElement.scrollWidth,
      body: document.body.scrollWidth,
      offenders: [...document.querySelectorAll('main, main *, dialog[open], dialog[open] *')]
        .map(element => {
          const box = element.getBoundingClientRect();
          const style = getComputedStyle(element);
          return {tag: element.tagName, id: element.id, className: String(element.className || ''),
            left: box.left, right: box.right, width: box.width, height: box.height,
            visible: style.display !== 'none' && style.visibility !== 'hidden'};
        }).filter(item => item.visible && item.width > 0 && item.height > 0 &&
          (item.left < -1 || item.right > innerWidth + 1)).slice(0, 12)
    })""")
    assert result["document"] <= result["viewport"] + 1, {scenario: result}
    assert result["body"] <= result["viewport"] + 1, {scenario: result}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--screenshot-dir", type=Path)
    args = parser.parse_args()
    output = args.screenshot_dir
    if output:
        output.mkdir(parents=True, exist_ok=True)

    preview = load_preview_module()
    gateway = preview.SyntheticGateway(ROOT)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), http.server.SimpleHTTPRequestHandler)
    origin = f"http://127.0.0.1:{server.server_port}"
    server.RequestHandlerClass = preview.preview_handler(ROOT, gateway, origin)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    requests = []
    outbound = []
    page_errors = []

    def shot(page, name, full_page=True):
        if output:
            page.screenshot(path=str(output / f"{name}.png"), full_page=full_page)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)

            def route_request(route):
                url = route.request.url
                parsed = urlparse(url)
                if parsed.scheme in {"blob", "data"} or url.startswith(origin + "/"):
                    route.continue_()
                else:
                    outbound.append(url)
                    route.abort()

            context.route("**/*", route_request)
            page = context.new_page()
            page.on("request", lambda request: requests.append((request.method, request.url)))
            page.on("pageerror", lambda error: page_errors.append(str(error)))

            # Editor starts with one source decision and no inactive workspace complexity.
            page.goto(origin + "/Audio-Editor.html")
            page.wait_for_function("document.getElementById('source-session-session-status').textContent.includes('активен')")
            assert page.locator("#workflow-choice").is_hidden()
            assert page.locator("#speaker-editor").is_hidden()
            assert page.locator("#announcement-processor-card").is_hidden()
            assert not page.locator("#import-zone").evaluate("element => element.open")
            assert page.get_by_role("button", name="Из аудиоархива Найти сохранённую запись").count() == 1
            assert page.get_by_role("button", name="С устройства Выбрать локальные дорожки").count() == 1
            for width in (320, 390, 768, 1280):
                page.set_viewport_size({"width": width, "height": 900})
                assert_no_page_overflow(page, f"editor-initial-{width}")
                shot(page, f"editor-initial-{width}")

            # Picker stays empty until the user explicitly requests records.
            page.set_viewport_size({"width": 390, "height": 900})
            write_start = len(requests)
            page.locator("#source-session-mode-archive").click()
            assert page.locator("#import-zone").evaluate("element => element.open")
            assert page.locator("#source-session-list > *").count() == 0
            assert page.locator("#source-session-count").inner_text() == "Список появится после поиска."
            shot(page, "editor-archive-picker-before-request-390")
            page.locator("#source-session-recent").click()
            page.locator("#source-session-list .source-session-item").first.wait_for()
            shot(page, "editor-archive-picker-results-390")
            multi_track = page.locator("#source-session-list .source-session-item").filter(has_text="3 дорожек")
            assert multi_track.count() == 1
            multi_track.get_by_role("button", name="Выбрать").click()
            page.wait_for_function("document.getElementById('current-recording').dataset.recordingState === 'archive'")
            assert page.locator("#workflow-choice").is_visible()
            assert page.locator("#current-recording-facts").is_visible()
            assert "Аудиоархив" in page.locator("#current-recording-source").inner_text()
            shot(page, "editor-current-recording-and-workflow-choice-390")
            assert all(method == "GET" for method, url in requests[write_start:] if "/v1/" in url), requests[write_start:]

            # Announcement is the intentionally simpler focused flow and processing stays local.
            page.set_viewport_size({"width": 1280, "height": 900})
            page.get_by_role("button", name="Открыть редактор анонс-мейкера", exact=True).click()
            page.locator("#announcement-processor-card").wait_for(state="visible")
            page.wait_for_function("!document.getElementById('processor-run').disabled")
            assert page.locator("#speaker-editor").is_hidden()
            shot(page, "announcement-workspace-1280")
            page.locator("#processor-run").click()
            page.locator("#processor-result").wait_for(state="visible", timeout=120_000)
            assert page.locator("#source-session-publish-announcement").is_visible()
            assert page.locator("#processor-download").is_visible()
            shot(page, "announcement-result-1280")
            assert not any(method in {"POST", "PUT", "PATCH", "DELETE"} for method, url in requests[write_start:] if "/v1/" in url), requests[write_start:]

            # Closing the workspace keeps the selected record and reveals the equal workflow choice.
            page.locator("#source-session-announcement-close").click()
            assert page.locator("#workflow-choice").is_visible()
            assert page.locator("#current-recording").get_attribute("data-recording-state") == "archive"

            # Speaker opens as the wide waveform-centered workspace; narrow overflow is local.
            page.get_by_role("button", name="Открыть финальную обработку спикерской", exact=True).click()
            page.locator("#speaker-editor").wait_for(state="visible")
            page.locator("#speaker-editor-tracks .speaker-track").first.wait_for(timeout=60_000)
            assert page.locator("#speaker-editor-tracks .speaker-track").count() == 3
            assert page.locator("#announcement-processor-card").is_hidden()
            wave = page.locator("#speaker-editor-tracks .speaker-waveform").first
            box = wave.bounding_box()
            assert box and box["width"] > 100
            page.mouse.move(box["x"] + box["width"] * .2, box["y"] + box["height"] * .5)
            page.mouse.down()
            page.mouse.move(box["x"] + box["width"] * .58, box["y"] + box["height"] * .5)
            page.mouse.up()
            shot(page, "speaker-workspace-selection-1280")
            for width in (320, 390, 768, 1280):
                page.set_viewport_size({"width": width, "height": 900})
                assert_no_page_overflow(page, f"speaker-workspace-{width}")
                if width in (320, 390):
                    shot(page, f"speaker-workspace-contained-timeline-{width}")

            # Archive entry is quiet, collection is requested explicitly, and detail is separate.
            page.goto(origin + "/Audio-Archive.html")
            page.wait_for_function("document.getElementById('status').textContent.includes('Данные загружены')")
            assert page.locator("#records").is_hidden()
            assert page.locator("#detail").is_hidden()
            for width in (320, 390, 768, 1280):
                page.set_viewport_size({"width": width, "height": 900})
                assert_no_page_overflow(page, f"archive-initial-{width}")
                shot(page, f"archive-initial-{width}")
            page.set_viewport_size({"width": 1280, "height": 900})
            archive_write_start = len(requests)
            page.locator("#record-picker-open").click()
            assert page.locator("#session-list > *").count() == 0
            page.locator("#record-picker-recent").click()
            page.locator("#session-list .source-row").first.wait_for()
            shot(page, "archive-record-list-1280")
            page.locator("#session-list .source-row").first.get_by_role("button", name="Открыть запись").click()
            page.locator("#detail-title").wait_for()
            assert page.locator("#archive-index").is_hidden()
            assert page.locator(".primary-workflows .workflow-choice").count() == 2
            assert page.locator(".ready-results").get_attribute("open") is not None
            assert page.locator(".version-history").get_attribute("open") is None
            shot(page, "archive-record-detail-1280")
            page.locator(".version-history > summary").click()
            shot(page, "archive-detail-expanded-history-1280")
            assert all(method == "GET" for method, url in requests[archive_write_start:] if "/v1/" in url), requests[archive_write_start:]

            # Dependency preview remains explicit and fits at every target width.
            page.locator(".workflow-announcement .destructive-disclosure > summary").click()
            page.locator(".workflow-announcement").get_by_role("button", name="Удалить все версии для анонс-мейкера").click()
            page.locator("#delete-dialog").wait_for(state="visible")
            assert page.locator("#delete-removed").inner_text()
            assert page.locator("#delete-retained").inner_text()
            for width in (320, 390, 768, 1280):
                page.set_viewport_size({"width": width, "height": 900})
                assert_no_page_overflow(page, f"deletion-dialog-{width}")
                if width in (320, 1280):
                    shot(page, f"deletion-dependency-dialog-{width}")
            page.keyboard.press("Escape")

            # Source deletion is an explicit mock-only mutation; retained results remain visible.
            page.locator(".record-management > summary").click()
            if page.locator(".danger-zone").get_attribute("open") is None:
                page.locator(".danger-zone > summary").click()
            page.get_by_role("button", name="Удалить исходные дорожки", exact=True).click()
            page.locator("#delete-dialog").wait_for(state="visible")
            page.locator("#delete-submit").click()
            page.wait_for_function("document.getElementById('detail-heading').textContent.includes('Исходники удалены')")
            assert page.locator(".ready-result").count() == 2
            page.set_viewport_size({"width": 390, "height": 900})
            shot(page, "archive-unavailable-sources-retained-results-390")
            if page.locator(".danger-zone").get_attribute("open") is None:
                page.locator(".danger-zone > summary").click()
            page.get_by_role("button", name="Удалить запись полностью", exact=True).click()
            page.locator("#delete-dialog").wait_for(state="visible")
            assert page.locator("#purge-label").is_visible()
            shot(page, "archive-exact-id-purge-confirmation-390")
            page.keyboard.press("Escape")

            # Disconnect state keeps a clear reconnect path and does not load production resources.
            page.locator("#detail-close").click()
            page.locator("#logout").click()
            page.wait_for_function("document.getElementById('status').textContent === 'Аудиоархив отключён.'")
            page.set_viewport_size({"width": 390, "height": 900})
            shot(page, "archive-reconnect-required-390")
            assert page.locator("#login").is_visible()

            assert not outbound, outbound
            assert not page_errors, page_errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        gateway.close()

    api_requests = [(method, urlparse(url).path) for method, url in requests if "/v1/" in url]
    writes = [entry for entry in api_requests if entry[0] in {"POST", "PUT", "PATCH", "DELETE"}]
    print(f"S09C browser smoke passed: {len(api_requests)} local gateway requests, {len(writes)} writes, 0 outbound requests.")


if __name__ == "__main__":
    main()
