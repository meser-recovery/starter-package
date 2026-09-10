"""Complementary timeline checks: zoomed seeking, cancelled flags and Retina.

Uses real local media and pointer/keyboard events; never connects to an archive.
"""
from pathlib import Path
from urllib.parse import urlparse
from s09a_smoke import fixture


def check_timeline_controls(browser, base_url, screenshot_dir=None):
    site = urlparse(base_url)
    output = Path(screenshot_dir)/'s09a-timeline' if screenshot_dir else None
    if output: output.mkdir(parents=True, exist_ok=True)
    for dpr in (1, 2):
        context = browser.new_context(viewport={'width':1280, 'height':900}, device_scale_factor=dpr, has_touch=True)
        context.add_init_script("sessionStorage.setItem('meser_service_access_v1','granted');window.__MESER_AUDIO_ARCHIVE_GATEWAY__='https://gateway.test';")
        context.route('**/*', lambda r: r.continue_() if urlparse(r.request.url).netloc == site.netloc else r.abort())
        page = context.new_page()
        try:
            page.goto(base_url.rstrip('/')+'/Audio-Editor.html')
            page.locator('#processor-file').set_input_files([fixture(330), fixture(660)])
            for mode, prefix, row_class, scroll_class, wave_class, zoom_id, rail_id in (
                ('announcement','processor-source-audio','processor-track','processor-waveform-scroll','processor-waveform','processor-source-zoom-range','processor-source-scrollbar'),
                ('speaker','speaker-editor-source-audio','speaker-track','speaker-waveform-scroll','speaker-waveform','speaker-editor-zoom','speaker-editor-source-scrollbar'),
            ):
                page.locator('#open-local-'+mode).click()
                page.wait_for_function('(id)=>!document.getElementById(id+"-play").disabled',arg=prefix)
                rows=page.locator('.'+row_class); scroll=rows.first.locator('.'+scroll_class); wave=rows.first.locator('.'+wave_class)
                audio=page.locator('#'+prefix)
                media_selector=('#speaker-editor' if mode=='speaker' else '#announcement-processor-card')+' audio[data-track-id]'
                for width in (320,390,768,1280):
                    page.set_viewport_size({'width':width,'height':900})
                    page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
                    fit_id='speaker-editor-zoom-fit' if mode=='speaker' else 'processor-source-zoom-fit'
                    page.locator('#'+fit_id).click()
                    zoom=page.locator('#'+zoom_id)
                    zoom.fill('4' if mode=='speaker' else '80')
                    zoom.dispatch_event('input')
                    scroll.evaluate('e=>e.scrollLeft=(e.scrollWidth-e.clientWidth)*.4')
                    page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
                    scroll.scroll_into_view_if_needed()
                    b=scroll.bounding_box()
                    geometry=scroll.evaluate('e=>({left:e.scrollLeft,width:e.firstElementChild.getBoundingClientRect().width})')
                    duration=audio.evaluate('a=>a.duration')
                    expected=(geometry['left']+b['width']*.4)/geometry['width']*duration
                    page.mouse.click(b['x']+b['width']*.4,b['y']+b['height']*.7)
                    times=page.locator(media_selector).evaluate_all('aa=>aa.map(a=>a.currentTime)')
                    assert abs(audio.evaluate('a=>a.currentTime')-expected)<.04,(mode,width,dpr,expected,times)
                    assert max(times)-min(times)<.06,(mode,width,dpr,times)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    assert page.locator('#'+rail_id).bounding_box()['y']>=rows.last.bounding_box()['y']+rows.last.bounding_box()['height']
                    if mode=='speaker':
                        assert rows.first.locator('canvas').evaluate('c=>Math.abs(c.width-c.getBoundingClientRect().width*devicePixelRatio)<=2')
                        assert rows.first.locator('canvas').evaluate('c=>{const p=c.getContext("2d").getImageData(0,0,c.width,c.height).data;return p.some((v,i)=>i%4===0&&v===116)}')
                    else:
                        assert rows.first.locator('img').evaluate('i=>i.complete&&i.naturalWidth>=4096')
                    if output:
                        page.evaluate('document.activeElement?.blur();scrollTo(0,0)')
                        page.screenshot(path=str(output/f'{mode}-zoom-scroll-{width}-dpr{dpr}.png'),full_page=True)
                page.locator('#'+fit_id).click()
                # Real playback must wrap repeatedly, retaining independent Mute.
                scroll.scroll_into_view_if_needed();b=scroll.bounding_box()
                page.mouse.move(b['x']+b['width']*.2,b['y']+b['height']*.7);page.mouse.down()
                page.mouse.move(b['x']+b['width']*.4,b['y']+b['height']*.7,steps=6);page.mouse.up()
                attr='data-action' if mode=='speaker' else 'data-track-action'
                rows.first.locator(f'[{attr}=mute]').click()
                page.evaluate('''id=>{const a=document.getElementById(id);window.timelineLoops=0;let previous=0;
                    const observe=()=>{if(a.currentTime<previous-.15)window.timelineLoops++;previous=a.currentTime;
                        if(window.timelineLoops<3)requestAnimationFrame(observe)};requestAnimationFrame(observe)}''',prefix)
                page.locator('#'+prefix+'-loop').click()
                page.wait_for_function('window.timelineLoops>=3',timeout=15000)
                flags=page.locator(media_selector).evaluate_all('aa=>aa.map(a=>a.muted)')
                assert flags==[True,False],(mode,flags)
                page.locator('#'+prefix+'-loop').click();page.locator('#'+prefix+'-stop').click()
                rows.first.locator(f'[{attr}=mute]').click()
                if mode=='speaker': check_flags_and_keyboard(page,output,dpr)
            print(f'Timeline controls: DPR {dpr}, both editors, four widths, zoom+scroll seek, three real loop cycles and independent Mute passed.',flush=True)
        finally: context.close()


def check_flags_and_keyboard(page,output,dpr):
    state="async ()=>(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload"
    baseline=page.evaluate(state);rows=page.locator('.speaker-track')
    for kind,direction in (('start',1),('end',-1)):
        flag=rows.first.locator('.speaker-boundary--'+kind)
        initial=flag.get_attribute('aria-valuenow');flag.scroll_into_view_if_needed();b=flag.bounding_box()
        page.mouse.move(b['x']+b['width']/2,b['y']+b['height']/2);page.mouse.down()
        page.mouse.move(b['x']+b['width']/2+direction*25,b['y']+b['height']/2,steps=5)
        assert flag.get_attribute('aria-valuenow')!=initial
        assert page.evaluate(state)==baseline
        flag.dispatch_event('pointercancel',{'pointerId':1});page.mouse.up()
        assert flag.get_attribute('aria-valuenow')==initial
        assert page.evaluate(state)==baseline
        flag.focus();page.keyboard.press('ArrowRight' if kind=='start' else 'ArrowLeft')
        assert abs(float(flag.get_attribute('aria-valuenow'))-float(initial)-direction*.1)<.00001
        page.keyboard.press('Shift+ArrowRight' if kind=='start' else 'Shift+ArrowLeft')
        assert abs(float(flag.get_attribute('aria-valuenow'))-float(initial)-direction*1.1)<.00001
        page.keyboard.press('Home' if kind=='start' else 'End')
        assert page.evaluate(state)==baseline
        assert flag.evaluate('e=>e===document.activeElement')
    for label in ('Улучшение','Выравнивание громкости'):
        switch=rows.first.get_by_role('switch',name=label,exact=True)
        switch.focus();page.keyboard.press('Space');assert switch.is_checked()
        assert switch.evaluate('e=>e===document.activeElement')
        page.keyboard.press('Space');assert not switch.is_checked()
    slider=rows.first.get_by_role('slider',name='Компрессия',exact=True);slider.focus();page.keyboard.press('Home')
    for i,preset in enumerate(('off','light','medium','strong')):
        if i:page.keyboard.press('ArrowRight')
        assert page.evaluate(state)['trackProcessing'][0]['compression']==preset
        assert slider.evaluate('e=>e===document.activeElement')
        assert slider.get_attribute('aria-valuetext') in ('Выкл.','Лёгкая','Средняя','Сильная')
    if output:
        page.evaluate('scrollTo(0,0)');page.screenshot(path=str(output/f'speaker-keyboard-dsp-dpr{dpr}.png'),full_page=True)
    page.keyboard.press('Home');assert page.evaluate(state)==baseline
    print(f'Timeline flags/DSP: DPR {dpr}, start/end drag cancellation, keyboard steps, focus, switches and four compression presets passed.',flush=True)
