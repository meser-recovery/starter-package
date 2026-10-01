"""Fail-closed access to immutable, human-approved S11 block audio."""
from __future__ import annotations

import hashlib
import json
import subprocess
import wave
from pathlib import Path

from modules import map_timing, request_text_and_indices
from validate import ROOT

APPROVALS = ROOT / 'approvals'


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def approved_path(name: str) -> Path:
    return APPROVALS / f'{name}-audio.json'


def validate_block_approval(block_id: str) -> dict:
    """A later block cannot start until the prior complete MP4 is approved."""
    path = APPROVALS / f'{block_id}-block.json'
    try:
        record = json.loads(path.read_text())
        if record['status'] != 'BLOCK_APPROVED' or record['block_id'] != block_id:
            raise ValueError('invalid block approval status')
        video = checked_file(record['video'], record['video_sha256'])
    except (OSError, KeyError, ValueError) as error:
        raise RuntimeError(f'{block_id} complete block approval is required') from error
    return {**record, 'video_path': str(video)}


def checked_file(relative: str, expected_hash: str) -> Path:
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT / 'generated'):
        raise RuntimeError('approved audio path leaves the generated area')
    if digest(path.read_bytes()) != expected_hash:
        raise RuntimeError(f'approved audio artifact changed: {relative}')
    return path


def validate_approval(spec: dict, block_id: str) -> dict:
    record = json.loads(approved_path(block_id).read_text())
    if record['status'] != 'AUDIO_APPROVED' or record['block_id'] != block_id:
        raise RuntimeError(f'{block_id} has no valid AUDIO_APPROVED record')
    module = next(m for m in spec['narration_modules'] if m['id'] == block_id)
    approved, source = record['approved_take'], record['source']
    if digest(module['narration'].encode()) != approved['canonical_text_sha256']:
        raise RuntimeError('approved audio no longer matches canonical text')
    checked_file(approved['mp3'], approved['mp3_sha256'])
    wav_path = checked_file(approved['wav'], approved['wav_sha256'])
    timing_path = checked_file(approved['alignment'], approved['alignment_sha256'])
    source_mp3 = checked_file(source['mp3'], source['mp3_sha256'])
    checked_file(source['source_alignment'], source['source_alignment_sha256'])
    metadata_ref, qa_ref = record['pause_review_metadata'], record['pause_review_qa']
    metadata = json.loads(checked_file(metadata_ref['path'], metadata_ref['sha256']).read_text())
    qa = json.loads(checked_file(qa_ref['path'], qa_ref['sha256']).read_text())
    if (metadata['mp3_sha256'] != approved['mp3_sha256'] or
            metadata['wav_sha256'] != approved['wav_sha256'] or
            metadata['final_pcm_sha256'] != approved['pcm_sha256'] or
            qa['status'] != 'PASS'):
        raise RuntimeError('B01 pause review provenance differs from approval')
    with wave.open(str(wav_path)) as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, approved['pcm_sample_rate']):
            raise RuntimeError('approved WAV format changed')
        pcm = wav.readframes(wav.getnframes())
        if wav.getnframes() != approved['pcm_samples'] or digest(pcm) != approved['pcm_sha256']:
            raise RuntimeError('approved PCM changed')
    original_pcm = subprocess.check_output(['ffmpeg', '-v', 'error', '-xerror', '-i', str(source_mp3),
                                            '-map', '0:a:0', '-c:a', 'pcm_s16le', '-f', 's16le', '-'])
    if (digest(original_pcm) != source['decoded_pcm_sha256'] or
            len(original_pcm) // 2 != source['decoded_pcm_samples']):
        raise RuntimeError('approved source PCM changed')
    restored = bytearray()
    previous = 0
    for event in record['insertions']:
        start = event['insert_start_final_sample'] * 2
        end = start + event['added_samples'] * 2
        if start < previous or pcm[start:end] != bytes(end-start):
            raise RuntimeError('approval insertion map is invalid')
        restored.extend(pcm[previous:start])
        previous = end
    restored.extend(pcm[previous:])
    if bytes(restored) != original_pcm:
        raise RuntimeError('approved PCM does not restore its source exactly')
    timing = json.loads(timing_path.read_text())
    if timing != map_timing(spec, module, timing['alignment'], timing['duration_seconds']):
        raise RuntimeError('approved alignment is invalid')
    if abs(timing['duration_seconds'] - approved['mp3_duration_seconds']) > .000001:
        raise RuntimeError('approved alignment duration changed')
    marked = [p['after_offset'] for p in module.get('tts', {}).get('pauses', [])]
    if [e['after_offset'] for e in record['insertions']] != marked:
        raise RuntimeError('approved insertion map differs from reviewed semantic boundaries')
    for approved_event, source_event, reason in zip(record['insertions'], metadata['events'],
                                                     (p['reason'] for p in module['tts']['pauses'])):
        if (approved_event['reason'] != reason or
                any(approved_event[key] != source_event[key] for key in
                    ('after_offset', 'quiet_start_source_sample', 'quiet_end_source_sample',
                     'cut_source_sample', 'insert_start_final_sample', 'added_samples',
                     'before_seconds', 'added_seconds', 'after_seconds'))):
            raise RuntimeError('approved six-insertion map differs from reviewed source')
    return {'record': record, 'timing': timing, 'wav_path': wav_path,
            'wav_duration_seconds': approved['pcm_samples'] / approved['pcm_sample_rate']}


def scene_timing(spec: dict, scene: dict, approval: dict) -> dict:
    """Give visual capture the approved alignment, with no provider tags."""
    module = next(m for m in spec['narration_modules'] if m['id'] == scene['block_id'])
    full = approval['timing']
    row = next(s for s in full['scenes'] if s['scene_id'] == scene['id'])
    start = row['range_start_seconds']
    end = min(row['range_end_seconds'], approval['wav_duration_seconds'])
    _, indices = request_text_and_indices(spec, module)
    positions = indices[scene['start_offset']:scene['end_offset']]
    alignment = full['alignment']
    local = {'characters': [alignment['characters'][i] for i in positions],
             'character_start_times_seconds': [max(0, alignment['character_start_times_seconds'][i]-start) for i in positions],
             'character_end_times_seconds': [max(0, alignment['character_end_times_seconds'][i]-start) for i in positions]}
    if ''.join(local['characters']) != scene['narration']:
        raise RuntimeError('approved scene alignment differs from canonical text')
    return {**row, 'alignment': local, 'duration_seconds': end-start,
            'range_start_seconds': start, 'range_end_seconds': end,
            'timing_identity': digest((approval['record']['approved_take']['alignment_sha256'] + scene['id']).encode())}
