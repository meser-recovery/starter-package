"""Native audio meters and stable DAW controls; no simulated meter values."""
import io
import struct
import wave
from pathlib import Path
from urllib.parse import urlparse
from s09a_edit_modes_smoke import apply_selection


def calibration(name, inverted=False):
    data = io.BytesIO()
    with wave.open(data, 'wb') as out:
        out.setnchannels(2); out.setsampwidth(2); out.setframerate(24000)
        frames = bytearray()
        for i in range(24000 * 8):
            # A faded DC plateau makes the summed-peak assertion independent
            # of native media start latency. Separate tone tests verify sound.
            sample = round(0.8 * 32767 * min(1, i / 2400, (24000 * 8 - i) / 2400))
            frames.extend(struct.pack('<hh', sample, -sample if inverted else sample))
        out.writeframes(frames)
    return {'name': name, 'mimeType': 'audio/wav', 'buffer': data.getvalue()}


def check_audio_meters(browser, base_url, screenshot_dir=None):
    context = browser.new_context(viewport={'width':1280,'height':1000}, device_scale_factor=2)
    context.add_init_script("sessionStorage.setItem('meser_service_access_v1','granted');window.__MESER_AUDIO_ARCHIVE_GATEWAY__='https://gateway.test';")
    site = urlparse(base_url)
    context.route('**/*', lambda r: r.continue_() if urlparse(r.request.url).netloc == site.netloc else r.abort())
    page = context.new_page(); errors=[]; page.on('pageerror', lambda e: errors.append(str(e)))
    output = Path(screenshot_dir)/'s09a-meters' if screenshot_dir else None
    if output: output.mkdir(parents=True, exist_ok=True)
    try:
        page.goto(base_url.rstrip('/')+'/Audio-Editor.html')
        page.locator('#processor-file').set_input_files([calibration('participant-a.wav',True),calibration('participant-b.wav',True)])
        for mode, root, prefix, row_selector, action in [
            ('speaker','#speaker-editor','speaker-editor-source-audio','.speaker-track','data-action'),
            ('announcement','#announcement-processor-card','processor-source-audio','.processor-track','data-track-action')]:
            page.locator('#open-local-'+mode).click()
            if page.locator('#speaker-unsaved-discard').is_visible(): page.locator('#speaker-unsaved-discard').click()
            page.wait_for_function('(id)=>!document.getElementById(id+"-play").disabled',arg=prefix)
            rows=page.locator(root+' '+row_selector)
            meters=rows.locator('.audio-meter')
            assert meters.count()==2
            master=page.locator(root+' .audio-meter--master')
            page.locator('#'+prefix+'-play').click()
            # Opposite-phase L/R must not disappear through analyser downmix.
            page.wait_for_function('(s)=>[...document.querySelectorAll(s)].every(e=>Number(e.dataset.rmsDb)>-2.4)', arg=root+' '+row_selector+' .audio-meter')
            for meter in meters.all():
                assert -2.5 < float(meter.get_attribute('data-rms-db')) < -1.5
                assert -2.3 < float(meter.get_attribute('data-peak-db')) < -1.5, meter.evaluate('e=>({data:{...e.dataset},time:document.querySelector("#speaker-editor-source-audio").currentTime})')
                assert meter.locator('.audio-meter__clip').get_attribute('aria-pressed')=='false'
                assert meter.locator('.audio-meter__mask').evaluate_all("nodes=>nodes.every(e=>parseFloat(e.style.width)<15)")
            # Two overlapping .8 plateaus: master peak 1.6 (+4.08 dBFS), not .8.
            page.wait_for_function('(s)=>Number(document.querySelector(s).dataset.peakDb)>3',arg=root+' .audio-meter--master')
            assert master.locator('.audio-meter__clip').get_attribute('aria-pressed')=='true'
            if output: page.locator(root).screenshot(path=str(output/(mode+'-playing-retina.png')))
            rows.first.locator('['+action+'=mute]').click()
            page.wait_for_function('(s)=>Number(document.querySelector(s).dataset.rmsDb)===-Infinity',arg=root+' '+row_selector+' .audio-meter')
            assert float(meters.nth(1).get_attribute('data-rms-db')) > -7
            rows.nth(1).locator('['+action+'=mute]').click()
            page.locator('#'+prefix+'-stop').click()
            page.wait_for_function('(s)=>Number(document.querySelector(s).dataset.rmsDb)===-Infinity',arg=root+' .audio-meter--master')
            assert float(master.get_attribute('data-peak-db')) == float('-inf')
            assert master.locator('.audio-meter__clip').get_attribute('aria-pressed')=='true', 'Stop must retain the overload latch until explicit reset'
            master.locator('.audio-meter__clip').click()
            assert master.locator('.audio-meter__clip').get_attribute('aria-pressed')=='false'
            for row in rows.all(): row.locator('['+action+'=mute]').click()
            for width in (320,390,768,1280):
                page.set_viewport_size({'width':width,'height':1000})
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert meters.evaluate_all('nodes=>nodes.every(e=>e.scrollWidth<=e.clientWidth && e.getBoundingClientRect().right<=e.parentElement.getBoundingClientRect().right+1)')
                if output: page.locator(root).screenshot(path=str(output/(mode+'-'+str(width)+'.png')))
            if mode=='speaker':
                for tool in ('cut','silence'):
                    wave_node=rows.first.locator('.speaker-waveform'); wave_node.scroll_into_view_if_needed(); b=wave_node.bounding_box()
                    page.mouse.move(b['x']+b['width']*.3,b['y']+b['height']*.65);page.mouse.down()
                    page.mouse.move(b['x']+b['width']*.5,b['y']+b['height']*.65,steps=5);page.mouse.up()
                    apply_selection(page,tool)
                    region=rows.first.locator('.speaker-region-overlay--'+tool).first
                    for width in (320,390,768,1280):
                        page.set_viewport_size({'width':width,'height':1000})
                        page.keyboard.press('Escape')
                        buttons=page.locator('#speaker-editor .speaker-selection__actions button')
                        geometry="nodes=>nodes.map(e=>{const r=e.getBoundingClientRect(),p=e.parentElement.getBoundingClientRect();return [r.x-p.x,r.y-p.y,r.width,r.height]})"
                        before=buttons.evaluate_all(geometry)
                        region.focus();page.keyboard.press('Enter')
                        assert page.locator('#speaker-editor-add-'+tool).get_attribute('data-mode')=='restore'
                        assert buttons.evaluate_all(geometry)==before, (tool,width,before,buttons.evaluate_all(geometry))
                        handle=region.locator('[data-edge=start]')
                        assert handle.evaluate("e=>parseFloat(getComputedStyle(e).width)>=16 && getComputedStyle(e).backgroundColor==='rgba(0, 0, 0, 0)' && parseFloat(getComputedStyle(e,'::after').width)<=2")
                        if output: page.locator(root).screenshot(path=str(output/(tool+'-selected-'+str(width)+'.png')))
                    page.locator('#speaker-editor-add-'+tool).click()
                assert rows.first.locator('.speaker-boundary--start').evaluate("e=>getComputedStyle(e).backgroundColor==='rgba(0, 0, 0, 0)' && parseFloat(getComputedStyle(e,'::before').width)<=2")
        assert not errors, errors
        print('Digital meters: PASS; both editors, stereo anti-phase, summed master/clip, mute, stop/reset, four widths, stable tools, thin edges.')
    finally:
        context.close()
