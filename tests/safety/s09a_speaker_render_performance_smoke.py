"""Real-browser coverage for Speaker loudness caching, input mapping and render stages."""
from urllib.parse import urlparse

from s09a_approved_timeline_ux_smoke import fixture


def check_speaker_render_performance(browser, base_url):
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    context.add_init_script("sessionStorage.setItem('meser_service_access_v1','granted')")
    context.add_init_script("""(() => {
      window.speakerRenderProbe = {messages: [], stages: [], workers: 0, terminated: 0};
      const NativeWorker = window.Worker;
      window.Worker = class extends NativeWorker {
        constructor(...args) { super(...args); this.probeId = ++window.speakerRenderProbe.workers; }
        postMessage(message, ...args) {
          window.speakerRenderProbe.messages.push({worker:this.probeId,type:message.type,path:message.data?.path,args:message.data?.args});
          return super.postMessage(message, ...args);
        }
        terminate() { window.speakerRenderProbe.terminated++; return super.terminate(); }
      };
      document.addEventListener('DOMContentLoaded', () => {
        const status = document.getElementById('speaker-editor-render-status');
        if (status) new MutationObserver(() => window.speakerRenderProbe.stages.push(status.textContent))
          .observe(status, {childList:true,subtree:true});
      });
    })();""")
    site = urlparse(base_url)
    context.route("**/*", lambda route: route.continue_() if urlparse(route.request.url).netloc == site.netloc else route.abort())
    page = context.new_page(); errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def analysis_count(messages):
        return len([message for message in messages if message["type"] == "EXEC" and
                    any("print_format=json" in str(arg) for arg in (message.get("args") or []))])

    def render(expected_analyses, expected_inputs=3):
        before = page.evaluate("({messages:window.speakerRenderProbe.messages.length,workers:window.speakerRenderProbe.workers})")
        page.locator("#speaker-editor-render").click()
        page.get_by_text("Финальная версия готова. В архив ничего не передавалось.", exact=True).wait_for(timeout=180000)
        result = page.evaluate("""async before => {
          const state=(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState();
          const bytes=new Uint8Array(await state.candidate.blob.arrayBuffer());
          const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');
          return {messages:window.speakerRenderProbe.messages.slice(before.messages),profile:state.renderProfile,hash,size:bytes.length,
            workersCreated:window.speakerRenderProbe.workers-before.workers};
        }""", before)
        assert analysis_count(result["messages"]) == expected_analyses, result
        writes = [message["path"] for message in result["messages"] if message["type"] == "WRITE_FILE" and
                  str(message.get("path") or "").startswith("speaker-input-")]
        assert len(writes) == expected_inputs and len(set(writes)) == expected_inputs, result
        assert result["profile"]["analysisExecCount"] == expected_analyses, result
        assert result["profile"]["analysisConcurrency"] <= 2, result
        if expected_analyses <= 1:
            assert result["profile"]["analysisConcurrency"] == 1 and result["workersCreated"] <= 1, result
        assert result["profile"]["includedTrackCount"] == expected_inputs, result
        assert result["profile"]["outcome"] == "success" and result["size"] > 0, result
        normalization = [line for line in result["profile"].get("finalLoudnormLog", [])
                         if line.startswith("Normalization Type:")]
        assert len(normalization) == expected_inputs, result
        assert all(line in {"Normalization Type:   Linear", "Normalization Type:   Dynamic"}
                   for line in normalization), result
        return result

    try:
        page.goto(base_url.rstrip("/") + "/Audio-Editor.html")
        page.locator("#source-session-mode-device").click()
        sources = [fixture(330, 6), fixture(440, 6), fixture(550, 6)]
        page.locator("#processor-file").set_input_files(sources)
        page.locator("#open-local-speaker").click()
        page.wait_for_function("!document.getElementById('speaker-editor-render').disabled", timeout=180000)
        page.get_by_text("Точное редактирование", exact=True).click()
        for index in range(3):
            page.locator('.speaker-track [data-dsp-field="leveling"]').nth(index).check()

        cold = render(3)
        assert cold["profile"]["cacheMisses"] == 3 and cold["profile"]["cacheHits"] == 0
        assert cold["profile"]["analysisConcurrency"] == 2 and cold["profile"]["analysisEngineCount"] == 2, cold
        assert cold["workersCreated"] == 2, cold
        assert {item.get("worker") for item in cold["profile"]["analyses"]} == {"main", "auxiliary"}, cold
        warm = render(0)
        assert warm["profile"]["cacheHits"] == 3 and warm["hash"] == cold["hash"]

        compression = page.locator('.speaker-track [data-dsp-field="compression"]').first
        compression.fill("3"); compression.dispatch_event("change")
        compressed = render(0)
        assert compressed["profile"]["cacheHits"] == 3

        page.locator('.speaker-track [data-dsp-field="enhancement"]').first.check()
        page.locator('.speaker-track [data-dsp-field="enhancement"]').nth(1).check()
        enhanced = render(2)
        assert enhanced["profile"]["cacheHits"] == 1 and enhanced["profile"]["cacheMisses"] == 2
        assert enhanced["profile"]["analysisConcurrency"] == 2, enhanced
        page.locator('.speaker-track [data-dsp-field="enhancement"]').nth(1).uncheck()

        page.locator("#speaker-editor-selection-start").fill("1")
        page.locator("#speaker-editor-selection-end").fill("1.4")
        page.locator("#speaker-editor-selection-track").select_option(index=1)
        page.locator("#speaker-editor-add-silence").click()
        page.locator(".speaker-waveform").nth(1).focus(); page.keyboard.press("Enter")
        silenced = render(1)
        assert silenced["profile"]["cacheHits"] == 2 and silenced["profile"]["cacheMisses"] == 1

        page.locator("#speaker-editor-selection-start").fill("2")
        page.locator("#speaker-editor-selection-end").fill("2.4")
        page.locator("#speaker-editor-add-cut").click()
        page.locator(".speaker-waveform").first.focus(); page.keyboard.press("Enter")
        cut = render(3)
        assert cut["profile"]["cacheMisses"] == 3

        page.locator(".speaker-track").nth(1).get_by_role("button", name="Исключить из микса", exact=True).click()
        excluded = render(0, 2)
        assert excluded["profile"]["cacheHits"] == 2
        page.locator(".speaker-track").first.get_by_role("button", name="Вниз", exact=True).click()
        reordered = render(0, 2)
        assert reordered["profile"]["cacheHits"] == 2
        page.locator(".speaker-track").filter(has_text="Participant-440.wav").get_by_role("button", name="Вернуть в микс", exact=True).click()
        returned = render(0)
        assert returned["profile"]["cacheHits"] == 3

        # A cancelled in-flight analysis cannot become ready in the cache.
        page.locator('.speaker-track').filter(has_text="Participant-550.wav").locator('[data-dsp-field="enhancement"]').check()
        before = page.evaluate("window.speakerRenderProbe.messages.length")
        page.locator("#speaker-editor-render").click()
        page.wait_for_function("""before => window.speakerRenderProbe.messages.slice(before).some(m =>
          m.type==='EXEC' && (m.args||[]).some(arg=>String(arg).includes('print_format=json')))""", arg=before, timeout=180000)
        page.locator("#speaker-editor-cancel").click()
        page.wait_for_function("!document.getElementById('speaker-editor-render').disabled", timeout=30000)
        retried = render(1)
        assert retried["profile"]["cacheMisses"] == 1

        # History traversal restores signal settings without manufacturing a new source
        # or re-running measurements that are already known for either state.
        page.locator("#speaker-editor-undo").click()
        undone = render(0)
        assert undone["profile"]["cacheHits"] == 3
        page.locator("#speaker-editor-redo").click()
        redone = render(0)
        assert redone["profile"]["cacheHits"] == 3

        stages = page.evaluate("window.speakerRenderProbe.stages")
        for label in ("Подготовка аудио", "Измерение громкости",
                      "Монтаж, обработка и кодирование", "Проверка результата", "Подготовка формы волны"):
            assert any(label in stage for stage in stages), (label, stages)

        # Re-selecting equal bytes under equal names creates new File objects and a fresh source context.
        page.locator("#processor-file").set_input_files(sources)
        if page.locator("#speaker-unsaved-discard").is_visible(): page.locator("#speaker-unsaved-discard").click()
        page.locator("#open-local-speaker").click()
        if page.locator("#speaker-unsaved-discard").is_visible(): page.locator("#speaker-unsaved-discard").click()
        page.wait_for_function("!document.getElementById('speaker-editor-render').disabled", timeout=180000)
        for index in range(3): page.locator('.speaker-track [data-dsp-field="leveling"]').nth(index).check()
        before = page.evaluate("({messages:window.speakerRenderProbe.messages.length,terminated:window.speakerRenderProbe.terminated})")
        page.locator("#speaker-editor-render").click()
        page.wait_for_function("""before => window.speakerRenderProbe.messages.slice(before.messages).filter(m =>
          m.type==='EXEC' && (m.args||[]).some(arg=>String(arg).includes('print_format=json'))).length===2""", arg=before, timeout=180000)
        page.locator("#speaker-editor-cancel").click()
        page.wait_for_function("!document.getElementById('speaker-editor-render').disabled", timeout=30000)
        assert page.evaluate("window.speakerRenderProbe.terminated",) - before["terminated"] == 2
        replaced = render(3)
        assert replaced["profile"]["cacheHits"] == 0 and replaced["profile"]["cacheMisses"] == 3

        # An auxiliary Worker infrastructure failure falls back exactly once to
        # the already loaded main engine without changing the DSP result path.
        for index in range(3): page.locator('.speaker-track [data-dsp-field="enhancement"]').nth(index).check()
        page.evaluate("window.__MESER_SPEAKER_TEST_AUX_LOAD_FAILURE__=true")
        fallback = render(3)
        assert fallback["profile"]["analysisConcurrencyRequested"] == 2, fallback
        assert fallback["profile"]["analysisConcurrency"] == 1, fallback
        assert str(fallback["profile"]["analysisFallbackReason"]).startswith("auxiliary-load:"), fallback
        assert fallback["workersCreated"] == 0, fallback

        # A real loudnorm -inf/invalid measurement fails closed and is retried, never cached as ready.
        page.locator("#processor-file").set_input_files([fixture(0, 2)])
        if page.locator("#speaker-unsaved-discard").is_visible(): page.locator("#speaker-unsaved-discard").click()
        page.locator("#open-local-speaker").click()
        if page.locator("#speaker-unsaved-discard").is_visible(): page.locator("#speaker-unsaved-discard").click()
        page.wait_for_function("!document.getElementById('speaker-editor-render').disabled", timeout=180000)
        page.locator('.speaker-track [data-dsp-field="leveling"]').check()
        for _ in range(2):
            before = page.evaluate("window.speakerRenderProbe.messages.length")
            page.locator("#speaker-editor-render").click()
            page.wait_for_function("!document.getElementById('speaker-editor-cancel').offsetParent && !document.getElementById('speaker-editor-render').disabled", timeout=180000)
            failure = page.evaluate("""async before => ({
              messages:window.speakerRenderProbe.messages.slice(before),
              state:(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState()
            })""", before)
            assert analysis_count(failure["messages"]) == 1, failure
            assert failure["state"]["candidate"] is None and failure["state"]["renderProfile"]["outcome"] == "failed", failure
        assert not errors, errors
        print("Speaker render performance: PASS (real analysis EXEC counts, LRU identity, included-input mapping, cancellation and honest stages)", flush=True)
    finally:
        context.close()


def check_speaker_parallel_equivalence(browser, base_url):
    """Sequential and parallel cold snapshots must produce identical DSP data and MP3 bytes."""
    site = urlparse(base_url)

    def cold(concurrency):
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        context.add_init_script(f"sessionStorage.setItem('meser_service_access_v1','granted'); window.__MESER_SPEAKER_ANALYSIS_CONCURRENCY__={concurrency}")
        context.route("**/*", lambda route: route.continue_() if urlparse(route.request.url).netloc == site.netloc else route.abort())
        page = context.new_page(); errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            page.goto(base_url.rstrip("/") + "/Audio-Editor.html")
            page.locator("#source-session-mode-device").click()
            page.locator("#processor-file").set_input_files([fixture(330, 6), fixture(440, 6), fixture(550, 6)])
            page.locator("#open-local-speaker").click()
            page.wait_for_function("!document.getElementById('speaker-editor-render').disabled", timeout=180000)
            for index in range(3):
                row = page.locator(".speaker-track").nth(index)
                row.locator('[data-dsp-field="enhancement"]').check()
                row.locator('[data-dsp-field="leveling"]').check()
                compression = row.locator('[data-dsp-field="compression"]')
                compression.fill("1"); compression.dispatch_event("change")
            page.locator("#speaker-editor-render").click()
            page.get_by_text("Финальная версия готова. В архив ничего не передавалось.", exact=True).wait_for(timeout=180000)
            result = page.evaluate("""async () => {
              const state=(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState();
              const bytes=new Uint8Array(await state.candidate.blob.arrayBuffer());
              const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');
              return {hash,duration:state.candidate.resultDurationSeconds,
                measurements:state.renderProfile.analyses.map(item=>item.measurements),
                settings:state.renderProfile.settings.map(({trackId,...setting})=>setting),
                normalization:state.renderProfile.finalLoudnormLog,
                concurrency:state.renderProfile.analysisConcurrency};
            }""")
            assert not errors, errors
            return result
        finally:
            context.close()

    sequential = cold(1); parallel = cold(2)
    assert sequential["concurrency"] == 1 and parallel["concurrency"] == 2
    assert sequential["measurements"] == parallel["measurements"], (sequential, parallel)
    assert sequential["settings"] == parallel["settings"]
    assert sequential["normalization"] == parallel["normalization"]
    assert sequential["duration"] == parallel["duration"] and sequential["hash"] == parallel["hash"]
    print("Speaker parallel equivalence: PASS (measurements, settings, normalization log, duration and MP3 SHA-256)", flush=True)
