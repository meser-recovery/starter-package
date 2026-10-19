"""B13 actions on the real, isolated Archive and Editor interfaces."""
from __future__ import annotations

import asyncio
from urllib.parse import urljoin

from b09_block import raw_seed_region
from scenes import (import_archive, import_local, login, open_archive_detail_from_editor,
                    publish_announcement, render_speaker_final,
                    reopen_project_from_detail, save_speaker_project)

TITLE = 'Спикер'


async def state(page, label):
    result = await page.evaluate('''async () => {
      const el=id=>document.getElementById(id);
      const speaker=await import('./scripts/speaker-editor.mjs').catch(()=>null);
      const data=speaker?.getSpeakerSaveState?.();
      return {url:location.pathname,scroll:[scrollX,scrollY],
        detailTitle:el('detail-title')?.textContent.trim()||'',
        announcementVersions:[...document.querySelectorAll('#detail .workflow-announcement .result-row')].map(x=>x.textContent.trim()),
        speakerVersions:[...document.querySelectorAll('#detail .workflow-speaker .result-row')].map(x=>x.textContent.trim()),
        projectStates:[...document.querySelectorAll('#detail .project-state-row')].map(x=>x.textContent.trim()),
        tracks:document.querySelectorAll('#speaker-editor-tracks .speaker-track').length,
        waveformColors:[...document.querySelectorAll('#speaker-editor-tracks canvas')].map(c=>{
          const d=c.getContext('2d').getImageData(0,0,c.width,c.height).data,colors=new Set();
          for(let i=0;i<d.length;i+=100)colors.add(`${d[i]},${d[i+1]},${d[i+2]}`);
          return colors.size;
        }),
        cuts:data?.payload?.globalCuts?.length??null,
        silence:data?.payload?.trackSilenceRegions?.length??null,
        enhancement:data?.payload?.trackProcessing?.[0]?.enhancement??null,
        localSaveDialog:!!el('speaker-local-save-dialog')?.open,
        resultVisible:!!el('speaker-editor-result')&&!el('speaker-editor-result').hidden,
        saveStatus:el('speaker-editor-status')?.textContent.trim()||'',
        publicationStatus:el('source-session-publication-status')?.textContent.trim()||''};
    }''')
    if hasattr(page, 'tutorial'):
        page.tutorial.events.append({'type':'b13-state','seconds':page.tutorial.now(),
                                     'label':label,'state':result})
    return result


async def reveal(page, locator, label):
    """Show a necessary page scroll before aiming at a control."""
    box = await locator.bounding_box()
    if not box:
        raise RuntimeError('B13 missing UI target: '+label)
    screen = await page.evaluate('innerHeight')
    # The Archive's playback tray can cover the lowest ~180 px after Play.
    if box['y'] >= 72 and box['y'] + box['height'] < screen-205:
        return
    distance = box['y'] - max(95, min(250, screen*.23))
    await page.evaluate("window.__s11Capture.hide('intentional-scroll')")
    before = page.tutorial.now()
    for i in range(1,25):
        p=i/24; p=p*p*(3-2*p)
        await page.evaluate('(delta)=>window.scrollBy(0,delta)', distance/24 if i==24 else distance*(p-(i-1)/24*((i-1)/24)*(3-2*(i-1)/24)))
        await asyncio.sleep(.035)
    page.tutorial.events.append({'type':'visible-scroll','seconds':before,
                                 'end_seconds':page.tutorial.now(),'label':label})


async def follow_link(page, link, target_selector, label):
    href=await link.get_attribute('href')
    if not href or not href.startswith('Audio-Editor.html?session='):
        raise RuntimeError('B13 real Archive workflow link is missing: '+label)
    await reveal(page, link.raw, label)
    target=urljoin(page.url, href)
    if await link.get_attribute('target')=='_blank':
        async with page.raw.expect_popup() as opened:
            await link.click()
        popup=await opened.value
        await popup.locator(target_selector).wait_for(state='visible',timeout=60000)
        # The editor consumes its session query with history.replaceState after import.
        if not popup.url.startswith(target.split('?',1)[0]):
            raise RuntimeError(f'B13 workflow destination differs from real link: {popup.url}')
        await popup.close()
        await page.tutorial.pause_capture()
        await page.goto(target)
    else:
        await link.click()
        await page.tutorial.pause_capture()
        if not page.url.startswith(target.split('?',1)[0]):
            raise RuntimeError(f'B13 project history link navigated elsewhere: {page.url}')
    if target_selector=='#speaker-editor':
        await page.raw.wait_for_function("async () => document.querySelectorAll('#speaker-editor-tracks .speaker-track').length===4 && (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().ready",timeout=60000)
    else:
        await page.raw.wait_for_function("document.querySelectorAll('#processor-file-info .processor-track').length===4",timeout=60000)
    await page.raw.wait_for_timeout(300)
    await page.evaluate("window.__s11Capture.hide('workflow-context')")
    await page.tutorial.resume_capture()
    await state(page,label)


async def archive_from_editor(page, base, label):
    await page.locator('nav[aria-label="Аудиопортал"] a[href="Audio-Archive.html"]').click()
    await page.locator('#archive-index').wait_for(state='visible',timeout=60000)
    if not await page.locator('#records').is_visible():
        await page.locator('#record-picker-open').click()
    row=page.locator('#session-list article').filter(
        has=page.raw.get_by_role('heading',name=TITLE,exact=True)).first
    await row.get_by_role('button',name='Открыть запись').click()
    await page.locator('#detail-title').wait_for(state='visible',timeout=60000)
    await page.evaluate("window.__s11Capture.hide('archive-context')")
    result=await state(page,label)
    if result['detailTitle']!=TITLE: raise RuntimeError('B13 wrong Archive record')


async def publish(page, label):
    button=page.locator('#source-session-publish-announcement')
    await reveal(page,button.raw,label)
    await button.click()
    await page.locator('#source-session-publication-dialog').wait_for(state='visible')
    await page.locator('#source-session-publication-submit').click()
    await page.locator('#source-session-publication-dialog').wait_for(state='hidden',timeout=120000)
    await state(page,label)


async def save_final(page, label):
    button=page.locator('#speaker-editor-archive-save')
    await reveal(page,button.raw,label)
    await button.click()
    await page.locator('#speaker-editor-save-submit').click()
    await page.locator('#speaker-editor-save-dialog').wait_for(state='hidden',timeout=120000)
    await state(page,label)


async def prepare_speaker_history(page, base, *, first_final):
    """Recreate the same visible cut and settings history for scenes 050–051."""
    await import_archive(page,base,TITLE,'speaker')
    await raw_seed_region(page,'cut','Спикер.wav',5.2,6.5)
    await save_speaker_project(page)  # State 1: the recognizable common cut.
    await open_archive_detail_from_editor(page,base,TITLE)
    await reopen_project_from_detail(page,base)
    await page.locator('#speaker-editor-tracks .speaker-track').first.locator('[data-dsp-field="enhancement"]').check()
    await save_speaker_project(page)  # State 2: enhancement added.
    await open_archive_detail_from_editor(page,base,TITLE)
    await reopen_project_from_detail(page,base)
    await page.locator('#speaker-editor-tracks .speaker-track').first.locator('[data-dsp-field="leveling"]').check()
    await save_speaker_project(page)  # State 3: leveling added.
    await open_archive_detail_from_editor(page,base,TITLE)
    if first_final:
        await page.locator('#detail .project-disclosure > summary').click()
        early=page.locator('#detail .project-state-row').filter(has_text='Состояние 1').get_by_role('link',name='Продолжить с этого состояния')
        href=await early.get_attribute('href')
        await page.goto(base+'/'+href)
        await page.wait_for_function("async () => document.querySelectorAll('#speaker-editor-tracks .speaker-track').length===4 && (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().ready",timeout=60000)
        await save_speaker_project(page)  # State 4: branch from State 1.
        await render_speaker_final(page)
        await page.locator('#speaker-editor-archive-save').click()
        await page.locator('#speaker-editor-save-submit').click()
        await page.locator('#speaker-editor-save-dialog').wait_for(state='hidden',timeout=120000)
        await open_archive_detail_from_editor(page,base,TITLE)


async def prepare(page, scene, base):
    await page.set_viewport_size({'width':1728,'height':972})
    await login(page,base)
    sid=scene['id']
    if sid=='B13-046':
        await import_archive(page,base,TITLE,'announcement')
        await page.locator('#processor-run').click()
        await page.locator('#processor-result').wait_for(state='visible',timeout=120000)
    elif sid=='B13-047':
        await import_archive(page,base,TITLE,'announcement')
        await publish_announcement(page)
        await open_archive_detail_from_editor(page,base,TITLE)
        href=await page.locator('#detail .workflow-choice-announcement a').get_attribute('href')
        await page.goto(base+'/'+href)
        await page.locator('#announcement-processor-card').wait_for(state='visible',timeout=60000)
        await page.locator('#processor-file-info .processor-track').first.wait_for(timeout=60000)
        await page.locator('#processor-file-info .processor-track').filter(has_text='Участник.wav').locator('[data-track-action="remove"]').click()
        await page.locator('#processor-run').click()
        await page.wait_for_function("!document.querySelector('#source-session-publish-announcement').disabled",timeout=120000)
        await page.locator('#source-session-publish-announcement').click()
        await page.locator('#source-session-publication-dialog').wait_for(state='visible')
    elif sid=='B13-048':
        await import_archive(page,base,TITLE,'speaker')
        await raw_seed_region(page,'cut','Спикер.wav',5.2,6.5)
        await page.locator('#speaker-editor-tracks .speaker-track').first.locator('[data-dsp-field="enhancement"]').check()
        await save_speaker_project(page)
        await open_archive_detail_from_editor(page,base,TITLE)
    elif sid=='B13-049':
        await import_local(page,base,'speaker')
        await raw_seed_region(page,'cut','Спикер.wav',5.2,6.5)
    elif sid=='B13-050':
        await prepare_speaker_history(page,base,first_final=False)
        await page.locator('#detail .project-disclosure > summary').click()
    elif sid=='B13-051':
        await prepare_speaker_history(page,base,first_final=True)
        await page.locator('#detail .project-disclosure > summary').click()
        await page.locator('#detail .version-history > summary').click()
    else:raise RuntimeError('unexpected B13 scene '+sid)
    await page.add_style_tag(content='* { overflow-anchor: none !important; }')
    if sid=='B13-046':
        await page.locator('#source-session-publish-announcement').scroll_into_view_if_needed()
    else:
        await page.evaluate('window.scrollTo(0,0)')
    await page.evaluate('async()=>{await document.fonts.ready;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))}')
    await page.wait_for_timeout(800 if sid=='B13-046' else 350)
    await page.screenshot()


async def perform(page, scene, base, cue):
    sid=scene['id']
    if sid=='B13-046':
        await cue('сохранить в Аудиоархиве')
        await publish(page,'announcement version 1 saved')
        await cue('той же исходной записью Zoom')
        await archive_from_editor(page,base,'announcement version attached to original Zoom recording')
        await page.locator('#detail .version-history > summary').click()
        versions=await state(page,'original source and announcement version visible')
        if len(versions['announcementVersions'])!=1:raise RuntimeError('B13 first announcement version missing')
    elif sid=='B13-047':
        await page.locator('#source-session-publication-submit').click()
        await page.locator('#source-session-publication-dialog').wait_for(state='hidden',timeout=120000)
        await state(page,'second announcement version saved')
        await archive_from_editor(page,base,'two announcement versions opened in Archive')
        ready=page.locator('#detail .ready-results .ready-result').filter(has_text='Анонс-мейкер')
        await reveal(page,ready.get_by_role('button',name='Прослушать').raw,'ready announcement result')
        await cue('позже можно')
        await ready.get_by_role('button',name='Прослушать').click()
        await state(page,'announcement played from Archive')
        await cue('скачать')
        await ready.get_by_role('button',name='Скачать').click()
        summary=page.locator('#detail .version-history > summary')
        await reveal(page,summary.raw,'show saved versions')
        await summary.click()
        rows=page.locator('#detail .workflow-announcement .result-row')
        if await rows.count()!=2:raise RuntimeError('B13 two announcement results missing')
        await state(page,'both announcement versions retained')
        await cue('проект обработки')
        link=page.locator('#detail .project-section').get_by_role('link',name='Начать обработку')
        await follow_link(page,link,'#speaker-editor','Speaker project opened from Archive')
        await raw_seed_region(page,'cut','Спикер.wav',5.2,6.5)
        await page.locator('#speaker-editor-tracks .speaker-track').first.locator('[data-dsp-field="enhancement"]').check()
        await page.locator('#speaker-editor-save').click()
        await page.raw.wait_for_function("document.querySelector('#speaker-editor-status').dataset.dirty==='false'",timeout=120000)
        project=await state(page,'Speaker project saved with cut and setting')
        if project['cuts']<1 or project['tracks']!=4:raise RuntimeError('B13 project state absent')
    elif sid=='B13-048':
        await cue('снова открыть')
        link=page.locator('#detail .project-section').get_by_role('link',name='Продолжить обработку')
        await follow_link(page,link,'#speaker-editor','Speaker project restored')
        restored=await state(page,'restored tracks cut and processing')
        if restored['tracks']!=4 or restored['cuts']<1:raise RuntimeError('B13 Speaker restoration failed')
        await cue('сохраняя новое состояние')
        await raw_seed_region(page,'silence','Переводчик 1.wav',9,10)
        await page.locator('#speaker-editor-save').click()
        await page.raw.wait_for_function("document.querySelector('#speaker-editor-status').dataset.dirty==='false'",timeout=120000)
        await state(page,'second Speaker project state saved')
    elif sid=='B13-049':
        await cue('первом сохранении проекта')
        button=page.locator('#speaker-editor-save')
        await reveal(page,button.raw,'first local project save')
        await button.click()
        dialog=await state(page,'real local source and project confirmation')
        if not dialog['localSaveDialog']:raise RuntimeError('B13 first local save confirmation missing')
        await page.locator('#speaker-local-save-confirm').click()
        await page.raw.wait_for_function("document.querySelector('#speaker-editor-status').dataset.dirty==='false'",timeout=120000)
        await state(page,'local source and project saved together')
        await archive_from_editor(page,base,'local source and first project state opened')
        await cue('новое состояние')
        await page.locator('#detail .project-disclosure > summary').click()
        await state(page,'first local project state visible in Archive')
        link=page.locator('#detail .project-section').get_by_role('link',name='Продолжить обработку')
        await follow_link(page,link,'#speaker-editor','local project resumed for next state')
        setting=page.locator('#speaker-editor-tracks .speaker-track').first.locator('.speaker-dsp-field').filter(has_text='Улучшение')
        await reveal(page,setting.raw,'new project setting')
        await setting.click()
        await page.locator('#speaker-editor-save').click()
        await page.raw.wait_for_function("document.querySelector('#speaker-editor-status').dataset.dirty==='false'",timeout=120000)
        await state(page,'second local project state saved')
    elif sid=='B13-050':
        await cue('предыдущих вариантов')
        early=page.locator('#detail .project-state-row').filter(has_text='Состояние 1').get_by_role('link',name='Продолжить с этого состояния')
        await follow_link(page,early,'#speaker-editor','earlier project state restored')
        restored=await state(page,'earlier project state inspected')
        if restored['tracks']!=4:raise RuntimeError('B13 earlier project state did not load')
        await page.locator('#speaker-editor-save').click()
        await page.raw.wait_for_function("document.querySelector('#speaker-editor-status').dataset.dirty==='false'",timeout=120000)
        await cue('готовый MP3')
        await page.locator('#speaker-editor-render').click()
        await page.locator('#speaker-editor-result').wait_for(state='visible',timeout=120000)
        await state(page,'Speaker final MP3 created')
        await cue('сохранить в Аудиоархиве')
        await save_final(page,'Speaker final linked to current project state')
        await archive_from_editor(page,base,'saved final and history')
        await page.locator('#detail .project-disclosure > summary').click()
        await page.locator('#detail .version-history > summary').click()
        final=await state(page,'final version and linked state visible')
        if len(final['speakerVersions'])!=1:raise RuntimeError('B13 first Speaker final missing')
    elif sid=='B13-051':
        await cue('новых правок')
        link=page.locator('#detail .project-section').get_by_role('link',name='Продолжить обработку')
        await follow_link(page,link,'#speaker-editor','Speaker continued for new version')
        await raw_seed_region(page,'silence','Переводчик 1.wav',9,10)
        await page.locator('#speaker-editor-save').click()
        await page.raw.wait_for_function("document.querySelector('#speaker-editor-status').dataset.dirty==='false'",timeout=120000)
        await page.locator('#speaker-editor-render').click()
        await page.locator('#speaker-editor-result').wait_for(state='visible',timeout=120000)
        await save_final(page,'second Speaker final saved')
        await archive_from_editor(page,base,'both Speaker final versions opened')
        await page.locator('#detail .version-history > summary').click()
        finals=await state(page,'both Speaker final versions retained')
        if len(finals['speakerVersions'])!=2:raise RuntimeError('B13 second Speaker version missing')
        await cue('выбрать одну из финальных версий')
        old=page.locator('#detail .workflow-speaker .result-row').filter(has_text='Версия 1').get_by_role('link',name='Продолжить редактирование с этой финальной версии')
        await follow_link(page,old,'#speaker-editor','older final project state restored')
        old_state=await state(page,'older final state differs from latest edit')
        if old_state['cuts']!=1 or old_state['silence']!=0:
            raise RuntimeError('B13 older final did not restore its older project state')
    else:raise RuntimeError('unexpected B13 scene '+sid)
    await page.evaluate("window.__s11Capture.hide('scene-complete')")
