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
        if output:
            page.evaluate('document.activeElement?.blur()')
            page.locator('#speaker-editor').screenshot(path=str(output/(name+'.png')))

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
        drag(handle,20)
        handle.evaluate('e=>e.releasePointerCapture(1)'); page.mouse.up()
        assert page.evaluate(state)==original and abs(region.bounding_box()['width']-width)<1
        # Keyboard edge changes commit once and preserve focus after rebuilding rows.
        handle.focus(); page.keyboard.press('ArrowLeft')
        assert abs(page.evaluate(state)[key][0]['endSeconds'] - original[key][0]['endSeconds'] + .01) < .000001
        page.keyboard.press('Shift+ArrowRight')
        assert abs(page.evaluate(state)[key][0]['endSeconds'] - original[key][0]['endSeconds'] - .99) < .000001
        assert handle.evaluate('e=>e===document.activeElement')
        restore_selection(page,tool); assert page.evaluate(state)==baseline
        assert page.locator('#speaker-editor-add-'+tool).get_attribute('data-mode')=='apply'
        page.keyboard.press('Escape')

    check_region_identity_and_collisions(page, baseline)

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
    # The actual source loop clips an oversized selection to recording bounds.
    for edge,value in [('start',0),('end',duration)]:
        page.locator('#speaker-editor-selection-'+edge).evaluate('(e,v)=>{e.value=v;e.dispatchEvent(new Event("input",{bubbles:true}))}',str(value))
    page.evaluate("""()=>{const a=document.getElementById('speaker-editor-source-audio');window.boundLoops=0;
        let previous=a.currentTime;const tick=()=>{if(a.currentTime<previous-.1)boundLoops++;previous=a.currentTime;
            if(boundLoops<2)requestAnimationFrame(tick)};requestAnimationFrame(tick)}""")
    page.locator('#speaker-editor-source-audio-loop').click()
    page.wait_for_function('window.boundLoops>=2',timeout=15000)
    assert page.locator('#speaker-editor-source-audio-loop').get_attribute('aria-pressed')=='true'
    title=page.locator('#speaker-editor-source-audio-loop').get_attribute('title')
    assert f'{start:.3f}–{end:.3f}' in title,title
    page.locator('#speaker-editor-source-audio-stop').click()
    page.locator('#speaker-editor-selection-end').evaluate('(e,v)=>{e.value=v;e.dispatchEvent(new Event("input",{bubbles:true}))}',str(start/2))
    assert page.locator('#speaker-editor-source-audio-loop').is_disabled()
    assert page.locator('#speaker-editor-source-audio-loop').get_attribute('aria-pressed')=='false'
    rows.first.locator('.speaker-boundary--start').focus(); page.keyboard.press('Home')
    rows.first.locator('.speaker-boundary--end').focus(); page.keyboard.press('End')
    assert page.evaluate(state)==baseline
    assert page.evaluate("async()=>(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().files.every((f,i)=>f===handleFiles[i])")
    for width in (320,390,768,1280):
        page.set_viewport_size({'width':width,'height':900})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.set_viewport_size({'width':1280,'height':900})
    print('Region handles, contextual restore, live flags and bounded playback: PASS',flush=True)


def check_region_identity_and_collisions(page, baseline):
    state = "async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload"
    rows = page.locator('#speaker-editor-tracks .speaker-track')

    def create(tool, start, end, row=0):
        page.keyboard.press('Escape')
        detail=page.locator('.speaker-selection details')
        if not detail.evaluate('e=>e.open'):detail.locator('summary').click()
        page.locator('#speaker-editor-selection-track').select_option(rows.nth(row).get_attribute('data-track-id'))
        for edge, value in [('start',start),('end',end)]:
            page.locator('#speaker-editor-selection-'+edge).evaluate(
                '(e,v)=>{e.value=v;e.dispatchEvent(new Event("input",{bubbles:true}))}', str(value))
        apply_selection(page,tool)

    def choose(region_id, row=0):
        region=rows.nth(row).locator(f'[data-region-id="{region_id}"]')
        region.focus();page.keyboard.press('Enter')
        return region

    def remove(region_id, tool, row=0):
        choose(region_id,row);page.locator('#speaker-editor-add-'+tool).click()

    # Coincident cut and silence remain distinct edits, selected by ID/type.
    create('cut',.5,1.1);create('silence',.5,1.1,1)
    current=page.evaluate(state);cut=current['globalCuts'][0];silence=current['trackSilenceRegions'][0]
    choose(cut['regionId']);assert page.locator('#speaker-editor-add-cut').get_attribute('data-mode')=='restore'
    page.locator('#speaker-editor-selection-start').evaluate('e=>{e.value=.6;e.dispatchEvent(new Event("input",{bubbles:true}))}')
    assert page.locator('#speaker-editor-add-cut').get_attribute('data-mode')=='apply'
    remove(cut['regionId'],'cut')
    assert page.evaluate(state)['globalCuts']==baseline['globalCuts']
    assert page.evaluate(state)['trackSilenceRegions']==[silence]
    remove(silence['regionId'],'silence',1);assert page.evaluate(state)==baseline

    for tool,key,row in [('cut','globalCuts',0),('silence','trackSilenceRegions',1)]:
        create(tool,.4,.8,row);create(tool,1.2,1.6,row)
        before=page.evaluate(state);region_id=before[key][0]['regionId']
        region=choose(region_id,row)
        pps=rows.nth(row).locator('.speaker-waveform').bounding_box()['width']/3
        for edge,delta in [('end',.6*pps),('start',.6*pps)]:
            handle=region.locator('[data-edge='+edge+']');handle.scroll_into_view_if_needed();box=handle.bounding_box()
            x,y=box['x']+box['width']/2,box['y']+box['height']/2
            width=region.bounding_box()['width']
            page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+delta,y)
            assert page.evaluate(state)==before
            assert abs(region.bounding_box()['width']-width)<1
            assert page.locator('#speaker-editor-selection-error').inner_text()
            page.mouse.up();assert page.evaluate(state)==before
        # Native touch input intentionally grabs the region edge, committing once.
        handle=region.locator('[data-edge=end]');handle.scroll_into_view_if_needed();box=handle.bounding_box()
        x,y=box['x']+box['width']/2,box['y']+box['height']/2
        touch=page.context.new_cdp_session(page)
        touch.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':x,'y':y}]})
        touch.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':x+20,'y':y}]})
        assert page.evaluate(state)==before
        assert region.bounding_box()['width']>width+15
        touch.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]});touch.detach()
        assert abs(page.evaluate(state)[key][0]['endSeconds']-.8-20/pps)<.002
        page.locator('#speaker-editor-undo').click();assert page.evaluate(state)==before
        for r in before[key]:remove(r['regionId'],tool,row)
        assert page.evaluate(state)==baseline
    page.keyboard.press('Escape')
    # Replacing prepared source state cancels an in-flight edge, including a
    # late pointerup from the detached element, and keeps the exact Files.
    create('cut',.5,1.1)
    before=page.evaluate(state);region=choose(before['globalCuts'][0]['regionId'])
    handle=region.locator('[data-edge=end]');handle.scroll_into_view_if_needed();box=handle.bounding_box()
    handle.evaluate('e=>window.oldRegionHandle=e')
    page.mouse.move(box['x']+box['width']/2,box['y']+box['height']/2);page.mouse.down()
    page.mouse.move(box['x']+box['width']/2+20,box['y']+box['height']/2)
    assert page.evaluate(state)==before
    page.evaluate("""async()=>{const m=await import('./scripts/speaker-editor.mjs');const s=m.getSpeakerSaveState();
        window.regionEpoch=s.sourceEpoch;
        await m.closeSpeakerEditor(true);
        await m.openSpeakerEditor({session:s.session,files:s.files});
        window.oldRegionHandle.dispatchEvent(new PointerEvent('pointerup',{pointerId:1,bubbles:true}));}""")
    page.mouse.up()
    assert page.evaluate(state)==baseline
    assert page.evaluate("async()=>(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().sourceEpoch>regionEpoch")
    assert page.evaluate("async()=>(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().files.every((f,i)=>f===handleFiles[i])")
    assert page.locator('[data-gesture-preview]').count()==0
    detail=page.locator('.speaker-selection details')
    if detail.evaluate('e=>e.open'):detail.locator('summary').click()
    print('Region safety: coincident ID restore, numeric reset, collision/inversion rejection, touch edges and replacement/late-pointer cancellation passed.',flush=True)
