#!/usr/bin/env python3
"""Validate only corrective v2 artifacts; never generate audio or a master."""
import json,subprocess
from corrective_pilot import ALLOWED,OUT,preservation
from validate import validate


def run():
    rows=[]
    for number in ALLOWED:
        files=list((OUT/'scenes').glob(f'{number:03d}-*.mp4'))
        if len(files)!=1:raise RuntimeError(f'Expected one clip for {number}')
        source=files[0];meta=json.loads(source.with_suffix('.json').read_text());ch=meta['choreography']
        p=OUT/'review-scenes'/source.name
        assert p.is_file(),'Build the review clips before final validation'
        info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(p)]))
        assert [s['codec_type'] for s in info['streams']]==['video'],'Pilot must reference existing audio without encoding it'
        subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(p),'-f','null','-'],check=True)
        assert not ch['overlay']['violations'],ch['overlay']['violations']
        arrivals=[e for e in ch['alignment_action_cues'] if e['kind']=='cursor-arrival']
        assert all(e['movement_start_seconds']<e['target_seconds'] and abs(e['error_seconds'])<=.18 for e in arrivals)
        actions=[e for e in ch['events'] if e['type']=='action-timing']
        assert all(e['dwell_seconds']>=.75 and (e['phrase_end_seconds'] is None or e['seconds']>=e['phrase_end_seconds']+.25) for e in actions)
        holds=[];last_action=None
        for event in ch['events']:
            if event['type'] in ('click','file-selection','field-input','select'):last_action=event['seconds']
            if event['type']=='move' and last_action is not None:
                hold=event['seconds']-event['actual_duration']-last_action;holds.append(hold)
                assert hold>=.44,f'Movement too soon after action: {hold}'
                last_action=None
        geometry=ch['geometry_checks']
        assert all(g['pixels']['max_error_px']<=2 and not g['cursorVisible'] for g in geometry)
        assert meta['browser_errors']==0 and meta['production_mutation_requests']==0
        assert not any(k.startswith('DELETE ') for k in meta['network_requests']),'Destructive preview performed a delete'
        rows.append({'scene_id':meta['scene_id'],'duration_seconds':meta['duration_seconds'],'decode':'PASS','audio_streams':0,
                     'max_arrival_error_seconds':max([abs(c['error_seconds']) for c in arrivals],default=0),
                     'min_dwell_seconds':min([x['dwell_seconds'] for x in actions],default=None),
                     'min_post_action_hold_seconds':min(holds,default=None),
                     'geometry_checks':len(geometry),'max_geometry_error_px':max([g['pixels']['max_error_px'] for g in geometry],default=0),
                     'control_outline_violations':0,'section_cursor_emphasis':False})
    assert len(list((OUT/'scenes').glob('*.mp4')))==6,'Unexpected recaptures'
    result={'status':'PASS','scenes':rows,'preservation':preservation(),'content_drift':validate(),
            'tts_requests':0,'new_audio_encodes':0,'full_master_assembly':False,'remaining_browser_recaptures':0,
            'approval_gate':'Awaiting user visual approval; do not capture remaining scenes or assemble full MP4'}
    (OUT/'evidence/pilot-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return result

if __name__=='__main__':run()
