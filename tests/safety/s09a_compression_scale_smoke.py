"""Browser geometry coverage for the Speaker compression control."""
from pathlib import Path
from urllib.parse import urlparse

from s09a_approved_timeline_ux_smoke import fixture


def check_compression_scale(browser, base_url, screenshot_dir=None):
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    context.add_init_script("sessionStorage.setItem('meser_service_access_v1','granted')")
    site = urlparse(base_url)
    context.route("**/*", lambda route: route.continue_() if urlparse(route.request.url).netloc == site.netloc else route.abort())
    page = context.new_page(); errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def geometry():
        values = page.evaluate("""() => [...document.querySelectorAll('.speaker-dsp-field--compression')]
          .filter(field => field.getBoundingClientRect().width > 0).slice(0,2).map(field => {
            const input=field.querySelector('input'), ticks=field.querySelector('.speaker-compression-ticks'), output=field.querySelector('.speaker-dsp-value');
            const range=input.getBoundingClientRect(), tickBox=ticks.getBoundingClientRect();
            const zoom=range.width/input.offsetWidth, thumb=16*zoom;
            const expected=[range.left+thumb/2,range.left+range.width/3+thumb/6,
              range.left+range.width*2/3-thumb/6,range.right-thumb/2];
            const labels=[...ticks.children].map(node => { const box=node.getBoundingClientRect(); return {left:box.left,right:box.right,center:(box.left+box.right)/2,text:node.textContent}; });
            return {range:{left:range.left,right:range.right,width:range.width},
              ticks:{left:tickBox.left,right:tickBox.right,width:tickBox.width}, expected, labels,
              fieldHeight:field.getBoundingClientRect().height, aria:input.getAttribute('aria-valuetext'),
              selected:{text:output.textContent,visible:output.getBoundingClientRect().width>0&&output.getBoundingClientRect().height>0}};
          })""")
        assert len(values) == 2, values
        for value in values:
            assert abs(value["range"]["left"] - value["ticks"]["left"]) < 0.75, value
            assert abs(value["range"]["width"] - value["ticks"]["width"]) < 0.75, value
            assert all(abs(label["center"] - expected) < 1.25 for label, expected in zip(value["labels"], value["expected"])), value
            assert all(value["labels"][index]["right"] <= value["labels"][index + 1]["left"] + 0.75 for index in range(3)), value
            assert [label["text"] for label in value["labels"]] == ["Выкл.", "Лёгкая", "Средняя", "Сильная"], value
            assert value["selected"]["visible"], value
        return values

    try:
        page.goto(base_url.rstrip("/") + "/Audio-Editor.html")
        page.locator("#source-session-mode-device").click()
        page.locator("#processor-file").set_input_files([fixture(330, 4), fixture(440, 4)])
        page.locator("#open-local-speaker").click()
        page.wait_for_function("!document.getElementById('speaker-editor-render').disabled", timeout=180000)
        normal = geometry()
        if screenshot_dir:
            target = Path(screenshot_dir); target.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(target / "speaker-compression-normal.png"), full_page=True)
        first = page.locator('.speaker-track [data-dsp-field="compression"]').first
        baseline_width = first.locator("xpath=..").evaluate("node => node.getBoundingClientRect().width")
        for value, label in ((0, "Выкл."), (1, "Лёгкая"), (2, "Средняя"), (3, "Сильная")):
            first.focus(); first.press("Home");
            for _ in range(value): first.press("ArrowRight")
            assert first.get_attribute("aria-valuetext") == label
            assert abs(first.locator("xpath=..").evaluate("node => node.getBoundingClientRect().width") - baseline_width) < 0.75

        page.locator("#speaker-editor-expand").click(); page.wait_for_timeout(100)
        expanded = geometry()
        assert all(item["fieldHeight"] > 0 for item in expanded)
        if screenshot_dir:
            page.screenshot(path=str(target / "speaker-compression-expanded.png"), full_page=True)

        page.locator("#speaker-editor-expand").click()
        for width in (767, 768):
            page.set_viewport_size({"width": width, "height": 900}); page.wait_for_timeout(50)
            for details in page.locator(".speaker-dsp-disclosure").all():
                if details.get_attribute("open") is None: details.locator("summary").click()
            geometry()
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator("#speaker-editor-scale-mode").click()
        page.locator("#speaker-editor-zoom").fill("148"); page.locator("#speaker-editor-zoom").dispatch_event("input")
        for details in page.locator(".speaker-dsp-disclosure").all():
            if details.get_attribute("open") is None: details.locator("summary").click()
        compact = geometry()
        assert all(item["fieldHeight"] > 0 for item in compact)
        for zoom in (1, 1.25, 1.5):
            page.evaluate("zoom => document.documentElement.style.zoom=String(zoom)", zoom)
            geometry()
        page.evaluate("document.documentElement.style.zoom='1'")
        if screenshot_dir: page.screenshot(path=str(Path(screenshot_dir) / "speaker-compression-compact-narrow.png"), full_page=True)
        assert not errors, errors
        print("Speaker compression scale: PASS (two controls, all values, normal/expanded/compact, 767/768/narrow and 100/125/150% zoom)", flush=True)
    finally:
        context.close()
