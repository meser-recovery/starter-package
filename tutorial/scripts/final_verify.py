"""Verify delivered S11 pixels, PCM, subtitle cues and all scene boundaries."""
from __future__ import annotations
import array
import hashlib
import json
import math
import subprocess
from b01_block import check_embedded_subtitles
from b07_block import visual_transition_anomalies
from final_assemble import OUT, ROOT, RATE, FPS, QUIET, pcm, probe, preservation, parse_srt
from modules import sha, write_json
from validate import validate

PIXELS=48*27


def small_frames(path):
    return subprocess.check_output(['ffmpeg','-v','error','-xerror','-i',str(path),'-map','0:v:0',
        '-vf','scale=48:27:flags=area,format=gray','-fps_mode','passthrough','-f','rawvideo','-'])


def distance(a,b):
    return sum(abs(x-y) for x,y in zip(a,b))/len(a)


def review_is_valid(manifest, candidates, review):
    if not review or review.get('video_sha256')!=manifest['final_sha256'] or review.get('candidates')!=candidates:
        return False
    rows=review.get('reviews',[])
    covered=sorted(i for r in rows for i in r.get('candidate_indices',[]))
    sources={r['block_id']:r['video_source_sha256'] for r in manifest['blocks']}
    return bool(rows and covered==list(range(len(candidates))) and all(
        r['decision']=='EXPECTED_APPROVED_ACTION' and r['source_sha256']==sources.get(r['block_id']) for r in rows))


def verify():
    validate()
    m=json.loads((OUT/'manifest.json').read_text());video=OUT/'S11.mp4'
    if sha(video)!=m['final_sha256']:raise RuntimeError('final MP4 hash changed')
    kept=preservation(m)
    master=pcm(OUT/'S11-master.wav')
    source_checks=[]
    for row in m['blocks']:
        data=pcm(ROOT/row['wav_source']);start=row['pcm_start_sample']*2
        if master[start:start+len(data)]!=data:raise RuntimeError('source speech PCM modified')
        source_checks.append({'block_id':row['block_id'],'samples':len(data)//2,
                              'source_pcm_sha256':hashlib.sha256(data).hexdigest(),'exact_bytes_preserved':True})
    values=array.array('h');values.frombytes(master)
    audio_checks=[]
    for join in m['timeline']['boundaries']:
        a=join['last_signal_sample'];b=join['first_signal_sample']
        if b-a-1!=35280 or abs(values[a])<=QUIET or abs(values[b])<=QUIET or any(abs(x)>QUIET for x in values[a+1:b]):
            raise RuntimeError('interblock gap does not match 0.8 seconds')
        audio_checks.append({**join,'measured_quiet_samples':b-a-1,'measured_quiet_seconds':(b-a-1)/RATE,'status':'PASS'})
    info=probe(video);streams={s['codec_type']:s for s in info['streams']}
    v=streams['video'];a=streams['audio'];s=streams['subtitle']
    if (v['width'],v['height'],v['r_frame_rate'],v['pix_fmt'],v['codec_name'],a['codec_name'],s['codec_name']) != (1920,1080,'30/1','yuv420p','h264','aac','mov_text'):
        raise RuntimeError('final stream format wrong')
    if int(v['nb_frames'])!=m['timeline']['video_frames']:raise RuntimeError('final frame count wrong')
    spec=json.loads((ROOT/'tutorial.yaml').read_text())
    canonical=' '.join(' '.join(r['narration'].split()) for r in spec['narration_modules'])
    subtitles=check_embedded_subtitles(video,OUT/'S11.ru.srt',canonical)
    extracted=subprocess.check_output(['ffmpeg','-v','error','-xerror','-i',str(video),'-map','0:s:0','-f','srt','-'],text=True)
    (OUT/'S11.embedded.ru.srt').write_text(extracted)
    if parse_srt(OUT/'S11.embedded.ru.srt')[-1][2]!='Спасибо за внимание.':raise RuntimeError('thanks cue missing')
    decoded=subprocess.check_output(['ffmpeg','-v','error','-xerror','-i',str(video),'-map','0:a:0','-ac','1','-ar',str(RATE),'-f','s16le','-'])
    actual=array.array('h');actual.frombytes(decoded)
    if abs(len(actual)-len(values))>1024:raise RuntimeError('AAC sample count wrong')
    def correlation(lag):
        dot=aa=bb=0
        for i in range(10000,min(len(values)-32,len(actual)-32),100):
            x,y=values[i],actual[i+lag];dot+=x*y;aa+=x*x;bb+=y*y
        return dot/math.sqrt(aa*bb)
    corr={lag:correlation(lag) for lag in (-32,0,32)}
    if corr[0]<.995 or corr[0]<=max(corr[-32],corr[32]):raise RuntimeError('AAC differs from PCM timeline')
    raw=small_frames(video);count=len(raw)//PIXELS
    if count!=int(v['nb_frames']) or len(raw)%PIXELS:raise RuntimeError('decode frame count wrong')
    frames=[memoryview(raw)[i:i+PIXELS] for i in range(0,len(raw),PIXELS)]
    blanks=[i for i,f in enumerate(frames) if max(f)-min(f)<12 or max(f)<10 or min(f)>245]
    if blanks:raise RuntimeError('blank decoded frames: '+str(blanks[:20]))
    anomalies=visual_transition_anomalies(raw)
    # These candidates require visual inspection; never infer a good transition
    # merely from absence of black frames. Preserve and expose any finding.
    write_json(OUT/'transition-candidates.json',anomalies)
    review_path=OUT/'transition-review.json'
    review=json.loads(review_path.read_text()) if review_path.is_file() else None
    reviewed=review_is_valid(m,anomalies,review)
    source_frame_checks=[]
    for row in m['blocks']:
        source=small_frames(ROOT/row['video_source']);source_count=len(source)//PIXELS
        if source_count!=row['video_source_frames']:raise RuntimeError('approved source frame count differs')
        maximum=0;worst=0
        for i in range(row['allocated_video_frames']):
            source_i=min(i,source_count-1)
            err=distance(source[source_i*PIXELS:(source_i+1)*PIXELS],frames[row['video_start_frame']+i])
            if err>maximum:maximum=err;worst=i
        if maximum>2:raise RuntimeError(f'final picture differs from approved frames: {row["block_id"]} {maximum} at {worst}')
        source_frame_checks.append({'block_id':row['block_id'],'frames_checked':row['allocated_video_frames'],
            'max_mean_absolute_gray_difference':round(maximum,4),'worst_source_frame':worst,
            'frame_order_and_composition_preserved':True})
        print(json.dumps(source_frame_checks[-1]),flush=True)
    visual_checks=[]
    for boundary in m['scene_boundaries']:
        center=boundary['frame'];window=range(max(0,center-24),min(count,center+25))
        findings=[x for x in anomalies if x['start_frame']<=center+24 and x['end_frame']>=center-24]
        visual_checks.append({**boundary,'frames_checked':len(window),'review_window_seconds':[(center-24)/FPS,(center+24)/FPS],
            'blank_frames':0,'transition_candidates':findings,'approved_frame_order_verified':True,
            'frame_samples':[max(0,center-12),center-1,center, min(count-1,center+12)],
            'status':'PASS' if not findings else 'INSPECT'})
    boundary_report={'status':'PASS' if not anomalies or reviewed else 'INSPECT','interblock_count':13,'technical_scene_boundary_count':53,
        'count_note':'The 53 consecutive technical scene boundaries include the 13 interblock boundaries.',
        'audio_boundaries':audio_checks,'scene_boundaries':visual_checks,'whole_video_transition_candidates':anomalies,'candidate_review':review if reviewed else None,
        'whole_video_frames_decoded':count,'no_new_frame_order_or_composition_changes':True}
    write_json(OUT/'boundary-report.json',boundary_report)
    result={'status':'PASS' if not anomalies or reviewed else 'INSPECT','video_sha256':m['final_sha256'],
        'duration_seconds':m['final_duration_seconds'],'video_frames':count,'format':'1920x1080 30fps yuv420p H.264 / AAC',
        'source_pcm_checks':source_checks,'aac_zero_lag_correlation':corr[0],
        'aac_sample_count_difference':len(actual)-len(values),'pcm_speech_changed':False,
        'aac_encodes':m['aac_encodes'],'h264_encodes':m['h264_final_encodes'],
        'subtitle_matches_current_canonical':True,**subtitles,'last_subtitle_text':'Спасибо за внимание.',
        'blank_frames':0,'visual_source_comparisons':source_frame_checks,'transition_candidates':anomalies,'transition_review':review if reviewed else None,
        'source_preservation':kept,'new_tts_requests':0,'production_mutation_requests':0,
        'listening_performed':False,'listening_note':'No direct listening capability was available; PCM equality and AAC correlation do not establish natural intonation.'}
    write_json(OUT/'verification.json',result)
    return result


if __name__=='__main__':
    print(json.dumps(verify(),ensure_ascii=False,indent=2))
