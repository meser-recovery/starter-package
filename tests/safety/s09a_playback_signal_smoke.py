"""Measure real Chromium media output for distinguishable local tones.

MediaElementAudioSourceNode taps the native playback path after mute/volume;
there are no mocked play/pause methods or replacement audio samples. This proves
browser signal output, not the user's physical speakers or listening acceptance.
"""
from pathlib import Path
from urllib.parse import urlparse
from s09a_smoke import fixture


def check_playback_signal(browser, base_url, screenshot_dir=None):
    site = urlparse(base_url)
    context = browser.new_context(viewport={'width': 1280, 'height': 900}, has_touch=True)
    context.add_init_script("sessionStorage.setItem('meser_service_access_v1','granted');window.__MESER_AUDIO_ARCHIVE_GATEWAY__='https://gateway.test';")
    context.route('**/*', lambda r: r.continue_() if urlparse(r.request.url).netloc == site.netloc else r.abort())
    page = context.new_page()
    measurements = []
    output = Path(screenshot_dir)/'s09a-playback' if screenshot_dir else None
    if output: output.mkdir(parents=True, exist_ok=True)
    try:
        page.goto(base_url.rstrip('/') + '/Audio-Editor.html')
        files = [dict(fixture(hz), name=f'{hz}-Zoom-recording-with-a-long-readable-participant-name-and-session-date-2026-09-10.wav') for hz in (330, 660)]
        page.locator('#processor-file').set_input_files(files)
        for mode, root, prefix, row_selector, action_attribute in (
            ('announcement', '#announcement-processor-card', 'processor-source-audio', '.processor-track', 'data-track-action'),
            ('speaker', '#speaker-editor', 'speaker-editor-source-audio', '.speaker-track', 'data-action'),
        ):
            page.locator('#open-local-' + mode).click()
            page.wait_for_function('(id) => !document.getElementById(id+"-play").disabled', arg=prefix)
            for width in (320, 390, 768, 1280):
                page.set_viewport_size({'width':width, 'height':900})
                page.evaluate('() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert page.locator(root + ' .archive-card__heading h2').evaluate('''e => {
                    const luminance=css=>{const rgb=css.match(/[0-9.]+/g).slice(0,3).map(x=>Number(x)/255).map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4);return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722};
                    const a=luminance(getComputedStyle(e).color),b=luminance(getComputedStyle(e.closest('.archive-card__heading')).backgroundColor);
                    return (Math.max(a,b)+.05)/(Math.min(a,b)+.05)>=4.5;
                }'''), 'Workspace heading contrast must be readable'
                assert page.locator(row_selector).evaluate_all('''rows=>rows.every(row=>{
                    const panel=row.querySelector('.speaker-track-controls,.processor-track__top').getBoundingClientRect(),wave=row.querySelector('.speaker-waveform-scroll,.processor-waveform-scroll').getBoundingClientRect();
                    return Math.abs(panel.right-wave.left)<2 && Math.abs(panel.top-wave.top)<2 && wave.width>0;
                })''')
                if mode == 'speaker' and width < 768:
                    disclosure=page.locator('.speaker-dsp-disclosure').first
                    if disclosure.evaluate('e=>e.open'):
                        disclosure.locator('summary').tap()
                        page.wait_for_function("!document.querySelector('.speaker-dsp-disclosure').open")
                    disclosure.locator('summary').tap()
                    disclosure.get_by_label('Улучшение',exact=True).wait_for(state='visible')
                    if output: page.screenshot(path=str(output/f'{mode}-long-name-dsp-{width}.png'),full_page=True)
                    disclosure.locator('summary').focus();page.keyboard.press('Enter')
                    assert not disclosure.evaluate('e=>e.open')
                    assert disclosure.locator('summary').evaluate('e=>e===document.activeElement')
                if output: page.screenshot(path=str(output/f'{mode}-long-name-{width}.png'),full_page=True)
            page.set_viewport_size({'width':320, 'height':450})
            transport=page.locator(root+' .speaker-transport,'+root+' .processor-source-player')
            assert transport.evaluate('e=>getComputedStyle(e).position')=='sticky'
            assert transport.bounding_box()['height']<=450*.45+1
            if output: page.screenshot(path=str(output/f'{mode}-short-screen.png'))
            page.set_viewport_size({'width':1280, 'height':900})
            rows = page.locator(row_selector)
            ids = rows.evaluate_all('rows=>rows.map(r=>r.dataset.trackId)')
            page.evaluate('''async () => {
                const moduleUrl = new URL('scripts/audio-meters.mjs', document.baseURI).href;
                const {getPlaybackTap} = await import(moduleUrl);
                window.signalNodes ||= new WeakMap();
                window.attachSignal = selector => [...document.querySelectorAll(selector)].map(audio => {
                    if (!signalNodes.has(audio)) {
                        const tap=getPlaybackTap(audio); window.signalContext=tap.context;
                        const source=tap.source, analyser=signalContext.createAnalyser();
                        analyser.fftSize=8192; analyser.smoothingTimeConstant=0;
                        source.connect(analyser); // Independent observer; app alone owns the audible connection.
                        signalNodes.set(audio,analyser);
                    }
                    return audio;
                });
                window.readSignal = selector => attachSignal(selector).map(audio => {
                    const analyser=signalNodes.get(audio), time=new Float32Array(analyser.fftSize), bins=new Float32Array(analyser.frequencyBinCount);
                    analyser.getFloatTimeDomainData(time); analyser.getFloatFrequencyData(bins);
                    let peak=1; for(let i=2;i<bins.length;i++) if(bins[i]>bins[peak]) peak=i;
                    return {id:audio.dataset.trackId, rms:Math.sqrt(time.reduce((s,x)=>s+x*x,0)/time.length), hz:peak*signalContext.sampleRate/analyser.fftSize};
                });
            }''')
            selector = root + ' audio[data-track-id]'

            def toggle(index, action):
                page.locator(f'{row_selector}[data-track-id="{ids[index]}"] [{action_attribute}="{action}"]').click()

            def measure(label, sounding, level=1):
                page.locator('#' + prefix + '-stop').click()
                page.evaluate('(s)=>{attachSignal(s);void signalContext.resume()}', selector)
                page.locator('#' + prefix + '-play').click()
                page.wait_for_function('(id)=>document.getElementById(id).currentTime>.3', arg=prefix)
                values = page.evaluate('(s)=>readSignal(s)', selector)
                assert len(values) == 2, values
                for value in values:
                    index = ids.index(value['id'])
                    if index in sounding:
                        assert .04*level < value['rms'] < .09*level, (mode, label, values)
                        assert abs(value['hz'] - (330, 660)[index]) < 12, (mode, label, values)
                    else:
                        assert value['rms'] < .00001, (mode, label, values)
                measurements.append({'mode': mode, 'case': label, 'output': values})
                page.locator('#' + prefix + '-stop').click()

            measure('both', {0, 1})
            toggle(0, 'mute'); measure('mute first', {1}); toggle(0, 'mute')
            toggle(1, 'mute'); measure('mute second', {0}); toggle(1, 'mute')
            toggle(0, 'solo'); measure('solo first', {0})
            toggle(1, 'solo'); measure('multiple solo', {0, 1})
            toggle(0, 'solo'); measure('solo second', {1}); toggle(1, 'solo')
            page.locator(root + ' .daw-monitor-volume input').fill('0.35')
            measure('monitor volume', {0, 1}, .35)
            page.locator(root + ' .daw-monitor-volume input').fill('1')
            if mode == 'announcement':
                toggle(1, 'move-up')
            else:
                rows.nth(1).get_by_role('button', name='Вверх', exact=True).click()
            assert rows.evaluate_all('rows=>rows.map(r=>r.dataset.trackId)') == list(reversed(ids))
            measure('reordered stable identities', {0, 1})
            toggle(0, 'mute'); measure('mute after reorder', {1}); toggle(0, 'mute')
            if mode == 'announcement':
                toggle(0, 'move-up')
            if mode == 'speaker':
                page.locator(f'{row_selector}[data-track-id="{ids[0]}"]').get_by_role('button', name='Исключить из микса', exact=True).click()
                measure('excluded source remains audible', {0, 1})
                page.locator('#speaker-editor-render').click()
                page.wait_for_function("!document.getElementById('speaker-editor-result').hidden", timeout=60000)
                result = '#speaker-editor-result-audio'
                page.evaluate('(s)=>{attachSignal(s);void signalContext.resume()}', result)
                page.locator('#' + prefix + '-play').click()
                page.wait_for_function('(id)=>document.getElementById(id).currentTime>.1', arg=prefix)
                page.evaluate('(s)=>document.querySelector(s).play()', result)
                page.wait_for_function('(s)=>document.querySelector(s).currentTime>.3', arg=result)
                assert page.locator(selector).evaluate_all('audios=>audios.every(a=>a.paused)')
                value = page.evaluate('(s)=>readSignal(s)[0]', result)
                assert value['rms'] > .02 and abs(value['hz']-660) < 12, value
                page.wait_for_function("Number(document.querySelector('#speaker-editor .audio-meter--master').dataset.rmsDb)>-40")
                assert 'результат' in page.locator('#speaker-editor .audio-meter--master .audio-meter__heading').inner_text()
                assert page.locator('#speaker-editor-tracks .audio-meter').evaluate_all('nodes=>nodes.every(e=>Number(e.dataset.rmsDb)===-Infinity)')
                measurements.append({'mode':mode,'case':'render excludes 330 Hz; result pauses all sources','output':value})
                page.locator('#' + prefix + '-play').click()
                page.wait_for_function('(s)=>document.querySelector(s).paused', arg=result)
                page.locator('#' + prefix + '-stop').click()
                page.locator('#open-local-announcement').click()
                page.locator('#speaker-unsaved-discard').click()
                assert page.locator('#speaker-editor audio').evaluate_all('audios=>audios.every(a=>a.paused)')
        if screenshot_dir:
            import json
            (output/'signal.json').write_text(json.dumps(measurements,indent=2)+'\n')
        print(f'S09A real media signal: PASS; {len(measurements)} tone/RMS cases, both editors, mute/solo/volume/reorder/exclusion/result isolation.')
    finally:
        context.close()
