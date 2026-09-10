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
    fault = {'wasm': False, 'hold_wasm': False}
    held = []

    def intercept(route):
        target = urlparse(route.request.url)
        if target.netloc == site.netloc:
            if fault['hold_wasm'] and target.path.endswith('ffmpeg-core.wasm'):
                fault['hold_wasm'] = False; held.append(route); return
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
            page.evaluate('scrollTo(0,0)')
            page.screenshot(path=str(output/(name+'.png')), clip=page.locator(selector).bounding_box(), full_page=True)
            if name == 'preparation-error':
                previous=page.viewport_size
                for width in (320,390,768,1280):
                    page.set_viewport_size({'width':width,'height':900}); page.evaluate('scrollTo(0,0)')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(output/(name+f'-{width}.png')), clip=page.locator(selector).bounding_box(), full_page=True)
                page.set_viewport_size(previous)

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
                if(await engine.exec(['-i','tone.wav','-c:a','libmp3lame','-b:a','32k','short.mp3'])!==0) throw new Error('Synthetic MP3 encoding failed');
                const mp3=new File([await engine.readFile('short.mp3')],'short.mp3',{type:'audio/mpeg'});
                const sourceWav=new File([Uint8Array.from(atob(wav),c=>c.charCodeAt(0))],'short.wav',{type:'audio/wav'});
                window.correctiveFixtures={short:[short,new File([short],'second.m4a',{type:short.type})],
                    long:[long,new File([long],'second-hour.m4a',{type:long.type})], formats:[mp3,short,sourceWav]};
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
        # Explicit selection target and independent track monitoring, including
        # the audio element's actual mute flag (not only button styling).
        from s09a_selection_tools_smoke import check_selection_tools
        check_selection_tools(page, output)
        # A short M4A now opens despite native decode failure. Test real editing,
        # so a placeholder waveform or a disabled successful-looking view fails.
        page.locator('.speaker-selection details > summary').click()
        assert page.locator('#speaker-editor-add-cut').is_disabled()
        assert page.locator('#speaker-editor-add-silence').is_disabled()
        page.locator('#speaker-editor-selection-start').fill('0.5')
        page.locator('#speaker-editor-selection-end').fill('1')
        page.locator('#speaker-editor-add-cut').click()
        assert page.locator('.speaker-region-overlay--cut').count() == 2
        page.locator('#speaker-editor-undo').click()
        assert page.locator('.speaker-region-overlay--cut').count() == 0
        page.locator('#speaker-editor-selection-end').fill('99')
        assert page.locator('#speaker-editor-add-cut').is_disabled()
        page.locator('#speaker-editor-selection-end').fill('1')
        page.locator('#speaker-editor-selection-track').select_option(index=1)
        assert 'Дорожка 2 · second.m4a' in page.locator('#speaker-selection-summary').inner_text()
        page.locator('#speaker-editor-add-silence').click()
        assert page.locator('.speaker-region-overlay--silence').count()==1
        assert page.locator('.speaker-track').nth(1).locator('.speaker-region-overlay--silence').count()==1
        page.locator('.speaker-regions > summary').click()
        page.locator('.speaker-region-row input').last.fill('1.1')
        page.locator('.speaker-region-row').get_by_role('button', name='Применить границы').click()
        assert page.locator('.speaker-region-row').get_by_role('button', name='Применить границы').evaluate('e=>e===document.activeElement')
        page.locator('.speaker-regions > summary').click()
        control=page.locator('.speaker-track').nth(1).get_by_label('Выравнивание громкости', exact=True)
        control.focus(); control.select_option('on')
        assert page.locator('.speaker-track').nth(1).get_by_label('Выравнивание громкости', exact=True).evaluate('e=>e===document.activeElement')
        # A rerender caused by editing must keep the source viewport aligned.
        page.locator('#speaker-editor-zoom').fill('4'); page.locator('#speaker-editor-zoom').dispatch_event('input')
        page.locator('.speaker-waveform-scroll').first.evaluate('e=>e.scrollLeft=200')
        page.wait_for_timeout(50)
        page.locator('.speaker-track').nth(1).get_by_label('Компрессия', exact=True).select_option('light')
        assert page.locator('.speaker-waveform-scroll').first.evaluate('e=>e.scrollLeft')==200
        assert page.locator('.speaker-waveform-scroll').nth(1).evaluate('e=>e.scrollLeft')==200
        snapshot('selection-dsp-focus', '#speaker-editor')
        page.locator('#speaker-editor-render').click()
        page.wait_for_function("!document.getElementById('speaker-editor-result').hidden", timeout=60000)
        with page.expect_download() as download: page.locator('#speaker-editor-download').click()
        assert download.value.failure() is None

        # A decode/load failure names the file and retains the actual File objects.
        fault['wasm'] = True
        open_files('short')
        page.locator('#speaker-editor-source-retry').wait_for(state='visible', timeout=60000)
        assert 'short.m4a' in page.locator('#speaker-editor-status').inner_text()
        assert page.locator('.speaker-track').count() == 2
        assert page.locator('#speaker-editor-render').is_disabled()
        retained()
        for selector in ('#processor-save-incoming', '#speaker-editor-save', '#speaker-editor-add-cut', '#speaker-editor-add-silence', '#speaker-editor-set-start', '#speaker-editor-set-end'):
            assert page.locator(selector).is_disabled()
        assert '—' in page.locator('#speaker-editor-source-time').inner_text()
        assert page.locator('#speaker-editor-source-audio').is_hidden()
        assert page.locator('#speaker-source-timeline span').count()==0
        assert 'Все изменения сохранены' not in page.locator('#speaker-editor-status').inner_text()
        assert page.locator('.speaker-track .track-monitor-status').all_text_contents() == ['Прослушивание недоступно'] * 2
        snapshot('preparation-error', '#speaker-editor')
        fault['wasm'] = False
        page.locator('#speaker-editor-source-retry').click(); ready(); retained()
        assert page.evaluate('document.body.dataset.editing') == 'speaker'

        if page.locator('.speaker-selection details').evaluate('e=>e.open'): page.locator('.speaker-selection details > summary').click()
        # All three local formats remain usable in both modes without an archive session.
        open_files('formats'); ready(); retained()
        assert page.locator('.speaker-track').count()==3
        page.locator('#open-local-announcement').click(); page.locator('#speaker-unsaved-discard').click()
        page.wait_for_function("document.querySelectorAll('#processor-file-info .processor-waveform img').length===3", timeout=180000)
        page.locator('#processor-run').click()
        page.wait_for_function("document.getElementById('processor-download').href.startsWith('blob:')", timeout=60000)
        with page.expect_download() as download: page.locator('#processor-download').click()
        assert download.value.failure() is None
        # A result must stop the synchronized source preview. Opening the other
        # editor must explicitly pause this result as well, not merely hide it.
        page.locator('#processor-source-audio-play').click()
        page.wait_for_function("!document.getElementById('processor-source-audio').paused")
        page.evaluate("""async () => {
            const result = document.getElementById('processor-result-audio');
            await result.play();
            window.inactiveResultPauses = 0;
            const pause = result.pause;
            result.pause = function(...args) { window.inactiveResultPauses++; return pause.apply(this, args); };
        }""")
        page.wait_for_function("[...document.querySelectorAll('#processor-source audio')].every(a => a.paused)")
        # A delayed decoder load must not resurrect a closed editor.
        fault['hold_wasm']=True
        page.evaluate('''async () => {
            const editor=await import('./scripts/speaker-editor.mjs'), {localSourceContext}=await import('./scripts/audio-project.mjs');
            const files=correctiveFixtures.short;
            void editor.openSpeakerEditor({session:localSourceContext(files),files});
        }''')
        for _ in range(500):
            if held: break
            page.wait_for_timeout(20)
        assert held
        assert page.evaluate("inactiveResultPauses > 0 && document.getElementById('processor-result-audio').paused")
        page.locator('#speaker-editor-close').click(); page.locator('#speaker-unsaved-discard').click()
        for route in held: route.continue_()
        held.clear(); page.wait_for_timeout(200)
        assert page.locator('#speaker-editor').is_hidden()
        calls = page.evaluate('correctiveNativeCalls')
        open_files('long'); ready(); retained()
        assert page.evaluate('correctiveNativeCalls') == calls, 'Hour-long audio entered full Web Audio decoding'
        assert page.evaluate("async () => Math.abs((await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().originalDuration-3747)<0.1")
        page.locator('.speaker-selection details > summary').click()
        page.locator('#speaker-editor-selection-start').fill('10'); page.locator('#speaker-editor-selection-end').fill('20')
        page.locator('#speaker-editor-add-cut').click()
        assert page.locator('.speaker-region-overlay--cut').count()==2
        page.locator('#speaker-editor-undo').click()
        assert page.locator('.speaker-region-overlay--cut').count()==0
        page.locator('.speaker-selection details > summary').click()
        page.locator('#speaker-editor-zoom-fit').click()
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
            page.locator('#processor-source-zoom-fit').click()
            assert page.locator('#processor-source-scrollbar-thumb').bounding_box()['width'] >= page.locator('#processor-source-scrollbar').bounding_box()['width'] - 2
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
