#!/usr/bin/env python3
"""Render B09 from one reviewed take and real Speaker workspace actions."""
from __future__ import annotations

import array
import asyncio
import hashlib
import inspect
import json
import math
import re
import subprocess
import wave
from pathlib import Path

from audio_approval import validate_block_approval
from b01_block import check_embedded_subtitles, timestamp
from browser_capture import capture
from build import demo_server
from modules import cached, map_timing, request_text_and_indices, sha, write_json
from scenes import import_local, login
from validate import ROOT, validate

OUT = ROOT / 'generated/b09-block-review'
AUDIO = ROOT / 'generated/narration-blocks-v2/B09'
SCENE_IDS = ('B09-028', 'B09-029', 'B09-030', 'B09-031', 'B09-032', 'B09-033', 'B09-034')
VARIANT = 'B09-review-01'
LEAD = .6
RATE = 44100
FPS = 30
FRAME_BYTES = 1920 * 1080 * 3 // 2


def inputs():
    validate()
    validate_block_approval('B07')
    spec = json.loads((ROOT / 'tutorial.yaml').read_text())
    module = next(m for m in spec['narration_modules'] if m['id'] == 'B09')
    hit = cached(spec, module)
    if not hit:
        raise RuntimeError('B09 one-request narration is missing or stale')
    metadata = json.loads((AUDIO / f'{VARIANT}-metadata.json').read_text())
    review = json.loads((AUDIO / 'B09-review-map.json').read_text())
    if (review['status'], review['block_id'], review['variant_id']) != ('SEMANTIC_REVIEWED', 'B09', 'review-01'):
        raise RuntimeError('B09 semantic review map invalid')
    for path, digest in ((AUDIO / 'narration.mp3', metadata['source_mp3_sha256']),
                         (AUDIO / f'{VARIANT}.mp3', metadata['mp3_sha256']),
                         (AUDIO / f'{VARIANT}.wav', metadata['wav_sha256']),
                         (AUDIO / f'{VARIANT}-timing.json', metadata['timing_sha256'])):
        if sha(path) != digest:
            raise RuntimeError('B09 reviewed audio source changed: ' + str(path))
    if (metadata['source_mp3_sha256'] != hit['metadata']['audio_sha256']
            or metadata['new_tts_requests'] or metadata['speed_pitch_gain_processing']
            or not metadata['source_pcm_recovered_exactly'] or metadata['events']):
        raise RuntimeError('B09 review must preserve the one unmodified source take')
    with wave.open(str(AUDIO / f'{VARIANT}.wav')) as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, RATE):
            raise RuntimeError('B09 WAV format invalid')
        pcm = wav.readframes(wav.getnframes())
        duration = wav.getnframes() / RATE
    if hashlib.sha256(pcm).hexdigest() != metadata['final_pcm_sha256']:
        raise RuntimeError('B09 PCM source changed')
    timing = json.loads((AUDIO / f'{VARIANT}-timing.json').read_text())
    if timing != map_timing(spec, module, timing['alignment'], timing['duration_seconds']):
        raise RuntimeError('B09 alignment no longer maps to canonical text')
    scenes = [s for s in spec['scenes'] if s['id'] in SCENE_IDS]
    if tuple(s['id'] for s in scenes) != SCENE_IDS:
        raise RuntimeError('B09 storyboard order changed')
    return spec, module, scenes, metadata, timing, pcm, duration


def scene_timing(spec, module, scene, timing, metadata, audio_duration):
    row = next(r for r in timing['scenes'] if r['scene_id'] == scene['id'])
    start = row['range_start_seconds']
    end = min(row['range_end_seconds'], audio_duration)
    _, indices = request_text_and_indices(spec, module)
    positions = indices[scene['start_offset']:scene['end_offset']]
    full = timing['alignment']
    alignment = {'characters': [full['characters'][i] for i in positions],
                 'character_start_times_seconds': [max(0, full['character_start_times_seconds'][i]-start) for i in positions],
                 'character_end_times_seconds': [max(0, full['character_end_times_seconds'][i]-start) for i in positions]}
    if ''.join(alignment['characters']) != scene['narration']:
        raise RuntimeError('B09 scene alignment differs from canonical text')
    return {**row, 'alignment': alignment, 'duration_seconds': end-start,
            'range_start_seconds': start, 'range_end_seconds': end,
            'timing_identity': hashlib.sha256((metadata['timing_sha256']+scene['id']).encode()).hexdigest()}


def capture_spec(scene):
    return {**scene, 'visual': {'type': 'browser', 'goal': scene['goal'],
                               'capture_pipeline_revision': 'b09-edit-tools-waveform-gestures-v1'},
            'initial_state': 'speaker-source-tracks', 'expected_state': 'B09 explained action completed',
            'assertions': [], 'fixture_set': 'existing-synthetic-zoom-v1',
            'padding': {'head': 0., 'tail': 0.}}


def track(page, filename):
    return page.locator('#speaker-editor-tracks .speaker-track').filter(has_text=filename)


async def payload(page):
    return await page.evaluate("async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload")


def inner_regions(data, kind):
    return [r for r in data[kind] if r['startSeconds'] > 0 and r['endSeconds'] < 18]


async def raw_seed_region(page, kind, name, start, end):
    ident = await track(page, name).get_attribute('data-track-id')
    await page.locator('#speaker-editor-selection-track').select_option(ident)
    for edge, value in (('start', start), ('end', end)):
        await page.locator('#speaker-editor-selection-' + edge).fill(str(value))
    button = page.locator('#speaker-editor-add-' + kind)
    if await button.get_attribute('aria-pressed') != 'true':
        await button.click()
    await track(page, name).locator('.speaker-waveform').focus()
    await page.keyboard.press('Enter')
    key = 'globalCuts' if kind == 'cut' else 'trackSilenceRegions'
    if len(inner_regions(await payload(page), key)) != 1:
        raise RuntimeError('B09 seed region was not committed: ' + kind)
    await page.keyboard.press('Escape')


async def raw_seed_edge(page, locator, delta_seconds):
    await locator.scroll_into_view_if_needed()
    box = await locator.bounding_box()
    if not box:
        raise RuntimeError('B09 seed edge unavailable')
    pps = await page.locator('#speaker-editor-tracks .speaker-waveform').first.evaluate('e=>e.getBoundingClientRect().width/18')
    x, y = box['x'] + box['width']/2, box['y'] + box['height']/2
    await page.mouse.move(x,y)
    await page.mouse.down()
    await page.mouse.move(x+delta_seconds*pps,y,steps=10)
    await page.mouse.up()


async def raw_seed_numeric(page, key, edge, value):
    region = inner_regions(await payload(page), key)[0]
    row = page.locator(f'#speaker-editor-regions .speaker-region-row[data-region-id="{region["regionId"]}"]')
    field = row.locator('input').nth(0 if edge == 'start' else 1)
    await field.fill(str(value))
    await row.get_by_role('button', name='Применить границы').click()
    updated = inner_regions(await payload(page), key)[0]
    if abs(updated[edge+'Seconds']-value) > .001:
        raise RuntimeError('B09 seed numeric update did not commit')


async def prepare(page, scene, base):
    await page.set_viewport_size({'width':1728,'height':972})
    await login(page,base)
    await import_local(page,base,'speaker')
    await page.wait_for_function("document.querySelectorAll('#speaker-editor-tracks .speaker-track canvas').length===4 && !document.querySelector('#speaker-editor-tracks .speaker-source-pending')",timeout=60000)
    await page.locator('#speaker-editor-scale-mode').click()
    await page.locator('#speaker-editor-zoom').fill('168')
    await page.locator('#speaker-editor-tracks .speaker-track').first.scroll_into_view_if_needed()
    await page.wait_for_timeout(350)
    scene_id=scene['id']
    if scene_id == 'B09-029':
        await page.locator('#speaker-editor-add-cut').click()
    if scene_id in ('B09-030','B09-031','B09-032','B09-033','B09-034'):
        await raw_seed_region(page,'cut','Спикер.wav',5.2,6.5)
    if scene_id == 'B09-031':
        await page.locator('#speaker-editor-add-silence').click()
    if scene_id in ('B09-032','B09-033','B09-034'):
        await raw_seed_region(page,'silence','Переводчик 1.wav',9,10)
    if scene_id in ('B09-033','B09-034'):
        first=track(page,'Спикер.wav').locator('.speaker-waveform')
        await raw_seed_edge(page,first.locator('.speaker-boundary--start'),.8)
        await raw_seed_edge(page,first.locator('.speaker-boundary--end'),-1.)
        cut=inner_regions(await payload(page),'globalCuts')[0]
        await raw_seed_edge(page,first.locator(f'[data-region-id="{cut["regionId"]}"] [data-edge=start]'),-.3)
        silence=inner_regions(await payload(page),'trackSilenceRegions')[0]
        await raw_seed_edge(page,track(page,'Переводчик 1.wav').locator(f'[data-region-id="{silence["regionId"]}"] [data-edge=end]'),.4)
    if scene_id == 'B09-034':
        await page.locator('.speaker-regions > summary').click()
    if scene_id == 'B09-034':
        await raw_seed_numeric(page,'globalCuts','end',6.3)
        await raw_seed_numeric(page,'trackSilenceRegions','start',9.1)
        cut=inner_regions(await payload(page),'globalCuts')[0]
        await track(page,'Спикер.wav').locator(f'[data-region-id="{cut["regionId"]}"]').first.click()
        if await page.locator('#speaker-editor-add-cut').get_attribute('data-mode')!='restore':
            raise RuntimeError('B09 selected cut not seeded')
    await page.locator('#speaker-editor-tracks .speaker-track').first.scroll_into_view_if_needed()
    await page.evaluate('async()=>{await document.fonts.ready;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))}')
    await page.wait_for_timeout(350)


async def cue_wait(cue, phrase):
    await cue(phrase)
    await cue.__self__.wait_pending()


async def visible_wave_drag(page,name,start,end):
    wave=track(page,name).locator('.speaker-waveform-scroll').raw
    await wave.scroll_into_view_if_needed()
    box=await wave.bounding_box()
    data=await wave.evaluate('e=>({left:e.scrollLeft,width:e.scrollWidth})')
    if not box or data['width']<=0:
        raise RuntimeError('B09 waveform gesture geometry unavailable')
    pps=data['width']/18
    x1=box['x']+start*pps-data['left'];x2=box['x']+end*pps-data['left']
    y=box['y']+box['height']*.65
    if not box['x']+12<x1<x2<box['x']+box['width']-12:
        raise RuntimeError('B09 selected interval is outside displayed waveform')
    await page.mouse.move(x1,y)
    await page.mouse.down()
    await page.tutorial.move(x2,y,duration=.9)
    await asyncio.sleep(.15)
    await page.mouse.up()
    return {'start':start,'end':end,'track':name,'start_point':[x1,y],'end_point':[x2,y]}


async def visible_edge_drag(page,locator,delta_seconds,label):
    raw=locator.raw
    await raw.scroll_into_view_if_needed()
    box=await raw.bounding_box()
    if not box:
        raise RuntimeError('B09 drag edge not visible: '+label)
    pps=await page.locator('#speaker-editor-tracks .speaker-waveform').first.evaluate('e=>e.getBoundingClientRect().width/18')
    x,y=box['x']+box['width']/2,box['y']+box['height']/2
    before=float(await raw.get_attribute('aria-valuenow'))
    await page.mouse.move(x,y)
    await page.mouse.down()
    await page.tutorial.move(x+delta_seconds*pps,y,duration=.85)
    preview=float(await raw.get_attribute('aria-valuenow'))
    if abs(preview-before)<.08:
        raise RuntimeError('B09 edge had no visible preview: '+label)
    page.tutorial.events.append({'type':'drag-preview','seconds':page.tutorial.now(),'label':label,'before':before,'preview':preview})
    await asyncio.sleep(.12)
    await page.mouse.up()
    final=float(await raw.get_attribute('aria-valuenow'))
    if abs(final-preview)>.08:
        raise RuntimeError('B09 edge result differs from visible preview: '+label)
    page.tutorial.events.append({'type':'drag-result','seconds':page.tutorial.now(),'label':label,'final':final})
    return final


async def perform(page,scene,base,cue):
    scene_id=scene['id']
    if scene_id=='B09-028':
        await cue('сначала выбирается нужный инструмент')
        await page.locator('#speaker-editor-add-cut').click()
        if await page.locator('#speaker-editor-add-cut').get_attribute('aria-pressed')!='true':
            raise RuntimeError('B09 cut tool was not armed before waveform selection')
        await page.evaluate("window.__s11Capture.hide('tool-selected')")
    elif scene_id=='B09-029':
        if await page.locator('#speaker-editor-add-cut').get_attribute('aria-pressed')!='true':
            raise RuntimeError('B09 cut tool not selected at scene start')
        await cue('на любой из дорожек')
        gesture=await visible_wave_drag(page,'Спикер.wav',5.2,6.5)
        data=await payload(page)
        counts=[await track(page,name).locator('.speaker-region-overlay--cut').count()
                for name in ('Спикер.wav','Переводчик 1.wav','Переводчик 2.wav')]
        if len(inner_regions(data,'globalCuts'))!=1 or counts!=[1,1,1]:
            raise RuntimeError('B09 global cut did not appear across tracks')
        page.tutorial.events.append({'type':'edit-result','seconds':page.tutorial.now(),'action':'global-cut','gesture':gesture,'region':inner_regions(data,'globalCuts')[0]})
        await page.evaluate("window.__s11Capture.hide('global-cut-visible')")
    elif scene_id=='B09-030':
        await cue('воспроизведения в редакторе')
        await page.evaluate("""() => {
          const audio=document.querySelector('#speaker-editor-source-audio');audio.currentTime=4.85;
          window.__b09Playback=[];let previous=audio.currentTime;
          const sample=()=>{window.__b09Playback.push(audio.currentTime);if(!audio.paused)requestAnimationFrame(sample)};
          audio.addEventListener('play',sample,{once:true});
        }""")
        await page.locator('#speaker-editor-source-audio-play').click()
        await page.wait_for_timeout(1700)
        times=await page.evaluate('window.__b09Playback')
        if not times or max(times)<6.6 or not any(b-a>.7 for a,b in zip(times,times[1:])):
            raise RuntimeError('B09 source preview did not skip the global cut')
        page.tutorial.events.append({'type':'playback-cut-skip','seconds':page.tutorial.now(),'max_jump_seconds':max(b-a for a,b in zip(times,times[1:]))})
        await page.locator('#speaker-editor-source-audio-stop').click()
        await cue('используется инструмент')
        await page.locator('#speaker-editor-add-silence').click()
        if await page.locator('#speaker-editor-add-silence').get_attribute('aria-pressed')!='true':
            raise RuntimeError('B09 silence tool did not arm')
        await page.evaluate("window.__s11Capture.hide('silence-tool-selected')")
    elif scene_id=='B09-031':
        await cue('на той дорожке')
        gesture=await visible_wave_drag(page,'Переводчик 1.wav',9,10)
        data=await payload(page)
        if len(inner_regions(data,'trackSilenceRegions'))!=1 or await track(page,'Переводчик 1.wav').locator('.speaker-region-overlay--silence').count()!=1 or await track(page,'Спикер.wav').locator('.speaker-region-overlay--silence').count():
            raise RuntimeError('B09 silence was not limited to one track')
        page.tutorial.events.append({'type':'edit-result','seconds':page.tutorial.now(),'action':'single-track-silence','gesture':gesture,'region':inner_regions(data,'trackSilenceRegions')[0]})
        await page.evaluate("window.__s11Capture.hide('silence-result')")
    elif scene_id=='B09-032':
        first=track(page,'Спикер.wav').locator('.speaker-waveform')
        await cue('перетащить соответствующий маркер')
        await visible_edge_drag(page,first.locator('.speaker-boundary--start'),.8,'recording-start')
        await cue('после маркера «Конец»')
        await visible_edge_drag(page,first.locator('.speaker-boundary--end'),-1.,'recording-end')
        await cue('После создания выреза')
        cut=inner_regions(await payload(page),'globalCuts')[0]
        await visible_edge_drag(page,first.locator(f'[data-region-id="{cut["regionId"]}"] [data-edge=start]'),-.3,'cut-start')
        silence=inner_regions(await payload(page),'trackSilenceRegions')[0]
        await visible_edge_drag(page,track(page,'Переводчик 1.wav').locator(f'[data-region-id="{silence["regionId"]}"] [data-edge=end]'),.4,'silence-end')
        data=await payload(page)
        if len(data['globalCuts'])!=3 or len(inner_regions(data,'trackSilenceRegions'))!=1:
            raise RuntimeError('B09 final marker/edge edit count invalid')
        await page.evaluate("window.__s11Capture.hide('edge-edits-complete')")
    elif scene_id=='B09-033':
        await cue('требуется более')
        await page.locator('.speaker-regions > summary').click()
        cut=inner_regions(await payload(page),'globalCuts')[0]
        row=page.locator(f'#speaker-editor-regions .speaker-region-row[data-region-id="{cut["regionId"]}"]')
        await cue('точные значения границ')
        await row.locator('input').nth(1).fill('6.3')
        await row.get_by_role('button', name='Применить границы').click()
        silence=inner_regions(await payload(page),'trackSilenceRegions')[0]
        row=page.locator(f'#speaker-editor-regions .speaker-region-row[data-region-id="{silence["regionId"]}"]')
        await row.locator('input').nth(0).fill('9.1')
        await row.get_by_role('button', name='Применить границы').click()
        data=await payload(page)
        if abs(inner_regions(data,'globalCuts')[0]['endSeconds']-6.3)>.001 or abs(inner_regions(data,'trackSilenceRegions')[0]['startSeconds']-9.1)>.001:
            raise RuntimeError('B09 numeric region changes did not commit: '+str((inner_regions(data,'globalCuts'),inner_regions(data,'trackSilenceRegions'))))
        await cue('сперва выбрать')
        cut=inner_regions(data,'globalCuts')[0]
        await track(page,'Спикер.wav').locator(f'[data-region-id="{cut["regionId"]}"]').first.click()
        if await page.locator('#speaker-editor-add-cut').get_attribute('data-mode')!='restore':
            raise RuntimeError('B09 cut selection did not expose restore action')
        await page.evaluate("window.__s11Capture.hide('selected-cut')")
    elif scene_id=='B09-034':
        if await page.locator('#speaker-editor-add-cut').get_attribute('data-mode')!='restore':
            raise RuntimeError('B09 cut restore action missing at scene start')
        await cue('«Снять вырез»')
        await page.locator('#speaker-editor-add-cut').click()
        if inner_regions(await payload(page),'globalCuts'):
            raise RuntimeError('B09 selected cut was not removed')
        silence=inner_regions(await payload(page),'trackSilenceRegions')[0]
        await track(page,'Переводчик 1.wav').locator(f'[data-region-id="{silence["regionId"]}"]').first.click()
        if await page.locator('#speaker-editor-add-silence').get_attribute('data-mode')!='restore':
            raise RuntimeError('B09 selected silence did not expose restore action')
        await cue('в зависимости от того')
        await page.locator('#speaker-editor-add-silence').click()
        if inner_regions(await payload(page),'trackSilenceRegions'):
            raise RuntimeError('B09 selected silence was not removed')
        await cue('«Отменить»')
        await page.locator('#speaker-editor-undo').click()
        if len(inner_regions(await payload(page),'trackSilenceRegions'))!=1:
            raise RuntimeError('B09 Undo did not restore the removed silence')
        await cue('снова применить')
        await page.locator('#speaker-editor-redo').click()
        if inner_regions(await payload(page),'trackSilenceRegions'):
            raise RuntimeError('B09 Redo did not remove silence again')
        await page.evaluate("window.__s11Capture.hide('history-complete')")
    else:
        raise RuntimeError('unexpected B09 scene')
    await page.evaluate("window.__s11Capture.hide('scene-complete')")


async def visual():
    if (ROOT / 'approvals/B09-block.json').exists():
        raise RuntimeError('B09 complete block is approved and immutable')
    spec, module, scenes, metadata, timing, _, audio_duration = inputs()
    (OUT / 'scenes').mkdir(parents=True, exist_ok=True)
    recipe = '\n'.join(inspect.getsource(fn) for fn in
                       (capture_spec, track, payload, inner_regions, raw_seed_region, raw_seed_edge, raw_seed_numeric, prepare, cue_wait, visible_wave_drag, visible_edge_drag, perform))
    identity = hashlib.sha256(recipe.encode()).hexdigest()
    rows = []
    with demo_server(None) as base:
        for scene in scenes:
            local = scene_timing(spec, module, scene, timing, metadata, audio_duration)
            local.update(visual_lead_seconds=LEAD if scene['id'] == SCENE_IDS[0] else 0.,
                         visual_source_sha256=identity, strict_choreography=False)
            path = OUT / 'scenes' / f"{scene['id']}.mp4"
            evidence = await capture(capture_spec(scene), spec['narration'], base, timing=local,
                                     destination=path, prepare_scene=prepare, perform_scene=perform)
            if evidence['browser_errors'] or evidence['production_mutation_requests']:
                raise RuntimeError('B09 isolated capture failed')
            if max((e['seconds'] for e in evidence['choreography']['events']), default=0) > local['duration_seconds']+local['visual_lead_seconds']+.2:
                raise RuntimeError(f"B09 {scene['id']} action extends beyond its narrated scene")
            row = {'scene_id': scene['id'], 'visual': str(path), 'sha256': sha(path),
                   'duration_seconds': evidence['duration_seconds'],
                   'cue_errors_seconds': [c['actual_seconds']-c['target_seconds'] for c in evidence['alignment_action_cues']],
                   'production_mutation_requests': evidence['production_mutation_requests']}
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    result = {'status':'PASS','block_id':'B09','source_mp3_sha256':metadata['source_mp3_sha256'],
              'final_wav_sha256':metadata['wav_sha256'],'tts_requests':0,'scenes':rows}
    write_json(OUT / 'visual-capture.json', result)
    return result


def subtitles(scenes, timings):
    cues = []
    for scene, timing in zip(scenes, timings):
        text = scene['narration']
        starts = timing['alignment']['character_start_times_seconds']
        ends = timing['alignment']['character_end_times_seconds']
        words = list(re.finditer(r'\S+', text))
        begin = 0
        for i, word in enumerate(words):
            first, last = words[begin].start(), word.end()-1
            phrase = ' '.join(text[first:last+1].split())
            if len(phrase) >= 68 or word.group()[-1:] in '.!?…' or i == len(words)-1:
                start = LEAD + timing['range_start_seconds'] + starts[first]
                end = LEAD + timing['range_start_seconds'] + ends[last]
                if end <= start or '[' in phrase or ']' in phrase:
                    raise RuntimeError('B09 subtitle timing/text invalid')
                cues.append((start,end,phrase));begin=i+1
    if any(cues[i][0] < cues[i-1][1]-.01 for i in range(1,len(cues))):
        raise RuntimeError('B09 subtitle cues overlap')
    for suffix in ('srt','vtt'):
        vtt = suffix == 'vtt'
        content = ('WEBVTT\n\n' if vtt else '') + '\n\n'.join(
            ('' if vtt else f'{i}\n') + f'{timestamp(a,vtt=vtt)} --> {timestamp(b,vtt=vtt)}\n{text}'
            for i,(a,b,text) in enumerate(cues,1)) + '\n'
        (OUT / f'B09.ru.{suffix}').write_text(content)
    return cues


def assemble():
    if (ROOT / 'approvals/B09-block.json').exists():
        raise RuntimeError('B09 complete block is approved and immutable')
    spec,module,scenes,metadata,timing,pcm,audio_duration=inputs()
    capture_report=json.loads((OUT/'visual-capture.json').read_text())
    if (capture_report['source_mp3_sha256']!=metadata['source_mp3_sha256']
            or [r['scene_id'] for r in capture_report['scenes']]!=list(SCENE_IDS)):
        raise RuntimeError('B09 scene capture differs from source audio')
    timings=[scene_timing(spec,module,s,timing,metadata,audio_duration) for s in scenes]
    cues=subtitles(scenes,timings)
    timeline=OUT/'B09-video-timeline.wav'
    with wave.open(str(timeline),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(RATE)
        wav.writeframes(bytes(round(LEAD*RATE)*2)+pcm)
    duration=math.ceil(max(LEAD+audio_duration,cues[-1][1]+.01)*FPS)/FPS
    bounds=[0]+[LEAD+t['range_start_seconds'] for t in timings[1:]]+[duration]
    counts=[round(bounds[i+1]*FPS)-round(bounds[i]*FPS) for i in range(len(scenes))]
    if min(counts)<=0:
        raise RuntimeError('B09 scene frame count invalid')
    candidate=OUT/'B09.tmp.mp4'
    command=['ffmpeg','-y','-v','error','-f','rawvideo','-pixel_format','yuv420p',
             '-video_size','1920x1080','-framerate',str(FPS),'-i','pipe:0',
             '-i',str(timeline),'-i',str(OUT/'B09.ru.srt'),
             '-map','0:v:0','-map','1:a:0','-map','2:s:0',
             '-c:v','libx264','-preset','veryfast','-crf','21','-pix_fmt','yuv420p',
             '-c:a','aac','-b:a','192k','-c:s','mov_text','-metadata:s:s:0','language=rus',
             '-frames:v',str(sum(counts)),'-movflags','+faststart',str(candidate)]
    with (OUT/'encode.log').open('wb') as log:
        encoder=subprocess.Popen(command,stdin=subprocess.PIPE,stderr=log)
        try:
            for scene,count in zip(scenes,counts):
                path=OUT/'scenes'/f"{scene['id']}.mp4"
                if not path.is_file():
                    raise RuntimeError('B09 scene missing: '+scene['id'])
                decoder=subprocess.Popen(['ffmpeg','-v','error','-xerror','-i',str(path),'-an',
                                          '-vf','scale=1920:1080,fps=30,trim=start_frame=1,'
                                                'tpad=start=1:start_mode=clone,setpts=N/(30*TB),'
                                                'tpad=stop_mode=clone:stop=300',
                                          '-r',str(FPS),'-frames:v',str(count),'-pix_fmt','yuv420p',
                                          '-f','rawvideo','pipe:1'],stdout=subprocess.PIPE)
                copied=0
                try:
                    while chunk:=decoder.stdout.read(1024*1024):
                        encoder.stdin.write(chunk);copied+=len(chunk)
                finally:
                    decoder.stdout.close()
                if decoder.wait() or copied!=count*FRAME_BYTES:
                    raise RuntimeError('B09 captured frame count mismatch: '+scene['id'])
            encoder.stdin.close()
            if encoder.wait():
                raise RuntimeError('B09 MP4 encoding failed; see encode.log')
        finally:
            if encoder.poll() is None:
                encoder.kill();encoder.wait()
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(candidate),'-f','null','-'],
                   check=True,stdout=subprocess.DEVNULL)
    canonical=' '.join(' '.join(s['narration'].split()) for s in scenes)
    checked=check_embedded_subtitles(candidate,OUT/'B09.ru.srt',canonical)
    final=OUT/'B09.mp4';candidate.replace(final)
    report={'status':'READY FOR B09 BLOCK REVIEW','block_id':'B09','video':str(final),
            'video_sha256':sha(final),'duration_seconds':duration,
            'source_mp3_sha256':metadata['source_mp3_sha256'],'final_mp3_sha256':metadata['mp3_sha256'],
            'final_wav_sha256':metadata['wav_sha256'],'final_pcm_sha256':metadata['final_pcm_sha256'],
            'final_alignment_sha256':metadata['timing_sha256'],'video_audio_timeline':str(timeline),
            'video_audio_lead_seconds':LEAD,'internal_audio_silence_added_seconds':0,
            'scene_frame_counts':dict(zip(SCENE_IDS,counts)),
            'embedded_subtitle_cues':checked['embedded_subtitle_cues'],
            'last_embedded_subtitle_end_seconds':checked['last_embedded_subtitle_end_seconds'],
            'new_tts_requests':0,'production_mutation_requests':0}
    write_json(OUT/'report.json',report)
    return report


def pointer_pixels_in_mp4(video:Path,evidence:dict,scene_start:float,scene_id:str,evidence_dir:Path):
    events=evidence['choreography']['events']
    arrivals=[e for e in events if e['type']=='cursor-arrival']
    clicks=[e for e in events if e['type']=='click']
    pointerdowns=[e for e in evidence['choreography']['overlay']['events'] if e['type']=='pointerdown']
    expected=len(clicks)
    if len(arrivals)<expected or len(pointerdowns)<expected:
        raise RuntimeError(f'{scene_id} expected {expected} real clicks, got {len(clicks)}')
    viewport_w,viewport_h=evidence['choreography']['overlay']['viewport']
    evidence_dir.mkdir(parents=True,exist_ok=True)
    checks=[]
    click_arrivals=[]
    for click in clicks:
        matching=[a for a in arrivals if a['target']==click['target'] and a['seconds']<=click['seconds']]
        if not matching:
            raise RuntimeError(f'{scene_id} real click has no matching pointer arrival')
        click_arrivals.append(max(matching,key=lambda a:a['seconds']))
    for number,(arrival,click) in enumerate(zip(click_arrivals,clicks),1):
        box=arrival['box']
        pointer=pointerdowns[-expected+number-1]
        if not (box['x']<=pointer['x']<=box['x']+box['width']
                and box['y']<=pointer['y']<=box['y']+box['height']):
            raise RuntimeError(f'{scene_id} click {number} pointer tip is outside its real control')
        target=[box['x']*960/viewport_w,box['y']*540/viewport_h,
                (box['x']+box['width'])*960/viewport_w,(box['y']+box['height'])*540/viewport_h]
        press=scene_start+click['seconds'];start=press-.3
        rgb=subprocess.check_output(['ffmpeg','-v','error','-ss',f'{start:.6f}','-i',str(video),
                                     '-t','0.9','-vf','fps=30,scale=960:540,format=rgb24',
                                     '-f','rawvideo','-'])
        frame_bytes=960*540*3;best=(0,-1,None)
        for frame_number in range(len(rgb)//frame_bytes):
            frame=rgb[frame_number*frame_bytes:(frame_number+1)*frame_bytes]
            points=[]
            for y in range(max(0,int(target[1])-12),min(540,int(target[3])+12)):
                for x in range(max(0,int(target[0])-12),min(960,int(target[2])+12)):
                    k=(y*960+x)*3;r,g,b=frame[k:k+3]
                    if r>=190 and 115<=g<=240 and b<=170 and r>g+8 and g>b+25:
                        points.append((x,y))
            if len(points)>best[0]:
                best=(len(points),frame_number,
                      [min(x for x,_ in points),min(y for _,y in points),
                       max(x for x,_ in points),max(y for _,y in points)] if points else None)
        count,frame_number,ring=best
        center=((ring[0]+ring[2])/2,(ring[1]+ring[3])/2) if ring else None
        if count<4 or ring is None or not (target[0]<=center[0]<=target[2]
                                                and target[1]<=center[1]<=target[3]):
            raise RuntimeError(f'{scene_id} click {number} misses its rendered button: ring={ring}, button={target}, gold_pixels={count}')
        frame_time=start+frame_number/FPS
        for label,when in (('before',frame_time-.35),('press',frame_time),('after',frame_time+.65)):
            png=subprocess.check_output(['ffmpeg','-v','error','-ss',f'{when:.6f}','-i',str(video),
                                         '-frames:v','1','-f','image2pipe','-vcodec','png','-'])
            (evidence_dir/f'click-{number}-{label}.png').write_bytes(png)
        check={'click':number,'target':arrival['target'],'status':'PASS',
               'button_box_half_resolution':target,'rendered_ring_box_half_resolution':ring,
               'ring_pixels':count,'press_frame_seconds':frame_time}
        checks.append(check)
    if evidence['choreography']['overlay']['cursorVisible']:
        raise RuntimeError(f'{scene_id} cursor remains visible at scene end')
    return checks


def gesture_pixels_in_mp4(video:Path,evidence:dict,scene_start:float,scene_id:str,evidence_dir:Path):
    events=evidence['choreography']['events']
    starts=[e for e in events if e['type']=='drag-start']
    moves=[e for e in events if e['type']=='drag-move']
    ends=[e for e in events if e['type']=='drag-end']
    if len(starts)!=len(moves) or len(moves)!=len(ends):
        raise RuntimeError(f'{scene_id} incomplete drag gesture')
    if scene_id in ('B09-029','B09-031') and len(starts)!=1:
        raise RuntimeError(f'{scene_id} missing waveform selection drag')
    if scene_id=='B09-032' and len(starts)!=4:
        raise RuntimeError('B09 boundary and region edge drags incomplete')
    previews=[e for e in events if e['type']=='drag-preview']
    results=[e for e in events if e['type']=='drag-result']
    if scene_id=='B09-032' and (len(previews)!=4 or len(results)!=4):
        raise RuntimeError('B09 boundary drag previews/results missing')
    for preview,result in zip(previews,results):
        if (preview['label']!=result['label'] or abs(preview['preview']-result['final'])>.08
                or abs(preview['preview']-preview['before'])<.08):
            raise RuntimeError('B09 drag did not commit its visible preview')
    if not starts:
        return []
    viewport_w,viewport_h=evidence['choreography']['overlay']['viewport']
    evidence_dir.mkdir(parents=True,exist_ok=True)
    def rgb_at(when):
        data=subprocess.check_output(['ffmpeg','-v','error','-ss',f'{when:.6f}','-i',str(video),
                                      '-frames:v','1','-vf','scale=960:540,format=rgb24','-f','rawvideo','-'])
        if len(data)!=960*540*3:
            raise RuntimeError(f'{scene_id} missing rendered drag frame at {when:.3f}')
        return data
    checks=[]
    for index,(start,move,end) in enumerate(zip(starts,moves,ends),1):
        if not (start['seconds']<move['seconds']<end['seconds']):
            raise RuntimeError(f'{scene_id} drag {index} gesture order invalid')
        before=scene_start+max(.01,start['seconds']-.2)
        during=scene_start+(start['seconds']+move['seconds'])/2
        after=scene_start+end['seconds']+.25
        frames={label:rgb_at(when) for label,when in (('before',before),('during',during),('after',after))}
        for label,when in (('before',before),('during',during),('after',after)):
            png=subprocess.check_output(['ffmpeg','-v','error','-ss',f'{when:.6f}','-i',str(video),
                                         '-frames:v','1','-f','image2pipe','-vcodec','png','-'])
            (evidence_dir/f'drag-{index}-{label}.png').write_bytes(png)
        x1,y1=move['start'];x2,_=move['end']
        xlo=max(0,int((min(x1,x2)-16)*960/viewport_w))
        xhi=min(960,int((max(x1,x2)+16)*960/viewport_w))
        ylo=max(0,int((y1-55)*540/viewport_h))
        yhi=min(540,int((y1-18)*540/viewport_h))
        changed=0
        a,b=frames['before'],frames['after']
        for y in range(ylo,yhi):
            for x in range(xlo,xhi):
                offset=(y*960+x)*3
                if sum(abs(a[offset+c]-b[offset+c]) for c in range(3))>45:
                    changed+=1
        if changed<15:
            raise RuntimeError(f'{scene_id} drag {index} has no rendered result near the edited interval: {changed} pixels')
        checks.append({'drag':index,'status':'PASS','before_seconds':before,'during_seconds':during,
                       'after_seconds':after,'edited_interval_box_half_resolution':[xlo,ylo,xhi,yhi],
                       'changed_pixels_away_from_cursor':changed})
    return checks


def history_pixels_in_mp4(video:Path,evidence:dict,scene_start:float,evidence_dir:Path):
    clicks=[e for e in evidence['choreography']['events'] if e['type']=='click']
    if len(clicks)!=5 or not clicks[-2]['target'].endswith("selector='#speaker-editor-undo'>") or not clicks[-1]['target'].endswith("selector='#speaker-editor-redo'>"):
        raise RuntimeError('B09 Undo/Redo click history is incomplete')
    moments={'before_undo':scene_start+clicks[-2]['seconds']-.7,
             'after_undo':scene_start+clicks[-2]['seconds']+.7,
             'after_redo':scene_start+clicks[-1]['seconds']+.35}
    evidence_dir.mkdir(parents=True,exist_ok=True)
    counts={}
    # The single-track silence overlay occupies this stable rendered band in
    # the final 960x540 editor frame; no pointer enters this band at these times.
    for label,when in moments.items():
        rgb=subprocess.check_output(['ffmpeg','-v','error','-ss',f'{when:.6f}','-i',str(video),
                                     '-frames:v','1','-vf','scale=960:540,format=rgb24','-f','rawvideo','-'])
        if len(rgb)!=960*540*3:
            raise RuntimeError('B09 final MP4 history frame missing')
        png=subprocess.check_output(['ffmpeg','-v','error','-ss',f'{when:.6f}','-i',str(video),
                                     '-frames:v','1','-f','image2pipe','-vcodec','png','-'])
        (evidence_dir/f'{label}.png').write_bytes(png)
        count=0
        for y in range(95,185):
            for x in range(490,532):
                i=(y*960+x)*3;r,g,b=rgb[i:i+3]
                if 60<=r<=140 and 60<=g<=130 and 20<=b<=85 and r>b*1.5:
                    count+=1
        counts[label]=count
    if not (counts['before_undo']<100 and counts['after_undo']>500 and counts['after_redo']<100):
        raise RuntimeError(f'B09 rendered Undo/Redo does not remove, restore and remove silence: {counts}')
    return {'status':'PASS','sample_times_seconds':moments,'silence_overlay_pixels':counts}


def visual_transition_anomalies(raw:bytes, *, width=48, height=27, fps=FPS):
    """Find brief A→B→A screens and clustered full-frame capture jumps."""
    pixels=width*height
    if len(raw)%pixels:
        raise RuntimeError('B09 visual transition scan received partial frame')
    frames=[memoryview(raw)[i:i+pixels] for i in range(0,len(raw),pixels)]
    sampled=range(0,pixels,2)
    def distance(a,b):
        return sum(abs(frames[a][i]-frames[b][i]) for i in sampled)/len(sampled)
    jumps=[i for i in range(1,len(frames)) if distance(i-1,i)>20]
    anomalies=[]
    for position,start in enumerate(jumps):
        for end in jumps[position+1:]:
            if end-start>30:break
            if distance(start-1,end)<5 and distance(start-1,(start+end)//2)>20:
                anomalies.append({'type':'brief_screen_return','start_frame':start,'end_frame':end,
                                  'start_seconds':start/fps,'end_seconds':end/fps})
                break
    for start,end in zip(jumps,jumps[1:]):
        if end-start<=18 and not any(a['start_frame']==start and a['end_frame']==end for a in anomalies):
            anomalies.append({'type':'clustered_screen_jumps','start_frame':start,'end_frame':end,
                              'start_seconds':start/fps,'end_seconds':end/fps})
    return sorted(anomalies,key=lambda row:(row['start_frame'],row['end_frame']))


def verify():
    spec,module,scenes,metadata,timing,pcm,_=inputs()
    report=json.loads((OUT/'report.json').read_text());video=OUT/'B09.mp4'
    if sha(video)!=report['video_sha256'] or report['final_wav_sha256']!=metadata['wav_sha256']:
        raise RuntimeError('B09 video or source audio changed')
    with wave.open(str(OUT/'B09-video-timeline.wav')) as wav:
        timeline=wav.readframes(wav.getnframes())
    lead=round(LEAD*RATE)*2
    if timeline[:lead]!=bytes(lead) or timeline[lead:]!=pcm:
        raise RuntimeError('B09 video timeline changed source PCM')
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(video)]))
    streams={s['codec_type']:s for s in probe['streams']}
    frames=sum(report['scene_frame_counts'].values())
    if (int(streams['video']['nb_frames'])!=frames or streams['video']['r_frame_rate']!='30/1'
            or streams['audio']['codec_name']!='aac' or streams['subtitle']['codec_name']!='mov_text'):
        raise RuntimeError('B09 MP4 stream format invalid')
    canonical=' '.join(' '.join(s['narration'].split()) for s in scenes)
    checked=check_embedded_subtitles(video,OUT/'B09.ru.srt',canonical)
    decoded=subprocess.check_output(['ffmpeg','-v','error','-xerror','-i',str(video),'-map','0:a:0',
                                     '-ac','1','-ar',str(RATE),'-c:a','pcm_s16le','-f','s16le','-'])
    actual=array.array('h');actual.frombytes(decoded)
    expected=array.array('h');expected.frombytes(timeline)
    if abs(len(actual)-len(expected))>1024:
        raise RuntimeError('B09 AAC sample count differs from source timeline')
    def correlation(lag):
        dot=aa=bb=0
        for i in range(lead//2+10000,min(len(actual),len(expected)-max(0,lag)),100):
            j=i+lag
            if j<0:continue
            x,y=actual[j],expected[i];dot+=x*y;aa+=x*x;bb+=y*y
        return dot/math.sqrt(aa*bb)
    corr={lag:correlation(lag) for lag in (-32,0,32)}
    if corr[0]<.995 or corr[0]<=max(corr[-32],corr[32]):
        raise RuntimeError('B09 AAC does not align to source WAV')
    small=subprocess.check_output(['ffmpeg','-v','error','-xerror','-i',str(video),'-map','0:v:0',
                                   '-vf','scale=48:27:flags=area,format=gray','-r',str(FPS),'-f','rawvideo','-'])
    pixels=48*27
    if len(small)!=frames*pixels:
        raise RuntimeError('B09 video frame count invalid')
    lum=[];blank=[]
    for i in range(frames):
        frame=small[i*pixels:(i+1)*pixels];lum.append(sum(frame)/pixels)
        if max(frame)-min(frame)<12 or all(v<10 for v in frame) or all(v>245 for v in frame):blank.append(i)
    flash=[i for i in range(1,frames-1) if abs(lum[i]-lum[i-1])>35 and abs(lum[i]-lum[i+1])>35 and abs(lum[i-1]-lum[i+1])<10]
    if blank or flash:
        raise RuntimeError(f'B09 blank/flash frames: {blank[:5]} / {flash[:5]}')
    transition_anomalies=visual_transition_anomalies(small)
    if transition_anomalies:
        raise RuntimeError(f'B09 brief screen/scroll transitions: {transition_anomalies[:5]}')
    visual_report=json.loads((OUT/'visual-capture.json').read_text())
    cue_errors=[];pointer=[];gestures=[];history=None;cursor_violations=[]
    elapsed=0
    for scene in scenes:
        row=next(r for r in visual_report['scenes'] if r['scene_id']==scene['id'])
        source=OUT/'scenes'/f"{scene['id']}.mp4"
        if sha(source)!=row['sha256']:
            raise RuntimeError('B09 scene source changed')
        evidence=json.loads(source.with_suffix('.json').read_text())
        if evidence['expected_state']!='PASS' or evidence['browser_errors'] or evidence['production_mutation_requests']:
            raise RuntimeError('B09 browser scene invalid')
        cursor_violations.extend(evidence['choreography']['overlay']['violations'])
        cue_errors.extend(abs(x) for x in row['cue_errors_seconds'])
        pointer.extend({'scene_id':scene['id'],**p} for p in pointer_pixels_in_mp4(video,evidence,elapsed,scene['id'],OUT/'qa-clicks'/scene['id']))
        gestures.extend({'scene_id':scene['id'],**g} for g in gesture_pixels_in_mp4(video,evidence,elapsed,scene['id'],OUT/'qa-drags'/scene['id']))
        if scene['id']=='B09-034':
            history=history_pixels_in_mp4(video,evidence,elapsed,OUT/'qa-history')
        elapsed+=report['scene_frame_counts'][scene['id']]/FPS
    if cursor_violations or (cue_errors and max(cue_errors)>.3):
        raise RuntimeError('B09 cursor lifecycle or cue synchronization failed')
    result={'status':'PASS','block_id':'B09','video_sha256':sha(video),
            'final_wav_sha256':metadata['wav_sha256'],'final_pcm_preserved_in_timeline':True,
            'aac_zero_lag_correlation':corr[0],'subtitle_cues':checked['embedded_subtitle_cues'],
            'last_embedded_subtitle_end_seconds':checked['last_embedded_subtitle_end_seconds'],
            'subtitle_matches_canonical_text':True,'video_frames':frames,
            'blank_frames':0,'isolated_flash_frames':0,'visual_transition_anomalies':[],
            'cursor_violations':0,
            'max_visual_cue_error_seconds':max(cue_errors) if cue_errors else None,
            'rendered_pointer_clicks':pointer,'rendered_drag_results':gestures,
            'rendered_undo_redo':history,
            'new_tts_requests':0,'production_mutation_requests':0}
    write_json(OUT/'verification.json',result)
    return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('visual','assemble','verify'))
    args=parser.parse_args()
    print(json.dumps(asyncio.run(visual()) if args.mode=='visual' else assemble() if args.mode=='assemble' else verify(),ensure_ascii=False,indent=2))
