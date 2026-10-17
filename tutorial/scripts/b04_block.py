#!/usr/bin/env python3
"""Render B04-010 using its continuous narration and the real mode-choice UI."""
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
from scenes import login, import_archive
from validate import ROOT, validate

OUT = ROOT / 'generated/b04-block-review'
AUDIO = ROOT / 'generated/narration-blocks-v2/B04'
SCENE_ID = 'B04-010'
VARIANT = 'B04-review-01'
LEAD = .6
RATE = 44100
FPS = 30
FRAME_BYTES = 1920 * 1080 * 3 // 2


def inputs():
    validate()
    validate_block_approval('B03')
    spec = json.loads((ROOT / 'tutorial.yaml').read_text())
    module = next(m for m in spec['narration_modules'] if m['id'] == 'B04')
    hit = cached(spec, module)
    if not hit:
        raise RuntimeError('B04 one-request narration is missing or stale')
    metadata = json.loads((AUDIO / f'{VARIANT}-metadata.json').read_text())
    review = json.loads((AUDIO / 'B04-review-map.json').read_text())
    if (review['status'], review['block_id'], review['variant_id']) != ('SEMANTIC_REVIEWED', 'B04', 'review-01'):
        raise RuntimeError('B04 semantic review map invalid')
    for path, digest in ((AUDIO / 'narration.mp3', metadata['source_mp3_sha256']),
                         (AUDIO / f'{VARIANT}.mp3', metadata['mp3_sha256']),
                         (AUDIO / f'{VARIANT}.wav', metadata['wav_sha256']),
                         (AUDIO / f'{VARIANT}-timing.json', metadata['timing_sha256'])):
        if sha(path) != digest:
            raise RuntimeError('B04 reviewed audio source changed: ' + str(path))
    if (metadata['source_mp3_sha256'] != hit['metadata']['audio_sha256']
            or metadata['new_tts_requests'] or metadata['speed_pitch_gain_processing']
            or not metadata['source_pcm_recovered_exactly'] or metadata['events']):
        raise RuntimeError('B04 review must preserve one unmodified TTS take')
    with wave.open(str(AUDIO / f'{VARIANT}.wav')) as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, RATE):
            raise RuntimeError('B04 WAV format invalid')
        pcm = wav.readframes(wav.getnframes())
        duration = wav.getnframes() / RATE
    if hashlib.sha256(pcm).hexdigest() != metadata['final_pcm_sha256']:
        raise RuntimeError('B04 PCM source changed')
    timing = json.loads((AUDIO / f'{VARIANT}-timing.json').read_text())
    if timing != map_timing(spec, module, timing['alignment'], timing['duration_seconds']):
        raise RuntimeError('B04 alignment no longer maps to canonical text')
    scene = next(s for s in spec['scenes'] if s['id'] == SCENE_ID)
    if scene['narration'] != module['narration']:
        raise RuntimeError('B04 scene differs from its canonical block')
    _, indices = request_text_and_indices(spec, module)
    full = timing['alignment']
    local = {'characters': [full['characters'][i] for i in indices],
             'character_start_times_seconds': [full['character_start_times_seconds'][i] for i in indices],
             'character_end_times_seconds': [full['character_end_times_seconds'][i] for i in indices]}
    if ''.join(local['characters']) != scene['narration']:
        raise RuntimeError('B04 scene alignment differs from canonical text')
    scene_timing = {**timing['scenes'][0], 'alignment': local,
                    'duration_seconds': duration, 'visual_lead_seconds': LEAD,
                    'timing_identity': hashlib.sha256((metadata['timing_sha256'] + SCENE_ID).encode()).hexdigest(),
                    'strict_choreography': False}
    return spec, scene, scene_timing, metadata, pcm, duration


def capture_spec(scene):
    return {**scene, 'visual': {'type': 'browser', 'goal': scene['goal'],
                               'capture_pipeline_revision': 'b04-mode-choice-v1'},
            'initial_state': 'real-editor-workflow-choice', 'expected_state': 'Announcement editor opened',
            'assertions': [], 'fixture_set': 'existing-synthetic-zoom-v1',
            'padding': {'head': 0., 'tail': 0.}}


async def prepare(page, scene, base):
    await login(page, base)
    await import_archive(page, base, 'Пример записи собрания')
    # The entire viewport and capture overlay share the same 1536 × 864
    # coordinate system; final scaling applies to both exactly once.
    await page.set_viewport_size({'width': 1536, 'height': 864})
    choice = page.locator('#workflow-choice')
    await choice.evaluate("el => el.scrollIntoView({block: 'center', behavior: 'instant'})")
    await page.wait_for_timeout(120)
    if not await choice.is_visible() or not await page.locator('#open-local-announcement').is_visible():
        raise RuntimeError('real mode-choice controls are not visible')


async def perform(page, scene, base, cue):
    await cue('Давайте сперва')
    await page.locator('#open-local-announcement').click()
    await page.locator('#announcement-processor-card').wait_for(state='visible', timeout=60000)
    await page.evaluate("window.__s11Capture.hide('workflow-context-changed')")
    if await page.locator('#workflow-choice').is_visible():
        raise RuntimeError('mode choice did not close after opening Announcement')


async def visual():
    if (ROOT / 'approvals/B04-block.json').exists():
        raise RuntimeError('B04 complete block is approved and immutable')
    spec, scene, timing, metadata, _, _ = inputs()
    (OUT / 'scenes').mkdir(parents=True, exist_ok=True)
    recipe = '\n'.join(inspect.getsource(fn) for fn in (capture_spec, prepare, perform))
    timing['visual_source_sha256'] = hashlib.sha256(recipe.encode()).hexdigest()
    destination = OUT / 'scenes' / f'{SCENE_ID}.mp4'
    with demo_server(None) as base:
        evidence = await capture(capture_spec(scene), spec['narration'], base, timing=timing,
                                 destination=destination, prepare_scene=prepare, perform_scene=perform)
    if evidence['browser_errors'] or evidence['production_mutation_requests']:
        raise RuntimeError('B04 isolated scene capture failed')
    row = {'scene_id': SCENE_ID, 'visual': str(destination), 'sha256': sha(destination),
           'duration_seconds': evidence['duration_seconds'],
           'cue_errors_seconds': [c['actual_seconds'] - c['target_seconds'] for c in evidence['alignment_action_cues']],
           'production_mutation_requests': evidence['production_mutation_requests']}
    result = {'status': 'PASS', 'block_id': 'B04', 'source_mp3_sha256': metadata['source_mp3_sha256'],
              'final_wav_sha256': metadata['wav_sha256'], 'tts_requests': 0, 'scenes': [row]}
    write_json(OUT / 'visual-capture.json', result)
    return result


def subtitles(scene, timing):
    text = scene['narration']
    starts = timing['alignment']['character_start_times_seconds']
    ends = timing['alignment']['character_end_times_seconds']
    words = list(re.finditer(r'\S+', text))
    cues = []
    begin = 0
    for i, word in enumerate(words):
        first, last = words[begin].start(), word.end() - 1
        phrase = ' '.join(text[first:last+1].split())
        if len(phrase) >= 68 or word.group()[-1:] in '.!?…' or i == len(words)-1:
            cues.append((LEAD + starts[first], LEAD + ends[last], phrase))
            begin = i + 1
    if any(a >= b or '[' in caption or ']' in caption for a, b, caption in cues):
        raise RuntimeError('B04 subtitle timing or text invalid')
    for suffix in ('srt', 'vtt'):
        vtt = suffix == 'vtt'
        body = ('WEBVTT\n\n' if vtt else '') + '\n\n'.join(
            ('' if vtt else f'{i}\n') + f'{timestamp(a,vtt=vtt)} --> {timestamp(b,vtt=vtt)}\n{caption}'
            for i, (a, b, caption) in enumerate(cues, 1)) + '\n'
        (OUT / f'B04.ru.{suffix}').write_text(body)
    return cues


def assemble():
    if (ROOT / 'approvals/B04-block.json').exists():
        raise RuntimeError('B04 complete block is approved and immutable')
    spec, scene, timing, metadata, pcm, audio_duration = inputs()
    visual_report = json.loads((OUT / 'visual-capture.json').read_text())
    source = OUT / 'scenes' / f'{SCENE_ID}.mp4'
    if (visual_report['source_mp3_sha256'] != metadata['source_mp3_sha256']
            or sha(source) != visual_report['scenes'][0]['sha256']):
        raise RuntimeError('B04 visual source differs from reviewed audio')
    cues = subtitles(scene, timing)
    timeline = OUT / 'B04-video-timeline.wav'
    with wave.open(str(timeline), 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(RATE)
        wav.writeframes(bytes(round(LEAD * RATE) * 2) + pcm)
    duration = math.ceil(max(LEAD + audio_duration, cues[-1][1] + .01) * FPS) / FPS
    count = round(duration * FPS)
    candidate = OUT / 'B04.tmp.mp4'
    command = ['ffmpeg', '-y', '-v', 'error', '-i', str(source), '-i', str(timeline),
               '-i', str(OUT / 'B04.ru.srt'), '-map', '0:v:0', '-map', '1:a:0', '-map', '2:s:0',
               '-vf', f'fps={FPS},scale=1920:1080,tpad=stop_mode=clone:stop=300,trim=end_frame={count},setpts=N/({FPS}*TB)',
               '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21', '-pix_fmt', 'yuv420p',
               '-c:a', 'aac', '-b:a', '192k', '-c:s', 'mov_text', '-metadata:s:s:0', 'language=rus',
               '-r', str(FPS), '-frames:v', str(count), '-movflags', '+faststart', str(candidate)]
    subprocess.run(command, check=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(candidate), '-f', 'null', '-'],
                   check=True, stdout=subprocess.DEVNULL)
    checked = check_embedded_subtitles(candidate, OUT / 'B04.ru.srt', ' '.join(scene['narration'].split()))
    final = OUT / 'B04.mp4'
    candidate.replace(final)
    report = {'status': 'READY FOR B04 BLOCK REVIEW', 'block_id': 'B04', 'video': str(final),
              'video_sha256': sha(final), 'duration_seconds': duration,
              'source_mp3_sha256': metadata['source_mp3_sha256'], 'final_mp3_sha256': metadata['mp3_sha256'],
              'final_wav_sha256': metadata['wav_sha256'], 'final_pcm_sha256': metadata['final_pcm_sha256'],
              'final_alignment_sha256': metadata['timing_sha256'], 'video_audio_timeline': str(timeline),
              'video_audio_lead_seconds': LEAD, 'internal_audio_silence_added_seconds': 0,
              'scene_frame_counts': {SCENE_ID: count}, 'embedded_subtitle_cues': checked['embedded_subtitle_cues'],
              'last_embedded_subtitle_end_seconds': checked['last_embedded_subtitle_end_seconds'],
              'new_tts_requests': 0, 'production_mutation_requests': 0}
    write_json(OUT / 'report.json', report)
    return report


def pointer_check(video, evidence):
    events = evidence['choreography']['events']
    arrivals = [event for event in events if event['type'] == 'cursor-arrival']
    clicks = [event for event in events if event['type'] == 'click']
    viewport_w, viewport_h = evidence['choreography']['overlay']['viewport']
    if len(arrivals) != 1 or len(clicks) != 1 or '#open-local-announcement' not in arrivals[0]['target']:
        raise RuntimeError('B04 must contain one click on the real Announcement button')
    box = arrivals[0]['box']
    target = [box['x'] * 960 / viewport_w, box['y'] * 540 / viewport_h,
              (box['x'] + box['width']) * 960 / viewport_w,
              (box['y'] + box['height']) * 540 / viewport_h]
    press = clicks[0]['seconds']
    start = press - .3
    rgb = subprocess.check_output(['ffmpeg', '-v', 'error', '-ss', f'{start:.6f}', '-i', str(video),
                                   '-t', '0.9', '-vf', 'fps=30,scale=960:540,format=rgb24', '-f', 'rawvideo', '-'])
    width, height = 960, 540
    frame_bytes = width * height * 3
    best = (0, -1, None)
    for frame_number in range(len(rgb) // frame_bytes):
        frame = rgb[frame_number * frame_bytes:(frame_number+1)*frame_bytes]
        points = []
        for y in range(max(0, int(target[1])-12), min(height, int(target[3])+12)):
            for x in range(max(0, int(target[0])-12), min(width, int(target[2])+12)):
                k = (y * width + x) * 3
                red, green, blue = frame[k:k+3]
                if red >= 190 and 115 <= green <= 240 and blue <= 170 and red > green+8 and green > blue+25:
                    points.append((x, y))
        if len(points) > best[0]:
            best = (len(points), frame_number,
                    [min(x for x, _ in points), min(y for _, y in points),
                     max(x for x, _ in points), max(y for _, y in points)] if points else None)
    pixels, frame_number, ring = best
    if pixels < 10 or ring is None or not (target[0] <= ring[0] <= ring[2] <= target[2]
                                            and target[1] <= ring[1] <= ring[3] <= target[3]):
        raise RuntimeError(f'B04 final MP4 click misses rendered button: ring={ring}, target={target}, pixels={pixels}')
    press_frame = start + frame_number / FPS
    evidence_dir = OUT / 'qa-clicks'
    evidence_dir.mkdir(parents=True, exist_ok=True)
    for name, when in (('before', press_frame-.35), ('press', press_frame), ('after', press_frame+.65),
                       ('context-changed', min(evidence['duration_seconds']-.1, press_frame+1.4))):
        png = subprocess.check_output(['ffmpeg', '-v', 'error', '-ss', f'{when:.6f}', '-i', str(video),
                                       '-frames:v', '1', '-f', 'image2pipe', '-vcodec', 'png', '-'])
        (evidence_dir / f'{name}.png').write_bytes(png)
    cursor_x = round(ring[0] + ring[2])
    cursor_y = round(ring[1] + ring[3])
    def pointer_pixels(name):
        raw = subprocess.check_output(['ffmpeg', '-v', 'error', '-i',
                                       str(evidence_dir / f'{name}.png'), '-vf',
                                       f'crop=40:45:{cursor_x-5}:{cursor_y-5},format=rgb24',
                                       '-f', 'rawvideo', '-'])
        return sum(max(raw[i:i+3]) < 80 for i in range(0, len(raw), 3))
    pointer_before = pointer_pixels('press')
    pointer_after = pointer_pixels('context-changed')
    if pointer_before < 30 or pointer_after > 5:
        raise RuntimeError(f'B04 final MP4 cursor did not disappear on context change: '
                           f'press={pointer_before}, after={pointer_after}')
    def gray(name):
        return subprocess.check_output(['ffmpeg', '-v', 'error', '-i',
                                        str(evidence_dir / f'{name}.png'), '-vf',
                                        'scale=240:135:flags=area,format=gray', '-f', 'rawvideo', '-'])
    before, after = gray('before'), gray('after')
    changed = sum(abs(a-b) >= 25 for a,b in zip(before,after)) / len(before)
    if changed < .04:
        raise RuntimeError('B04 final MP4 click did not open a different interface')
    if evidence['choreography']['overlay']['cursorVisible']:
        raise RuntimeError('B04 cursor remained visible after mode context changed')
    return {'status': 'PASS', 'button_box_half_resolution': target,
            'rendered_ring_box_half_resolution': ring, 'ring_pixels': pixels,
            'press_frame_seconds': press_frame,
            'interface_changed_pixel_fraction': changed,
            'pointer_dark_pixels_press': pointer_before,
            'pointer_dark_pixels_after_context_change': pointer_after,
            'cursor_hidden_after_context_change': True,
            'qa_frames': [str(evidence_dir / f'{name}.png') for name in ('before','press','after','context-changed')]}


def verify():
    _, scene, _, metadata, pcm, _ = inputs()
    report = json.loads((OUT / 'report.json').read_text())
    video = OUT / 'B04.mp4'
    if sha(video) != report['video_sha256'] or report['final_wav_sha256'] != metadata['wav_sha256']:
        raise RuntimeError('B04 video or audio source changed')
    with wave.open(str(OUT / 'B04-video-timeline.wav')) as wav:
        timeline = wav.readframes(wav.getnframes())
    lead = round(LEAD * RATE) * 2
    if timeline[:lead] != bytes(lead) or timeline[lead:] != pcm:
        raise RuntimeError('B04 timeline modified speech PCM')
    probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
                                                '-of', 'json', str(video)]))
    streams = {s['codec_type']: s for s in probe['streams']}
    frames = report['scene_frame_counts'][SCENE_ID]
    if (int(streams['video']['nb_frames']) != frames or streams['video']['r_frame_rate'] != '30/1'
            or streams['audio']['codec_name'] != 'aac' or streams['subtitle']['codec_name'] != 'mov_text'):
        raise RuntimeError('B04 MP4 stream format invalid')
    captions = check_embedded_subtitles(video, OUT / 'B04.ru.srt', ' '.join(scene['narration'].split()))
    decoded = subprocess.check_output(['ffmpeg', '-v', 'error', '-xerror', '-i', str(video), '-map', '0:a:0',
                                       '-ac', '1', '-ar', str(RATE), '-c:a', 'pcm_s16le', '-f', 's16le', '-'])
    actual = array.array('h'); actual.frombytes(decoded)
    expected = array.array('h'); expected.frombytes(timeline)
    if abs(len(actual) - len(expected)) > 1024:
        raise RuntimeError('B04 AAC sample count differs from source timeline')
    def correlation(lag):
        dot = aa = bb = 0
        for i in range(lead//2+10000, min(len(actual), len(expected)-max(0,lag)), 40):
            j = i+lag
            if j < 0: continue
            x,y = actual[j],expected[i]
            dot += x*y; aa += x*x; bb += y*y
        return dot/math.sqrt(aa*bb)
    corr = {lag: correlation(lag) for lag in (-32,0,32)}
    if corr[0] < .995 or corr[0] <= max(corr[-32],corr[32]):
        raise RuntimeError('B04 AAC does not align to source WAV')
    evidence = json.loads((OUT / 'scenes' / f'{SCENE_ID}.json').read_text())
    if (evidence['expected_state'] != 'PASS' or evidence['browser_errors']
            or evidence['production_mutation_requests'] or evidence['choreography']['overlay']['violations']):
        raise RuntimeError('B04 browser capture invalid')
    if sha(OUT / 'scenes' / f'{SCENE_ID}.mp4') != json.loads((OUT / 'visual-capture.json').read_text())['scenes'][0]['sha256']:
        raise RuntimeError('B04 source capture changed')
    pointer = pointer_check(video, evidence)
    small = subprocess.check_output(['ffmpeg','-v','error','-i',str(video),'-map','0:v:0',
                                     '-vf','scale=48:27:flags=area,format=gray','-r',str(FPS),'-f','rawvideo','-'])
    pixels = 48*27
    if len(small) != frames*pixels:
        raise RuntimeError('B04 video frame count invalid')
    lum = []; blank = []
    for i in range(frames):
        frame = small[i*pixels:(i+1)*pixels]
        lum.append(sum(frame)/pixels)
        if max(frame)-min(frame)<12 or all(v<10 for v in frame) or all(v>245 for v in frame): blank.append(i)
    flash = [i for i in range(1,frames-1) if abs(lum[i]-lum[i-1])>35 and abs(lum[i]-lum[i+1])>35 and abs(lum[i-1]-lum[i+1])<10]
    if blank or flash:
        raise RuntimeError(f'B04 blank/flash frames: {blank[:5]} / {flash[:5]}')
    result = {'status':'PASS','block_id':'B04','video_sha256':sha(video),
              'final_wav_sha256':metadata['wav_sha256'],'final_pcm_preserved_in_timeline':True,
              'aac_zero_lag_correlation':corr[0],'subtitle_cues':captions['embedded_subtitle_cues'],
              'last_embedded_subtitle_end_seconds':captions['last_embedded_subtitle_end_seconds'],
              'subtitle_matches_canonical_text':True,'video_frames':frames,
              'blank_frames':0,'isolated_flash_frames':0,'rendered_pointer_click':pointer,
              'cursor_violations':0,'new_tts_requests':0,'production_mutation_requests':0}
    write_json(OUT / 'verification.json', result)
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('visual','assemble','verify'))
    args = parser.parse_args()
    print(json.dumps(asyncio.run(visual()) if args.mode == 'visual' else assemble() if args.mode == 'assemble' else verify(), ensure_ascii=False, indent=2))
