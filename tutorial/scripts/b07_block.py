#!/usr/bin/env python3
"""Render B07 from one reviewed take, real Speaker controls and concept animation."""
from __future__ import annotations

import array
import asyncio
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
from browser_capture import capture
from build import demo_server
from modules import cached, map_timing, request_text_and_indices, sha, write_json
from scenes import import_local, login
from validate import ROOT, validate

OUT = ROOT / 'generated/b07-block-review'
AUDIO = ROOT / 'generated/narration-blocks-v2/B07'
SCENE_IDS = ('B07-019', 'B07-020', 'B07-021', 'B07-022')
VARIANT = 'B07-review-01'
ANIMATION = ROOT / 'animations/b07-processing.html'
LEAD = .6
RATE = 44100
FPS = 30
FRAME_BYTES = 1920 * 1080 * 3 // 2


def inputs():
    validate()
    validate_block_approval('B06')
    spec = json.loads((ROOT / 'tutorial.yaml').read_text())
    module = next(m for m in spec['narration_modules'] if m['id'] == 'B07')
    hit = cached(spec, module)
    if not hit:
        raise RuntimeError('B07 one-request narration is missing or stale')
    metadata = json.loads((AUDIO / f'{VARIANT}-metadata.json').read_text())
    review = json.loads((AUDIO / 'B07-review-map.json').read_text())
    if (review['status'], review['block_id'], review['variant_id']) != ('SEMANTIC_REVIEWED', 'B07', 'review-01'):
        raise RuntimeError('B07 semantic review map invalid')
    for path, digest in ((AUDIO / 'narration.mp3', metadata['source_mp3_sha256']),
                         (AUDIO / f'{VARIANT}.mp3', metadata['mp3_sha256']),
                         (AUDIO / f'{VARIANT}.wav', metadata['wav_sha256']),
                         (AUDIO / f'{VARIANT}-timing.json', metadata['timing_sha256'])):
        if sha(path) != digest:
            raise RuntimeError('B07 reviewed audio source changed: ' + str(path))
    if (metadata['source_mp3_sha256'] != hit['metadata']['audio_sha256']
            or metadata['new_tts_requests'] or metadata['speed_pitch_gain_processing']
            or not metadata['source_pcm_recovered_exactly'] or metadata['events']):
        raise RuntimeError('B07 review must preserve the one unmodified source take')
    with wave.open(str(AUDIO / f'{VARIANT}.wav')) as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, RATE):
            raise RuntimeError('B07 WAV format invalid')
        pcm = wav.readframes(wav.getnframes())
        duration = wav.getnframes() / RATE
    if hashlib.sha256(pcm).hexdigest() != metadata['final_pcm_sha256']:
        raise RuntimeError('B07 PCM source changed')
    timing = json.loads((AUDIO / f'{VARIANT}-timing.json').read_text())
    if timing != map_timing(spec, module, timing['alignment'], timing['duration_seconds']):
        raise RuntimeError('B07 alignment no longer maps to canonical text')
    scenes = [s for s in spec['scenes'] if s['id'] in SCENE_IDS]
    if tuple(s['id'] for s in scenes) != SCENE_IDS:
        raise RuntimeError('B07 storyboard order changed')
    return spec, module, scenes, metadata, timing, pcm, duration


def scene_timing(spec, module, scene, timing, metadata, audio_duration):
    row = next(r for r in timing['scenes'] if r['scene_id'] == scene['id'])
    start = row['range_start_seconds']
    end = min(row['range_end_seconds'], audio_duration)
    _, indices = request_text_and_indices(spec, module)
    positions = indices[scene['start_offset']:scene['end_offset']]
    full = timing['alignment']
    alignment = {'characters': [full['characters'][i] for i in positions],
                 'character_start_times_seconds': [max(0, full['character_start_times_seconds'][i]-start) for i in positions],
                 'character_end_times_seconds': [max(0, full['character_end_times_seconds'][i]-start) for i in positions]}
    if ''.join(alignment['characters']) != scene['narration']:
        raise RuntimeError('B07 scene alignment differs from canonical text')
    return {**row, 'alignment': alignment, 'duration_seconds': end-start,
            'range_start_seconds': start, 'range_end_seconds': end,
            'timing_identity': hashlib.sha256((metadata['timing_sha256']+scene['id']).encode()).hexdigest()}


def capture_spec(scene):
    return {**scene, 'visual': {'type': 'browser', 'goal': scene['goal'],
                               'capture_pipeline_revision': 'b07-real-speaker-controls-and-processing-v1'},
            'initial_state': 'speaker-source-tracks', 'expected_state': 'B07 explained action completed',
            'assertions': [], 'fixture_set': 'existing-synthetic-zoom-v1',
            'padding': {'head': 0., 'tail': 0.}}


def track(page, filename):
    return page.locator('#speaker-editor-tracks .speaker-track').filter(has_text=filename)


async def prepare(page, scene, base):
    await page.set_viewport_size({'width': 1536, 'height': 864})
    await login(page, base)
    await import_local(page, base, None if scene['id'] == 'B07-019' else 'speaker')
    if scene['id'] == 'B07-019':
        await page.locator('#workflow-choice').wait_for(state='visible')
        await page.locator('#open-local-speaker').scroll_into_view_if_needed()
        return
    await page.wait_for_function("document.querySelectorAll('#speaker-editor-tracks .speaker-track canvas').length===4", timeout=60000)
    await page.wait_for_timeout(800)
    if scene['id'] == 'B07-020':
        await track(page, 'Спикер.wav').scroll_into_view_if_needed()
        await install_explainer(page, 'leveling', visible=False)
    elif scene['id'] == 'B07-021':
        await track(page, 'Участник.wav').scroll_into_view_if_needed()
        await install_explainer(page, 'monitor', visible=False)
    else:
        row = track(page, 'Участник.wav')
        await row.locator('[data-action="mute"]').click()
        if await row.locator('[data-action="mute"]').get_attribute('aria-pressed') != 'true':
            raise RuntimeError('B07 requires a muted but included source track')
        await row.get_by_role('button', name='Исключить из микса').scroll_into_view_if_needed()
        await install_explainer(page, 'monitor', visible=False)
    await page.wait_for_timeout(150)


async def install_explainer(page, mode, *, visible):
    html = ANIMATION.read_text().replace(
        "const mode=new URLSearchParams(location.search).get('mode')||'leveling';",
        f"const mode='{mode}';")
    await page.evaluate("""({html,visible}) => {
        document.querySelector('#b07-explainer')?.remove();
        const frame=document.createElement('iframe');frame.id='b07-explainer';
        frame.setAttribute('aria-label','Объяснение обработки дорожек');
        frame.srcdoc=html;
        Object.assign(frame.style,{position:'fixed',inset:'0',width:'100vw',height:'100vh',
          border:'0',background:'#f7fafc',zIndex:'100000',pointerEvents:'none',
          visibility:visible?'visible':'hidden'});
        document.body.append(frame);
    }""", {'html':html,'visible':visible})
    await page.wait_for_function("typeof document.querySelector('#b07-explainer')?.contentWindow?.b07SetPhase === 'function'")


async def animation_phase(page, phase, *, show=False, hide=False):
    await page.evaluate("""({phase,show,hide}) => {
        const frame=document.querySelector('#b07-explainer');
        if(show) frame.style.visibility='visible';
        if(phase) frame.contentWindow.b07SetPhase(phase);
        if(hide) frame.style.visibility='hidden';
    }""", {'phase':phase,'show':show,'hide':hide})


async def semantic_moment(cue, phrase):
    await cue(phrase)
    await cue.__self__.wait_pending()


async def perform(page, scene, base, cue):
    scene_id = scene['id']
    if scene_id == 'B07-019':
        await cue('«Спикерская»')
        await page.locator('#open-local-speaker').click()
        await page.locator('#speaker-editor').wait_for(state='visible', timeout=60000)
        await page.wait_for_function("document.querySelectorAll('#speaker-editor-tracks .speaker-track canvas').length===4", timeout=60000)
        await page.evaluate("window.__s11Capture.hide('speaker-opened')")
        await page.locator('#speaker-editor-tracks').scroll_into_view_if_needed()
        await semantic_moment(cue, 'Для каждой дорожки доступны три вида обработки')
        await track(page, 'Спикер.wav').scroll_into_view_if_needed()
    elif scene_id == 'B07-020':
        row=track(page, 'Спикер.wav')
        await cue('ослабить низкий гул')
        await row.locator('[data-dsp-field="enhancement"]').check()
        await page.wait_for_function("async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload.trackProcessing[0].enhancement==='gentle'")
        await page.evaluate("window.__s11Capture.hide('enhancement-set')")
        await cue('Выравнивание громкости')
        await row.locator('[data-dsp-field="leveling"]').check()
        await page.wait_for_function("async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload.trackProcessing[0].leveling==='on'")
        await page.evaluate("window.__s11Capture.hide('leveling-set')")
        await animation_phase(page, 'leveling-start', show=True)
        await semantic_moment(cue, 'один участник записан заметно тише')
        await animation_phase(page, 'leveling-done')
        await cue('Компрессия уменьшает разницу')
        await animation_phase(page, '', hide=True)
        await row.locator('[data-dsp-field="compression"]').click()
        await page.wait_for_function("async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload.trackProcessing[0].compression!=='off'")
        await page.evaluate("window.__s11Capture.hide('compression-set')")
        await install_explainer(page, 'compression', visible=True)
        await semantic_moment(cue, 'в рамках одной и той же дорожки')
        await animation_phase(page, 'compression-done')
        await semantic_moment(cue, 'Все эти настройки доступны')
        await animation_phase(page, '', hide=True)
        await track(page, 'Спикер.wav').scroll_into_view_if_needed()
    elif scene_id == 'B07-021':
        speaker=track(page, 'Спикер.wav')
        participant=track(page, 'Участник.wav')
        await cue('Solo позволяет')
        await speaker.locator('[data-action="solo"]').click()
        if await speaker.locator('[data-action="solo"]').get_attribute('aria-pressed') != 'true':
            raise RuntimeError('B07 real Solo did not activate')
        await cue('Mute — временно отключить')
        await participant.locator('[data-action="mute"]').click()
        if await participant.locator('[data-action="mute"]').get_attribute('aria-pressed') != 'true':
            raise RuntimeError('B07 real Mute did not activate')
        if 'в финальном миксе' not in await participant.inner_text():
            raise RuntimeError('B07 Mute must keep source in final mix')
        await page.evaluate("window.__s11Capture.hide('monitoring-set')")
        await semantic_moment(cue, 'не изменяют конечный результат')
        await animation_phase(page, 'mute', show=True)
        await semantic_moment(cue, 'Но в режиме «Спикерская»')
        await animation_phase(page, '', hide=True)
        await participant.get_by_role('button',name='Исключить из микса').scroll_into_view_if_needed()
    elif scene_id == 'B07-022':
        row=track(page, 'Участник.wav')
        await cue('такое отключение')
        await row.get_by_role('button', name='Исключить из микса').click()
        await page.wait_for_function("document.querySelector('#speaker-editor-tracks .speaker-track:last-child').classList.contains('is-excluded')")
        await page.evaluate("window.__s11Capture.hide('track-excluded')")
        await semantic_moment(cue, 'звук этой дорожки не попадёт')
        await animation_phase(page, 'excluded', show=True)
        await semantic_moment(cue, 'сама исходная дорожка не удаляется')
        await animation_phase(page, '', hide=True)
        if await row.count()!=1 or 'Не в финальном миксе' not in await row.inner_text():
            raise RuntimeError('B07 excluded source must remain in project')
        await cue('снова вернуть в финальный микс')
        await row.get_by_role('button',name='Вернуть в микс').click()
        await page.wait_for_function("!document.querySelector('#speaker-editor-tracks .speaker-track:last-child').classList.contains('is-excluded')")
        await page.evaluate("window.__s11Capture.hide('track-restored')")
    else:
        raise RuntimeError('unexpected B07 scene')


async def visual():
    if (ROOT / 'approvals/B07-block.json').exists():
        raise RuntimeError('B07 complete block is approved and immutable')
    spec, module, scenes, metadata, timing, _, audio_duration = inputs()
    (OUT / 'scenes').mkdir(parents=True, exist_ok=True)
    recipe = '\n'.join(inspect.getsource(fn) for fn in
                       (capture_spec, track, prepare, install_explainer, animation_phase, semantic_moment, perform))
    identity = hashlib.sha256(recipe.encode() + ANIMATION.read_bytes()).hexdigest()
    rows = []
    with demo_server(None) as base:
        for scene in scenes:
            local = scene_timing(spec, module, scene, timing, metadata, audio_duration)
            local.update(visual_lead_seconds=LEAD if scene['id'] == SCENE_IDS[0] else 0.,
                         visual_source_sha256=identity, strict_choreography=False)
            path = OUT / 'scenes' / f"{scene['id']}.mp4"
            evidence = await capture(capture_spec(scene), spec['narration'], base, timing=local,
                                     destination=path, prepare_scene=prepare, perform_scene=perform)
            if evidence['browser_errors'] or evidence['production_mutation_requests']:
                raise RuntimeError('B07 isolated capture failed')
            if max((e['seconds'] for e in evidence['choreography']['events']), default=0) > local['duration_seconds']+local['visual_lead_seconds']+.2:
                raise RuntimeError(f"B07 {scene['id']} action extends beyond its narrated scene")
            row = {'scene_id': scene['id'], 'visual': str(path), 'sha256': sha(path),
                   'duration_seconds': evidence['duration_seconds'],
                   'cue_errors_seconds': [c['actual_seconds']-c['target_seconds'] for c in evidence['alignment_action_cues']],
                   'production_mutation_requests': evidence['production_mutation_requests']}
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    result = {'status':'PASS','block_id':'B07','source_mp3_sha256':metadata['source_mp3_sha256'],
              'final_wav_sha256':metadata['wav_sha256'],'tts_requests':0,'scenes':rows}
    write_json(OUT / 'visual-capture.json', result)
    return result


def subtitles(scenes, timings):
    cues = []
    for scene, timing in zip(scenes, timings):
        text = scene['narration']
        starts = timing['alignment']['character_start_times_seconds']
        ends = timing['alignment']['character_end_times_seconds']
        words = list(re.finditer(r'\S+', text))
        begin = 0
        for i, word in enumerate(words):
            first, last = words[begin].start(), word.end()-1
            phrase = ' '.join(text[first:last+1].split())
            if len(phrase) >= 68 or word.group()[-1:] in '.!?…' or i == len(words)-1:
                start = LEAD + timing['range_start_seconds'] + starts[first]
                end = LEAD + timing['range_start_seconds'] + ends[last]
                if end <= start or '[' in phrase or ']' in phrase:
                    raise RuntimeError('B07 subtitle timing/text invalid')
                cues.append((start,end,phrase));begin=i+1
    if any(cues[i][0] < cues[i-1][1]-.01 for i in range(1,len(cues))):
        raise RuntimeError('B07 subtitle cues overlap')
    for suffix in ('srt','vtt'):
        vtt = suffix == 'vtt'
        content = ('WEBVTT\n\n' if vtt else '') + '\n\n'.join(
            ('' if vtt else f'{i}\n') + f'{timestamp(a,vtt=vtt)} --> {timestamp(b,vtt=vtt)}\n{text}'
            for i,(a,b,text) in enumerate(cues,1)) + '\n'
        (OUT / f'B07.ru.{suffix}').write_text(content)
    return cues


def assemble():
    if (ROOT / 'approvals/B07-block.json').exists():
        raise RuntimeError('B07 complete block is approved and immutable')
    spec,module,scenes,metadata,timing,pcm,audio_duration=inputs()
    capture_report=json.loads((OUT/'visual-capture.json').read_text())
    if (capture_report['source_mp3_sha256']!=metadata['source_mp3_sha256']
            or [r['scene_id'] for r in capture_report['scenes']]!=list(SCENE_IDS)):
        raise RuntimeError('B07 scene capture differs from source audio')
    timings=[scene_timing(spec,module,s,timing,metadata,audio_duration) for s in scenes]
    cues=subtitles(scenes,timings)
    timeline=OUT/'B07-video-timeline.wav'
    with wave.open(str(timeline),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(RATE)
        wav.writeframes(bytes(round(LEAD*RATE)*2)+pcm)
    duration=math.ceil(max(LEAD+audio_duration,cues[-1][1]+.01)*FPS)/FPS
    bounds=[0]+[LEAD+t['range_start_seconds'] for t in timings[1:]]+[duration]
    counts=[round(bounds[i+1]*FPS)-round(bounds[i]*FPS) for i in range(len(scenes))]
    if min(counts)<=0:
        raise RuntimeError('B07 scene frame count invalid')
    candidate=OUT/'B07.tmp.mp4'
    command=['ffmpeg','-y','-v','error','-f','rawvideo','-pixel_format','yuv420p',
             '-video_size','1920x1080','-framerate',str(FPS),'-i','pipe:0',
             '-i',str(timeline),'-i',str(OUT/'B07.ru.srt'),
             '-map','0:v:0','-map','1:a:0','-map','2:s:0',
             '-c:v','libx264','-preset','veryfast','-crf','21','-pix_fmt','yuv420p',
             '-c:a','aac','-b:a','192k','-c:s','mov_text','-metadata:s:s:0','language=rus',
             '-frames:v',str(sum(counts)),'-movflags','+faststart',str(candidate)]
    with (OUT/'encode.log').open('wb') as log:
        encoder=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=log)
        try:
            for scene,count in zip(scenes,counts):
                path=OUT/'scenes'/f"{scene['id']}.mp4"
                if not path.is_file():
                    raise RuntimeError('B07 scene missing: '+scene['id'])
                decoder=subprocess.Popen(['ffmpeg','-v','error','-xerror','-i',str(path),'-an',
                                          '-vf','scale=1920:1080,fps=30,trim=start_frame=1,'
                                                'tpad=start=1:start_mode=clone,setpts=N/(30*TB),'
                                                'tpad=stop_mode=clone:stop=300',
                                          '-r',str(FPS),'-frames:v',str(count),'-pix_fmt','yuv420p',
                                          '-f','rawvideo','pipe:1'],stdout=subprocess.PIPE)
                copied=0
                try:
                    while chunk:=decoder.stdout.read(1024*1024):
                        encoder.stdin.write(chunk);copied+=len(chunk)
                finally:
                    decoder.stdout.close()
                if decoder.wait() or copied!=count*FRAME_BYTES:
                    raise RuntimeError('B07 captured frame count mismatch: '+scene['id'])
            encoder.stdin.close()
            if encoder.wait():
                raise RuntimeError('B07 MP4 encoding failed; see encode.log')
        finally:
            if encoder.poll() is None:
                encoder.kill();encoder.wait()
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(candidate),'-f','null','-'],
                   check=True,stdout=subprocess.DEVNULL)
    canonical=' '.join(' '.join(s['narration'].split()) for s in scenes)
    checked=check_embedded_subtitles(candidate,OUT/'B07.ru.srt',canonical)
    final=OUT/'B07.mp4';candidate.replace(final)
    report={'status':'READY FOR B07 BLOCK REVIEW','block_id':'B07','video':str(final),
            'video_sha256':sha(final),'duration_seconds':duration,
            'source_mp3_sha256':metadata['source_mp3_sha256'],'final_mp3_sha256':metadata['mp3_sha256'],
            'final_wav_sha256':metadata['wav_sha256'],'final_pcm_sha256':metadata['final_pcm_sha256'],
            'final_alignment_sha256':metadata['timing_sha256'],'video_audio_timeline':str(timeline),
            'video_audio_lead_seconds':LEAD,'internal_audio_silence_added_seconds':0,
            'scene_frame_counts':dict(zip(SCENE_IDS,counts)),
            'embedded_subtitle_cues':checked['embedded_subtitle_cues'],
            'last_embedded_subtitle_end_seconds':checked['last_embedded_subtitle_end_seconds'],
            'new_tts_requests':0,'production_mutation_requests':0}
    write_json(OUT/'report.json',report)
    return report


def pointer_pixels_in_mp4(video:Path,evidence:dict,scene_start:float,scene_id:str,evidence_dir:Path):
    events=evidence['choreography']['events']
    arrivals=[e for e in events if e['type']=='cursor-arrival']
    clicks=[e for e in events if e['type']=='click']
    pointerdowns=[e for e in evidence['choreography']['overlay']['events'] if e['type']=='pointerdown']
    expected={'B07-019':1,'B07-020':3,'B07-021':2,'B07-022':2}[scene_id]
    if len(arrivals)!=expected or len(clicks)!=expected or len(pointerdowns)!=expected:
        raise RuntimeError(f'{scene_id} expected {expected} real clicks, got {len(clicks)}')
    viewport_w,viewport_h=evidence['choreography']['overlay']['viewport']
    evidence_dir.mkdir(parents=True,exist_ok=True)
    checks=[]
    for number,(arrival,click) in enumerate(zip(arrivals,clicks),1):
        box=arrival['box']
        pointer=pointerdowns[number-1]
        if not (box['x']<=pointer['x']<=box['x']+box['width']
                and box['y']<=pointer['y']<=box['y']+box['height']):
            raise RuntimeError(f'{scene_id} click {number} pointer tip is outside its real control')
        target=[box['x']*960/viewport_w,box['y']*540/viewport_h,
                (box['x']+box['width'])*960/viewport_w,(box['y']+box['height'])*540/viewport_h]
        press=scene_start+click['seconds'];start=press-.3
        rgb=subprocess.check_output(['ffmpeg','-v','error','-ss',f'{start:.6f}','-i',str(video),
                                     '-t','0.9','-vf','fps=30,scale=960:540,format=rgb24',
                                     '-f','rawvideo','-'])
        frame_bytes=960*540*3;best=(0,-1,None)
        for frame_number in range(len(rgb)//frame_bytes):
            frame=rgb[frame_number*frame_bytes:(frame_number+1)*frame_bytes]
            points=[]
            for y in range(max(0,int(target[1])-12),min(540,int(target[3])+12)):
                for x in range(max(0,int(target[0])-12),min(960,int(target[2])+12)):
                    k=(y*960+x)*3;r,g,b=frame[k:k+3]
                    if r>=190 and 115<=g<=240 and b<=170 and r>g+8 and g>b+25:
                        points.append((x,y))
            if len(points)>best[0]:
                best=(len(points),frame_number,
                      [min(x for x,_ in points),min(y for _,y in points),
                       max(x for x,_ in points),max(y for _,y in points)] if points else None)
        count,frame_number,ring=best
        center=((ring[0]+ring[2])/2,(ring[1]+ring[3])/2) if ring else None
        if count<6 or ring is None or not (target[0]<=center[0]<=target[2]
                                                and target[1]<=center[1]<=target[3]):
            raise RuntimeError(f'{scene_id} click {number} misses its rendered button: ring={ring}, button={target}, gold_pixels={count}')
        frame_time=start+frame_number/FPS
        for label,when in (('before',frame_time-.35),('press',frame_time),('after',frame_time+.65)):
            png=subprocess.check_output(['ffmpeg','-v','error','-ss',f'{when:.6f}','-i',str(video),
                                         '-frames:v','1','-f','image2pipe','-vcodec','png','-'])
            (evidence_dir/f'click-{number}-{label}.png').write_bytes(png)
        check={'click':number,'target':arrival['target'],'status':'PASS',
               'button_box_half_resolution':target,'rendered_ring_box_half_resolution':ring,
               'ring_pixels':count,'press_frame_seconds':frame_time}
        if scene_id in ('B07-019','B07-022'):
            lifecycle=evidence['choreography']['overlay']['events']
            hide_events=[event for event in lifecycle if event['type']=='cursor-hide']
            if not any(0<=event['t']-pointer['t']<=2000 for event in hide_events):
                raise RuntimeError(f'{scene_id} click {number} cursor was not hidden on context change')
            check['cursor_hidden_on_context_change']=True
        checks.append(check)
    if evidence['choreography']['overlay']['cursorVisible']:
        raise RuntimeError(f'{scene_id} cursor remains visible at scene end')
    return checks


def verify():
    spec,module,scenes,metadata,timing,pcm,_=inputs()
    report=json.loads((OUT/'report.json').read_text());video=OUT/'B07.mp4'
    if sha(video)!=report['video_sha256'] or report['final_wav_sha256']!=metadata['wav_sha256']:
        raise RuntimeError('B07 video or source audio changed')
    with wave.open(str(OUT/'B07-video-timeline.wav')) as wav:
        timeline=wav.readframes(wav.getnframes())
    lead=round(LEAD*RATE)*2
    if timeline[:lead]!=bytes(lead) or timeline[lead:]!=pcm:
        raise RuntimeError('B07 video timeline changed source PCM')
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(video)]))
    streams={s['codec_type']:s for s in probe['streams']}
    frames=sum(report['scene_frame_counts'].values())
    if (int(streams['video']['nb_frames'])!=frames or streams['video']['r_frame_rate']!='30/1'
            or streams['audio']['codec_name']!='aac' or streams['subtitle']['codec_name']!='mov_text'):
        raise RuntimeError('B07 MP4 stream format invalid')
    canonical=' '.join(' '.join(s['narration'].split()) for s in scenes)
    checked=check_embedded_subtitles(video,OUT/'B07.ru.srt',canonical)
    decoded=subprocess.check_output(['ffmpeg','-v','error','-xerror','-i',str(video),'-map','0:a:0',
                                     '-ac','1','-ar',str(RATE),'-c:a','pcm_s16le','-f','s16le','-'])
    actual=array.array('h');actual.frombytes(decoded)
    expected=array.array('h');expected.frombytes(timeline)
    if abs(len(actual)-len(expected))>1024:
        raise RuntimeError('B07 AAC sample count differs from source timeline')
    def correlation(lag):
        dot=aa=bb=0
        for i in range(lead//2+10000,min(len(actual),len(expected)-max(0,lag)),100):
            j=i+lag
            if j<0:continue
            x,y=actual[j],expected[i];dot+=x*y;aa+=x*x;bb+=y*y
        return dot/math.sqrt(aa*bb)
    corr={lag:correlation(lag) for lag in (-32,0,32)}
    if corr[0]<.995 or corr[0]<=max(corr[-32],corr[32]):
        raise RuntimeError('B07 AAC does not align to source WAV')
    small=subprocess.check_output(['ffmpeg','-v','error','-xerror','-i',str(video),'-map','0:v:0',
                                   '-vf','scale=48:27:flags=area,format=gray','-r',str(FPS),'-f','rawvideo','-'])
    pixels=48*27
    if len(small)!=frames*pixels:
        raise RuntimeError('B07 video frame count invalid')
    lum=[];blank=[]
    for i in range(frames):
        frame=small[i*pixels:(i+1)*pixels];lum.append(sum(frame)/pixels)
        if max(frame)-min(frame)<12 or all(v<10 for v in frame) or all(v>245 for v in frame):blank.append(i)
    flash=[i for i in range(1,frames-1) if abs(lum[i]-lum[i-1])>35 and abs(lum[i]-lum[i+1])>35 and abs(lum[i-1]-lum[i+1])<10]
    if blank or flash:
        raise RuntimeError(f'B07 blank/flash frames: {blank[:5]} / {flash[:5]}')
    visual_report=json.loads((OUT/'visual-capture.json').read_text())
    cue_errors=[];pointer=[];cursor_violations=[]
    elapsed=0
    for scene in scenes:
        row=next(r for r in visual_report['scenes'] if r['scene_id']==scene['id'])
        source=OUT/'scenes'/f"{scene['id']}.mp4"
        if sha(source)!=row['sha256']:
            raise RuntimeError('B07 scene source changed')
        evidence=json.loads(source.with_suffix('.json').read_text())
        if evidence['expected_state']!='PASS' or evidence['browser_errors'] or evidence['production_mutation_requests']:
            raise RuntimeError('B07 browser scene invalid')
        cursor_violations.extend(evidence['choreography']['overlay']['violations'])
        cue_errors.extend(abs(x) for x in row['cue_errors_seconds'])
        pointer.extend({'scene_id':scene['id'],**p} for p in pointer_pixels_in_mp4(video,evidence,elapsed,scene['id'],OUT/'qa-clicks'/scene['id']))
        elapsed+=report['scene_frame_counts'][scene['id']]/FPS
    if cursor_violations or (cue_errors and max(cue_errors)>.3):
        raise RuntimeError('B07 cursor lifecycle or cue synchronization failed')
    result={'status':'PASS','block_id':'B07','video_sha256':sha(video),
            'final_wav_sha256':metadata['wav_sha256'],'final_pcm_preserved_in_timeline':True,
            'aac_zero_lag_correlation':corr[0],'subtitle_cues':checked['embedded_subtitle_cues'],
            'last_embedded_subtitle_end_seconds':checked['last_embedded_subtitle_end_seconds'],
            'subtitle_matches_canonical_text':True,'video_frames':frames,
            'blank_frames':0,'isolated_flash_frames':0,'cursor_violations':0,
            'max_visual_cue_error_seconds':max(cue_errors) if cue_errors else None,
            'rendered_pointer_clicks':pointer,'new_tts_requests':0,'production_mutation_requests':0}
    write_json(OUT/'verification.json',result)
    return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('visual','assemble','verify'))
    args=parser.parse_args()
    print(json.dumps(asyncio.run(visual()) if args.mode=='visual' else assemble() if args.mode=='assemble' else verify(),ensure_ascii=False,indent=2))
