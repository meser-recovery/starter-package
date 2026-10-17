"""Assemble the exact fourteen approved S11 blocks, without generating media."""
from __future__ import annotations

import array
import hashlib
import html
import json
import re
import subprocess
import wave
from pathlib import Path

from audio_approval import approval_records, validate_approval, validate_block_approval
from b01_block import check_embedded_subtitles, timestamp
from module_assemble import boundary_padding
from modules import sha, write_json
from validate import ROOT, validate

OUT = ROOT/'generated/s11-final-review'
RATE, FPS, LEAD, QUIET = 44100, 30, .6, 8
PAUSE_SAMPLES = 35280
FRAME_BYTES = 1920*1080*3//2
CURRENT = {
    'B01':'a8d799b77b7e09e65a010b6ccb4f3a1989eb0b45cf56635a8238fc89498819b4',
    'B02':'8b122abd98ca9552d568c7179e0627a31547eb78f843cb34b070bdfb8b15ca6d',
    'B03':'6535356a17c3b2cb885a423a41418ac3ca6616d97b32568f1512e485966d6206',
    'B04':'f14978c373710fd5b8e5a579a4f718079ada4ea1e0ffd2dd24409d80a52b99bb',
    'B05':'04c281e73e288b9b8fc104b13af3c1a9dd23d64be159ac1a29dec36e4de8ff31',
    'B06':'452afd7e19e1ecbc1542c1e42d00f03de5366f51d5fb802f2e445df9b2970ace',
    'B07':'7055e5a42dc4616ab8fd1a6d504038ef849d447218f812eaec39e2b75ae7c577',
    'B08':'22ef673a36f21cf8773301fd20d9ee97e2f6e30708c84267980b8132d644e8ca',
    'B09':'5776bf60053d09fad28e0879119e5a9e41bf4daf294e72f411fb465dac2e10d0',
    'B10':'32376f595a1e1e937341e26827698a3a9a416a1edc8c72b0b74a1dcf835bf58c',
    'B11':'ce69f239312b0a2daec9117c133b78c86c9615b34423eb00d666470da3b4c9a5',
    'B12':'115862d1fb0bd4b04fc38c08e2671105895cabf7f7e84473733eef8ee7e32ffe',
    'B13':'a28c96a5d7b5b96db7ab24e69ec55459b8a4e165ba31d9f04e565822ce35e81d',
    'B14':'e64b61ebf5933796c918682babadfd049a32294bd481b25116f19982956a04a1',
}


def probe(path):
    return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)]))


def pcm(path):
    with wave.open(str(path)) as wav:
        if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate()) != (1,2,RATE):
            raise RuntimeError('approved WAV must remain mono 44.1 kHz s16')
        return wav.readframes(wav.getnframes())


def signal_edges(data):
    samples=array.array('h');samples.frombytes(data)
    first=next(i for i,x in enumerate(samples) if abs(x)>QUIET)
    last=len(samples)-1-next(i for i,x in enumerate(reversed(samples)) if abs(x)>QUIET)
    return first,last,samples[-1]


def audit(*, write_manifest=True):
    content=validate();spec=json.loads((ROOT/'tutorial.yaml').read_text())
    if [m['id'] for m in spec['narration_modules']] != list(CURRENT):
        raise RuntimeError('final assembly requires all fourteen blocks in canonical order')
    blocks=[];protected={}
    def pin(path):
        path=Path(path);stat=path.stat()
        key=str(path.relative_to(ROOT))
        protected[key]={'path':key,'sha256':sha(path),'bytes':stat.st_size,'mtime_ns':stat.st_mtime_ns}
        return protected[key]
    for module in spec['narration_modules']:
        bid=module['id'];records=approval_records(spec,bid)
        approval=validate_approval(spec,bid);block=validate_block_approval(bid)
        if block['video_sha256'] != CURRENT[bid]:
            raise RuntimeError(f'{bid} is not the latest user-approved candidate')
        for p in (ROOT/f'approvals/{bid}-audio.json',ROOT/f'approvals/{bid}-block.json'):
            pin(p)
        take=records['audio']['approved_take']
        for key in ('mp3','wav','alignment'):
            pin(ROOT/take[key])
        for reference in records['audio'].values():
            if isinstance(reference,dict) and 'path' in reference and 'sha256' in reference:
                pin(ROOT/reference['path'])
        for reference in records['audio'].get('source',{}).values():
            if isinstance(reference,str) and reference.startswith('generated/') and (ROOT/reference).is_file():
                pin(ROOT/reference)
        for key in ('video','subtitle_srt','subtitle_vtt','video_audio_timeline','report','verification'):
            pin(ROOT/block[key])
        for source in block['scene_sources']:
            pin(ROOT/source['path'])
        data=pcm(approval['wav_path']);timeline=pcm(ROOT/block['video_audio_timeline'])
        lead=round(LEAD*RATE)*2
        if timeline[:lead] != bytes(lead) or timeline[lead:lead+len(data)] != data or any(timeline[lead+len(data):]):
            raise RuntimeError(f'{bid} approved block timeline does not contain exact approved PCM')
        info=probe(ROOT/block['video']);stream=next(s for s in info['streams'] if s['codec_type']=='video')
        if (stream['width'],stream['height'],stream['r_frame_rate'],stream['pix_fmt']) != (1920,1080,'30/1','yuv420p'):
            raise RuntimeError('approved block video format changed')
        blocks.append({'block_id':bid,'title':module['title'],'approval':block,'audio':take,
                       'timing':approval['timing'],'video_source':block['video'],
                       'video_source_sha256':block['video_sha256'],'video_source_frames':int(stream['nb_frames']),
                       'wav_source':take['wav'],'pcm_samples':len(data)//2,'lead_seconds':LEAD})
        print(json.dumps({'audited_block':bid,'video_sha256':block['video_sha256']}),flush=True)
    if write_manifest:OUT.mkdir(parents=True,exist_ok=True)
    manifest={'status':'ALL_INPUTS_APPROVED','content_validation':content,'spec_sha256':sha(ROOT/'tutorial.yaml'),
              'blocks':blocks,'protected_files':list(protected.values()),'new_tts_requests':0,
              'video_source_rule':'Decode only current approved block MP4 pictures; raw scene sources are verified provenance, never recaptured.',
              'historical_media_consumed':False,'production_mutation_requests':0}
    if write_manifest:write_json(OUT/'input-manifest.json',manifest)
    return spec,manifest


def make_timeline(manifest):
    rows=manifest['blocks'];pieces=[bytes(round(LEAD*RATE)*2)];cursor=round(LEAD*RATE);boundaries=[]
    previous_last=None
    for index,row in enumerate(rows):
        data=pcm(ROOT/row['wav_source']);first,last,tail=signal_edges(data)
        if index:
            # The 0.6 s incoming visual pre-roll is part of this gap, not an
            # additional gap. Retain every original PCM sample. A <=5 ms decay
            # touches appended samples only, avoiding a jump from a nonzero tail.
            previous=rows[index-1]
            decay=boundary_padding(previous_last,round(.005*RATE),RATE).tobytes()
            d=array.array('h');d.frombytes(decay)
            voiced=[i for i,x in enumerate(d) if abs(x)>QUIET]
            prev_last_global=previous['pcm_start_sample']+previous['last_signal_source_sample']
            if voiced:prev_last_global=cursor+voiced[-1]
            pieces.append(decay);cursor+=len(d)
            target=prev_last_global+1+PAUSE_SAMPLES-first
            missing=target-cursor
            if missing<0:
                raise RuntimeError('existing quiet interval exceeds contract; do not trim approved speech')
            pieces.append(bytes(missing*2));cursor+=missing
            boundaries.append({'from':previous['block_id'],'to':row['block_id'],
                               'last_signal_sample':prev_last_global,'first_signal_sample':cursor+first,
                               'quiet_samples':PAUSE_SAMPLES,'quiet_seconds':.8,
                               'appended_decay_samples':len(d),'added_zero_samples':missing,
                               'existing_right_quiet_samples':first,
                               'visual_pre_roll_included_seconds':LEAD})
        row.update(pcm_start_sample=cursor,audio_start_seconds=cursor/RATE,
                   first_signal_source_sample=first,last_signal_source_sample=last,
                   source_pcm_sha256=hashlib.sha256(data).hexdigest(),
                   video_start_frame=round((cursor/RATE-LEAD)*FPS))
        row['video_start_seconds']=row['video_start_frame']/FPS
        row['subtitle_shift_seconds']=cursor/RATE-LEAD
        pieces.append(data);cursor+=len(data)//2;previous_last=tail
    final_frames=rows[-1]['video_start_frame']+rows[-1]['video_source_frames']
    final_samples=final_frames*(RATE//FPS)
    if final_samples<cursor+round(.005*RATE):raise RuntimeError('final visual does not retain the closing audio')
    pieces.append(boundary_padding(previous_last,final_samples-cursor,RATE).tobytes())
    master=OUT/'S11-master.wav'
    with wave.open(str(master),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(RATE)
        for part in pieces:wav.writeframesraw(part)
    for i,row in enumerate(rows):
        end=rows[i+1]['video_start_frame'] if i+1<len(rows) else final_frames
        row['allocated_video_frames']=end-row['video_start_frame']
        row['held_last_frame_count']=row['allocated_video_frames']-row['video_source_frames']
        if row['held_last_frame_count']<0:raise RuntimeError('approved videos would overlap; review required')
    result={'sample_rate':RATE,'sample_format':'s16le mono','samples':final_samples,'duration_seconds':final_samples/RATE,
            'video_frames':final_frames,'boundaries':boundaries,'master_wav':'S11-master.wav','master_sha256':sha(master),
            'all_source_pcm_samples_preserved':True,'speed_processing':False,'crossfades':False,
            'boundary_rule':'0.8 s total quiet at abs(sample)<=8 (-72.25 dBFS); incoming 0.6 s picture lead included. <=5 ms decay in added samples only.'}
    manifest['timeline']=result
    write_json(OUT/'timeline.json',result)
    return result


def parse_srt(path):
    cues=[]
    def seconds(text):
        h,m,s=text.replace(',','.').split(':');return int(h)*3600+int(m)*60+float(s)
    for cue in re.split(r'\n\s*\n',Path(path).read_text().strip()):
        lines=cue.splitlines();a,b=lines[1].split(' --> ')
        cues.append((seconds(a),seconds(b),' '.join(lines[2:])))
    return cues


def subtitles_and_navigation(spec,manifest):
    cues=[];scenes=[]
    for row,module in zip(manifest['blocks'],spec['narration_modules']):
        shift=row['subtitle_shift_seconds'];source_cues=parse_srt(ROOT/row['approval']['subtitle_srt'])
        cues.extend((a+shift,b+shift,text) for a,b,text in source_cues)
        report=json.loads((ROOT/row['approval']['report']).read_text())
        counts=report.get('scene_frame_counts');source_frame=0
        for index,scene_id in enumerate(module['scene_ids']):
            timing=next(s for s in row['timing']['scenes'] if s['scene_id']==scene_id)
            if not counts:source_frame=0 if index==0 else round((LEAD+timing['range_start_seconds'])*FPS)
            scenes.append({'scene_id':scene_id,'block_id':row['block_id'],'source_frame':source_frame,
                           'frame':row['video_start_frame']+source_frame,
                           'seconds':(row['video_start_frame']+source_frame)/FPS})
            if counts:source_frame+=counts[scene_id]
    canonical=' '.join(' '.join(m['narration'].split()) for m in spec['narration_modules'])
    if ' '.join(text for a,b,text in cues)!=canonical or not canonical.endswith('Спасибо за внимание.'):
        raise RuntimeError('global subtitles differ from current canonical narration')
    if any(a<0 or b<=a or b>manifest['timeline']['duration_seconds']+.01 or (i and a<cues[i-1][1]) for i,(a,b,t) in enumerate(cues)):
        raise RuntimeError('global subtitle order or timing invalid')
    for suffix,vtt in [('srt',False),('vtt',True)]:
        body=('WEBVTT\n\n' if vtt else '')+'\n\n'.join(
            ('' if vtt else f'{i}\n')+f'{timestamp(a,vtt=vtt)} --> {timestamp(b,vtt=vtt)}\n{text}'
            for i,(a,b,text) in enumerate(cues,1))+'\n'
        (OUT/f'S11.ru.{suffix}').write_text(body)
    from modules import request_text_and_indices
    characters=[];starts=[];ends=[];block_ranges=[]
    for row,module in zip(manifest['blocks'],spec['narration_modules']):
        request,indices=request_text_and_indices(spec,module)
        alignment=row['timing']['alignment']
        if ''.join(alignment['characters']) != request:
            raise RuntimeError('approved request character mapping changed')
        if characters:
            for character in '\n\n':
                characters.append(character);starts.append(row['audio_start_seconds']);ends.append(row['audio_start_seconds'])
        first=len(characters)
        for index in indices:
            characters.append(alignment['characters'][index])
            starts.append(row['audio_start_seconds']+alignment['character_start_times_seconds'][index])
            ends.append(row['audio_start_seconds']+alignment['character_end_times_seconds'][index])
        block_ranges.append({'block_id':row['block_id'],'start_offset':first,'end_offset':len(characters),
                             'source_alignment':row['audio']['alignment'],
                             'source_alignment_sha256':row['audio']['alignment_sha256'],
                             'audio_start_seconds':row['audio_start_seconds']})
    if ' '.join(''.join(characters).split())!=canonical:
        raise RuntimeError('global alignment content drift')
    write_json(OUT/'S11-alignment.json',{'characters':characters,'character_start_times_seconds':starts,
        'character_end_times_seconds':ends,'blocks':block_ranges,'delivery_markup_included':False})
    manifest['global_alignment_sha256']=sha(OUT/'S11-alignment.json')
    manifest['scenes']=scenes;manifest['subtitle_cues']=len(cues)
    manifest['scene_boundaries']=[{'from':left['scene_id'],'to':right['scene_id'],'frame':right['frame'],
                                  'seconds':right['seconds'],'block_boundary':left['block_id']!=right['block_id']}
                                 for left,right in zip(scenes,scenes[1:])]
    if len(scenes)!=54 or len(manifest['scene_boundaries'])!=53:raise RuntimeError('technical scene map changed')
    write_json(OUT/'navigation.json',{'blocks':[{'block_id':r['block_id'],'title':r['title'],'seconds':r['video_start_seconds']} for r in manifest['blocks']],
                                     'scenes':scenes,'boundaries':manifest['scene_boundaries']})


def preservation(manifest):
    changed=[]
    for row in manifest['protected_files']:
        path=ROOT/row['path'];stat=path.stat()
        if sha(path)!=row['sha256'] or stat.st_size!=row['bytes'] or stat.st_mtime_ns!=row['mtime_ns']:
            changed.append(row['path'])
    if changed:raise RuntimeError('approved originals changed: '+str(changed))
    result={'status':'PASS','files_checked':len(manifest['protected_files']),'sha256_size_mtime_unchanged':True,
            'new_tts_requests':0,'blocks_regenerated':0}
    write_json(OUT/'source-preservation.json',result);return result


def assemble():
    if (OUT/'S11.mp4').exists():
        raise RuntimeError('complete candidate already exists; verify it or preserve it before another assembly')
    spec,manifest=audit();make_timeline(manifest);subtitles_and_navigation(spec,manifest)
    write_json(OUT/'input-manifest.json',manifest)
    final=OUT/'S11.mp4';candidate=OUT/'S11.tmp.mp4'
    command=['ffmpeg','-y','-v','error','-f','rawvideo','-pixel_format','yuv420p','-video_size','1920x1080',
             '-framerate','30','-i','pipe:0','-i',str(OUT/'S11-master.wav'),'-i',str(OUT/'S11.ru.srt'),
             '-map','0:v:0','-map','1:a:0','-map','2:s:0','-c:v','libx264','-preset','veryfast','-crf','20',
             '-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-c:s','mov_text','-metadata:s:s:0','language=rus',
             '-frames:v',str(manifest['timeline']['video_frames']),'-movflags','+faststart',str(candidate)]
    with (OUT/'encode.log').open('wb') as log:
        encoder=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=log)
        try:
            for row in manifest['blocks']:
                count=row['allocated_video_frames'];source=ROOT/row['video_source']
                decoder=subprocess.Popen(['ffmpeg','-v','error','-xerror','-i',str(source),'-an',
                    '-vf',f'scale=1920:1080:flags=lanczos,settb=1/30,setpts=N,tpad=stop_mode=clone:stop={row["held_last_frame_count"]},setpts=N',
                    '-frames:v',str(count),'-fps_mode','passthrough','-pix_fmt','yuv420p','-f','rawvideo','pipe:1'],stdout=subprocess.PIPE)
                copied=0;digest=hashlib.sha256()
                try:
                    while chunk:=decoder.stdout.read(1024*1024):
                        encoder.stdin.write(chunk);digest.update(chunk);copied+=len(chunk)
                finally:decoder.stdout.close()
                if decoder.wait() or copied!=count*FRAME_BYTES:raise RuntimeError(f'visual frame stream differs: {row["block_id"]} {copied}/{count*FRAME_BYTES} bytes')
                row['normalized_input_frames_sha256']=digest.hexdigest()
                print(json.dumps({'decoded_approved_block':row['block_id'],'frames':count,'held_frames':row['held_last_frame_count']}),flush=True)
            encoder.stdin.close()
            if encoder.wait():raise RuntimeError('final encode failed; see encode.log')
        finally:
            if encoder.poll() is None:encoder.kill();encoder.wait()
    canonical=' '.join(' '.join(m['narration'].split()) for m in spec['narration_modules'])
    check=check_embedded_subtitles(candidate,OUT/'S11.ru.srt',canonical)
    candidate.replace(final)
    manifest.update(status='READY FOR S11 ACCEPTANCE',final='S11.mp4',final_sha256=sha(final),
                    final_duration_seconds=float(probe(final)['format']['duration']),aac_encodes=1,h264_final_encodes=1,
                    ffmpeg_final_command=command,embedded_subtitle_check=check)
    preservation(manifest);write_json(OUT/'manifest.json',manifest)
    review(manifest)
    return {'status':manifest['status'],'duration_seconds':manifest['final_duration_seconds'],'sha256':manifest['final_sha256']}


def review(manifest):
    blocks=''.join(f'<button data-seek="{r["video_start_seconds"]:.6f}">{r["block_id"]} · {html.escape(r["title"])}</button>' for r in manifest['blocks'])
    joins=''.join(f'<button data-seek="{max(0,r["seconds"]-2):.6f}">{r["from"]} → {r["to"]}</button>' for r in manifest['scene_boundaries'])
    (OUT/'index.html').write_text(f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>S11 · Полный кандидат</title><style>body{{margin:0;background:#0b2238;color:#eaf5ff;font:17px/1.5 system-ui}}main{{max-width:1200px;margin:auto;padding:24px}}video{{display:block;width:100%;aspect-ratio:16/9;background:#071522;margin:20px 0}}button,a{{display:inline-block;font:inherit;color:#eaf5ff;background:#245c87;border:1px solid #5799c8;border-radius:6px;padding:8px 12px;margin:4px;text-decoration:none}}button{{cursor:pointer}}nav{{display:flex;flex-wrap:wrap}}summary{{cursor:pointer}}</style>
<main><h1>S11 · Полный ролик B01–B14</h1><p>READY FOR S11 ACCEPTANCE · утверждённые блоки · 0 новых TTS</p>
<video id="review" controls playsinline preload="metadata"><source src="S11.mp4?v={manifest['final_sha256'][:12]}" type="video/mp4"><track kind="subtitles" src="S11.ru.vtt" srclang="ru" label="Русские" default></video>
<nav aria-label="Блоки">{blocks}</nav><details><summary>53 стыка сцен · просмотр за 2 секунды до перехода</summary><nav>{joins}</nav></details>
<p><a href="S11.mp4" download>MP4</a><a href="S11.ru.srt" download>SRT</a><a href="S11.ru.vtt" download>VTT</a><a href="manifest.json">Manifest</a><a href="verification.json">Проверки</a><a href="boundary-report.json">Стыки</a></p>
<p>SHA-256: <code>{manifest['final_sha256']}</code></p></main><script>document.querySelectorAll('[data-seek]').forEach(b=>b.onclick=()=>{{const v=document.getElementById('review');v.currentTime=Number(b.dataset.seek);v.play()}});</script></html>''')


if __name__=='__main__':
    print(json.dumps(assemble(),ensure_ascii=False,indent=2))
