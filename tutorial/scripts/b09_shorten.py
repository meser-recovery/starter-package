"""Derive the approved-content B09 shorter take from its existing one-request TTS PCM."""
from __future__ import annotations

import array
import hashlib
import json
import subprocess
import wave
from pathlib import Path

from modules import map_timing, request_body, sha, write_json
from validate import ROOT

FOLDER = ROOT / 'generated/narration-blocks-v2/B09'
SOURCE_VARIANT = 'B09-review-01'
VARIANT = 'B09-short-01'
RATE = 44100
REMOVED_TEXT = ('Если требуется более точное редактирование, точные значения границ '
                'можно также указать вручную с помощью числовых полей.\n\n')
# Both joins are inside decoded near-silence, clear of the previous word and
# of the following audible onset. These are sample positions, not a speed edit.
CUT_START_SAMPLE = 4_397_652  # 99.720000 s
CUT_END_SAMPLE = 4_765_005    # 108.050000 s


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def prepare(spec: dict, module: dict) -> tuple[dict, dict, bytes]:
    source_meta = json.loads((FOLDER / 'metadata.json').read_text())
    source_timing = json.loads((FOLDER / 'timing.json').read_text())
    review = json.loads((FOLDER / f'{SOURCE_VARIANT}-metadata.json').read_text())
    source_mp3 = FOLDER / 'narration.mp3'
    source_wav = FOLDER / f'{SOURCE_VARIANT}.wav'
    if (source_meta['tts_requests_for_this_take'] != 1 or sha(source_mp3) != source_meta['audio_sha256']
            or sha(FOLDER / 'timing.json') != source_meta['timing_sha256']
            or sha(source_wav) != review['wav_sha256']
            or review['source_mp3_sha256'] != source_meta['audio_sha256']):
        raise RuntimeError('B09 original one-request take changed')
    old_request = source_meta['request']['text']
    old_alignment = source_timing['alignment']
    if ''.join(old_alignment['characters']) != old_request:
        raise RuntimeError('B09 original provider alignment differs from its request')
    old_canonical = source_timing['canonical_spoken_text']
    if (old_canonical.count(REMOVED_TEXT) != 1
            or old_canonical.replace(REMOVED_TEXT, '', 1) != module['narration']
            or old_request.count(REMOVED_TEXT) != 1
            or old_request.replace(REMOVED_TEXT, '', 1) != request_body(spec, module)['text']):
        raise RuntimeError('B09 content change exceeds the authorized sentence removal')
    request_start = old_request.index(REMOVED_TEXT)
    request_end = request_start + len(REMOVED_TEXT)
    with wave.open(str(source_wav)) as source:
        if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, RATE):
            raise RuntimeError('B09 reviewed source WAV format changed')
        original_pcm = source.readframes(source.getnframes())
        original_samples = source.getnframes()
    if digest(original_pcm) != review['final_pcm_sha256']:
        raise RuntimeError('B09 reviewed source PCM changed')
    decoded = subprocess.check_output(['ffmpeg', '-v', 'error', '-xerror', '-i', str(source_mp3),
                                       '-map', '0:a:0', '-ac', '1', '-ar', str(RATE),
                                       '-c:a', 'pcm_s16le', '-f', 's16le', '-'])
    if decoded != original_pcm:
        raise RuntimeError('B09 provider MP3 no longer decodes to the reviewed PCM')
    samples = array.array('h'); samples.frombytes(original_pcm)
    if not (0 < CUT_START_SAMPLE < CUT_END_SAMPLE < original_samples):
        raise RuntimeError('B09 PCM splice range invalid')
    for position in (CUT_START_SAMPLE, CUT_END_SAMPLE):
        if max(abs(value) for value in samples[position-441:position+441]) > 4:
            raise RuntimeError(f'B09 splice at sample {position} is not quiet')
    if abs(samples[CUT_START_SAMPLE-1] - samples[CUT_END_SAMPLE]) > 4:
        raise RuntimeError('B09 PCM splice would create a sample step')
    removed_samples = CUT_END_SAMPLE - CUT_START_SAMPLE
    shift = removed_samples / RATE
    final_pcm = original_pcm[:CUT_START_SAMPLE*2] + original_pcm[CUT_END_SAMPLE*2:]
    if final_pcm[:CUT_START_SAMPLE*2] != original_pcm[:CUT_START_SAMPLE*2] or final_pcm[CUT_START_SAMPLE*2:] != original_pcm[CUT_END_SAMPLE*2:]:
        raise RuntimeError('B09 retained speech PCM differs from source')
    wav_path = FOLDER / f'{VARIANT}.wav'
    with wave.open(str(wav_path), 'wb') as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(RATE)
        output.writeframes(final_pcm)
    old_chars = old_alignment['characters']
    alignment = {
        'characters': old_chars[:request_start] + old_chars[request_end:],
        'character_start_times_seconds': old_alignment['character_start_times_seconds'][:request_start]
            + [value-shift for value in old_alignment['character_start_times_seconds'][request_end:]],
        'character_end_times_seconds': old_alignment['character_end_times_seconds'][:request_start]
            + [value-shift for value in old_alignment['character_end_times_seconds'][request_end:]],
    }
    duration = (original_samples-removed_samples)/RATE
    timing = map_timing(spec, module, alignment, duration)
    timing_path = FOLDER / f'{VARIANT}-timing.json'
    write_json(timing_path, timing)
    metadata = {
        'block_id': 'B09', 'variant_id': 'short-01',
        'source_mp3_sha256': source_meta['audio_sha256'],
        'source_wav_sha256': review['wav_sha256'],
        'source_timing_sha256': source_meta['timing_sha256'],
        'source_pcm_sha256': digest(original_pcm),
        'wav_sha256': sha(wav_path), 'timing_sha256': sha(timing_path),
        'final_pcm_sha256': digest(final_pcm), 'duration_seconds': duration,
        'removed_canonical_text': REMOVED_TEXT, 'removed_request_range': [request_start, request_end],
        'cut_source_sample_range': [CUT_START_SAMPLE, CUT_END_SAMPLE],
        'cut_source_seconds': [CUT_START_SAMPLE/RATE, CUT_END_SAMPLE/RATE],
        'removed_samples': removed_samples, 'removed_seconds': shift,
        'join_sample_step': samples[CUT_END_SAMPLE]-samples[CUT_START_SAMPLE-1],
        'source_pcm_recovered_exactly': final_pcm[:CUT_START_SAMPLE*2]
            + original_pcm[CUT_START_SAMPLE*2:CUT_END_SAMPLE*2]
            + final_pcm[CUT_START_SAMPLE*2:] == original_pcm,
        'new_tts_requests': 0, 'speed_pitch_gain_processing': False,
    }
    if not metadata['source_pcm_recovered_exactly']:
        raise RuntimeError('B09 removal map cannot restore original PCM')
    write_json(FOLDER / f'{VARIANT}-metadata.json', metadata)
    return metadata, timing, final_pcm
