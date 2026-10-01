"""Canonical continuous narration modules, paid-request ledger and scene/phrase ranges."""
from __future__ import annotations
import base64
import hashlib
import json
import re
import shutil
import subprocess
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from narration import api_key, probe_duration
from validate import ROOT

CACHE = ROOT / 'generated/narration-blocks-v2'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def write_json(path, value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    candidate=path.with_suffix(path.suffix+'.tmp')
    candidate.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    candidate.replace(path)


def members(spec, module):
    by_id={s['id']:s for s in spec['scenes']}
    return [by_id[sid] for sid in module['scene_ids']]


def spoken_text(spec, module):
    if spec['schema_version'] == 1:
        return '\n\n'.join(s['narration'] for s in members(spec,module))
    return module['narration']


def request_body(spec, module):
    settings=spec['narration']
    body={'text':settings['delivery_prefix']+'\n'+spoken_text(spec,module),
          'model_id':settings['model_id'],'language_code':settings['language_code'],
          'voice_settings':settings['voice_settings']}
    if module['pronunciation_dictionary_locators']:
        body['pronunciation_dictionary_locators']=module['pronunciation_dictionary_locators']
    return body


def narration_hash(spec, module):
    if spec['schema_version'] == 1:
        return identity({'module_id':module['id'],'ordered_scene_ids':module['scene_ids'],
                         'canonical_spoken_text':spoken_text(spec,module),
                         'profile':spec['narration'],'pronunciation_configuration':module['pronunciation_dictionary_locators']})
    return identity({'model_version':spec['schema_version'],'module_id':module['id'],
                     'ordered_scene_mapping':[(s['id'],s['start_offset'],s['end_offset']) for s in members(spec,module)],
                     'canonical_spoken_text':spoken_text(spec,module),
                     'profile':spec['narration'],'pronunciation_configuration':module['pronunciation_dictionary_locators']})


def map_timing(spec, module, alignment, duration):
    request=request_body(spec,module)['text']
    if not alignment or ''.join(alignment['characters'])!=request:
        raise RuntimeError('module alignment differs from exact request text')
    starts,ends=alignment['character_start_times_seconds'],alignment['character_end_times_seconds']
    if len(starts)!=len(request) or len(ends)!=len(request) or not all(0<=a<=b<=duration+.1 for a,b in zip(starts,ends)) or any(a>b for a,b in zip(starts,starts[1:])):
        raise RuntimeError('invalid module character timing')
    prefix=len(spec['narration']['delivery_prefix'])+1
    legacy=spec['schema_version']==1
    offset=0; ranges=[]
    for scene in members(spec,module):
        if not legacy: offset=scene['start_offset']
        text=scene['narration']; n=len(text); r=prefix+offset
        assert request[r:r+n]==text
        first=next((i for i,c in enumerate(text) if not c.isspace()),None)
        last=next((i for i in range(n-1,-1,-1) if not text[i].isspace()),None)
        if first is None or last is None: raise RuntimeError('empty scene narration')
        phrase_ranges=[]
        for match in re.finditer(r'\S(?:[^.!?]*?)[.!?](?=\s|$)|\S[^.!?]*$',text):
            phrase_ranges.append({'text':match.group(),'canonical_start_offset':offset+match.start(),
                                  'canonical_end_offset':offset+match.end(),
                                  'start_seconds':starts[r+match.start()],'end_seconds':ends[r+match.end()-1]})
        ranges.append({'module_id':module['id'],'scene_id':scene['id'],
                       'scene_start_seconds':starts[r+first],'scene_end_seconds':ends[r+last],
                       'canonical_start_offset':offset,'canonical_end_offset':offset+n if legacy else scene['end_offset'],
                       'request_start_offset':r,'phrases':phrase_ranges})
        if legacy: offset+=n+2
    # Full continuous module is covered once, including pauses between logical scenes.
    for i,row in enumerate(ranges):
        row['range_start_seconds']=0.0 if i==0 else row['scene_start_seconds']
        row['range_end_seconds']=ranges[i+1]['scene_start_seconds'] if i+1<len(ranges) else duration
    return {'module_id':module['id'],'duration_seconds':duration,'alignment':alignment,
            'canonical_spoken_text':spoken_text(spec,module),'request_prefix':spec['narration']['delivery_prefix'],
            'scenes':ranges}


def cached(spec, module, root=CACHE):
    folder=root/module['id']
    try:
        meta=json.loads((folder/'metadata.json').read_text())
        timing=json.loads((folder/'timing.json').read_text())
        if meta['http_status']!=200 or meta['decode']!='PASS' or meta['tts_requests_for_this_take']!=1:
            return None
        if meta['narration_hash']!=narration_hash(spec,module) or sha(folder/'narration.mp3')!=meta['audio_sha256'] or sha(folder/'timing.json')!=meta['timing_sha256']:
            return None
        expected=map_timing(spec,module,timing['alignment'],timing['duration_seconds'])
        if timing!=expected or abs(probe_duration(folder/'narration.mp3')-timing['duration_seconds'])>.05:
            return None
        return {'metadata':meta,'timing':timing,'folder':str(folder)}
    except (OSError,KeyError,ValueError,RuntimeError,subprocess.CalledProcessError):
        return None


def generate(spec,module,force=False,root=CACHE):
    hit=cached(spec,module,root)
    if hit and not force:
        return hit,'HIT'
    folder=root/module['id']; folder.mkdir(parents=True,exist_ok=True)
    body=request_body(spec,module); profile=spec['narration']
    url=f"https://api.elevenlabs.io/v1/text-to-speech/{profile['voice_id']}/with-timestamps?output_format={profile['output_format']}"
    payload=json.dumps(body,ensure_ascii=False).encode()
    request=urllib.request.Request(url,payload,{'xi-api-key':api_key(),'Content-Type':'application/json'},method='POST')
    attempt={'attempt_id':uuid.uuid4().hex,'module_id':module['id'],'narration_hash':narration_hash(spec,module),'force':force,
             'started_utc':datetime.now(timezone.utc).isoformat(),'endpoint':url,'characters':len(spoken_text(spec,module)),
             'request_body_sha256':hashlib.sha256(payload).hexdigest()}
    with (root/'requests.jsonl').open('a') as log:
        log.write(json.dumps({**attempt,'event':'started'})+'\n')
    try:
        with urllib.request.urlopen(request,timeout=480) as response:
            result=json.load(response); request_id=response.headers.get('request-id'); status=response.status
    except urllib.error.HTTPError as error:
        with (root/'requests.jsonl').open('a') as log:
            log.write(json.dumps({'attempt_id':attempt['attempt_id'],'event':'http_error','http_status':error.code})+'\n')
        raise RuntimeError(f"ElevenLabs HTTP {error.code} for {module['id']}; no automatic retry") from None
    except Exception as error:
        with (root/'requests.jsonl').open('a') as log:
            log.write(json.dumps({'attempt_id':attempt['attempt_id'],'event':'transport_error','error_type':type(error).__name__})+'\n')
        raise
    with (root/'requests.jsonl').open('a') as log:
        log.write(json.dumps({'attempt_id':attempt['attempt_id'],'event':'response','http_status':status,
                              'request_id':request_id})+'\n')
    # Preserve the paid response before validation so failures can be diagnosed without another request.
    pending=folder/'pending'/attempt['attempt_id']; pending.mkdir(parents=True,exist_ok=True)
    write_json(pending/'raw-response.json',result)
    audio=base64.b64decode(result.pop('audio_base64'),validate=True)
    (pending/'narration.mp3').write_bytes(audio)
    write_json(pending/'response-timing.json',result)
    write_json(pending/'request.json',body)
    if status!=200: raise RuntimeError(f'Unexpected ElevenLabs HTTP status: {status}')
    duration=probe_duration(pending/'narration.mp3')
    timing=map_timing(spec,module,result.get('alignment'),duration)
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(pending/'narration.mp3'),'-f','null','-'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    write_json(pending/'timing.json',timing)
    meta={**attempt,'http_status':status,'request_id':request_id,'duration_seconds':duration,'decode':'PASS',
          'audio_sha256':sha(pending/'narration.mp3'),'timing_sha256':sha(pending/'timing.json'),
          'tts_requests_for_this_take':1,'scene_audio_files':False,'request':body}
    write_json(pending/'metadata.json',meta)
    (pending/'canonical-spoken-text.txt').write_text(spoken_text(spec,module))
    (pending/'request-text.txt').write_text(body['text'])
    if hit:
        archive=folder/'takes'/hit['metadata']['audio_sha256']
        archive.mkdir(parents=True,exist_ok=True)
        for name in ['narration.mp3','timing.json','request.json','request-text.txt','canonical-spoken-text.txt','response-timing.json','metadata.json']:
            source=folder/name
            if source.exists() and not (archive/name).exists(): shutil.copy2(source,archive/name)
    for name in ['narration.mp3','timing.json','request.json','request-text.txt','canonical-spoken-text.txt','response-timing.json','metadata.json']:
        (pending/name).replace(folder/name)
    hit=cached(spec,module,root)
    if not hit: raise RuntimeError('new module failed cache validation')
    return hit,'MISS'


def selection(spec, module_id=None, scene_id=None, chapter=None):
    if module_id and module_id not in [m['id'] for m in spec['narration_modules']]:
        raise ValueError('unknown module: '+module_id)
    if scene_id and scene_id not in [s['id'] for s in spec['scenes']]:
        raise ValueError('unknown scene: '+scene_id)
    selected=[m for m in spec['narration_modules'] if (not module_id or m['id']==module_id)
              and (not scene_id or scene_id in m['scene_ids'])
              and (not chapter or any(s['chapter']==chapter for s in members(spec,m)))]
    if not selected: raise ValueError('selection has no narration modules')
    return selected


def plan(spec,selected,force=False,root=CACHE):
    ids={m['id'] for m in selected}; rows=[]
    for module in spec['narration_modules']:
        hit=cached(spec,module,root)
        spend=module['id'] in ids and (force or not hit)
        rows.append({'module_id':module['id'],'selected':module['id'] in ids,'cache':'HIT' if hit else 'MISS',
                     'tts_requests':int(spend),'canonical_characters':len(spoken_text(spec,module)),
                     'characters_to_generate':len(spoken_text(spec,module)) if spend else 0,
                     'narration_hash':narration_hash(spec,module),'scene_ids':module['scene_ids']})
    return {'modules':rows,'tts_requests':sum(x['tts_requests'] for x in rows),
            'characters_to_generate':sum(x['characters_to_generate'] for x in rows),
            'unselected_modules_never_generated':True}


def scene_timing(spec,scene,root=CACHE):
    module=next(m for m in spec['narration_modules'] if scene['id'] in m['scene_ids'])
    hit=cached(spec,module,root)
    if not hit: raise RuntimeError('module cache missing/stale: '+module['id'])
    row=next(r for r in hit['timing']['scenes'] if r['scene_id']==scene['id'])
    start=row['range_start_seconds']; length=row['range_end_seconds']-start
    a=hit['timing']['alignment']; first=row['request_start_offset']; last=first+len(scene['narration'])
    local={'characters':a['characters'][first:last],
           'character_start_times_seconds':[max(0,x-start) for x in a['character_start_times_seconds'][first:last]],
           'character_end_times_seconds':[max(0,x-start) for x in a['character_end_times_seconds'][first:last]]}
    cue_list=[]
    for cue in spec.get('visual_cues',{}).get(scene['id'],[]):
        index=scene['narration'].index(cue['text'])
        cue_list.append({'text':cue['text'],'phase':cue['phase'],'seconds':local['character_start_times_seconds'][index]})
    return {**row,'alignment':local,'duration_seconds':length,'visual_cues':cue_list,
            'timing_identity':identity({'audio':hit['metadata']['audio_sha256'],'row':row,'alignment':local,'cues':cue_list})}
