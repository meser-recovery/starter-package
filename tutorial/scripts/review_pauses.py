#!/usr/bin/env python3
"""Apply a manually justified, block-specific silence map to one continuous take."""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import shutil
import subprocess
import sys
import wave
from pathlib import Path

from audio_approval import approved_path
from modules import cached, map_timing, request_text_and_indices, write_json
from narration import probe_duration
from validate import ROOT, validate

QUIET_PEAK = 32  # approximately -60 dBFS in s16 PCM


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def quiet_run(samples: array.array, begin: int, end: int) -> tuple[int, int]:
    current = None
    best = (begin, begin)
    for i in range(begin, end):
        if abs(samples[i]) <= QUIET_PEAK:
            if current is None:
                current = i
        elif current is not None:
            if i-current > best[1]-best[0]:
                best = (current, i)
            current = None
    if current is not None and end-current > best[1]-best[0]:
        best = (current, end)
    return best


def apply(map_path: Path) -> dict:
    validate()
    spec = json.loads((ROOT / 'tutorial.yaml').read_text())
    review = json.loads(map_path.read_text())
    block_id = review['block_id']
    if block_id == 'B01' or approved_path(block_id).exists():
        raise RuntimeError('approved B01 or another approved audio take cannot be edited')
    module = next(m for m in spec['narration_modules'] if m['id'] == block_id)
    if review['status'] != 'SEMANTIC_REVIEWED' or not module.get('tts', {}).get('semantic_reviewed'):
        raise RuntimeError('manual semantic review is required before silence processing')
    variant = review['variant_id']
    if not variant.isascii() or not variant.replace('-', '').isalnum() or len(variant) > 36:
        raise RuntimeError('invalid review variant ID')
    requested = review['insertions']
    offsets = [r['after_offset'] for r in requested]
    if offsets != sorted(set(offsets)):
        raise RuntimeError('insertions must be in unique canonical offset order')
    reasons = {p['after_offset']: p['reason'] for p in module['tts']['pauses']}
    if any(offset not in reasons or row['reason'] != reasons[offset]
           or not 0 < row['target_total_seconds'] <= 3 for row, offset in zip(requested, offsets)):
        raise RuntimeError('silence request differs from the reviewed semantic map')
    hit = cached(spec, module)
    if not hit:
        raise RuntimeError('one continuous original TTS take and alignment are required')
    folder = Path(hit['folder'])
    prefix = f'{block_id}-{variant}'
    outputs = [folder / f'{prefix}{suffix}' for suffix in
               ('.wav', '.mp3', '-timing.json', '-source-timing.json', '-metadata.json')]
    if any(path.exists() for path in outputs):
        raise RuntimeError('review variant already exists; refusing to overwrite')
    source_mp3 = folder / 'narration.mp3'
    stream = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'a:0',
                                                 '-show_entries', 'stream=sample_rate,channels', '-of', 'json',
                                                 str(source_mp3)]))['streams'][0]
    rate = int(stream['sample_rate'])
    if stream['channels'] != 1 or rate != 44100:
        raise RuntimeError('source must be 44.1 kHz mono; no resampling is permitted')
    original_pcm = subprocess.check_output(['ffmpeg', '-v', 'error', '-xerror', '-i', str(source_mp3),
                                            '-map', '0:a:0', '-c:a', 'pcm_s16le', '-f', 's16le', '-'])
    samples = array.array('h')
    samples.frombytes(original_pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    alignment = hit['timing']['alignment']
    starts, ends = alignment['character_start_times_seconds'], alignment['character_end_times_seconds']
    canonical = module['narration']
    _, positions = request_text_and_indices(spec, module)
    events = []
    for row in requested:
        offset = row['after_offset']
        left, right = offset-1, offset
        while canonical[left].isspace():
            left -= 1
        while canonical[right].isspace():
            right += 1
        previous_end, next_start = ends[positions[left]], starts[positions[right]]
        lo = max(0, round((previous_end-.2)*rate))
        hi = min(len(samples), round((next_start+.12)*rate))
        quiet_start, quiet_end = quiet_run(samples, lo, hi)
        if (quiet_end-quiet_start < round(.25*rate)
                or not quiet_start/rate <= (previous_end+next_start)/2 <= quiet_end/rate):
            raise RuntimeError(f'{block_id} {offset}: ambiguous or voiced boundary; no insertion made')
        cut = (quiet_start+quiet_end)//2
        if min(cut-quiet_start, quiet_end-cut) < round(.1*rate):
            raise RuntimeError(f'{block_id} {offset}: silent cut too close to speech')
        zeroes = [i for i in range(cut-44, cut+45) if samples[i] == 0]
        if zeroes:
            cut = min(zeroes, key=lambda i: abs(i-cut))
        added = max(0, round(row['target_total_seconds']*rate)-(quiet_end-quiet_start))
        events.append({'after_offset': offset, 'reason': row['reason'],
                       'quiet_start_source_sample': quiet_start, 'quiet_end_source_sample': quiet_end,
                       'cut_source_sample': cut, 'before_seconds': (quiet_end-quiet_start)/rate,
                       'added_samples': added, 'added_seconds': added/rate,
                       'after_seconds': (quiet_end-quiet_start+added)/rate})
    output = bytearray()
    previous = cumulative = 0
    for event in events:
        cut = event['cut_source_sample']
        output.extend(original_pcm[previous*2:cut*2])
        event['insert_start_final_sample'] = cut+cumulative
        output.extend(bytes(event['added_samples']*2))
        cumulative += event['added_samples']
        previous = cut
    output.extend(original_pcm[previous*2:])
    final_pcm = bytes(output)
    restored = bytearray()
    previous = 0
    for event in events:
        start = event['insert_start_final_sample']*2
        restored.extend(final_pcm[previous:start])
        previous = start+event['added_samples']*2
    restored.extend(final_pcm[previous:])
    if bytes(restored) != original_pcm:
        raise RuntimeError('final PCM does not restore the untouched source PCM')
    stage = folder / f'{prefix}.stage'
    stage.mkdir()
    wav_path = stage / f'{prefix}.wav'
    with wave.open(str(wav_path), 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(rate)
        wav.writeframes(final_pcm)
    mp3_path = stage / f'{prefix}.mp3'
    if any(event['added_samples'] for event in events):
        subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(wav_path), '-map', '0:a:0',
                        '-c:a', 'libmp3lame', '-b:a', '128k', str(mp3_path)], check=True)
    else:
        shutil.copy2(source_mp3, mp3_path)
    subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(mp3_path), '-f', 'null', '-'],
                   check=True, stdout=subprocess.DEVNULL)
    duration = probe_duration(mp3_path)

    def shift(value: float) -> float:
        return value + sum(e['added_seconds'] for e in events if value*rate >= e['cut_source_sample'])

    shifted = {**alignment,
               'character_start_times_seconds': [shift(value) for value in starts],
               'character_end_times_seconds': [shift(value) for value in ends]}
    timing = map_timing(spec, module, shifted, duration)
    write_json(stage / f'{prefix}-timing.json', timing)
    shutil.copy2(folder / 'timing.json', stage / f'{prefix}-source-timing.json')
    metadata = {'block_id': block_id, 'variant_id': variant,
                'source_mp3_sha256': digest(source_mp3.read_bytes()),
                'source_pcm_sha256': digest(original_pcm),
                'restored_pcm_sha256': digest(bytes(restored)),
                'final_pcm_sha256': digest(final_pcm),
                'wav_sha256': digest(wav_path.read_bytes()),
                'mp3_sha256': digest(mp3_path.read_bytes()),
                'timing_sha256': digest((stage / f'{prefix}-timing.json').read_bytes()),
                'source_timing_sha256': digest((folder / 'timing.json').read_bytes()),
                'mp3_duration_seconds': duration, 'new_tts_requests': 0,
                'speed_pitch_gain_processing': False,
                'source_pcm_recovered_exactly': True, 'events': events}
    write_json(stage / f'{prefix}-metadata.json', metadata)
    for path in stage.iterdir():
        path.replace(folder / path.name)
    stage.rmdir()
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('review_map', type=Path, help='manual per-block JSON map with semantic reasons')
    args = parser.parse_args()
    print(json.dumps(apply(args.review_map), ensure_ascii=False, indent=2))
