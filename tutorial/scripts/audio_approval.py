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
        audio_record = approved_path(block_id)
        if (record['approved_audio_record'] != str(audio_record.relative_to(ROOT))
                or digest(audio_record.read_bytes()) != record['approved_audio_record_sha256']):
            raise ValueError('approved audio record changed')
        audio = json.loads(audio_record.read_text())['approved_take']
        for approval_key, audio_key in (('approved_mp3_sha256', 'mp3_sha256'),
                                        ('approved_wav_sha256', 'wav_sha256'),
                                        ('approved_pcm_sha256', 'pcm_sha256'),
                                        ('approved_alignment_sha256', 'alignment_sha256'),
                                        ('canonical_text_sha256', 'canonical_text_sha256')):
            if record[approval_key] != audio[audio_key]:
                raise ValueError(f'{approval_key} differs from audio approval')
        if record['approved_alignment'] != audio['alignment']:
            raise ValueError('approved alignment path changed')
        for name, hash_name in (('approved_alignment', 'approved_alignment_sha256'),
                                ('subtitle_srt', 'subtitle_srt_sha256'),
                                ('subtitle_vtt', 'subtitle_vtt_sha256'),
                                ('video_audio_timeline', 'video_audio_timeline_sha256'),
                                ('report', 'report_sha256'), ('verification', 'verification_sha256')):
            checked_file(record[name], record[hash_name])
        for scene in record['scene_sources']:
            checked_file(scene['path'], scene['sha256'])
        report = json.loads((ROOT / record['report']).read_text())
        verification = json.loads((ROOT / record['verification']).read_text())
        report_alignment = report.get('approved_alignment_sha256', report.get('final_alignment_sha256'))
        if (report['video_sha256'] != record['video_sha256']
                or report_alignment != record['approved_alignment_sha256']
                or verification['status'] != 'PASS'
                or verification['video_sha256'] != record['video_sha256']
                or verification['subtitle_cues'] != record['embedded_subtitle_cues']
                or verification['last_embedded_subtitle_end_seconds'] != record['last_embedded_subtitle_end_seconds']):
            raise ValueError(f'{block_id} verification differs from block approval')
        probe = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries',
                                                    'format=duration', '-of', 'json', str(video)]))
        if abs(float(probe['format']['duration']) - record['duration_seconds']) > .001:
            raise ValueError('approved video duration changed')
    except (OSError, KeyError, ValueError, subprocess.CalledProcessError) as error:
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
    if block_id == 'B09':
        return validate_shortened_approval(spec, record)
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
    inserted = [e['after_offset'] for e in record['insertions']]
    if not set(inserted).issubset(marked) or inserted != sorted(set(inserted)):
        raise RuntimeError('approved insertion map differs from reviewed semantic boundaries')
    reviewed_reasons = {p['after_offset']: p['reason'] for p in module['tts']['pauses']}
    for approved_event, source_event, reason in zip(record['insertions'], metadata['events'],
                                                     (reviewed_reasons[e['after_offset']] for e in record['insertions'])):
        if (approved_event['reason'] != reason or
                any(approved_event[key] != source_event[key] for key in
                    ('after_offset', 'quiet_start_source_sample', 'quiet_end_source_sample',
                     'cut_source_sample', 'insert_start_final_sample', 'added_samples',
                     'before_seconds', 'added_seconds', 'after_seconds'))):
            raise RuntimeError('approved insertion map differs from reviewed source')
    return {'record': record, 'timing': timing, 'wav_path': wav_path,
            'wav_duration_seconds': approved['pcm_samples'] / approved['pcm_sample_rate']}


def validate_shortened_approval(spec: dict, record: dict) -> dict:
    """B09's authorized sentence removal retains every other source PCM sample."""
    module = next(m for m in spec['narration_modules'] if m['id'] == 'B09')
    approved, source = record['approved_take'], record['source']
    if digest(module['narration'].encode()) != approved['canonical_text_sha256']:
        raise RuntimeError('B09 approval no longer matches canonical text')
    checked_file(approved['mp3'], approved['mp3_sha256'])
    wav_path = checked_file(approved['wav'], approved['wav_sha256'])
    timing_path = checked_file(approved['alignment'], approved['alignment_sha256'])
    source_mp3 = checked_file(source['mp3'], source['mp3_sha256'])
    source_wav = checked_file(source['wav'], source['wav_sha256'])
    checked_file(source['source_alignment'], source['source_alignment_sha256'])
    metadata_ref = record['derivation_metadata']
    metadata = json.loads(checked_file(metadata_ref['path'], metadata_ref['sha256']).read_text())
    qa_ref = record['review_qa']
    qa = json.loads(checked_file(qa_ref['path'], qa_ref['sha256']).read_text())
    if qa['status'] != 'PASS':
        raise RuntimeError('B09 review QA did not pass')
    with wave.open(str(source_wav)) as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 44100):
            raise RuntimeError('B09 source WAV format changed')
        source_pcm = wav.readframes(wav.getnframes())
    if (digest(source_pcm) != source['decoded_pcm_sha256']
            or len(source_pcm) // 2 != source['decoded_pcm_samples']):
        raise RuntimeError('B09 source PCM changed')
    decoded = subprocess.check_output(['ffmpeg', '-v', 'error', '-xerror', '-i', str(source_mp3),
                                       '-map', '0:a:0', '-ac', '1', '-ar', '44100',
                                       '-c:a', 'pcm_s16le', '-f', 's16le', '-'])
    if decoded != source_pcm:
        raise RuntimeError('B09 original provider MP3 changed')
    with wave.open(str(wav_path)) as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, approved['pcm_sample_rate']):
            raise RuntimeError('B09 approved WAV format changed')
        pcm = wav.readframes(wav.getnframes())
        samples = wav.getnframes()
    if digest(pcm) != approved['pcm_sha256'] or samples != approved['pcm_samples']:
        raise RuntimeError('B09 approved PCM changed')
    cut_start, cut_end = record['deleted_source_sample_range']
    if not (0 < cut_start < cut_end < len(source_pcm) // 2):
        raise RuntimeError('B09 approved deletion range invalid')
    if (metadata['cut_source_sample_range'] != [cut_start, cut_end]
            or metadata['final_pcm_sha256'] != approved['pcm_sha256']
            or metadata['wav_sha256'] != approved['wav_sha256']
            or metadata['timing_sha256'] != approved['alignment_sha256']
            or not metadata['source_pcm_recovered_exactly']
            or metadata['new_tts_requests'] != 0
            or metadata['speed_pitch_gain_processing']):
        raise RuntimeError('B09 deletion provenance differs from approval')
    if pcm != source_pcm[:cut_start * 2] + source_pcm[cut_end * 2:]:
        raise RuntimeError('B09 retained source PCM changed')
    timing = json.loads(timing_path.read_text())
    if timing != map_timing(spec, module, timing['alignment'], timing['duration_seconds']):
        raise RuntimeError('B09 approved alignment invalid')
    if abs(timing['duration_seconds'] - samples / approved['pcm_sample_rate']) > .000001:
        raise RuntimeError('B09 approved alignment duration changed')
    return {'record': record, 'timing': timing, 'wav_path': wav_path,
            'wav_duration_seconds': samples / approved['pcm_sample_rate']}


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
