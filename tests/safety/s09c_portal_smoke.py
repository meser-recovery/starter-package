#!/usr/bin/env python3
"""Focused S09C browser validation against the real pages and synthetic gateway."""
from __future__ import annotations

import argparse
import importlib.util
import http.server
import math
from pathlib import Path
import struct
import tempfile
import threading
from urllib.parse import urlparse
import wave

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


def write_wave(path: Path, frequency: float, phase: float = 0.0):
    rate = 8_000
    frames = bytearray()
    for index in range(rate * 3):
        envelope = .22 + .16 * math.sin(index / rate * math.pi * 1.7 + phase)
        sample = int(32767 * envelope * math.sin(2 * math.pi * frequency * index / rate))
        frames.extend(struct.pack("<h", sample))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(frames)


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

    fixture_directory = tempfile.TemporaryDirectory(prefix="s09c-local-audio-")
    local_tracks = []
    for index, (name, frequency) in enumerate((("host.wav", 190), ("guest.wav", 260), ("music.wav", 115))):
        path = Path(fixture_directory.name) / name
        write_wave(path, frequency, index * .6)
        local_tracks.append(str(path))

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
            assert page.get_by_role("button", name="Из аудиоархива Открыть сохранённую Zoom-запись Выбрать запись").count() == 1
            assert page.get_by_role("button", name="С этого устройства Загрузить локальные аудиодорожки Выбрать файлы").count() == 1
            for width in (320, 390, 768, 1280):
                page.set_viewport_size({"width": width, "height": 900})
                assert_no_page_overflow(page, f"editor-initial-{width}")
                shot(page, f"editor-initial-{width}")

            # The local-file modal is a focused sheet and keeps selected tracks compact.
            page.set_viewport_size({"width": 1280, "height": 900})
            page.locator("#source-session-mode-device").click()
            assert page.locator("#import-zone").evaluate("element => element.open")
            page.locator("#processor-file").set_input_files(local_tracks)
            page.wait_for_function("document.querySelectorAll('#import-files li').length === 3")
            page.locator("#source-session-use-local").wait_for(state="visible")
            shot(page, "editor-local-files-1280", full_page=False)
            page.set_viewport_size({"width": 390, "height": 900})
            assert_no_page_overflow(page, "editor-local-files-390")
            shot(page, "editor-local-files-390", full_page=False)
            page.locator("#source-session-use-local").click()

            # The archive picker opens with real records already visible.
            page.set_viewport_size({"width": 1280, "height": 900})
            write_start = len(requests)
            page.locator("#source-session-mode-archive").click()
            assert page.locator("#import-zone").evaluate("element => element.open")
            page.locator("#source-session-list .source-session-item").first.wait_for()
            shot(page, "editor-archive-selection-1280", full_page=False)
            page.set_viewport_size({"width": 390, "height": 900})
            assert_no_page_overflow(page, "editor-archive-selection-390")
            shot(page, "editor-archive-selection-390", full_page=False)
            page.set_viewport_size({"width": 1280, "height": 900})
            multi_track = page.locator("#source-session-list .source-session-item").filter(has_text="3 дорожек")
            assert multi_track.count() == 1
            multi_track.get_by_role("button", name="Выбрать").click()
            page.locator("#source-session-loading").wait_for(state="visible")
            shot(page, "editor-loading-1280", full_page=False)
            page.locator("#source-session-loading").wait_for(state="hidden")
            page.wait_for_function("document.getElementById('current-recording').dataset.recordingState === 'archive'")
            assert page.locator("#workflow-choice").is_visible()
            assert page.locator("#current-recording-facts").is_visible()
            assert "Аудиоархив" in page.locator("#current-recording-source").inner_text()
            shot(page, "editor-workflow-choice-1280")
            page.set_viewport_size({"width": 390, "height": 900})
            assert_no_page_overflow(page, "editor-workflow-choice-390")
            shot(page, "editor-workflow-choice-390")
            assert all(method == "GET" for method, url in requests[write_start:] if "/v1/" in url), requests[write_start:]

            # Announcement is the intentionally simpler focused flow and processing stays local.
            page.set_viewport_size({"width": 1280, "height": 900})
            page.get_by_role("button", name="Открыть анонс-мейкер", exact=True).click()
            page.locator("#announcement-processor-card").wait_for(state="visible")
            page.wait_for_function("!document.getElementById('processor-run').disabled")
            assert page.locator("#speaker-editor").is_hidden()
            page.evaluate("window.scrollTo(0, 0)")
            shot(page, "announcement-workspace-1280", full_page=False)
            page.locator("#processor-run").click()
            page.locator("#processor-result").wait_for(state="visible", timeout=120_000)
            assert page.locator("#source-session-publish-announcement").is_visible()
            assert page.locator("#processor-download").is_visible()
            page.locator("#processor-result").scroll_into_view_if_needed()
            shot(page, "announcement-result-1280", full_page=False)
            page.locator("#source-session-publish-announcement").click()
            page.locator("#source-session-publication-dialog").wait_for(state="visible")
            shot(page, "dialog-save-announcement-1280", full_page=False)
            page.locator("#source-session-publication-cancel").click()
            assert not any(method in {"POST", "PUT", "PATCH", "DELETE"} for method, url in requests[write_start:] if "/v1/" in url), requests[write_start:]

            # Closing the workspace keeps the selected record and reveals the equal workflow choice.
            page.locator("#source-session-announcement-close").click()
            assert page.locator("#workflow-choice").is_visible()
            assert page.locator("#current-recording").get_attribute("data-recording-state") == "archive"

            # Speaker opens as the wide waveform-centered workspace; narrow overflow is local.
            page.get_by_role("button", name="Открыть спикерскую", exact=True).click()
            page.locator("#speaker-editor").wait_for(state="visible")
            page.locator("#speaker-editor-tracks .speaker-track").first.wait_for(timeout=60_000)
            assert page.locator("#speaker-editor-tracks .speaker-track").count() == 3
            assert page.locator("#announcement-processor-card").is_hidden()
            assert page.locator("#speaker-selection-heading").inner_text().casefold() == "редактирование"
            assert page.locator("#speaker-editor .technical-details").count() == 0
            assert page.locator("#speaker-editor-technical").is_hidden()
            assert page.get_by_text("Технические сведения", exact=True).count() == 0
            for row in page.locator("#speaker-editor-tracks .speaker-track").all():
                assert row.locator('[data-dsp-field="enhancement"]').is_visible()
                assert row.locator('[data-dsp-field="leveling"]').is_visible()
                assert row.locator('[data-dsp-field="compression"]').is_visible()
                assert row.locator(".speaker-dsp-disclosure > summary").count() == 0
            wave = page.locator("#speaker-editor-tracks .speaker-waveform").first
            box = wave.bounding_box()
            assert box and box["width"] > 100
            page.mouse.move(box["x"] + box["width"] * .2, box["y"] + box["height"] * .5)
            page.mouse.down()
            page.mouse.move(box["x"] + box["width"] * .58, box["y"] + box["height"] * .5)
            page.mouse.up()
            page.evaluate("window.scrollTo(0, 0)")
            shot(page, "speaker-workspace-1280", full_page=False)
            page.set_viewport_size({"width": 1680, "height": 932})
            page.evaluate("window.scrollTo(0, 0)")
            shot(page, "speaker-workspace-1680", full_page=False)
            for width in (320, 390, 768, 1280, 1680):
                page.set_viewport_size({"width": width, "height": 900})
                assert_no_page_overflow(page, f"speaker-workspace-{width}")
                transport_layout = page.evaluate("""() => {
                  const bounds = node => { const box=node.getBoundingClientRect(); return {name:node.id||node.className,left:box.left,right:box.right,top:box.top,bottom:box.bottom}; };
                  const main=document.querySelector('#speaker-editor .studio-transport-main');
                  const controls=document.querySelector('#speaker-editor .speaker-transport-controls');
                  return {main:bounds(main),controls:bounds(controls),mainChildren:[...main.children].filter(node=>node.getBoundingClientRect().width).map(bounds),controlChildren:[...controls.children].filter(node=>node.getBoundingClientRect().width).map(bounds)};
                }""")
                main_box, controls_box = transport_layout["main"], transport_layout["controls"]
                separated_horizontally = main_box["right"] <= controls_box["left"] + 1 or controls_box["right"] <= main_box["left"] + 1
                separated_vertically = main_box["bottom"] <= controls_box["top"] + 1 or controls_box["bottom"] <= main_box["top"] + 1
                assert separated_horizontally or separated_vertically, (width, transport_layout)
                for main_child in transport_layout["mainChildren"]:
                    for control_child in transport_layout["controlChildren"]:
                        child_horizontal = main_child["right"] <= control_child["left"] + 1 or control_child["right"] <= main_child["left"] + 1
                        child_vertical = main_child["bottom"] <= control_child["top"] + 1 or control_child["bottom"] <= main_child["top"] + 1
                        assert child_horizontal or child_vertical, (width, main_child, control_child, transport_layout)
                if width in (390, 1280, 1680):
                    follow_box = page.locator("#speaker-editor-follow").bounding_box()
                    transport_box = page.locator("#speaker-editor .speaker-transport").bounding_box()
                    assert follow_box and transport_box
                    assert follow_box["x"] >= transport_box["x"] and follow_box["x"] + follow_box["width"] <= transport_box["x"] + transport_box["width"], (width, follow_box, transport_box)
                if width in (320, 390):
                    shot(page, f"speaker-workspace-{width}", full_page=False)

            page.set_viewport_size({"width": 1280, "height": 900})
            transport = page.locator("#speaker-editor .speaker-transport")
            transported_ids = ("speaker-editor-scale-mode", "speaker-editor-zoom-out", "speaker-editor-zoom",
                "speaker-editor-scale-value", "speaker-editor-zoom-in", "speaker-editor-zoom-fit", "speaker-editor-follow")
            for control_id in transported_ids:
                assert transport.locator(f"#{control_id}").count() == 1, control_id
                assert page.locator(f"#speaker-editor .speaker-selection #{control_id}").count() == 0, control_id
            fit = page.locator("#speaker-editor-zoom-fit")
            follow = page.locator("#speaker-editor-follow")
            assert fit.get_attribute("aria-label") == fit.get_attribute("title") == "Вписать timeline в доступную ширину"
            assert follow.get_attribute("aria-label") == follow.get_attribute("title") == "Следовать за playhead при воспроизведении"
            for icon_button in (fit, follow):
                assert icon_button.evaluate("button => ![...button.childNodes].some(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim())")
                assert icon_button.locator("svg[aria-hidden=true]").count() == 1
                assert icon_button.locator(".visually-hidden").count() == 1
            if output: transport.screenshot(path=str(output / "speaker-transport-closeup-1280.png"))

            project_before_transport = page.evaluate("async () => JSON.stringify((await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload)")
            zoom = page.locator("#speaker-editor-zoom")
            zoom.fill("4"); zoom.dispatch_event("input")
            page.wait_for_timeout(80)
            time_width = wave.evaluate("element => element.getBoundingClientRect().width")
            assert zoom.get_attribute("aria-label") == "Горизонтальный масштаб времени"
            assert "Горизонтальный масштаб времени" in page.locator("#speaker-editor-scale-mode").get_attribute("aria-label")
            shot(page, "speaker-scale-time-1280", full_page=False)

            page.locator("#speaker-editor-scale-mode").click()
            assert page.locator("#speaker-editor-scale-mode").get_attribute("aria-pressed") == "true"
            assert zoom.get_attribute("aria-label") == "Высота всех дорожек Спикерской"
            assert "Высота дорожек" in page.locator("#speaker-editor-scale-mode").get_attribute("aria-label")
            stable_controls = page.locator("#speaker-editor-tracks .speaker-track").first.evaluate("""row => {
              const panel=row.querySelector('.speaker-track-controls').getBoundingClientRect();
              const button=row.querySelector('.speaker-track__buttons button').getBoundingClientRect();
              const dsp=row.querySelector('.speaker-dsp').getBoundingClientRect();
              return {panelWidth:panel.width,buttonWidth:button.width,buttonHeight:button.height,dspWidth:dsp.width};
            }""")
            for height, name in ((168, "speaker-scale-height-min-1280"), (244, None), (320, "speaker-scale-height-max-1280"), (196, "speaker-scale-height-1280")):
                zoom.fill(str(height)); zoom.dispatch_event("input"); page.wait_for_timeout(80)
                geometry = page.locator("#speaker-editor-tracks .speaker-track").first.evaluate("""row => {
                  const box=e=>e.getBoundingClientRect(); const panel=box(row.querySelector('.speaker-track-controls'));
                  const lane=box(row.querySelector('.speaker-waveform-scroll')), wave=box(row.querySelector('.speaker-waveform'));
                  const canvas=row.querySelector('canvas'), pixels=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
                  const bg=[pixels[0],pixels[1],pixels[2]], ys=[];
                  for(let y=0;y<canvas.height;y++) for(let x=0;x<canvas.width;x++) { const i=(y*canvas.width+x)*4; if(pixels[i]!==bg[0]||pixels[i+1]!==bg[1]||pixels[i+2]!==bg[2]) { ys.push(y); break; } }
                  const button=box(row.querySelector('.speaker-track__buttons button')), dsp=box(row.querySelector('.speaker-dsp'));
                  return {row:box(row).height,panel:panel.height,lane:lane.height,wave:wave.height,canvasCss:box(canvas).height,
                    canvasPixels:canvas.height,dpr:Math.max(1,Math.min(3,devicePixelRatio||1)),minY:Math.min(...ys),maxY:Math.max(...ys),
                    panelWidth:panel.width,buttonWidth:button.width,buttonHeight:button.height,dspWidth:dsp.width};
                }""")
                for key in ("row", "panel", "lane", "wave", "canvasCss"):
                    assert abs(geometry[key] - height) < 2, (height, geometry)
                assert abs(geometry["canvasPixels"] - height * geometry["dpr"]) <= 2, geometry
                assert geometry["minY"] > 1 and geometry["maxY"] < geometry["canvasPixels"] - 2, geometry
                assert abs((geometry["minY"] + geometry["maxY"]) / 2 - geometry["canvasPixels"] / 2) <= 2, geometry
                for key in ("panelWidth", "buttonWidth", "buttonHeight", "dspWidth"):
                    assert abs(geometry[key] - stable_controls[key]) < 1, (key, height, geometry, stable_controls)
                if name: shot(page, name, full_page=False)
            if output: page.locator("#speaker-editor-tracks .speaker-track").first.screenshot(path=str(output / "speaker-track-enhancement-controls-1280.png"))
            page.locator("#speaker-editor-scale-mode").click()
            assert float(zoom.input_value()) == 4
            page.locator("#speaker-editor-zoom-in").focus(); page.keyboard.press("Tab")
            assert fit.evaluate("button => document.activeElement === button && button.matches(':focus-visible')")
            fit.click()
            page.wait_for_timeout(80)
            assert float(zoom.input_value()) == 1
            assert page.evaluate("getComputedStyle(document.getElementById('speaker-editor')).getPropertyValue('--track-height').trim()") == "196px"
            assert wave.evaluate("element => element.getBoundingClientRect().width") < time_width
            shot(page, "speaker-fit-after-zoom-1280", full_page=False)

            page.locator("#speaker-editor-zoom-in").focus(); page.keyboard.press("Tab"); page.keyboard.press("Tab")
            assert follow.evaluate("button => document.activeElement === button && button.matches(':focus-visible')")
            assert follow.get_attribute("aria-pressed") == "false"
            shot(page, "speaker-follow-off-1280", full_page=False)
            page.keyboard.press("Space")
            assert follow.get_attribute("aria-pressed") == "true"
            assert page.evaluate("getComputedStyle(document.getElementById('speaker-editor-follow')).backgroundColor") == "rgb(8, 126, 101)"
            shot(page, "speaker-follow-on-1280", full_page=False)
            page.keyboard.press("Space")
            assert follow.get_attribute("aria-pressed") == "false"
            assert page.evaluate("async () => JSON.stringify((await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload)") == project_before_transport

            help_box = page.locator("#speaker-editor .audio-help")
            help_summary = help_box.locator("summary")
            assert help_summary.get_attribute("aria-expanded") == "false"
            if output: help_box.screenshot(path=str(output / "speaker-help-closed-1280.png"))
            help_summary.press("Enter"); page.wait_for_function("document.querySelector('#speaker-editor .audio-help').open && document.querySelector('#speaker-editor .audio-help summary').getAttribute('aria-expanded') === 'true'")
            assert help_box.get_attribute("open") is not None and help_summary.get_attribute("aria-expanded") == "true"
            if output: help_box.screenshot(path=str(output / "speaker-help-open-1280.png"))
            help_summary.press("Enter"); page.wait_for_function("!document.querySelector('#speaker-editor .audio-help').open && document.querySelector('#speaker-editor .audio-help summary').getAttribute('aria-expanded') === 'false'")
            assert help_box.get_attribute("open") is None and help_summary.get_attribute("aria-expanded") == "false"
            help_summary.press("Enter"); page.wait_for_function("document.querySelector('#speaker-editor .audio-help').open && document.querySelector('#speaker-editor .audio-help summary').getAttribute('aria-expanded') === 'true'")
            assert help_box.get_attribute("open") is not None and help_summary.get_attribute("aria-expanded") == "true"
            help_summary.press("Enter"); page.wait_for_function("!document.querySelector('#speaker-editor .audio-help').open && document.querySelector('#speaker-editor .audio-help summary').getAttribute('aria-expanded') === 'false'")

            fullscreen_before = page.evaluate("""async () => ({payload:JSON.stringify((await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload),
              selection:[document.getElementById('speaker-editor-selection-start').value,document.getElementById('speaker-editor-selection-end').value],
              follow:document.getElementById('speaker-editor-follow').getAttribute('aria-pressed'),scroll:document.querySelector('#speaker-editor-tracks .speaker-waveform-scroll').scrollLeft})""")
            expand = page.locator("#speaker-editor-expand")
            assert expand.get_attribute("aria-label") == expand.get_attribute("title") == "На весь экран"
            assert not expand.is_disabled()
            expand.click(); page.wait_for_function("document.fullscreenElement === document.getElementById('speaker-editor')")
            assert expand.get_attribute("aria-label") == expand.get_attribute("title") == "Выйти из полноэкранного режима"
            assert expand.get_attribute("aria-pressed") == "true"
            assert page.locator("#speaker-editor .speaker-dsp [data-dsp-field]").count() == 9
            assert all(control.is_visible() for control in page.locator("#speaker-editor .speaker-dsp [data-dsp-field]").all())
            shot(page, "speaker-fullscreen-1280", full_page=False)
            page.keyboard.press("Escape"); page.wait_for_function("document.fullscreenElement === null")
            assert expand.get_attribute("aria-label") == expand.get_attribute("title") == "На весь экран"
            assert expand.get_attribute("aria-pressed") == "false"
            fullscreen_after = page.evaluate("""async () => ({payload:JSON.stringify((await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload),
              selection:[document.getElementById('speaker-editor-selection-start').value,document.getElementById('speaker-editor-selection-end').value],
              follow:document.getElementById('speaker-editor-follow').getAttribute('aria-pressed'),scroll:document.querySelector('#speaker-editor-tracks .speaker-waveform-scroll').scrollLeft})""")
            assert fullscreen_after == fullscreen_before, (fullscreen_before, fullscreen_after)

            page.locator("#speaker-editor-render").click()
            page.locator("#speaker-editor-result").wait_for(state="visible", timeout=120_000)
            page.locator("#speaker-editor-result").scroll_into_view_if_needed()
            shot(page, "speaker-result-1280", full_page=False)
            page.set_viewport_size({"width": 1680, "height": 932})
            page.locator("#speaker-editor-result").scroll_into_view_if_needed()
            shot(page, "speaker-result-1680", full_page=False)

            # Archive entry is quiet, collection is requested explicitly, and detail is separate.
            page.goto(origin + "/Audio-Archive.html")
            page.wait_for_function("document.getElementById('status').textContent.includes('Данные загружены')")
            assert page.locator("#records").is_visible()
            assert page.locator("#detail").is_hidden()
            for width in (320, 390, 768, 1280):
                page.set_viewport_size({"width": width, "height": 900})
                assert_no_page_overflow(page, f"archive-initial-{width}")
                shot(page, f"archive-initial-{width}")
            page.set_viewport_size({"width": 1280, "height": 900})
            archive_write_start = len(requests)
            page.locator("#session-list .source-row").first.wait_for()
            shot(page, "archive-list-1280")
            page.set_viewport_size({"width": 1536, "height": 1024})
            page.evaluate("window.scrollTo(0, 0)")
            shot(page, "archive-list-1536", full_page=False)
            page.set_viewport_size({"width": 390, "height": 900})
            assert_no_page_overflow(page, "archive-list-390")
            shot(page, "archive-list-390")
            page.set_viewport_size({"width": 1280, "height": 900})
            page.locator("#session-list .source-row").first.get_by_role("button", name="Открыть запись").click()
            page.locator("#detail-title").wait_for()
            assert page.locator("#archive-index").is_hidden()
            assert page.locator(".primary-workflows .workflow-choice").count() == 2
            assert page.locator(".ready-results").get_attribute("open") is not None
            assert page.locator(".source-section").get_attribute("open") is not None
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
        fixture_directory.cleanup()

    api_requests = [(method, urlparse(url).path) for method, url in requests if "/v1/" in url]
    writes = [entry for entry in api_requests if entry[0] in {"POST", "PUT", "PATCH", "DELETE"}]
    print(f"S09C browser smoke passed: {len(api_requests)} local gateway requests, {len(writes)} writes, 0 outbound requests.")


if __name__ == "__main__":
    main()
