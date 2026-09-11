"""Compare the actual envelope in both editors, including the former style threshold."""
import json
import math
from pathlib import Path
from urllib.parse import urlparse
from s09a_waveform_motion_smoke import motion_fixture


def check_waveform_consistency(browser, base_url, screenshot_dir=None):
    context=browser.new_context(viewport={'width':1440,'height':1000},device_scale_factor=2)
    context.add_init_script("sessionStorage.setItem('meser_service_access_v1','granted')")
    host=urlparse(base_url).netloc
    context.route('**/*',lambda r:r.continue_() if urlparse(r.request.url).netloc==host else r.abort())
    page=context.new_page();measurements={}
    output=Path(screenshot_dir)/'s09a-waveform-consistency' if screenshot_dir else None
    if output:output.mkdir(parents=True,exist_ok=True)
    try:
        page.goto(base_url.rstrip('/')+'/Audio-Editor.html')
        page.locator('#processor-file').set_input_files(motion_fixture())
        for mode,row,audio,zoom,follow in (
            ('speaker','.speaker-track','speaker-editor-source-audio','speaker-editor-zoom','speaker-editor-follow'),
            ('announcement','.processor-track','processor-source-audio','processor-source-zoom-range','processor-source-follow')):
            page.locator('#open-local-'+mode).click()
            if page.locator('#speaker-unsaved-discard').is_visible():page.locator('#speaker-unsaved-discard').click()
            page.wait_for_function('(id)=>!document.getElementById(id+"-play").disabled',arg=audio,timeout=180000)
            page.wait_for_function("!document.getElementById('processor-file').disabled",timeout=180000)
            if page.locator('#'+follow).get_attribute('aria-pressed')!='true':page.locator('#'+follow).click()
            measurements[mode]={}
            for pps in (80,159,160,300,1000):
                page.locator('#'+audio).evaluate('a=>a.currentTime=12')
                page.wait_for_function('(id)=>!document.getElementById(id).seeking',arg=audio)
                scroll=page.locator(row+' [class$="waveform-scroll"]')
                base=scroll.evaluate('e=>e.clientWidth/73.3')
                value=pps/base if mode=='speaker' else 100*math.log(pps/base)/math.log(1000/base)
                page.locator('#'+zoom).evaluate('(e,v)=>{e.value=String(v);e.dispatchEvent(new Event("input",{bubbles:true}))}',value)
                scroll.evaluate("e=>{const pps=parseFloat(e.firstElementChild.style.width)/73.3;e.scrollLeft=12*pps-e.clientWidth/2;e.dispatchEvent(new Event('scroll'))}")
                # A retained ready bitmap can still belong to the previous
                # viewport while seek/scroll events settle. Wait for the actual
                # probe coordinates, then read the pixels in the same callback.
                measured=page.wait_for_function('''selector=>{
                    const c=document.querySelector(selector+' canvas');
                    if(!c||c.hidden||['loading','unavailable'].includes(c.dataset.waveDetail))return false;
                    const wave=c.parentElement,ctx=c.getContext('2d');
                    const pps=parseFloat(wave.style.width)/73.3,origin=parseFloat(c.style.left)||0;
                    const s=getComputedStyle(c),probe=document.createElement('canvas'),p=probe.getContext('2d');
                    p.fillStyle=s.getPropertyValue('--track-wave').trim()||s.getPropertyValue('--studio-wave').trim();p.fillRect(0,0,1,1);
                    const rgb=p.getImageData(0,0,1,1).data,values=[];
                    for(let i=0;i<32;i++){
                        const time=11.88+i*.008,x=Math.round((time*pps-origin)*devicePixelRatio);
                        if(x<0||x>=c.width)return false;
                        const data=ctx.getImageData(x,0,1,c.height).data;let ink=0;
                        for(let y=0;y<c.height;y++){const j=y*4;if(Math.abs(data[j]-rgb[0])<3&&Math.abs(data[j+1]-rgb[1])<3&&Math.abs(data[j+2]-rgb[2])<3)ink++;}
                        values.push(ink/(c.height*.92));
                    }
                    return {pps,values};
                }''',arg=row,timeout=180000)
                values=measured.json_value();measured.dispose()
                measurements[mode][pps]=values
                assert max(values['values'])>.3,(mode,pps,values)
                if output and pps in (80,1000):
                    page.screenshot(path=str(output/f'{mode}-{pps}.png'),full_page=True)
        for pps in measurements['speaker']:
            a=measurements['speaker'][pps];b=measurements['announcement'][pps]
            # Native range controls can round the requested pps slightly. The
            # visible envelope must agree within two raster edges plus that bin.
            delta=max(abs(x-y) for x,y in zip(a['values'],b['values']))
            assert delta<.035,(pps,delta,a,b)
        raster=page.evaluate("""async()=>{
            const {drawWaveformViewport}=await import('./scripts/audio-waveform-view.mjs');
            const samples=Float32Array.from({length:64000},(_,i)=>.4+.3*Math.sin(i*.003));samples.sampleRate=2000;
            const results=[];
            for(const dpr of [1,1.1,1.25,1.5,2,3]){
                const a=document.createElement('canvas'),b=document.createElement('canvas');
                drawWaveformViewport(a,samples,32,300,2000,800,100,dpr);
                drawWaveformViewport(b,samples,32,300,2500,800,100,dpr);
                const x0=Math.round(parseFloat(a.style.left)*dpr),x1=Math.round(parseFloat(b.style.left)*dpr);
                const from=Math.max(x0,x1)+4,to=Math.min(x0+a.width,x1+b.width)-4;
                const pa=a.getContext('2d').getImageData(from-x0,0,to-from,a.height).data;
                const pb=b.getContext('2d').getImageData(from-x1,0,to-from,b.height).data;
                let differences=0;for(let i=0;i<pa.length;i++)if(pa[i]!==pb[i])differences++;
                results.push({dpr,differences,bytes:pa.length});
            }return results;
        }""")
        assert all(r['bytes']>0 and r['differences']==0 for r in raster),raster
        measurements['raster']=raster
        if output:(output/'comparison.json').write_text(json.dumps(measurements,indent=2)+'\n')
        print('Waveform parity PASS: same file in both editors at 80/159/160/300/1000 px/s, normalized visible contours.',flush=True)
    finally:context.close()
