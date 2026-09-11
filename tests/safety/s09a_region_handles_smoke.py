"""Real pointer/capture and native-media regression on the existing two-track fixture."""
from s09a_edit_modes_smoke import apply_selection, restore_selection


def check_region_handles(page, output=None):
    state = "async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload"
    baseline = page.evaluate(state)
    rows = page.locator('#speaker-editor-tracks .speaker-track')
    page.keyboard.press('Escape')
    page.locator('#speaker-editor-zoom-fit').click()
    page.locator('#speaker-editor-source-audio-stop').click()
    page.evaluate("async()=>{window.handleFiles=(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().files}")

    def select(a, b, row=0):
        wave = rows.nth(row).locator('.speaker-waveform')
        wave.scroll_into_view_if_needed(); box = wave.bounding_box()
        y = box['y'] + box['height'] * .6
        page.mouse.move(box['x'] + box['width'] * a, y); page.mouse.down()
        page.mouse.move(box['x'] + box['width'] * b, y, steps=4); page.mouse.up()

    def drag(handle, delta):
        handle.scroll_into_view_if_needed(); b = handle.bounding_box()
        x, y = b['x'] + b['width']/2, b['y'] + b['height']/2
        page.mouse.move(x, y); page.mouse.down(); page.mouse.move(x+delta, y, steps=6)

    def shot(name):
        if output: page.locator('#speaker-editor').screenshot(path=str(output/(name+'.png')))

    for tool, key, row in [('cut', 'globalCuts', 0), ('silence', 'trackSilenceRegions', 1)]:
        select(.25,.45,row); apply_selection(page,tool)
        original = page.evaluate(state)
        region_id = original[key][0]['regionId']
        region = rows.nth(row).locator(f'[data-region-id="{region_id}"]')
        region.focus(); page.keyboard.press('Enter')
        assert page.locator('#speaker-editor-add-'+tool).get_attribute('data-mode')=='restore'
        other = 'silence' if tool=='cut' else 'cut'
        assert page.locator('#speaker-editor-add-'+other).get_attribute('data-mode')=='apply'
        assert page.locator('[id^=speaker-editor-restore-]').count()==0
        for edge, delta in [('start',-25),('end',25)]:
            original = page.evaluate(state)
            width = region.bounding_box()['width']
            handle = region.locator('[data-edge='+edge+']')
            drag(handle,delta)
            assert region.bounding_box()['width'] > width+20, 'Width must visibly change before release'
            assert page.evaluate(state)==original, 'Pointermove must not mutate the saved recipe'
            if tool=='cut':
                widths=page.locator(f'#speaker-editor-tracks [data-region-id="{region_id}"]').evaluate_all('rr=>rr.map(r=>r.getBoundingClientRect().width)')
                assert len(widths)==2 and abs(widths[0]-widths[1])<1
            else: assert rows.first.locator('.speaker-region-overlay--silence').count()==0
            shot('resize-'+tool+'-'+edge+'-live')
            page.mouse.up()
            changed=page.evaluate(state)
            assert changed!=original and changed[key][0]['regionId']==region_id
            page.locator('#speaker-editor-undo').click(); assert page.evaluate(state)==original
            page.locator('#speaker-editor-redo').click(); assert page.evaluate(state)==changed
        original=page.evaluate(state)
        width=region.bounding_box()['width']
        drag(region.locator('[data-edge=end]'),20)
        page.keyboard.press('Escape'); page.mouse.up()
        assert page.evaluate(state)==original and abs(region.bounding_box()['width']-width)<1
        handle=region.locator('[data-edge=end]'); drag(handle,20)
        handle.dispatch_event('pointercancel',{'pointerId':1}); page.mouse.up()
        assert page.evaluate(state)==original and abs(region.bounding_box()['width']-width)<1
        # Keyboard edge changes commit once and preserve focus after rebuilding rows.
        handle.focus(); page.keyboard.press('ArrowLeft')
        assert page.evaluate(state)[key][0]['endSeconds'] < original[key][0]['endSeconds']
        assert handle.evaluate('e=>e===document.activeElement')
        restore_selection(page,tool); assert page.evaluate(state)==baseline
        assert page.locator('#speaker-editor-add-'+tool).get_attribute('data-mode')=='apply'
        page.keyboard.press('Escape')

    # Word-scale resizing uses source seconds, not overview pixels.
    select(.25,.45); apply_selection(page,'cut')
    region_id=page.evaluate(state)['globalCuts'][0]['regionId']
    zoom=page.locator('#speaker-editor-zoom'); zoom.fill(zoom.get_attribute('max')); zoom.dispatch_event('input')
    region=rows.first.locator(f'[data-region-id="{region_id}"]')
    handle=region.locator('[data-edge=end]')
    handle.scroll_into_view_if_needed()
    duration=page.evaluate("async()=>(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().originalDuration")
    pps=rows.first.locator('.speaker-waveform').bounding_box()['width']/duration
    assert pps>=1000
    before=page.evaluate(state)['globalCuts'][0]['endSeconds']
    drag(handle,25); page.mouse.up()
    after=page.evaluate(state)['globalCuts'][0]['endSeconds']
    assert abs(after-before-25/pps)<.002
    restore_selection(page,'cut'); assert page.evaluate(state)==baseline
    page.keyboard.press('Escape'); page.locator('#speaker-editor-zoom-fit').click()

    # Entire-recording flags paint their excluded span during the gesture too.
    for kind, delta in [('start',70),('end',-70)]:
        flag=rows.first.locator('.speaker-boundary--'+kind)
        original=page.evaluate(state)
        before=float(flag.get_attribute('aria-valuenow'))
        drag(flag,delta)
        assert abs(float(flag.get_attribute('aria-valuenow'))-before)>.01
        assert page.locator('[data-gesture-preview]').count()==2
        assert page.evaluate(state)==original
        shot('recording-'+kind+'-live')
        page.keyboard.press('Escape'); page.mouse.up()
        assert page.evaluate(state)==original
        assert abs(float(flag.get_attribute('aria-valuenow'))-before)<.000001
        assert page.locator('[data-gesture-preview]').count()==0
        drag(flag,delta); page.mouse.up()
        assert page.evaluate(state)!=original
    cuts=page.evaluate(state)['globalCuts']
    start=next(r['endSeconds'] for r in cuts if r['startSeconds']==0)
    duration=page.evaluate("async()=>(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().originalDuration")
    end=next(r['startSeconds'] for r in cuts if r['endSeconds']==duration)
    page.locator('#speaker-editor-source-audio-stop').click()
    page.wait_for_function('(s)=>Math.abs(document.getElementById("speaker-editor-source-audio").currentTime-s)<.02',arg=start)
    page.locator('#speaker-editor-source-audio-play').click()
    page.wait_for_function('document.getElementById("speaker-editor-source-audio").paused',timeout=10000)
    times=page.locator('#speaker-editor audio[data-track-id]').evaluate_all('aa=>aa.map(a=>a.currentTime)')
    assert all(abs(t-end)<.06 for t in times), times
    assert page.locator('#speaker-editor audio[data-track-id]').evaluate_all('aa=>aa.every(a=>a.paused)')
    # Replay starts at the marked start. Source loop is clipped to those bounds.
    page.locator('#speaker-editor-source-audio-play').click()
    page.wait_for_function('(s)=>{const a=document.getElementById("speaker-editor-source-audio");return !a.paused&&a.currentTime>=s&&a.currentTime<s+.5}',arg=start)
    page.locator('#speaker-editor-source-audio-stop').click()
    assert page.locator('#speaker-editor-source-audio-loop').inner_text()=='Loop'
    assert page.locator('#speaker-editor-source-audio-loop svg').evaluate('e=>getComputedStyle(e).fill')=='none'
    rows.first.locator('.speaker-boundary--start').focus(); page.keyboard.press('Home')
    rows.first.locator('.speaker-boundary--end').focus(); page.keyboard.press('End')
    assert page.evaluate(state)==baseline
    assert page.evaluate("async()=>(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().files.every((f,i)=>f===handleFiles[i])")
    for width in (320,390,768,1280):
        page.set_viewport_size({'width':width,'height':900})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.set_viewport_size({'width':1280,'height':900})
    print('Region handles, contextual restore, live flags and bounded playback: PASS',flush=True)
