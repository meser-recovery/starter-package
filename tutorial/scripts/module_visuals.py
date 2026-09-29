"""Timing-coupled visuals: approved procedural language and actual loopback Meser UI."""
from __future__ import annotations
import asyncio,base64,hashlib,json,math,subprocess
from pathlib import Path
from modules import ROOT,identity,sha,write_json,scene_timing
from capture import probe

OUT=ROOT/json.loads((ROOT/'tutorial.yaml').read_text())['module_assembly']['output_directory']


def paths(scene):
    return OUT/'visuals'/f"{scene['id']}.mp4"


def visual_hash(spec,scene,timing):
    if scene['visual']['type']=='animation':
        source=[ROOT/spec['module_assembly']['animation_source'],ROOT/'animations/module-visuals.js']
        inputs=[sha(p) for p in source]
    else:
        from browser_capture import visual_hash as browser_hash
        inputs=[browser_hash(scene)]
    return identity({'visual':scene['visual'],'captions':scene['captions'],'inputs':inputs,
                     'timing_identity':timing['timing_identity'],'renderer':sha(Path(__file__))})


def cached(spec,scene,timing):
    path=paths(scene)
    try:
        meta=json.loads(path.with_suffix('.json').read_text())
        if meta['visual_hash']==visual_hash(spec,scene,timing) and sha(path)==meta['sha256'] and meta['expected_state']=='PASS' and not meta['browser_errors'] and not meta['production_mutation_requests']:
            return meta
    except (OSError,ValueError,KeyError): pass
    return None


def phase_at(second,cues,duration):
    points=[(0.,0.)]+[(c['seconds'],c['phase']) for c in cues]+[(duration,1.)]
    for (a,x),(b,y) in zip(points,points[1:]):
        if second<=b: return x+(y-x)*max(0,min(1,(second-a)/max(.001,b-a)))
    return 1.


def browser_timeline_factor(target,evidence):
    events=evidence.get('choreography',{}).get('events',[])
    if max((e['seconds'] for e in events),default=0)>target+1/30:
        raise RuntimeError('browser choreography exceeds its alignment range; adjust actions, never speed them up')
    if evidence['duration_seconds']>target+1.1:
        raise RuntimeError('browser capture overran its alignment range beyond the final idle hold')
    # CDP timestamps are real time. Extra terminal still frames may be trimmed;
    # a short rounding gap may be padded. Neither changes gesture/cue speed.
    return 1.0


async def render(spec,scenes,base_url=None):
    from playwright.async_api import async_playwright
    from browser_capture import capture as browser_capture
    from build import demo_server
    from fixtures import generate
    if any(s['visual']['type']=='browser' for s in scenes): generate()
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        page=await browser.new_page(viewport={'width':1920,'height':1080})
        errors=[]; page.on('pageerror',lambda e:errors.append(str(e)))
        await page.route('http://**/*',lambda route:route.abort())
        await page.route('https://**/*',lambda route:route.abort())
        await page.goto((ROOT/spec['module_assembly']['animation_source']).as_uri()+'?capture')
        for scene in scenes:
            timing=scene_timing(spec,scene)
            hit=cached(spec,scene,timing)
            if hit:
                print(json.dumps({'scene':scene['id'],'visual_cache':'HIT'}),flush=True); continue
            path=paths(scene); path.parent.mkdir(parents=True,exist_ok=True)
            target=math.ceil(timing['duration_seconds']*30)/30
            raw=path.with_name(path.stem+'.raw.mp4')
            evidence={}
            if scene['visual']['type']=='browser':
                clean={**scene,'padding':{'head':0.,'tail':0.}}
                for attempt in range(2):
                    try:
                        with demo_server(base_url) as origin:
                            evidence=await browser_capture(clean,spec['narration'],origin,timing=timing,destination=raw)
                        break
                    except RuntimeError as error:
                        if attempt or not str(error).startswith('browser capture produced only'): raise
                captured=probe(raw)['duration_seconds']
                speed=browser_timeline_factor(target,evidence)
                filters='fps=30,tpad=stop_mode=clone:stop_duration=1'
                # Review captions are canonical overlays, never TTS instructions.
                caption_file=None
                if scene['captions']:
                    from assemble import caption_font
                    caption_file=path.with_suffix('.caption.txt'); caption_file.write_text('\n'.join(scene['captions']))
                    filters+=f",drawtext=fontfile='{caption_font()}':textfile='{caption_file}':fontsize=36:fontcolor=white:box=1:boxcolor=black@0.8:boxborderw=16:x=(w-text_w)/2:y=h-text_h-70"
                subprocess.run(['ffmpeg','-y','-v','error','-i',str(raw),'-vf',filters,'-t',str(target),'-an','-c:v','libx264','-preset','veryfast','-crf','21','-pix_fmt','yuv420p',str(path)],check=True)
                evidence['retime_factor']=speed
            else:
                process=await asyncio.create_subprocess_exec('ffmpeg','-y','-v','error','-f','image2pipe','-framerate','30','-vcodec','mjpeg','-i','pipe:0','-an','-c:v','libx264','-preset','veryfast','-crf','21','-pix_fmt','yuv420p',str(path),stdin=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
                try:
                    for frame in range(round(target*30)):
                        progress=phase_at(frame/30,timing['visual_cues'],timing['duration_seconds'])
                        data=await page.evaluate('args=>window.frameJpeg(...args)',[scene['id'][:3],progress,0])
                        process.stdin.write(base64.b64decode(data)); await process.stdin.drain()
                    process.stdin.close(); error=await process.stderr.read()
                    if await process.wait(): raise RuntimeError(error.decode()[:500])
                finally:
                    if process.returncode is None: process.kill(); await process.wait()
                if errors: raise RuntimeError(str(errors))
            meta={'scene_id':scene['id'],'module_id':timing['module_id'],'visual_hash':visual_hash(spec,scene,timing),
                  'sha256':sha(path),**probe(path),'expected_state':'PASS','browser_errors':0,'production_mutation_requests':0,
                  'source':'procedural-pilot-language' if scene['visual']['type']=='animation' else 'real-loopback-Meser-UI',
                  'alignment_visual_cues':timing['visual_cues'],'timing_identity':timing['timing_identity'],'browser_evidence':evidence}
            write_json(path.with_suffix('.json'),meta)
            print(json.dumps({'scene':scene['id'],'visual_cache':'MISS','seconds':target}),flush=True)
        await browser.close()
