#!/usr/bin/env python3
"""Render B08 from one reviewed take and real Speaker workspace actions."""
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

OUT = ROOT / 'generated/b08-block-review'
AUDIO = ROOT / 'generated/narration-blocks-v2/B08'
SCENE_IDS = ('B08-023', 'B08-024', 'B08-025', 'B08-026', 'B08-027')
VARIANT = 'B08-review-01'
LEAD = .6
RATE = 44100
FPS = 30
FRAME_BYTES = 1920 * 1080 * 3 // 2


def inputs():
    validate()
    validate_block_approval('B07')
    spec = json.loads((ROOT / 'tutorial.yaml').read_text())
    module = next(m for m in spec['narration_modules'] if m['id'] == 'B08')
    hit = cached(spec, module)
    if not hit:
        raise RuntimeError('B08 one-request narration is missing or stale')
    metadata = json.loads((AUDIO / f'{VARIANT}-metadata.json').read_text())
    review = json.loads((AUDIO / 'B08-review-map.json').read_text())
    if (review['status'], review['block_id'], review['variant_id']) != ('SEMANTIC_REVIEWED', 'B08', 'review-01'):
        raise RuntimeError('B08 semantic review map invalid')
    for path, digest in ((AUDIO / 'narration.mp3', metadata['source_mp3_sha256']),
                         (AUDIO / f'{VARIANT}.mp3', metadata['mp3_sha256']),
                         (AUDIO / f'{VARIANT}.wav', metadata['wav_sha256']),
                         (AUDIO / f'{VARIANT}-timing.json', metadata['timing_sha256'])):
        if sha(path) != digest:
            raise RuntimeError('B08 reviewed audio source changed: ' + str(path))
    if (metadata['source_mp3_sha256'] != hit['metadata']['audio_sha256']
            or metadata['new_tts_requests'] or metadata['speed_pitch_gain_processing']
            or not metadata['source_pcm_recovered_exactly'] or metadata['events']):
        raise RuntimeError('B08 review must preserve the one unmodified source take')
    with wave.open(str(AUDIO / f'{VARIANT}.wav')) as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, RATE):
            raise RuntimeError('B08 WAV format invalid')
        pcm = wav.readframes(wav.getnframes())
        duration = wav.getnframes() / RATE
    if hashlib.sha256(pcm).hexdigest() != metadata['final_pcm_sha256']:
        raise RuntimeError('B08 PCM source changed')
    timing = json.loads((AUDIO / f'{VARIANT}-timing.json').read_text())
    if timing != map_timing(spec, module, timing['alignment'], timing['duration_seconds']):
        raise RuntimeError('B08 alignment no longer maps to canonical text')
    scenes = [s for s in spec['scenes'] if s['id'] in SCENE_IDS]
    if tuple(s['id'] for s in scenes) != SCENE_IDS:
        raise RuntimeError('B08 storyboard order changed')
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
        raise RuntimeError('B08 scene alignment differs from canonical text')
    return {**row, 'alignment': alignment, 'duration_seconds': end-start,
            'range_start_seconds': start, 'range_end_seconds': end,
            'timing_identity': hashlib.sha256((metadata['timing_sha256']+scene['id']).encode()).hexdigest()}


def capture_spec(scene):
    return {**scene, 'visual': {'type': 'browser', 'goal': scene['goal'],
                               'capture_pipeline_revision': 'b08-stable-editor-and-semantic-screen-holds-v2'},
            'initial_state': 'speaker-source-tracks', 'expected_state': 'B08 explained action completed',
            'assertions': [], 'fixture_set': 'existing-synthetic-zoom-v1',
            'padding': {'head': 0., 'tail': 0.}}


def track(page, filename):
    return page.locator('#speaker-editor-tracks .speaker-track').filter(has_text=filename)


async def prepare(page, scene, base):
    await page.set_viewport_size({'width': 1536, 'height': 864})
    await login(page, base)
    await import_local(page, base, 'speaker')
    await page.wait_for_function("document.querySelectorAll('#speaker-editor-tracks .speaker-track canvas').length===4 && !document.querySelector('#speaker-editor-tracks .speaker-source-pending')", timeout=60000)
    await page.wait_for_timeout(500)
    scene_id=scene['id']
    if scene_id != 'B08-023':
        # Replay the accepted state of the previous scene before recording starts.
        speaker=track(page,'Спикер.wav')
        await speaker.locator('input[type="color"]').fill('#d94873')
        await speaker.get_by_role('button',name='Вниз').click()
        if await page.locator('#speaker-editor-tracks .speaker-track').nth(1).locator('h4').inner_text()!='Спикер.wav':
            raise RuntimeError('B08 seeded track order is wrong')
    if scene_id=='B08-025':
        # Scene 024 leaves the real editor at 2× after exiting fullscreen.
        await page.locator('#speaker-editor-zoom').fill('2')
    if scene_id in ('B08-026','B08-027'):
        await page.locator('#speaker-editor-scale-mode').click()
        await page.locator('#speaker-editor-zoom').fill('168')
    if scene_id=='B08-027':
        await page.locator('#speaker-editor-zoom-in').click()
        await page.locator('#speaker-editor-zoom').fill('320')
        await page.locator('#speaker-editor-follow').click()
        await page.evaluate("""() => {
          const a=document.querySelector('#speaker-editor-source-audio');a.currentTime=12;
          const first=document.querySelector('#speaker-editor-tracks .speaker-waveform-scroll');
          if(first) {const span=first.scrollWidth/18;first.scrollLeft=Math.max(0,12*span-first.clientWidth/2);first.dispatchEvent(new Event('scroll'))}
        }""")
    await page.locator('#speaker-editor-tracks .speaker-track').first.scroll_into_view_if_needed()
    if scene_id in ('B08-024','B08-025','B08-026','B08-027'):
        await page.locator('#speaker-editor-scale-mode').scroll_into_view_if_needed()
    if scene_id=='B08-027':
        await track(page,'Спикер.wav').locator('.speaker-waveform-scroll').scroll_into_view_if_needed()
    await page.evaluate('async()=>{await document.fonts.ready;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))}')
    await page.wait_for_timeout(350)


async def cue_wait(cue, phrase):
    await cue(phrase)
    await cue.__self__.wait_pending()


async def stable_fullscreen_click(page, expanded):
    """Show a real press, then resume only on the settled native fullscreen UI."""
    director=page.tutorial
    locator=page.locator('#speaker-editor-expand')
    await director.aim(locator.raw)
    await director.before_action()
    pressed_at=director.now()
    await director.page.mouse.down()
    await asyncio.sleep(.13)
    await page.evaluate("window.__s11Capture.hide('fullscreen-changing')")
    await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
    await director.pause_capture()
    await director.page.mouse.up()
    director.events.append({'type':'click','seconds':pressed_at,'target':str(locator.raw),'ripple':True})
    await page.wait_for_function('(expanded)=>Boolean(document.fullscreenElement)===expanded',arg=expanded,timeout=10000)
    await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
    await page.wait_for_timeout(200)
    await director.resume_capture()
    await director.after_action()


async def stable_fullscreen_escape(page):
    director=page.tutorial
    await director.pause_capture()
    await director.page.keyboard.press('Escape')
    await page.wait_for_function('document.fullscreenElement===null',timeout=10000)
    await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
    await page.wait_for_timeout(200)
    await director.resume_capture()
    director.events.append({'type':'fullscreen-exit-key','seconds':director.now(),'key':'Escape'})


async def drag_selection(page, start_seconds, end_seconds):
    wave=track(page,'Спикер.wav').locator('.speaker-waveform-scroll').raw
    box=await wave.bounding_box()
    data=await wave.evaluate("el=>({left:el.scrollLeft,width:el.scrollWidth,client:el.clientWidth})")
    if not box or not data['width']:
        raise RuntimeError('B08 waveform selection geometry unavailable')
    x1=box['x']+start_seconds*data['width']/18-data['left']
    x2=box['x']+end_seconds*data['width']/18-data['left']
    y=box['y']+box['height']*.35
    if not (box['x']+12<x1<x2<box['x']+box['width']-12 and 0<y<864):
        raise RuntimeError('B08 loop selection lies outside visible waveform')
    await page.mouse.move(x1,y)
    await page.mouse.down()
    await page.mouse.move(x2,y)
    await page.mouse.up()
    start=float(await page.locator('#speaker-editor-selection-start').input_value())
    end=float(await page.locator('#speaker-editor-selection-end').input_value())
    if abs(start-start_seconds)>.3 or abs(end-end_seconds)>.3:
        raise RuntimeError(f'B08 real selection mismatch: {start}, {end}')
    return {'start':start,'end':end}


async def perform(page, scene, base, cue):
    scene_id=scene['id']
    if scene_id=='B08-023':
        before=await page.locator('#speaker-editor-tracks .speaker-track').all_inner_texts()
        if len(before)!=4:raise RuntimeError('B08 needs four synchronized tracks')
        speaker=track(page,'Спикер.wav')
        await cue('каждой дорожке')
        await speaker.locator('input[type="color"]').fill('#d94873')
        if await speaker.locator('input[type="color"]').input_value()!='#d94873':
            raise RuntimeError('B08 color did not change on the real track')
        await page.evaluate("window.__s11Capture.hide('color-change-complete')")
        await cue('изменить порядок')
        await speaker.get_by_role('button',name='Вниз').click()
        await page.wait_for_function("document.querySelector('#speaker-editor-tracks .speaker-track:nth-child(2) h4')?.textContent==='Спикер.wav'")
        await page.evaluate("window.__s11Capture.hide('track-order-changed')")
        after=await page.locator('#speaker-editor-tracks .speaker-track').all_inner_texts()
        if before[0]==after[0] or 'Спикер.wav' not in after[1]:
            raise RuntimeError('B08 track reorder not visible')
    elif scene_id=='B08-024':
        await cue('рабочую область')
        await stable_fullscreen_click(page,True)
        await asyncio.sleep(max(0,6.0-page.tutorial.now()))
        await stable_fullscreen_escape(page)
        await cue('увеличить его')
        await page.locator('#speaker-editor-zoom').fill('4')
        wide=await page.locator('#speaker-editor-tracks .speaker-waveform').first.evaluate('el=>el.getBoundingClientRect().width')
        await cue('уменьшить')
        await page.locator('#speaker-editor-zoom-out').click()
        fitted=await page.locator('#speaker-editor-tracks .speaker-waveform').first.evaluate('el=>el.getBoundingClientRect().width')
        if wide<=fitted*1.5:raise RuntimeError('B08 horizontal zoom did not visibly change the timeline')
        await page.evaluate("window.__s11Capture.hide('zoom-control-complete')")
    elif scene_id=='B08-025':
        await cue('«Вписать»')
        await page.locator('#speaker-editor-zoom-fit').click()
        first=page.locator('#speaker-editor-tracks .speaker-waveform-scroll').first
        if await first.evaluate('el=>Math.abs(el.scrollWidth-el.clientWidth)')>4:
            raise RuntimeError('B08 Fit did not fit the source timeline')
        await cue('переключить в режим')
        await page.locator('#speaker-editor-scale-mode').click()
        if await page.locator('#speaker-editor-scale-mode').get_attribute('aria-pressed')!='true':
            raise RuntimeError('B08 height scale mode did not activate')
        await cue('больше дорожек одновременно')
        await page.locator('#speaker-editor-zoom').fill('168')
        if not await page.locator('#speaker-editor').evaluate("el=>el.classList.contains('has-compact-tracks')"):
            raise RuntimeError('B08 compact height did not activate')
        await page.evaluate("window.__s11Capture.hide('height-minimum')")
    elif scene_id=='B08-026':
        await cue('При увеличении высоты')
        await page.locator('#speaker-editor-zoom').fill('320')
        if await page.locator('#speaker-editor').evaluate("el=>el.classList.contains('has-compact-tracks')"):
            raise RuntimeError('B08 large tracks did not restore controls')
        await page.locator('#speaker-editor-zoom-in').click()
        await cue('Follow')
        await page.locator('#speaker-editor-follow').click()
        if await page.locator('#speaker-editor-follow').get_attribute('aria-pressed')!='true':
            raise RuntimeError('B08 Follow did not activate')
        await page.evaluate("document.querySelector('#speaker-editor-source-audio').currentTime=12")
        await page.locator('#speaker-editor-source-audio-play').click()
        before=await page.locator('#speaker-editor-tracks .speaker-waveform-scroll').first.evaluate('el=>el.scrollLeft')
        await page.wait_for_timeout(1300)
        after=await page.locator('#speaker-editor-tracks .speaker-waveform-scroll').first.evaluate('el=>el.scrollLeft')
        if after<=before+15:raise RuntimeError('B08 Follow did not move with playback')
        await page.evaluate("window.__s11Capture.hide('follow-playing')")
    elif scene_id=='B08-027':
        await cue('выделить нужный участок')
        selected=await drag_selection(page,12,14)
        await page.locator('#speaker-editor-source-audio-loop').click()
        if await page.locator('#speaker-editor-source-audio-loop').get_attribute('aria-pressed')!='true':
            raise RuntimeError('B08 Loop did not activate')
        if not await page.locator('#speaker-editor-global-regions .timeline-loop-strip').count():
            raise RuntimeError('B08 Loop region is not visible on actual timeline')
        await page.evaluate("window.__s11Capture.hide('loop-playing')")
        await page.wait_for_timeout(2700)
        current=await page.locator('#speaker-editor-source-audio').evaluate('el=>el.currentTime')
        if not selected['start']<=current<=selected['end']+.2:
            raise RuntimeError('B08 repeated playback left the selected region')
    else:raise RuntimeError('unexpected B08 scene')
    await page.evaluate("window.__s11Capture.hide('scene-complete')")


async def visual():
    if (ROOT / 'approvals/B08-block.json').exists():
        raise RuntimeError('B08 complete block is approved and immutable')
    spec, module, scenes, metadata, timing, _, audio_duration = inputs()
    (OUT / 'scenes').mkdir(parents=True, exist_ok=True)
    recipe = '\n'.join(inspect.getsource(fn) for fn in
                       (capture_spec, track, prepare, cue_wait, stable_fullscreen_click, stable_fullscreen_escape, drag_selection, perform))
    identity = hashlib.sha256(recipe.encode()).hexdigest()
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
                raise RuntimeError('B08 isolated capture failed')
            if max((e['seconds'] for e in evidence['choreography']['events']), default=0) > local['duration_seconds']+local['visual_lead_seconds']+.2:
                raise RuntimeError(f"B08 {scene['id']} action extends beyond its narrated scene")
            row = {'scene_id': scene['id'], 'visual': str(path), 'sha256': sha(path),
                   'duration_seconds': evidence['duration_seconds'],
                   'cue_errors_seconds': [c['actual_seconds']-c['target_seconds'] for c in evidence['alignment_action_cues']],
                   'production_mutation_requests': evidence['production_mutation_requests']}
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    result = {'status':'PASS','block_id':'B08','source_mp3_sha256':metadata['source_mp3_sha256'],
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
                    raise RuntimeError('B08 subtitle timing/text invalid')
                cues.append((start,end,phrase));begin=i+1
    if any(cues[i][0] < cues[i-1][1]-.01 for i in range(1,len(cues))):
        raise RuntimeError('B08 subtitle cues overlap')
    for suffix in ('srt','vtt'):
        vtt = suffix == 'vtt'
        content = ('WEBVTT\n\n' if vtt else '') + '\n\n'.join(
            ('' if vtt else f'{i}\n') + f'{timestamp(a,vtt=vtt)} --> {timestamp(b,vtt=vtt)}\n{text}'
            for i,(a,b,text) in enumerate(cues,1)) + '\n'
        (OUT / f'B08.ru.{suffix}').write_text(content)
    return cues


def assemble():
    if (ROOT / 'approvals/B08-block.json').exists():
        raise RuntimeError('B08 complete block is approved and immutable')
    spec,module,scenes,metadata,timing,pcm,audio_duration=inputs()
    capture_report=json.loads((OUT/'visual-capture.json').read_text())
    if (capture_report['source_mp3_sha256']!=metadata['source_mp3_sha256']
            or [r['scene_id'] for r in capture_report['scenes']]!=list(SCENE_IDS)):
        raise RuntimeError('B08 scene capture differs from source audio')
    timings=[scene_timing(spec,module,s,timing,metadata,audio_duration) for s in scenes]
    cues=subtitles(scenes,timings)
    timeline=OUT/'B08-video-timeline.wav'
    with wave.open(str(timeline),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(RATE)
        wav.writeframes(bytes(round(LEAD*RATE)*2)+pcm)
    duration=math.ceil(max(LEAD+audio_duration,cues[-1][1]+.01)*FPS)/FPS
    bounds=[0]+[LEAD+t['range_start_seconds'] for t in timings[1:]]+[duration]
    counts=[round(bounds[i+1]*FPS)-round(bounds[i]*FPS) for i in range(len(scenes))]
    if min(counts)<=0:
        raise RuntimeError('B08 scene frame count invalid')
    candidate=OUT/'B08.tmp.mp4'
    command=['ffmpeg','-y','-v','error','-f','rawvideo','-pixel_format','yuv420p',
             '-video_size','1920x1080','-framerate',str(FPS),'-i','pipe:0',
             '-i',str(timeline),'-i',str(OUT/'B08.ru.srt'),
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
                    raise RuntimeError('B08 scene missing: '+scene['id'])
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
                    raise RuntimeError('B08 captured frame count mismatch: '+scene['id'])
            encoder.stdin.close()
            if encoder.wait():
                raise RuntimeError('B08 MP4 encoding failed; see encode.log')
        finally:
            if encoder.poll() is None:
                encoder.kill();encoder.wait()
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(candidate),'-f','null','-'],
                   check=True,stdout=subprocess.DEVNULL)
    canonical=' '.join(' '.join(s['narration'].split()) for s in scenes)
    checked=check_embedded_subtitles(candidate,OUT/'B08.ru.srt',canonical)
    final=OUT/'B08.mp4';candidate.replace(final)
    report={'status':'READY FOR B08 BLOCK REVIEW','block_id':'B08','video':str(final),
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
    expected=len(clicks)
    if len(arrivals)<expected or len(pointerdowns)<expected:
        raise RuntimeError(f'{scene_id} expected {expected} real clicks, got {len(clicks)}')
    viewport_w,viewport_h=evidence['choreography']['overlay']['viewport']
    evidence_dir.mkdir(parents=True,exist_ok=True)
    checks=[]
    click_arrivals=[]
    for click in clicks:
        matching=[a for a in arrivals if a['target']==click['target'] and a['seconds']<=click['seconds']]
        if not matching:
            raise RuntimeError(f'{scene_id} real click has no matching pointer arrival')
        click_arrivals.append(max(matching,key=lambda a:a['seconds']))
    for number,(arrival,click) in enumerate(zip(click_arrivals,clicks),1):
        box=arrival['box']
        pointer=pointerdowns[-expected+number-1]
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
        checks.append(check)
    if evidence['choreography']['overlay']['cursorVisible']:
        raise RuntimeError(f'{scene_id} cursor remains visible at scene end')
    return checks


def visual_transition_anomalies(raw:bytes, *, width=48, height=27, fps=FPS):
    """Find brief A→B→A screens and clustered full-frame capture jumps."""
    pixels=width*height
    if len(raw)%pixels:
        raise RuntimeError('B08 visual transition scan received partial frame')
    frames=[memoryview(raw)[i:i+pixels] for i in range(0,len(raw),pixels)]
    sampled=range(0,pixels,2)
    def distance(a,b):
        return sum(abs(frames[a][i]-frames[b][i]) for i in sampled)/len(sampled)
    jumps=[i for i in range(1,len(frames)) if distance(i-1,i)>20]
    anomalies=[]
    for position,start in enumerate(jumps):
        for end in jumps[position+1:]:
            if end-start>30:break
            if distance(start-1,end)<5 and distance(start-1,(start+end)//2)>20:
                anomalies.append({'type':'brief_screen_return','start_frame':start,'end_frame':end,
                                  'start_seconds':start/fps,'end_seconds':end/fps})
                break
    for start,end in zip(jumps,jumps[1:]):
        if end-start<=18 and not any(a['start_frame']==start and a['end_frame']==end for a in anomalies):
            anomalies.append({'type':'clustered_screen_jumps','start_frame':start,'end_frame':end,
                              'start_seconds':start/fps,'end_seconds':end/fps})
    return sorted(anomalies,key=lambda row:(row['start_frame'],row['end_frame']))


def verify():
    spec,module,scenes,metadata,timing,pcm,_=inputs()
    report=json.loads((OUT/'report.json').read_text());video=OUT/'B08.mp4'
    if sha(video)!=report['video_sha256'] or report['final_wav_sha256']!=metadata['wav_sha256']:
        raise RuntimeError('B08 video or source audio changed')
    with wave.open(str(OUT/'B08-video-timeline.wav')) as wav:
        timeline=wav.readframes(wav.getnframes())
    lead=round(LEAD*RATE)*2
    if timeline[:lead]!=bytes(lead) or timeline[lead:]!=pcm:
        raise RuntimeError('B08 video timeline changed source PCM')
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(video)]))
    streams={s['codec_type']:s for s in probe['streams']}
    frames=sum(report['scene_frame_counts'].values())
    if (int(streams['video']['nb_frames'])!=frames or streams['video']['r_frame_rate']!='30/1'
            or streams['audio']['codec_name']!='aac' or streams['subtitle']['codec_name']!='mov_text'):
        raise RuntimeError('B08 MP4 stream format invalid')
    canonical=' '.join(' '.join(s['narration'].split()) for s in scenes)
    checked=check_embedded_subtitles(video,OUT/'B08.ru.srt',canonical)
    decoded=subprocess.check_output(['ffmpeg','-v','error','-xerror','-i',str(video),'-map','0:a:0',
                                     '-ac','1','-ar',str(RATE),'-c:a','pcm_s16le','-f','s16le','-'])
    actual=array.array('h');actual.frombytes(decoded)
    expected=array.array('h');expected.frombytes(timeline)
    if abs(len(actual)-len(expected))>1024:
        raise RuntimeError('B08 AAC sample count differs from source timeline')
    def correlation(lag):
        dot=aa=bb=0
        for i in range(lead//2+10000,min(len(actual),len(expected)-max(0,lag)),100):
            j=i+lag
            if j<0:continue
            x,y=actual[j],expected[i];dot+=x*y;aa+=x*x;bb+=y*y
        return dot/math.sqrt(aa*bb)
    corr={lag:correlation(lag) for lag in (-32,0,32)}
    if corr[0]<.995 or corr[0]<=max(corr[-32],corr[32]):
        raise RuntimeError('B08 AAC does not align to source WAV')
    small=subprocess.check_output(['ffmpeg','-v','error','-xerror','-i',str(video),'-map','0:v:0',
                                   '-vf','scale=48:27:flags=area,format=gray','-r',str(FPS),'-f','rawvideo','-'])
    pixels=48*27
    if len(small)!=frames*pixels:
        raise RuntimeError('B08 video frame count invalid')
    lum=[];blank=[]
    for i in range(frames):
        frame=small[i*pixels:(i+1)*pixels];lum.append(sum(frame)/pixels)
        if max(frame)-min(frame)<12 or all(v<10 for v in frame) or all(v>245 for v in frame):blank.append(i)
    flash=[i for i in range(1,frames-1) if abs(lum[i]-lum[i-1])>35 and abs(lum[i]-lum[i+1])>35 and abs(lum[i-1]-lum[i+1])<10]
    if blank or flash:
        raise RuntimeError(f'B08 blank/flash frames: {blank[:5]} / {flash[:5]}')
    transition_anomalies=visual_transition_anomalies(small)
    if transition_anomalies:
        raise RuntimeError(f'B08 brief screen/scroll transitions: {transition_anomalies[:5]}')
    visual_report=json.loads((OUT/'visual-capture.json').read_text())
    cue_errors=[];pointer=[];cursor_violations=[]
    elapsed=0
    for scene in scenes:
        row=next(r for r in visual_report['scenes'] if r['scene_id']==scene['id'])
        source=OUT/'scenes'/f"{scene['id']}.mp4"
        if sha(source)!=row['sha256']:
            raise RuntimeError('B08 scene source changed')
        evidence=json.loads(source.with_suffix('.json').read_text())
        if evidence['expected_state']!='PASS' or evidence['browser_errors'] or evidence['production_mutation_requests']:
            raise RuntimeError('B08 browser scene invalid')
        cursor_violations.extend(evidence['choreography']['overlay']['violations'])
        cue_errors.extend(abs(x) for x in row['cue_errors_seconds'])
        pointer.extend({'scene_id':scene['id'],**p} for p in pointer_pixels_in_mp4(video,evidence,elapsed,scene['id'],OUT/'qa-clicks'/scene['id']))
        elapsed+=report['scene_frame_counts'][scene['id']]/FPS
    if cursor_violations or (cue_errors and max(cue_errors)>.3):
        raise RuntimeError('B08 cursor lifecycle or cue synchronization failed')
    result={'status':'PASS','block_id':'B08','video_sha256':sha(video),
            'final_wav_sha256':metadata['wav_sha256'],'final_pcm_preserved_in_timeline':True,
            'aac_zero_lag_correlation':corr[0],'subtitle_cues':checked['embedded_subtitle_cues'],
            'last_embedded_subtitle_end_seconds':checked['last_embedded_subtitle_end_seconds'],
            'subtitle_matches_canonical_text':True,'video_frames':frames,
            'blank_frames':0,'isolated_flash_frames':0,'visual_transition_anomalies':[],
            'cursor_violations':0,
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
