"""Waveform pixels must survive actual playback/Follow without morphing."""
import io
import json
import math
import struct
import wave
from pathlib import Path
from urllib.parse import urlparse


def motion_fixture():
    out = io.BytesIO()
    with wave.open(out, 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
        wav.writeframes(b''.join(struct.pack('<h', round(25000 * (.2+.7*math.sin(i/16000*5.3)**2) * math.sin(i*2*math.pi*330/16000))) for i in range(round(73.3*16000))))
    return {'name':'moving-wave.wav','mimeType':'audio/wav','buffer':out.getvalue()}


MEASURE = '''({prefix,rowSelector,seconds})=>new Promise(resolve=>{
    const audio=document.getElementById(prefix),rows=[...document.querySelectorAll(rowSelector)],scrolls=rows.map(r=>r.querySelector('[class$="waveform-scroll"]'));
    const canvas=rows[0].querySelector('canvas'), image=rows[0].querySelector('img');
    let previous=null, frames=0,updates=0,comparisons=0,differences=0,maxGap=0,lastChange=performance.now(),last=scrolls[0].scrollLeft;
    let frameGaps=[],lastFrame=performance.now(),desynchronized=0,notReady=0,headUpdates=0,lastHead='',imageSignature=null,imageChanges=0;
    const starts=new Set(),begin=performance.now(),startTime=audio.currentTime;
    const snapshot=()=>{
        if(canvas.hidden){const signature=image.src+':'+image.getBoundingClientRect().width;if(imageSignature!==null&&signature!==imageSignature)imageChanges++;imageSignature=signature;return null;}
        const ctx=canvas.getContext('2d'), height=canvas.height;
        const origin=Math.round((parseFloat(canvas.style.left)||0)*devicePixelRatio);
        const offset=Math.max(0,Math.round(scrolls[0].scrollLeft*devicePixelRatio)-origin);
        const width=Math.min(canvas.width-offset,Math.floor(scrolls[0].clientWidth*devicePixelRatio)),hashes=new Uint32Array(width);
        for(const fraction of [.17,.26,.35,.43,.59,.71,.83]){
            const data=ctx.getImageData(offset,Math.floor(height*fraction),width,1).data;
            for(let x=0;x<width;x++)hashes[x]=(Math.imul(hashes[x],31)+(data[x*4]<<16)+(data[x*4+1]<<8)+data[x*4+2])>>>0;
        }
        return {origin:origin+offset,hashes};
    };
    const frame=now=>{
        frames++;frameGaps.push(now-lastFrame);lastFrame=now;
        const left=scrolls[0].scrollLeft;
        if(left!==last){updates++;maxGap=Math.max(maxGap,now-lastChange);lastChange=now;last=left;}
        if(scrolls.some(s=>Math.abs(s.scrollLeft-left)>1))desynchronized++;
        const head=rows[0].querySelector('[class$="playhead"]').style.left;if(head!==lastHead){headUpdates++;lastHead=head;}
        if(canvas.dataset.waveDetail==='ready')starts.add(canvas.dataset.detailStart);
        if(canvas.dataset.waveDetail==='loading'||canvas.dataset.waveDetail==='unavailable')notReady++;
        const current=snapshot();
        if(previous&&current){
            const from=Math.max(previous.origin,current.origin)+6,to=Math.min(previous.origin+previous.hashes.length,current.origin+current.hashes.length)-6;
            for(let x=from;x<to;x++){comparisons++;if(previous.hashes[x-previous.origin]!==current.hashes[x-current.origin])differences++;}
        }
        previous=current;
        if(now-begin<seconds*1000)requestAnimationFrame(frame);
        else{frameGaps.sort((a,b)=>a-b);resolve({frames,updates,headUpdates,fps:frames*1000/(now-begin),maxGap,p95Frame:frameGaps[Math.floor(frameGaps.length*.95)],comparisons,differences,desynchronized,notReady,imageChanges,starts:[...starts],startTime,endTime:audio.currentTime});}
    };requestAnimationFrame(frame);
})'''


def check_waveform_motion(browser, base_url, screenshot_dir=None):
    context=browser.new_context(viewport={'width':1440,'height':1000},device_scale_factor=2)
    context.add_init_script("sessionStorage.setItem('meser_service_access_v1','granted')")
    site=urlparse(base_url)
    context.route('**/*',lambda r:r.continue_() if urlparse(r.request.url).netloc==site.netloc else r.abort())
    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    output=Path(screenshot_dir)/'s09a-waveform-motion' if screenshot_dir else None
    if output:output.mkdir(parents=True,exist_ok=True)
    measurements=[]
    try:
        page.goto(base_url.rstrip('/')+'/Audio-Editor.html')
        first=motion_fixture();second={**first,'name':'second-wave.wav'}
        page.locator('#processor-file').set_input_files([first,second])
        for mode,row,prefix,zoom,follow in (
            ('speaker','.speaker-track','speaker-editor-source-audio','speaker-editor-zoom','speaker-editor-follow'),
            ('announcement','.processor-track','processor-source-audio','processor-source-zoom-range','processor-source-follow'),
        ):
            page.locator('#open-local-'+mode).click()
            if page.locator('#speaker-unsaved-discard').is_visible():page.locator('#speaker-unsaved-discard').click()
            page.wait_for_function('(id)=>!document.getElementById(id+"-play").disabled',arg=prefix,timeout=180000)
            if page.locator('#'+follow).get_attribute('aria-pressed')!='true':page.locator('#'+follow).click()
            rows=page.locator(row);scroll=rows.first.locator('.speaker-waveform-scroll' if mode=='speaker' else '.processor-waveform-scroll')
            for label,target in [('fit',0),('overview',80),('medium',300),('detail',1000)]:
                page.locator('#'+prefix+'-stop').click()
                base=scroll.evaluate('e=>e.clientWidth/73.3')
                value=(max(1,target/base) if mode=='speaker' else 100*math.log(max(base,target)/base)/math.log(1000/base))
                page.locator('#'+zoom).evaluate('(e,value)=>{e.value=String(value);e.dispatchEvent(new Event("input",{bubbles:true}))}',value)
                if label=='detail':
                    page.wait_for_function('(selector)=>[...document.querySelectorAll(selector+" canvas")].every(c=>c.dataset.waveDetail==="ready")',arg=row,timeout=180000)
                start=23 if label=='detail' else 10
                page.locator('#'+prefix).evaluate('(a,v)=>{a.playbackRate=v.rate;a.currentTime=v.start}',{'rate':4 if label=='detail' else 1,'start':start})
                page.wait_for_function('(id)=>!document.getElementById(id).seeking',arg=prefix)
                page.locator('#'+prefix+'-play').click()
                page.wait_for_function('({id,start})=>document.getElementById(id).currentTime>start+.15',arg={'id':prefix,'start':start})
                # Await initial detail once. Subsequent moving frames may never
                # fall back to the overview, including all prefetch boundaries.
                if label!='fit':
                    page.wait_for_function('(s)=>[...document.querySelectorAll(s+" canvas")].every(c=>!["loading","unavailable"].includes(c.dataset.waveDetail))',arg=row,timeout=180000)
                report=page.evaluate(MEASURE,{'prefix':prefix,'rowSelector':row,'seconds':11.3 if label=='detail' else 1.5})
                measurements.append({'editor':mode,'scale':label,**report})
                if output:(output/'measurements.json').write_text(json.dumps(measurements,indent=2)+'\n')
                assert report['endTime']>report['startTime']+1,(mode,label,report)
                assert report['fps']>20 and report['headUpdates']>report['frames']*.75,(mode,label,report)
                if label!='fit':
                    assert report['updates']>report['frames']*.75,(mode,label,report)
                    assert report['maxGap']<max(120,report['p95Frame']*4),(mode,label,report)
                assert report['differences']==0 and report['imageChanges']==0,(mode,label,report)
                assert report['desynchronized']==0 and report['notReady']==0,(mode,label,report)
                if label=='detail':assert len(report['starts'])>=2,(mode,report)
                page.locator('#'+prefix+'-play').click()
                page.wait_for_function('(id)=>document.getElementById(id).paused',arg=prefix)
                before=scroll.evaluate('e=>e.scrollLeft');page.wait_for_timeout(150)
                assert scroll.evaluate('e=>e.scrollLeft')==before,(mode,label,'moving after pause')
                if output and label in ('overview','detail'):
                    page.evaluate('scrollTo(0,0)')
                    page.screenshot(path=str(output/f'{mode}-{label}.png'),full_page=True)
                print(f'Waveform motion {mode}/{label}: {report["fps"]:.1f} RAF fps, {report["updates"]}/{report["frames"]} scroll updates, {report["differences"]}/{report["comparisons"]} changed source pixels, detail windows={report["starts"]} PASS.',flush=True)
            # Zoom in and back out while audio continues, including the detail
            # decoder transition. Once ready, the contour must stay unchanged.
            page.locator('#'+prefix+'-stop').click()
            page.locator('#'+prefix).evaluate('a=>{a.playbackRate=1;a.currentTime=12}')
            page.wait_for_function('(id)=>!document.getElementById(id).seeking',arg=prefix)
            page.locator('#'+prefix+'-play').click()
            for target in (80,1000,300,80):
                base=scroll.evaluate('e=>e.clientWidth/73.3')
                value=target/base if mode=='speaker' else 100*math.log(target/base)/math.log(1000/base)
                page.locator('#'+zoom).evaluate('(e,v)=>{e.value=String(v);e.dispatchEvent(new Event("input",{bubbles:true}))}',value)
                page.wait_for_function('(s)=>[...document.querySelectorAll(s+" canvas")].every(c=>!c.hidden&&!["loading","unavailable"].includes(c.dataset.waveDetail))',arg=row,timeout=180000)
                page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
                report=page.evaluate(MEASURE,{'prefix':prefix,'rowSelector':row,'seconds':1.2})
                assert report['endTime']>report['startTime']+1,(mode,target,report)
                assert report['comparisons']>0 and report['differences']==0,(mode,target,report)
                assert report['notReady']==0 and report['desynchronized']==0,(mode,target,report)
                assert report['updates']>report['frames']*.75,(mode,target,report)
                measurements.append({'editor':mode,'liveZoom':target,**report})
            if output:(output/'measurements.json').write_text(json.dumps(measurements,indent=2)+'\n')
            print(f'Waveform live zoom {mode}: 80→1000→300→80 px/s, uninterrupted audio and stable source pixels PASS.',flush=True)
            page.locator('#'+prefix+'-stop').click()
            if mode=='speaker':
                page.locator('#speaker-editor-render').click()
                page.wait_for_function('document.getElementById("speaker-editor-result-audio").readyState>=2',timeout=180000)
                result=page.evaluate('''async()=>{
                    const audio=document.getElementById('speaker-editor-result-audio'),wave=document.getElementById('speaker-editor-result-waveform'),canvas=wave.querySelector('canvas');
                    const bitmap=canvas.toDataURL();await audio.play();
                    const measurement=await new Promise(resolve=>{let frames=0,updates=0,last='',start=performance.now();
                        const frame=now=>{frames++;const left=wave.querySelector('.speaker-playhead').style.left;if(left!==last){updates++;last=left;}
                            if(now-start<1500)requestAnimationFrame(frame);else resolve({frames,updates,fps:frames*1000/(now-start),time:audio.currentTime});};requestAnimationFrame(frame);});
                    audio.pause();return {...measurement,unchanged:bitmap===canvas.toDataURL()};
                }''')
                assert result['updates']>result['frames']*.75 and result['time']>1 and result['unchanged'],result
                measurements.append({'editor':'speaker-result',**result})
                if output:(output/'measurements.json').write_text(json.dumps(measurements,indent=2)+'\n')
                print(f'Speaker rendered result: {result["fps"]:.1f} RAF fps, {result["updates"]}/{result["frames"]} playhead updates, unchanged waveform PASS.',flush=True)
        assert not errors,errors
    finally:context.close()
