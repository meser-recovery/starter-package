#!/usr/bin/env python3
"""Acoustic boundary checks; optionally import independently produced local ASR evidence.

Numerical checks detect seam risks; they do not replace human prosody review.
"""
import argparse,array,hashlib,json,math,re,wave
from pathlib import Path
from modules import ROOT,cached,sha,write_json
from module_visuals import OUT


def speech_checks(evidence):
    def normalized(text):
        return re.sub(r'[^а-яa-z0-9]', '', text.lower().replace('ё', 'е'))
    rows=[]
    for row in evidence['windows']:
        expected=normalized(row['expected_boundary_phrase']); actual=normalized(row['transcript'])
        edge=actual.startswith(expected) if row['window']=='opening' else actual.endswith(expected)
        tags=bool(re.search(r'calm|conversational|калм|конверсейш',row['transcript'],re.I))
        rows.append({'module_id':row['module_id'],'window':row['window'],
                     'complete_boundary_phrase':edge,'boundary_phrase_count':actual.count(expected),
                     'delivery_tags_detected':tags,'status':'PASS' if edge and actual.count(expected)==1 and not tags else 'REVIEW'})
    coverage={(r['module_id'],r['window']) for r in rows}
    complete=coverage=={(f'N{i:02}',w) for i in range(1,9) for w in ('opening','ending')} and len(rows)==16
    return {'status':'PASS' if complete and all(r['status']=='PASS' for r in rows) else 'REVIEW',
            'method':'Independent ASR boundary phrase presence/order; punctuation and word spacing normalized; no phoneme/prosody claim.',
            'windows':rows}


def boundary_checks(spec):
    timeline=json.loads((OUT/'audio/timeline.json').read_text())
    with wave.open(str(OUT/'audio/master.wav')) as source:
        rate=source.getframerate();samples=array.array('h');samples.frombytes(source.readframes(source.getnframes()))
    if sha(OUT/'audio/master.wav')!=timeline['master_sha256']:raise RuntimeError('stale PCM timeline')
    tails=[]
    for module in timeline['modules']:
        start=module['start_sample'];end=start+module['decoded_frames'];stop=start+module['frames']
        unchanged=hashlib.sha256(samples[start:end].tobytes()).hexdigest()==module['decoded_pcm_sha256']
        # Check the actual source-to-padding edge, not just the later module seam.
        peak_step=max(abs(samples[i]-samples[i-1])/32768 for i in range(end,stop))
        tails.append({'module_id':module['module_id'],'decoded_PCM_unchanged':unchanged,
                      'source_to_padding_peak_step':peak_step,'padding_end_zero':samples[stop-1]==0,
                      'status':'PASS' if unchanged and peak_step<.02 and samples[stop-1]==0 else 'REVIEW'})
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
    report={'acoustic_status':'PASS' if all(r['status']=='PASS' for r in rows+tails) else 'REVIEW',
            'source_to_padding_checks':tails,
            'master_sha256':timeline['master_sha256'],'boundaries':rows,'delivery_prefix_alignment':tags,
            'speech_verification':'Independent ASR evidence required; timestamps alone do not establish unspoken tags.',
            'human_prosody_review':'Use all seven review controls; automated metrics do not certify natural intonation.'}
    asr=OUT/'audio/asr-boundaries.json'
    if asr.exists():
        evidence=json.loads(asr.read_text())
        if evidence.get('source_audio_sha256')=={row['module_id']:row['audio_sha256'] for row in tags}:
            report['independent_asr']=evidence
            report['speech_boundary_check']=speech_checks(evidence)
    write_json(OUT/'audio/boundary-validation.json',report)
    return report


if __name__=='__main__':
    spec=json.loads((ROOT/'tutorial.yaml').read_text())
    result=boundary_checks(spec)
    print(json.dumps({k:v for k,v in result.items() if k not in ('independent_asr','boundaries')},ensure_ascii=False,indent=2))
