"""B14 actions on the real Archive and Editor in the isolated preview."""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from b13_actions import reveal
from b09_block import raw_seed_region
from scenes import FIXTURES, TRACKS, login, publish_announcement, render_speaker_final, save_speaker_project, open_archive_detail_from_editor, reopen_project_from_detail
from validate import ROOT

TITLES = ('Северное собрание', 'Южное собрание', 'Западное собрание', 'Июльская встреча')
DATES = ('2026-09-14T14:00', '2026-09-18T15:00', '2026-08-12T16:00', '2026-07-19T12:00')
CUSTOM = ROOT/'generated/fixtures/b14-search'

async def state(page, label):
    result = await page.evaluate('''() => {
      const q=s=>document.querySelector(s), all=s=>[...document.querySelectorAll(s)];
      return {url:location.pathname, scrollY:scrollY, picker:!q('#records')?.hidden,
        search:q('#filters [name=search]')?.value||'', month:q('#filters [name=month]')?.value||'',
        project:!!q('#filters [name=speakerProject]')?.checked,
        announcement:!!q('#filters [name=announcementResult]')?.checked,
        final:!!q('#filters [name=speakerResult]')?.checked,
        matching:q('#matching')?.textContent.trim()||'',
        results:all('#session-list article.archive-card h3').map(x=>x.textContent.trim()),
        detail:q('#detail-title')?.textContent.trim()||'',
        ready:q('#detail .ready-results')?.textContent.trim()||'',
        historyOpen:!!q('#detail .version-history')?.open,
        projectOpen:!!q('#detail .project-disclosure')?.open,
        projectStates:all('#detail .project-state-row').map(x=>x.textContent.trim()),
        sourceTracks:all('#detail .source-section .source-track .track-name').map(x=>x.textContent.trim()),
        editorTracks:all('#speaker-editor-tracks .speaker-track').length,
        announcementTracks:all('#processor-file-info .processor-track').length};
    }''')
    if hasattr(page,'tutorial'):
        page.tutorial.events.append({'type':'b14-state','seconds':page.tutorial.now(),'label':label,'state':result})
    return result

async def create_record(page, title, recorded, special=False):
    await page.locator('#archive-create-open').click()
    await page.locator('#archive-create-name').fill(title)
    await page.locator('#archive-create-recorded').fill(recorded)
    tracks=TRACKS
    if special:
        CUSTOM.mkdir(parents=True,exist_ok=True)
        custom=CUSTOM/'Северный микрофон.wav'
        if not custom.exists():shutil.copyfile(TRACKS[0],custom)
        tracks=[custom,*TRACKS[1:]]
    await page.locator('#archive-create-files').set_input_files([str(p) for p in tracks])
    await page.locator('#archive-create-submit').click()
    await page.locator('#detail-title').wait_for(timeout=60000)
    if await page.locator('#detail-title').inner_text()!=title:raise RuntimeError('B14 wrong saved record')
    await page.locator('#detail-close').click()
    await page.locator('#archive-create-open').wait_for(state='visible',timeout=60000)

async def open_editor(page,base,title,mode):
    await page.goto(base+'/Audio-Editor.html')
    await page.locator('#source-session-mode-archive').click()
    item=page.locator('#source-session-list .source-session-item').filter(has_text=title).first
    await item.get_by_role('button',name='Выбрать').click()
    await page.locator('#workflow-choice').wait_for(state='visible',timeout=60000)
    await page.locator('#open-local-'+('speaker' if mode=='speaker' else 'announcement')).click()
    selector='#speaker-editor' if mode=='speaker' else '#announcement-processor-card'
    await page.locator(selector).wait_for(state='visible',timeout=60000)
    if mode=='speaker':
        await page.wait_for_function("async()=>document.querySelectorAll('#speaker-editor-tracks .speaker-track').length===4&&(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().ready",timeout=60000)
    else:await page.locator('#processor-file-info .processor-track').first.wait_for(timeout=60000)

async def prepare_records(page,base,*,all_material=False):
    await login(page,base)
    if all_material:
        title=TITLES[0]
        await create_record(page,title,DATES[0],True)
        await open_editor(page,base,title,'announcement')
        await publish_announcement(page)
        await open_editor(page,base,title,'speaker')
        await raw_seed_region(page,'cut','Северный микрофон.wav',5.2,6.5)
        await save_speaker_project(page)
        await open_archive_detail_from_editor(page,base,title)
        await reopen_project_from_detail(page,base)
        await page.locator('#speaker-editor-tracks .speaker-track').first.locator('[data-dsp-field="enhancement"]').check()
        await save_speaker_project(page)
        await render_speaker_final(page)
        await page.locator('#speaker-editor-archive-save').click()
        await page.locator('#speaker-editor-save-submit').click()
        await page.locator('#speaker-editor-save-dialog').wait_for(state='hidden',timeout=120000)
    else:
        for title,date in zip(TITLES,DATES):await create_record(page,title,date,title==TITLES[0])
        await open_editor(page,base,TITLES[0],'speaker');await save_speaker_project(page)
        await open_editor(page,base,TITLES[1],'announcement');await publish_announcement(page)
        await open_editor(page,base,TITLES[2],'speaker');await save_speaker_project(page)
        await render_speaker_final(page)
        await page.locator('#speaker-editor-archive-save').click()
        await page.locator('#speaker-editor-save-submit').click()
        await page.locator('#speaker-editor-save-dialog').wait_for(state='hidden',timeout=120000)
    await page.goto(base+'/Audio-Archive.html')
    await page.locator('#archive-index, #detail').first.wait_for(state='attached',timeout=60000)
    await page.wait_for_timeout(500)
    if await page.locator('#detail').is_visible():await page.locator('#detail-close').click()
    await page.locator('#archive-index').wait_for(state='visible',timeout=60000)
    # The compact Archive CSS hides the still-functional entry control and picker heading.
    # Reveal these real controls only in the isolated tutorial capture for the canonical walkthrough.
    await page.add_style_tag(content='.audio-studio .archive-entry-actions{display:flex!important}.audio-studio .record-picker .picker-heading{display:flex!important}')
    if await page.locator('#records').is_visible():await page.locator('#record-picker-close').click()

async def prepare(page,scene,base):
    await page.set_viewport_size({'width':1728,'height':972})
    await prepare_records(page,base,all_material=scene['id']!='B14-052')
    if scene['id'] in ('B14-053','B14-054'):
        await page.locator('#record-picker-open').click()
        row=page.locator('#session-list article').filter(has=page.get_by_role('heading',name=TITLES[0],exact=True)).first
        await row.get_by_role('button',name='Открыть запись').click()
        await page.locator('#detail-title').wait_for(state='visible')
    await page.add_style_tag(content='*{overflow-anchor:none!important}')
    await page.evaluate('window.scrollTo(0,0)')
    await page.evaluate('async()=>{await document.fonts.ready;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))}')
    await page.wait_for_timeout(350)

async def search(page,label):
    button=page.locator('#record-picker-search')
    await page.evaluate("window.__s11Capture.hide('search-result')") if hasattr(page,'tutorial') else None
    await button.raw.click() if hasattr(button,'raw') else await button.click()
    result=await state(page,label)
    await asyncio.sleep(.35)
    return result

async def perform(page,scene,base,cue):
    sid=scene['id']
    if sid=='B14-052':
        await cue('Показать записи');await page.locator('#record-picker-open').click()
        await state(page,'picker opened')
        await cue('по её названию');await page.locator('#filters [name=search]').fill('Северное')
        await search(page,'search by title')
        await page.locator('#filters [name=search]').raw.fill('Северный микрофон.wav');await asyncio.sleep(.25)
        await search(page,'search by source track')
        await page.locator('#filters [name=search]').fill('')
        await page.locator('#filters [name=month]').raw.fill('2026-09');await asyncio.sleep(.25)
        await search(page,'September only')
        await page.locator('#filters .secondary-filters > summary').click()
        await page.locator('#filters [name=month]').fill('')
        await page.locator('#filters [name=speakerProject]').check()
        await search(page,'project filter')
        await page.locator('#filters [name=speakerProject]').click()
        await page.locator('#filters [name=announcementResult]').check()
        await search(page,'announcement filter')
        await page.locator('#filters [name=announcementResult]').click()
        await page.locator('#filters [name=speakerResult]').check()
        await search(page,'final filter')
        await cue('После открытия нужной записи');
        row=page.locator('#session-list article').filter(has=page.raw.get_by_role('heading',name=TITLES[2],exact=True)).first
        await reveal(page,row.raw,'found record');await row.get_by_role('button',name='Открыть запись').click()
        await state(page,'found record opened')
        await page.evaluate("window.__s11Capture.hide('detail-context')")
        await asyncio.sleep(.5)
    elif sid=='B14-053':
        await cue('Готовые записи');await reveal(page,page.locator('#detail .ready-results').raw,'ready recordings')
        await state(page,'ready recordings visible')
        await cue('Все версии и управление');await reveal(page,page.locator('#detail .version-history > summary').raw,'version history')
        await page.locator('#detail .version-history > summary').click();await state(page,'all versions open')
        await cue('Проект обработки спикерской');await reveal(page,page.locator('#detail .project-disclosure > summary').raw,'project history')
        await page.locator('#detail .project-disclosure > summary').click();await state(page,'project history open')
        await page.evaluate("window.__s11Capture.hide('explanation-finished')")
    elif sid=='B14-054':
        detail_url=page.url
        await cue('отдельных дорожек Zoom');await page.tutorial.wait_pending()
        await reveal(page,page.locator('#detail .source-section > summary').raw,'original Zoom tracks')
        if await page.locator('#detail .source-section').get_attribute('open') is None:
            await page.locator('#detail .source-section > summary').click()
        await state(page,'original tracks visible')
        await cue('Анонс-мейкер');await page.tutorial.wait_pending()
        await reveal(page,page.locator('#detail .ready-results').raw,'short announcement result')
        await state(page,'announcement result visible')
        await cue('Спикерская');await page.tutorial.wait_pending()
        link=page.locator('#detail .project-section').get_by_role('link',name='Продолжить обработку')
        href=await link.get_attribute('href')
        if not href or not href.startswith('Audio-Editor.html?session='):
            raise RuntimeError('B14 missing real Speaker project link')
        await page.evaluate("window.__s11Capture.hide('speaker-context')")
        await page.tutorial.pause_capture()
        await page.goto(base+'/'+href)
        await page.wait_for_function("async()=>document.querySelectorAll('#speaker-editor-tracks .speaker-track').length===4&&(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().ready",timeout=60000)
        await page.wait_for_timeout(250)
        await page.evaluate("window.__s11Capture.hide('speaker-stable')")
        await page.tutorial.resume_capture()
        await state(page,'speaker edit and tracks visible')
        await cue('А Аудиоархив');await page.tutorial.wait_pending()
        await page.evaluate("window.__s11Capture.hide('archive-context')")
        await page.tutorial.pause_capture()
        await page.goto(detail_url)
        await page.locator('#detail-title').wait_for(state='visible',timeout=60000)
        await page.wait_for_timeout(250)
        await page.evaluate("window.__s11Capture.hide('archive-stable')")
        await page.tutorial.resume_capture()
        await state(page,'archive record and materials visible')
        await page.evaluate("window.__s11Capture.hide('closing')")
    else:raise RuntimeError('unexpected B14 scene '+sid)
