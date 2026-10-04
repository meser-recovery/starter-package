#!/usr/bin/env python3
"""Replace only B14's summary picture with an approved-B01/B02-style animation."""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path

from b01_block import check_embedded_subtitles
from b09_block import visual_transition_anomalies
from b14_block import inputs
from browser_capture import capture
from modules import sha, write_json
from validate import ROOT

OUT=ROOT/'generated/b14-outro-review'
PRIOR=ROOT/'generated/b14-block-review/B14.mp4'
PRIOR_SHA='56b334a3c8b0e43f57f6d41c0259ef11521e0cbe637d0ceb92b7259d4e2c030a'
PRIOR_SRT=ROOT/'generated/b14-block-review/B14.ru.srt'
PRIOR_VTT=ROOT/'generated/b14-block-review/B14.ru.vtt'
SRT_SHA='688dee7ee6e64e63749cc70625917be77dab7324161dcccac9ec490421b90907'
VTT_SHA='1478e96c65a051378814bc004a863adc10cb140288a7f68d8f634df57369f5b3'
ANIMATION=ROOT/'animations/b14-outro.html'
TABLET=ROOT/'assets/s11/project-tablet.svg'
CUT_FRAME=2034
TOTAL_FRAMES=3583
FPS=30
FRAME_BYTES=1920*1080*3//2
TAIL_FRAMES=TOTAL_FRAMES-CUT_FRAME
TAIL_DURATION=TAIL_FRAMES/FPS


def validated_inputs():
    source=inputs()
    if sha(PRIOR)!=PRIOR_SHA:raise RuntimeError('B14 accepted pre-summary candidate changed')
    if sha(PRIOR_SRT)!=SRT_SHA or sha(PRIOR_VTT)!=VTT_SHA:
        raise RuntimeError('B14 canonical subtitles changed')
    if not ANIMATION.exists() or not TABLET.exists():raise RuntimeError('B14 outro animation assets missing')
    return source


def capture_spec():
    return {'id':'B14-OUTRO','narration':'Итак, подведём итог.',
            'visual':{'type':'browser','goal':'B14 summary using approved B01–B02 color and motion language',
                      'capture_pipeline_revision':'b14-summary-v2'},
            'initial_state':'approved B14 Archive frame at 67.800 s',
            'expected_state':'summary reaches a calm complete frame',
            'assertions':[],'fixture_set':'existing-synthetic-zoom-v1',
            'padding':{'head':0.,'tail':0.}}


async def prepare(page,scene,base):
    await page.goto(ANIMATION.as_uri())
    await page.wait_for_function('window.assetsLoaded===true',timeout=30000)
    await page.evaluate('window.setPreviewTime(0)')
    await page.screenshot()


async def perform(page,scene,base,cue):
    await page.evaluate("window.__s11Capture.hide('concept-animation')")
    await page.evaluate('window.startAnimation()')


async def visual():
    _,_,_,metadata,_,_,_=validated_inputs()
    OUT.mkdir(parents=True,exist_ok=True)
    identity=hashlib.sha256(ANIMATION.read_bytes()+TABLET.read_bytes()+
                            json.dumps([CUT_FRAME,TOTAL_FRAMES,FPS]).encode()).hexdigest()
    timing={'duration_seconds':TAIL_DURATION,'alignment':{'characters':[],
            'character_start_times_seconds':[],'character_end_times_seconds':[]},
            'timing_identity':metadata['timing_sha256'],
            'visual_source_sha256':identity,'strict_choreography':False}
    evidence=await capture(capture_spec(),{},'http://127.0.0.1:1',timing=timing,
                           destination=OUT/'outro-visual.mp4',prepare_scene=prepare,perform_scene=perform)
    if evidence['browser_errors'] or evidence['production_mutation_requests'] or evidence['choreography']['overlay']['cursorVisible']:
        raise RuntimeError('B14 summary visual capture failed')
    result={'status':'PASS','source_video_sha256':PRIOR_SHA,
            'preserved_prefix_frames':CUT_FRAME,'cut_seconds':CUT_FRAME/FPS,
            'animation_sha256':identity,'outro_video_sha256':sha(OUT/'outro-visual.mp4'),
            'outro_duration_seconds':evidence['duration_seconds'],
            'audio_changes':0,'subtitle_changes':0,'new_tts_requests':0}
    write_json(OUT/'visual-capture.json',result)
    return result


def _decoder(source:Path,count:int,*,tail:bool):
    filt=('fps=30,scale=1920:1080,format=yuv420p,tpad=stop_mode=clone:stop=300'
          if tail else 'scale=1920:1080,format=yuv420p')
    return subprocess.Popen(['ffmpeg','-v','error','-xerror','-i',str(source),'-an','-vf',filt,
                             '-frames:v',str(count),'-pix_fmt','yuv420p','-f','rawvideo','pipe:1'],
                            stdout=subprocess.PIPE)


def assemble():
    _,_,scenes,metadata,_,_,_=validated_inputs()
    capture_report=json.loads((OUT/'visual-capture.json').read_text())
    visual=OUT/'outro-visual.mp4'
    if capture_report['source_video_sha256']!=PRIOR_SHA or sha(visual)!=capture_report['outro_video_sha256']:
        raise RuntimeError('B14 summary capture changed')
    for source,target in ((PRIOR_SRT,OUT/'B14.ru.srt'),(PRIOR_VTT,OUT/'B14.ru.vtt')):
        shutil.copy2(source,target)
    candidate=OUT/'B14.tmp.mp4'
    cmd=['ffmpeg','-y','-v','error','-f','rawvideo','-pixel_format','yuv420p',
         '-video_size','1920x1080','-framerate','30','-i','pipe:0','-i',str(PRIOR),
         '-map','0:v:0','-map','1:a:0','-map','1:s:0',
         '-c:v','libx264','-preset','veryfast','-crf','21','-pix_fmt','yuv420p',
         '-c:a','copy','-c:s','copy','-metadata:s:s:0','language=rus',
         '-frames:v',str(TOTAL_FRAMES),'-movflags','+faststart',str(candidate)]
    with (OUT/'encode.log').open('wb') as log:
        encoder=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=log)
        try:
            for source,count,tail in ((PRIOR,CUT_FRAME,False),(visual,TAIL_FRAMES,True)):
                decoder=_decoder(source,count,tail=tail);copied=0
                try:
                    while chunk:=decoder.stdout.read(1024*1024):
                        encoder.stdin.write(chunk);copied+=len(chunk)
                finally:decoder.stdout.close()
                if decoder.wait() or copied!=count*FRAME_BYTES:
                    raise RuntimeError(f'B14 video frame source incomplete: {source}, {copied}/{count*FRAME_BYTES}')
            encoder.stdin.close()
            if encoder.wait():raise RuntimeError('B14 summary encoding failed; inspect encode.log')
        finally:
            if encoder.poll() is None:encoder.kill();encoder.wait()
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(candidate),'-f','null','-'],
                   check=True,stdout=subprocess.DEVNULL)
    canonical=' '.join(' '.join(s['narration'].split()) for s in scenes)
    checked=check_embedded_subtitles(candidate,OUT/'B14.ru.srt',canonical)
    final=OUT/'B14.mp4';candidate.replace(final)
    report={'status':'READY FOR B14 BLOCK REVIEW','block_id':'B14','video':str(final),
            'video_sha256':sha(final),'duration_seconds':TOTAL_FRAMES/FPS,
            'prior_candidate_sha256':PRIOR_SHA,'preserved_picture_until_seconds':CUT_FRAME/FPS,
            'outro_animation_start_seconds':CUT_FRAME/FPS,
            'approved_audio_mp3_sha256':metadata['mp3_sha256'],
            'approved_audio_wav_sha256':metadata['wav_sha256'],
            'approved_alignment_sha256':metadata['timing_sha256'],
            'final_alignment_sha256':metadata['timing_sha256'],
            'subtitle_srt_sha256':SRT_SHA,'subtitle_vtt_sha256':VTT_SHA,
            'embedded_subtitle_cues':checked['embedded_subtitle_cues'],
            'subtitle_cues':checked['embedded_subtitle_cues'],
            'last_embedded_subtitle_end_seconds':checked['last_embedded_subtitle_end_seconds'],
            'tts_requests_for_visual_revision':0,'production_mutation_requests':0}
    write_json(OUT/'report.json',report)
    html=(ROOT/'generated/b14-block-review/index.html').read_text()
    html=html.replace(PRIOR_SHA,report['video_sha256']).replace(PRIOR_SHA[:8],report['video_sha256'][:8])
    html=html.replace('B14 · поиск и материалы Аудиоархива','B14 · поиск и анимированный итог')
    (OUT/'index.html').write_text(html)
    return report


def _audio_payload_hash(path):
    data=subprocess.check_output(['ffmpeg','-v','error','-xerror','-i',str(path),
                                  '-map','0:a:0','-c:a','copy','-f','adts','pipe:1'])
    return hashlib.sha256(data).hexdigest()


def _small(path):
    return subprocess.check_output(['ffmpeg','-v','error','-xerror','-i',str(path),
                                    '-map','0:v:0','-vf','scale=48:27:flags=area,format=gray',
                                    '-r','30','-f','rawvideo','pipe:1'])


def verify():
    _,_,scenes,metadata,_,_,_=validated_inputs()
    report=json.loads((OUT/'report.json').read_text());final=OUT/'B14.mp4'
    if sha(final)!=report['video_sha256']:raise RuntimeError('B14 updated MP4 changed')
    if sha(OUT/'B14.ru.srt')!=SRT_SHA or sha(OUT/'B14.ru.vtt')!=VTT_SHA:
        raise RuntimeError('B14 subtitles changed')
    if _audio_payload_hash(final)!=_audio_payload_hash(PRIOR):
        raise RuntimeError('B14 AAC payload changed during visual revision')
    canonical=' '.join(' '.join(s['narration'].split()) for s in scenes)
    checked=check_embedded_subtitles(final,OUT/'B14.ru.srt',canonical)
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams',
                                              '-of','json',str(final)]))
    streams={s['codec_type']:s for s in probe['streams']}
    if int(streams['video']['nb_frames'])!=TOTAL_FRAMES or streams['video']['r_frame_rate']!='30/1':
        raise RuntimeError('B14 updated video frame count invalid')
    if streams['audio']['codec_name']!='aac' or streams['subtitle']['codec_name']!='mov_text':
        raise RuntimeError('B14 approved audio/subtitle codec changed')
    prior=_small(PRIOR);out=_small(final);pixels=48*27
    if len(prior)!=TOTAL_FRAMES*pixels or len(out)!=TOTAL_FRAMES*pixels:
        raise RuntimeError('B14 decoded frame count changed')
    differences=[]
    for i in range(CUT_FRAME):
        a=prior[i*pixels:(i+1)*pixels];b=out[i*pixels:(i+1)*pixels]
        differences.append(sum(abs(x-y) for x,y in zip(a,b))/pixels)
    if max(differences)>5 or sum(differences)/len(differences)>2:
        raise RuntimeError('B14 picture before summary changed materially')
    lum=[];blank=[]
    for i in range(TOTAL_FRAMES):
        f=out[i*pixels:(i+1)*pixels];lum.append(sum(f)/pixels)
        if max(f)-min(f)<12 or all(v<10 for v in f) or all(v>245 for v in f):blank.append(i)
    flash=[i for i in range(1,TOTAL_FRAMES-1) if abs(lum[i]-lum[i-1])>35 and
           abs(lum[i]-lum[i+1])>35 and abs(lum[i-1]-lum[i+1])<10]
    anomalies=visual_transition_anomalies(out)
    if blank or flash or anomalies:
        raise RuntimeError(f'B14 blank/flash/short return frames: {blank[:3]}/{flash[:3]}/{anomalies[:3]}')
    result={'status':'PASS','video_sha256':sha(final),'preserved_prefix_frames':CUT_FRAME,
            'preserved_prefix_mean_luma_difference':sum(differences)/len(differences),
            'preserved_prefix_max_luma_difference':max(differences),
            'aac_payload_unchanged':True,'original_wav_sha256':metadata['wav_sha256'],
            'alignment_sha256':metadata['timing_sha256'],
            'subtitle_srt_unchanged':True,'subtitle_vtt_unchanged':True,
            'embedded_subtitle_cues':checked['embedded_subtitle_cues'],
            'subtitle_cues':checked['embedded_subtitle_cues'],
            'last_embedded_subtitle_end_seconds':checked['last_embedded_subtitle_end_seconds'],
            'video_frames':TOTAL_FRAMES,'blank_frames':0,'isolated_flash_frames':0,
            'visual_transition_anomalies':[],'production_mutation_requests':0,'new_tts_requests':0}
    write_json(OUT/'verification.json',result)
    return result
