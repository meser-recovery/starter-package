#!/usr/bin/env python3
"""Capture and verify B10 against the real isolated Speaker editor."""
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

from audio_approval import validate_approval, validate_block_approval
from b01_block import check_embedded_subtitles, timestamp
from b09_block import pointer_pixels_in_mp4, visual_transition_anomalies
from b09_block import raw_seed_region
from browser_capture import capture
from build import demo_server
from modules import cached, map_timing, request_text_and_indices, sha, write_json
from scenes import import_local, login, render_speaker_final
from validate import ROOT, validate

OUT = ROOT / 'generated/b10-block-review'
AUDIO = ROOT / 'generated/narration-blocks-v2/B10'
SCENE_IDS = ('B10-035', 'B10-036', 'B10-037')
VARIANT = 'B10-review-01'
LEAD = .6
RATE = 44100
FPS = 30
FRAME_BYTES = 1920 * 1080 * 3 // 2
VIEW_Y = 800
START_Y = 500


def inputs():
    validate()
    validate_block_approval('B09')
    spec = json.loads((ROOT / 'tutorial.yaml').read_text())
    validate_approval(spec, 'B09')
    module = next(m for m in spec['narration_modules'] if m['id'] == 'B10')
    hit = cached(spec, module)
    if not hit:
        raise RuntimeError('B10 one-request narration is missing or stale')
    metadata = json.loads((AUDIO / f'{VARIANT}-metadata.json').read_text())
    review = json.loads((AUDIO / 'B10-review-map.json').read_text())
    if (review['status'], review['block_id'], review['variant_id']) != ('SEMANTIC_REVIEWED', 'B10', 'review-01'):
        raise RuntimeError('B10 semantic review map invalid')
    for path, digest in ((AUDIO / 'narration.mp3', metadata['source_mp3_sha256']),
                         (AUDIO / f'{VARIANT}.mp3', metadata['mp3_sha256']),
                         (AUDIO / f'{VARIANT}.wav', metadata['wav_sha256']),
                         (AUDIO / f'{VARIANT}-timing.json', metadata['timing_sha256'])):
        if sha(path) != digest:
            raise RuntimeError('B10 reviewed audio changed: ' + str(path))
    if (metadata['source_mp3_sha256'] != hit['metadata']['audio_sha256']
            or metadata['new_tts_requests'] or metadata['speed_pitch_gain_processing']
            or not metadata['source_pcm_recovered_exactly'] or metadata['events']):
        raise RuntimeError('B10 review must preserve its one unmodified TTS take')
    with wave.open(str(AUDIO / f'{VARIANT}.wav')) as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, RATE):
            raise RuntimeError('B10 WAV format invalid')
        pcm = wav.readframes(wav.getnframes())
        duration = wav.getnframes() / RATE
    if hashlib.sha256(pcm).hexdigest() != metadata['final_pcm_sha256']:
        raise RuntimeError('B10 source PCM changed')
    timing = json.loads((AUDIO / f'{VARIANT}-timing.json').read_text())
    if timing != map_timing(spec, module, timing['alignment'], timing['duration_seconds']):
        raise RuntimeError('B10 alignment differs from canonical narration')
    scenes = [s for s in spec['scenes'] if s['id'] in SCENE_IDS]
    if tuple(s['id'] for s in scenes) != SCENE_IDS:
        raise RuntimeError('B10 scene map changed')
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
        raise RuntimeError('B10 scene alignment differs from canonical text')
    return {**row, 'alignment': alignment, 'duration_seconds': end-start,
            'range_start_seconds': start, 'range_end_seconds': end,
            'timing_identity': hashlib.sha256((metadata['timing_sha256'] + scene['id']).encode()).hexdigest()}


def capture_spec(scene):
    return {**scene, 'visual': {'type': 'browser', 'goal': scene['goal'],
                               'capture_pipeline_revision': 'b10-stable-final-result-v1'},
            'initial_state': 'speaker-source-tracks', 'expected_state': 'B10 result action completed',
            'assertions': [], 'fixture_set': 'existing-synthetic-zoom-v1',
            'padding': {'head': 0., 'tail': 0.}}


async def assert_view(page, label, *, result, expected_y=VIEW_Y):
    state = await page.evaluate('''() => {
      const box=id=>{const e=document.querySelector(id);const r=e?.getBoundingClientRect();
        return r&&{x:r.x,y:r.y,width:r.width,height:r.height}};
      return {scroll_x:window.scrollX,scroll_y:window.scrollY,viewport:[innerWidth,innerHeight],
        render:box('#speaker-editor-render'),result:box('#speaker-editor-result'),
        audio:box('#speaker-editor-result-audio'),download:box('#speaker-editor-download'),
        archive:box('#speaker-editor-archive-save'),result_visible:!document.querySelector('#speaker-editor-result').hidden};
    }''')
    if (state['scroll_x'] != 0 or abs(state['scroll_y'] - expected_y) > 1
            or state['viewport'] != [1728, 972]):
        raise RuntimeError(f'B10 {label} viewport moved: {state}')
    if not state['render'] or not (0 < state['render']['y'] < 972):
        raise RuntimeError(f'B10 {label} render button left frame: {state}')
    if result:
        if not state['result_visible']:
            raise RuntimeError(f'B10 {label} result not visible')
        for name in ('result', 'audio', 'download', 'archive'):
            box = state[name]
            if not box or not (0 <= box['x'] < box['x'] + box['width'] <= 1728
                               and 0 <= box['y'] < box['y'] + box['height'] <= 972):
                raise RuntimeError(f'B10 {label} {name} outside frame: {state}')
    if hasattr(page, 'tutorial'):
        page.tutorial.events.append({'type': 'stable-editor-view', 'seconds': page.tutorial.now(),
                                     'label': label, 'position': state})
    return state


async def scroll_to_result(page):
    await page.evaluate("window.__s11Capture.hide('result-scroll')")
    await page.evaluate('''async target => {
      const from=window.scrollY,start=performance.now(),duration=650;
      await new Promise(resolve=>{
        const step=now=>{
          const p=Math.min(1,(now-start)/duration),e=p*p*(3-2*p);
          window.scrollTo(0,from+(target-from)*e);
          if(p<1)requestAnimationFrame(step);else resolve();
        };requestAnimationFrame(step);
      });
      window.scrollTo(0,target);
      await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    }''',VIEW_Y)
    if hasattr(page, 'tutorial'):
        page.tutorial.events.append({'type':'intentional-result-scroll','seconds':page.tutorial.now(),
                                     'from_y':START_Y,'to_y':VIEW_Y})


async def assert_result(page, label):
    values = {name: await page.locator('#speaker-editor-' + name).inner_text()
              for name in ('original-duration', 'result-duration', 'removed-duration', 'result-format')}
    if (values['original-duration'] != '18 с' or values['removed-duration'] != '1 с'
            or not values['result-duration'].startswith('17,')
            or 'MP3' not in values['result-format'] or 'КБ' not in values['result-format']):
        raise RuntimeError(f'B10 {label} result statistics wrong: {values}')
    download = page.locator('#speaker-editor-download')
    if (not (await download.get_attribute('href') or '').startswith('blob:')
            or not (await download.get_attribute('download') or '').lower().endswith('.mp3')
            or not await page.locator('#speaker-editor-archive-save').is_disabled()
            or 'Сохраните проект' not in await page.locator('#speaker-editor-archive-unavailable').inner_text()):
        raise RuntimeError(f'B10 {label} result/download/archive prerequisite missing')
    if hasattr(page, 'tutorial'):
        page.tutorial.events.append({'type': 'result-verified', 'seconds': page.tutorial.now(),
                                     'label': label, 'statistics': values,
                                     'archive_save_disabled': True, 'download_is_mp3': True})
    return values


async def prepare(page, scene, base):
    await page.set_viewport_size({'width': 1728, 'height': 972})
    await login(page, base)
    await import_local(page, base, 'speaker')
    await page.wait_for_function("document.querySelectorAll('#speaker-editor-tracks .speaker-track canvas').length===4 && !document.querySelector('#speaker-editor-tracks .speaker-source-pending')", timeout=60000)
    await page.locator('#speaker-editor-tracks .speaker-track').last.get_by_role(
        'button', name='Исключить из микса').click()
    await raw_seed_region(page, 'cut', 'Спикер.wav', 3, 4)
    if scene['id'] != 'B10-035':
        await render_speaker_final(page)
    if scene['id'] == 'B10-037':
        playback=json.loads((OUT/'scene036-playback-state.json').read_text())
        await page.locator('#speaker-editor-result-audio').evaluate(
            '(audio,time)=>{audio.currentTime=time}', playback['paused_time_seconds'])
        await page.wait_for_function('''time =>
          Math.abs(document.querySelector('#speaker-editor-result-audio').currentTime-time)<.02''',
          arg=playback['paused_time_seconds'])
    # Only the scrollable canvas gains review headroom; the real controls,
    # waveform and result keep their native size and position relative to one another.
    initial_y = START_Y if scene['id']=='B10-035' else VIEW_Y
    await page.evaluate(f"document.body.style.paddingBottom='600px';window.scrollTo(0,{initial_y})")
    await page.evaluate('async()=>{await document.fonts.ready;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))}')
    await page.wait_for_timeout(300)
    await assert_view(page, 'prepared', result=scene['id'] != 'B10-035', expected_y=initial_y)
    if scene['id'] != 'B10-035':
        await assert_result(page, 'prepared')
    await page.screenshot()


async def perform(page, scene, base, cue):
    director = page.tutorial
    if scene['id'] == 'B10-035':
        await cue('Создать финальную версию')
        await page.locator('#speaker-editor-render').click()
        await page.locator('#speaker-editor-result').wait_for(state='visible', timeout=120000)
        await page.wait_for_function("document.querySelector('#speaker-editor-result-waveform canvas').width>0")
        await scroll_to_result(page)
        await assert_view(page, 'render finished', result=True)
        await assert_result(page, 'render finished')
        await cue('После завершения обработки')
        await director.wait_pending()
    elif scene['id'] == 'B10-036':
        audio = page.raw.locator('#speaker-editor-result-audio')
        box = await audio.bounding_box()
        if not box:
            raise RuntimeError('B10 real audio controls unavailable')
        x, y = box['x'] + 24, box['y'] + box['height'] / 2
        await cue('прослушать непосредственно')
        await page.mouse.move(x, y)
        await page.mouse.down(); await page.mouse.up()
        await page.wait_for_function("!document.querySelector('#speaker-editor-result-audio').paused")
        await page.wait_for_function("document.querySelector('#speaker-editor-result-audio').currentTime>1", timeout=10000)
        director.events.append({'type': 'result-playback-confirmed', 'seconds': director.now(),
                                'play_button_point': [x, y],
                                'audio_time': await audio.evaluate('e=>e.currentTime')})
        await cue('проверить результат')
        await page.mouse.move(x, y)
        await page.mouse.down(); await page.mouse.up()
        if not await audio.evaluate('e=>e.paused && e.currentTime>1'):
            raise RuntimeError('B10 result playback did not pause after listening')
        write_json(OUT/'scene036-playback-state.json',
                   {'paused_time_seconds':await audio.evaluate('e=>e.currentTime')})
        await page.evaluate("window.__s11Capture.hide('listening-complete')")
        await cue('Здесь же отображается')
        await director.wait_pending()
        await assert_result(page, 'statistics displayed')
        await cue('Готовый файл можно')
        await page.locator('#speaker-editor-download').click()
        await page.evaluate("window.__s11Capture.hide('download-complete')")
        await assert_view(page, 'download ready', result=True)
    elif scene['id'] == 'B10-037':
        retained=json.loads((OUT/'scene036-playback-state.json').read_text())['paused_time_seconds']
        current=await page.locator('#speaker-editor-result-audio').evaluate('e=>e.currentTime')
        if abs(current-retained)>.02:
            raise RuntimeError('B10 playback position jumped at scene 036→037')
        await cue('сохранить в Аудиоархиве')
        await director.wait_pending()
        await cue('сначала должен быть сохранён')
        await director.wait_pending()
        await assert_result(page, 'archive prerequisite displayed')
        await page.evaluate("window.__s11Capture.hide('archive-prerequisite-complete')")
        await cue('будет показано в следующей части')
        await director.wait_pending()
        await assert_view(page, 'closing', result=True)
    else:
        raise RuntimeError('unexpected B10 scene')
    await page.evaluate("window.__s11Capture.hide('scene-complete')")


async def visual():
    if (ROOT / 'approvals/B10-block.json').exists():
        raise RuntimeError('B10 complete block is approved and immutable')
    spec, module, scenes, metadata, timing, _, duration = inputs()
    (OUT / 'scenes').mkdir(parents=True, exist_ok=True)
    recipe = '\n'.join(inspect.getsource(fn) for fn in
                       (capture_spec, assert_view, scroll_to_result, assert_result, prepare, perform))
    identity = hashlib.sha256(recipe.encode()).hexdigest()
    rows = []
    with demo_server(None) as base:
        for scene in scenes:
            local = scene_timing(spec, module, scene, timing, metadata, duration)
            local.update(visual_lead_seconds=LEAD if scene['id'] == SCENE_IDS[0] else 0.,
                         visual_source_sha256=identity, strict_choreography=False)
            path = OUT / 'scenes' / f"{scene['id']}.mp4"
            evidence = await capture(capture_spec(scene), spec['narration'], base, timing=local,
                                     destination=path, prepare_scene=prepare, perform_scene=perform)
            if evidence['browser_errors'] or evidence['production_mutation_requests']:
                raise RuntimeError('B10 isolated capture failed')
            if max((e['seconds'] for e in evidence['choreography']['events']), default=0) > local['duration_seconds']+local['visual_lead_seconds']+.25:
                raise RuntimeError(f"B10 {scene['id']} action exceeds narrated scene")
            row = {'scene_id': scene['id'], 'visual': str(path), 'sha256': sha(path),
                   'duration_seconds': evidence['duration_seconds'],
                   'cue_errors_seconds': [c['actual_seconds']-c['target_seconds'] for c in evidence['alignment_action_cues']],
                   'production_mutation_requests': evidence['production_mutation_requests']}
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    result = {'status': 'PASS', 'block_id': 'B10', 'source_mp3_sha256': metadata['source_mp3_sha256'],
              'final_wav_sha256': metadata['wav_sha256'], 'tts_requests': 0, 'scenes': rows}
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
                    raise RuntimeError('B10 subtitle timing/text invalid')
                cues.append((start, end, phrase)); begin = i+1
    if any(cues[i][0] < cues[i-1][1]-.01 for i in range(1,len(cues))):
        raise RuntimeError('B10 subtitle cues overlap')
    for suffix in ('srt', 'vtt'):
        vtt = suffix == 'vtt'
        content = ('WEBVTT\n\n' if vtt else '') + '\n\n'.join(
            ('' if vtt else f'{i}\n') + f'{timestamp(a,vtt=vtt)} --> {timestamp(b,vtt=vtt)}\n{phrase}'
            for i,(a,b,phrase) in enumerate(cues,1)) + '\n'
        (OUT / f'B10.ru.{suffix}').write_text(content)
    return cues


def assemble():
    if (ROOT / 'approvals/B10-block.json').exists():
        raise RuntimeError('B10 complete block is approved and immutable')
    spec,module,scenes,metadata,timing,pcm,duration=inputs()
    capture_report=json.loads((OUT/'visual-capture.json').read_text())
    if (capture_report['source_mp3_sha256'] != metadata['source_mp3_sha256']
            or [r['scene_id'] for r in capture_report['scenes']] != list(SCENE_IDS)):
        raise RuntimeError('B10 capture differs from approved source')
    timings=[scene_timing(spec,module,s,timing,metadata,duration) for s in scenes]
    cues=subtitles(scenes,timings)
    timeline=OUT/'B10-video-timeline.wav'
    with wave.open(str(timeline),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(RATE)
        wav.writeframes(bytes(round(LEAD*RATE)*2)+pcm)
    total=math.ceil(max(LEAD+duration,cues[-1][1]+.01)*FPS)/FPS
    bounds=[0]+[LEAD+t['range_start_seconds'] for t in timings[1:]]+[total]
    counts=[round(bounds[i+1]*FPS)-round(bounds[i]*FPS) for i in range(len(scenes))]
    if min(counts)<=0:
        raise RuntimeError('B10 scene frame count invalid')
    candidate=OUT/'B10.tmp.mp4'
    command=['ffmpeg','-y','-v','error','-f','rawvideo','-pixel_format','yuv420p',
             '-video_size','1920x1080','-framerate',str(FPS),'-i','pipe:0',
             '-i',str(timeline),'-i',str(OUT/'B10.ru.srt'),
             '-map','0:v:0','-map','1:a:0','-map','2:s:0',
             '-c:v','libx264','-preset','veryfast','-crf','21','-pix_fmt','yuv420p',
             '-c:a','aac','-b:a','192k','-c:s','mov_text','-metadata:s:s:0','language=rus',
             '-frames:v',str(sum(counts)),'-movflags','+faststart',str(candidate)]
    with (OUT/'encode.log').open('wb') as log:
        encoder=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=log)
        try:
            for scene,count in zip(scenes,counts):
                path=OUT/'scenes'/f"{scene['id']}.mp4"
                if not path.is_file():raise RuntimeError('B10 scene missing: '+scene['id'])
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
                    raise RuntimeError('B10 captured frame count mismatch: '+scene['id'])
            encoder.stdin.close()
            if encoder.wait():raise RuntimeError('B10 MP4 encoding failed; see encode.log')
        finally:
            if encoder.poll() is None:encoder.kill();encoder.wait()
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(candidate),'-f','null','-'],
                   check=True,stdout=subprocess.DEVNULL)
    canonical=' '.join(' '.join(s['narration'].split()) for s in scenes)
    checked=check_embedded_subtitles(candidate,OUT/'B10.ru.srt',canonical)
    final=OUT/'B10.mp4';candidate.replace(final)
    report={'status':'READY FOR B10 BLOCK REVIEW','block_id':'B10','video':str(final),
            'video_sha256':sha(final),'duration_seconds':total,
            'source_mp3_sha256':metadata['source_mp3_sha256'],
            'final_wav_sha256':metadata['wav_sha256'],'final_pcm_sha256':metadata['final_pcm_sha256'],
            'final_alignment_sha256':metadata['timing_sha256'],'video_audio_timeline':str(timeline),
            'video_audio_lead_seconds':LEAD,'internal_audio_silence_added_seconds':0,
            'scene_frame_counts':dict(zip(SCENE_IDS,counts)),
            'embedded_subtitle_cues':checked['embedded_subtitle_cues'],
            'last_embedded_subtitle_end_seconds':checked['last_embedded_subtitle_end_seconds'],
            'tts_requests_for_source':1,'production_mutation_requests':0}
    write_json(OUT/'report.json',report)
    return report


def download_click_pixels_in_mp4(video, evidence, scene_start):
    """Check the real download press; this dark button yields a muted gold ripple."""
    events=evidence['choreography']['events']
    clicks=[e for e in events if e['type']=='click']
    arrivals=[e for e in events if e['type']=='cursor-arrival']
    downs=[e for e in evidence['choreography']['overlay']['events'] if e['type']=='pointerdown']
    if len(clicks)!=1 or len(arrivals)!=1 or not downs:
        raise RuntimeError('B10 download lacks one real click and pointerdown')
    click,arrival,down=clicks[0],arrivals[0],downs[-1]
    if '#speaker-editor-download' not in click['target'] or arrival['target']!=click['target']:
        raise RuntimeError('B10 download target changed')
    box=arrival['box']
    if not (box['x']<=down['x']<=box['x']+box['width']
            and box['y']<=down['y']<=box['y']+box['height']):
        raise RuntimeError('B10 download pointer misses real control')
    width,height=evidence['choreography']['overlay']['viewport']
    px,py=down['x']*960/width,down['y']*540/height
    press=scene_start+click['seconds']
    start=press-.2
    rgb=subprocess.check_output(['ffmpeg','-v','error','-ss',f'{start:.6f}','-i',str(video),
                                 '-t','0.55','-vf','fps=30,scale=960:540,format=rgb24',
                                 '-f','rawvideo','-'])
    frame_bytes=960*540*3
    best=(0,None)
    for n in range(len(rgb)//frame_bytes):
        frame=rgb[n*frame_bytes:(n+1)*frame_bytes]
        count=0
        for y in range(max(0,round(py)-15),min(540,round(py)+16)):
            for x in range(max(0,round(px)-15),min(960,round(px)+16)):
                k=(y*960+x)*3;r,g,b=frame[k:k+3]
                if r>=150 and g>=130 and b<=150 and r>=g-20 and g>b+20:
                    count+=1
        if count>best[0]:best=(count,n)
    if best[0]<15:
        raise RuntimeError(f'B10 download press has no rendered ripple: {best}')
    return {'scene_id':'B10-036','target':click['target'],'status':'PASS',
            'pointer_tip_inside_button':True,'rendered_ripple_pixels':best[0],
            'press_frame_seconds':start+best[1]/FPS}


def verify():
    spec,module,scenes,metadata,timing,pcm,_=inputs()
    report=json.loads((OUT/'report.json').read_text());video=OUT/'B10.mp4'
    if sha(video)!=report['video_sha256'] or report['final_wav_sha256']!=metadata['wav_sha256']:
        raise RuntimeError('B10 video or audio changed')
    with wave.open(str(OUT/'B10-video-timeline.wav')) as wav:
        timeline=wav.readframes(wav.getnframes())
    lead=round(LEAD*RATE)*2
    if timeline[:lead]!=bytes(lead) or timeline[lead:]!=pcm:
        raise RuntimeError('B10 video timeline changed source PCM')
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(video)]))
    streams={s['codec_type']:s for s in probe['streams']}
    frames=sum(report['scene_frame_counts'].values())
    if (int(streams['video']['nb_frames'])!=frames or streams['video']['r_frame_rate']!='30/1'
            or streams['audio']['codec_name']!='aac' or streams['subtitle']['codec_name']!='mov_text'):
        raise RuntimeError('B10 MP4 stream format invalid')
    canonical=' '.join(' '.join(s['narration'].split()) for s in scenes)
    checked=check_embedded_subtitles(video,OUT/'B10.ru.srt',canonical)
    decoded=subprocess.check_output(['ffmpeg','-v','error','-xerror','-i',str(video),'-map','0:a:0',
                                     '-ac','1','-ar',str(RATE),'-c:a','pcm_s16le','-f','s16le','-'])
    actual=array.array('h');actual.frombytes(decoded)
    expected=array.array('h');expected.frombytes(timeline)
    if abs(len(actual)-len(expected))>1024:
        raise RuntimeError('B10 AAC sample count differs from source timeline')
    def correlation(lag):
        dot=aa=bb=0
        for i in range(lead//2+10000,min(len(actual),len(expected)-max(0,lag)),50):
            j=i+lag
            if j<0:continue
            x,y=actual[j],expected[i];dot+=x*y;aa+=x*x;bb+=y*y
        return dot/math.sqrt(aa*bb)
    corr={lag:correlation(lag) for lag in (-32,0,32)}
    if corr[0]<.995 or corr[0]<=max(corr[-32],corr[32]):
        raise RuntimeError('B10 AAC not aligned with source WAV')
    small=subprocess.check_output(['ffmpeg','-v','error','-xerror','-i',str(video),'-map','0:v:0',
                                   '-vf','scale=48:27:flags=area,format=gray','-r',str(FPS),'-f','rawvideo','-'])
    pixels=48*27
    if len(small)!=frames*pixels:
        raise RuntimeError('B10 video frame count invalid')
    lum=[];blank=[]
    for i in range(frames):
        frame=small[i*pixels:(i+1)*pixels];lum.append(sum(frame)/pixels)
        if max(frame)-min(frame)<12 or all(v<10 for v in frame) or all(v>245 for v in frame):blank.append(i)
    flash=[i for i in range(1,frames-1) if abs(lum[i]-lum[i-1])>35 and abs(lum[i]-lum[i+1])>35 and abs(lum[i-1]-lum[i+1])<10]
    anomalies=visual_transition_anomalies(small)
    first_evidence=json.loads((OUT/'scenes/B10-035.json').read_text())
    intentional=[e for e in first_evidence['choreography']['events']
                 if e['type']=='intentional-result-scroll']
    if len(intentional)!=1 or (intentional[0]['from_y'],intentional[0]['to_y'])!=(START_Y,VIEW_Y):
        raise RuntimeError('B10 intended result scroll was not recorded')
    scroll_end=intentional[0]['seconds']
    unexpected=[a for a in anomalies if not (a['type']=='clustered_screen_jumps'
                and scroll_end-.9 <= a['start_seconds']
                and a['end_seconds'] <= scroll_end+.2)]
    if blank or flash or unexpected:
        raise RuntimeError(f'B10 blank/flash/return frames: {blank[:4]} / {flash[:4]} / {unexpected[:4]}')
    visual_report=json.loads((OUT/'visual-capture.json').read_text())
    pointers=[];cues=[];view=[];results=[];playback=[];violations=[];elapsed=0
    for scene in scenes:
        row=next(r for r in visual_report['scenes'] if r['scene_id']==scene['id'])
        source=OUT/'scenes'/f"{scene['id']}.mp4"
        if sha(source)!=row['sha256']:raise RuntimeError('B10 scene source changed')
        evidence=json.loads(source.with_suffix('.json').read_text())
        if evidence['expected_state']!='PASS' or evidence['browser_errors'] or evidence['production_mutation_requests']:
            raise RuntimeError('B10 browser capture invalid')
        events=evidence['choreography']['events']
        view.extend({'scene_id':scene['id'],'seconds':elapsed+e['seconds'],**e}
                    for e in events if e['type']=='stable-editor-view')
        results.extend({'scene_id':scene['id'],'seconds':elapsed+e['seconds'],**e}
                       for e in events if e['type']=='result-verified')
        playback.extend({'scene_id':scene['id'],'seconds':elapsed+e['seconds'],**e}
                        for e in events if e['type']=='result-playback-confirmed')
        violations.extend(evidence['choreography']['overlay']['violations'])
        cues.extend(abs(x) for x in row['cue_errors_seconds'])
        if scene['id']=='B10-036':
            pointers.append(download_click_pixels_in_mp4(video,evidence,elapsed))
        else:
            pointers.extend({'scene_id':scene['id'],**p} for p in
                            pointer_pixels_in_mp4(video,evidence,elapsed,scene['id'],OUT/'qa-clicks'/scene['id']))
        elapsed+=report['scene_frame_counts'][scene['id']]/FPS
    if (len(pointers)!=2 or not playback or len(results)<3 or violations
            or not view or any(abs(e['position']['scroll_y']-VIEW_Y)>1 for e in view)
            or (cues and max(cues)>.35)):
        raise RuntimeError('B10 action, viewport or cue validation failed')
    result={'status':'PASS','block_id':'B10','video_sha256':sha(video),
            'final_wav_sha256':metadata['wav_sha256'],'final_pcm_preserved_in_timeline':True,
            'aac_zero_lag_correlation':corr[0],'subtitle_cues':checked['embedded_subtitle_cues'],
            'last_embedded_subtitle_end_seconds':checked['last_embedded_subtitle_end_seconds'],
            'subtitle_matches_canonical_text':True,'video_frames':frames,
            'blank_frames':0,'isolated_flash_frames':0,'visual_transition_anomalies':unexpected,
            'intentional_result_scroll_seconds':{'start':scroll_end-.9,'end':scroll_end+.2},
            'rendered_pointer_clicks':pointers,'playback':playback,
            'result_statistics':results[-1]['statistics'],'archive_save_disabled':True,
            'stable_view_checkpoints':view,'max_visual_cue_error_seconds':max(cues) if cues else None,
            'production_mutation_requests':0}
    write_json(OUT/'verification.json',result)
    return result
