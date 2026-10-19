"""V2 full-candidate choreography. All targets belong to the actual Meser UI."""
import inspect
import scenes as original
from modules import identity, ROOT
from corrective_pilot import perform_pilot


async def prepare(page,scene,base):
    n=int(scene['id'][:3])
    if n==32:
        await original.login(page,base)
        tracks=[ROOT/'generated/visual-corrective/fixtures'/name for name in
                ('Тест уровня 1.wav','Тест уровня 2.wav','Тест уровня 3.wav','Участник.wav')]
        if not all(p.is_file() for p in tracks):raise RuntimeError('Existing CLIP fixtures missing')
        await original.import_local(page,base,'speaker',tracks)
    else:await original.prepare(page,scene,base)
    if await page.locator('#speaker-editor:visible').count():
        await page.wait_for_function("""() => !document.querySelector('#speaker-editor-source-audio-play').disabled &&
          !document.querySelector('#speaker-editor').textContent.includes('Подготовка формы сигнала')""",timeout=60000)
    if n in (11,50):
        await page.locator('#detail .project-disclosure > summary').click()
        await page.locator('#detail .version-history > summary').click()
        await page.locator('#detail .source-section' if n==11 else '#detail .project-disclosure').scroll_into_view_if_needed()
    if n in (56,57):await page.locator('#detail .record-management > summary').click()
    if n==59:
        await page.locator('#detail .danger-zone > summary').click()
        await page.locator('#detail .danger-zone').scroll_into_view_if_needed()
    if n in (28,29):await page.locator('#processor-result').scroll_into_view_if_needed()
    if n in (48,49):await page.locator('#speaker-editor-result').scroll_into_view_if_needed()
    await page.screenshot()


async def p005(p,s,b,c):
    await p.tutorial.highlight(p.locator('#detail'),'Аудиоархив позволяет')
    await c('Аудиоредактор позволяет')
    await p.locator('nav[aria-label="Аудиопортал"] a[href="Audio-Editor.html"]').click()
    await p.locator('#source-session-mode-archive').wait_for()
    await p.locator('#source-session-mode-archive').click()
    await p.locator('#source-session-list .source-session-item').filter(has_text='Учебная запись S11 005').get_by_role('button',name='Выбрать').click()
    await p.locator('#workflow-choice').wait_for(state='visible',timeout=60000)
    await p.tutorial.highlight(p.locator('#workflow-choice'),'вариантов работы')

async def p007(p,s,b,c):
    await c('Создать запись');await p.locator('#archive-create-open').click()
    await c('название');await p.tutorial.aim(p.raw.locator('#archive-create-name'))
    await c('Дата и время');await p.tutorial.aim(p.raw.locator('#archive-create-recorded'))

async def p006(p,s,b,c):
    await c('Аудиоархива');await original.perform(p,s,b,c)

async def p008(p,s,b,c):
    await c('выбираются');await original.perform(p,s,b,c)

async def p010(p,s,b,c):
    await c('сохранения');await original.perform(p,s,b,c)

async def p013(p,s,b,c):
    await c('Аудиоредактору');await original.perform(p,s,b,c)

async def p011(p,s,b,c):
    d=p.tutorial
    await d.highlight(p.locator('#detail .source-section'),'исходные дорожки')
    await d.highlight(p.locator('#detail .project-disclosure'),'проект обработки')
    await d.highlight(p.locator('#detail .workflow-announcement'),'версии для анонс-мейкера')
    await d.highlight(p.locator('#detail .workflow-speaker'),'финальные версии')

async def p012(p,s,b,c):
    await c('искать по названию');await p.locator('#filters input[name="search"]').fill('S11')
    # Search input is real and visible. The next cue demonstrates the actual
    # filters; an extra submit would crowd out that phrase's cursor arrival.
    await c('сортировать и фильтровать');await p.locator('.secondary-filters summary').click()
    await p.tutorial.highlight(p.locator('.secondary-filters'),'показывать только записи')

async def p015(p,s,b,c):await perform_pilot(p,s,b,c)
async def p016(p,s,b,c):await perform_pilot(p,s,b,c)
async def p029(p,s,b,c):await perform_pilot(p,s,b,c)
async def p059(p,s,b,c):await perform_pilot(p,s,b,c)

async def p024(p,s,b,c):
    await c('слушать');await original.perform(p,s,b,c)

async def p033(p,s,b,c):
    await c('прослушать');await original.perform(p,s,b,c)

async def p034(p,s,b,c):
    await c('назначить');await original.perform(p,s,b,c)

async def p035(p,s,b,c):
    await c('увеличить');await original.perform(p,s,b,c)

async def p043(p,s,b,c):
    await original.perform(p,s,b,c)

async def p044(p,s,b,c):
    # The real source workspace contains the track list. Its own outline clears
    # the Editor's overflow boundary, unlike the clipped inner OL border.
    await p.tutorial.highlight(p.locator('#speaker-editor .speaker-source'),'проект обработки',label='Редактируемый монтаж')
    await c('Сохранить проект');await original.save_speaker_project(p)
    await p.tutorial.highlight(p.locator('#speaker-editor-status'))
    await p.tutorial.highlight(p.locator('#speaker-editor .speaker-source'),'Такой проект')
    await c('Но сохранённый проект');await p.tutorial.aim(p.raw.locator('#speaker-editor-render'))

async def p046(p,s,b,c):
    await c('при сохранении проекта');await original.perform(p,s,b,c)

async def p025(p,s,b,c):
    await c('масштабирование');await p.tutorial.aim(p.raw.locator('#processor-source-zoom-in'))
    await c('изменение высоты дорожек');await p.tutorial.aim(p.raw.locator('#processor-source-scale-mode'))
    await c('Вписать');await p.locator('#processor-source-zoom-fit').click()
    await c('Follow');await p.locator('#processor-source-follow').click()
    wave=p.locator('#processor-file-info .processor-waveform').first;box=await wave.bounding_box()
    await c('Небольшой участок')
    y=box['y']+box['height']*.6
    await p.mouse.move(box['x']+box['width']*.2,y);await p.mouse.down()
    await p.mouse.move(box['x']+box['width']*.3,y);await p.mouse.up()
    await c('повторно');await p.locator('#processor-source-audio-loop').click()
    assert await p.locator('#processor-source-audio-loop').get_attribute('aria-pressed')=='true'

async def p026(p,s,b,c):
    await c('развернуть');await p.tutorial.aim(p.raw.locator('#processor-expand'))
    await c('изменить цвета');await p.tutorial.aim(p.raw.locator('#processor-file-info .processor-track input[type="color"]').first)
    await c('порядок дорожек');await p.tutorial.aim(p.raw.locator('#processor-file-info [data-track-action="move-down"]').first)
    await c('убрать ошибочно');await p.locator('#processor-file-info [data-track-action="remove"]').last.click()
    assert await p.locator('#processor-file-info .processor-track').count()==3

async def p027(p,s,b,c):
    await c('запускается обработка');await p.locator('#processor-run').click()
    await p.locator('#processor-result').wait_for(state='visible',timeout=120000)
    await p.tutorial.highlight(p.locator('#processor-result'),'единый результат')

async def p028(p,s,b,c):
    await p.tutorial.highlight(p.locator('#processor-result'),'исходная и новая длительность')

async def p031(p,s,b,c):
    row=p.locator('#speaker-editor-tracks .speaker-track').first
    await c('включить улучшение звука');await row.locator('[data-dsp-field="enhancement"]').check()
    await c('Отдельно доступно');await row.locator('[data-dsp-field="leveling"]').check()
    await c('Компрессия');await row.locator('[data-dsp-field="compression"]').press('Home')
    await row.locator('[data-dsp-field="compression"]').press('ArrowRight')
    await row.locator('[data-dsp-field="compression"]').press('ArrowRight')
    settings=await p.evaluate("async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload.trackProcessing[0]")
    assert [settings[k] for k in ('enhancement','leveling','compression')]==['gentle','on','medium']

async def p032(p,s,b,c):
    await c('контроля звука');await p.locator('#speaker-editor-source-audio-play').click()
    await p.tutorial.highlight(p.locator('#speaker-editor .audio-meter--master'),'индикаторы уровня')
    await p.locator('#speaker-editor .audio-meter--master [data-clipped="true"]').wait_for(timeout=8000)
    await p.tutorial.highlight(p.locator('#speaker-editor .audio-meter--master'),'Если появляется CLIP')

async def p036(p,s,b,c):
    await original.drag_speaker_selection(p)
    await c('Loop');await p.locator('#speaker-editor-source-audio-loop').click()
    assert await p.locator('#speaker-editor-source-audio-loop').get_attribute('aria-pressed')=='true'

async def p037(p,s,b,c):
    wave=p.locator('#speaker-editor-tracks .speaker-waveform-scroll').first;box=await wave.bounding_box()
    y=box['y']+box['height']*.6
    await c('выбирается')
    await p.mouse.move(box['x']+box['width']*.12,y);await p.mouse.down()
    await p.mouse.move(box['x']+box['width']*.85,y);await p.mouse.up()
    await c('новое начало');await p.locator('#speaker-editor-set-start').click()
    await c('правильный конец');await p.tutorial.aim(p.raw.locator('#speaker-editor-set-end'))

async def p042(p,s,b,c):
    details=p.locator('.speaker-selection > details:first-of-type')
    if await details.get_attribute('open')!='':await details.locator(':scope > summary').click()
    edge=p.locator('#speaker-editor-tracks [data-edge="start"]').first;box=await edge.bounding_box()
    before=await edge.get_attribute('aria-valuenow');x=box['x']+box['width']/2;y=box['y']+box['height']/2
    await c('передвигать');await p.mouse.move(x,y);await p.mouse.down()
    await p.mouse.move(x+42,y);await p.mouse.up()
    assert await edge.get_attribute('aria-valuenow')!=before
    await c('начало и конец');await original.select_speaker_range(p,'2.5','5.5')

async def p048(p,s,b,c):
    assert await p.locator('#speaker-editor-result-duration').inner_text()
    await c('прослушать');await p.tutorial.aim(p.raw.locator('#speaker-editor-result-audio'))
    await c('скачать');await p.tutorial.aim(p.raw.locator('#speaker-editor-download'))

async def p050(p,s,b,c):
    # Exact approved semantic association: final belongs to state 3, current is state 4.
    d=p.tutorial;linked=p.locator('#detail .project-state-row').filter(has_text='Связанные финальные версии:').first
    await d.highlight(linked,'с тем состоянием проекта',label='Состояние, из которого создан MP3')
    await d.highlight(p.locator('#detail .project-state-row').first,'Если после этого',label='Новое состояние сохранено отдельно')
    await d.highlight(linked,'уже существующая',label='Связь прежнего MP3 сохранена')
    await d.highlight(p.locator('#detail .workflow-speaker'),'новая финальная версия')

async def p052(p,s,b,c):
    await c('Истории проекта');await p.locator('#detail .project-disclosure > summary').click()
    await p.tutorial.highlight(p.locator('#detail .project-state-row').first,'когда было сохранено состояние')
    assert await p.locator('#detail .project-state-row').count()>=3

async def p054(p,s,b,c):
    await c('финальные версии');await p.locator('#detail .version-history > summary').click()
    await c('прослушивать')
    await p.locator('#detail .version-history .workflow-speaker').get_by_role('button',name='Прослушать').first.click()
    await p.locator('#player').wait_for(state='visible',timeout=60000)

async def p058(p,s,b,c):
    await c('результаты');await original.perform(p,s,b,c)

async def p056(p,s,b,c):
    await p.tutorial.highlight(p.locator('#detail .record-management'),'управлять уже сохранёнными материалами')
    await c('изменить название');await p.tutorial.aim(p.raw.locator('#metadata-title'))
    await c('дату и время');await p.tutorial.aim(p.raw.locator('#metadata-date'))

async def p057(p,s,b,c):
    m=p.locator('#detail .record-management')
    await c('убрать из рабочего списка');await m.get_by_role('button',name='Убрать из рабочего списка').click()
    await m.get_by_role('button',name='Вернуть в рабочий список').wait_for()
    await c('вернуть обратно');await p.tutorial.aim(m.get_by_role('button',name='Вернуть в рабочий список').raw)

PERFORM={int(name[1:]):fn for name,fn in list(globals().items()) if name.startswith('p') and name[1:].isdigit()}

async def perform(page,scene,base,cue):
    fn=PERFORM.get(int(scene['id'][:3]))
    if fn:result=await fn(page,scene,base,cue)
    else:result=await original.perform(page,scene,base,cue)
    alerts=page.locator('[role="alert"]:visible')
    if await alerts.count():raise RuntimeError('Unexpected UI alert: '+await alerts.first.inner_text())
    return result


def fingerprint(scene):
    # Editing one scene recipe invalidates that scene; shared preparation invalidates all.
    fn=PERFORM.get(int(scene['id'][:3]),original.perform)
    return identity([inspect.getsource(prepare),inspect.getsource(perform),inspect.getsource(fn),
                     inspect.getsource(perform_pilot) if fn in (p015,p016,p029,p059) else ''])
