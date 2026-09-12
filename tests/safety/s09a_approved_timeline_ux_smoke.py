"""Approved shared timeline UX: both real editors, no mocked transport."""
import io
import math
import struct
import wave
from pathlib import Path
from urllib.parse import urlparse

from s09a_edit_modes_smoke import apply_selection


def fixture(hz, seconds=4):
    data = io.BytesIO()
    with wave.open(data, "wb") as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(16000)
        output.writeframes(b"".join(struct.pack("<h", round(6500 * math.sin(i * hz * 2 * math.pi / 16000))) for i in range(16000 * seconds)))
    return {"name": f"Participant-{hz}.wav", "mimeType": "audio/wav", "buffer": data.getvalue()}


def check_approved_timeline_ux(browser, base_url, screenshot_dir=None):
    output = Path(screenshot_dir) / "s09a-approved-timeline" if screenshot_dir else None
    if output: output.mkdir(parents=True, exist_ok=True)
    options = {"viewport": {"width": 1440, "height": 1000}, "device_scale_factor": 2}
    if output: options.update(record_video_dir=str(output), record_video_size={"width": 1440, "height": 1000})
    context = browser.new_context(**options)
    context.add_init_script("sessionStorage.setItem('meser_service_access_v1','granted')")
    site = urlparse(base_url)
    context.route("**/*", lambda route: route.continue_() if urlparse(route.request.url).netloc == site.netloc else route.abort())
    page = context.new_page(); video = page.video; errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(base_url.rstrip("/") + "/Audio-Editor.html")
        page.locator("#source-session-mode-device").click()
        page.locator("#processor-file").set_input_files([fixture(330), fixture(660)])
        page.locator("#open-local-speaker").click()
        page.wait_for_function("!document.getElementById('speaker-editor-source-audio-play').disabled", timeout=180000)
        rows = page.locator("#speaker-editor-tracks .speaker-track")
        assert page.locator(".speaker-selection-overlay[data-scope=all]").count() == rows.count()
        payload = "async()=>JSON.stringify((await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload)"
        baseline = page.evaluate(payload)

        # The one slider retains independent time and height values and never mutates the recipe.
        zoom = page.locator("#speaker-editor-zoom")
        zoom.fill("4"); zoom.dispatch_event("input")
        page.locator("#speaker-editor-scale-mode").click(); assert zoom.input_value() == "196"
        zoom.fill("180"); zoom.dispatch_event("input")
        assert abs(rows.first.locator(".speaker-waveform-scroll").bounding_box()["height"] - 180) < 2
        assert page.evaluate(payload) == baseline
        page.locator("#speaker-editor-scale-mode").click(); assert float(zoom.input_value()) == 4

        # Track color follows identity through reorder and leaves edit colors semantic.
        identity = rows.first.get_attribute("data-track-id")
        color = rows.first.locator('input[type="color"]')
        color.evaluate("e=>{e.value='#6a4fb3';e.dispatchEvent(new Event('input',{bubbles:true}))}")
        assert page.evaluate(payload) == baseline
        rows.first.get_by_role("button", name="Вниз", exact=True).click()
        colored = page.locator(f'.speaker-track[data-track-id="{identity}"]')
        assert colored.evaluate("e=>getComputedStyle(e).getPropertyValue('--track-wave').trim()") == "#6a4fb3"

        details = page.locator(".speaker-selection > details"); details.evaluate("e=>e.open=true")
        for edge, value in (("start", ".3"), ("end", "3.7")):
            page.locator(f"#speaker-editor-selection-{edge}").fill(value)
            page.locator(f"#speaker-editor-set-{edge}").click()
        assert page.locator(".timeline-outside-region").count() == rows.count() * 2
        assert page.locator(".timeline-outside-region").first.evaluate("e=>getComputedStyle(e).backgroundColor") == "rgba(75, 86, 100, 0.64)"
        page.locator("#speaker-editor-selection-start").fill("1")
        page.locator("#speaker-editor-selection-end").fill("1.4"); apply_selection(page, "cut")
        page.locator("#speaker-editor-selection-start").fill("1.6")
        page.locator("#speaker-editor-selection-end").fill("2"); apply_selection(page, "silence")
        assert page.locator(".timeline-cut-label").count() == 1
        assert page.locator(".speaker-region-overlay--silence .timeline-region-label").count() == 1
        assert page.locator(".speaker-region-overlay--cut").first.evaluate("e=>getComputedStyle(e).backgroundColor") == "rgba(221, 66, 75, 0.27)"
        assert page.locator(".speaker-region-overlay--silence").evaluate("e=>getComputedStyle(e).backgroundColor") == "rgba(234, 184, 47, 0.36)"

        # Loop is common, live and editable from the ruler strip.
        page.locator("#speaker-editor-selection-start").fill(".6")
        page.locator("#speaker-editor-selection-end").fill("2.8")
        page.locator("#speaker-editor-source-audio-loop").click()
        page.locator(".timeline-loop-strip").wait_for(state="visible")
        assert page.locator(".timeline-loop-region").count() == rows.count()
        handle = page.locator("#speaker-editor-global-regions .timeline-loop-handle--start")
        before = float(handle.get_attribute("aria-valuenow")); box = handle.bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 10); page.mouse.down(); page.mouse.move(box["x"] + 35, box["y"] + 10, steps=4)
        assert float(handle.get_attribute("aria-valuenow")) > before
        page.mouse.up()
        page.locator("#speaker-editor-source-audio-stop").click()

        # Pinch-shaped wheel remains horizontal zoom while the slider shows height.
        page.locator("#speaker-editor-scale-mode").click(); height_value = zoom.input_value()
        surface = rows.first.locator(".speaker-waveform-scroll"); surface.evaluate("e=>e.scrollLeft=120")
        box = surface.bounding_box(); before_geometry = surface.evaluate("e=>({left:e.scrollLeft,width:e.firstElementChild.getBoundingClientRect().width})")
        anchor_before = (before_geometry["left"] + 120) / (before_geometry["width"] / 4)
        surface.dispatch_event("wheel", {"deltaY": -80, "deltaMode": 0, "ctrlKey": True, "clientX": box["x"] + 120, "clientY": box["y"] + 60})
        after_geometry = surface.evaluate("e=>({left:e.scrollLeft,width:e.firstElementChild.getBoundingClientRect().width})")
        anchor_after = (after_geometry["left"] + 120) / (after_geometry["width"] / 4)
        assert after_geometry["width"] > before_geometry["width"] and abs(anchor_after - anchor_before) < .02
        assert zoom.input_value() == height_value
        page.locator("#speaker-editor-scale-mode").click()

        # Space pauses and resumes at the same position; repeat and fields are ignored.
        heading = page.locator("#speaker-editor-heading"); heading.evaluate("e=>{e.tabIndex=-1;e.focus()}")
        page.keyboard.press("Space"); page.wait_for_function("!document.getElementById('speaker-editor-source-audio').paused")
        page.wait_for_timeout(180); page.keyboard.press("Space"); position = page.locator("#speaker-editor-source-audio").evaluate("a=>a.currentTime")
        assert position > .3
        heading.dispatch_event("keydown", {"code": "Space", "key": " ", "repeat": True})
        assert page.locator("#speaker-editor-source-audio").evaluate("a=>a.paused")
        page.locator("#speaker-editor-selection-start").focus(); page.keyboard.press("Space")
        assert page.locator("#speaker-editor-source-audio").evaluate("a=>a.paused")

        # Pointer/focus context switches Space to the rendered result transport.
        page.locator("#speaker-editor-render").click()
        page.wait_for_function("document.getElementById('speaker-editor-result-audio').readyState >= 2", timeout=60000)
        result_heading = page.locator("#speaker-result-heading")
        result_heading.evaluate("e=>{e.tabIndex=-1;e.focus()}")
        page.keyboard.press("Space")
        page.wait_for_function("!document.getElementById('speaker-editor-result-audio').paused")
        assert page.locator("#speaker-editor-source-audio").evaluate("a=>a.paused")
        page.wait_for_timeout(120); page.keyboard.press("Space")
        assert page.locator("#speaker-editor-result-audio").evaluate("a=>a.paused && a.currentTime > 0")

        if output: page.locator("#speaker-editor").screenshot(path=str(output / "speaker-before-expand.png"))
        page.locator("#speaker-editor-expand").click(); assert page.locator("#speaker-editor").evaluate("e=>e.classList.contains('is-expanded')")
        assert page.evaluate(payload) != baseline  # only the intentional edits above changed it
        if output: page.screenshot(path=str(output / "speaker-expanded.png"))
        page.keyboard.press("Escape"); assert not page.locator("#speaker-editor").evaluate("e=>e.classList.contains('is-expanded')")

        # Switch to the second editor, preserving its own display state and common selection.
        page.locator("#open-local-announcement").click()
        page.locator("#speaker-unsaved-discard").click()
        page.wait_for_function("document.querySelectorAll('#processor-file-info .processor-track').length===2 && !document.getElementById('processor-source-audio-play').disabled", timeout=60000)
        tracks = page.locator("#processor-file-info .processor-track")
        assert page.locator(".processor-selection-overlay").count() == tracks.count()
        source_zoom = page.locator("#processor-source-zoom-range"); time_value = source_zoom.input_value()
        page.locator("#processor-source-scale-mode").click(); source_zoom.fill("176"); source_zoom.dispatch_event("input")
        assert abs(tracks.first.locator(".processor-waveform-scroll").bounding_box()["height"] - 176) < 2
        page.locator("#processor-source-scale-mode").click(); assert source_zoom.input_value() == time_value
        announcement_surface = tracks.first.locator(".processor-waveform-scroll")
        gesture_before = announcement_surface.locator(".processor-waveform").evaluate("e=>e.getBoundingClientRect().width")
        announcement_surface.evaluate("""e=>{
            const x=e.getBoundingClientRect().left+100;
            for(const [type,scale] of [['gesturestart',1],['gesturechange',1.5],['gestureend',1.5]]){
                const event=new Event(type,{bubbles:true,cancelable:true});
                Object.defineProperties(event,{clientX:{value:x},scale:{value:scale}}); e.dispatchEvent(event);
            }
        }""")
        assert announcement_surface.locator(".processor-waveform").evaluate("e=>e.getBoundingClientRect().width") > gesture_before
        identity = tracks.first.get_attribute("data-track-id")
        tracks.first.locator('input[type="color"]').evaluate("e=>{e.value='#b04d6f';e.dispatchEvent(new Event('input',{bubbles:true}))}")
        tracks.first.get_by_role("button", name="Переместить дорожку 1 вниз", exact=False).click()
        assert page.locator(f'.processor-track[data-track-id="{identity}"]').evaluate("e=>getComputedStyle(e).getPropertyValue('--track-wave').trim()") == "#b04d6f"
        page.locator("#processor-source-audio-loop").click(); page.locator("#processor-global-regions .timeline-loop-strip").wait_for(state="visible")
        assert page.locator("#processor-file-info .timeline-loop-region").count() == tracks.count()
        page.locator("#processor-source-audio-stop").click()
        page.locator("#processor-expand").click(); assert page.locator("#announcement-processor-card").evaluate("e=>e.classList.contains('is-expanded')")
        if output: page.screenshot(path=str(output / "announcement-expanded.png"))
        page.keyboard.press("Escape"); assert not page.locator("#announcement-processor-card").evaluate("e=>e.classList.contains('is-expanded')")
        page.locator("#processor-heading").evaluate("e=>{e.tabIndex=-1;e.focus()}")
        page.keyboard.press("Space"); page.wait_for_function("!document.getElementById('processor-source-audio').paused")
        page.wait_for_timeout(150); page.keyboard.press("Space"); assert page.locator("#processor-source-audio").evaluate("a=>a.paused")
        assert not errors, errors
        print("Approved timeline UX: PASS; shared selection/Loop, semantic regions, height/time, colors, Space, pinch-shaped wheel and expand in both editors.", flush=True)
    finally:
        context.close()
        if output and video:
            path = Path(video.path())
            path.replace(output / "approved-timeline-interactions.webm")
