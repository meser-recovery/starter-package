"""Local M4A preparation and compact editor regression; synthetic audio only."""
import base64
from pathlib import Path
from urllib.parse import urlparse
from s09a_smoke import fixture


def check_s09a_editor_corrective(browser, base_url, screenshot_dir=None):
    site = urlparse(base_url)
    context = browser.new_context(viewport={'width': 1280, 'height': 900})
    context.add_init_script("sessionStorage.setItem('meser_service_access_v1','granted');window.__MESER_AUDIO_ARCHIVE_GATEWAY__='https://gateway.test';")
    outbound = []
    fault = {'wasm': False}

    def intercept(route):
        target = urlparse(route.request.url)
        if target.netloc == site.netloc:
            if fault['wasm'] and target.path.endswith('ffmpeg-core.wasm'):
                route.fulfill(status=503, body='Synthetic decoder unavailable')
            else:
                route.continue_()
            return
        if target.netloc == 'gateway.test' and route.request.method == 'GET':
            route.fulfill(status=401, content_type='application/json', body='{}', headers={
                'Access-Control-Allow-Origin': f'{site.scheme}://{site.netloc}',
                'Access-Control-Allow-Credentials': 'true'})
            return
        outbound.append((route.request.method, route.request.url))
        route.abort()

    context.route('**/*', intercept)
    page = context.new_page()
    output = Path(screenshot_dir)/'s09a-corrective' if screenshot_dir else None
    if output:
        output.mkdir(parents=True, exist_ok=True)

    def snapshot(name, selector):
        if output:
            page.locator(selector).screenshot(path=str(output/(name+'.png')))

    def ready():
        page.wait_for_function("!document.getElementById('speaker-editor-render').disabled", timeout=180000)

    def open_files(kind):
        page.evaluate("""async kind => {
            await (await import('./scripts/speaker-editor.mjs')).closeSpeakerEditor(true);
            const {loadProcessorFiles} = await import('./scripts/audio-processor.mjs');
            window.correctiveSelected = window.correctiveFixtures[kind];
            loadProcessorFiles(window.correctiveSelected);
        }""", kind)
        page.locator('#open-local-speaker').click()

    def retained():
        assert page.evaluate("""async () => {
            const s = (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState();
            return s.files.length === correctiveSelected.length && s.files.every((f,i) => f === correctiveSelected[i]);
        }""")

    try:
        page.goto(base_url.rstrip('/')+'/Audio-Editor.html')
        # Generate AAC/M4A with the actual bundled codec, without a native ffmpeg
        # dependency on the CI runner or any real user recording.
        wav = base64.b64encode(fixture(330)['buffer']).decode()
        page.evaluate("""async wav => {
            const {FFmpeg} = await import('./vendor/ffmpeg/ffmpeg/index.js');
            const engine = new FFmpeg();
            try {
                await engine.load({coreURL:new URL('./vendor/ffmpeg/core/ffmpeg-core.js',location.href).href,
                    wasmURL:new URL('./vendor/ffmpeg/core/ffmpeg-core.wasm',location.href).href});
                await engine.writeFile('tone.wav', Uint8Array.from(atob(wav), c=>c.charCodeAt(0)));
                const encode = async (seconds, name) => {
                    const code=await engine.exec(['-stream_loop','-1','-i','tone.wav','-t',String(seconds),'-c:a','aac','-b:a','32k',name]);
                    if(code!==0) throw new Error('Synthetic M4A encoding failed');
                    const bytes=await engine.readFile(name);
                    await engine.deleteFile(name);
                    return new File([bytes],name,{type:'audio/mp4'});
                };
                const short=await encode(3,'short.m4a');
                const long=await encode(3747,'hour.m4a');
                window.correctiveFixtures={short:[short,new File([short],'second.m4a',{type:short.type})],
                    long:[long,new File([long],'second-hour.m4a',{type:long.type})]};
            } finally {engine.terminate();}
            window.correctiveNativeCalls=0;
            // Model a browser that can play M4A but rejects Web Audio decoding.
            AudioContext.prototype.decodeAudioData = async function() {
                window.correctiveNativeCalls++;
                throw new DOMException('Synthetic native decode failure','EncodingError');
            };
        }""", wav)
        open_files('short'); ready(); retained()
        assert page.locator('.speaker-track').count() == 2
        assert page.evaluate('correctiveNativeCalls') == 2
        assert page.locator('#speaker-source-timeline span').count() > 0
        assert page.locator('#announcement-processor-card').is_hidden()
        # A short M4A now opens despite native decode failure. Test real editing,
        # so a placeholder waveform or a disabled successful-looking view fails.
        page.locator('.speaker-selection details').evaluate('e=>e.open=true')
        page.locator('#speaker-editor-selection-start').fill('0.5')
        page.locator('#speaker-editor-selection-end').fill('1')
        page.locator('#speaker-editor-add-cut').click()
        assert page.locator('.speaker-region-overlay--cut').count() == 2
        page.locator('#speaker-editor-undo').click()
        assert page.locator('.speaker-region-overlay--cut').count() == 0

        # A decode/load failure names the file and retains the actual File objects.
        fault['wasm'] = True
        open_files('short')
        page.locator('#speaker-editor-source-retry').wait_for(state='visible', timeout=60000)
        assert 'short.m4a' in page.locator('#speaker-editor-status').inner_text()
        assert page.locator('.speaker-track').count() == 2
        assert page.locator('#speaker-editor-render').is_disabled()
        retained(); snapshot('preparation-error', '#speaker-editor')
        fault['wasm'] = False
        page.locator('#speaker-editor-source-retry').click(); ready(); retained()
        assert page.evaluate('document.body.dataset.editing') == 'speaker'

        calls = page.evaluate('correctiveNativeCalls')
        open_files('long'); ready(); retained()
        assert page.evaluate('correctiveNativeCalls') == calls, 'Hour-long audio entered full Web Audio decoding'
        for width in (320, 390, 768, 1280):
            page.set_viewport_size({'width':width,'height':900})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            if width >= 768:
                lanes=page.locator('.speaker-track').evaluate_all("""rows => rows.map(row=>{
                    const r=row.getBoundingClientRect(), w=row.querySelector('.speaker-waveform-scroll').getBoundingClientRect();
                    return {height:r.height,waveHeight:w.height,waveWidth:w.width,width:r.width};
                })""")
                assert all(r['height'] <= 210 and r['waveHeight'] >= r['height']-2 and r['waveWidth'] > r['width']/2 for r in lanes), lanes
            else:
                assert page.locator('.speaker-track__buttons button').first.evaluate('e=>e.getBoundingClientRect().height>=44')
            snapshot(f'speaker-{width}', '#speaker-editor')

        page.set_viewport_size({'width':1280,'height':900})
        page.locator('#open-local-announcement').click()
        page.locator('#speaker-unsaved-discard').click()
        page.wait_for_function("document.querySelectorAll('#processor-file-info .processor-waveform img').length===2", timeout=180000)
        for width in (320,390,768,1280):
            page.set_viewport_size({'width':width,'height':900})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            if width >= 768:
                lanes=page.locator('.processor-track').evaluate_all("""rows=>rows.map(row=>{
                    const r=row.getBoundingClientRect(), w=row.querySelector('.processor-waveform-scroll').getBoundingClientRect();
                    return {height:r.height,waveHeight:w.height};
                })""")
                assert all(r['height']<=150 and r['waveHeight']>=r['height']-2 for r in lanes), lanes
            snapshot(f'announcement-{width}', '#announcement-processor-card')
        assert not outbound, outbound
        print('S09A corrective: M4A native failure fallback, retained files/retry, two hour-long tracks, editing and compact lanes at four widths passed.')
    finally:
        context.close()
