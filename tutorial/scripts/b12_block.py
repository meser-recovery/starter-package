#!/usr/bin/env python3
"""B12 real Editor–Archive routes in an isolated local portal."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import math
import re
import subprocess
import wave
from pathlib import Path
from urllib.parse import urljoin

from audio_approval import validate_block_approval
from b01_block import check_embedded_subtitles, timestamp
from b09_block import pointer_pixels_in_mp4, visual_transition_anomalies
from browser_capture import capture
from build import demo_server
from modules import cached, map_timing, request_text_and_indices, sha, write_json
from scenes import (TRACKS, create_archive, import_archive, import_local,
                    login, open_archive_detail_from_editor, save_speaker_project)
from validate import ROOT, validate

OUT=ROOT/'generated/b12-block-review'
AUDIO=ROOT/'generated/narration-blocks-v2/B12'
SCENE_IDS=('B12-042','B12-043','B12-044','B12-045')
TITLE='Спикер'
FRESH_TITLE=TITLE
PROJECT_TITLE='Учебная запись с проектом'
VARIANT='B12-review-01'
LEAD=.6
RATE=44100
FPS=30
FRAME_BYTES=1920*1080*3//2


def inputs():
    validate();validate_block_approval('B11')
    spec=json.loads((ROOT/'tutorial.yaml').read_text())
    module=next(m for m in spec['narration_modules'] if m['id']=='B12')
    hit=cached(spec,module)
    if not hit:raise RuntimeError('B12 one-request narration is missing or stale')
    metadata=json.loads((AUDIO/f'{VARIANT}-metadata.json').read_text())
    review=json.loads((AUDIO/'B12-review-map.json').read_text())
    if (review['status'],review['block_id'],review['variant_id'])!=('SEMANTIC_REVIEWED','B12','review-01'):
        raise RuntimeError('B12 semantic pause map invalid')
    for path,digest in ((AUDIO/'narration.mp3',metadata['source_mp3_sha256']),
                        (AUDIO/f'{VARIANT}.mp3',metadata['mp3_sha256']),
                        (AUDIO/f'{VARIANT}.wav',metadata['wav_sha256']),
                        (AUDIO/f'{VARIANT}-timing.json',metadata['timing_sha256']),
                        (AUDIO/f'{VARIANT}-source-timing.json',metadata['source_timing_sha256'])):
        if sha(path)!=digest:raise RuntimeError('B12 reviewed audio changed: '+str(path))
    if (metadata['source_mp3_sha256']!=hit['metadata']['audio_sha256']
            or metadata['new_tts_requests'] or metadata['speed_pitch_gain_processing']
            or not metadata['source_pcm_recovered_exactly']
            or [x['after_offset'] for x in metadata['events']]!=[x['after_offset'] for x in review['insertions']]):
        raise RuntimeError('B12 source/review provenance invalid')
    with wave.open(str(AUDIO/f'{VARIANT}.wav')) as wav:
        if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())!=(1,2,RATE):
            raise RuntimeError('B12 WAV format invalid')
        pcm=wav.readframes(wav.getnframes());duration=wav.getnframes()/RATE
    if hashlib.sha256(pcm).hexdigest()!=metadata['final_pcm_sha256']:
        raise RuntimeError('B12 final PCM changed')
    original=subprocess.check_output(['ffmpeg','-v','error','-xerror','-i',str(AUDIO/'narration.mp3'),
                                      '-ac','1','-ar',str(RATE),'-c:a','pcm_s16le','-f','s16le','-'])
    restored=bytearray();previous=0
    for event in metadata['events']:
        start=event['insert_start_final_sample']*2;end=start+event['added_samples']*2
        if pcm[start:end]!=bytes(end-start):raise RuntimeError('B12 inserted PCM is not silent')
        restored.extend(pcm[previous:start]);previous=end
    restored.extend(pcm[previous:])
    if bytes(restored)!=original:raise RuntimeError('B12 source PCM is not exactly restored')
    timing=json.loads((AUDIO/f'{VARIANT}-timing.json').read_text())
    if timing!=map_timing(spec,module,timing['alignment'],timing['duration_seconds']):
        raise RuntimeError('B12 alignment no longer maps to canonical text')
    scenes=[s for s in spec['scenes'] if s['id'] in SCENE_IDS]
    if tuple(s['id'] for s in scenes)!=SCENE_IDS:raise RuntimeError('B12 scene map changed')
    return spec,module,scenes,metadata,timing,pcm,duration


def scene_timing(spec,module,scene,timing,metadata,duration):
    row=next(r for r in timing['scenes'] if r['scene_id']==scene['id'])
    start=row['range_start_seconds'];end=min(row['range_end_seconds'],duration)
    _,positions=request_text_and_indices(spec,module)
    positions=positions[scene['start_offset']:scene['end_offset']]
    full=timing['alignment']
    local={'characters':[full['characters'][i] for i in positions],
           'character_start_times_seconds':[max(0,full['character_start_times_seconds'][i]-start) for i in positions],
           'character_end_times_seconds':[max(0,full['character_end_times_seconds'][i]-start) for i in positions]}
    if ''.join(local['characters'])!=scene['narration']:
        raise RuntimeError('B12 scene alignment differs from canonical text')
    return {**row,'alignment':local,'duration_seconds':end-start,
            'timing_identity':hashlib.sha256((metadata['timing_sha256']+scene['id']).encode()).hexdigest()}


def capture_spec(scene):
    return {**scene,'visual':{'type':'browser','goal':scene['goal'],
                             'capture_pipeline_revision':'b12-archive-workflow-v1'},
            'initial_state':scene['id'],'expected_state':'B12 archive action completed',
            'assertions':[],'fixture_set':'existing-synthetic-zoom-v1',
            'padding':{'head':0.,'tail':0.}}


async def settled(page,label):
    state=await page.evaluate('''() => {
      const el=id=>document.getElementById(id);
      return {page:location.pathname,scrollX,scrollY,viewport:[innerWidth,innerHeight],
        ingestOpen:!!el('source-session-ingest-dialog')?.open,
        ingestName:el('source-session-ingest-name')?.value||'',
        localFiles:[...document.querySelectorAll('#source-session-ingest-list li')].map(x=>x.textContent.trim()),
        editorRecord:el('current-recording-heading')?.textContent.trim()||'',
        editorArchiveLink:el('current-recording-archive-link')?.getAttribute('href')||'',
        editorTracks:el('current-recording-tracks')?.textContent.trim()||'',
        editorMode:el('active-editor-mode')?.textContent.trim()||'',
        workflowVisible:!!el('workflow-choice')&&!el('workflow-choice').hidden,
        announcementVisible:!!el('announcement-processor-card')&&!el('announcement-processor-card').hidden,
        speakerVisible:!!el('speaker-editor')&&!el('speaker-editor').hidden,
        pickerOpen:!!el('import-zone')?.open,
        pickerRows:[...document.querySelectorAll('#source-session-list .source-session-item')].map(x=>x.textContent.trim()),
        detailVisible:!!el('detail')&&!el('detail').hidden,
        detailTitle:el('detail-title')?.textContent.trim()||'',
        detailActions:el('detail')?.querySelector('.primary-workflows')?.textContent.trim()||''};
    }''')
    if state['scrollX']!=0 or state['viewport']!=[1728,972]:
        raise RuntimeError(f'B12 {label} viewport changed: {state}')
    if hasattr(page,'tutorial'):
        page.tutorial.events.append({'type':'b12-state','seconds':page.tutorial.now(),
                                     'label':label,'state':state})
    return state


async def scroll_import_panel(page):
    await page.evaluate("window.__s11Capture.hide('intentional-import-scroll')")
    first=await page.evaluate("document.querySelector('#import-zone').scrollTop")
    maximum=await page.evaluate("el=>el.scrollHeight-el.clientHeight",await page.raw.query_selector('#import-zone'))
    if maximum<120:raise RuntimeError('B12 import dialog does not need the expected visible scroll')
    started=page.tutorial.now()
    for step in range(1,29):
        t=step/28; eased=t*t*(3-2*t)
        await page.evaluate('value=>document.querySelector("#import-zone").scrollTop=value',
                            first+(maximum-first)*eased)
        await asyncio.sleep(.04)
    page.tutorial.events.append({'type':'intentional-import-scroll','seconds':started,
                                 'end_seconds':page.tutorial.now(),'from':first,'to':maximum})


async def follow_real_workflow_link(page,link,target_selector,label):
    href=await link.get_attribute('href')
    if not href or not href.startswith('Audio-Editor.html?session='):
        raise RuntimeError('B12 Archive workflow link has no verified Editor target')
    target=urljoin(page.url,href)
    async with page.raw.expect_popup() as opened:
        await link.click()
    popup=await opened.value
    await popup.locator(target_selector).wait_for(state='visible',timeout=60000)
    if '/Audio-Editor.html' not in popup.url:
        raise RuntimeError('B12 workflow link did not open the real Audio Editor')
    await popup.close()
    # The real control opens a new browser tab. Show that same verified URL in
    # the capture tab so one uninterrupted screencast can follow the action.
    await page.goto(target)
    if target_selector=='#speaker-editor':
        await page.raw.wait_for_function("async () => document.querySelectorAll('#speaker-editor-tracks .speaker-track').length===4 && (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().ready",timeout=60000)
    else:
        await page.raw.wait_for_function("document.querySelectorAll('#processor-file-info .processor-track').length===4",timeout=60000)
    await page.raw.wait_for_timeout(250)
    await page.locator(target_selector).wait_for(state='visible',timeout=60000)
    await page.evaluate("window.__s11Capture.hide('workflow-tab-context')")
    state=await settled(page,label)
    if target_selector=='#announcement-processor-card' and not state['announcementVisible']:
        raise RuntimeError('B12 announcement mode did not open')
    if target_selector=='#speaker-editor' and not state['speakerVisible']:
        raise RuntimeError('B12 Speaker mode did not open')


async def open_archive_record(page,title):
    await page.locator('nav[aria-label="Аудиопортал"] a[href="Audio-Archive.html"]').click()
    await page.locator('#archive-index').wait_for(state='visible')
    if not await page.locator('#records').is_visible():
        await page.locator('#record-picker-open').click()
    row=page.locator('#session-list article').filter(
        has=page.raw.get_by_role('heading',name=title,exact=True)).first
    await row.get_by_role('button',name='Открыть запись').click()
    await page.locator('#detail-title').wait_for(state='visible',timeout=60000)
    state=await settled(page,'archive record opened: '+title)
    if state['detailTitle']!=title:raise RuntimeError('B12 selected the wrong Archive record')
    await page.evaluate("window.__s11Capture.hide('record-detail-context')")


async def select_archive_record_without_loading_frames(page,button):
    """Capture the real press, then resume only after its async import settles."""
    director=page.tutorial
    await director.aim(button.raw)
    await director.before_action()
    pressed=director.now()
    await page.raw.mouse.down()
    await asyncio.sleep(.13)
    await page.evaluate("window.__s11Capture.hide('archive-selection-context')")
    await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
    await asyncio.sleep(.04)
    await director.pause_capture()
    await page.raw.mouse.up()
    await page.locator('#workflow-choice').wait_for(state='visible',timeout=60000)
    await page.raw.wait_for_function("document.querySelector('#current-recording-tracks')?.textContent.trim()==='4'",timeout=60000)
    await page.raw.wait_for_timeout(250)
    await director.stable()
    await director.resume_capture()
    director.events.append({'type':'click','seconds':pressed,'target':str(button.raw),
                            'ripple':True,'loading_frames_excluded':True})
    await director.after_action()


async def prepare(page,scene,base):
    await page.set_viewport_size({'width':1728,'height':972})
    await login(page,base)
    sid=scene['id']
    if sid in ('B12-042','B12-043'):
        await import_local(page,base)
        await page.locator('#source-session-mode-device').click()
        await page.evaluate("document.querySelector('#import-zone').scrollTop=0;window.scrollTo(0,0)")
        if sid=='B12-043':
            await page.locator('#processor-save-incoming').click()
            await page.locator('#source-session-ingest-dialog').wait_for(state='visible')
    elif sid=='B12-044':
        await import_archive(page,base,PROJECT_TITLE,'speaker')
        await save_speaker_project(page)
        await open_archive_detail_from_editor(page,base,PROJECT_TITLE)
        await page.goto(base+'/Audio-Archive.html')
        await page.locator('#archive-create-open').wait_for(state='visible')
        await create_archive(page,FRESH_TITLE)
    elif sid=='B12-045':
        await create_archive(page,FRESH_TITLE)
        await page.goto(base+'/Audio-Editor.html')
        await page.locator('#source-session-mode-archive').wait_for(state='visible')
    else:raise RuntimeError('unexpected B12 scene')
    await page.evaluate('async()=>{await document.fonts.ready;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))}')
    await page.wait_for_timeout(300)
    await page.screenshot()


async def perform(page,scene,base,cue):
    sid=scene['id'];director=page.tutorial
    if sid=='B12-042':
        await cue('Если работа уже была начата');await director.wait_pending()
        await scroll_import_panel(page)
        await cue('Сохранить запись Zoom в аудиоархив')
        await page.locator('#processor-save-incoming').click()
        await page.locator('#source-session-ingest-dialog').wait_for(state='visible')
        await page.evaluate("window.__s11Capture.hide('save-dialog-context')")
        state=await settled(page,'local-source save dialog')
        if not state['ingestOpen'] or len(state['localFiles'])!=4:
            raise RuntimeError('B12 local sources were not passed to the real save dialog')
    elif sid=='B12-043':
        await cue('сохранить исходную запись')
        await page.locator('#source-session-ingest-submit').click()
        await page.locator('#source-session-ingest-dialog').wait_for(state='hidden',timeout=60000)
        saved=await settled(page,'local sources saved')
        if saved['editorRecord']!=TITLE or not saved['editorArchiveLink']:
            raise RuntimeError('B12 local record did not gain an Archive link')
        await page.locator('#import-zone > summary').click()
        await page.evaluate("window.__s11Capture.hide('source-dialog-closed')")
        await cue('Уже сохранённую запись')
        await page.locator('#current-recording-archive-link').click()
        await page.locator('#detail-title').wait_for(state='visible',timeout=60000)
        detail=await settled(page,'saved record opened from editor')
        if detail['detailTitle']!=TITLE:
            raise RuntimeError('B12 Archive did not open the saved local record')
    elif sid=='B12-044':
        fresh=await settled(page,'fresh record actions')
        if fresh['detailTitle']!=FRESH_TITLE or 'Начать обработку' not in fresh['detailActions']:
            raise RuntimeError('B12 fresh Archive record lacks Start action')
        await cue('Открыть анонс-мейкер')
        await follow_real_workflow_link(page,
            page.locator('#detail .workflow-choice-announcement').get_by_role('link',name='Открыть анонс-мейкер'),
            '#announcement-processor-card','announcement opened from Archive')
        await open_archive_record(page,FRESH_TITLE)
        await cue('используется')
        await follow_real_workflow_link(page,
            page.locator('#detail .project-section').get_by_role('link',name='Начать обработку'),
            '#speaker-editor','new Speaker project opened')
        await open_archive_record(page,PROJECT_TITLE)
        project=await settled(page,'saved project Continue action')
        if 'Продолжить обработку' not in project['detailActions']:
            raise RuntimeError('B12 saved Archive project lacks Continue action')
        await cue('будет предложено')
        await follow_real_workflow_link(page,
            page.locator('#detail .project-section').get_by_role('link',name='Продолжить обработку'),
            '#speaker-editor','saved Speaker project resumed')
    elif sid=='B12-045':
        await cue('можно выбрать вариант')
        await page.locator('#source-session-mode-archive').click()
        item=page.locator('#source-session-list .source-session-item').filter(has_text=FRESH_TITLE).first
        await cue('найти нужную запись')
        await select_archive_record_without_loading_frames(page,item.get_by_role('button',name='Выбрать'))
        await page.evaluate("window.__s11Capture.hide('archive-sources-ready')")
        result=await settled(page,'archive tracks opened in editor')
        if (not result['workflowVisible'] or result['editorRecord']!=FRESH_TITLE
                or not result['editorArchiveLink'] or not result['editorTracks']):
            raise RuntimeError('B12 Editor did not load the saved Archive sources')
    else:raise RuntimeError('unexpected B12 scene')
    await page.evaluate("window.__s11Capture.hide('scene-complete')")


async def visual():
    if (ROOT/'approvals/B12-block.json').exists():raise RuntimeError('B12 approved and immutable')
    spec,module,scenes,metadata,timing,_,duration=inputs()
    (OUT/'scenes').mkdir(parents=True,exist_ok=True)
    recipe='\n'.join(inspect.getsource(fn) for fn in
                     (capture_spec,settled,scroll_import_panel,follow_real_workflow_link,
                      open_archive_record,prepare,perform))
    identity=hashlib.sha256((recipe+json.dumps([TITLE,FRESH_TITLE,PROJECT_TITLE],ensure_ascii=False)).encode()).hexdigest()
    rows=[]
    for scene in scenes:
        with demo_server(None) as base:
            local=scene_timing(spec,module,scene,timing,metadata,duration)
            local.update(visual_lead_seconds=LEAD if scene['id']==SCENE_IDS[0] else 0.,
                         visual_source_sha256=identity,strict_choreography=False)
            path=OUT/'scenes'/f"{scene['id']}.mp4"
            evidence=await capture(capture_spec(scene),spec['narration'],base,timing=local,
                                   destination=path,prepare_scene=prepare,perform_scene=perform)
            if evidence['browser_errors'] or evidence['production_mutation_requests']:
                raise RuntimeError('B12 isolated capture failed')
            if max((e['seconds'] for e in evidence['choreography']['events']),default=0)>local['duration_seconds']+local['visual_lead_seconds']+.25:
                raise RuntimeError('B12 action exceeds narrated scene: '+scene['id'])
            row={'scene_id':scene['id'],'visual':str(path),'sha256':sha(path),
                 'duration_seconds':evidence['duration_seconds'],
                 'cue_errors_seconds':[c['actual_seconds']-c['target_seconds'] for c in evidence['alignment_action_cues']],
                 'production_mutation_requests':0}
            rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    result={'status':'PASS','block_id':'B12','source_mp3_sha256':metadata['source_mp3_sha256'],
            'final_wav_sha256':metadata['wav_sha256'],'tts_requests':0,'scenes':rows}
    write_json(OUT/'visual-capture.json',result)
    return result


def subtitles(scenes,timings):
    cues=[]
    for scene,timing in zip(scenes,timings):
        text=scene['narration'];starts=timing['alignment']['character_start_times_seconds']
        ends=timing['alignment']['character_end_times_seconds'];words=list(re.finditer(r'\S+',text));begin=0
        for i,word in enumerate(words):
            first,last=words[begin].start(),word.end()-1
            phrase=' '.join(text[first:last+1].split())
            if len(phrase)>=68 or word.group()[-1:] in '.!?…' or i==len(words)-1:
                start=LEAD+timing['range_start_seconds']+starts[first]
                end=LEAD+timing['range_start_seconds']+ends[last]
                if end<=start or '[' in phrase or ']' in phrase:raise RuntimeError('B12 subtitle invalid')
                cues.append((start,end,phrase));begin=i+1
    if any(cues[i][0]<cues[i-1][1]-.01 for i in range(1,len(cues))):
        raise RuntimeError('B12 subtitle cues overlap')
    for suffix in ('srt','vtt'):
        vtt=suffix=='vtt'
        body=('WEBVTT\n\n' if vtt else '')+'\n\n'.join(
            ('' if vtt else f'{i}\n')+f'{timestamp(a,vtt=vtt)} --> {timestamp(b,vtt=vtt)}\n{phrase}'
            for i,(a,b,phrase) in enumerate(cues,1))+'\n'
        (OUT/f'B12.ru.{suffix}').write_text(body)
    return cues


def assemble():
    if (ROOT/'approvals/B12-block.json').exists():raise RuntimeError('B12 approved and immutable')
    spec,module,scenes,metadata,timing,pcm,duration=inputs()
    visual_report=json.loads((OUT/'visual-capture.json').read_text())
    if (visual_report['source_mp3_sha256']!=metadata['source_mp3_sha256']
            or [r['scene_id'] for r in visual_report['scenes']]!=list(SCENE_IDS)):
        raise RuntimeError('B12 visual capture differs from source')
    timings=[scene_timing(spec,module,s,timing,metadata,duration) for s in scenes]
    cues=subtitles(scenes,timings)
    timeline=OUT/'B12-video-timeline.wav'
    with wave.open(str(timeline),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(RATE)
        wav.writeframes(bytes(round(LEAD*RATE)*2)+pcm)
    total=math.ceil(max(LEAD+duration,cues[-1][1]+.01)*FPS)/FPS
    bounds=[0]+[LEAD+t['range_start_seconds'] for t in timings[1:]]+[total]
    counts=[round(bounds[i+1]*FPS)-round(bounds[i]*FPS) for i in range(len(scenes))]
    if min(counts)<=0:raise RuntimeError('B12 scene frame count invalid')
    candidate=OUT/'B12.tmp.mp4'
    cmd=['ffmpeg','-y','-v','error','-f','rawvideo','-pixel_format','yuv420p',
         '-video_size','1920x1080','-framerate',str(FPS),'-i','pipe:0',
         '-i',str(timeline),'-i',str(OUT/'B12.ru.srt'),
         '-map','0:v:0','-map','1:a:0','-map','2:s:0',
         '-c:v','libx264','-preset','veryfast','-crf','21','-pix_fmt','yuv420p',
         '-c:a','aac','-b:a','192k','-c:s','mov_text','-metadata:s:s:0','language=rus',
         '-frames:v',str(sum(counts)),'-movflags','+faststart',str(candidate)]
    with (OUT/'encode.log').open('wb') as log:
        encoder=subprocess.Popen(cmd,stdin=subprocess.PIPE,stderr=log)
        try:
            for scene,count in zip(scenes,counts):
                source=OUT/'scenes'/f"{scene['id']}.mp4"
                if not source.exists():raise RuntimeError('B12 scene missing: '+scene['id'])
                decoder=subprocess.Popen(['ffmpeg','-v','error','-xerror','-i',str(source),'-an',
                    '-vf','scale=1920:1080,fps=30,trim=start_frame=1,tpad=start=1:start_mode=clone,setpts=N/(30*TB),tpad=stop_mode=clone:stop=300',
                    '-r',str(FPS),'-frames:v',str(count),'-pix_fmt','yuv420p','-f','rawvideo','pipe:1'],stdout=subprocess.PIPE)
                copied=0
                try:
                    while chunk:=decoder.stdout.read(1024*1024):
                        encoder.stdin.write(chunk);copied+=len(chunk)
                finally:decoder.stdout.close()
                if decoder.wait() or copied!=count*FRAME_BYTES:
                    raise RuntimeError('B12 captured frame count mismatch: '+scene['id'])
            encoder.stdin.close()
            if encoder.wait():raise RuntimeError('B12 encoding failed; see encode.log')
        finally:
            if encoder.poll() is None:encoder.kill();encoder.wait()
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(candidate),'-f','null','-'],
                   check=True,stdout=subprocess.DEVNULL)
    canonical=' '.join(' '.join(s['narration'].split()) for s in scenes)
    checked=check_embedded_subtitles(candidate,OUT/'B12.ru.srt',canonical)
    final=OUT/'B12.mp4';candidate.replace(final)
    report={'status':'READY FOR B12 BLOCK REVIEW','block_id':'B12','video':str(final),
            'video_sha256':sha(final),'duration_seconds':total,
            'source_mp3_sha256':metadata['source_mp3_sha256'],'final_wav_sha256':metadata['wav_sha256'],
            'final_pcm_sha256':metadata['final_pcm_sha256'],'final_alignment_sha256':metadata['timing_sha256'],
            'video_audio_timeline':str(timeline),'video_audio_lead_seconds':LEAD,
            'insertions':len(metadata['events']),'scene_frame_counts':dict(zip(SCENE_IDS,counts)),
            'embedded_subtitle_cues':checked['embedded_subtitle_cues'],
            'last_embedded_subtitle_end_seconds':checked['last_embedded_subtitle_end_seconds'],
            'tts_requests_for_source':1,'production_mutation_requests':0}
    write_json(OUT/'report.json',report)
    return report


def verify():
    spec,module,scenes,metadata,timing,pcm,_=inputs()
    report=json.loads((OUT/'report.json').read_text());video=OUT/'B12.mp4'
    if sha(video)!=report['video_sha256']:raise RuntimeError('B12 MP4 changed')
    with wave.open(str(OUT/'B12-video-timeline.wav')) as wav:timeline=wav.readframes(wav.getnframes())
    lead=round(LEAD*RATE)*2
    if timeline[:lead]!=bytes(lead) or timeline[lead:]!=pcm:
        raise RuntimeError('B12 video timeline changed approved source PCM')
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(video)]))
    streams={s['codec_type']:s for s in probe['streams']}
    frames=sum(report['scene_frame_counts'].values())
    if (int(streams['video']['nb_frames'])!=frames or streams['video']['r_frame_rate']!='30/1'
            or streams['audio']['codec_name']!='aac' or streams['subtitle']['codec_name']!='mov_text'):
        raise RuntimeError('B12 MP4 stream format invalid')
    canonical=' '.join(' '.join(s['narration'].split()) for s in scenes)
    checked=check_embedded_subtitles(video,OUT/'B12.ru.srt',canonical)
    small=subprocess.check_output(['ffmpeg','-v','error','-xerror','-i',str(video),'-map','0:v:0',
                                   '-vf','scale=48:27:flags=area,format=gray','-r',str(FPS),'-f','rawvideo','-'])
    pixels=48*27
    if len(small)!=frames*pixels:raise RuntimeError('B12 video frame count invalid')
    lum=[];blank=[]
    for i in range(frames):
        frame=small[i*pixels:(i+1)*pixels];lum.append(sum(frame)/pixels)
        if max(frame)-min(frame)<12 or all(v<10 for v in frame) or all(v>245 for v in frame):blank.append(i)
    flash=[i for i in range(1,frames-1) if abs(lum[i]-lum[i-1])>35 and abs(lum[i]-lum[i+1])>35 and abs(lum[i-1]-lum[i+1])<10]
    anomalies=visual_transition_anomalies(small)
    visual_report=json.loads((OUT/'visual-capture.json').read_text())
    checks=[];states=[];cue_errors=[];violations=[];elapsed=0
    for scene in scenes:
        row=next(r for r in visual_report['scenes'] if r['scene_id']==scene['id'])
        source=OUT/'scenes'/f"{scene['id']}.mp4"
        if sha(source)!=row['sha256']:raise RuntimeError('B12 scene source changed')
        evidence=json.loads(source.with_suffix('.json').read_text())
        if evidence['expected_state']!='PASS' or evidence['browser_errors'] or evidence['production_mutation_requests']:
            raise RuntimeError('B12 browser capture invalid')
        events=evidence['choreography']['events']
        states.extend({'scene_id':scene['id'],'seconds':elapsed+e['seconds'],**e}
                      for e in events if e['type']=='b12-state')
        cue_errors.extend(abs(x) for x in row['cue_errors_seconds'])
        violations.extend(evidence['choreography']['overlay']['violations'])
        if scene['id']=='B12-042' and not any(e['type']=='intentional-import-scroll' and
                e['to']>e['from']+100 and e['end_seconds']-e['seconds']>.9 for e in events):
            raise RuntimeError('B12 local save dialog was not visibly scrolled')
        click_evidence=copy.deepcopy(evidence)
        arrivals=[e for e in click_evidence['choreography']['events'] if e['type']=='cursor-arrival']
        clicks=[e for e in click_evidence['choreography']['events'] if e['type']=='click']
        for click in clicks:
            if any(a['target']==click['target'] and a['seconds']<=click['seconds'] for a in arrivals):
                continue
            # Navigation changes Playwright's frame URL after pointer-up. The
            # real selector must still match the prior arrival before pixel QA.
            same=[a for a in arrivals if a['seconds']<=click['seconds'] and
                  a['target'].split(' selector=')[-1]==click['target'].split(' selector=')[-1]]
            if not same:raise RuntimeError('B12 navigational click changed its real target')
            click['target']=max(same,key=lambda a:a['seconds'])['target']
        checks.extend({'scene_id':scene['id'],**c} for c in
                      pointer_pixels_in_mp4(video,click_evidence,elapsed,scene['id'],OUT/'qa-clicks'/scene['id']))
        elapsed+=report['scene_frame_counts'][scene['id']]/FPS
    names={e['label']:e['state'] for e in states}
    dialog=names.get('local-source save dialog');local=names.get('local sources saved')
    opened=names.get('saved record opened from editor');fresh=names.get('fresh record actions')
    announcement=names.get('announcement opened from Archive')
    started=names.get('new Speaker project opened')
    project=names.get('saved project Continue action')
    resumed=names.get('saved Speaker project resumed')
    reverse=names.get('archive tracks opened in editor')
    if (not dialog or not dialog['ingestOpen'] or len(dialog['localFiles'])!=4
            or not local or local['editorRecord']!=TITLE or not local['editorArchiveLink']
            or not opened or opened['detailTitle']!=TITLE
            or not fresh or fresh['detailTitle']!=FRESH_TITLE or 'Начать обработку' not in fresh['detailActions']
            or not announcement or not announcement['announcementVisible']
            or not started or not started['speakerVisible']
            or not project or project['detailTitle']!=PROJECT_TITLE or 'Продолжить обработку' not in project['detailActions']
            or not resumed or not resumed['speakerVisible']
            or not reverse or reverse['editorRecord']!=FRESH_TITLE or not reverse['workflowVisible']
            or not reverse['editorArchiveLink'] or not reverse['editorTracks']
            or violations or len(checks)<12
            or (cue_errors and max(cue_errors)>.35)):
        raise RuntimeError(f'B12 real actions/result/cursor/synchronization failed: '
                           f'states={list(names)}, violations={violations}, clicks={len(checks)}, '
                           f'cue={max(cue_errors) if cue_errors else None}')
    if blank or flash or anomalies:
        raise RuntimeError(f'B12 blank/flash/return frames: {blank[:3]}/{flash[:3]}/{anomalies[:3]}')
    result={'status':'PASS','block_id':'B12','video_sha256':sha(video),
            'source_pcm_preserved_in_timeline':True,'subtitle_cues':checked['embedded_subtitle_cues'],
            'last_embedded_subtitle_end_seconds':checked['last_embedded_subtitle_end_seconds'],
            'subtitle_matches_canonical_text':True,'video_frames':frames,'blank_frames':0,
            'isolated_flash_frames':0,'visual_transition_anomalies':[],
            'rendered_pointer_clicks':checks,'real_interface_states':states,
            'max_visual_cue_error_seconds':max(cue_errors) if cue_errors else None,
            'production_mutation_requests':0}
    write_json(OUT/'verification.json',result)
    return result
