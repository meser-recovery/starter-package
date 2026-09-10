"""Runs within the existing synthetic two-track speaker browser fixture."""


def check_selection_tools(page, output=None):
    tools = page.locator('.speaker-selection__actions button')
    assert tools.count() == 4
    for button in tools.all():
        assert button.is_disabled()
        assert button.locator('svg[aria-hidden=true]').count() == 1
    rows = page.locator('.speaker-track')
    ids = rows.evaluate_all('rows => rows.map(row => row.dataset.trackId)')

    def monitoring():
        return page.evaluate("""() => [...document.querySelectorAll('#speaker-editor audio[data-track-id]')]
            .map(audio => [audio.dataset.trackId, audio.muted]).sort()""")

    def assert_audio(first, second):
        assert monitoring() == sorted([[ids[0], first], [ids[1], second]])

    assert_audio(False, False)
    rows.nth(0).locator('[data-action=mute]').click()
    assert_audio(True, False)
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

    # The range appears during dragging, before pointerup. A one-track silence
    # must retain the target's stable ID; a global cut must stay global.
    wave = rows.nth(1).locator('.speaker-waveform')
    wave.scroll_into_view_if_needed()
    box = wave.bounding_box()
    page.mouse.move(box['x'] + box['width'] * .2, box['y'] + box['height'] * .5)
    page.mouse.down()
    page.mouse.move(box['x'] + box['width'] * .4, box['y'] + box['height'] * .5, steps=5)
    assert rows.nth(1).locator('.speaker-selection-overlay').count() == 1
    assert rows.nth(0).locator('.speaker-selection-overlay').count() == 0
    page.mouse.up()
    assert page.locator('#speaker-editor-selection-track').input_value() == ids[1]
    assert 'Дорожка 2' in page.locator('#speaker-editor-selection-scope').inner_text()
    assert tools.locator('svg').count() == 4
    page.locator('#speaker-editor-add-silence').click()
    payload = page.evaluate("async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload")
    assert payload['trackSilenceRegions'][0]['trackId'] == ids[1]
    assert payload['globalCuts'] == []
    page.locator('#speaker-editor-undo').click()
    page.locator('#speaker-editor-add-cut').click()
    payload = page.evaluate("async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload")
    assert len(payload['globalCuts']) == 1
    assert payload['trackSilenceRegions'] == []
    assert rows.nth(0).locator('.speaker-region-overlay--cut').count() == 1
    assert rows.nth(1).locator('.speaker-region-overlay--cut').count() == 1
    page.locator('#speaker-editor-undo').click()

    for width in (320, 390, 768, 1280):
        page.set_viewport_size({'width': width, 'height': 900})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
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
