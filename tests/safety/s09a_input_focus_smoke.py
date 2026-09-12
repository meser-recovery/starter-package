"""Space routing and gesture focus on both real editors, without studio click setup."""
from urllib.parse import urlparse
from s09a_approved_timeline_ux_smoke import fixture


def check_input_focus(browser, base_url):
    for speaker in (True, False):
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        context.add_init_script("sessionStorage.setItem('meser_service_access_v1','granted')")
        site = urlparse(base_url)
        context.route("**/*", lambda route: route.continue_() if urlparse(route.request.url).netloc == site.netloc else route.abort())
        page = context.new_page(); errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        prefix = "speaker-editor" if speaker else "processor"
        workspace = "#speaker-editor" if speaker else "#announcement-processor-card"
        launcher = "#open-local-speaker" if speaker else "#open-local-announcement"
        surface_selector = ".speaker-waveform-scroll" if speaker else ".processor-waveform-scroll"
        scale_id = f"#{prefix}-scale-mode" if speaker else "#processor-source-scale-mode"
        zoom_id = "#speaker-editor-zoom" if speaker else "#processor-source-zoom-range"
        audio_id = f"{prefix}-source-audio"
        audio = page.locator(f"#{audio_id}")
        try:
            page.goto(base_url.rstrip("/") + "/Audio-Editor.html")
            page.locator("#source-session-mode-device").click()
            page.locator("#processor-file").set_input_files([fixture(330, 8), fixture(660, 8)])
            page.locator(launcher).click()
            page.wait_for_function(f"!document.getElementById('{audio_id}-play').disabled", timeout=180000)
            assert page.locator(launcher).evaluate("e=>e===document.activeElement")
            # Neither gesture path needs keyboard focus or a pointer click in the studio.
            surface = page.locator(workspace + " " + surface_selector).first
            surface.scroll_into_view_if_needed(); box = surface.bounding_box()
            width = lambda: surface.evaluate("e=>e.firstElementChild.getBoundingClientRect().width")
            before = width()
            surface.dispatch_event("wheel", {"ctrlKey": True, "deltaY": -80, "clientX": box["x"] + 100, "clientY": box["y"] + 40})
            assert width() > before
            before = width()
            surface.evaluate("""e=>{
                for(const [type,scale] of [['gesturestart',1],['gesturechange',1.2],['gestureend',1.2]]) {
                    const ev=new Event(type,{bubbles:true,cancelable:true});
                    Object.defineProperties(ev,{clientX:{value:e.getBoundingClientRect().left+100},scale:{value:scale}});
                    e.dispatchEvent(ev);
                }
            }""")
            assert width() > before
            assert page.locator(launcher).evaluate("e=>e===document.activeElement")
            page.keyboard.press("Space")
            page.wait_for_function(f"!document.getElementById('{audio_id}').paused")
            assert page.locator("#announcement-processor-card audio" if speaker else "#speaker-editor audio").evaluate_all("nodes=>nodes.every(a=>a.paused)")
            page.wait_for_timeout(150); page.keyboard.press("Space")
            assert audio.evaluate("a=>a.paused && a.currentTime>0")
            # Pointer-clicked toolbar commands do not repeat themselves on Space.
            scale = page.locator(scale_id); scale.click()
            mode = page.locator(zoom_id).input_value()
            page.keyboard.press("Space")
            page.wait_for_function(f"!document.getElementById('{audio_id}').paused")
            assert page.locator(zoom_id).input_value() == mode
            page.keyboard.press("Space"); assert audio.evaluate("a=>a.paused")
            # Tab restores standard native button activation, including after a mouse click.
            page.keyboard.press("Tab"); page.keyboard.press("Shift+Tab")
            assert scale.evaluate("e=>e===document.activeElement")
            page.keyboard.press("Space")
            assert page.locator(zoom_id).input_value() != mode
            assert audio.evaluate("a=>a.paused")
            # Input fields retain Space; pinch does not steal their focus.
            field = page.locator("#speaker-editor-selection-start" if speaker else zoom_id)
            field.evaluate("e=>{e.closest('details')?.setAttribute('open','');e.focus()}")
            page.keyboard.press("Space"); assert audio.evaluate("a=>a.paused")
            before = width(); box = surface.bounding_box()
            surface.dispatch_event("wheel", {"ctrlKey": True, "deltaY": -50, "clientX": box["x"] + 100})
            assert width() > before and field.evaluate("e=>e===document.activeElement")
            before = width()
            surface.dispatch_event("wheel", {"deltaY": -50, "deltaX": 20})
            assert width() == before
            # Neutral page focus is enough; repeat and modifiers must not toggle playback.
            page.evaluate("document.activeElement.blur()")
            page.keyboard.press("Space"); page.wait_for_function(f"!document.getElementById('{audio_id}').paused")
            page.keyboard.press("Space"); assert audio.evaluate("a=>a.paused")
            page.locator("body").dispatch_event("keydown", {"code": "Space", "key": " ", "repeat": True})
            page.locator("body").dispatch_event("keydown", {"code": "Space", "key": " ", "isComposing": True})
            page.keyboard.press("Shift+Space"); assert audio.evaluate("a=>a.paused")
            # An open menu blocks the global shortcut even when focus is outside it.
            page.evaluate("document.body.insertAdjacentHTML('beforeend','<div role=menu id=focus-test-menu>Menu</div>')")
            page.keyboard.press("Space"); assert audio.evaluate("a=>a.paused")
            page.locator("#focus-test-menu").evaluate("e=>e.remove()")
            assert not errors, errors
            print(f"Input focus {prefix}: PASS (launcher/toolbar Space, Tab, fields, neutral focus, menu, unfocused wheel/gesture, normal wheel)", flush=True)
        finally:
            context.close()
