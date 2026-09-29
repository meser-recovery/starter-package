"""One continuous PCM soundtrack and exactly one AAC encode; no scene audio clips."""
from __future__ import annotations
import array,hashlib,html,json,math,subprocess,wave
from pathlib import Path
from modules import ROOT,CACHE,cached,members,scene_timing,sha,write_json,identity
from module_visuals import OUT,paths as visual_path,cached as visual_cached
from assemble import ffprobe,timestamp
from validate import validate


def boundary_padding(last_sample, frames, rate):
    """Continue the final sample into added silence, then decay over at most 5 ms.

    Only newly appended samples are shaped; decoded speech is never faded.
    """
    padding=array.array('h',[0])*frames
    count=min(frames,round(rate*.005))
    if count>1:
        for i in range(count): padding[i]=round(last_sample*(1-i/(count-1)))
    return padding


def pcm_timeline(spec):
    folder=OUT/'audio'; folder.mkdir(parents=True,exist_ok=True)
    config=spec['module_assembly']; rate=config['sample_rate']; pause=round(config['boundary_pause_seconds']*rate)
    master=folder/'master.wav'; rows=[]; cursor=0; boundaries=[]; old_last=0
    with wave.open(str(master.with_suffix('.tmp.wav')),'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(rate)
        for index,module in enumerate(spec['narration_modules']):
            hit=cached(spec,module)
            if not hit: raise RuntimeError('missing/stale module '+module['id'])
            source=Path(hit['folder'])/'narration.mp3'
            pcm=subprocess.check_output(['ffmpeg','-v','error','-i',str(source),'-ac','1','-ar',str(rate),'-f','s16le','-'])
            samples=array.array('h'); samples.frombytes(pcm)
            frames=max(len(samples)+round(rate*.005),round(hit['timing']['duration_seconds']*rate))
            if index:
                previous=rows[-1]
                boundaries.append({'from':previous['module_id'],'to':module['id'],'seconds':cursor/rate,
                                   'review_start_seconds':max(0,cursor/rate-5),
                                   'inserted_silence_seconds':pause/rate,
                                   'left_decoded_sample_abs':abs(old_last)/32768,
                                   'left_join_sample_abs':0.0,
                                   'right_join_sample_abs':abs(samples[0])/32768})
                out.writeframesraw(bytes(pause*2)); cursor+=pause
            decoded_peak=max(abs(x) for x in samples)/32768
            if decoded_peak>=1: raise RuntimeError('PCM clipped: '+module['id'])
            speech=[x/32768 for x in samples if abs(x)>300]
            rms=math.sqrt(sum(x*x for x in speech)/max(1,len(speech)))
            row={'module_id':module['id'],'start_sample':cursor,'start_seconds':cursor/rate,
                 'duration_seconds':frames/rate,'source_duration_seconds':hit['timing']['duration_seconds'],
                 'frames':frames,'decoded_frames':len(samples),'source_audio_sha256':hit['metadata']['audio_sha256'],
                 'decoded_pcm_sha256':hashlib.sha256(pcm).hexdigest(),
                 'tail_padding_frames':frames-len(samples),'padding_decay_max_seconds':.005,
                 'peak_dbfs':20*math.log10(max(decoded_peak,1e-9)),'speech_rms_dbfs':20*math.log10(max(rms,1e-9)),
                 'scene_ids':module['scene_ids'],'timing_sha256':hit['metadata']['timing_sha256']}
            out.writeframesraw(pcm)
            out.writeframesraw(boundary_padding(samples[-1],frames-len(samples),rate).tobytes())
            cursor+=frames; row['end_seconds']=cursor/rate; rows.append(row); old_last=samples[-1]
    master.with_suffix('.tmp.wav').replace(master)
    for i,b in enumerate(boundaries):
        left,right=rows[i],rows[i+1]
        b['loudness_difference_db']=abs(left['speech_rms_dbfs']-right['speech_rms_dbfs'])
        b['sample_discontinuity_pass']=max(b['left_join_sample_abs'],b['right_join_sample_abs'])<.02
        b['loudness_pass']=b['loudness_difference_db']<6
        b['right_start_seconds']=right['start_seconds']
    result={'sample_rate':rate,'channels':1,'format':'PCM s16le','frames':cursor,'duration_seconds':cursor/rate,
            'modules':rows,'boundaries':boundaries,'master_sha256':sha(master),'aac_encodes':0,
            'crossfades':False,'speech_trimmed':False,'decoded_speech_samples_modified':False,
            'boundary_padding':'At most 5 ms decay in appended non-speech padding only'}
    write_json(folder/'timeline.json',result)
    return result


def subtitles(spec,timeline):
    cues=[]; rows=[]
    for module,mrow in zip(spec['narration_modules'],timeline['modules']):
        for scene in members(spec,module):
            timing=scene_timing(spec,scene); a=timing['alignment']; text=scene['narration']
            offset=mrow['start_seconds']+timing['range_start_seconds']
            import re
            matches=list(re.finditer(r'\S+',text)); begin=0
            for i,match in enumerate(matches):
                first=matches[begin].start(); end=match.end()
                if len(text[first:end])>=65 or text[end-1] in '.!?…' or i==len(matches)-1:
                    start=offset+a['character_start_times_seconds'][first]
                    finish=offset+a['character_end_times_seconds'][end-1]
                    if finish<=start: raise RuntimeError('empty subtitle timing')
                    cues.append((start,finish,' '.join(text[first:end].split())))
                    begin=i+1
            rows.append({'scene_id':scene['id'],'module_id':module['id'],
                         'start_seconds':offset,'spoken_start_seconds':mrow['start_seconds']+timing['scene_start_seconds'],
                         'end_seconds':mrow['start_seconds']+timing['range_end_seconds'],
                         'timing_identity':timing['timing_identity'],'canonical_text':scene['narration']})
    if any(a<0 or b>timeline['duration_seconds']+.05 or (i and a<cues[i-1][1]-.001) for i,(a,b,text) in enumerate(cues)):
        raise RuntimeError('subtitle overlap or out of range')
    if any('[calm]' in text or '[conversational]' in text for a,b,text in cues): raise RuntimeError('delivery tags leaked')
    for suffix,srt in [('srt',True),('vtt',False)]:
        (OUT/f'tutorial.ru.{suffix}').write_text(('' if srt else 'WEBVTT\n\n')+'\n\n'.join(
            (str(i)+'\n' if srt else '')+f'{timestamp(a,srt)} --> {timestamp(b,srt)}\n{text}' for i,(a,b,text) in enumerate(cues,1))+'\n')
    return rows,len(cues)


def review(spec,manifest):
    modules=manifest['timeline']['modules']; boundaries=manifest['timeline']['boundaries']
    buttons=''.join(f'<button data-seek="{m["start_seconds"]}">{m["module_id"]} · {m["duration_seconds"]:.2f} с</button>' for m in modules)
    boundary_buttons=''.join(f'<button data-seek="{b["review_start_seconds"]}">{b["from"]} → {b["to"]} · −5 с</button>' for b in boundaries)
    scenes=''.join(f'<tr><td><button data-seek="{s["spoken_start_seconds"]}">{s["scene_id"]}</button></td><td>{s["module_id"]}</td><td>{s["spoken_start_seconds"]:.3f}</td><td>{html.escape(s["canonical_text"])}</td></tr>' for s in manifest['scenes'])
    page='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>S11 · V3 module candidate</title><link rel="icon" href="data:,"><style>*{box-sizing:border-box}body{font:16px/1.5 system-ui;background:#f1f5fa;color:#183247;margin:0}main{max-width:1280px;margin:auto;padding:24px}h1{font-size:34px}video{width:100%;background:#102d40;border-radius:12px}.controls{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}button{cursor:pointer;background:#075fa8;color:white;border:0;border-radius:7px;padding:12px;min-height:44px;font:inherit}a{color:#075fa8}table{border-collapse:collapse;width:100%}td,th{padding:12px;border-bottom:1px solid #d5e1eb;text-align:left;vertical-align:top}td:last-child{white-space:pre-line}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#e2ecf4;padding:18px}details{margin:24px 0}summary{cursor:pointer;font-weight:700}:focus-visible{outline:3px solid #ffae00;outline-offset:3px}@media(max-width:700px){main{padding:16px}table,tbody,tr{display:block}thead{display:none}td{display:block}td:last-child{font-size:14px}}</style><main><h1>S11 · Eleven v3 · N01–N08</h1><p>Новый полный candidate · 60 сцен · 13 procedural animations · реальные демонстрации Meser UI.</p><video id="player" controls preload="metadata" src="meser-audio-tutorial-v3.mp4"><track kind="subtitles" srclang="ru" label="Русский" src="tutorial.ru.vtt" default></video><h2>Модули narration</h2><div class="controls">'''+buttons+'''</div><h2>Проверка стыков модулей</h2><p>Прослушивание начинается за пять секунд до конца модуля. Это переход внутри единого master, без склейки AAC-клипов. Проверьте интонацию, отсутствие щелчков, повторов, обрезанных звуков и неестественных пауз.</p><div class="controls">'''+boundary_buttons+'''</div><p><a href="meser-audio-tutorial-v3.mp4" download>Скачать MP4</a> · <a href="audio/master.wav">PCM master WAV</a> · <a href="tutorial.ru.srt">SRT</a> · <a href="manifest.json">Manifest</a> · <a href="verification.json">Validation</a> · <a href="audio/boundary-validation.json">Boundary evidence</a></p><h2>Фактический профиль</h2><pre>'''+html.escape(json.dumps(spec['narration'],ensure_ascii=False,indent=2))+'''</pre><p>Delivery prefix — только TTS-инструкция; в canonical text и субтитрах его нет. Каждый модуль получен одним непрерывным запросом.</p><details><summary>Все сцены и canonical narration</summary><table><thead><tr><th>Scene</th><th>Module</th><th>Time</th><th>Canonical text</th></tr></thead><tbody>'''+scenes+'''</tbody></table></details></main><script>const p=document.getElementById('player');document.querySelectorAll('[data-seek]').forEach(b=>b.onclick=()=>{p.currentTime=Number(b.dataset.seek);p.play().catch(()=>{});});</script></html>'''
    (OUT/'index.html').write_text(page)


def assemble(spec):
    content=validate(); OUT.mkdir(parents=True,exist_ok=True)
    timeline=pcm_timeline(spec); rows,caption_count=subtitles(spec,timeline)
    by_id={s['id']:s for s in spec['scenes']}
    segments=OUT/'video-segments'; segments.mkdir(exist_ok=True); clips=[]
    for i,row in enumerate(rows):
        scene=by_id[row['scene_id']]; timing=scene_timing(spec,scene)
        meta=visual_cached(spec,scene,timing)
        if not meta: raise RuntimeError('missing/stale visual '+scene['id'])
        end=rows[i+1]['start_seconds'] if i+1<len(rows) else timeline['duration_seconds']
        count=round(end*30)-round(row['start_seconds']*30)
        dest=segments/f"{scene['id']}.mp4"; stamp=dest.with_suffix('.json')
        key=identity({'source':meta['sha256'],'frames':count,'captions':scene['captions']})
        if not dest.exists() or not stamp.exists() or json.loads(stamp.read_text()).get('key')!=key:
            subprocess.run(['ffmpeg','-y','-v','error','-i',str(visual_path(scene)),'-an','-vf',f'fps=30,tpad=stop_mode=clone:stop_duration=10','-frames:v',str(count),'-c:v','libx264','-preset','veryfast','-crf','21','-pix_fmt','yuv420p',str(dest)],check=True)
            write_json(stamp,{'key':key,'frames':count})
        row['visual_source']=meta['source'];row['visual_hash']=meta['visual_hash'];row['video_frames']=count
        clips.append(dest)
    listing=segments/'video.ffconcat';listing.write_text('ffconcat version 1.0\n'+''.join(f"file '{p}'\n" for p in clips))
    final=OUT/'meser-audio-tutorial-v3.mp4'; candidate=final.with_suffix('.tmp.mp4')
    # The concat input is VIDEO ONLY. AAC is encoded once from the PCM master.
    command=['ffmpeg','-y','-v','error','-safe','0','-f','concat','-i',str(listing),'-i',str(OUT/'audio/master.wav'),
             '-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-b:a','160k','-t',str(timeline['duration_seconds']),'-movflags','+faststart',str(candidate)]
    subprocess.run(command,check=True)
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(candidate),'-f','null','-'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    candidate.replace(final)
    timeline['aac_encodes']=1
    manifest={'repo_head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'content_validation':content,
              'spec_sha256':sha(ROOT/'tutorial.yaml'),'timeline':timeline,'scenes':rows,'subtitle_cues':caption_count,
              'final':str(final),'final_sha256':sha(final),'final_duration_seconds':float(ffprobe(final)['format']['duration']),
              'audio_pipeline':'8 MP3 decodes → continuous PCM s16le timeline → one final AAC encode',
              'ffmpeg_final_command':command,'production_mutation_requests':0,'full_decode':'PASS'}
    write_json(OUT/'manifest.json',manifest);review(spec,manifest)
    from module_audio_qa import boundary_checks
    boundary_checks(spec)
    return {'final':str(final),'duration_seconds':timeline['duration_seconds'],'scenes':len(rows),'aac_encodes':1}


def browser_action_errors(scene_id,evidence):
    errors=[]
    for cue in evidence.get('alignment_action_cues',[]):
        error=abs(cue['actual_seconds']*evidence['retime_factor']-cue['target_seconds'])
        assert error<=.1, f"browser action timing drift: {scene_id} ({error:.3f}s)"
        errors.append(error)
    return errors


def verify(spec):
    content=validate(); manifest=json.loads((OUT/'manifest.json').read_text()); info=ffprobe(Path(manifest['final']))
    assert manifest['spec_sha256']==sha(ROOT/'tutorial.yaml')
    assert manifest['final_sha256']==sha(manifest['final'])
    assert len(manifest['scenes'])==60 and manifest['timeline']['aac_encodes']==1
    animation=[r for r in manifest['scenes'] if r['visual_source']=='procedural-pilot-language']
    assert len(animation)==13
    for m,row in zip(spec['narration_modules'],manifest['timeline']['modules']):
        hit=cached(spec,m); assert hit and hit['metadata']['audio_sha256']==row['source_audio_sha256']
    browser_cue_errors=[]
    for scene in spec['scenes']:
        meta=visual_cached(spec,scene,scene_timing(spec,scene));assert meta
        browser_cue_errors.extend(browser_action_errors(scene['id'],meta.get('browser_evidence',{})))
    streams=info['streams'];video=next(s for s in streams if s['codec_type']=='video');audio=next(s for s in streams if s['codec_type']=='audio')
    assert (video['codec_name'],video['width'],video['height'],video['r_frame_rate'])==('h264',1920,1080,'30/1')
    assert audio['codec_name']=='aac'
    assert abs(float(info['format']['duration'])-manifest['timeline']['duration_seconds'])<.1
    from verify import cue_times
    cues=cue_times(OUT/'tutorial.ru.srt');assert all(0<=a<b<=float(info['format']['duration'])+.05 for a,b in cues)
    assert all(cues[i][0]>=cues[i-1][1] for i in range(1,len(cues)))
    from module_audio_qa import boundary_checks
    boundary_report=boundary_checks(spec)
    assert boundary_report['acoustic_status']=='PASS', 'module acoustic boundary check needs review'
    assert boundary_report.get('speech_boundary_check',{}).get('status')!='REVIEW', 'ASR boundary mismatch needs review'
    report={'status':'PASS','content_validation':content,'modules':8,'scenes':60,'new_explanatory_scenes':13,
            'real_browser_scenes':47,'subtitle_cues':len(cues),'full_decode':manifest['full_decode'],
            'aac_encodes':1,'production_mutation_requests':0,'duration_seconds':manifest['final_duration_seconds'],
            'acoustic_boundaries':boundary_report['acoustic_status'],
            'independent_asr_windows':len(boundary_report.get('independent_asr',{}).get('windows',[])),
            'speech_boundary_check':boundary_report.get('speech_boundary_check',{}).get('status','NOT_RUN'),
            'browser_action_cues':len(browser_cue_errors),
            'max_browser_cue_error_seconds':max(browser_cue_errors,default=0),
            'human_prosody_review':boundary_report['human_prosody_review']}
    write_json(OUT/'verification.json',report);return report
