#!/usr/bin/env python3
"""Finish one saved continuous B01 provider take for audio review, without TTS."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from modules import CACHE, cached, map_timing, narration_hash, request_body, request_text_and_indices, sha, write_json
from narration import probe_duration
from validate import ROOT, validate

SAMPLE_RATE = 44100


def pcm(audio: Path, tempo: float) -> bytes:
    command = ['ffmpeg', '-v', 'error', '-xerror', '-i', str(audio), '-af',
               f'rubberband=tempo={tempo}:formant=preserved', '-ac', '1', '-ar', str(SAMPLE_RATE),
               '-f', 's16le', '-']
    return subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def encode(raw: bytes, output: Path) -> None:
    command = ['ffmpeg', '-v', 'error', '-xerror', '-f', 's16le', '-ar', str(SAMPLE_RATE),
               '-ac', '1', '-i', '-', '-codec:a', 'libmp3lame', '-b:a', '128k',
               '-ar', str(SAMPLE_RATE), '-y', str(output)]
    subprocess.run(command, input=raw, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def finish(attempt_id: str) -> dict:
    validate()
    spec=json.loads((ROOT/'tutorial.yaml').read_text())
    block=spec['narration_modules'][0]
    assert block['id']=='B01'
    folder=CACHE/'B01'; pending=folder/'pending'/attempt_id
    body=json.loads((pending/'request.json').read_text())
    if body!=request_body(spec,block):
        raise RuntimeError('saved provider request differs from current B01 profile')
    response=json.loads((pending/'response-timing.json').read_text())
    source_audio=pending/'narration.mp3'
    source_duration=probe_duration(source_audio)
    source_alignment=response['alignment']
    map_timing(spec,block,source_alignment,source_duration)
    entries=[json.loads(line) for line in (CACHE/'requests.jsonl').read_text().splitlines()]
    started=next(e for e in entries if e.get('attempt_id')==attempt_id and e.get('event')=='started')
    replied=next(e for e in entries if e.get('attempt_id')==attempt_id and e.get('event')=='response')
    if replied['http_status']!=200:
        raise RuntimeError('saved provider response is not HTTP 200')

    profile=block['tts']['review_processing']
    raw=pcm(source_audio,profile['tempo'])
    stretched_duration=len(raw)/(SAMPLE_RATE*2)
    scale=stretched_duration/source_duration
    _,indices=request_text_and_indices(spec,block)
    canonical=block['narration']
    starts=source_alignment['character_start_times_seconds']
    ends=source_alignment['character_end_times_seconds']
    cuts=[]
    for marker in block['tts']['pauses']:
        offset=marker['after_offset']; left=offset-1; right=offset
        while canonical[left].isspace(): left-=1
        while canonical[right].isspace(): right+=1
        before=ends[indices[left]]*scale
        after=starts[indices[right]]*scale
        target=profile['subtopic_pause_seconds'] if marker['count']==2 else profile['thought_pause_seconds']
        cut=(before+after)/2
        padding=max(0,round((target-(after-before))*SAMPLE_RATE))
        cuts.append({'after_offset':offset,'target_seconds':target,'source_gap_seconds':after-before,
                     'cut_sample':round(cut*SAMPLE_RATE),'inserted_samples':padding})
    if any(a['cut_sample']>=b['cut_sample'] for a,b in zip(cuts,cuts[1:])):
        raise RuntimeError('non-increasing B01 pause locations')
    output=bytearray(); previous=0
    for cut in cuts:
        sample=cut['cut_sample']; output.extend(raw[previous*2:sample*2])
        output.extend(bytes(cut['inserted_samples']*2)); previous=sample
    output.extend(raw[previous*2:])

    def adjusted(value: float) -> float:
        sample=value*scale*SAMPLE_RATE
        return (sample+sum(c['inserted_samples'] for c in cuts if sample>=c['cut_sample']))/SAMPLE_RATE

    alignment={**source_alignment,
               'character_start_times_seconds':[adjusted(x) for x in starts],
               'character_end_times_seconds':[adjusted(x) for x in ends]}
    stage=pending/'finished';stage.mkdir(exist_ok=True)
    encode(bytes(output),stage/'narration.mp3')
    duration=probe_duration(stage/'narration.mp3')
    timing=map_timing(spec,block,alignment,duration)
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(stage/'narration.mp3'),'-f','null','-'],
                   check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    write_json(stage/'timing.json',timing)
    write_json(stage/'request.json',body)
    write_json(stage/'response-timing.json',response)
    (stage/'request-text.txt').write_text(body['text'])
    (stage/'canonical-spoken-text.txt').write_text(canonical)
    metadata={**started,'narration_hash':narration_hash(spec,block),'http_status':200,
              'request_id':replied.get('request_id'),'duration_seconds':duration,'decode':'PASS',
              'audio_sha256':sha(stage/'narration.mp3'),'timing_sha256':sha(stage/'timing.json'),
              'tts_requests_for_this_take':1,'scene_audio_files':False,'request':body,
              'provider_source_audio_sha256':sha(source_audio),'provider_source_duration_seconds':source_duration,
              'review_processing':{**profile,'stretched_duration_seconds':stretched_duration,'cuts':cuts}}
    write_json(stage/'metadata.json',metadata)
    source_archive=folder/'provider-source'/metadata['provider_source_audio_sha256']
    source_archive.mkdir(parents=True,exist_ok=True)
    for name in ('narration.mp3','request.json','response-timing.json'):
        if not (source_archive/name).exists(): shutil.copy2(pending/name,source_archive/name)
    for name in ('narration.mp3','timing.json','request.json','response-timing.json',
                 'request-text.txt','canonical-spoken-text.txt','metadata.json'):
        (stage/name).replace(folder/name)
    for name in ('local-asr.json','local-asr.txt','qa.json'):
        (folder/name).unlink(missing_ok=True)
    review=folder/'B01.mp3';review.unlink(missing_ok=True)
    os.link(folder/'narration.mp3',review)
    if not cached(spec,block):
        raise RuntimeError('finished B01 take failed cache validation')
    return {'audio_sha256':metadata['audio_sha256'],'duration_seconds':duration,
            'provider_source_audio_sha256':metadata['provider_source_audio_sha256'],
            'inserted_silence_seconds':sum(c['inserted_samples'] for c in cuts)/SAMPLE_RATE}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('attempt_id',help='saved B01 pending provider attempt')
    args=parser.parse_args()
    print(json.dumps(finish(args.attempt_id),ensure_ascii=False))
