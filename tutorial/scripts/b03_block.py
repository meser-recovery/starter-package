#!/usr/bin/env python3
"""Render B03 from its one continuous take and the real source-selection UI."""
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
from browser_capture import capture, visual_hash as browser_visual_hash
from build import demo_server
from modules import cached, map_timing, request_text_and_indices, sha, write_json
from scenes import create_archive, login
from validate import ROOT, validate

OUT = ROOT / 'generated/b03-block-review'
AUDIO = ROOT / 'generated/narration-blocks-v2/B03'
DIAGRAM = ROOT / 'animations/b03-sources.html'
SCENE_IDS = ('B03-008', 'B03-009')
LEAD_SECONDS = .6
RATE = 44100
FPS = 30
FRAME_BYTES = 1920 * 1080 * 3 // 2
VARIANT = 'B03-review-01'


def inputs():
    validate()
    validate_block_approval('B02')
    spec = json.loads((ROOT / 'tutorial.yaml').read_text())
    module = next(m for m in spec['narration_modules'] if m['id'] == 'B03')
    hit = cached(spec, module)
    if not hit:
        raise RuntimeError('B03 one-request narration is missing or stale')
    metadata = json.loads((AUDIO / f'{VARIANT}-metadata.json').read_text())
    review = json.loads((AUDIO / 'B03-review-map.json').read_text())
    if (review['status'], review['block_id'], review['variant_id']) != ('SEMANTIC_REVIEWED', 'B03', 'review-01'):
        raise RuntimeError('B03 semantic review map invalid')
    for path, digest in ((AUDIO / 'narration.mp3', metadata['source_mp3_sha256']),
                         (AUDIO / f'{VARIANT}.mp3', metadata['mp3_sha256']),
                         (AUDIO / f'{VARIANT}.wav', metadata['wav_sha256']),
                         (AUDIO / f'{VARIANT}-timing.json', metadata['timing_sha256'])):
        if sha(path) != digest:
            raise RuntimeError('B03 reviewed audio source changed: ' + str(path))
    if (metadata['source_mp3_sha256'] != hit['metadata']['audio_sha256']
            or metadata['new_tts_requests'] or metadata['speed_pitch_gain_processing']
            or not metadata['source_pcm_recovered_exactly'] or metadata['events']):
        raise RuntimeError('B03 audio no longer matches one unmodified TTS source')
    with wave.open(str(AUDIO / f'{VARIANT}.wav')) as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, RATE):
            raise RuntimeError('B03 WAV format invalid')
        pcm = wav.readframes(wav.getnframes())
        duration = wav.getnframes() / RATE
    if hashlib.sha256(pcm).hexdigest() != metadata['final_pcm_sha256']:
        raise RuntimeError('B03 PCM source changed')
    timing = json.loads((AUDIO / f'{VARIANT}-timing.json').read_text())
    if timing != map_timing(spec, module, timing['alignment'], timing['duration_seconds']):
        raise RuntimeError('B03 alignment no longer maps to canonical text')
    scenes = [s for s in spec['scenes'] if s['id'] in SCENE_IDS]
    if tuple(s['id'] for s in scenes) != SCENE_IDS:
        raise RuntimeError('B03 scene map changed')
    return spec, {'module': module, 'metadata': metadata, 'timing': timing,
                  'pcm': pcm, 'wav_duration_seconds': duration}, scenes


def scene_timing(spec, scene, audio):
    row = next(s for s in audio['timing']['scenes'] if s['scene_id'] == scene['id'])
    start = row['range_start_seconds']
    end = min(row['range_end_seconds'], audio['wav_duration_seconds'])
    _, indices = request_text_and_indices(spec, audio['module'])
    positions = indices[scene['start_offset']:scene['end_offset']]
    full = audio['timing']['alignment']
    alignment = {'characters': [full['characters'][i] for i in positions],
                 'character_start_times_seconds': [max(0, full['character_start_times_seconds'][i]-start) for i in positions],
                 'character_end_times_seconds': [max(0, full['character_end_times_seconds'][i]-start) for i in positions]}
    if ''.join(alignment['characters']) != scene['narration']:
        raise RuntimeError('B03 scene alignment differs from canonical text')
    return {**row, 'alignment': alignment, 'duration_seconds': end-start,
            'range_start_seconds': start, 'range_end_seconds': end,
            'timing_identity': hashlib.sha256((audio['metadata']['timing_sha256']+scene['id']).encode()).hexdigest()}


def source_identity():
    recipe = '\n'.join(inspect.getsource(fn) for fn in (capture_spec, prepare, perform))
    return hashlib.sha256(recipe.encode() + DIAGRAM.read_bytes() +
                          (ROOT / 'assets/s11/recording-computer.svg').read_bytes() +
                          (ROOT / 'assets/s11/recording-cloud.svg').read_bytes()).hexdigest()


def capture_spec(scene):
    return {**scene, 'visual': {'type': 'browser', 'goal': scene['goal'],
                               'capture_pipeline_revision': 'b03-source-choice-v1'},
            'initial_state': 'synchronized-recording' if scene['id'] == 'B03-008' else 'local-audio-editor-source-choice',
            'expected_state': 'B03 source selection explained', 'assertions': [],
            'fixture_set': 'existing-synthetic-zoom-v1', 'padding': {'head': 0., 'tail': 0.}}


async def prepare(page, scene, base):
    if scene['id'] == 'B03-008':
        await page.goto(DIAGRAM.as_uri())
        await page.wait_for_function('window.assetsLoaded === true && typeof window.configure === "function"')
        spec, audio, _ = inputs()
        await page.evaluate('(seconds)=>window.configure(seconds)', scene_timing(spec, scene, audio)['duration_seconds'])
    else:
        await login(page, base)
        await create_archive(page, 'Пример записи собрания')
        await page.goto(base + '/Audio-Editor.html')
        # Browser zoom preserves the real interface and its layout while making
        # the source choices legible in the 1920 × 1080 tutorial frame.
        await page.evaluate("document.body.style.zoom='1.25'")
        await page.locator('#source-session-mode-archive').wait_for(state='visible')
    await page.screenshot()


async def perform(page, scene, base, cue):
    if scene['id'] == 'B03-008':
        await page.evaluate('window.startAnimation()')
        return
    director = page.tutorial
    await cue('Аудиоархив')
    await page.locator('#source-session-mode-archive').click()
    await page.locator('#source-session-list .source-session-item').first.wait_for(state='visible')
    await page.evaluate("window.__s11Capture.hide('modal-context')")
    await cue('воспользоваться ей')
    item = page.locator('#source-session-list .source-session-item').filter(has_text='Пример записи собрания').first
    await item.get_by_role('button', name='Выбрать').click()
    await page.locator('#workflow-choice').wait_for(state='visible')
    await page.evaluate("window.__s11Capture.hide('selection-context')")


async def visual():
    if (ROOT / 'approvals/B03-block.json').exists():
        raise RuntimeError('B03 approved block is immutable')
    spec, audio, scenes = inputs()
    (OUT / 'scenes').mkdir(parents=True, exist_ok=True)
    rows = []
    with demo_server(None) as base:
        for scene in scenes:
            timing = scene_timing(spec, scene, audio)
            timing.update(visual_lead_seconds=LEAD_SECONDS if scene['id'] == SCENE_IDS[0] else 0.,
                          visual_source_sha256=source_identity(), strict_choreography=False)
            destination = OUT / 'scenes' / f"{scene['id']}.mp4"
            evidence = await capture(capture_spec(scene), spec['narration'], base,
                                     timing=timing, destination=destination,
                                     prepare_scene=prepare, perform_scene=perform)
            if evidence['browser_errors'] or evidence['production_mutation_requests']:
                raise RuntimeError('B03 isolated scene capture failed')
            row = {'scene_id': scene['id'], 'visual': str(destination), 'sha256': sha(destination),
                   'duration_seconds': evidence['duration_seconds'],
                   'cue_errors_seconds': [c['actual_seconds']-c['target_seconds'] for c in evidence['alignment_action_cues']],
                   'production_mutation_requests': evidence['production_mutation_requests']}
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    result = {'status': 'PASS', 'block_id': 'B03', 'source_mp3_sha256': audio['metadata']['source_mp3_sha256'],
              'final_wav_sha256': audio['metadata']['wav_sha256'], 'tts_requests': 0, 'scenes': rows}
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
                start = LEAD_SECONDS + timing['range_start_seconds'] + starts[first]
                end = LEAD_SECONDS + timing['range_start_seconds'] + ends[last]
                if end <= start:
                    raise RuntimeError('B03 subtitle has empty timing')
                cues.append((start, end, phrase)); begin = i+1
    if any(cues[i][0] < cues[i-1][1]-.01 for i in range(1,len(cues))):
        raise RuntimeError('B03 subtitle cues overlap')
    for suffix in ('srt','vtt'):
        vtt = suffix == 'vtt'
        content = ('WEBVTT\n\n' if vtt else '') + '\n\n'.join(
            ('' if vtt else f'{i}\n') + f'{timestamp(a,vtt=vtt)} --> {timestamp(b,vtt=vtt)}\n{text}'
            for i,(a,b,text) in enumerate(cues,1)) + '\n'
        (OUT / f'B03.ru.{suffix}').write_text(content)
    return cues


def assemble():
    if (ROOT / 'approvals/B03-block.json').exists():
        raise RuntimeError('B03 approved block is immutable')
    spec, audio, scenes = inputs()
    capture_report = json.loads((OUT / 'visual-capture.json').read_text())
    if (capture_report['source_mp3_sha256'] != audio['metadata']['source_mp3_sha256']
            or [row['scene_id'] for row in capture_report['scenes']] != list(SCENE_IDS)):
        raise RuntimeError('B03 scene capture differs from source audio')
    timings = [scene_timing(spec, scene, audio) for scene in scenes]
    cues = subtitles(scenes, timings)
    lead_samples = round(LEAD_SECONDS*RATE)
    timeline = OUT / 'B03-video-timeline.wav'
    with wave.open(str(timeline),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(RATE)
        wav.writeframes(bytes(lead_samples*2)+audio['pcm'])
    duration = math.ceil(max(LEAD_SECONDS+audio['wav_duration_seconds'],cues[-1][1]+.01)*FPS)/FPS
    bounds = [0, LEAD_SECONDS+timings[1]['range_start_seconds'], duration]
    counts = [round(bounds[i+1]*FPS)-round(bounds[i]*FPS) for i in range(2)]
    if min(counts) <= 0:
        raise RuntimeError('B03 scene frame count invalid')
    candidate = OUT / 'B03.tmp.mp4'
    command = ['ffmpeg','-y','-v','error','-f','rawvideo','-pixel_format','yuv420p',
               '-video_size','1920x1080','-framerate',str(FPS),'-i','pipe:0',
               '-i',str(timeline),'-i',str(OUT/'B03.ru.srt'),
               '-map','0:v:0','-map','1:a:0','-map','2:s:0',
               '-c:v','libx264','-preset','veryfast','-crf','21','-pix_fmt','yuv420p',
               '-c:a','aac','-b:a','192k','-c:s','mov_text','-metadata:s:s:0','language=rus',
               '-frames:v',str(sum(counts)),'-movflags','+faststart',str(candidate)]
    with (OUT/'encode.log').open('wb') as log:
        encoder = subprocess.Popen(command,stdin=subprocess.PIPE,stderr=log)
        try:
            for scene,count in zip(scenes,counts):
                path = OUT/'scenes'/f"{scene['id']}.mp4"
                if not path.is_file():
                    raise RuntimeError('B03 scene missing: '+scene['id'])
                decoder = subprocess.Popen(['ffmpeg','-v','error','-xerror','-i',str(path),'-an',
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
                if decoder.wait() or copied != count*FRAME_BYTES:
                    raise RuntimeError('B03 captured frame count mismatch: '+scene['id'])
            encoder.stdin.close()
            if encoder.wait():
                raise RuntimeError('B03 MP4 encoding failed; see encode.log')
        finally:
            if encoder.poll() is None:
                encoder.kill();encoder.wait()
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(candidate),'-f','null','-'],check=True,stdout=subprocess.DEVNULL)
    canonical = ' '.join(' '.join(scene['narration'].split()) for scene in scenes)
    checked = check_embedded_subtitles(candidate,OUT/'B03.ru.srt',canonical)
    final = OUT/'B03.mp4';candidate.replace(final)
    report = {'status':'READY FOR B03 BLOCK REVIEW','block_id':'B03','video':str(final),'video_sha256':sha(final),
              'duration_seconds':duration,'source_mp3_sha256':audio['metadata']['source_mp3_sha256'],
              'final_mp3_sha256':audio['metadata']['mp3_sha256'],'final_wav_sha256':audio['metadata']['wav_sha256'],
              'final_pcm_sha256':audio['metadata']['final_pcm_sha256'],
              'final_alignment_sha256':audio['metadata']['timing_sha256'],
              'video_audio_timeline':str(timeline),'video_audio_lead_seconds':LEAD_SECONDS,
              'internal_audio_silence_added_seconds':0,'scene_frame_counts':dict(zip(SCENE_IDS,counts)),
              'embedded_subtitle_cues':checked['embedded_subtitle_cues'],
              'last_embedded_subtitle_end_seconds':checked['last_embedded_subtitle_end_seconds'],
              'new_tts_requests':0,'production_mutation_requests':0}
    write_json(OUT/'report.json',report)
    return report


def verify():
    spec,audio,scenes=inputs()
    report=json.loads((OUT/'report.json').read_text())
    video=OUT/'B03.mp4'
    if sha(video)!=report['video_sha256'] or report['final_wav_sha256']!=audio['metadata']['wav_sha256']:
        raise RuntimeError('B03 video or approved source changed')
    with wave.open(str(OUT/'B03-video-timeline.wav')) as wav:
        timeline=wav.readframes(wav.getnframes())
    lead=round(LEAD_SECONDS*RATE)*2
    if timeline[:lead]!=bytes(lead) or timeline[lead:]!=audio['pcm']:
        raise RuntimeError('B03 video timeline changed source PCM')
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(video)]))
    streams={s['codec_type']:s for s in probe['streams']}
    frames=sum(report['scene_frame_counts'].values())
    if (int(streams['video']['nb_frames'])!=frames or streams['video']['r_frame_rate']!='30/1'
            or streams['audio']['codec_name']!='aac' or streams['subtitle']['codec_name']!='mov_text'):
        raise RuntimeError('B03 MP4 stream format invalid')
    canonical=' '.join(' '.join(scene['narration'].split()) for scene in scenes)
    checked=check_embedded_subtitles(video,OUT/'B03.ru.srt',canonical)
    decoded=subprocess.check_output(['ffmpeg','-v','error','-xerror','-i',str(video),'-map','0:a:0',
                                     '-ac','1','-ar',str(RATE),'-c:a','pcm_s16le','-f','s16le','-'])
    actual=array.array('h');actual.frombytes(decoded)
    expected=array.array('h');expected.frombytes(timeline)
    if abs(len(actual)-len(expected))>1024:
        raise RuntimeError('B03 AAC sample count differs from source timeline')
    def correlation(lag):
        dot=aa=bb=0
        for i in range(lead//2+10000,min(len(actual),len(expected)-max(0,lag)),100):
            j=i+lag
            if j<0:continue
            x,y=actual[j],expected[i];dot+=x*y;aa+=x*x;bb+=y*y
        return dot/math.sqrt(aa*bb)
    corr={lag:correlation(lag) for lag in (-32,0,32)}
    if corr[0]<.995 or corr[0]<=max(corr[-32],corr[32]):
        raise RuntimeError('B03 AAC does not align to source WAV')
    small=subprocess.check_output(['ffmpeg','-v','error','-xerror','-i',str(video),'-map','0:v:0',
                                   '-vf','scale=48:27:flags=area,format=gray','-r',str(FPS),'-f','rawvideo','-'])
    pixels=48*27
    if len(small)!=frames*pixels:
        raise RuntimeError('B03 video frame count invalid')
    lum=[];blank=[]
    for i in range(frames):
        frame=small[i*pixels:(i+1)*pixels]
        lum.append(sum(frame)/pixels)
        if max(frame)-min(frame)<12 or all(v<10 for v in frame) or all(v>245 for v in frame):blank.append(i)
    flash=[i for i in range(1,frames-1) if abs(lum[i]-lum[i-1])>35 and abs(lum[i]-lum[i+1])>35 and abs(lum[i-1]-lum[i+1])<10]
    if blank or flash:
        raise RuntimeError(f'B03 blank/flash frames: {blank[:5]} / {flash[:5]}')
    visual=json.loads((OUT/'visual-capture.json').read_text())
    cue_errors=[];cursor_violations=[]
    for scene in scenes:
        row=next(r for r in visual['scenes'] if r['scene_id']==scene['id'])
        source=OUT/'scenes'/f"{scene['id']}.mp4"
        if sha(source)!=row['sha256']:
            raise RuntimeError('B03 scene source changed')
        evidence=json.loads(source.with_suffix('.json').read_text())
        if evidence['expected_state']!='PASS' or evidence['browser_errors'] or evidence['production_mutation_requests']:
            raise RuntimeError('B03 browser scene invalid')
        cursor_violations.extend(evidence['choreography']['overlay']['violations'])
        cue_errors.extend(abs(x) for x in row['cue_errors_seconds'])
        if evidence['choreography']['overlay']['cursorVisible']:
            raise RuntimeError('B03 cursor remained visible after scene')
    if cursor_violations or (cue_errors and max(cue_errors)>.3):
        raise RuntimeError('B03 cursor lifecycle or cue synchronization failed')
    result={'status':'PASS','block_id':'B03','video_sha256':sha(video),
            'final_wav_sha256':audio['metadata']['wav_sha256'],'final_pcm_preserved_in_timeline':True,
            'aac_zero_lag_correlation':corr[0],'subtitle_cues':checked['embedded_subtitle_cues'],
            'last_embedded_subtitle_end_seconds':checked['last_embedded_subtitle_end_seconds'],
            'subtitle_matches_canonical_text':True,'video_frames':frames,'blank_frames':0,'isolated_flash_frames':0,
            'cursor_violations':0,'max_visual_cue_error_seconds':max(cue_errors) if cue_errors else None,
            'new_tts_requests':0,'production_mutation_requests':0}
    write_json(OUT/'verification.json',result)
    return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('visual','assemble','verify'))
    args=parser.parse_args()
    print(json.dumps(asyncio.run(visual()) if args.mode=='visual' else assemble() if args.mode=='assemble' else verify(),ensure_ascii=False,indent=2))
