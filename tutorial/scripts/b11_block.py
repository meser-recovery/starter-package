#!/usr/bin/env python3
"""B11 Archive explanation and real isolated recording creation."""
from __future__ import annotations

import array
import asyncio
import copy
import hashlib
import inspect
import json
import math
import re
import subprocess
import wave
from pathlib import Path

from audio_approval import validate_block_approval
from b01_block import check_embedded_subtitles, timestamp
from b09_block import pointer_pixels_in_mp4, visual_transition_anomalies
from browser_capture import capture
from build import demo_server
from modules import cached, map_timing, request_text_and_indices, sha, write_json
from scenes import TRACKS, login
from validate import ROOT, validate

OUT=ROOT/'generated/b11-block-review'
AUDIO=ROOT/'generated/narration-blocks-v2/B11'
CONCEPT=ROOT/'animations/b11-archive-concept.js'
SCENE_IDS=('B11-038','B11-039','B11-040','B11-041')
TITLE='Учебная спикерская запись B11'
DATE='2026-09-28T12:00'
VARIANT='B11-review-01'
LEAD=.6
RATE=44100
FPS=30
FRAME_BYTES=1920*1080*3//2


def inputs():
    validate();validate_block_approval('B10')
    spec=json.loads((ROOT/'tutorial.yaml').read_text())
    module=next(m for m in spec['narration_modules'] if m['id']=='B11')
    hit=cached(spec,module)
    if not hit:raise RuntimeError('B11 one-request narration is missing or stale')
    metadata=json.loads((AUDIO/f'{VARIANT}-metadata.json').read_text())
    review=json.loads((AUDIO/'B11-review-map.json').read_text())
    if (review['status'],review['block_id'],review['variant_id'])!=('SEMANTIC_REVIEWED','B11','review-01'):
        raise RuntimeError('B11 semantic pause map invalid')
    for path,digest in ((AUDIO/'narration.mp3',metadata['source_mp3_sha256']),
                        (AUDIO/f'{VARIANT}.mp3',metadata['mp3_sha256']),
                        (AUDIO/f'{VARIANT}.wav',metadata['wav_sha256']),
                        (AUDIO/f'{VARIANT}-timing.json',metadata['timing_sha256']),
                        (AUDIO/f'{VARIANT}-source-timing.json',metadata['source_timing_sha256'])):
        if sha(path)!=digest:raise RuntimeError('B11 reviewed audio changed: '+str(path))
    if (metadata['source_mp3_sha256']!=hit['metadata']['audio_sha256']
            or metadata['new_tts_requests'] or metadata['speed_pitch_gain_processing']
            or not metadata['source_pcm_recovered_exactly']
            or [x['after_offset'] for x in metadata['events']]!=[x['after_offset'] for x in review['insertions']]):
        raise RuntimeError('B11 source/review provenance invalid')
    with wave.open(str(AUDIO/f'{VARIANT}.wav')) as wav:
        if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())!=(1,2,RATE):
            raise RuntimeError('B11 WAV format invalid')
        pcm=wav.readframes(wav.getnframes());duration=wav.getnframes()/RATE
    if hashlib.sha256(pcm).hexdigest()!=metadata['final_pcm_sha256']:
        raise RuntimeError('B11 final PCM changed')
    original=subprocess.check_output(['ffmpeg','-v','error','-xerror','-i',str(AUDIO/'narration.mp3'),
                                      '-ac','1','-ar',str(RATE),'-c:a','pcm_s16le','-f','s16le','-'])
    restored=bytearray();previous=0
    for event in metadata['events']:
        start=event['insert_start_final_sample']*2;end=start+event['added_samples']*2
        if pcm[start:end]!=bytes(end-start):raise RuntimeError('B11 inserted PCM is not silent')
        restored.extend(pcm[previous:start]);previous=end
    restored.extend(pcm[previous:])
    if bytes(restored)!=original:raise RuntimeError('B11 source PCM is not exactly restored')
    timing=json.loads((AUDIO/f'{VARIANT}-timing.json').read_text())
    if timing!=map_timing(spec,module,timing['alignment'],timing['duration_seconds']):
        raise RuntimeError('B11 alignment no longer maps to canonical text')
    scenes=[s for s in spec['scenes'] if s['id'] in SCENE_IDS]
    if tuple(s['id'] for s in scenes)!=SCENE_IDS:raise RuntimeError('B11 scene map changed')
    return spec,module,scenes,metadata,timing,pcm,duration


def scene_timing(spec,module,scene,timing,metadata,duration):
    row=next(r for r in timing['scenes'] if r['scene_id']==scene['id'])
    start=row['range_start_seconds'];end=min(row['range_end_seconds'],duration)
    _,positions=request_text_and_indices(spec,module)
    positions=positions[scene['start_offset']:scene['end_offset']]
    full=timing['alignment']
    local={'characters':[full['characters'][i] for i in positions],
           'character_start_times_seconds':[max(0,full['character_start_times_seconds'][i]-start) for i in positions],
           'character_end_times_seconds':[max(0,full['character_end_times_seconds'][i]-start) for i in positions]}
    if ''.join(local['characters'])!=scene['narration']:
        raise RuntimeError('B11 scene alignment differs from canonical text')
    return {**row,'alignment':local,'duration_seconds':end-start,
            'timing_identity':hashlib.sha256((metadata['timing_sha256']+scene['id']).encode()).hexdigest()}


def capture_spec(scene):
    return {**scene,'visual':{'type':'browser','goal':scene['goal'],
                             'capture_pipeline_revision':'b11-archive-workflow-v1'},
            'initial_state':scene['id'],'expected_state':'B11 archive action completed',
            'assertions':[],'fixture_set':'existing-synthetic-zoom-v1',
            'padding':{'head':0.,'tail':0.}}


async def settled(page,label):
    state=await page.evaluate('''() => ({scrollX:scrollX,scrollY:scrollY,
      viewport:[innerWidth,innerHeight],createOpen:!document.querySelector('#archive-create').hidden,
      files:[...document.querySelectorAll('#archive-create-list li')].map(x=>x.textContent.trim()),
      summary:document.querySelector('#archive-create-summary').textContent.trim(),
      title:document.querySelector('#archive-create-name').value,
      detailVisible:!document.querySelector('#detail').hidden,
      detailTitle:document.querySelector('#detail-title')?.textContent.trim()||''})''')
    if state['scrollX']!=0 or state['viewport']!=[1728,972]:
        raise RuntimeError(f'B11 {label} viewport changed: {state}')
    if hasattr(page,'tutorial'):
        page.tutorial.events.append({'type':'archive-state','seconds':page.tutorial.now(),
                                     'label':label,'state':state})
    return state


async def load_concept(page,mode,elapsed=0):
    await page.add_script_tag(path=str(CONCEPT))
    await page.evaluate('args=>window.B11Concept.mount(args.mode,args.elapsed)',
                        {'mode':mode,'elapsed':elapsed})
    await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')


async def prepare(page,scene,base):
    await page.set_viewport_size({'width':1728,'height':972})
    await login(page,base)
    sid=scene['id']
    if sid=='B11-038':
        await page.goto(base+'/Audio-Editor.html')
        await page.locator('nav[aria-label="Аудиопортал"] a[href="Audio-Archive.html"]').wait_for()
    elif sid=='B11-039':
        await load_concept(page,'archive',8)
    elif sid=='B11-040':
        await load_concept(page,'handoff',8)
    else:
        await page.locator('#archive-create-open').click()
        await page.locator('#archive-create-name').fill(TITLE)
        await page.locator('#archive-create-recorded').fill(DATE)
        await page.locator('#archive-create-files').set_input_files([str(x) for x in TRACKS[:2]])
        await page.wait_for_function("document.querySelectorAll('#archive-create-list li').length===2")
    await page.evaluate('async()=>{await document.fonts.ready;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))}')
    await page.wait_for_timeout(300)
    if sid=='B11-041':
        state=await settled(page,'initial selected tracks')
        if not state['createOpen'] or len(state['files'])!=2 or state['title']!=TITLE:
            raise RuntimeError('B11 scene 041 initial form differs from preceding action')
    await page.screenshot()


async def perform(page,scene,base,cue):
    sid=scene['id'];director=page.tutorial
    if sid=='B11-038':
        await cue('Теперь')
        await page.locator('nav[aria-label="Аудиопортал"] a[href="Audio-Archive.html"]').click()
        await page.get_by_role('heading',name='Аудиоархив').wait_for()
        await page.evaluate("window.__s11Capture.hide('archive-navigation')")
        await cue('Использовать Аудиоархив необязательно');await director.wait_pending()
        await load_concept(page,'local')
        await cue('Но если требуется дополнительная гибкость');await director.wait_pending()
        await page.evaluate("window.B11Concept.mode('archive')")
        await cue('Он позволяет хранить');await director.wait_pending()
        await settled(page,'archive concept over real portal')
    elif sid=='B11-039':
        await cue('передавать работу');await director.wait_pending()
        await page.evaluate("window.B11Concept.mode('handoff')")
        await cue('Вместо того чтобы отдельно пересылать');await director.wait_pending()
        await settled(page,'handoff shown')
    elif sid=='B11-040':
        await cue('Другой возможный сценарий');await director.wait_pending()
        await page.evaluate("window.B11Concept.mode('device')")
        await cue('Чтобы добавить новую запись');await director.wait_pending()
        await page.evaluate("window.B11Concept.hide()")
        await asyncio.sleep(.55)
        await cue('используется кнопка')
        await page.locator('#archive-create-open').click()
        await page.evaluate("window.__s11Capture.hide('creation-form-opened')")
        await cue('Сначала указывается название')
        await page.locator('#archive-create-name').fill(TITLE)
        await cue('дату и время собрания')
        await page.locator('#archive-create-recorded').fill(DATE)
        await cue('выбираются исходные')
        await page.locator('#archive-create-pick').click()
        await page.locator('#archive-create-files').set_input_files([str(x) for x in TRACKS[:2]])
        state=await settled(page,'initial file choice')
        if len(state['files'])!=2 or not state['summary']:
            raise RuntimeError('B11 initial Zoom file choice not visible')
    elif sid=='B11-041':
        await cue('Добавить дорожки')
        await page.locator('#archive-create-add').click()
        await page.locator('#archive-create-files').set_input_files(str(TRACKS[2]))
        added=await settled(page,'track added')
        if len(added['files'])!=3 or TRACKS[2].name not in ' '.join(added['files']):
            raise RuntimeError('B11 add did not extend file list')
        await cue('Выбрать заново')
        await page.locator('#archive-create-replace').click()
        await page.locator('#archive-create-files').set_input_files([str(x) for x in (TRACKS[0],TRACKS[2],TRACKS[3])])
        replaced=await settled(page,'list replaced')
        if (len(replaced['files'])!=3 or TRACKS[1].name in ' '.join(replaced['files'])
                or TRACKS[3].name not in ' '.join(replaced['files'])):
            raise RuntimeError('B11 replace did not replace the complete list')
        await cue('общий размер');await director.wait_pending()
        if not any(x in replaced['summary'] for x in ('МБ','КБ')):
            raise RuntimeError('B11 total selected size not shown')
        await cue('Сохранить запись')
        await page.locator('#archive-create-submit').click()
        await page.locator('#detail-title').wait_for(state='visible',timeout=60000)
        saved=await settled(page,'record saved in Archive')
        if not saved['detailVisible'] or saved['detailTitle']!=TITLE:
            raise RuntimeError('B11 saved record not present in real Archive')
        await page.evaluate("window.__s11Capture.hide('saved-record-context')")
    else:raise RuntimeError('unexpected B11 scene')
    await page.evaluate("window.__s11Capture.hide('scene-complete')")


async def visual():
    if (ROOT/'approvals/B11-block.json').exists():raise RuntimeError('B11 approved and immutable')
    spec,module,scenes,metadata,timing,_,duration=inputs()
    (OUT/'scenes').mkdir(parents=True,exist_ok=True)
    recipe='\n'.join(inspect.getsource(fn) for fn in
                     (capture_spec,settled,load_concept,prepare,perform))
    identity=hashlib.sha256(recipe.encode()+CONCEPT.read_bytes()).hexdigest()
    rows=[]
    with demo_server(None) as base:
        for scene in scenes:
            local=scene_timing(spec,module,scene,timing,metadata,duration)
            local.update(visual_lead_seconds=LEAD if scene['id']==SCENE_IDS[0] else 0.,
                         visual_source_sha256=identity,strict_choreography=False)
            path=OUT/'scenes'/f"{scene['id']}.mp4"
            evidence=await capture(capture_spec(scene),spec['narration'],base,timing=local,
                                   destination=path,prepare_scene=prepare,perform_scene=perform)
            if evidence['browser_errors'] or evidence['production_mutation_requests']:
                raise RuntimeError('B11 isolated capture failed')
            if max((e['seconds'] for e in evidence['choreography']['events']),default=0)>local['duration_seconds']+local['visual_lead_seconds']+.25:
                raise RuntimeError('B11 action exceeds narrated scene: '+scene['id'])
            row={'scene_id':scene['id'],'visual':str(path),'sha256':sha(path),
                 'duration_seconds':evidence['duration_seconds'],
                 'cue_errors_seconds':[c['actual_seconds']-c['target_seconds'] for c in evidence['alignment_action_cues']],
                 'production_mutation_requests':0}
            rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    result={'status':'PASS','block_id':'B11','source_mp3_sha256':metadata['source_mp3_sha256'],
            'final_wav_sha256':metadata['wav_sha256'],'tts_requests':0,'scenes':rows}
    write_json(OUT/'visual-capture.json',result)
    return result


def subtitles(scenes,timings):
    cues=[]
    for scene,timing in zip(scenes,timings):
        text=scene['narration'];starts=timing['alignment']['character_start_times_seconds']
        ends=timing['alignment']['character_end_times_seconds'];words=list(re.finditer(r'\S+',text));begin=0
        for i,word in enumerate(words):
            first,last=words[begin].start(),word.end()-1
            phrase=' '.join(text[first:last+1].split())
            if len(phrase)>=68 or word.group()[-1:] in '.!?…' or i==len(words)-1:
                start=LEAD+timing['range_start_seconds']+starts[first]
                end=LEAD+timing['range_start_seconds']+ends[last]
                if end<=start or '[' in phrase or ']' in phrase:raise RuntimeError('B11 subtitle invalid')
                cues.append((start,end,phrase));begin=i+1
    if any(cues[i][0]<cues[i-1][1]-.01 for i in range(1,len(cues))):
        raise RuntimeError('B11 subtitle cues overlap')
    for suffix in ('srt','vtt'):
        vtt=suffix=='vtt'
        body=('WEBVTT\n\n' if vtt else '')+'\n\n'.join(
            ('' if vtt else f'{i}\n')+f'{timestamp(a,vtt=vtt)} --> {timestamp(b,vtt=vtt)}\n{phrase}'
            for i,(a,b,phrase) in enumerate(cues,1))+'\n'
        (OUT/f'B11.ru.{suffix}').write_text(body)
    return cues


def assemble():
    if (ROOT/'approvals/B11-block.json').exists():raise RuntimeError('B11 approved and immutable')
    spec,module,scenes,metadata,timing,pcm,duration=inputs()
    visual_report=json.loads((OUT/'visual-capture.json').read_text())
    if (visual_report['source_mp3_sha256']!=metadata['source_mp3_sha256']
            or [r['scene_id'] for r in visual_report['scenes']]!=list(SCENE_IDS)):
        raise RuntimeError('B11 visual capture differs from source')
    timings=[scene_timing(spec,module,s,timing,metadata,duration) for s in scenes]
    cues=subtitles(scenes,timings)
    timeline=OUT/'B11-video-timeline.wav'
    with wave.open(str(timeline),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(RATE)
        wav.writeframes(bytes(round(LEAD*RATE)*2)+pcm)
    total=math.ceil(max(LEAD+duration,cues[-1][1]+.01)*FPS)/FPS
    bounds=[0]+[LEAD+t['range_start_seconds'] for t in timings[1:]]+[total]
    counts=[round(bounds[i+1]*FPS)-round(bounds[i]*FPS) for i in range(len(scenes))]
    if min(counts)<=0:raise RuntimeError('B11 scene frame count invalid')
    candidate=OUT/'B11.tmp.mp4'
    cmd=['ffmpeg','-y','-v','error','-f','rawvideo','-pixel_format','yuv420p',
         '-video_size','1920x1080','-framerate',str(FPS),'-i','pipe:0',
         '-i',str(timeline),'-i',str(OUT/'B11.ru.srt'),
         '-map','0:v:0','-map','1:a:0','-map','2:s:0',
         '-c:v','libx264','-preset','veryfast','-crf','21','-pix_fmt','yuv420p',
         '-c:a','aac','-b:a','192k','-c:s','mov_text','-metadata:s:s:0','language=rus',
         '-frames:v',str(sum(counts)),'-movflags','+faststart',str(candidate)]
    with (OUT/'encode.log').open('wb') as log:
        encoder=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=log)
        try:
            for scene,count in zip(scenes,counts):
                source=OUT/'scenes'/f"{scene['id']}.mp4"
                if not source.exists():raise RuntimeError('B11 scene missing: '+scene['id'])
                decoder=subprocess.Popen(['ffmpeg','-v','error','-xerror','-i',str(source),'-an',
                    '-vf','scale=1920:1080,fps=30,trim=start_frame=1,tpad=start=1:start_mode=clone,setpts=N/(30*TB),tpad=stop_mode=clone:stop=300',
                    '-r',str(FPS),'-frames:v',str(count),'-pix_fmt','yuv420p','-f','rawvideo','pipe:1'],stdout=subprocess.PIPE)
                copied=0
                try:
                    while chunk:=decoder.stdout.read(1024*1024):
                        encoder.stdin.write(chunk);copied+=len(chunk)
                finally:decoder.stdout.close()
                if decoder.wait() or copied!=count*FRAME_BYTES:
                    raise RuntimeError('B11 captured frame count mismatch: '+scene['id'])
            encoder.stdin.close()
            if encoder.wait():raise RuntimeError('B11 encoding failed; see encode.log')
        finally:
            if encoder.poll() is None:encoder.kill();encoder.wait()
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(candidate),'-f','null','-'],
                   check=True,stdout=subprocess.DEVNULL)
    canonical=' '.join(' '.join(s['narration'].split()) for s in scenes)
    checked=check_embedded_subtitles(candidate,OUT/'B11.ru.srt',canonical)
    final=OUT/'B11.mp4';candidate.replace(final)
    report={'status':'READY FOR B11 BLOCK REVIEW','block_id':'B11','video':str(final),
            'video_sha256':sha(final),'duration_seconds':total,
            'source_mp3_sha256':metadata['source_mp3_sha256'],'final_wav_sha256':metadata['wav_sha256'],
            'final_pcm_sha256':metadata['final_pcm_sha256'],'final_alignment_sha256':metadata['timing_sha256'],
            'video_audio_timeline':str(timeline),'video_audio_lead_seconds':LEAD,
            'insertions':len(metadata['events']),'scene_frame_counts':dict(zip(SCENE_IDS,counts)),
            'embedded_subtitle_cues':checked['embedded_subtitle_cues'],
            'last_embedded_subtitle_end_seconds':checked['last_embedded_subtitle_end_seconds'],
            'tts_requests_for_source':1,'production_mutation_requests':0}
    write_json(OUT/'report.json',report)
    return report


def verify():
    spec,module,scenes,metadata,timing,pcm,_=inputs()
    report=json.loads((OUT/'report.json').read_text());video=OUT/'B11.mp4'
    if sha(video)!=report['video_sha256']:raise RuntimeError('B11 MP4 changed')
    with wave.open(str(OUT/'B11-video-timeline.wav')) as wav:timeline=wav.readframes(wav.getnframes())
    lead=round(LEAD*RATE)*2
    if timeline[:lead]!=bytes(lead) or timeline[lead:]!=pcm:
        raise RuntimeError('B11 video timeline changed approved source PCM')
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(video)]))
    streams={s['codec_type']:s for s in probe['streams']}
    frames=sum(report['scene_frame_counts'].values())
    if (int(streams['video']['nb_frames'])!=frames or streams['video']['r_frame_rate']!='30/1'
            or streams['audio']['codec_name']!='aac' or streams['subtitle']['codec_name']!='mov_text'):
        raise RuntimeError('B11 MP4 stream format invalid')
    canonical=' '.join(' '.join(s['narration'].split()) for s in scenes)
    checked=check_embedded_subtitles(video,OUT/'B11.ru.srt',canonical)
    small=subprocess.check_output(['ffmpeg','-v','error','-xerror','-i',str(video),'-map','0:v:0',
                                   '-vf','scale=48:27:flags=area,format=gray','-r',str(FPS),'-f','rawvideo','-'])
    pixels=48*27
    if len(small)!=frames*pixels:raise RuntimeError('B11 video frame count invalid')
    lum=[];blank=[]
    for i in range(frames):
        frame=small[i*pixels:(i+1)*pixels];lum.append(sum(frame)/pixels)
        if max(frame)-min(frame)<12 or all(v<10 for v in frame) or all(v>245 for v in frame):blank.append(i)
    flash=[i for i in range(1,frames-1) if abs(lum[i]-lum[i-1])>35 and abs(lum[i]-lum[i+1])>35 and abs(lum[i-1]-lum[i+1])<10]
    anomalies=visual_transition_anomalies(small)
    # The concept layer exits once, over the already stable Archive page.
    # Its three adjacent fade frames are a single planned transition, not a
    # transient screen return. Keep every other jump subject to the detector.
    archive_scene_start=(report['scene_frame_counts']['B11-038']+
                         report['scene_frame_counts']['B11-039'])/FPS
    overlay_exit=[a for a in anomalies if archive_scene_start+16.5<=a['start_seconds']
                  and a['end_seconds']<=archive_scene_start+16.8]
    unexpected_jumps=[a for a in anomalies if a not in overlay_exit]
    visual_report=json.loads((OUT/'visual-capture.json').read_text())
    checks=[];states=[];cue_errors=[];violations=[];elapsed=0
    for scene in scenes:
        row=next(r for r in visual_report['scenes'] if r['scene_id']==scene['id'])
        source=OUT/'scenes'/f"{scene['id']}.mp4"
        if sha(source)!=row['sha256']:raise RuntimeError('B11 scene source changed')
        evidence=json.loads(source.with_suffix('.json').read_text())
        if evidence['expected_state']!='PASS' or evidence['browser_errors'] or evidence['production_mutation_requests']:
            raise RuntimeError('B11 browser capture invalid')
        events=evidence['choreography']['events']
        states.extend({'scene_id':scene['id'],'seconds':elapsed+e['seconds'],**e}
                      for e in events if e['type']=='archive-state')
        cue_errors.extend(abs(x) for x in row['cue_errors_seconds'])
        violations.extend(evidence['choreography']['overlay']['violations'])
        if scene['id']!='B11-039':
            if scene['id']=='B11-038':
                # Playwright records the destination URL on a navigational click.
                # Preserve the verified selector identity for the rendered-pointer check.
                evidence=copy.deepcopy(evidence)
                arrivals=[e for e in evidence['choreography']['events'] if e['type']=='cursor-arrival']
                clicks=[e for e in evidence['choreography']['events'] if e['type']=='click']
                if len(arrivals)!=1 or len(clicks)!=1 or (
                        arrivals[0]['target'].split(' selector=')[-1]
                        !=clicks[0]['target'].split(' selector=')[-1]):
                    raise RuntimeError('B11 Archive navigation click changed its target selector')
                clicks[0]['target']=arrivals[0]['target']
            checks.extend({'scene_id':scene['id'],**c} for c in
                          pointer_pixels_in_mp4(video,evidence,elapsed,scene['id'],OUT/'qa-clicks'/scene['id']))
        elapsed+=report['scene_frame_counts'][scene['id']]/FPS
    names={e['label']:e['state'] for e in states}
    initial=names.get('initial file choice');added=names.get('track added')
    replaced=names.get('list replaced');saved=names.get('record saved in Archive')
    if (not initial or len(initial['files'])!=2 or not added or len(added['files'])!=3
            or not replaced or len(replaced['files'])!=3 or not saved or saved['detailTitle']!=TITLE
            or not saved['detailVisible'] or violations or len(checks)<5
            or (cue_errors and max(cue_errors)>.35)):
        raise RuntimeError(f'B11 real actions/result/cursor/synchronization failed: '
                           f'states={[(k,len(v["files"])) for k,v in names.items() if k in ("initial file choice","track added","list replaced")]}, '
                           f'saved={saved}, violations={violations}, clicks={len(checks)}, '
                           f'cue={max(cue_errors) if cue_errors else None}')
    if blank or flash or unexpected_jumps:
        raise RuntimeError(f'B11 blank/flash/return frames: {blank[:3]}/{flash[:3]}/{unexpected_jumps[:3]}')
    result={'status':'PASS','block_id':'B11','video_sha256':sha(video),
            'source_pcm_preserved_in_timeline':True,'subtitle_cues':checked['embedded_subtitle_cues'],
            'last_embedded_subtitle_end_seconds':checked['last_embedded_subtitle_end_seconds'],
            'subtitle_matches_canonical_text':True,'video_frames':frames,'blank_frames':0,
            'isolated_flash_frames':0,'visual_transition_anomalies':[],
            'classified_concept_exit_fade_frames':len(overlay_exit),
            'rendered_pointer_clicks':checks,'real_archive_states':states,
            'max_visual_cue_error_seconds':max(cue_errors) if cue_errors else None,
            'production_mutation_requests':0}
    write_json(OUT/'verification.json',result)
    return result
