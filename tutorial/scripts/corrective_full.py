#!/usr/bin/env python3
"""Isolated, cache-only-audio VISUAL-CORRECTIVE-V2 full candidate."""
import argparse,asyncio,hashlib,json,math,shutil,subprocess
from pathlib import Path
import module_visuals, module_assemble, module_audio_qa, video_qa
from modules import ROOT, cached, scene_timing, sha, write_json
from validate import validate
from browser_capture import capture
from capture import probe
from build import demo_server
import corrective_scenes

OUT=ROOT/'generated/visual-corrective-v2-full'
PREVIOUS=ROOT/'generated/visual-corrective'


def configure():
    for module in (module_visuals,module_assemble,module_audio_qa,video_qa):module.OUT=OUT
    spec=json.loads((ROOT/'tutorial.yaml').read_text())
    for scene in spec['scenes']:
        if scene['visual']['type']=='browser':
            scene['visual']['capture_profile_hash']=corrective_scenes.fingerprint(scene)
            scene['visual']['capture_pipeline_revision']='semantic-lifecycle-v2-navigation-feedback'
    return spec


def preservation():
    before=json.loads((OUT/'evidence/preservation-before.json').read_text());changed=[]
    for path,item in before.items():
        p=ROOT.parent/path
        if not p.is_file() or p.stat().st_mtime_ns!=item['mtime_ns'] or sha(p)!=item['sha256']:changed.append(path)
    report={'status':'FAIL' if changed else 'PASS','protected_files':len(before),'changed':changed,'tts_requests':0}
    write_json(OUT/'evidence/narration-preservation.json',report)
    if changed:raise RuntimeError('Protected artifacts changed: '+str(changed))
    return report


def check_audio(spec):
    hits={m['id']:cached(spec,m) for m in spec['narration_modules']}
    if not all(hits.values()):raise RuntimeError('Missing narration cache; this command never requests TTS')
    result={mid:{'cache':'HIT','seconds':h['timing']['duration_seconds'],'sha256':h['metadata']['audio_sha256']} for mid,h in hits.items()}
    write_json(OUT/'evidence/narration-cache.json',{'modules':result,'tts_requests':0})
    return result


async def render(spec,numbers):
    failures=[]
    for scene in spec['scenes']:
        if int(scene['id'][:3]) not in numbers:continue
        timing=scene_timing(spec,scene);path=module_visuals.paths(scene)
        if module_visuals.cached(spec,scene,timing):
            print(json.dumps({'scene':scene['id'],'cache':'HIT'}),flush=True);continue
        path.parent.mkdir(parents=True,exist_ok=True)
        if scene['visual']['type']=='animation':
            previous=PREVIOUS/'visuals'/path.name;meta=json.loads(previous.with_suffix('.json').read_text())
            assert meta['visual_hash']==module_visuals.visual_hash(spec,scene,timing) and sha(previous)==meta['sha256'],'Approved animation inputs changed'
            shutil.copyfile(previous,path);shutil.copyfile(previous.with_suffix('.json'),path.with_suffix('.json'))
            print(json.dumps({'scene':scene['id'],'cache':'REUSED_APPROVED_ANIMATION'}),flush=True);continue
        print(json.dumps({'scene':scene['id'],'capture':'START'}),flush=True)
        try:
            render_hash=module_visuals.visual_hash(spec,scene,timing)
            timing.update(strict_choreography=True,evidence_directory=str(OUT/'evidence'),visual_profile=scene['visual']['capture_profile_hash'])
            clean={**scene,'padding':{'head':0.,'tail':0.}}
            raw=path.with_name(path.stem+'.raw.mp4')
            with demo_server(None) as base:
                evidence=await capture(clean,spec['narration'],base,timing=timing,destination=raw,
                                       prepare_scene=corrective_scenes.prepare,perform_scene=corrective_scenes.perform)
            target=math.ceil(timing['duration_seconds']*30)/30
            evidence['retime_factor']=module_visuals.browser_timeline_factor(target,evidence)
            if module_visuals.visual_hash(spec,scene,timing)!=render_hash:raise RuntimeError('Capture inputs changed during recording; retry with stable source')
            filters='fps=30,tpad=stop_mode=clone:stop_duration=1'
            if scene['captions']:
                from assemble import caption_font
                cap=path.with_suffix('.caption.txt');cap.write_text('\n'.join(scene['captions']))
                filters+=f",drawtext=fontfile='{caption_font()}':textfile='{cap}':fontsize=36:fontcolor=white:box=1:boxcolor=black@0.8:boxborderw=16:x=(w-text_w)/2:y=h-text_h-70"
            subprocess.run(['ffmpeg','-y','-v','error','-i',str(raw),'-vf',filters,'-t',str(target),'-an','-c:v','libx264','-preset','veryfast','-crf','21','-pix_fmt','yuv420p',str(path)],check=True)
            meta={'scene_id':scene['id'],'module_id':timing['module_id'],'visual_hash':render_hash,
                  'sha256':sha(path),**probe(path),'expected_state':'PASS','browser_errors':0,'production_mutation_requests':0,
                  'source':'real-loopback-Meser-UI','alignment_visual_cues':timing['visual_cues'],
                  'timing_identity':timing['timing_identity'],'browser_evidence':evidence}
            write_json(path.with_suffix('.json'),meta)
            print(json.dumps({'scene':scene['id'],'capture':'PASS','seconds':target}),flush=True)
        except Exception as error:
            failures.append({'scene':scene['id'],'error':str(error)})
            print(json.dumps(failures[-1],ensure_ascii=False),flush=True)
    report=OUT/f'evidence/capture-run-{min(numbers):03}-{max(numbers):03}.json'
    write_json(report,{'requested_scenes':numbers,'failures':failures,'tts_requests':0})
    if failures:raise RuntimeError(f'{len(failures)} capture failures; see {report.name}')


def assemble(spec):
    (OUT/'audio').mkdir(exist_ok=True)
    shutil.copyfile(PREVIOUS/'audio/asr-boundaries.json',OUT/'audio/asr-boundaries.json')
    result=module_assemble.assemble(spec)
    assert sha(OUT/'audio/master.wav')==sha(PREVIOUS/'audio/master.wav'),'PCM soundtrack changed'
    for ext in ('srt','vtt'):assert sha(OUT/f'tutorial.ru.{ext}')==sha(PREVIOUS/f'tutorial.ru.{ext}'),'Subtitle timing changed'
    write_json(OUT/'evidence/audio-equivalence.json',{'status':'PASS','PCM_sha256':sha(OUT/'audio/master.wav'),
        'identical_to_previous_PCM':True,'subtitles_unchanged':True,'aac_encodes':1,'tts_requests':0})
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('check','capture','assemble','verify'))
    parser.add_argument('--scenes',default=','.join(str(n) for n in range(1,61)))
    args=parser.parse_args();spec=configure();preservation();check_audio(spec)
    print(json.dumps(validate()),flush=True)
    if args.action=='capture':asyncio.run(render(spec,[int(n) for n in args.scenes.split(',')]))
    if args.action=='assemble':print(json.dumps(assemble(spec)),flush=True)
    if args.action=='verify':print(json.dumps(module_assemble.verify(spec)),flush=True)
    preservation()
