#!/usr/bin/env python3
"""Build B02 only from its one continuous reviewed take and four conceptual scenes."""
from __future__ import annotations

import asyncio
import array
import hashlib
import inspect
import json
import math
import re
import shutil
import subprocess
import wave
from pathlib import Path

from audio_approval import validate_block_approval
from b01_block import check_embedded_subtitles, timestamp
from browser_capture import capture, visual_hash as browser_visual_hash
from build import demo_server
from modules import cached, map_timing, request_text_and_indices, sha, write_json
from validate import ROOT, validate

OUT = ROOT / 'generated/b02-visual-v3-review'
PRIOR_OUT = ROOT / 'generated/b02-visual-v2-review'
AUDIO = ROOT / 'generated/narration-blocks-v2/B02'
DIAGRAM = ROOT / 'animations/b02-tracks-v3.html'
SCENE_IDS = ('B02-004', 'B02-005', 'B02-006', 'B02-007')
LEAD_SECONDS = .6
RATE = 44100
FPS = 30
FRAME_BYTES = 1920 * 1080 * 3 // 2
VARIANT = 'B02-review-01'
PRIOR_VIDEO_SHA256 = 'd78d7823dcfb6881692d99730fc5a610c3ff54ccc3891d65c23c466f6c8b8b0a'
PRESERVED_SCENES = {
    'B02-005': '495c9cc4bdb3b0f330d0886a041edb85190d477e26d155d3d10d2bef74e9aad6',
    'B02-007': '07e1326a40ab6890ab6240635c7ef78e6b2e3a0e193014957b2c2a86519ae2b0',
}
PRESERVED_SUBTITLES = {
    'srt': '46a6f6abd4b962c29fc226f1223fa870ff7c13f639966413bfdd1a1600e1759f',
    'vtt': 'a6f0114b2d6955e1674ec8b3c30b35ea0a00a79c5c4041f54e8630cc4ce4276f',
}


def inputs() -> tuple[dict, dict, list[dict]]:
    validate()
    validate_block_approval('B01')
    spec = json.loads((ROOT / 'tutorial.yaml').read_text())
    module = next(m for m in spec['narration_modules'] if m['id'] == 'B02')
    hit = cached(spec, module)
    if not hit:
        raise RuntimeError('B02 one-request source take is missing or stale')
    metadata = json.loads((AUDIO / f'{VARIANT}-metadata.json').read_text())
    review = json.loads((AUDIO / 'B02-review-map.json').read_text())
    if (review['block_id'], review['variant_id'], review['status']) != ('B02', 'review-01', 'SEMANTIC_REVIEWED'):
        raise RuntimeError('B02 reviewed silence map is invalid')
    for name, digest in ((AUDIO / 'narration.mp3', metadata['source_mp3_sha256']),
                         (AUDIO / f'{VARIANT}.wav', metadata['wav_sha256']),
                         (AUDIO / f'{VARIANT}.mp3', metadata['mp3_sha256']),
                         (AUDIO / f'{VARIANT}-timing.json', metadata['timing_sha256']),
                         (AUDIO / f'{VARIANT}-source-timing.json', metadata['source_timing_sha256'])):
        if sha(name) != digest:
            raise RuntimeError(f'B02 reviewed audio file changed: {name.name}')
    if metadata['source_mp3_sha256'] != hit['metadata']['audio_sha256'] or metadata['source_timing_sha256'] != hit['metadata']['timing_sha256']:
        raise RuntimeError('B02 reviewed audio does not derive from its one-request source')
    if (metadata['new_tts_requests'] != 0 or metadata['speed_pitch_gain_processing']
            or not metadata['source_pcm_recovered_exactly']):
        raise RuntimeError('B02 audio review altered source speech')
    events = metadata['events']
    if ([row['after_offset'] for row in events] != [row['after_offset'] for row in review['insertions']]
            or any(event['reason'] != request['reason'] for event, request in zip(events, review['insertions']))):
        raise RuntimeError('B02 insertion events differ from reviewed semantic map')
    with wave.open(str(AUDIO / f'{VARIANT}.wav')) as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, RATE):
            raise RuntimeError('B02 final WAV must be 44.1 kHz mono s16 PCM')
        pcm = wav.readframes(wav.getnframes())
        wav_duration = wav.getnframes() / RATE
    if hashlib.sha256(pcm).hexdigest() != metadata['final_pcm_sha256']:
        raise RuntimeError('B02 reviewed PCM changed')
    source = subprocess.check_output(['ffmpeg', '-v', 'error', '-xerror', '-i', str(AUDIO / 'narration.mp3'),
                                      '-map', '0:a:0', '-c:a', 'pcm_s16le', '-f', 's16le', '-'])
    if hashlib.sha256(source).hexdigest() != metadata['source_pcm_sha256']:
        raise RuntimeError('B02 source PCM changed')
    restored = bytearray()
    previous = 0
    for event in events:
        start = event['insert_start_final_sample'] * 2
        end = start + event['added_samples'] * 2
        if start < previous or pcm[start:end] != bytes(end-start):
            raise RuntimeError('B02 inserted region is invalid')
        restored.extend(pcm[previous:start]); previous = end
    restored.extend(pcm[previous:])
    if bytes(restored) != source:
        raise RuntimeError('B02 source PCM was not restored byte for byte')
    timing = json.loads((AUDIO / f'{VARIANT}-timing.json').read_text())
    if timing != map_timing(spec, module, timing['alignment'], timing['duration_seconds']):
        raise RuntimeError('B02 final alignment does not map to canonical text')
    scenes = [s for s in spec['scenes'] if s['id'] in SCENE_IDS]
    if tuple(s['id'] for s in scenes) != SCENE_IDS:
        raise RuntimeError('B02 technical scene map changed')
    return spec, {'module': module, 'metadata': metadata, 'timing': timing,
                  'wav_path': AUDIO / f'{VARIANT}.wav', 'wav_duration_seconds': wav_duration}, scenes


def scene_timing(spec: dict, scene: dict, audio: dict) -> dict:
    row = next(s for s in audio['timing']['scenes'] if s['scene_id'] == scene['id'])
    start = row['range_start_seconds']
    end = min(row['range_end_seconds'], audio['wav_duration_seconds'])
    _, positions = request_text_and_indices(spec, audio['module'])
    positions = positions[scene['start_offset']:scene['end_offset']]
    full = audio['timing']['alignment']
    local = {'characters': [full['characters'][i] for i in positions],
             'character_start_times_seconds': [max(0, full['character_start_times_seconds'][i]-start) for i in positions],
             'character_end_times_seconds': [max(0, full['character_end_times_seconds'][i]-start) for i in positions]}
    if ''.join(local['characters']) != scene['narration']:
        raise RuntimeError('B02 scene alignment differs from canonical text')
    return {**row, 'alignment': local, 'duration_seconds': end-start,
            'range_start_seconds': start, 'range_end_seconds': end,
            'timing_identity': hashlib.sha256((audio['metadata']['timing_sha256'] + scene['id']).encode()).hexdigest()}


def source_identity() -> str:
    recipe = '\n'.join(inspect.getsource(fn) for fn in (capture_spec, prepare, perform))
    assets = (ROOT / 'assets/s11/recording-computer.svg',
              ROOT / 'assets/s11/recording-cloud.svg',
              ROOT / 'assets/s11/nam-poputi-catalog-2026-10-02.png')
    return hashlib.sha256(recipe.encode() + DIAGRAM.read_bytes() +
                          b''.join(path.read_bytes() for path in assets)).hexdigest()


def capture_spec(scene: dict) -> dict:
    return {**scene, 'visual': {'type': 'browser', 'goal': scene['goal'],
                               'capture_pipeline_revision': 'b02-local-visual-corrections-v3'},
            'initial_state': scene['id'], 'expected_state': 'B02 continuous waveform transformation',
            'assertions': [], 'fixture_set': 'existing-synthetic-zoom-v1',
            'padding': {'head': 0., 'tail': 0.}}


async def prepare(page, scene: dict, base: str) -> None:
    await page.goto(DIAGRAM.as_uri())
    await page.wait_for_function('typeof window.configure === "function"')
    spec, audio, _ = inputs()
    timing = scene_timing(spec, scene, audio)
    await page.evaluate('args => window.configure(args.id,args.duration)',
                        {'id': scene['id'], 'duration': timing['duration_seconds']})
    await page.wait_for_function('window.assetsLoaded === true')
    await page.screenshot()


async def perform(page, scene: dict, base: str, cue) -> None:
    await page.evaluate('window.startAnimation()')


async def visual() -> dict:
    if (ROOT / 'approvals/B02-block.json').exists():
        raise RuntimeError('B02 complete block is approved and immutable')
    spec, audio, scenes = inputs()
    if sha(PRIOR_OUT / 'B02.mp4') != PRIOR_VIDEO_SHA256:
        raise RuntimeError('prior B02 candidate changed')
    (OUT / 'scenes').mkdir(parents=True, exist_ok=True)
    rows = []
    with demo_server(None) as base:
        for scene in scenes:
            timing = scene_timing(spec, scene, audio)
            timing.update(visual_lead_seconds=LEAD_SECONDS if scene['id'] == SCENE_IDS[0] else 0.,
                          visual_source_sha256=source_identity(), strict_choreography=False)
            destination = OUT / 'scenes' / f"{scene['id']}.mp4"
            if scene['id'] in PRESERVED_SCENES:
                prior = PRIOR_OUT / 'scenes' / f"{scene['id']}.mp4"
                if sha(prior) != PRESERVED_SCENES[scene['id']]:
                    raise RuntimeError('preserved B02 scene changed: ' + scene['id'])
                shutil.copy2(prior, destination)
                shutil.copy2(prior.with_suffix('.json'), destination.with_suffix('.json'))
                evidence = json.loads(destination.with_suffix('.json').read_text())
            else:
                evidence = await capture(capture_spec(scene), spec['narration'], base,
                                         timing=timing, destination=destination,
                                         prepare_scene=prepare, perform_scene=perform)
            if max((event['seconds'] for event in evidence['choreography']['events']), default=0) > timing['duration_seconds'] + timing['visual_lead_seconds'] + .1:
                raise RuntimeError('B02 choreography exceeds scene duration')
            if evidence['choreography']['overlay']['cursorVisible']:
                raise RuntimeError('B02 conceptual animation must not show a cursor')
            row = {'scene_id': scene['id'], 'visual': str(destination), 'sha256': sha(destination),
                   'duration_seconds': evidence['duration_seconds'],
                   'cue_errors_seconds': [c['actual_seconds']-c['target_seconds'] for c in evidence['alignment_action_cues']],
                   'production_mutation_requests': evidence['production_mutation_requests'],
                   'preserved_from_previous_candidate': scene['id'] in PRESERVED_SCENES}
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    report = {'status': 'PASS', 'block_id': 'B02', 'source_mp3_sha256': audio['metadata']['source_mp3_sha256'],
              'final_wav_sha256': audio['metadata']['wav_sha256'], 'tts_requests': 0, 'scenes': rows}
    write_json(OUT / 'visual-capture.json', report)
    return report


def subtitles(scenes: list[dict], timings: list[dict]) -> list[tuple[float, float, str]]:
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
                    raise RuntimeError('empty B02 subtitle timing')
                cues.append((start, end, phrase)); begin = i+1
    if any(cues[i][0] < cues[i-1][1]-.01 for i in range(1, len(cues))):
        raise RuntimeError('B02 subtitle overlap')
    if any('[' in text or ']' in text for _, _, text in cues):
        raise RuntimeError('B02 TTS tags entered subtitles')
    for suffix in ('srt', 'vtt'):
        vtt = suffix == 'vtt'
        body = ('WEBVTT\n\n' if vtt else '') + '\n\n'.join(
            ('' if vtt else f'{i}\n') + f'{timestamp(a,vtt=vtt)} --> {timestamp(b,vtt=vtt)}\n{text}'
            for i, (a, b, text) in enumerate(cues, 1)) + '\n'
        (OUT / f'B02.ru.{suffix}').write_text(body)
    return cues


def assemble() -> dict:
    if (ROOT / 'approvals/B02-block.json').exists():
        raise RuntimeError('B02 complete block is approved and immutable')
    spec, audio, scenes = inputs()
    capture_report = json.loads((OUT / 'visual-capture.json').read_text())
    if (capture_report['source_mp3_sha256'] != audio['metadata']['source_mp3_sha256']
            or [row['scene_id'] for row in capture_report['scenes']] != list(SCENE_IDS)):
        raise RuntimeError('B02 capture does not match reviewed audio and scene map')
    timings = [scene_timing(spec, scene, audio) for scene in scenes]
    cues = subtitles(scenes, timings)
    for suffix, digest in PRESERVED_SUBTITLES.items():
        if sha(OUT / f'B02.ru.{suffix}') != digest:
            raise RuntimeError('B02 subtitles changed during visual-only correction')
    with wave.open(str(audio['wav_path'])) as wav:
        final_pcm = wav.readframes(wav.getnframes())
    lead_samples = round(LEAD_SECONDS * RATE)
    timeline = OUT / 'B02-video-timeline.wav'
    with wave.open(str(timeline), 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(RATE)
        wav.writeframes(bytes(lead_samples*2) + final_pcm)
    audio_duration = LEAD_SECONDS + audio['wav_duration_seconds']
    visual_duration = math.ceil(max(audio_duration, cues[-1][1]+.01)*FPS)/FPS
    bounds = [0] + [LEAD_SECONDS + t['range_start_seconds'] for t in timings[1:]] + [visual_duration]
    counts = [round(bounds[i+1]*FPS)-round(bounds[i]*FPS) for i in range(len(SCENE_IDS))]
    if min(counts) <= 0:
        raise RuntimeError('invalid B02 scene frame count')
    final, candidate = OUT / 'B02.mp4', OUT / 'B02.tmp.mp4'
    command = ['ffmpeg', '-y', '-v', 'error', '-f', 'rawvideo', '-pixel_format', 'yuv420p',
               '-video_size', '1920x1080', '-framerate', str(FPS), '-i', 'pipe:0',
               '-i', str(timeline), '-i', str(OUT / 'B02.ru.srt'),
               '-map', '0:v:0', '-map', '1:a:0', '-map', '2:s:0',
               '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21', '-pix_fmt', 'yuv420p',
               '-c:a', 'aac', '-b:a', '192k', '-c:s', 'mov_text',
               '-metadata:s:s:0', 'language=rus', '-frames:v', str(sum(counts)),
               '-movflags', '+faststart', str(candidate)]
    with (OUT / 'encode.log').open('wb') as log:
        encoder = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=log)
        try:
            for scene, count in zip(scenes, counts):
                path = OUT / 'scenes' / f"{scene['id']}.mp4"
                if not path.is_file():
                    raise RuntimeError('B02 scene capture missing: ' + scene['id'])
                decoder = subprocess.Popen(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path), '-an',
                                            '-vf', 'scale=1920:1080,fps=30,trim=start_frame=1,'
                                                   'tpad=start=1:start_mode=clone,setpts=N/(30*TB),'
                                                   'tpad=stop_mode=clone:stop=300',
                                            '-r', str(FPS), '-frames:v', str(count), '-pix_fmt', 'yuv420p',
                                            '-f', 'rawvideo', 'pipe:1'], stdout=subprocess.PIPE)
                copied = 0
                try:
                    while chunk := decoder.stdout.read(1024*1024):
                        encoder.stdin.write(chunk); copied += len(chunk)
                finally:
                    decoder.stdout.close()
                if decoder.wait() or copied != count*FRAME_BYTES:
                    raise RuntimeError('B02 visual frame count mismatch: ' + scene['id'])
            encoder.stdin.close()
            if encoder.wait():
                raise RuntimeError('B02 MP4 encode failed; see encode.log')
        finally:
            if encoder.poll() is None:
                encoder.kill(); encoder.wait()
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(candidate), '-f', 'null', '-'],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    canonical = ' '.join(' '.join(scene['narration'].split()) for scene in scenes)
    subtitle_check = check_embedded_subtitles(candidate, OUT / 'B02.ru.srt', canonical)
    candidate.replace(final)
    info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
                                               '-show_format', '-of', 'json', str(final)]))
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    sound = next(s for s in info['streams'] if s['codec_type'] == 'audio')
    if (video['codec_name'], video['width'], video['height']) != ('h264', 1920, 1080) or sound['codec_name'] != 'aac':
        raise RuntimeError('B02 MP4 output stream format invalid')
    if abs(float(info['format']['duration'])-visual_duration) > .08:
        raise RuntimeError('B02 video duration differs from final alignment')
    report = {'status': 'READY FOR B02 BLOCK REVIEW', 'block_id': 'B02',
              'source_mp3_sha256': audio['metadata']['source_mp3_sha256'],
              'final_mp3_sha256': audio['metadata']['mp3_sha256'],
              'final_wav_sha256': audio['metadata']['wav_sha256'],
              'final_pcm_sha256': audio['metadata']['final_pcm_sha256'],
              'final_alignment_sha256': audio['metadata']['timing_sha256'],
              'video_audio_timeline': str(timeline), 'video_audio_lead_seconds': LEAD_SECONDS,
              'internal_audio_silence_added_seconds': audio['metadata']['events'][0]['added_seconds'],
              'visual_tail_seconds': visual_duration-audio_duration,
              'video': str(final), 'video_sha256': sha(final),
              'duration_seconds': float(info['format']['duration']),
              'scene_frame_counts': dict(zip(SCENE_IDS, counts)), 'subtitle_cues': len(cues),
              **subtitle_check, 'new_tts_requests': 0, 'production_mutation_requests': 0}
    write_json(OUT / 'report.json', report)
    (OUT / 'index.html').write_text(f'''<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>B02 · Review</title>
<style>body{{margin:0;background:#0b2238;color:#eaf5ff;font:18px/1.45 system-ui,sans-serif}}
main{{max-width:1200px;margin:auto;padding:24px}}h1{{margin:0 0 6px;font-size:32px}}p{{color:#bdd7ea}}
video{{display:block;width:100%;aspect-ratio:16/9;background:#071522;border-radius:12px;margin:22px 0}}
button,a{{color:#eaf5ff;background:#245c87;border:1px solid #5799c8;border-radius:8px;padding:10px 14px;margin:0 8px 8px 0;font:inherit;cursor:pointer}}
a{{display:inline-block;text-decoration:none}}button:hover,a:hover{{background:#3179ad}}</style>
<main><h1>B02 · Запись в виде отдельных аудиодорожек</h1><p>Полный блок для просмотра · B01 BLOCK_APPROVED · 0 новых TTS-запросов</p>
<video id="review" controls playsinline preload="metadata"><source src="B02.mp4?v={sha(final)[:12]}" type="video/mp4">
<track kind="subtitles" src="B02.ru.vtt" srclang="ru" label="Русские субтитры"></video>
<nav aria-label="Сцены"><button data-seek="0">004 · Режимы записи</button>
<button data-seek="{bounds[1]:.2f}">005 · Переводчик</button>
<button data-seek="{bounds[2]:.2f}">006 · Проблемы звука</button>
<button data-seek="{bounds[3]:.2f}">007 · Обработка</button></nav>
<a href="B02.mp4" download>Скачать MP4</a><a href="B02.ru.srt" download>Скачать субтитры</a>
<script>document.querySelectorAll('[data-seek]').forEach(b=>b.addEventListener('click',()=>{{
const v=document.getElementById('review');v.currentTime=Number(b.dataset.seek);v.play()}}));</script></main></html>''')
    return report


def verify() -> dict:
    spec, audio, scenes = inputs()
    report = json.loads((OUT / 'report.json').read_text())
    video_path = Path(report['video'])
    if sha(video_path) != report['video_sha256'] or report['final_wav_sha256'] != audio['metadata']['wav_sha256']:
        raise RuntimeError('B02 review MP4 or audio source changed')
    with wave.open(str(audio['wav_path'])) as wav:
        final_pcm = wav.readframes(wav.getnframes())
    with wave.open(report['video_audio_timeline']) as wav:
        timeline_pcm = wav.readframes(wav.getnframes())
    lead = round(report['video_audio_lead_seconds']*RATE)*2
    if timeline_pcm[:lead] != bytes(lead) or timeline_pcm[lead:] != final_pcm:
        raise RuntimeError('B02 video timeline altered reviewed PCM')
    info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
                                               '-show_format', '-of', 'json', str(video_path)]))
    streams = {stream['codec_type']: stream for stream in info['streams']}
    frames = sum(report['scene_frame_counts'].values())
    if (int(streams['video']['nb_frames']) != frames or streams['video']['r_frame_rate'] != '30/1'
            or streams['audio']['codec_name'] != 'aac' or streams['subtitle']['codec_name'] != 'mov_text'):
        raise RuntimeError('B02 MP4 frame, audio or subtitle stream invalid')
    canonical = ' '.join(' '.join(scene['narration'].split()) for scene in scenes)
    subtitle_check = check_embedded_subtitles(video_path, OUT / 'B02.ru.srt', canonical)
    decoded = subprocess.check_output(['ffmpeg', '-v', 'error', '-xerror', '-i', str(video_path),
                                       '-map', '0:a:0', '-ac', '1', '-ar', str(RATE),
                                       '-c:a', 'pcm_s16le', '-f', 's16le', '-'])
    actual_samples = array.array('h'); actual_samples.frombytes(decoded)
    expected_samples = array.array('h'); expected_samples.frombytes(timeline_pcm)
    if abs(len(actual_samples)-len(expected_samples)) > 1024:
        raise RuntimeError('B02 AAC sample count differs from reviewed timeline')
    def correlation(lag: int) -> float:
        dot = aa = bb = 0
        for i in range(lead//2+10000, min(len(expected_samples),len(actual_samples)-max(0,lag)), 100):
            j = i+lag
            if j < 0: continue
            a,b = actual_samples[j],expected_samples[i]
            dot += a*b; aa += a*a; bb += b*b
        return dot/math.sqrt(aa*bb)
    correlations = {lag: correlation(lag) for lag in (-32,0,32)}
    if correlations[0] < .995 or correlations[0] <= max(correlations[-32],correlations[32]):
        raise RuntimeError('B02 AAC is not aligned with reviewed WAV')
    small = subprocess.check_output(['ffmpeg', '-v', 'error', '-xerror', '-i', str(video_path),
                                     '-map', '0:v:0', '-vf', 'scale=48:27:flags=area,format=gray',
                                     '-r', str(FPS), '-f', 'rawvideo', '-'])
    pixels = 48*27
    if len(small) != frames*pixels:
        raise RuntimeError('B02 decoded visual frame count invalid')
    blank = []; luminance = []
    for i in range(frames):
        frame = small[i*pixels:(i+1)*pixels]
        luminance.append(sum(frame)/pixels)
        if max(frame)-min(frame) < 12 or all(x < 10 for x in frame) or all(x > 245 for x in frame):
            blank.append(i)
    if blank:
        raise RuntimeError(f'B02 blank or near-uniform frames: {blank[:8]}')
    flashes = [i for i in range(1,frames-1) if abs(luminance[i]-luminance[i-1]) > 35
               and abs(luminance[i]-luminance[i+1]) > 35 and abs(luminance[i-1]-luminance[i+1]) < 10]
    if flashes:
        raise RuntimeError(f'B02 isolated flash frames: {flashes[:8]}')
    errors = []; cursor_shows = 0
    capture_rows = {row['scene_id']: row for row in json.loads((OUT / 'visual-capture.json').read_text())['scenes']}
    for scene in scenes:
        if capture_rows[scene['id']]['sha256'] != sha(OUT / 'scenes' / f"{scene['id']}.mp4"):
            raise RuntimeError('B02 source scene changed: ' + scene['id'])
        meta = json.loads((OUT / 'scenes' / f"{scene['id']}.json").read_text())
        timing = scene_timing(spec, scene, audio)
        visual_inputs = {'visual_lead_seconds': LEAD_SECONDS if scene['id'] == SCENE_IDS[0] else 0.,
                         'visual_source_sha256': source_identity(), 'strict_choreography': False}
        if scene['id'] in PRESERVED_SCENES:
            prior = PRIOR_OUT / 'scenes' / f"{scene['id']}.mp4"
            if (sha(prior) != PRESERVED_SCENES[scene['id']]
                    or sha(OUT / 'scenes' / f"{scene['id']}.mp4") != sha(prior)
                    or meta != json.loads(prior.with_suffix('.json').read_text())):
                raise RuntimeError('B02 preserved scene differs from prior candidate: ' + scene['id'])
        else:
            expected_hash = hashlib.sha256((browser_visual_hash(capture_spec(scene)) +
                timing['timing_identity'] + json.dumps(visual_inputs, sort_keys=True)).encode()).hexdigest()
            if meta['visual_hash'] != expected_hash:
                raise RuntimeError('B02 corrected capture is stale: ' + scene['id'])
        if meta['expected_state'] != 'PASS' or meta['browser_errors'] or meta['production_mutation_requests']:
            raise RuntimeError('B02 capture was not isolated or did not pass')
        overlay = meta['choreography']['overlay']
        cursor_shows += sum(event['type'] == 'cursor-show' for event in overlay['events'])
        if overlay['violations'] or overlay['cursorVisible']:
            raise RuntimeError('B02 animation showed cursor or invalid overlay')
        errors.extend(abs(c.get('error_seconds', c['actual_seconds']-c['target_seconds']))
                      for c in meta['alignment_action_cues'])
    if (errors and max(errors) > .18) or cursor_shows:
        raise RuntimeError('B02 visual cues drift or conceptual cursor appeared')
    result = {'status': 'PASS', 'block_id': 'B02', 'video_sha256': report['video_sha256'],
              'source_mp3_sha256': audio['metadata']['source_mp3_sha256'],
              'final_wav_sha256': audio['metadata']['wav_sha256'],
              'final_pcm_preserved_in_timeline': True,
              'source_pcm_restored_exactly': True,
              'aac_zero_lag_correlation': correlations[0],
              'subtitle_cues': subtitle_check['embedded_subtitle_cues'],
              'last_embedded_subtitle_end_seconds': subtitle_check['last_embedded_subtitle_end_seconds'],
              'subtitle_matches_canonical_text': True,
              'video_frames': frames, 'blank_frames': 0, 'isolated_flash_frames': 0,
              'cursor_show_events': cursor_shows,
              'measured_visual_cue_count': len(errors),
              'max_visual_cue_error_seconds': max(errors) if errors else None,
              'new_tts_requests': 0, 'production_mutation_requests': 0}
    write_json(OUT / 'verification.json', result)
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('visual', 'assemble', 'verify'))
    args = parser.parse_args()
    output = asyncio.run(visual()) if args.mode == 'visual' else assemble() if args.mode == 'assemble' else verify()
    print(json.dumps(output, ensure_ascii=False, indent=2))
