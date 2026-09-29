#!/usr/bin/env python3
"""Six-scene corrective pilot ONLY. Reads existing audio; has no TTS/assembly path."""
import argparse, asyncio, hashlib, json, subprocess
from pathlib import Path
from browser_capture import capture
from build import demo_server
from modules import scene_timing, cached
from scenes import prepare, perform, login, import_local, TRACKS
from validate import ROOT, validate

OUT=ROOT/'generated/visual-corrective-v2'
ALLOWED=(15,16,29,32,50,59)
LEAD=1.2
TAIL=1.2

async def prepare_pilot(page,scene,base):
    number=int(scene['id'][:3])
    if number not in ALLOWED:raise RuntimeError('Only the six approved corrective scenes may be captured')
    if number==32:
        await login(page,base)
        # Existing synthetic level fixtures are read only: no WAV writes/regeneration.
        tracks=[ROOT/'generated/visual-corrective/fixtures'/name for name in
                ('Тест уровня 1.wav','Тест уровня 2.wav','Тест уровня 3.wav','Участник.wav')]
        if not all(p.is_file() for p in tracks):raise RuntimeError('Existing synthetic CLIP fixtures unavailable')
        await import_local(page,base,'speaker',tracks)
    else:await prepare(page,scene,base)
    if number==59:
        await page.locator('#detail .danger-zone > summary').click()
        await page.locator('#detail .danger-zone').scroll_into_view_if_needed()
    if number==29:await page.locator('#processor-result').scroll_into_view_if_needed()

async def perform_pilot(page,scene,base,cue):
    number=int(scene['id'][:3]);d=page.tutorial
    if number==15:
        await cue('выбрать файлы')
        await page.locator('#processor-file').set_input_files([str(p) for p in TRACKS])
        await page.locator('#source-session-use-local').click()
        await page.locator('#workflow-choice').wait_for(state='visible',timeout=60000)
        await cue('С этого устройства')
        await d.aim(page.raw.locator('#source-session-mode-device'))
    elif number==16:
        if await page.locator('#current-recording-archive-link').is_visible():raise RuntimeError('Unexpected Archive link')
        await cue('выбор файлов')
        await page.locator('#source-session-mode-device').click()
        await d.highlight(page.locator('#import-files'),'файлы остаются')
    elif number==29:
        await cue('скачать как MP3')
        await page.locator('#processor-download').click()
        await cue('готовый материал можно также сохранить')
        await page.locator('#source-session-publish-announcement').click()
        await page.locator('#source-session-publication-dialog').wait_for(state='visible')
        await d.highlight(page.locator('#source-session-publication-dialog'))
        await cue('сохранить новую версию')
        await page.locator('#source-session-publication-submit').click()
        await page.locator('#source-session-publication-dialog').wait_for(state='hidden',timeout=120000)
    elif number==32:
        await cue('Для контроля звука')
        await page.locator('#speaker-editor-source-audio-play').click()
        await d.highlight(page.locator('#speaker-editor .audio-meter--master'),'индикаторы уровня')
        await page.locator('#speaker-editor .audio-meter--master [data-clipped="true"]').wait_for(timeout=8000)
        await d.highlight(page.locator('#speaker-editor .audio-meter--master'),'Если появляется CLIP')
    elif number==50:
        # Preserve the already-correct linked project-state semantic selectors.
        await perform(page,scene,base,cue=cue)
    elif number==59:
        danger=page.locator('#detail .danger-zone')
        await cue('удаление исходных дорожек')
        await danger.get_by_role('button',name='Удалить исходные дорожки').click()
        await page.locator('#delete-dialog').wait_for(state='visible')
        await d.highlight(page.locator('#delete-retained'),'проекты и результаты могут остаться')
        await cue('исходные аудиофайлы')
        await page.locator('#delete-cancel').click()
        await cue('запись можно удалить полностью')
        await danger.get_by_role('button',name='Удалить запись полностью').click()
        await page.locator('#delete-dialog').wait_for(state='visible')
        await d.highlight(page.locator('#delete-dialog'),'что именно будет удалено')
        if not await page.locator('#delete-removed').inner_text():raise RuntimeError('Missing real deletion preview')
    else:raise RuntimeError('Scene outside corrective pilot')


def preservation():
    before=json.loads((OUT/'evidence/preservation-before.json').read_text())
    changed=[]
    for path,item in before.items():
        p=ROOT.parent/path
        if not p.is_file() or p.stat().st_mtime_ns!=item['mtime_ns'] or hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:changed.append(path)
    result={'status':'FAIL' if changed else 'PASS','protected_files':len(before),'changed':changed,'tts_requests':0}
    (OUT/'evidence/preservation.json').write_text(json.dumps(result,indent=2))
    if changed:raise RuntimeError('Protected files changed: '+str(changed))
    return result

async def run(numbers):
    if not set(numbers)<=set(ALLOWED):raise RuntimeError('Pilot allowlist violation')
    report=validate();spec=json.loads((ROOT/'tutorial.yaml').read_text())
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'evidence').mkdir(exist_ok=True)
    preservation()
    # No generation fallback. Every module must already be a valid cache hit.
    hits={m['id']:bool(cached(spec,m)) for m in spec['narration_modules']}
    if not all(hits.values()):raise RuntimeError('Narration cache missing; pilot never generates audio')
    rows=[]
    for scene in spec['scenes']:
        if int(scene['id'][:3]) not in numbers:continue
        timing=scene_timing(spec,scene)
        timing.update(visual_lead_seconds=LEAD,visual_tail_seconds=TAIL,strict_choreography=True,
                      visual_pilot_source=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      evidence_directory=str(OUT/'evidence'))
        with demo_server(None) as base:
            evidence=await capture(scene,spec['narration'],base,timing=timing,destination=OUT/'scenes'/f"{scene['id']}.mp4",
                                   prepare_scene=prepare_pilot,perform_scene=perform_pilot)
        rows.append({'scene_id':scene['id'],'cache':evidence['cache'],'seconds':evidence['duration_seconds']})
        print(json.dumps(rows[-1]),flush=True)
    result={'scene_results':rows,'narration_cache':hits,'preservation':preservation(),'content_drift':report,'tts_requests':0,'full_assembly':False}
    (OUT/'evidence/run.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenes',default=','.join(map(str,ALLOWED)))
    args=parser.parse_args()
    asyncio.run(run([int(x) for x in args.scenes.split(',')]))
