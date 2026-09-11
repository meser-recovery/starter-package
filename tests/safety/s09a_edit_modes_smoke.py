"""Tool-first editing: real gestures, source-time zoom and cancellation."""


def apply_selection(page, tool):
    """Keyboard application for existing numeric-selection regression fixtures."""
    button = page.locator('#speaker-editor-add-' + tool)
    if button.get_attribute('aria-pressed') != 'true':
        button.click()
    page.locator('.speaker-waveform').first.focus()
    page.keyboard.press('Enter')
    page.keyboard.press('Escape')


def check_edit_modes(page, output=None):
    state = "async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload"
    rows = page.locator('.speaker-track')
    baseline = page.evaluate(state)
    assert page.locator('.speaker-selection__actions button').evaluate_all(
        "bs => bs.map(b => b.id.replace('speaker-editor-',''))") == [
            'set-start','set-end','add-cut','restore-cut','add-silence','restore-silence']
    page.locator('#speaker-editor-zoom-fit').click()
    page.locator('#speaker-editor-add-cut').click()
    assert page.evaluate(state) == baseline, 'Arming an edit must not change the recipe'
    wave = rows.first.locator('.speaker-waveform-scroll')
    wave.scroll_into_view_if_needed(); b = wave.bounding_box()
    def start_drag():
        page.mouse.move(b['x'] + b['width']*.22, b['y'] + b['height']*.6)
        page.mouse.down()
        page.mouse.move(b['x'] + b['width']*.32, b['y'] + b['height']*.6, steps=5)
    start_drag()
    assert page.locator('.speaker-selection-overlay[data-scope=all]').count() == rows.count()
    assert page.evaluate(state) == baseline, 'Dragging is a preview until pointerup'
    if output: page.locator('#speaker-editor').screenshot(path=str(output/'tool-cut-during-drag.png'))
    page.keyboard.press('Escape'); page.mouse.up()
    assert page.evaluate(state) == baseline
    page.locator('#speaker-editor-add-cut').click()
    start_drag(); page.mouse.up()
    cut = page.evaluate(state)['globalCuts'][-1]
    assert page.locator('.speaker-region-overlay--cut').count() == rows.count()
    page.locator('#speaker-editor-restore-cut').click()
    assert page.evaluate(state) == baseline
    # A global preview includes an excluded row; cancellation preserves its
    # existing exclusion and does not commit a cut or leave a captured pointer.
    rows.nth(1).get_by_role('button',name='Исключить из микса',exact=True).click()
    excluded = page.evaluate(state)
    wave.scroll_into_view_if_needed(); b = wave.bounding_box(); start_drag()
    assert page.locator('.speaker-selection-overlay[data-scope=all]').count() == rows.count()
    assert rows.nth(1).locator('.speaker-selection-overlay').count() == 1
    assert page.evaluate(state) == excluded
    rows.first.locator('.speaker-waveform').dispatch_event('pointercancel', {'pointerId':1})
    page.mouse.up(); assert page.evaluate(state) == excluded
    assert page.locator('#speaker-editor-add-cut').get_attribute('aria-pressed') == 'true'
    rows.nth(1).get_by_role('button',name='Вернуть в микс',exact=True).click()
    assert page.evaluate(state) == baseline
    page.locator('#speaker-editor-add-silence').click()
    wave = rows.nth(1).locator('.speaker-waveform-scroll')
    wave.scroll_into_view_if_needed(); b = wave.bounding_box()
    start_drag()
    assert rows.first.locator('.speaker-selection-overlay').count() == 0
    assert rows.nth(1).locator('.speaker-selection-overlay').count() == 1
    rows.nth(1).locator('.speaker-waveform').dispatch_event('pointercancel', {'pointerId':1})
    page.mouse.up(); assert page.evaluate(state) == baseline
    assert page.locator('#speaker-editor-add-silence').get_attribute('aria-pressed') == 'true'
    start_drag()
    page.mouse.up()
    assert page.evaluate(state)['globalCuts'] == baseline['globalCuts']
    silence = page.evaluate(state)['trackSilenceRegions'][-1]
    assert silence['trackId'] == rows.nth(1).get_attribute('data-track-id')
    page.locator('#speaker-editor-restore-silence').click()
    assert page.evaluate(state) == baseline
    page.keyboard.press('Escape')
    # Max zoom must permit a 100ms word fragment to occupy ~100 CSS pixels.
    zoom = page.locator('#speaker-editor-zoom')
    zoom.fill(zoom.get_attribute('max')); zoom.dispatch_event('input')
    wave = rows.first.locator('.speaker-waveform-scroll')
    wave.evaluate('e => e.scrollLeft = 0')
    wave.scroll_into_view_if_needed(); b = wave.bounding_box()
    pps = wave.evaluate('e => e.firstElementChild.getBoundingClientRect().width') / page.evaluate(
        "async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().originalDuration")
    assert pps >= 990, pps
    page.locator('#speaker-editor-add-cut').click()
    wave.scroll_into_view_if_needed(); b = wave.bounding_box()
    page.mouse.move(b['x']+70,b['y']+b['height']*.6); page.mouse.down()
    page.mouse.move(b['x']+170,b['y']+b['height']*.6,steps=6); page.mouse.up()
    cut = page.evaluate(state)['globalCuts'][-1]
    assert abs(cut['endSeconds']-cut['startSeconds']-100/pps)<.002,cut
    if output: page.locator('#speaker-editor').screenshot(path=str(output/'tool-word-cut.png'))
    page.locator('#speaker-editor-restore-cut').click()
    assert page.evaluate(state) == baseline
    page.keyboard.press('Escape'); page.locator('#speaker-editor-zoom-fit').click()
    page.locator('.speaker-waveform').first.click(position={'x':80,'y':60})


def check_word_detail(page, mode, output=None):
    speaker = mode == 'speaker'
    zoom = page.locator('#speaker-editor-zoom' if speaker else '#processor-source-zoom-range')
    zoom.fill(zoom.get_attribute('max')); zoom.dispatch_event('input')
    scroll = page.locator('.speaker-waveform-scroll' if speaker else '.processor-waveform-scroll').first
    scroll.evaluate('e => e.scrollLeft = 80000')
    scroll.scroll_into_view_if_needed()
    selector = '#speaker-editor-tracks .speaker-waveform canvas' if speaker else '.processor-waveform-detail'
    page.wait_for_function('(s) => [...document.querySelectorAll(s)].length === 2 && [...document.querySelectorAll(s)].every(c => c.dataset.waveDetail === "ready" && +c.dataset.detailStart >= 72)', arg=selector, timeout=60000)
    info = page.locator(selector).evaluate_all('cs => cs.map(c => ({width:c.width,css:c.getBoundingClientRect().width,start:+c.dataset.detailStart,span:+c.dataset.detailDuration,bins:+c.dataset.detailBins}))')
    assert all(x['span']<=32 and x['bins']>=x['span']*1000 and abs(x['width']-x['css']*page.evaluate('devicePixelRatio'))<=2 for x in info),info
    b = scroll.bounding_box()
    geometry=scroll.evaluate('e=>({left:e.scrollLeft,width:e.firstElementChild.getBoundingClientRect().width})')
    audio=page.locator('#speaker-editor-source-audio' if speaker else '#processor-source-audio')
    expected=(geometry['left']+100)/geometry['width']*audio.evaluate('a=>a.duration')
    page.mouse.click(b['x']+100,b['y']+b['height']*.65)
    assert abs(audio.evaluate('a=>a.currentTime')-expected)<.02
    if output: page.locator('#speaker-editor' if speaker else '#announcement-processor-card').screenshot(path=str(output/(mode+'-word-detail.png')))
    if speaker:
        state = "async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload"
        baseline = page.evaluate(state)
        page.evaluate("async()=>{window.wordFiles=(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().files}")
        page.locator('#speaker-editor-add-cut').click()
        scroll.scroll_into_view_if_needed(); b=scroll.bounding_box()
        pps=scroll.evaluate('e=>e.firstElementChild.getBoundingClientRect().width')/audio.evaluate('a=>a.duration')
        page.mouse.move(b['x']+100,b['y']+b['height']*.65);page.mouse.down()
        page.mouse.move(b['x']+200,b['y']+b['height']*.65,steps=6)
        assert page.evaluate(state)==baseline
        assert page.locator('.speaker-selection-overlay[data-scope=all]').count()==2
        page.mouse.up()
        current=page.evaluate(state);assert len(current['globalCuts'])==len(baseline['globalCuts'])+1
        cut=current['globalCuts'][-1];assert abs(cut['endSeconds']-cut['startSeconds']-100/pps)<.002
        if output: page.locator('#speaker-editor').screenshot(path=str(output/'hour-recording-word-cut.png'))
        page.locator('#speaker-editor-restore-cut').click();assert page.evaluate(state)==baseline
        assert page.evaluate("async()=>(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().files.every((f,i)=>f===wordFiles[i])")
        page.keyboard.press('Escape')
    page.locator('#speaker-editor-zoom-fit' if speaker else '#processor-source-zoom-fit').click()
