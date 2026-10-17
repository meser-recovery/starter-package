#!/usr/bin/env python3
"""Create one B01 silence-only review variant from the specified provider MP3."""
from __future__ import annotations

import array
import hashlib
import json
import shutil
import subprocess
import sys
import wave

from modules import CACHE, cached, map_timing, request_text_and_indices, write_json
from narration import probe_duration
from validate import ROOT, validate

SOURCE_SHA256 = 'e39add9963b32649b90aceb1a786d0a3a9ec442860fa30a31f66432a9fa0557e'
RATE = 44100
QUIET_PEAK = 32  # -60 dBFS; search for a continuous region, not an alignment gap alone.
TARGETS = {450: 1.2, 795: 0.8, 999: 1.2, 1409: 1.2, 1699: 0.8, 1902: 1.0}
PREFIX = 'B01-six-pauses'


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, **kwargs)


def longest_quiet_run(samples: array.array, begin: int, end: int) -> tuple[int, int]:
    run_start = None
    best = (begin, begin)
    for index in range(begin, end):
        if abs(samples[index]) <= QUIET_PEAK:
            if run_start is None:
                run_start = index
        elif run_start is not None:
            if index - run_start > best[1] - best[0]:
                best = (run_start, index)
            run_start = None
    if run_start is not None and end - run_start > best[1] - best[0]:
        best = (run_start, end)
    return best


def create() -> dict:
    validate()
    spec = json.loads((ROOT / 'tutorial.yaml').read_text())
    block = spec['narration_modules'][0]
    assert block['id'] == 'B01'
    if [p['after_offset'] for p in block['tts']['pauses']] != list(TARGETS):
        raise RuntimeError('B01 semantic pause map changed')
    folder = CACHE / 'B01'
    source_mp3 = folder / 'B01.mp3'
    if digest(source_mp3.read_bytes()) != SOURCE_SHA256:
        raise RuntimeError('B01 source MP3 is not the requested original provider take')
    hit = cached(spec, block)
    if not hit or hit['metadata']['audio_sha256'] != SOURCE_SHA256:
        raise RuntimeError('B01 original alignment or provider cache is invalid')
    if any((folder / f'{PREFIX}{suffix}').exists() for suffix in
           ('.wav', '.mp3', '-timing.json', '-source-timing.json', '-metadata.json')):
        raise RuntimeError('review variant already exists; refusing to replace it')
    stage = folder / 'pause-review-stage'
    if stage.exists():
        raise RuntimeError('unfinished review stage already exists')
    stage.mkdir()

    probe = json.loads(run(['ffprobe', '-v', 'error', '-select_streams', 'a:0',
                            '-show_entries', 'stream=sample_rate,channels', '-of', 'json',
                            str(source_mp3)]).stdout)
    stream = probe['streams'][0]
    if (int(stream['sample_rate']), stream['channels']) != (RATE, 1):
        raise RuntimeError('source is not 44.1 kHz mono; refusing resampling or remixing')
    source_pcm = run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(source_mp3),
                      '-map', '0:a:0', '-c:a', 'pcm_s16le', '-f', 's16le', '-']).stdout
    samples = array.array('h')
    samples.frombytes(source_pcm)
    if sys.byteorder != 'little':
        samples.byteswap()
    timing = hit['timing']
    alignment = timing['alignment']
    starts = alignment['character_start_times_seconds']
    ends = alignment['character_end_times_seconds']
    canonical = block['narration']
    _, positions = request_text_and_indices(spec, block)
    events = []
    for offset, target in TARGETS.items():
        left, right = offset - 1, offset
        while canonical[left].isspace():
            left -= 1
        while canonical[right].isspace():
            right += 1
        previous_end = ends[positions[left]]
        next_start = starts[positions[right]]
        window_start = max(0, round((previous_end - .2) * RATE))
        window_end = min(len(samples), round((next_start + .12) * RATE))
        quiet_start, quiet_end = longest_quiet_run(samples, window_start, window_end)
        midpoint = (previous_end + next_start) / 2
        if not (quiet_start / RATE <= midpoint <= quiet_end / RATE):
            raise RuntimeError(f'B01 {offset}: quiet region does not span the aligned boundary')
        if quiet_end - quiet_start < round(.25 * RATE):
            raise RuntimeError(f'B01 {offset}: no unambiguous silent interval')
        cut = (quiet_start + quiet_end) // 2
        if min(cut - quiet_start, quiet_end - cut) < round(.1 * RATE):
            raise RuntimeError(f'B01 {offset}: insertion would be too close to speech')
        # Both sides of the cut are below -60 dBFS. Choose a zero-valued sample
        # near the midpoint to avoid creating an edge click.
        zeroes = [i for i in range(cut - 44, cut + 45) if samples[i] == 0]
        if zeroes:
            cut = min(zeroes, key=lambda i: abs(i - cut))
        original_quiet = quiet_end - quiet_start
        added = max(0, round(target * RATE) - original_quiet)
        events.append({'after_offset': offset, 'target_seconds': target,
                       'aligned_previous_end_seconds': previous_end,
                       'aligned_next_start_seconds': next_start,
                       'quiet_start_source_sample': quiet_start,
                       'quiet_end_source_sample': quiet_end,
                       'cut_source_sample': cut,
                       'before_seconds': original_quiet / RATE,
                       'added_samples': added,
                       'added_seconds': added / RATE,
                       'after_seconds': (original_quiet + added) / RATE})

    output = bytearray()
    previous = 0
    cumulative = 0
    for event in events:
        cut = event['cut_source_sample']
        output.extend(source_pcm[previous * 2:cut * 2])
        event['insert_start_final_sample'] = cut + cumulative
        output.extend(bytes(event['added_samples'] * 2))
        cumulative += event['added_samples']
        previous = cut
    output.extend(source_pcm[previous * 2:])
    final_pcm = bytes(output)
    restored = bytearray()
    previous = 0
    for event in events:
        insertion = event['insert_start_final_sample'] * 2
        restored.extend(final_pcm[previous:insertion])
        previous = insertion + event['added_samples'] * 2
    restored.extend(final_pcm[previous:])
    if bytes(restored) != source_pcm:
        raise RuntimeError('removing inserted samples does not restore original PCM')

    wav_path = stage / f'{PREFIX}.wav'
    with wave.open(str(wav_path), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(final_pcm)
    with wave.open(str(wav_path)) as wav:
        if wav.readframes(wav.getnframes()) != final_pcm:
            raise RuntimeError('review WAV PCM differs from verified output')
    mp3_path = stage / f'{PREFIX}.mp3'
    run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(wav_path), '-map', '0:a:0',
         '-c:a', 'libmp3lame', '-b:a', '128k', '-y', str(mp3_path)])
    run(['ffmpeg', '-v', 'error', '-xerror', '-i', str(mp3_path), '-f', 'null', '-'])
    duration = probe_duration(mp3_path)

    def shift(value: float) -> float:
        return value + sum(e['added_seconds'] for e in events
                           if value * RATE >= e['cut_source_sample'])

    shifted_alignment = {**alignment,
        'character_start_times_seconds': [shift(value) for value in starts],
        'character_end_times_seconds': [shift(value) for value in ends]}
    shifted_timing = map_timing(spec, block, shifted_alignment, duration)
    write_json(stage / f'{PREFIX}-timing.json', shifted_timing)
    shutil.copy2(folder / 'timing.json', stage / f'{PREFIX}-source-timing.json')
    metadata = {'module_id': 'B01', 'source_mp3_sha256': SOURCE_SHA256,
                'source_timing_sha256': digest((folder / 'timing.json').read_bytes()),
                'source_pcm_sha256': digest(source_pcm),
                'restored_pcm_sha256': digest(bytes(restored)),
                'final_pcm_sha256': digest(final_pcm),
                'wav_sha256': digest(wav_path.read_bytes()),
                'mp3_sha256': digest(mp3_path.read_bytes()),
                'source_pcm_samples': len(samples),
                'final_pcm_samples': len(final_pcm) // 2,
                'sample_rate': RATE, 'sample_format': 'signed 16-bit little-endian mono',
                'mp3_duration_seconds': duration,
                'new_tts_requests': 0, 'speed_or_pitch_processing': False,
                'source_pcm_recovered_exactly': True,
                'events': events}
    write_json(stage / f'{PREFIX}-metadata.json', metadata)
    for file in stage.iterdir():
        file.replace(folder / file.name)
    stage.rmdir()
    return metadata


if __name__ == '__main__':
    print(json.dumps(create(), ensure_ascii=False, indent=2))
