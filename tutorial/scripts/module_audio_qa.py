#!/usr/bin/env python3
"""Acoustic boundary checks; optionally import independently produced local ASR evidence.

Numerical checks detect seam risks; they do not replace human prosody review.
"""
import argparse,array,json,math,re,wave
from pathlib import Path
from modules import ROOT,cached,sha,write_json
from module_visuals import OUT


def boundary_checks(spec):
    timeline=json.loads((OUT/'audio/timeline.json').read_text())
    with wave.open(str(OUT/'audio/master.wav')) as source:
        rate=source.getframerate();samples=array.array('h');samples.frombytes(source.readframes(source.getnframes()))
    if sha(OUT/'audio/master.wav')!=timeline['master_sha256']:raise RuntimeError('stale PCM timeline')
    rows=[]
    for index,boundary in enumerate(timeline['boundaries']):
        left,right=timeline['modules'][index:index+2]
        lm,rm=spec['narration_modules'][index:index+2]
        l=cached(spec,lm);r=cached(spec,rm)
        if not l or not r:raise RuntimeError('stale module')
        speech_end=left['start_seconds']+l['timing']['scenes'][-1]['scene_end_seconds']
        speech_start=right['start_seconds']+r['timing']['scenes'][0]['scene_start_seconds']
        gap=speech_start-speech_end
        a=round(left['end_seconds']*rate);b=round(right['start_seconds']*rate)
        silence=not any(samples[a:b])
        left_step=abs(samples[a]-samples[a-1])/32768
        right_step=abs(samples[b]-samples[b-1])/32768
        rows.append({**boundary,'aligned_speech_gap_seconds':gap,'inserted_PCM_silence_exact':silence,
                     'actual_left_step':left_step,'actual_right_step':right_step,
                     'status':'PASS' if silence and max(left_step,right_step)<.02 and 0<=gap<3 and boundary['loudness_pass'] else 'REVIEW',
                     'expected_left_text':l['timing']['scenes'][-1]['phrases'][-1]['text'],
                     'expected_right_text':r['timing']['scenes'][0]['phrases'][0]['text']})
    tags=[]
    for module in spec['narration_modules']:
        hit=cached(spec,module);a=hit['timing']['alignment'];n=len(spec['narration']['delivery_prefix'])
        tags.append({'module_id':module['id'],'audio_sha256':hit['metadata']['audio_sha256'],
                     'prefix_alignment_end_seconds':max(a['character_end_times_seconds'][:n]),
                     'first_spoken_character_seconds':hit['timing']['scenes'][0]['scene_start_seconds']})
    report={'acoustic_status':'PASS' if all(r['status']=='PASS' for r in rows) else 'REVIEW',
            'master_sha256':timeline['master_sha256'],'boundaries':rows,'delivery_prefix_alignment':tags,
            'speech_verification':'Independent ASR evidence required; timestamps alone do not establish unspoken tags.',
            'human_prosody_review':'Use all seven review controls; automated metrics do not certify natural intonation.'}
    asr=OUT/'audio/asr-boundaries.json'
    if asr.exists():
        evidence=json.loads(asr.read_text())
        if evidence.get('source_audio_sha256')=={row['module_id']:row['audio_sha256'] for row in tags}:
            report['independent_asr']=evidence
    write_json(OUT/'audio/boundary-validation.json',report)
    return report


if __name__=='__main__':
    spec=json.loads((ROOT/'tutorial.yaml').read_text())
    result=boundary_checks(spec)
    print(json.dumps({k:v for k,v in result.items() if k not in ('independent_asr','boundaries')},ensure_ascii=False,indent=2))
