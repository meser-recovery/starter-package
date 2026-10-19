#!/usr/bin/env python3
"""Capture and assemble B01 visual revision from immutable approved WAV/alignment."""
from __future__ import annotations

import asyncio
import array
import hashlib
import inspect
import json
import math
import re
import subprocess
import wave
from pathlib import Path

from audio_approval import scene_timing, validate_approval
from browser_capture import capture, visual_hash as browser_visual_hash
from build import demo_server
from modules import sha, write_json
from scenes import login
from validate import ROOT, validate

OUT = ROOT / 'generated/b01-visual-v3-review'
SCENE_IDS = ('B01-001', 'B01-002', 'B01-003')
LEAD_SECONDS = .6
RATE = 44100
FPS = 30
FRAME_BYTES = 1920 * 1080 * 3 // 2
DIAGRAM = ROOT / 'animations/b01-explainer-v3.html'
SITE_SCREENSHOT = ROOT / 'assets/s11/nam-poputi-catalog-2026-10-02.png'
PRO_EDITOR_SCREENSHOT = ROOT / 'assets/s11/logic-pro-main-window-apple.png'

VISUAL_ANCHORS = {
    'meeting': 'Как вам известно',
    'edit': 'Обычно после собрания',
    'trim': 'отредактировать начало и конец',
    'level': 'разницей в громкости',
    'filter': 'убрать мешающие частоты',
    'site': 'сайт «Нам по пути»',
    'difficulty': 'Для человека',
    'announcement': 'Кроме того, эта же запись',
    'ideas': 'выделяет основные мысли',
    'cost': 'При этом анонс-мейкеру',
    'original': 'игнорировать голос оригинала',
    'new': 'Учитывая недостатки',
    'short': 'Для анонс-мейкера появилась',
    'isolate': 'за счёт того',
    'final': 'А для подготовки финальной',
    'tools': 'простые инструменты редактирования',
}


def visual_schedule(scene: dict, timing: dict) -> dict[str, float]:
    text = scene['narration']
    starts = timing['alignment']['character_start_times_seconds']
    schedule = {}
    for key, phrase in VISUAL_ANCHORS.items():
        offset = text.find(phrase)
        if offset < 0 or text.find(phrase, offset + 1) >= 0:
            raise RuntimeError(f'B01 visual anchor must be unique: {phrase}')
        schedule[key] = starts[offset]
    schedule['end'] = timing['duration_seconds']
    return schedule


def source_identity() -> str:
    recipe = '\n'.join(inspect.getsource(fn) for fn in (visual_schedule, capture_spec, prepare, perform))
    return hashlib.sha256(recipe.encode() + DIAGRAM.read_bytes() + SITE_SCREENSHOT.read_bytes() +
                          PRO_EDITOR_SCREENSHOT.read_bytes()).hexdigest()


def inputs() -> tuple[dict, dict, list[dict]]:
    validate()
    spec = json.loads((ROOT / 'tutorial.yaml').read_text())
    approval = validate_approval(spec, 'B01')
    scenes = [s for s in spec['scenes'] if s['id'] in SCENE_IDS]
    if tuple(s['id'] for s in scenes) != SCENE_IDS:
        raise RuntimeError('B01 scene map changed')
    return spec, approval, scenes


def capture_spec(scene: dict) -> dict:
    return {**scene, 'visual': {'type': 'browser', 'goal': scene['goal'],
                               'capture_pipeline_revision': 'b01-semantic-simplification-v3'},
            'initial_state': 'local-public-site' if scene['id'] == 'B01-001' else
                             'conceptual-process' if scene['id'] == 'B01-002' else 'local-service-home',
            'expected_state': 'approved B01 semantic visual', 'assertions': [],
            'fixture_set': 'existing-synthetic-zoom-v1', 'padding': {'head': 0., 'tail': 0.}}


async def prepare(page, scene: dict, base: str) -> None:
    scene_id = scene['id']
    if scene_id == 'B01-002':
        await page.goto(DIAGRAM.as_uri())
        await page.wait_for_function('typeof window.configure === "function" && ["nam-poputi", "logic-pro"].every(id => {const im=document.getElementById(id); return im.complete && im.naturalWidth>0})')
        spec, approval, _ = inputs()
        await page.evaluate('(schedule) => window.configure(schedule)', visual_schedule(scene, scene_timing(spec, scene, approval)))
    else:
        await login(page, base)
        if scene_id == 'B01-001':
            await page.goto((ROOT.parent / 'index.html').as_uri())
            # The real public link points to production. Redirect this capture-only
            # click to the isolated, in-memory mirror of the same service page.
            await page.locator('a.service-link').evaluate('(el,url)=>el.href=url', base + '/')
            await page.evaluate('''() => {
              const title=document.createElement('div'); title.id='s11-b01-title';
              title.textContent='01  /  Вступление';
              title.style='position:fixed;left:78px;top:124px;z-index:2147483000;'+
                'color:#fff;font:700 40px/1.1 Arial,sans-serif;text-shadow:0 2px 14px #102a4788;'+
                'transition:opacity .5s;pointer-events:none';document.body.append(title);
            }''')
        else:
            await page.goto(base + '/')
            await page.get_by_role('heading', name='Служебная страница').wait_for()
    await page.screenshot()  # Flush the intended ready frame before CDP capture.


async def perform(page, scene: dict, base: str, cue) -> None:
    director = page.tutorial
    if scene['id'] == 'B01-001':
        await asyncio.sleep(3.8)
        await page.evaluate("document.getElementById('s11-b01-title').style.opacity='0'")
        await cue('в разделе «Для служащих»')
        await page.locator('a.service-link').click()
        await page.get_by_role('heading', name='Служебная страница').wait_for()
        # Same-tab navigation can leave the CDP screencast showing the old
        # compositor surface until another change. Force the ready UI frame now.
        await page.raw.screenshot()
        await page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
        await cue('Google Диск')
        await director.aim(page.raw.locator('a[href="Google-Drive.html"]'))
        await cue('Google Календарь')
        await director.aim(page.raw.locator('a[href="Calendar.html"]'))
        await cue('Теперь к ним добавились')
        await director.aim(page.raw.locator('a[href="Audio-Editor.html"]'))
        await cue('с записью и обработкой')
        await director.wait_pending()
        await page.evaluate("window.__s11Capture.hide('context-change')")
    elif scene['id'] == 'B01-002':
        await page.evaluate('window.startAnimation()')
        for phrase in VISUAL_ANCHORS.values():
            await cue(phrase)
            await director.wait_pending()
    elif scene['id'] == 'B01-003':
        # Arrive on the real menu item as the section is introduced, then open
        # it while its name is spoken. The generic click waits for the entire
        # phrase to finish, which leaves almost no time to see the editor.
        await cue('в разделе')
        target = page.raw.locator('a[href="Audio-Editor.html"]')
        await director.aim(target)
        await cue('Редактирование аудио')
        await director.wait_pending()
        await director.before_action()
        press = director.now()
        await page.raw.mouse.down()
        await asyncio.sleep(.13)
        await page.evaluate("window.__s11Capture.hide('navigation-action')")
        await page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
        await asyncio.sleep(.04)
        director.events.append({'type': 'navigation-feedback', 'seconds': director.now(),
                                'press_seconds': press, 'cursor_hidden_before_transition': True})
        director.ready = False
        async with page.raw.expect_navigation(wait_until='domcontentloaded'):
            await page.raw.mouse.up()
        director.events.append({'type': 'click', 'seconds': press, 'target': str(target), 'ripple': True})
        await director.after_action()
        await page.get_by_role('heading', name='Редактирование аудио').wait_for()
        await page.raw.screenshot()
        await page.evaluate('() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))')
        await page.evaluate("window.__s11Capture.hide('context-change')")
    else:
        raise RuntimeError('B01 capture contains an unexpected scene')


async def visual(only: str | None = None) -> dict:
    if (ROOT / 'approvals/B01-block.json').exists():
        raise RuntimeError('B01 complete block is approved and immutable')
    spec, approval, scenes = inputs()
    scene_dir = OUT / 'scenes'
    scene_dir.mkdir(parents=True, exist_ok=True)
    previous_report = OUT / 'visual-capture.json'
    old = json.loads(previous_report.read_text()) if previous_report.is_file() else None
    if old and old['approved_mp3_sha256'] != approval['record']['approved_take']['mp3_sha256']:
        raise RuntimeError('B01 visual review belongs to another audio take')
    rows_by_id = {r['scene_id']: r for r in old['scenes']} if old else {}
    with demo_server(None) as base:
        for scene in scenes:
            if only and scene['id'] != only:
                continue
            timing = scene_timing(spec, scene, approval)
            timing.update(visual_lead_seconds=LEAD_SECONDS if scene['id'] == 'B01-001' else 0.,
                          visual_source_sha256=source_identity(), strict_choreography=False)
            destination = scene_dir / f"{scene['id']}.mp4"
            evidence = await capture(capture_spec(scene), spec['narration'], base,
                                     timing=timing, destination=destination,
                                     prepare_scene=prepare, perform_scene=perform)
            events = evidence['choreography']['events']
            if max((e['seconds'] for e in events), default=0) > timing['duration_seconds'] + timing['visual_lead_seconds'] + .1:
                raise RuntimeError(f"visual choreography exceeds approved scene duration: {scene['id']}")
            rows_by_id[scene['id']] = {'scene_id': scene['id'], 'visual': str(destination),
                                      'sha256': sha(destination),
                                      'duration_seconds': evidence['duration_seconds'],
                                      'cue_errors_seconds': [c['actual_seconds']-c['target_seconds'] for c in evidence['alignment_action_cues']],
                                      'production_mutation_requests': evidence['production_mutation_requests']}
            print(json.dumps(rows_by_id[scene['id']], ensure_ascii=False), flush=True)
    if set(rows_by_id) != set(SCENE_IDS):
        raise RuntimeError('all three B01 visual scenes must be present before review')
    rows = [rows_by_id[sid] for sid in SCENE_IDS]
    report = {'status': 'PASS', 'block_id': 'B01', 'approved_mp3_sha256': approval['record']['approved_take']['mp3_sha256'],
              'tts_requests': 0, 'scenes': rows}
    write_json(OUT / 'visual-capture.json', report)
    return report


def timestamp(seconds: float, *, vtt: bool = False) -> str:
    millis = round(seconds * 1000)
    hours, rem = divmod(millis, 3600000)
    minutes, rem = divmod(rem, 60000)
    secs, ms = divmod(rem, 1000)
    return f'{hours:02d}:{minutes:02d}:{secs:02d}{"." if vtt else ","}{ms:03d}'


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
                    raise RuntimeError('empty B01 subtitle timing')
                cues.append((start, end, phrase))
                begin = i+1
    if any(cues[i][0] < cues[i-1][1]-.01 for i in range(1, len(cues))):
        raise RuntimeError('B01 subtitle overlap')
    if any('[' in text or ']' in text for _, _, text in cues):
        raise RuntimeError('TTS tags leaked into B01 subtitles')
    for suffix in ('srt', 'vtt'):
        vtt = suffix == 'vtt'
        body = ('WEBVTT\n\n' if vtt else '') + '\n\n'.join(
            ('' if vtt else f'{i}\n') + f'{timestamp(a,vtt=vtt)} --> {timestamp(b,vtt=vtt)}\n{text}'
            for i, (a, b, text) in enumerate(cues, 1)) + '\n'
        (OUT / f'B01.ru.{suffix}').write_text(body)
    return cues


def parse_srt(body: str) -> list[tuple[float, float, str]]:
    def seconds(value: str) -> float:
        hours, minutes, rest = value.split(':')
        return int(hours)*3600 + int(minutes)*60 + float(rest.replace(',', '.'))

    cues = []
    for block in re.split(r'\n\s*\n', body.strip()):
        lines = block.splitlines()
        if lines[0].isdigit():
            lines = lines[1:]
        match = re.fullmatch(r'(\d\d:\d\d:\d\d,\d{3}) --> (\d\d:\d\d:\d\d,\d{3})', lines[0])
        if not match or len(lines) < 2:
            raise RuntimeError('invalid extracted B01 subtitle cue')
        cues.append((seconds(match[1]), seconds(match[2]), ' '.join(' '.join(lines[1:]).split())))
    return cues


def check_embedded_subtitles(video: Path, source_srt: Path, canonical_text: str) -> dict:
    """Compare every subtitle decoded from the delivered MP4 with alignment SRT."""
    source = parse_srt(source_srt.read_text())
    embedded = parse_srt(subprocess.check_output([
        'ffmpeg', '-v', 'error', '-xerror', '-i', str(video), '-map', '0:s:0',
        '-f', 'srt', '-'], text=True))
    if len(embedded) != len(source):
        raise RuntimeError(f'B01 MP4 embedded subtitles incomplete: {len(embedded)}/{len(source)} cues')
    for index, (actual, expected) in enumerate(zip(embedded, source), 1):
        if actual[2] != expected[2] or abs(actual[0]-expected[0]) > .003 or abs(actual[1]-expected[1]) > .003:
            raise RuntimeError(f'B01 MP4 embedded subtitle cue {index} differs from alignment SRT')
    if ' '.join(cue[2] for cue in embedded) != canonical_text or any('[' in cue[2] or ']' in cue[2] for cue in embedded):
        raise RuntimeError('B01 MP4 embedded subtitles differ from canonical narration')
    return {'embedded_subtitle_cues': len(embedded),
            'last_embedded_subtitle_end_seconds': embedded[-1][1]}


def assemble() -> dict:
    if (ROOT / 'approvals/B01-block.json').exists():
        raise RuntimeError('B01 complete block is approved and immutable')
    spec, approval, scenes = inputs()
    if not (OUT / 'visual-capture.json').is_file():
        raise RuntimeError('B01 visual capture missing; no generation fallback')
    capture_report = json.loads((OUT / 'visual-capture.json').read_text())
    if capture_report['approved_mp3_sha256'] != approval['record']['approved_take']['mp3_sha256']:
        raise RuntimeError('B01 visual capture is tied to another audio take')
    timings = [scene_timing(spec, scene, approval) for scene in scenes]
    cues = subtitles(scenes, timings)
    with wave.open(str(approval['wav_path'])) as approved:
        approved_pcm = approved.readframes(approved.getnframes())
    lead_samples = round(LEAD_SECONDS * RATE)
    timeline = OUT / 'B01-video-timeline.wav'
    with wave.open(str(timeline), 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(RATE)
        wav.writeframes(bytes(lead_samples*2) + approved_pcm)
    with wave.open(str(timeline)) as wav:
        data = wav.readframes(wav.getnframes())
        if data[:lead_samples*2] != bytes(lead_samples*2) or data[lead_samples*2:] != approved_pcm:
            raise RuntimeError('B01 video timeline changed approved speech samples')
    audio_duration = LEAD_SECONDS + approval['wav_duration_seconds']
    # The provider alignment extends a few milliseconds past decoded PCM.
    # Keep one complete visual frame through the final subtitle, without
    # changing the approved WAV or inserting silence inside the block.
    visual_duration = math.ceil(max(audio_duration, cues[-1][1]) * FPS) / FPS
    bounds = [0, LEAD_SECONDS + timings[1]['range_start_seconds'],
              LEAD_SECONDS + timings[2]['range_start_seconds'], visual_duration]
    counts = [round(bounds[i+1]*FPS)-round(bounds[i]*FPS) for i in range(3)]
    if min(counts) <= 0:
        raise RuntimeError('invalid B01 scene frame count')
    final = OUT / 'B01.mp4'
    candidate = OUT / 'B01.tmp.mp4'
    command = ['ffmpeg', '-y', '-v', 'error', '-f', 'rawvideo', '-pixel_format', 'yuv420p',
               '-video_size', '1920x1080', '-framerate', str(FPS), '-i', 'pipe:0',
               '-i', str(timeline), '-i', str(OUT / 'B01.ru.srt'),
               '-map', '0:v:0', '-map', '1:a:0', '-map', '2:s:0',
               '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21', '-pix_fmt', 'yuv420p',
               '-c:a', 'aac', '-b:a', '192k', '-c:s', 'mov_text',
               '-metadata:s:s:0', 'language=rus', '-frames:v', str(sum(counts)),
               '-movflags', '+faststart', str(candidate)]
    encoder = subprocess.Popen(command, stdin=subprocess.PIPE,
                               stderr=(OUT / 'encode.log').open('wb'))
    try:
        for scene, count in zip(scenes, counts):
            path = OUT / 'scenes' / f"{scene['id']}.mp4"
            if not path.is_file():
                raise RuntimeError('B01 scene capture missing: ' + scene['id'])
            decoder = subprocess.Popen(['ffmpeg', '-v', 'error', '-xerror', '-i', str(path), '-an',
                                        '-vf', 'scale=1920:1080,fps=30,trim=start_frame=1,'
                                               'tpad=start=1:start_mode=clone,setpts=N/(30*TB),'
                                               'tpad=stop_mode=clone:stop=300',
                                        '-r', str(FPS), '-frames:v', str(count), '-pix_fmt', 'yuv420p',
                                        '-f', 'rawvideo', 'pipe:1'], stdout=subprocess.PIPE)
            copied = 0
            try:
                while chunk := decoder.stdout.read(1024*1024):
                    encoder.stdin.write(chunk)
                    copied += len(chunk)
            finally:
                decoder.stdout.close()
            if decoder.wait() or copied != count * FRAME_BYTES:
                raise RuntimeError('B01 visual frame count mismatch: ' + scene['id'])
        encoder.stdin.close()
        if encoder.wait():
            raise RuntimeError('B01 MP4 encode failed; see encode.log')
    finally:
        if encoder.poll() is None:
            encoder.kill(); encoder.wait()
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(candidate), '-f', 'null', '-'],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    expected_text = ' '.join(' '.join(s['narration'].split()) for s in scenes)
    subtitle_check = check_embedded_subtitles(candidate, OUT / 'B01.ru.srt', expected_text)
    candidate.replace(final)
    info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
                                               '-show_format', '-of', 'json', str(final)]))
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    audio = next(s for s in info['streams'] if s['codec_type'] == 'audio')
    if (video['codec_name'], video['width'], video['height']) != ('h264', 1920, 1080) or audio['codec_name'] != 'aac':
        raise RuntimeError('B01 output stream format invalid')
    if abs(float(info['format']['duration']) - visual_duration) > .08:
        raise RuntimeError('B01 video/audio duration mismatch')
    report = {'status': 'READY FOR B01 BLOCK REVIEW', 'block_id': 'B01',
              'approved_mp3_sha256': approval['record']['approved_take']['mp3_sha256'],
              'approved_wav_sha256': approval['record']['approved_take']['wav_sha256'],
              'approved_pcm_sha256': approval['record']['approved_take']['pcm_sha256'],
              'approved_alignment_sha256': approval['record']['approved_take']['alignment_sha256'],
              'audio_source': str(approval['wav_path']), 'video_audio_timeline': str(timeline),
              'video_audio_timeline_preserves_approved_pcm': True,
              'video_audio_lead_seconds': LEAD_SECONDS, 'internal_audio_silence_added_seconds': 0,
              'visual_tail_seconds': visual_duration - audio_duration,
              'video': str(final), 'video_sha256': sha(final),
              'duration_seconds': float(info['format']['duration']),
              'scene_frame_counts': dict(zip(SCENE_IDS, counts)), 'subtitle_cues': len(cues),
              **subtitle_check,
              'tts_requests': 0, 'production_mutation_requests': 0,
              'capture_cue_errors_seconds': {r['scene_id']: r['cue_errors_seconds'] for r in capture_report['scenes']}}
    write_json(OUT / 'report.json', report)
    (OUT / 'index.html').write_text('''<!doctype html>
<html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>B01 · Вступление · review</title>
<style>body{margin:0;background:#0b2238;color:#eaf5ff;font:18px/1.45 system-ui,sans-serif}
main{max-width:1200px;margin:auto;padding:24px}h1{margin:0 0 6px;font-size:32px}p{color:#bdd7ea}
video{display:block;width:100%;aspect-ratio:16/9;background:#071522;border-radius:12px;margin:22px 0}
button,a{color:#eaf5ff;background:#245c87;border:1px solid #5799c8;border-radius:8px;padding:10px 14px;margin:0 8px 8px 0;font:inherit;cursor:pointer}
a{display:inline-block;text-decoration:none}button:hover,a:hover{background:#3179ad}</style>
<main><h1>B01 · Вступление</h1><p>Готовый блок для просмотра · озвучка AUDIO_APPROVED · 0 новых TTS-запросов</p>
<video id="review" controls playsinline preload="metadata"><source src="B01.mp4" type="video/mp4">
<track kind="subtitles" src="B01.ru.vtt" srclang="ru" label="Русские субтитры"></video>
<nav aria-label="Сцены"><button data-seek="0">001 · Мэсэр</button><button data-seek="29.88">002 · Задачи записи</button>
<button data-seek="117.97">003 · Редактор</button></nav>
<a href="B01.mp4" download>Скачать MP4</a><a href="B01.ru.srt" download>Скачать субтитры</a>
<script>document.querySelectorAll('[data-seek]').forEach(b=>b.addEventListener('click',()=>{
const v=document.getElementById('review');v.currentTime=Number(b.dataset.seek);v.play()}));</script></main></html>
''')
    return report


def verify() -> dict:
    spec, approval, scenes = inputs()
    report = json.loads((OUT / 'report.json').read_text())
    video_path = Path(report['video'])
    if sha(video_path) != report['video_sha256']:
        raise RuntimeError('B01 review MP4 changed after assembly')
    if report['approved_wav_sha256'] != approval['record']['approved_take']['wav_sha256']:
        raise RuntimeError('B01 review MP4 does not refer to approved WAV')
    with wave.open(str(approval['wav_path'])) as wav:
        approved_pcm = wav.readframes(wav.getnframes())
    with wave.open(report['video_audio_timeline']) as wav:
        timeline_pcm = wav.readframes(wav.getnframes())
    lead = round(report['video_audio_lead_seconds']*RATE)*2
    if timeline_pcm[:lead] != bytes(lead) or timeline_pcm[lead:] != approved_pcm:
        raise RuntimeError('B01 video timeline does not preserve approved PCM exactly')
    info = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
                                               '-show_format', '-of', 'json', str(video_path)]))
    streams = {s['codec_type']: s for s in info['streams']}
    frames = sum(report['scene_frame_counts'].values())
    if int(streams['video']['nb_frames']) != frames or streams['video']['r_frame_rate'] != '30/1':
        raise RuntimeError('B01 video frame timing changed')
    if streams['audio']['codec_name'] != 'aac' or streams['subtitle']['codec_name'] != 'mov_text':
        raise RuntimeError('B01 audio/subtitle streams invalid')
    expected_text = ' '.join(' '.join(s['narration'].split()) for s in scenes)
    subtitle_check = check_embedded_subtitles(video_path, OUT / 'B01.ru.srt', expected_text)
    decoded = subprocess.check_output(['ffmpeg', '-v', 'error', '-xerror', '-i', str(video_path),
                                       '-map', '0:a:0', '-ac', '1', '-ar', str(RATE),
                                       '-c:a', 'pcm_s16le', '-f', 's16le', '-'])
    actual_samples = array.array('h'); actual_samples.frombytes(decoded)
    expected_samples = array.array('h'); expected_samples.frombytes(timeline_pcm)
    if abs(len(actual_samples)-len(expected_samples)) > 1024:
        raise RuntimeError('B01 AAC audio sample count differs from approved timeline')
    def correlation(lag: int) -> float:
        dot = aa = bb = 0
        for i in range(lead//2+10000, min(len(expected_samples),len(actual_samples)-max(0,lag)), 100):
            j = i+lag
            if j < 0:
                continue
            a,b = actual_samples[j],expected_samples[i]
            dot += a*b; aa += a*a; bb += b*b
        return dot/math.sqrt(aa*bb)
    correlations = {lag: correlation(lag) for lag in (-32,0,32)}
    if correlations[0] < .995 or correlations[0] <= max(correlations[-32],correlations[32]):
        raise RuntimeError('B01 AAC audio is not aligned with approved WAV')
    small = subprocess.check_output(['ffmpeg', '-v', 'error', '-xerror', '-i', str(video_path),
                                     '-map', '0:v:0', '-vf', 'scale=48:27:flags=area,format=gray',
                                     '-r', str(FPS), '-f', 'rawvideo', '-'])
    pixels = 48*27
    if len(small) != frames*pixels:
        raise RuntimeError('B01 decoded visual frame count invalid')
    blank = []
    luminance = []
    for i in range(frames):
        frame = small[i*pixels:(i+1)*pixels]
        luminance.append(sum(frame)/pixels)
        if max(frame)-min(frame) < 12 or all(x < 10 for x in frame) or all(x > 245 for x in frame):
            blank.append(i)
    if blank:
        raise RuntimeError(f'B01 contains blank or near-uniform visual frames: {blank[:8]}')
    isolated_flashes = [i for i in range(1,frames-1)
                        if abs(luminance[i]-luminance[i-1]) > 35
                        and abs(luminance[i]-luminance[i+1]) > 35
                        and abs(luminance[i-1]-luminance[i+1]) < 10]
    if isolated_flashes:
        raise RuntimeError(f'B01 contains isolated brightness flashes: {isolated_flashes[:8]}')
    scene3_start = sum(report['scene_frame_counts'][sid] for sid in SCENE_IDS[:2])
    editor_entry = next((i for i in range(scene3_start+1, frames)
                         if luminance[i]-luminance[i-1] > 50), None)
    if editor_entry is None:
        raise RuntimeError('B01 editor page never appears in the final MP4')
    editor_entry_seconds = editor_entry / FPS
    editor_inspection_seconds = frames / FPS - editor_entry_seconds
    if editor_entry_seconds > 121.6 or editor_inspection_seconds < 2.5:
        raise RuntimeError('B01 editor appears too late for final-phrase inspection')
    errors = []
    capture_rows = {row['scene_id']: row for row in json.loads((OUT / 'visual-capture.json').read_text())['scenes']}
    for scene in scenes:
        if capture_rows[scene['id']].get('sha256') != sha(OUT / 'scenes' / f"{scene['id']}.mp4"):
            raise RuntimeError('B01 visual scene file changed: ' + scene['id'])
        meta = json.loads((OUT / 'scenes' / f"{scene['id']}.json").read_text())
        timing = scene_timing(spec, scene, approval)
        visual_inputs = {'visual_lead_seconds': LEAD_SECONDS if scene['id'] == 'B01-001' else 0.,
                         'visual_source_sha256': source_identity(), 'strict_choreography': False}
        expected_visual_hash = hashlib.sha256((browser_visual_hash(capture_spec(scene)) +
            timing['timing_identity'] + json.dumps(visual_inputs, sort_keys=True)).encode()).hexdigest()
        if meta['visual_hash'] != expected_visual_hash:
            raise RuntimeError('B01 visual capture is stale: ' + scene['id'])
        if meta['expected_state'] != 'PASS' or meta['browser_errors'] or meta['production_mutation_requests']:
            raise RuntimeError('B01 local browser capture did not pass')
        if meta['choreography']['overlay']['violations']:
            raise RuntimeError('B01 cursor or highlight geometry violation')
        if scene['id'] == 'B01-003':
            events = meta['choreography']['overlay']['events']
            hides = [i for i, event in enumerate(events)
                     if event['type'] == 'cursor-hide' and event.get('reason') == 'navigation-action']
            if (len(hides) != 1 or any(event['type'] == 'cursor-show' for event in events[hides[0]+1:])
                    or meta['choreography']['overlay']['cursorVisible']):
                raise RuntimeError('B01 cursor must stay hidden after editor navigation')
        errors.extend(abs(c['error_seconds']) for c in meta['alignment_action_cues'] if 'error_seconds' in c)
        errors.extend(abs(c['actual_seconds']-c['target_seconds']) for c in meta['alignment_action_cues']
                      if 'error_seconds' not in c)
    if max(errors, default=0) > .18:
        raise RuntimeError('B01 capture cue drift exceeds 180 ms')
    result = {'status': 'PASS', 'block_id': 'B01', 'video_sha256': report['video_sha256'],
              'approved_mp3_sha256': approval['record']['approved_take']['mp3_sha256'],
              'approved_wav_sha256': approval['record']['approved_take']['wav_sha256'],
              'approved_pcm_preserved_in_timeline': True,
              'aac_zero_lag_correlation': correlations[0],
              'aac_shifted_correlations': correlations,
              'subtitle_cues': subtitle_check['embedded_subtitle_cues'],
              'last_embedded_subtitle_end_seconds': subtitle_check['last_embedded_subtitle_end_seconds'],
              'subtitle_matches_canonical_text': True,
              'video_frames': frames, 'blank_frames': len(blank),
              'isolated_flash_frames': len(isolated_flashes),
              'editor_first_frame_seconds': editor_entry_seconds,
              'editor_inspection_seconds': editor_inspection_seconds,
              'max_visual_cue_error_seconds': max(errors, default=0),
              'new_tts_requests': 0, 'production_mutation_requests': 0}
    write_json(OUT / 'verification.json', result)
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('visual', 'assemble', 'verify'))
    parser.add_argument('--scene', choices=SCENE_IDS, help='recapture one B01 technical scene')
    args = parser.parse_args()
    result = asyncio.run(visual(args.scene)) if args.mode == 'visual' else assemble() if args.mode == 'assemble' else verify()
    print(json.dumps(result, ensure_ascii=False, indent=2))
