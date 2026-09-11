"""Real decoder/pixel/audio onset regression across overview/detail zoom."""
import base64
import io
import json
import math
import struct
import wave
from pathlib import Path
from urllib.parse import urlparse


def onset_fixture(duration):
    data = io.BytesIO()
    with wave.open(data, 'wb') as out:
        out.setnchannels(2); out.setsampwidth(2); out.setframerate(16000)
        frames = bytearray()
        for i in range(round(duration * 16000)):
            t = i / 16000
            amplitude = .25 if 10.5 <= t < 11.5 else .7 if 24.75 <= t < 25.75 else .4 if duration-.35 <= t < duration-.15 else 0
            value = round(amplitude * 32767 * math.sin(2 * math.pi * 400 * t))
            # Right-only first onset; anti-phase later onsets must not cancel.
            frames.extend(struct.pack('<hh', 0 if t < 12 else value, -value))
        out.writeframes(frames)
    return {'name': f'onset-{duration}.wav', 'mimeType': 'audio/wav', 'buffer': data.getvalue()}


def check_waveform_alignment(browser, base_url, screenshot_dir=None):
    context = browser.new_context(viewport={'width':1440,'height':1000}, device_scale_factor=2)
    context.add_init_script("sessionStorage.setItem('meser_service_access_v1','granted')")
    site = urlparse(base_url)
    context.route('**/*', lambda r: r.continue_() if urlparse(r.request.url).netloc == site.netloc else r.abort())
    page = context.new_page(); errors=[]; page.on('pageerror', lambda e: errors.append(str(e)))
    output = Path(screenshot_dir)/'s09a-waveform-alignment' if screenshot_dir else None
    if output: output.mkdir(parents=True, exist_ok=True)
    results=[]
    try:
        page.goto(base_url.rstrip('/')+'/Audio-Editor.html')
        for duration in (41.3,129.37):
            fixture=onset_fixture(duration)
            report=page.evaluate('''async ({bytes,duration})=>{
                const file=new File([Uint8Array.from(atob(bytes),c=>c.charCodeAt(0))],'onset.wav');
                const {createWaveformReader}=await import('./scripts/speaker-waveform.mjs');
                const reader=createWaveformReader(), report=[];
                const measure=(samples,start,span,onsets)=>{
                    const rate=samples.sampleRate||samples.length/span;
                    return onsets.map(([at,level])=>{
                        let first=-1,peak=0;
                        for(let i=Math.max(0,Math.floor((at-start-.15)*rate));i<Math.min(samples.length,Math.ceil((at-start+.13)*rate));i++){
                            if(samples[i]>.06&&first<0)first=i;peak=Math.max(peak,samples[i]);
                        }
                        return {expected:at,level,onset:first<0?null:start+first/rate,peak,bin:1/rate};
                    });
                };
                try{
                    report.push({kind:'overview',values:measure(await reader.read(file,duration),0,duration,[[10.5,.25],[24.75,.7],[duration-.35,.4]])});
                    for(const start of [8,24,Math.floor((duration-1)/8)*8]){
                        const span=Math.min(32,duration-start), targets=[[10.5,.25],[24.75,.7],[duration-.35,.4]].filter(([t])=>t>start&&t<start+span);
                        report.push({kind:'detail',start,span,values:measure(await reader.readWindow(file,start,span),start,span,targets)});
                    }
                    return report;
                }finally{reader.dispose();}
            }''',{'bytes':base64.b64encode(fixture['buffer']).decode(),'duration':duration})
            for entry in report:
                for value in entry['values']:
                    assert value['onset'] is not None and abs(value['onset']-value['expected']) <= value['bin']+.002,(duration,entry)
                    assert abs(value['peak']-value['level'])<.025,(duration,entry)
            results.append({'duration':duration,'decoder':report})
            print(f'Waveform decoder alignment: {duration}s overview/detail/tail peaks PASS.',flush=True)
        # The UI crosses the native overview / WASM detail boundary repeatedly.
        page.locator('#processor-file').set_input_files(onset_fixture(41.3))
        for mode,row,prefix,zoom_id in (
            ('speaker','.speaker-track','speaker-editor-source-audio','speaker-editor-zoom'),
            ('announcement','.processor-track','processor-source-audio','processor-source-zoom-range'),
        ):
            page.locator('#open-local-'+mode).click()
            if page.locator('#speaker-unsaved-discard').is_visible():
                page.locator('#speaker-unsaved-discard').click()
            page.wait_for_function('(id)=>!document.getElementById(id+"-play").disabled',arg=prefix,timeout=180000)
            track=page.locator(row).first
            scroll=track.locator('.speaker-waveform-scroll' if mode=='speaker' else '.processor-waveform-scroll')
            canvas=track.locator('canvas')
            for setting in ('fit','max','fit','max'):
                if setting=='fit': page.locator('#'+('speaker-editor-zoom-fit' if mode=='speaker' else 'processor-source-zoom-fit')).click()
                else: page.locator('#'+zoom_id).evaluate('e=>{e.value=e.max;e.dispatchEvent(new Event("input",{bubbles:true}))}')
                pps=scroll.evaluate('e=>e.firstElementChild.getBoundingClientRect().width/41.3')
                # Avoid the rounded control width as the time clock.
                if mode=='speaker':
                    pps=page.locator('#speaker-editor-zoom').evaluate('e=>Number(e.value)*document.querySelector(".speaker-waveform-scroll").clientWidth/41.3')
                else:
                    pps=page.locator('#processor-source-zoom-range').get_attribute('aria-valuetext')
                    pps=float(pps.split()[0].replace(',','.')) if pps else scroll.evaluate('e=>e.firstElementChild.getBoundingClientRect().width/41.3')
                scroll.evaluate('(e,p)=>e.scrollLeft=p>100?10*p:0',pps)
                if setting=='max': page.wait_for_function('(c)=>c.dataset.waveDetail==="ready"',arg=canvas.element_handle(),timeout=180000)
                else: page.wait_for_function('(c)=>c.dataset.waveDetail==="overview"',arg=canvas.element_handle())
                pixels=track.evaluate('''(row,{pps,mode})=>{
                    const c=row.querySelector('canvas'), image=row.querySelector('img');
                    const detail=c.dataset.waveDetail==='ready', useCanvas=mode==='speaker'||detail;
                    let source=c,left=parseFloat(c.style.left)||0,pixelRate=pps*devicePixelRatio,color;
                    if(!useCanvas){source=document.createElement('canvas');source.width=image.naturalWidth;source.height=image.naturalHeight;source.getContext('2d').drawImage(image,0,0);left=0;pixelRate=source.width/(image.getBoundingClientRect().width/pps);color='#74b2e6';}
                    else{const s=getComputedStyle(c);color=s.getPropertyValue('--track-wave').trim()||s.getPropertyValue('--studio-wave').trim()||'#74b2e6';}
                    const probe=document.createElement('canvas'),ctx=probe.getContext('2d');ctx.fillStyle=color;ctx.fillRect(0,0,1,1);const rgb=ctx.getImageData(0,0,1,1).data;
                    const data=source.getContext('2d').getImageData(0,0,source.width,source.height).data;
                    let first=null,peak=0;
                    for(let x=0;x<source.width;x++){
                        const t=left/pps+x/pixelRate;if(t<10.2||t>11)continue;
                        let ink=0;
                        for(let y=0;y<source.height;y++){const i=(y*source.width+x)*4;if(data[i+3]>200&&Math.abs(data[i]-rgb[0])<3&&Math.abs(data[i+1]-rgb[1])<3&&Math.abs(data[i+2]-rgb[2])<3)ink++;}
                        const level=ink/(source.height*.92);if(level>.08&&first===null)first=t;peak=Math.max(peak,level);
                    }
                    return {onset:first,peak,pps,detail,left};
                }''',{'pps':pps,'mode':mode})
                assert pixels['onset'] is not None and abs(pixels['onset']-10.5)<max(.012,3/pps),(mode,setting,pixels)
                assert abs(pixels['peak']-.25)<.04,(mode,setting,pixels)
                results.append({'editor':mode,'setting':setting,**pixels})
                if output: track.screenshot(path=str(output/f'{mode}-{setting}.png'))
            # Observe actual native media output as the playhead crosses the onset.
            page.evaluate('''async prefix=>{
                const {getPlaybackTap}=await import('./scripts/audio-meters.mjs');
                const host=document.getElementById(prefix).closest('#speaker-editor, #announcement-processor-card');
                const audio=host.querySelector('audio[data-track-id]'),tap=getPlaybackTap(audio),analyser=tap.context.createAnalyser();
                analyser.fftSize=256;tap.source.connect(analyser);window.onsetProbe={audio,analyser};
                window.onsetLevel=()=>{const a=new Float32Array(256);analyser.getFloatTimeDomainData(a);return {t:audio.currentTime,rms:Math.sqrt(a.reduce((s,x)=>s+x*x,0)/256)};};
            }''',prefix)
            # Click at source time 10.0 in the enlarged waveform, then Play.
            scroll.evaluate('(e,p)=>e.scrollLeft=9.8*p',pps)
            scroll.scroll_into_view_if_needed();box=scroll.bounding_box();left=scroll.evaluate('e=>e.scrollLeft')
            page.mouse.click(box['x']+10*pps-left,box['y']+box['height']*.6)
            page.locator('#'+prefix+'-play').click()
            page.wait_for_function('onsetLevel().t>10.1&&onsetLevel().t<10.4')
            before=page.evaluate('onsetLevel()');assert before['rms']<.00001,before
            page.wait_for_function('onsetLevel().rms>.025',timeout=5000)
            audible=page.evaluate('onsetLevel()');assert 10.45<audible['t']<10.65,audible
            results.append({'editor':mode,'silentBefore':before,'audibleOnset':audible})
            page.locator('#'+prefix+'-stop').click()
        assert not errors,errors
        if output:(output/'measurements.json').write_text(json.dumps(results,indent=2)+'\n')
        print('Waveform alignment PASS: native/WASM, short/long/tail windows, right-only/anti-phase peaks, both editors repeated fit/detail zoom, actual pixels and audible onset.',flush=True)
    finally:context.close()
