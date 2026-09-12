"""Tool-first editing: real gestures, source-time zoom and cancellation."""


def apply_selection(page, tool):
    """Keyboard application for existing numeric-selection regression fixtures."""
    button = page.locator('#speaker-editor-add-' + tool)
    if button.get_attribute('aria-pressed') != 'true':
        button.click()
    page.locator('.speaker-waveform').first.focus()
    page.keyboard.press('Enter')
    assert button.get_attribute('aria-pressed') == 'false', 'A successful keyboard commit must consume the tool'
    page.keyboard.press('Escape')


def restore_selection(page, tool):
    key = 'globalCuts' if tool == 'cut' else 'trackSilenceRegions'
    region_id = page.evaluate("""async key => {
        const payload = (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload;
        const start = Number(document.getElementById('speaker-editor-selection-start').value);
        const end = Number(document.getElementById('speaker-editor-selection-end').value);
        const trackId = document.getElementById('speaker-editor-selection-track').value;
        return payload[key].find(r => Math.abs(r.startSeconds-start)<.000001 && Math.abs(r.endSeconds-end)<.000001 && (key==='globalCuts'||r.trackId===trackId))?.regionId;
    }""", key)
    assert region_id, 'A corresponding region must exist'
    region = page.locator(f'#speaker-editor-tracks [data-region-id="{region_id}"]').first
    region.focus(); page.keyboard.press('Enter')
    button = page.locator('#speaker-editor-add-' + tool)
    assert button.get_attribute('data-mode') == 'restore'
    button.click()
    assert button.get_attribute('aria-pressed') == 'false', 'Restoring a region must not arm its creation tool'


def check_edit_modes(page, output=None):
    state = "async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload"
    rows = page.locator('.speaker-track')
    page.locator('.speaker-selection details').evaluate('e => e.open = true')
    baseline = page.evaluate(state)
    assert page.locator('.speaker-selection__actions button').evaluate_all(
        "bs => bs.map(b => b.id.replace('speaker-editor-',''))") == [
            'set-start','set-end','add-cut','add-silence']
    page.locator('#speaker-editor-zoom-fit').click()
    page.locator('#speaker-editor-add-cut').click()
    assert page.evaluate(state) == baseline, 'Arming an edit must not change the recipe'
    wave = rows.first.locator('.speaker-waveform-scroll')
    wave.scroll_into_view_if_needed(); b = wave.bounding_box()
    def start_drag(start=.22, end=.32):
        page.mouse.move(b['x'] + b['width']*start, b['y'] + b['height']*.6)
        page.mouse.down()
        page.mouse.move(b['x'] + b['width']*end, b['y'] + b['height']*.6, steps=5)
    start_drag()
    assert page.locator('.speaker-selection-overlay[data-scope=all]').count() == rows.count()
    assert page.evaluate(state) == baseline, 'Dragging is a preview until pointerup'
    if output: page.locator('#speaker-editor').screenshot(path=str(output/'tool-cut-during-drag.png'))
    page.keyboard.press('Escape'); page.mouse.up()
    assert page.evaluate(state) == baseline
    page.locator('#speaker-editor-add-cut').click()
    start_drag(); page.mouse.up()
    cut_payload = page.evaluate(state)
    cut = cut_payload['globalCuts'][-1]
    assert page.locator('#speaker-editor-add-cut').get_attribute('aria-pressed') == 'false'
    assert page.locator('#speaker-editor').get_attribute('data-edit-tool') == 'select'
    assert page.locator('.speaker-region-overlay--cut').count() == rows.count()
    # The next drag is an ordinary time/Loop selection and cannot create a second cut.
    start_drag(.38, .48); page.mouse.up()
    assert page.evaluate(state) == cut_payload
    page.locator('#speaker-editor-add-cut').click()
    start_drag(.38, .48); page.mouse.up()
    two_cuts = page.evaluate(state)
    assert len(two_cuts['globalCuts']) == len(cut_payload['globalCuts']) + 1
    assert page.locator('#speaker-editor-add-cut').get_attribute('aria-pressed') == 'false'
    restore_selection(page, 'cut')
    first_region = page.locator(f'#speaker-editor-tracks [data-region-id="{cut["regionId"]}"]').first
    first_region.focus(); page.keyboard.press('Enter')
    assert page.locator('#speaker-editor-add-cut').get_attribute('data-mode') == 'restore'
    page.locator('#speaker-editor-add-cut').click()
    assert page.evaluate(state) == baseline
    # A global preview includes an excluded row; cancellation preserves its
    # existing exclusion and does not commit a cut or leave a captured pointer.
    rows.nth(1).get_by_role('button',name='Исключить из микса',exact=True).click()
    excluded = page.evaluate(state)
    page.locator('#speaker-editor-add-cut').click()
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
    assert page.locator('#speaker-editor-add-silence').get_attribute('aria-pressed') == 'false'
    silence_payload = page.evaluate(state)
    start_drag(.42, .52); page.mouse.up()
    assert page.evaluate(state) == silence_payload
    silence_region = page.locator(f'#speaker-editor-tracks [data-region-id="{silence["regionId"]}"]').first
    silence_region.focus(); page.keyboard.press('Enter')
    assert page.locator('#speaker-editor-add-silence').get_attribute('data-mode') == 'restore'
    page.locator('#speaker-editor-add-silence').click()
    assert page.locator('#speaker-editor-add-silence').get_attribute('aria-pressed') == 'false'
    assert page.evaluate(state) == baseline
    # Invalid keyboard confirmation keeps the armed tool; Escape consumes it explicitly.
    page.locator('#speaker-editor-add-cut').click()
    page.locator('#speaker-editor-selection-start').fill('1')
    page.locator('#speaker-editor-selection-end').fill('1')
    page.locator('#speaker-editor-selection-end').press('Enter')
    assert page.evaluate(state) == baseline
    assert page.locator('#speaker-editor-add-cut').get_attribute('aria-pressed') == 'true'
    page.keyboard.press('Escape')
    assert page.locator('#speaker-editor-add-cut').get_attribute('aria-pressed') == 'false'
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
    restore_selection(page, 'cut')
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
        restore_selection(page, 'cut');assert page.evaluate(state)==baseline
        assert page.evaluate("async()=>(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().files.every((f,i)=>f===wordFiles[i])")
        page.keyboard.press('Escape')
    page.locator('#speaker-editor-zoom-fit' if speaker else '#processor-source-zoom-fit').click()
