"""Runs within the existing synthetic two-track speaker browser fixture."""

from s09a_edit_modes_smoke import apply_selection, restore_selection


def check_selection_tools(page, output=None):
    tools = page.locator('.speaker-selection__actions button')
    assert tools.count() == 4
    for button in tools.all():
        assert button.is_enabled()
        assert button.locator('svg[aria-hidden=true]').count() == 1
    rows = page.locator('.speaker-track')
    ids = rows.evaluate_all('rows => rows.map(row => row.dataset.trackId)')
    assert page.locator('#speaker-editor-source-audio').is_hidden()
    page.locator('#speaker-editor-source-audio-play').click()
    page.wait_for_function("[...document.querySelectorAll('#speaker-editor audio[data-track-id]')].every(a => !a.paused)")
    page.locator('#speaker-editor-source-audio-stop').click()
    page.wait_for_function("[...document.querySelectorAll('#speaker-editor audio[data-track-id]')].every(a => a.paused && a.currentTime < .1)")

    def monitoring():
        return page.evaluate("""() => [...document.querySelectorAll('#speaker-editor audio[data-track-id]')]
            .map(audio => [audio.dataset.trackId, audio.muted]).sort()""")

    def assert_audio(first, second):
        assert monitoring() == sorted([[ids[0], first], [ids[1], second]])

    assert_audio(False, False)
    rows.nth(0).locator('[data-action=mute]').click()
    assert_audio(True, False)
    page.locator('#speaker-editor .daw-monitor-volume input').fill('0.35')
    page.wait_for_function("[...document.querySelectorAll('#speaker-editor audio[data-track-id]')].every(a => Math.abs(a.volume - .35) < .001)")
    assert_audio(True, False)
    page.locator('#speaker-editor .daw-monitor-volume input').fill('1')
    assert rows.nth(1).locator('[data-action=mute]').get_attribute('aria-pressed') == 'false'
    rows.nth(0).locator('[data-action=mute]').click()
    rows.nth(1).locator('[data-action=solo]').click()
    assert_audio(True, False)
    assert 'Solo другой' in rows.nth(0).locator('.track-monitor-status').inner_text()
    assert rows.nth(0).locator('[data-action=mute]').get_attribute('aria-pressed') == 'false'
    rows.nth(0).locator('[data-action=solo]').click()
    assert_audio(False, False)
    rows.nth(1).locator('[data-action=solo]').click()
    assert_audio(False, True)
    rows.nth(0).locator('[data-action=solo]').click()
    assert_audio(False, False)
    rows.nth(1).locator('[data-action=mute]').click()
    assert_audio(False, True)
    rows.nth(1).locator('[data-action=mute]').click()

    # The ordinary shared range appears on every row during dragging. Arming
    # Silence then narrows the same interval to its stable target identity.
    wave = rows.nth(1).locator('.speaker-waveform')
    wave.scroll_into_view_if_needed()
    box = wave.bounding_box()
    page.mouse.move(box['x'] + box['width'] * .2, box['y'] + box['height'] * .5)
    page.mouse.down()
    page.mouse.move(box['x'] + box['width'] * .4, box['y'] + box['height'] * .5, steps=5)
    assert page.locator('.speaker-selection-overlay[data-scope=all]').count() == rows.count()
    page.mouse.up()
    assert page.locator('#speaker-editor-selection-track').input_value() == ids[1]
    assert 'Все дорожки' in page.locator('#speaker-selection-summary').inner_text()
    assert tools.locator('svg').count() == 4
    apply_selection(page, 'silence')
    payload = page.evaluate("async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload")
    assert payload['trackSilenceRegions'][0]['trackId'] == ids[1]
    assert payload['globalCuts'] == []
    page.locator('#speaker-editor-undo').click()
    apply_selection(page, 'cut')
    payload = page.evaluate("async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload")
    assert len(payload['globalCuts']) == 1
    assert payload['trackSilenceRegions'] == []
    assert rows.nth(0).locator('.speaker-region-overlay--cut').count() == 1
    assert rows.nth(1).locator('.speaker-region-overlay--cut').count() == 1
    page.locator('#speaker-editor-undo').click()

    from s09a_edit_modes_smoke import check_edit_modes
    check_edit_modes(page, output)
    check_waveform_interactions(page, output)
    from s09a_region_handles_smoke import check_region_handles
    check_region_handles(page, output)

    for width in (320, 390, 768, 1280):
        page.set_viewport_size({'width': width, 'height': 900})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert page.locator('.speaker-transport').evaluate("e => getComputedStyle(e).position") == 'sticky'
        page.locator('.speaker-selection').scroll_into_view_if_needed()
        boxes = tools.evaluate_all('buttons => buttons.map(b => {const r=b.getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom};})')
        for index, a in enumerate(boxes):
            for b in boxes[index+1:]:
                assert a['right'] <= b['x'] or b['right'] <= a['x'] or a['bottom'] <= b['y'] or b['bottom'] <= a['y']
        if output:
            page.screenshot(path=str(output / f'selection-tools-{width}.png'), full_page=True)
    page.set_viewport_size({'width': 1280, 'height': 900})
    page.locator('.speaker-selection details > summary').click()
    page.locator('#speaker-editor-selection-start').fill('0')
    page.locator('#speaker-editor-selection-end').fill('')
    page.locator('.speaker-selection details > summary').click()


def check_waveform_interactions(page, output=None):
    """Real DOM/media regression for the seven requested timeline improvements."""
    rows = page.locator('.speaker-track')
    wave = rows.first.locator('.speaker-waveform')
    state = "async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload"
    baseline = page.evaluate(state)
    def shot(name):
        if output:
            page.evaluate('document.activeElement?.blur();scrollTo(0,0)')
            page.screenshot(path=str(output/(name+'.png')),full_page=True)
    page.locator('#speaker-editor-zoom-fit').click()
    wave.scroll_into_view_if_needed()
    box = wave.bounding_box()
    wave.click(position={'x': box['width'] * .6, 'y': box['height'] * .6})
    times = page.locator('#speaker-editor audio[data-track-id]').evaluate_all('aa => aa.map(a => a.currentTime)')
    assert min(times) > 0 and max(times) - min(times) < .06
    before = times[0]
    page.locator('#speaker-editor-source-audio-play').click()
    page.wait_for_function('(t) => document.getElementById("speaker-editor-source-audio").currentTime > t', arg=before)
    page.locator('#speaker-editor-source-audio-stop').click()

    def select(left, right):
        wave.scroll_into_view_if_needed()
        b = wave.bounding_box()
        page.mouse.move(b['x'] + b['width'] * left, b['y'] + b['height'] * .6)
        page.mouse.down()
        page.mouse.move(b['x'] + b['width'] * right, b['y'] + b['height'] * .6, steps=6)
        page.mouse.up()

    select(.2, .4)
    page.evaluate("""() => {
        const a = document.getElementById('speaker-editor-source-audio');
        window.loopReturns = 0; let previous = 0;
        const observe = () => {
            if (a.currentTime < previous - .1) window.loopReturns++;
            previous = a.currentTime;
            if (window.loopReturns < 2) requestAnimationFrame(observe);
        };
        requestAnimationFrame(observe);
    }""")
    page.locator('#speaker-editor-source-audio-loop').click()
    page.wait_for_function('window.loopReturns >= 2', timeout=15000)
    shot('timeline-loop-active')
    times = page.locator('#speaker-editor audio[data-track-id]').evaluate_all('aa => aa.map(a => a.currentTime)')
    assert max(times) - min(times) < .08
    page.locator('#speaker-editor-source-audio-loop').click()
    page.locator('#speaker-editor-source-audio-stop').click()
    # Two different operations on one exact range, plus an unrelated cut.
    apply_selection(page, 'cut')
    apply_selection(page, 'silence')
    selected = page.evaluate(state)
    region_id = selected['trackSilenceRegions'][0]['regionId']
    select(.55, .65)
    apply_selection(page, 'cut')
    unrelated = page.evaluate(state)['globalCuts'][-1]
    shot('timeline-cuts-and-silence')
    rows.first.locator(f'[data-region-id="{region_id}"]').click()
    restore_selection(page, 'silence')
    restore_selection(page, 'cut')
    current = page.evaluate(state)
    assert current['trackSilenceRegions'] == []
    assert current['globalCuts'] == [unrelated]
    shot('timeline-selective-restore')
    rows.first.locator(f'[data-region-id="{unrelated["regionId"]}"]').focus()
    page.keyboard.press('Enter')
    restore_selection(page, 'cut')
    assert page.evaluate(state) == baseline

    for kind, delta in [('start', .05), ('end', -.05)]:
        flag = rows.first.locator(f'.speaker-boundary--{kind}')
        flag.scroll_into_view_if_needed()
        b = flag.bounding_box()
        lane_width = wave.bounding_box()['width']
        page.mouse.move(b['x'] + b['width'] / 2, b['y'] + b['height'] / 2)
        page.mouse.down()
        page.mouse.move(b['x'] + b['width'] / 2 + delta * lane_width, b['y'] + b['height'] / 2, steps=5)
        prior = page.evaluate(state)
        assert len(prior['globalCuts']) == (0 if kind == 'start' else 1), 'pointermove must not commit'
        page.mouse.up()
        assert len(page.evaluate(state)['globalCuts']) == (1 if kind == 'start' else 2)
    shot('timeline-dragged-boundaries')
    rows.first.locator('.speaker-boundary--start').focus(); page.keyboard.press('Home')
    rows.first.locator('.speaker-boundary--end').focus(); page.keyboard.press('End')
    assert page.evaluate(state) == baseline
    assert rows.first.locator('.speaker-boundary--end').evaluate('e => e === document.activeElement')

    if not rows.first.get_by_role('switch', name='Улучшение', exact=True).is_visible():
        rows.first.locator('.speaker-dsp-disclosure > summary').click()
    rows.first.get_by_role('switch', name='Улучшение', exact=True).check()
    rows.first.get_by_role('switch', name='Выравнивание громкости', exact=True).check()
    slider = rows.first.get_by_role('slider', name='Компрессия', exact=True)
    for index, preset in enumerate(('off', 'light', 'medium', 'strong')):
        slider.fill(str(index)); slider.dispatch_event('change')
        processing = page.evaluate(state)['trackProcessing']
        assert processing[0]['compression'] == preset
        assert processing[1] == baseline['trackProcessing'][1]
    rows.first.get_by_role('switch', name='Улучшение', exact=True).uncheck()
    rows.first.get_by_role('switch', name='Выравнивание громкости', exact=True).uncheck()
    slider.fill('0'); slider.dispatch_event('change')
    assert page.evaluate(state) == baseline
    rail = page.locator('#speaker-editor-source-scrollbar')
    assert rail.bounding_box()['y'] >= rows.last.bounding_box()['y'] + rows.last.bounding_box()['height']
    # Backing pixels grow with DPR; zoom changes the time window, not bitmap scaling.
    page.locator('#speaker-editor-zoom').fill('4'); page.locator('#speaker-editor-zoom').dispatch_event('input')
    info = rows.first.locator('canvas').evaluate('c => ({bitmap:c.width,css:c.getBoundingClientRect().width,dpr:devicePixelRatio})')
    assert abs(info['bitmap'] - info['css'] * min(3, max(1, info['dpr']))) <= 2
    page.locator('#speaker-editor-zoom-fit').click()


def check_announcement_selection(page):
    page.wait_for_function("!document.getElementById('processor-run').disabled")
    page.locator('#processor-source-zoom-fit').click()
    lane = page.locator('.processor-track .processor-waveform').first
    lane.scroll_into_view_if_needed(); box = lane.bounding_box()
    lane.click(position={'x': box['width'] * .5, 'y': box['height'] * .5})
    assert page.locator('#processor-source-audio').evaluate('a => a.currentTime') > 0
    page.mouse.move(box['x'] + box['width'] * .2, box['y'] + box['height'] * .5)
    page.mouse.down()
    page.mouse.move(box['x'] + box['width'] * .4, box['y'] + box['height'] * .5, steps=6)
    page.mouse.up()
    assert page.locator('.processor-selection-overlay').count() == 3
    loop = page.locator('#processor-source-audio-loop'); assert loop.is_enabled()
    loop.click()
    page.wait_for_function("!document.getElementById('processor-source-audio').paused && document.getElementById('processor-source-audio-loop').getAttribute('aria-pressed') === 'true'")
    assert loop.get_attribute('aria-pressed') == 'true'
    page.wait_for_timeout(900)
    time = page.locator('#processor-source-audio').evaluate('a=>a.currentTime')
    assert .5 < time < 1.3
    loop.click(); page.locator('#processor-source-audio-stop').click()
    rail = page.locator('#processor-source-scrollbar')
    rows = page.locator('.processor-track')
    assert rail.bounding_box()['y'] >= rows.last.bounding_box()['y'] + rows.last.bounding_box()['height']
    # Pointer cancellation restores the prior range without moving the playhead.
    before = page.locator('#processor-loop-selection-summary').inner_text()
    lane.scroll_into_view_if_needed(); box = lane.bounding_box()
    page.mouse.move(box['x'] + box['width'] * .6, box['y'] + box['height'] * .5); page.mouse.down()
    page.mouse.move(box['x'] + box['width'] * .8, box['y'] + box['height'] * .5)
    page.locator('.processor-track .processor-waveform-scroll').first.dispatch_event('pointercancel', {'pointerId': 1})
    page.mouse.up()
    assert page.locator('#processor-loop-selection-summary').inner_text() == before
    lane.click(position={'x': box['width'] * .1, 'y': box['height'] * .5})
    assert loop.is_disabled()
