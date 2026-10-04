#!/usr/bin/env python3
"""Visual-only review of the one newly synthesized B01 and B02 takes.

The older approved audio, MP4s, and approval records remain in their original
directories. This module reads the new one-request provider responses from v3.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import wave
from pathlib import Path

import b01_block
import b02_block
from modules import cached, sha, write_json
from validate import ROOT, validate

SOURCE = ROOT / 'generated/narration-blocks-v3'
OUT = {'B01': ROOT / 'generated/b01-reopen-review',
       'B02': ROOT / 'generated/b02-reopen-review'}


def inputs(block: str):
    validate()
    spec = json.loads((ROOT / 'tutorial.yaml').read_text())
    module = next(item for item in spec['narration_modules'] if item['id'] == block)
    hit = cached(spec, module, root=SOURCE)
    if not hit or hit['metadata']['tts_requests_for_this_take'] != 1:
        raise RuntimeError(f'{block} single-request provider take missing or stale')
    folder = SOURCE / block
    mp3, wav, timing_path = folder / 'narration.mp3', folder / 'narration.wav', folder / 'timing.json'
    if not wav.exists():
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-xerror', '-i', str(mp3),
                        '-map', '0:a:0', '-ac', '1', '-ar', '44100', '-c:a', 'pcm_s16le', str(wav)],
                       check=True)
    with wave.open(str(wav)) as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, 44100):
            raise RuntimeError(f'{block} decoded WAV format invalid')
        pcm = source.readframes(source.getnframes())
        duration = source.getnframes() / 44100
    if hashlib.sha256(pcm).hexdigest() != hashlib.sha256(subprocess.check_output(
            ['ffmpeg', '-v', 'error', '-xerror', '-i', str(mp3), '-map', '0:a:0',
             '-f', 's16le', '-ac', '1', '-ar', '44100', 'pipe:1'])).hexdigest():
        raise RuntimeError(f'{block} WAV differs from provider MP3 decode')
    takes = {'status': 'NEW_TAKE_PENDING_AUDIO_AND_BLOCK_REVIEW', 'block_id': block,
             'provider_mp3': str(mp3), 'provider_mp3_sha256': sha(mp3),
             'wav': str(wav), 'wav_sha256': sha(wav),
             'pcm_sha256': hashlib.sha256(pcm).hexdigest(), 'pcm_samples': len(pcm)//2,
             'alignment': str(timing_path), 'alignment_sha256': sha(timing_path),
             'canonical_text_sha256': hashlib.sha256(module['narration'].encode()).hexdigest(),
             'duration_seconds': hit['timing']['duration_seconds'],
             'one_continuous_tts_request': True, 'silence_insertions': [],
             'speech_speed_processing': False}
    out = OUT[block]; out.mkdir(parents=True, exist_ok=True)
    record = out / 'new-audio.json'
    if record.exists() and json.loads(record.read_text()) != takes:
        raise RuntimeError(f'{block} prepared take changed')
    write_json(record, takes)
    scenes = [scene for scene in spec['scenes'] if scene['block_id'] == block]
    return spec, module, hit['timing'], duration, wav, takes, scenes


def b01_inputs():
    spec, module, timing, duration, wav, take, scenes = inputs('B01')
    approved = {'mp3_sha256': take['provider_mp3_sha256'],
                'wav_sha256': take['wav_sha256'], 'pcm_sha256': take['pcm_sha256'],
                'alignment_sha256': take['alignment_sha256']}
    proxy = {'record': {'approved_take': approved}, 'timing': timing,
             'wav_path': wav, 'wav_duration_seconds': duration}
    return spec, proxy, scenes


def b02_inputs():
    spec, module, timing, duration, wav, take, scenes = inputs('B02')
    metadata = {'source_mp3_sha256': take['provider_mp3_sha256'],
                'mp3_sha256': take['provider_mp3_sha256'], 'wav_sha256': take['wav_sha256'],
                'final_pcm_sha256': take['pcm_sha256'],
                'timing_sha256': take['alignment_sha256'], 'events': []}
    audio = {'module': module, 'metadata': metadata, 'timing': timing,
             'wav_path': wav, 'wav_duration_seconds': duration}
    return spec, audio, scenes


ANCHORS = {
    'B02-004': {'storage': 'Оба этих варианта', 'computer': 'компьютер',
                'cloud': 'облако', 'common': 'В первом', 'separate': 'Во втором'},
    'B02-005': {'translator': 'Например', 'gaps': 'Пока говорит',
                'shorten': 'Их можно сократить'},
    'B02-006': {'volume': 'У одного', 'noise': 'На одной дорожке',
                'shared': 'Когда все'},
    'B02-007': {'improve': 'улучшить звук', 'level': 'выровнять громкость',
                'noise': 'убрать помеху', 'exclude': 'Если в запись',
                'global': 'Если проблема', 'summary': 'Так раздельная'},
}


async def prepare_b02(page, scene: dict, base: str) -> None:
    await page.goto(b02_block.DIAGRAM.as_uri())
    await page.wait_for_function('typeof window.configure === "function" && window.assetsLoaded === true')
    spec, audio, _ = b02_inputs()
    timing = b02_block.scene_timing(spec, scene, audio)
    text = scene['narration']; starts = timing['alignment']['character_start_times_seconds']
    anchors = {}
    for key, phrase in ANCHORS[scene['id']].items():
        offset = text.find(phrase)
        if offset < 0 or text.find(phrase, offset+1) >= 0:
            raise RuntimeError(f'{scene["id"]} visual phrase is not unique: {phrase}')
        anchors[key] = starts[offset]
    await page.evaluate('(args) => window.configure(args.id,args.duration,args.anchors)',
                        {'id': scene['id'], 'duration': timing['duration_seconds'], 'anchors': anchors})
    await page.screenshot()


def configure(block: str):
    inputs(block)
    if block == 'B01':
        b01_block.OUT = OUT[block]
        b01_block.DIAGRAM = ROOT / 'animations/b01-explainer-v4.html'
        b01_block.inputs = b01_inputs
        return b01_block
    b02_block.OUT = OUT[block]
    b02_block.DIAGRAM = ROOT / 'animations/b02-tracks-v4.html'
    b02_block.PRESERVED_SCENES = {}
    b02_block.PRESERVED_SUBTITLES = {}
    b02_block.inputs = b02_inputs
    b02_block.prepare = prepare_b02
    return b02_block


def figure_motion() -> dict:
    """Measure the two outer portraits in delivered B01 frames at scene 002 entry."""
    report = json.loads((OUT['B01'] / 'report.json').read_text())
    first = report['scene_frame_counts']['B01-001']
    raw = subprocess.check_output([
        'ffmpeg', '-v', 'error', '-xerror', '-i', str(OUT['B01'] / 'B01.mp4'),
        '-vf', f'select=between(n\\,{first}\\,{first+18}),crop=1920:410:0:200,'
               'scale=480:102:flags=area,format=rgb24',
        '-vsync', '0', '-f', 'rawvideo', 'pipe:1'])
    frame_bytes = 480*102*3
    if len(raw) != 19*frame_bytes:
        raise RuntimeError('B01 figure motion sample is incomplete')
    positions = []
    for frame in range(19):
        rgb = raw[frame*frame_bytes:(frame+1)*frame_bytes]
        blue = []; gold = []
        for pixel in range(480*102):
            r, g, b = rgb[pixel*3:pixel*3+3]
            x = (pixel % 480)*4
            if b > 145 and b > g*1.2 and g > 60 and r < 100:
                blue.append(x)
            if r > 115 and 60 < g < 170 and b < 105:
                gold.append(x)
        if not blue or not gold:
            raise RuntimeError('B01 figures absent at scene entry')
        positions.append({'frame': first+frame, 'blue_x': round(sum(blue)/len(blue), 1),
                          'gold_x': round(sum(gold)/len(gold), 1)})
    blue = [point['blue_x'] for point in positions]
    gold = [point['gold_x'] for point in positions]
    if not all(blue[i]-blue[i+1] > 4 and gold[i+1]-gold[i] > 4 for i in range(2, 18)):
        raise RuntimeError('B01 figures pause or reverse after appearing')
    if blue[2]-blue[18] < 100 or gold[18]-gold[2] < 100:
        raise RuntimeError('B01 figure separation is too small')
    result = {'status': 'PASS', 'source': 'decoded final B01 MP4 frames',
              'first_scene_002_frame': first, 'first_moving_frame': first+2,
              'movement_started_after_seconds': 2/30,
              'positions': positions}
    write_json(OUT['B01'] / 'figure-motion.json', result)
    return result


def run(block: str, mode: str):
    module = configure(block)
    if mode == 'prepare':
        return json.loads((OUT[block] / 'new-audio.json').read_text())
    if mode == 'visual':
        return asyncio.run(module.visual())
    if mode == 'assemble':
        result = module.assemble()
        result['new_tts_requests_for_version'] = 1
        result['prior_approved_candidate_preserved'] = True
        write_json(OUT[block] / 'report.json', result)
        html = (OUT[block] / 'index.html').read_text()
        html = html.replace('озвучка AUDIO_APPROVED · 0 новых TTS-запросов',
                            'новый дубль озвучки · на повторное утверждение')
        html = html.replace('B01 BLOCK_APPROVED · 0 новых TTS-запросов',
                            'новый дубль озвучки · на повторное утверждение')
        if block == 'B01':
            scenes = result['scene_frame_counts']
            second = scenes['B01-001']/30
            third = (scenes['B01-001']+scenes['B01-002'])/30
            html = html.replace('data-seek="29.88"', f'data-seek="{second:.2f}"')
            html = html.replace('data-seek="117.97"', f'data-seek="{third:.2f}"')
        (OUT[block] / 'index.html').write_text(html)
        return result
    if mode == 'verify':
        result = module.verify()
        if block == 'B01':
            result['figure_motion'] = figure_motion()['status']
            write_json(OUT[block] / 'verification.json', result)
        return result
    raise ValueError(mode)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('block', choices=('B01', 'B02'))
    parser.add_argument('mode', choices=('prepare', 'visual', 'assemble', 'verify'))
    args = parser.parse_args()
    print(json.dumps(run(args.block, args.mode), ensure_ascii=False, indent=2))
