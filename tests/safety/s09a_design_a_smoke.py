"""Approved A: stable DSP viewport and real edit-aware audition (no audio mocks)."""
import io
import math
import struct
import wave
from pathlib import Path
from urllib.parse import urlparse
from s09a_edit_modes_smoke import apply_selection, restore_selection


def check_design_a(browser, base_url, screenshot_dir=None):
    context = browser.new_context(viewport={'width':1440,'height':1000}, device_scale_factor=2)
    context.add_init_script("sessionStorage.setItem('meser_service_access_v1','granted')")
    site=urlparse(base_url)
    context.route('**/*', lambda r: r.continue_() if urlparse(r.request.url).netloc==site.netloc else r.abort())
    page=context.new_page(); errors=[]; page.on('pageerror',lambda e:errors.append(str(e)))
    output=Path(screenshot_dir)/'s09a-design-a' if screenshot_dir else None
    if output: output.mkdir(parents=True,exist_ok=True)
    try:
        page.goto(base_url.rstrip('/')+'/Audio-Editor.html')
        files=[]
        for hz in (330,660):
            data=io.BytesIO()
            with wave.open(data,'wb') as out:
                out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000)
                out.writeframes(b''.join(struct.pack('<h',round(6000*(.3+.7*abs(math.sin(i/16000*3.7))*abs(math.sin(i/16000*11.1)))*math.sin(i*hz*2*math.pi/16000))) for i in range(16000*12)))
            files.append({'name':f'Participant-{hz}.wav','mimeType':'audio/wav','buffer':data.getvalue()})
        page.locator('#processor-file').set_input_files(files)
        page.locator('#open-local-speaker').click()
        page.wait_for_function("!document.getElementById('speaker-editor-source-audio-play').disabled")
        # Repeated DSP changes at several zoom factors retain the actual row,
        # canvas, viewport and native audio objects, including undo/redo.
        rows=page.locator('.speaker-track'); zoom=page.locator('#speaker-editor-zoom')
        for factor in (2,8,32):
            zoom.evaluate('(e,value)=>{e.value=String(Math.min(value,Number(e.max)));e.dispatchEvent(new Event("input",{bubbles:true}))}',factor)
            page.locator('.speaker-waveform-scroll').first.evaluate('e=>e.scrollLeft=450')
            page.wait_for_timeout(100)
            page.evaluate("window.savedRows=[...document.querySelectorAll('.speaker-track')];window.savedCanvases=savedRows.map(e=>e.querySelector('canvas'));window.savedAudio=[...document.querySelectorAll('#speaker-editor audio[data-track-id]')]")
            geometry="() => [...document.querySelectorAll('.speaker-track')].map(e=>{const s=e.querySelector('.speaker-waveform-scroll'),r=e.getBoundingClientRect();return [s.scrollLeft,s.firstElementChild.getBoundingClientRect().width,r.height,r.y+scrollY]})"
            before=page.evaluate(geometry)
            for field in ('Улучшение','Выравнивание громкости'):
                rows.first.get_by_label(field,exact=True).evaluate("e=>{e.checked=!e.checked;e.dispatchEvent(new Event('change',{bubbles:true}))}")
            rows.first.get_by_label('Компрессия',exact=True).evaluate("e=>{e.value=e.value==='3'?'0':'3';e.dispatchEvent(new Event('change',{bubbles:true}))}")
            page.locator('#speaker-editor-undo').evaluate('e=>e.click()');page.locator('#speaker-editor-redo').evaluate('e=>e.click()')
            assert page.evaluate(geometry)==before, (before,page.evaluate(geometry))
            assert page.evaluate("savedRows.every((r,i)=>r===document.querySelectorAll('.speaker-track')[i]&&savedCanvases[i]===r.querySelector('canvas')) && savedAudio.every((a,i)=>a===document.querySelectorAll('#speaker-editor audio[data-track-id]')[i])")
        page.locator('#speaker-editor-zoom-fit').click()
        def select(start,end):
            detail=page.locator('.speaker-selection>details');detail.evaluate('e=>e.open=true')
            for suffix,value in [('start',start),('end',end)]:
                page.locator('#speaker-editor-selection-'+suffix).fill(str(value))
                page.locator('#speaker-editor-selection-'+suffix).dispatch_event('change')
        select(2,5);apply_selection(page,'silence')
        select(6,8);apply_selection(page,'cut')
        select(1,11);page.locator('#speaker-editor-set-start').click();page.locator('#speaker-editor-set-end').click()
        page.locator('.speaker-selection>details').evaluate('e=>e.open=false')
        page.evaluate('''async()=>{
          const {getPlaybackTap}=await import('./scripts/audio-meters.mjs');
          window.observed=[...document.querySelectorAll('#speaker-editor audio[data-track-id]')].map(audio=>{
            const t=getPlaybackTap(audio),a=t.context.createAnalyser();a.fftSize=2048;t.source.connect(a);return {audio,a};
          });
          window.levels=()=>observed.map(({audio,a})=>{const x=new Float32Array(a.fftSize);a.getFloatTimeDomainData(x);return {time:audio.currentTime,rms:Math.sqrt(x.reduce((s,v)=>s+v*v,0)/x.length),mute:audio.muted};});
        }''')
        play=page.locator('#speaker-editor-source-audio-play');stop=page.locator('#speaker-editor-source-audio-stop')
        play.click()
        page.wait_for_function('levels().every(v=>v.time>2.7 && v.time<4.8)')
        values=page.evaluate('levels()')
        assert values[0]['rms']<.00001 and values[1]['rms']>.015,values
        assert all(not v['mute'] for v in values),values
        page.wait_for_function('levels().every(v=>v.time>5.2 && v.time<5.95 && v.rms>.015)')
        page.wait_for_function('levels().every(v=>v.time>=8 && v.time<9)')
        assert max(v['time'] for v in page.evaluate('levels()'))-min(v['time'] for v in page.evaluate('levels()'))<.15
        page.wait_for_function("document.getElementById('speaker-editor-source-audio').paused")
        assert abs(page.locator('#speaker-editor-source-audio').evaluate('a=>a.currentTime')-11)<.03
        # Restore by region ID, not undo; both tracks sound again in old silence.
        select(2,5);restore_selection(page,'silence');stop.click();play.click()
        page.wait_for_function('levels().every(v=>v.time>2.7 && v.time<4.8 && v.rms>.015)')
        stop.click()
        for scheme in ('light','dark'):
            page.emulate_media(color_scheme=scheme)
            for width in (320,390,768,1440):
                page.set_viewport_size({'width':width,'height':1000})
                page.wait_for_timeout(100)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(scheme,width)
                assert page.locator('.studio-transport-main').first.evaluate('e=>e.scrollWidth<=e.clientWidth'),(scheme,width)
                if output: page.screenshot(path=str(output/f'editor-{scheme}-{width}.png'),full_page=True)
        page.emulate_media(color_scheme='light');page.set_viewport_size({'width':1440,'height':1100})
        page.locator('.speaker-selection>details').evaluate('e=>e.open=false')
        page.locator('#speaker-editor-source-audio-play').click()
        page.wait_for_timeout(600)
        page.locator('#speaker-editor').evaluate('e=>window.scrollTo(0,e.getBoundingClientRect().top+scrollY-12)')
        if output: page.screenshot(path=str(output/'preview-a.png'))
        stop.click()
        assert not errors,errors
        print('Design A: PASS; DSP viewport/DOM/audio identity, real per-track silence/restoration, global cut skip, bounds stop, light/dark responsive.')
    finally: context.close()
