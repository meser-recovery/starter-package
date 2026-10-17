"""Semantic actions against the real, process-local Meser frontend.

Every helper operates only on the in-memory tutorial preview. Unsupported scenes
fail explicitly; a nearby control is never used as a substitute.
"""
from __future__ import annotations

from pathlib import Path

from validate import ROOT

FIXTURES = ROOT / "generated/fixtures/synthetic-zoom-v1"
TRACKS = [FIXTURES / name for name in ("Спикер.wav", "Переводчик 1.wav", "Переводчик 2.wav", "Участник.wav")]


async def login(page, base: str):
    await page.goto(base + "/Audio-Archive.html")
    if "/login" in page.url:
        await page.locator("#admin-password").fill("local-test-password")
        await page.locator("#admin-access-form button[type=submit]").click()
        await page.wait_for_url("**/Audio-Archive.html")
    await page.get_by_role("heading", name="Аудиоархив").wait_for()


async def create_archive(page, title: str):
    await page.locator("#archive-create-open").click()
    await page.locator("#archive-create-name").fill(title)
    await page.locator("#archive-create-files").set_input_files([str(path) for path in TRACKS])
    await page.locator("#archive-create-submit").click()
    await page.locator("#detail-title").wait_for(timeout=60_000)
    if await page.locator("#detail-title").inner_text() != title:
        raise RuntimeError("archive save did not open the requested synthetic record")


async def import_local(page, base: str, mode: str | None = None, tracks=None):
    await page.goto(base + "/Audio-Editor.html")
    await page.locator("#source-session-mode-device").click()
    await page.locator("#processor-file").set_input_files([str(path) for path in (tracks or TRACKS)])
    await page.locator("#import-files").get_by_text((tracks or TRACKS)[-1].name, exact=False).first.wait_for()
    await page.locator("#source-session-use-local").click()
    await page.locator("#workflow-choice").wait_for(state="visible", timeout=60_000)
    if mode == "speaker":
        await page.locator("#open-local-speaker").click()
        await page.locator("#speaker-editor").wait_for(state="visible", timeout=60_000)
        await page.wait_for_function("document.querySelectorAll('#speaker-editor-tracks .speaker-track').length===4", timeout=60_000)
        await page.wait_for_function("async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().ready", timeout=60_000)
    if mode == "announcement":
        await page.locator("#open-local-announcement").click()
        await page.locator("#announcement-processor-card").wait_for(state="visible", timeout=60_000)
        await page.locator("#processor-file-info .processor-track").first.wait_for(timeout=60_000)


async def import_archive(page, base: str, title: str, mode: str | None = None):
    await create_archive(page, title)
    await page.goto(base + "/Audio-Editor.html")
    await page.locator("#source-session-mode-archive").click()
    item = page.locator("#source-session-list .source-session-item").filter(has_text=title).first
    await item.get_by_role("button", name="Выбрать").click()
    await page.locator("#workflow-choice").wait_for(state="visible", timeout=60_000)
    if mode == "speaker":
        await page.locator("#open-local-speaker").click()
        await page.locator("#speaker-editor").wait_for(state="visible", timeout=60_000)
        await page.wait_for_function("async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().ready", timeout=60_000)
    if mode == "announcement":
        await page.locator("#open-local-announcement").click()
        await page.locator("#announcement-processor-card").wait_for(state="visible", timeout=60_000)


async def save_speaker_project(page):
    await page.locator("#speaker-editor-save").click()
    await page.wait_for_function("document.querySelector('#speaker-editor-status').dataset.dirty === 'false'", timeout=120_000)
    await page.wait_for_function("async () => !(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().saving", timeout=60_000)


async def render_speaker_final(page):
    await page.wait_for_function("!document.getElementById('speaker-editor-render').disabled", timeout=60_000)
    await page.locator("#speaker-editor-render").click()
    await page.locator("#speaker-editor-result").wait_for(state="visible", timeout=120_000)


async def publish_announcement(page):
    await page.locator("#processor-run").click()
    await page.locator("#processor-result").wait_for(state="visible", timeout=120_000)
    await page.locator("#source-session-publish-announcement").click()
    await page.locator("#source-session-publication-dialog").wait_for(state="visible")
    await page.locator("#source-session-publication-submit").click()
    await page.locator("#source-session-publication-dialog").wait_for(state="hidden", timeout=120_000)


async def open_archive_detail_from_editor(page, base: str, title: str):
    link = await page.locator("#current-recording-archive-link").get_attribute("href")
    if not link or not link.startswith("Audio-Archive.html?"):
        raise RuntimeError("current recording has no verified Archive link")
    await page.goto(base + "/" + link)
    await page.locator("#detail-title").wait_for(timeout=60_000)
    if await page.locator("#detail-title").inner_text() != title:
        raise RuntimeError("Archive detail identity mismatch")


async def reopen_project_from_detail(page, base: str):
    link = page.locator("#detail .project-section").get_by_role("link", name="Продолжить обработку")
    href = await link.get_attribute("href")
    if not href or not href.startswith("Audio-Editor.html?session=") or "workflow=speaker" not in href:
        raise RuntimeError("saved project has no verified editor link")
    await page.goto(base + "/" + href)
    await page.locator("#speaker-editor").wait_for(state="visible", timeout=60_000)
    await page.wait_for_function("async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().ready", timeout=60_000)


async def seed_history(page, base: str, title: str, *, finals: bool):
    await import_archive(page, base, title, "speaker")
    await save_speaker_project(page)
    await open_archive_detail_from_editor(page, base, title)
    await reopen_project_from_detail(page, base)
    row = page.locator("#speaker-editor-tracks .speaker-track").first
    await row.locator('[data-dsp-field="enhancement"]').check()
    await save_speaker_project(page)
    await open_archive_detail_from_editor(page, base, title)
    await reopen_project_from_detail(page, base)
    row = page.locator("#speaker-editor-tracks .speaker-track").first
    await row.locator('[data-dsp-field="leveling"]').check()
    await save_speaker_project(page)
    if finals:
        await render_speaker_final(page)
        await page.locator("#speaker-editor-archive-save").click()
        await page.locator("#speaker-editor-save-submit").click()
        await page.locator("#speaker-editor-save-dialog").wait_for(state="hidden", timeout=120_000)
    await open_archive_detail_from_editor(page, base, title)


async def select_speaker_range(page, start: str = "3", end: str = "4"):
    details=page.locator(".speaker-selection > details:first-of-type")
    if not await details.get_attribute('open') == '':
        await details.locator(':scope > summary').click()
    await page.locator("#speaker-editor-selection-start").fill(start)
    await page.locator("#speaker-editor-selection-end").fill(end)


async def add_speaker_edit(page, kind: str):
    button = page.locator("#speaker-editor-add-" + kind)
    await button.wait_for(state="visible")
    if not await button.is_enabled():
        # The tool can be armed before a time range is selected.
        await page.wait_for_function("async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().ready")
    await button.click()
    await drag_speaker_selection(page)
    key = "globalCuts" if kind == "cut" else "trackSilenceRegions"
    await page.wait_for_function("""async key =>
      (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload[key].length===1""", arg=key)


async def drag_speaker_selection(page):
    wave = page.locator("#speaker-editor-tracks .speaker-waveform-scroll").first
    await wave.scroll_into_view_if_needed()
    box = await wave.bounding_box()
    if not box:
        raise RuntimeError("speaker waveform unavailable for region gesture")
    y = box["y"] + box["height"] * .6
    await page.mouse.move(box["x"] + box["width"] * .22, y)
    await page.mouse.down()
    await page.mouse.move(box["x"] + box["width"] * .32, y, steps=8)
    await page.mouse.up()


async def restore_speaker_edit(page, kind: str):
    key = "globalCuts" if kind == "cut" else "trackSilenceRegions"
    region_id = await page.evaluate("""async key => {
      const payload=(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload;
      return payload[key][0]?.regionId || null;}""", key)
    if not region_id:
        raise RuntimeError(f"no {kind} region to restore")
    region = page.locator(f'#speaker-editor-tracks [data-region-id="{region_id}"]').first
    await region.focus()
    await page.keyboard.press("Enter")
    button = page.locator("#speaker-editor-add-" + kind)
    if await button.get_attribute("data-mode") != "restore":
        raise RuntimeError(f"{kind} restore mode missing")
    await button.click()
    await page.wait_for_function("""async key =>
      (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload[key].length===0""", arg=key)


async def prepare(page, scene: dict, base: str):
    number = int(scene["id"][:3])
    await login(page, base)
    title = f"Учебная запись S11 {number:03d}"
    if number == 5:
        await create_archive(page,title)
    elif number == 11:
        await seed_history(page,base,title,finals=True)
        href=await page.locator('#detail .workflow-choice-announcement a').get_attribute('href')
        await page.goto(base+'/'+href)
        await page.locator('#announcement-processor-card').wait_for(state='visible',timeout=60000)
        await publish_announcement(page)
        await open_archive_detail_from_editor(page,base,title)
    elif number == 44:
        await import_archive(page,base,title,'speaker')
        await add_speaker_edit(page,'cut')
        await page.locator('#speaker-editor-tracks [data-dsp-field="enhancement"]').first.check()
    elif number == 50:
        await seed_history(page,base,title,finals=True)
        await reopen_project_from_detail(page,base)
        await page.locator('#speaker-editor-tracks .speaker-track').last.get_by_role('button',name='Исключить из микса').click()
        await save_speaker_project(page)
        await open_archive_detail_from_editor(page,base,title)
    elif number == 6:
        await page.goto(base + "/Audio-Editor.html")
    elif 7 <= number <= 10:
        if number != 7:
            await page.locator("#archive-create-open").click()
        if number >= 8:
            await page.locator("#archive-create-name").fill(title)
        if number >= 9:
            await page.locator("#archive-create-files").set_input_files(str(TRACKS[0]))
        if number == 10:
            await page.locator("#archive-create-files").set_input_files([str(path) for path in TRACKS])
    elif number == 12:
        await create_archive(page, title)
        await page.locator("#detail-close").click()
        if not await page.locator("#records").is_visible():
            await page.locator("#record-picker-open").click()
    elif number == 13:
        pass
    elif number == 14:
        await create_archive(page, title)
        await page.goto(base + "/Audio-Editor.html")
    elif number in (15, 16):
        await page.goto(base + "/Audio-Editor.html")
        await page.locator("#source-session-mode-device").click()
        if number == 16:
            await page.locator("#processor-file").set_input_files([str(path) for path in TRACKS])
            await page.locator("#source-session-use-local").click()
            await page.locator("#workflow-choice").wait_for(state="visible", timeout=60_000)
    elif number in (17, 18):
        await import_local(page, base)
        if number==17:await page.locator('#source-session-mode-device').click()
    elif 23 <= number <= 29:
        if number == 29:
            await import_archive(page, base, title, "announcement")
        else:
            await import_local(page, base, None if number == 23 else "announcement")
        if number in (27, 28, 29):
            # Demonstrate the Russian-only workflow explained in scenes 019–022.
            rows = page.locator("#processor-file-info .processor-track")
            for source in ("Спикер.wav", "Участник.wav"):
                await rows.filter(has_text=source).locator('[data-track-action="remove"]').click()
            if await rows.count() != 2:
                raise RuntimeError("announcement must process exactly the two translator tracks")
        if number in (28, 29):
            await page.locator("#processor-run").click()
            await page.locator("#processor-result").wait_for(state="visible", timeout=120_000)
    elif 30 <= number <= 43 or 45 <= number <= 49:
        if number in (45, 49):
            await import_archive(page, base, title, "speaker")
        else:
            if number == 32:
                # Synthetic near-full-scale, in-phase sources make the REAL mix meter clip.
                import math,struct,wave
                folder=ROOT/'generated/visual-corrective/fixtures';folder.mkdir(parents=True,exist_ok=True)
                tracks=[]
                for name in ('Тест уровня 1.wav','Тест уровня 2.wav','Тест уровня 3.wav','Участник.wav'):
                    path=folder/name
                    with wave.open(str(path),'wb') as f:
                        f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000)
                        f.writeframes(b''.join(struct.pack('<h',round(31000*math.sin(i*2*math.pi*220/24000))) for i in range(24000*20)))
                    tracks.append(path)
                await import_local(page,base,'speaker',tracks)
            else:
                await import_local(page, base, None if number == 30 else "speaker")
        if number in (39, 42, 43):
            await add_speaker_edit(page, "cut")
        if number == 41:
            await add_speaker_edit(page, "silence")
        if number == 49:
            await save_speaker_project(page)
        if number in (48, 49):
            await render_speaker_final(page)
    elif 51 <= number <= 55:
        await seed_history(page, base, title, finals=number in (54, 55))
        if number in (53,55):await page.locator("#detail .project-disclosure > summary").click()
    elif number == 58:
        await import_archive(page, base, title, "announcement")
        await publish_announcement(page)
        await open_archive_detail_from_editor(page, base, title)
    elif 56 <= number <= 59:
        await create_archive(page, title)
    else:
        raise RuntimeError(f"browser scene setup not implemented: {scene['id']}")


async def perform(page, scene: dict, base: str, cue=None):
    async def at(phrase):
        if cue:
            await cue(phrase)
    async def focus(selector,phrase=None,kind='section',label=''):
        if hasattr(page,'tutorial'):
            await page.tutorial.focus(page.locator(selector).first,phrase,kind,label)
    async def move_edge(edge):
        await edge.scroll_into_view_if_needed()
        box=await edge.bounding_box()
        if not box: raise RuntimeError('Real region boundary unavailable')
        x=box['x']+box['width']/2;y=box['y']+box['height']/2
        await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x+42,y,steps=16);await page.mouse.up()
    number = int(scene["id"][:3])
    title = f"Учебная запись S11 {number:03d}"
    if number == 5:
        await focus('#detail','Аудиоархив позволяет')
        await at('Аудиоредактор позволяет')
        await page.locator('nav[aria-label="Аудиопортал"] a[href="Audio-Editor.html"]').click()
        await page.locator('#source-session-mode-archive').wait_for()
        await page.locator('#source-session-mode-archive').click()
        await page.locator('#source-session-list .source-session-item').filter(has_text=title).get_by_role('button',name='Выбрать').click()
        await page.locator('#workflow-choice').wait_for(state='visible',timeout=60000)
        await focus('#workflow-choice','выбрать один из двух')
    elif number == 11:
        await focus('#detail .source-section','исходные дорожки')
        await at('проект обработки')
        await page.locator('#detail .project-disclosure > summary').click()
        await focus('#detail .project-disclosure')
        await at('версии для анонс-мейкера')
        await page.locator('#detail .version-history > summary').click()
        await focus('#detail .workflow-announcement')
        await focus('#detail .workflow-speaker','финальные версии')
    elif number == 44:
        await focus('#speaker-editor-tracks','проект обработки',label='Редактируемый монтаж')
        await at('Сохранить проект')
        await save_speaker_project(page)
        await focus('#speaker-editor-status')
        await focus('#speaker-editor-tracks','Такой проект')
        await focus('#speaker-editor-render','Но сохранённый проект',kind='element',label='Проект ≠ MP3')
    elif number == 50:
        await page.locator('#detail .project-disclosure > summary').click()
        linked=page.locator('#detail .project-state-row').filter(has_text='Связанные финальные версии:').first
        if hasattr(page,'tutorial'): await page.tutorial.focus(linked,'с тем состоянием проекта',label='Состояние, из которого создан MP3')
        await focus('#detail .project-state-row','Если после этого',label='Новое состояние сохранено отдельно')
        if hasattr(page,'tutorial'): await page.tutorial.focus(linked,'уже существующая',label='Связь прежнего MP3 сохранена')
        await at('новая финальная версия')
        await page.locator('#detail .version-history > summary').click()
        await focus('#detail .workflow-speaker')
    elif number == 6:
        await page.locator('nav[aria-label="Аудиопортал"] a[href="Audio-Archive.html"]').click()
        await page.get_by_role("heading", name="Аудиоархив").wait_for()
    elif number == 7:
        await at('Создать запись')
        await page.locator("#archive-create-open").click()
        await at("Для записи указывается название")
        await page.locator("#archive-create-name").fill(title)
        await page.locator("#archive-create-recorded").fill("2026-09-28T12:00")
        if not await page.locator("#archive-create-name").input_value() == title:
            raise RuntimeError("archive title not set")
    elif number == 8:
        await page.locator("#archive-create-files").set_input_files([str(path) for path in TRACKS[:3]])
        if await page.locator("#archive-create-list li").count() != 3:
            raise RuntimeError("three selected synthetic tracks not visible")
    elif number == 9:
        await at('Добавить дорожки')
        await page.locator("#archive-create-add").click()
        await page.locator("#archive-create-files").set_input_files(str(TRACKS[1]))
        await at('Выбрать заново')
        await page.locator("#archive-create-replace").click()
        await page.locator("#archive-create-files").set_input_files([str(path) for path in TRACKS[:3]])
        if await page.locator("#archive-create-list li").count() != 3:
            raise RuntimeError("add/replace final selection mismatch")
    elif number == 10:
        await page.locator("#archive-create-submit").click()
        await page.locator("#detail-title").wait_for(timeout=60_000)
    elif number == 12:
        await at('искать по названию')
        await page.locator('#filters input[name="search"]').fill(title)
        await page.locator("#record-picker-search").click()
        await page.locator("#session-list").get_by_text(title).first.wait_for()
        await at("сортировать и фильтровать")
        await page.locator(".secondary-filters summary").click()
        await page.locator('#filters select[name="sort"]').select_option("title")
        await page.locator("#record-picker-recent").click()
    elif number == 13:
        await page.locator('nav[aria-label="Аудиопортал"] a[href="Audio-Editor.html"]').click()
        await page.locator("#source-session-mode-archive").wait_for()
    elif number == 14:
        await at('Из аудиоархива')
        await page.locator("#source-session-mode-archive").click()
        item = page.locator("#source-session-list .source-session-item").filter(has_text=title).first
        await item.get_by_role("button", name="Выбрать").click()
        await page.locator("#workflow-choice").wait_for(state="visible", timeout=60_000)
    elif number == 15:
        await at('выбрать файлы')
        await page.locator("#processor-file").set_input_files([str(path) for path in TRACKS])
        await page.locator("#source-session-use-local").click()
        await page.locator("#workflow-choice").wait_for(state="visible", timeout=60_000)
    elif number == 16:
        if await page.locator("#current-recording-archive-link").is_visible():
            raise RuntimeError("local import unexpectedly linked to Archive")
        await page.locator("#source-session-mode-device").click()
    elif number == 17:
        await page.locator("#processor-save-incoming").click()
        await page.locator("#source-session-ingest-dialog").wait_for(state="visible")
        record_title=await page.locator("#source-session-ingest-name").input_value()
        await at('сохранить запись в Архив')
        await page.locator("#source-session-ingest-submit").click()
        await page.locator("#current-recording-heading").get_by_text(record_title).wait_for(timeout=60_000)
    elif number == 18:
        await focus("#open-local-announcement","Анонс-мейкер",kind="element")
        await focus("#open-local-speaker","Спикерская",kind="element")
        if not await page.locator("#open-local-announcement").is_visible() or not await page.locator("#open-local-speaker").is_visible():
            raise RuntimeError("both editor modes not visible")
    elif number == 23:
        await at('Анонс-мейкер')
        await page.locator("#open-local-announcement").click()
        await page.locator("#announcement-processor-card").wait_for(state="visible", timeout=60_000)
    elif number == 30:
        await at('Спикерская')
        await page.locator("#open-local-speaker").click()
        await page.locator("#speaker-editor").wait_for(state="visible", timeout=60_000)
    elif number == 24:
        rows = page.locator("#processor-file-info .processor-track")
        await rows.first.locator('[data-track-action="solo"]').click()
        await at('Mute')
        await rows.nth(1).locator('[data-track-action="mute"]').click()
        if await rows.first.locator('[data-track-action="solo"]').get_attribute("aria-pressed") != "true":
            raise RuntimeError("announcement Solo did not engage")
    elif number == 25:
        await page.locator("#processor-source-zoom-in").click()
        await at("изменение высоты дорожек")
        await page.locator("#processor-source-scale-mode").click()
        await page.locator("#processor-source-zoom-in").click()
        await page.locator("#processor-source-scale-mode").click()
        await at('Вписать')
        await page.locator("#processor-source-zoom-fit").click()
        await at('Follow')
        await page.locator("#processor-source-follow").click()
        await at('Небольшой участок')
        wave = page.locator("#processor-file-info .processor-waveform").first
        box = await wave.bounding_box()
        if not box:
            raise RuntimeError("announcement waveform unavailable for Loop range")
        y = box["y"] + box["height"] * .6
        await page.mouse.move(box["x"] + box["width"] * .2, y)
        await page.mouse.down()
        await page.mouse.move(box["x"] + box["width"] * .3, y, steps=8)
        await page.mouse.up()
        await page.locator("#processor-source-audio-loop").click()
        if await page.locator("#processor-source-follow").get_attribute("aria-pressed") != "true":
            raise RuntimeError("announcement Follow did not engage")
        await page.wait_for_function("document.querySelector('#processor-source-audio-loop').getAttribute('aria-pressed') === 'true'", timeout=15_000)
        if await page.locator("#processor-source-audio-loop").get_attribute("aria-pressed") != "true":
            raise RuntimeError("announcement Loop did not engage")
    elif number == 26:
        await page.locator("#processor-expand").click()
        await at('изменить цвета')
        await page.locator('#processor-file-info .processor-track input[type="color"]').first.fill("#27b3a0")
        await page.locator('#processor-file-info [data-track-action="move-down"]').first.click()
        await at('убрать ошибочно')
        await page.locator('#processor-file-info [data-track-action="remove"]').last.click()
        if await page.locator("#processor-file-info .processor-track").count() != 3:
            raise RuntimeError("erroneous announcement track not removed")
    elif number == 27:
        await page.locator("#processor-run").click()
        await page.locator("#processor-result").wait_for(state="visible", timeout=120_000)
        await page.locator("#processor-result").scroll_into_view_if_needed()
    elif number == 28:
        await page.wait_for_function("document.querySelector('#processor-processed-duration').textContent.trim().length>0", timeout=30_000)
        await page.locator("#processor-result").scroll_into_view_if_needed()
    elif number == 29:
        if not await page.locator("#processor-download").is_visible():
            raise RuntimeError("announcement MP3 download missing")
        await page.locator("#processor-download").click()
        await at("готовый материал можно также сохранить")
        await page.locator("#source-session-publish-announcement").click()
        await page.locator("#source-session-publication-dialog").wait_for(state="visible")
        await page.locator("#source-session-publication-submit").click()
        await page.locator("#source-session-publication-dialog").wait_for(state="hidden", timeout=120_000)
    elif number == 31:
        await at('включить улучшение звука')
        row = page.locator("#speaker-editor-tracks .speaker-track").first
        await row.locator('[data-dsp-field="enhancement"]').check()
        await at('Отдельно доступно')
        await row.locator('[data-dsp-field="leveling"]').check()
        await at('Компрессия')
        await row.locator('[data-dsp-field="compression"]').press('Home')
        await row.locator('[data-dsp-field="compression"]').press('ArrowRight')
        await row.locator('[data-dsp-field="compression"]').press('ArrowRight')
        settings = await page.evaluate("""async () =>
          (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload.trackProcessing[0]""")
        if [settings[key] for key in ("enhancement", "leveling", "compression")] != ["gentle", "on", "medium"]:
            raise RuntimeError("independent track DSP selection failed")
    elif number == 32:
        await at('индикаторы уровня')
        await page.locator("#speaker-editor-source-audio-play").click()
        await page.locator("#speaker-editor-tracks .audio-meter").first.wait_for()
        await focus('#speaker-editor .audio-meter--master','Если появляется CLIP',label='Слишком высокий уровень')
        await page.locator('#speaker-editor .audio-meter--master [data-clipped="true"]').wait_for(timeout=8000)
    elif number == 33:
        row = page.locator("#speaker-editor-tracks .speaker-track").last
        await row.locator('[data-action="solo"]').click()
        await at('Mute')
        await row.locator('[data-action="mute"]').click()
        await at('Если дорожка вообще')
        await row.get_by_role("button", name="Исключить из микса").click()
        if not await row.evaluate("element => element.classList.contains('is-excluded')"):
            raise RuntimeError("track exclusion did not affect project")
        await at('Исходная дорожка')
        await row.get_by_role("button", name="Вернуть в микс").click()
    elif number == 34:
        row = page.locator("#speaker-editor-tracks .speaker-track").first
        await row.locator('input[type="color"]').fill("#27b3a0")
        await row.get_by_role("button", name="Вниз").click()
        await at('Рабочую область')
        await page.locator("#speaker-editor-expand").click()
    elif number == 35:
        await page.locator("#speaker-editor-zoom-in").click()
        await at('Кнопка')
        await page.locator("#speaker-editor-zoom-fit").click()
        await at('Тем же регулятором')
        await page.locator("#speaker-editor-scale-mode").click()
        await at("При включённой функции Follow")
        await page.locator("#speaker-editor-follow").click()
    elif number == 36:
        await drag_speaker_selection(page)
        await page.locator("#speaker-editor-source-audio-loop").click()
        edge = page.locator("#speaker-editor-tracks .speaker-boundary--start").first
        if await edge.count():
            await move_edge(edge)
        if await page.locator("#speaker-editor-source-audio-loop").get_attribute("aria-pressed") != "true":
            raise RuntimeError("Speaker Loop did not engage")
    elif number == 37:
        await drag_speaker_selection(page)
        await select_speaker_range(page, "2", "3")
        await page.locator("#speaker-editor-set-start").click()
        await at('Таким же образом')
        await select_speaker_range(page, "15", "16")
        await page.locator("#speaker-editor-set-end").click()
    elif number == 38:
        await at('Вырезать')
        await add_speaker_edit(page, "cut")
    elif number == 39:
        await restore_speaker_edit(page, "cut")
    elif number == 40:
        await at('Тишина')
        await add_speaker_edit(page, "silence")
    elif number == 41:
        await restore_speaker_edit(page, "silence")
    elif number == 42:
        edge = page.locator('#speaker-editor-tracks [data-edge="start"]').first
        before = await edge.get_attribute("aria-valuenow")
        await move_edge(edge)
        if await edge.get_attribute("aria-valuenow") == before:
            raise RuntimeError("region boundary did not move")
        await at("точными числовыми значениями")
        await select_speaker_range(page,"2.5","5.5")
    elif number == 43:
        await page.locator("#speaker-editor-undo").click()
        await at('Повторить')
        await page.locator("#speaker-editor-redo").click()
        await focus('#speaker-editor-source-audio-play','клавишей пробела',kind='element')
        await page.locator('#speaker-editor-source-audio-play').press('Space')
    elif number == 45:
        await at('проект сохраняется')
        await save_speaker_project(page)
    elif number == 46:
        await page.locator("#speaker-editor-save").click()
        await page.locator("#speaker-local-save-confirm").click()
        await page.wait_for_function("document.querySelector('#speaker-editor-status').dataset.dirty === 'false'", timeout=120_000)
    elif number == 47:
        await at('Создать финальную версию')
        await page.wait_for_function("!document.getElementById('speaker-editor-render').disabled", timeout=60_000)
        await page.locator("#speaker-editor-render").click()
        await page.locator("#speaker-editor-result").wait_for(state="visible", timeout=120_000)
        await page.locator("#speaker-editor-result").scroll_into_view_if_needed()
    elif number == 48:
        if not await page.locator("#speaker-editor-result-duration").inner_text():
            raise RuntimeError("final result duration missing")
        await focus('#speaker-editor-result-audio','прослушать',kind='element')
        await page.locator('#speaker-editor-result-audio').press('Space')
        await focus('#speaker-editor-download','скачать',kind='element')
    elif number == 49:
        await at('скачивание файла')
        if not await page.locator("#speaker-editor-download").is_visible():
            raise RuntimeError("local final download missing")
        await page.locator("#speaker-editor-download").click()
        await at('Чтобы готовая')
        await page.locator("#speaker-editor-archive-save").click()
        await page.locator("#speaker-editor-save-dialog").wait_for(state="visible")
        await page.locator("#speaker-editor-save-submit").click()
        await page.locator("#speaker-editor-save-dialog").wait_for(state="hidden", timeout=120_000)
    elif number == 51:
        await at('её проект')
        async with page.expect_popup() as opened:
            await page.locator("#detail .project-section").get_by_role("link", name="Продолжить обработку").click()
        popup = await opened.value
        await popup.locator("#speaker-editor").wait_for(state="visible", timeout=60_000)
        return popup
    elif number == 52:
        await at('Истории проекта')
        history = page.locator("#detail .project-disclosure")
        await history.locator(":scope > summary").click()
        await focus("#detail .project-state-row","Там видно")
        if await history.locator(".project-state-row").count() < 3:
            raise RuntimeError("three saved project states not visible")
    elif number == 53:
        await at('Продолжить с этого состояния')
        history = page.locator("#detail .project-disclosure")
        old = history.locator(".project-state-row").last
        await old.get_by_role("link", name="Продолжить с этого состояния").click()
        await page.locator("#speaker-editor").wait_for(state="visible", timeout=60_000)
    elif number == 54:
        await at('финальные версии')
        versions = page.locator("#detail .version-history")
        await versions.locator(":scope > summary").click()
        speaker = versions.locator(".workflow-speaker")
        await speaker.get_by_role("button", name="Прослушать").first.click()
        await page.locator("#player").wait_for(state="visible", timeout=60_000)
    elif number == 55:
        await focus('#detail .project-disclosure','конкретным состоянием проекта')
        await at('вернуться именно')
        history = page.locator("#detail .project-disclosure")
        linked = history.locator(".project-state-row").filter(has_text="Связанные финальные версии:").first
        await linked.get_by_role("link", name="Продолжить с этого состояния").click()
        await page.locator("#speaker-editor").wait_for(state="visible", timeout=60_000)
    elif number == 56:
        await at('изменить название')
        management = page.locator("#detail .record-management")
        await management.locator(":scope > summary").click()
        await page.locator("#metadata-title").fill(title + " · исправлено")
        await page.locator("#metadata-date").fill("2026-09-28T12:00")
        await management.get_by_role("button", name="Сохранить название и дату").click()
        await page.locator("#detail-title").get_by_text(title + " · исправлено").wait_for(timeout=60_000)
    elif number == 57:
        management = page.locator("#detail .record-management")
        await management.locator(":scope > summary").click()
        await management.get_by_role("button", name="Убрать из рабочего списка").click()
        await management.get_by_role("button", name="Вернуть в рабочий список").wait_for(timeout=60_000)
        await at('вернуть обратно')
        await management.get_by_role("button", name="Вернуть в рабочий список").click()
    elif number == 58:
        versions = page.locator("#detail .version-history")
        await versions.locator(":scope > summary").click()
        await versions.locator(".workflow-announcement .destructive-disclosure summary").click()
        if not await versions.get_by_role("button", name="Удалить все версии для анонс-мейкера").is_enabled():
            raise RuntimeError("result deletion control not available")
    elif number == 59:
        danger = page.locator("#detail .danger-zone")
        await danger.locator(":scope > summary").click()
        await at('удаление исходных дорожек')
        await danger.get_by_role('button',name='Удалить исходные дорожки').click()
        await page.locator('#delete-dialog').wait_for(state='visible')
        await focus('#delete-retained','проекты и результаты могут остаться')
        await page.locator('#delete-cancel').click()
        await at('запись можно удалить полностью')
        await danger.get_by_role("button", name="Удалить запись полностью").click()
        await page.locator("#delete-dialog").wait_for(state="visible")
        await focus('#delete-dialog','Перед необратимыми действиями',kind='dialog')
        if not await page.locator("#delete-removed").inner_text():
            raise RuntimeError("deletion consequence preview missing")
    else:
        raise RuntimeError(f"browser scene action not implemented: {scene['id']}")
    alerts = page.locator('[role="alert"]:visible')
    if await alerts.count():
        raise RuntimeError(f"unexpected error banner: {await alerts.first.inner_text()}")
