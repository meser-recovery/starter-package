#!/usr/bin/env python3
"""B13 real Editor–Archive routes in an isolated local portal."""
from __future__ import annotations

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
from b13_actions import prepare, perform, prepare_speaker_history, state, reveal, follow_link, archive_from_editor, publish, save_final
from browser_capture import capture
from build import demo_server
from modules import cached, map_timing, request_text_and_indices, sha, write_json
from validate import ROOT, validate

OUT=ROOT/'generated/b13-block-review'
AUDIO=ROOT/'generated/narration-blocks-v2/B13'
SCENE_IDS=tuple(f'B13-{number:03d}' for number in range(46,52))
VARIANT='B13-review-01'
LEAD=.6
RATE=44100
FPS=30
FRAME_BYTES=1920*1080*3//2


def inputs():
    validate();validate_block_approval('B12')
    spec=json.loads((ROOT/'tutorial.yaml').read_text())
    module=next(m for m in spec['narration_modules'] if m['id']=='B13')
    hit=cached(spec,module)
    if not hit:raise RuntimeError('B13 one-request narration is missing or stale')
    metadata=json.loads((AUDIO/f'{VARIANT}-metadata.json').read_text())
    review=json.loads((AUDIO/'B13-review-map.json').read_text())
    if (review['status'],review['block_id'],review['variant_id'])!=('SEMANTIC_REVIEWED','B13','review-01'):
        raise RuntimeError('B13 semantic pause map invalid')
    for path,digest in ((AUDIO/'narration.mp3',metadata['source_mp3_sha256']),
                        (AUDIO/f'{VARIANT}.mp3',metadata['mp3_sha256']),
                        (AUDIO/f'{VARIANT}.wav',metadata['wav_sha256']),
                        (AUDIO/f'{VARIANT}-timing.json',metadata['timing_sha256']),
                        (AUDIO/f'{VARIANT}-source-timing.json',metadata['source_timing_sha256'])):
        if sha(path)!=digest:raise RuntimeError('B13 reviewed audio changed: '+str(path))
    if (metadata['source_mp3_sha256']!=hit['metadata']['audio_sha256']
            or metadata['new_tts_requests'] or metadata['speed_pitch_gain_processing']
            or not metadata['source_pcm_recovered_exactly']
            or [x['after_offset'] for x in metadata['events']]!=[x['after_offset'] for x in review['insertions']]):
        raise RuntimeError('B13 source/review provenance invalid')
    with wave.open(str(AUDIO/f'{VARIANT}.wav')) as wav:
        if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())!=(1,2,RATE):
            raise RuntimeError('B13 WAV format invalid')
        pcm=wav.readframes(wav.getnframes());duration=wav.getnframes()/RATE
    if hashlib.sha256(pcm).hexdigest()!=metadata['final_pcm_sha256']:
        raise RuntimeError('B13 final PCM changed')
    original=subprocess.check_output(['ffmpeg','-v','error','-xerror','-i',str(AUDIO/'narration.mp3'),
                                      '-ac','1','-ar',str(RATE),'-c:a','pcm_s16le','-f','s16le','-'])
    restored=bytearray();previous=0
    for event in metadata['events']:
        start=event['insert_start_final_sample']*2;end=start+event['added_samples']*2
        if pcm[start:end]!=bytes(end-start):raise RuntimeError('B13 inserted PCM is not silent')
        restored.extend(pcm[previous:start]);previous=end
    restored.extend(pcm[previous:])
    if bytes(restored)!=original:raise RuntimeError('B13 source PCM is not exactly restored')
    timing=json.loads((AUDIO/f'{VARIANT}-timing.json').read_text())
    if timing!=map_timing(spec,module,timing['alignment'],timing['duration_seconds']):
        raise RuntimeError('B13 alignment no longer maps to canonical text')
    scenes=[s for s in spec['scenes'] if s['id'] in SCENE_IDS]
    if tuple(s['id'] for s in scenes)!=SCENE_IDS:raise RuntimeError('B13 scene map changed')
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
        raise RuntimeError('B13 scene alignment differs from canonical text')
    return {**row,'alignment':local,'duration_seconds':end-start,
            'timing_identity':hashlib.sha256((metadata['timing_sha256']+scene['id']).encode()).hexdigest()}


def capture_spec(scene):
    return {**scene,'visual':{'type':'browser','goal':scene['goal'],
                             'capture_pipeline_revision':'b13-archive-workflow-v1'},
            'initial_state':scene['id'],'expected_state':'B13 archive action completed',
            'assertions':[],'fixture_set':'existing-synthetic-zoom-v1',
            'padding':{'head':0.,'tail':0.}}


async def visual():
    if (ROOT/'approvals/B13-block.json').exists():raise RuntimeError('B13 approved and immutable')
    spec,module,scenes,metadata,timing,_,duration=inputs()
    (OUT/'scenes').mkdir(parents=True,exist_ok=True)
    recipe='\n'.join(inspect.getsource(fn) for fn in
                     (capture_spec,state,reveal,follow_link,archive_from_editor,publish,save_final,
                      prepare_speaker_history,prepare,perform))
    identity=hashlib.sha256((recipe+json.dumps([VARIANT,SCENE_IDS],ensure_ascii=False)).encode()).hexdigest()
    rows=[]
    for scene in scenes:
        with demo_server(None) as base:
            local=scene_timing(spec,module,scene,timing,metadata,duration)
            local.update(visual_lead_seconds=LEAD if scene['id']==SCENE_IDS[0] else 0.,
                         visual_source_sha256=identity,strict_choreography=False)
            path=OUT/'scenes'/f"{scene['id']}.mp4"
            evidence=await capture(capture_spec(scene),spec['narration'],base,timing=local,
                                   destination=path,prepare_scene=prepare,perform_scene=perform)
            if evidence['browser_errors'] or evidence['production_mutation_requests']:
                raise RuntimeError('B13 isolated capture failed')
            if max((e['seconds'] for e in evidence['choreography']['events']),default=0)>local['duration_seconds']+local['visual_lead_seconds']+.25:
                raise RuntimeError('B13 action exceeds narrated scene: '+scene['id'])
            row={'scene_id':scene['id'],'visual':str(path),'sha256':sha(path),
                 'duration_seconds':evidence['duration_seconds'],
                 'cue_errors_seconds':[c['actual_seconds']-c['target_seconds'] for c in evidence['alignment_action_cues']],
                 'production_mutation_requests':0}
            rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    result={'status':'PASS','block_id':'B13','source_mp3_sha256':metadata['source_mp3_sha256'],
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
                if end<=start or '[' in phrase or ']' in phrase:raise RuntimeError('B13 subtitle invalid')
                cues.append((start,end,phrase));begin=i+1
    if any(cues[i][0]<cues[i-1][1]-.01 for i in range(1,len(cues))):
        raise RuntimeError('B13 subtitle cues overlap')
    for suffix in ('srt','vtt'):
        vtt=suffix=='vtt'
        body=('WEBVTT\n\n' if vtt else '')+'\n\n'.join(
            ('' if vtt else f'{i}\n')+f'{timestamp(a,vtt=vtt)} --> {timestamp(b,vtt=vtt)}\n{phrase}'
            for i,(a,b,phrase) in enumerate(cues,1))+'\n'
        (OUT/f'B13.ru.{suffix}').write_text(body)
    return cues


def assemble():
    if (ROOT/'approvals/B13-block.json').exists():raise RuntimeError('B13 approved and immutable')
    spec,module,scenes,metadata,timing,pcm,duration=inputs()
    visual_report=json.loads((OUT/'visual-capture.json').read_text())
    if (visual_report['source_mp3_sha256']!=metadata['source_mp3_sha256']
            or [r['scene_id'] for r in visual_report['scenes']]!=list(SCENE_IDS)):
        raise RuntimeError('B13 visual capture differs from source')
    timings=[scene_timing(spec,module,s,timing,metadata,duration) for s in scenes]
    cues=subtitles(scenes,timings)
    timeline=OUT/'B13-video-timeline.wav'
    with wave.open(str(timeline),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(RATE)
        wav.writeframes(bytes(round(LEAD*RATE)*2)+pcm)
    total=math.ceil(max(LEAD+duration,cues[-1][1]+.01)*FPS)/FPS
    bounds=[0]+[LEAD+t['range_start_seconds'] for t in timings[1:]]+[total]
    counts=[round(bounds[i+1]*FPS)-round(bounds[i]*FPS) for i in range(len(scenes))]
    if min(counts)<=0:raise RuntimeError('B13 scene frame count invalid')
    candidate=OUT/'B13.tmp.mp4'
    cmd=['ffmpeg','-y','-v','error','-f','rawvideo','-pixel_format','yuv420p',
         '-video_size','1920x1080','-framerate',str(FPS),'-i','pipe:0',
         '-i',str(timeline),'-i',str(OUT/'B13.ru.srt'),
         '-map','0:v:0','-map','1:a:0','-map','2:s:0',
         '-c:v','libx264','-preset','veryfast','-crf','21','-pix_fmt','yuv420p',
         '-c:a','aac','-b:a','192k','-c:s','mov_text','-metadata:s:s:0','language=rus',
         '-frames:v',str(sum(counts)),'-movflags','+faststart',str(candidate)]
    with (OUT/'encode.log').open('wb') as log:
        encoder=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=log)
        try:
            for scene,count in zip(scenes,counts):
                source=OUT/'scenes'/f"{scene['id']}.mp4"
                if not source.exists():raise RuntimeError('B13 scene missing: '+scene['id'])
                decoder=subprocess.Popen(['ffmpeg','-v','error','-xerror','-i',str(source),'-an',
                    '-vf','scale=1920:1080,fps=30,trim=start_frame=1,tpad=start=1:start_mode=clone,setpts=N/(30*TB),tpad=stop_mode=clone:stop=300',
                    '-r',str(FPS),'-frames:v',str(count),'-pix_fmt','yuv420p','-f','rawvideo','pipe:1'],stdout=subprocess.PIPE)
                copied=0
                try:
                    while chunk:=decoder.stdout.read(1024*1024):
                        encoder.stdin.write(chunk);copied+=len(chunk)
                finally:decoder.stdout.close()
                if decoder.wait() or copied!=count*FRAME_BYTES:
                    raise RuntimeError('B13 captured frame count mismatch: '+scene['id'])
            encoder.stdin.close()
            if encoder.wait():raise RuntimeError('B13 encoding failed; see encode.log')
        finally:
            if encoder.poll() is None:encoder.kill();encoder.wait()
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(candidate),'-f','null','-'],
                   check=True,stdout=subprocess.DEVNULL)
    canonical=' '.join(' '.join(s['narration'].split()) for s in scenes)
    checked=check_embedded_subtitles(candidate,OUT/'B13.ru.srt',canonical)
    final=OUT/'B13.mp4';candidate.replace(final)
    report={'status':'READY FOR B13 BLOCK REVIEW','block_id':'B13','video':str(final),
            'video_sha256':sha(final),'duration_seconds':total,
            'source_mp3_sha256':metadata['source_mp3_sha256'],'final_wav_sha256':metadata['wav_sha256'],
            'final_pcm_sha256':metadata['final_pcm_sha256'],'final_alignment_sha256':metadata['timing_sha256'],
            'video_audio_timeline':str(timeline),'video_audio_lead_seconds':LEAD,
            'insertions':len(metadata['events']),'scene_frame_counts':dict(zip(SCENE_IDS,counts)),
            'embedded_subtitle_cues':checked['embedded_subtitle_cues'],
            'last_embedded_subtitle_end_seconds':checked['last_embedded_subtitle_end_seconds'],
            'tts_requests_for_source':1,'production_mutation_requests':0}
    write_json(OUT/'report.json',report)
    version=report['video_sha256'][:8]
    (OUT/'index.html').write_text(f'''<!doctype html>
<html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>B13 · просмотр блока</title>
<style>body{{margin:0;background:#101724;color:#eef3f6;font:16px/1.5 system-ui,sans-serif}}
main{{max-width:1100px;margin:auto;padding:24px}}video{{display:block;width:100%;background:#000;margin:24px 0}}
a{{color:#8cd0e9}}code{{overflow-wrap:anywhere}}</style>
<main><h1>B13 · версии, проекты и история</h1>
<p>Сцены 046–051 · {total:.3f} с · READY FOR B13 BLOCK REVIEW</p>
<video controls playsinline preload="metadata"><source src="B13.mp4?v={version}" type="video/mp4">
<track kind="subtitles" srclang="ru" label="Русские субтитры" src="B13.ru.vtt" default></video>
<p><a href="B13.mp4?v={version}" download>Скачать MP4</a> · <a href="B13.ru.srt" download>Скачать SRT</a></p>
<p>SHA-256 MP4: <code>{report['video_sha256']}</code></p></main></html>''')
    return report


def verify():
    spec,module,scenes,metadata,timing,pcm,_=inputs()
    report=json.loads((OUT/'report.json').read_text());video=OUT/'B13.mp4'
    if sha(video)!=report['video_sha256']:raise RuntimeError('B13 MP4 changed')
    with wave.open(str(OUT/'B13-video-timeline.wav')) as wav:timeline=wav.readframes(wav.getnframes())
    lead=round(LEAD*RATE)*2
    if timeline[:lead]!=bytes(lead) or timeline[lead:]!=pcm:
        raise RuntimeError('B13 video timeline changed approved source PCM')
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(video)]))
    streams={s['codec_type']:s for s in probe['streams']}
    frames=sum(report['scene_frame_counts'].values())
    if (int(streams['video']['nb_frames'])!=frames or streams['video']['r_frame_rate']!='30/1'
            or streams['audio']['codec_name']!='aac' or streams['subtitle']['codec_name']!='mov_text'):
        raise RuntimeError('B13 MP4 stream format invalid')
    canonical=' '.join(' '.join(s['narration'].split()) for s in scenes)
    checked=check_embedded_subtitles(video,OUT/'B13.ru.srt',canonical)
    small=subprocess.check_output(['ffmpeg','-v','error','-xerror','-i',str(video),'-map','0:v:0',
                                   '-vf','scale=48:27:flags=area,format=gray','-r',str(FPS),'-f','rawvideo','-'])
    pixels=48*27
    if len(small)!=frames*pixels:raise RuntimeError('B13 video frame count invalid')
    lum=[];blank=[]
    for i in range(frames):
        frame=small[i*pixels:(i+1)*pixels];lum.append(sum(frame)/pixels)
        if max(frame)-min(frame)<12 or all(v<10 for v in frame) or all(v>245 for v in frame):blank.append(i)
    flash=[i for i in range(1,frames-1) if abs(lum[i]-lum[i-1])>35 and abs(lum[i]-lum[i+1])>35 and abs(lum[i-1]-lum[i+1])<10]
    anomalies=visual_transition_anomalies(small)
    visual_report=json.loads((OUT/'visual-capture.json').read_text())
    checks=[];states=[];cue_errors=[];violations=[];elapsed=0
    for scene in scenes:
        row=next(r for r in visual_report['scenes'] if r['scene_id']==scene['id'])
        source=OUT/'scenes'/f"{scene['id']}.mp4"
        if sha(source)!=row['sha256']:raise RuntimeError('B13 scene source changed')
        evidence=json.loads(source.with_suffix('.json').read_text())
        if evidence['expected_state']!='PASS' or evidence['browser_errors'] or evidence['production_mutation_requests']:
            raise RuntimeError('B13 browser capture invalid')
        events=evidence['choreography']['events']
        states.extend({'scene_id':scene['id'],'seconds':elapsed+e['seconds'],**e}
                      for e in events if e['type']=='b13-state')
        cue_errors.extend(abs(x) for x in row['cue_errors_seconds'])
        violations.extend(evidence['choreography']['overlay']['violations'])
        if scene['id']=='B13-042' and not any(e['type']=='intentional-import-scroll' and
                e['to']>e['from']+100 and e['end_seconds']-e['seconds']>.9 for e in events):
            raise RuntimeError('B13 local save dialog was not visibly scrolled')
        click_evidence=copy.deepcopy(evidence)
        arrivals=[e for e in click_evidence['choreography']['events'] if e['type']=='cursor-arrival']
        clicks=[e for e in click_evidence['choreography']['events'] if e['type']=='click']
        for click in clicks:
            if any(a['target']==click['target'] and a['seconds']<=click['seconds'] for a in arrivals):
                continue
            # Navigation changes Playwright's frame URL after pointer-up. The
            # real selector must still match the prior arrival before pixel QA.
            same=[a for a in arrivals if a['seconds']<=click['seconds'] and
                  a['target'].split(' selector=')[-1]==click['target'].split(' selector=')[-1]]
            if not same:raise RuntimeError('B13 navigational click changed its real target')
            click['target']=max(same,key=lambda a:a['seconds'])['target']
        # Native select interactions also emit pointerdown, but are audited as
        # select events rather than clicks. Pair each recorded click with the
        # next pointerdown inside that click's real control rectangle.
        downs=[e for e in click_evidence['choreography']['overlay']['events'] if e['type']=='pointerdown']
        paired=[];cursor=0
        for click in clicks:
            arrival=max((a for a in arrivals if a['target']==click['target'] and a['seconds']<=click['seconds']),
                        key=lambda a:a['seconds'])
            box=arrival['box']
            while cursor<len(downs):
                down=downs[cursor];cursor+=1
                if (box['x']<=down['x']<=box['x']+box['width'] and
                        box['y']<=down['y']<=box['y']+box['height']):
                    paired.append(down);break
            else:raise RuntimeError('B13 rendered pointer missed a real clicked control')
        click_evidence['choreography']['overlay']['events']=[e for e in click_evidence['choreography']['overlay']['events']
            if e['type']!='pointerdown']+paired
        checks.extend({'scene_id':scene['id'],**c} for c in
                      pointer_pixels_in_mp4(video,click_evidence,elapsed,scene['id'],OUT/'qa-clicks'/scene['id']))
        elapsed+=report['scene_frame_counts'][scene['id']]/FPS
    names={e['label']:e['state'] for e in states}
    def require(label, predicate):
        row=names.get(label)
        if not row or not predicate(row):
            raise RuntimeError(f'B13 captured result missing or invalid: {label}: {row}')
    require('original source and announcement version visible',
            lambda x:x['detailTitle']=='Спикер' and len(x['announcementVersions'])==1)
    require('second announcement version saved',lambda x:'Версия 2 сохранена' in x['publicationStatus'])
    require('both announcement versions retained',lambda x:len(x['announcementVersions'])==2)
    require('Speaker project saved with cut and setting',
            lambda x:x['tracks']==4 and x['cuts']>=1 and x['enhancement']=='gentle' and max(x['waveformColors'],default=0)>20)
    require('restored tracks cut and processing',
            lambda x:x['tracks']==4 and x['cuts']>=1 and x['enhancement']=='gentle' and max(x['waveformColors'],default=0)>20)
    require('second Speaker project state saved',
            lambda x:x['tracks']==4 and x['cuts']>=1 and x['silence']>=1 and 'сохранен' in x['saveStatus'].lower())
    require('real local source and project confirmation',lambda x:x['localSaveDialog'])
    require('first local project state visible in Archive',
            lambda x:x['detailTitle']=='Спикер' and len(x['projectStates'])==1)
    require('second local project state saved',
            lambda x:x['tracks']==4 and x['enhancement']=='gentle' and 'сохранен' in x['saveStatus'].lower())
    require('final version and linked state visible',
            lambda x:len(x['speakerVersions'])==1 and len(x['projectStates'])==4 and
                     any('Связанные финальные версии: 1' in z for z in x['projectStates']))
    require('both Speaker final versions retained',
            lambda x:len(x['speakerVersions'])==2 and len(x['projectStates'])==5 and
                     any('Связанные финальные версии: 1' in z for z in x['projectStates']) and
                     any('Связанные финальные версии: 2' in z for z in x['projectStates']))
    require('older final state differs from latest edit',
            lambda x:x['tracks']==4 and x['cuts']==1 and x['silence']==0 and max(x['waveformColors'],default=0)>20)
    if violations or len(checks)<12 or (cue_errors and max(cue_errors)>1.5):
        raise RuntimeError(f'B13 pointer/overlay/synchronization failed: '
                           f'violations={violations}, clicks={len(checks)}, '
                           f'max_cue={max(cue_errors) if cue_errors else None}')
    if blank or flash or anomalies:
        raise RuntimeError(f'B13 blank/flash/return frames: {blank[:3]}/{flash[:3]}/{anomalies[:3]}')
    result={'status':'PASS','block_id':'B13','video_sha256':sha(video),
            'source_pcm_preserved_in_timeline':True,'subtitle_cues':checked['embedded_subtitle_cues'],
            'last_embedded_subtitle_end_seconds':checked['last_embedded_subtitle_end_seconds'],
            'subtitle_matches_canonical_text':True,'video_frames':frames,'blank_frames':0,
            'isolated_flash_frames':0,'visual_transition_anomalies':[],
            'rendered_pointer_clicks':checks,'real_interface_states':states,
            'max_visual_cue_error_seconds':max(cue_errors) if cue_errors else None,
            'production_mutation_requests':0}
    write_json(OUT/'verification.json',result)
    return result
