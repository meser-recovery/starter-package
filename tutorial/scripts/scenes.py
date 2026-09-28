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


async def import_local(page, base: str, mode: str | None = None):
    await page.goto(base + "/Audio-Editor.html")
    await page.locator("#source-session-mode-device").click()
    await page.locator("#processor-file").set_input_files([str(path) for path in TRACKS])
    await page.wait_for_function("document.querySelector('#import-files').textContent.includes('Участник.wav')")
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
    await page.locator(".speaker-selection > details:first-of-type").evaluate("element => element.open = true")
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
    if number == 6:
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
    elif 23 <= number <= 29:
        if number == 29:
            await import_archive(page, base, title, "announcement")
        else:
            await import_local(page, base, None if number == 23 else "announcement")
        if number in (28, 29):
            await page.locator("#processor-run").click()
            await page.locator("#processor-result").wait_for(state="visible", timeout=120_000)
    elif 30 <= number <= 43 or 45 <= number <= 49:
        if number in (45, 49):
            await import_archive(page, base, title, "speaker")
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
    elif number == 58:
        await import_archive(page, base, title, "announcement")
        await publish_announcement(page)
        await open_archive_detail_from_editor(page, base, title)
    elif 56 <= number <= 59:
        await create_archive(page, title)
    else:
        raise RuntimeError(f"browser scene setup not implemented: {scene['id']}")


async def perform(page, scene: dict, base: str):
    number = int(scene["id"][:3])
    title = f"Учебная запись S11 {number:03d}"
    if number == 6:
        await page.locator('nav[aria-label="Аудиопортал"] a[href="Audio-Archive.html"]').click()
        await page.get_by_role("heading", name="Аудиоархив").wait_for()
    elif number == 7:
        await page.locator("#archive-create-open").click()
        await page.locator("#archive-create-name").fill(title)
        await page.locator("#archive-create-recorded").fill("2026-09-28T12:00")
        if not await page.locator("#archive-create-name").input_value() == title:
            raise RuntimeError("archive title not set")
    elif number == 8:
        await page.locator("#archive-create-files").set_input_files([str(path) for path in TRACKS[:3]])
        if await page.locator("#archive-create-list li").count() != 3:
            raise RuntimeError("three selected synthetic tracks not visible")
    elif number == 9:
        await page.locator("#archive-create-add").click()
        await page.locator("#archive-create-files").set_input_files(str(TRACKS[1]))
        await page.locator("#archive-create-replace").click()
        await page.locator("#archive-create-files").set_input_files([str(path) for path in TRACKS[:3]])
        if await page.locator("#archive-create-list li").count() != 3:
            raise RuntimeError("add/replace final selection mismatch")
    elif number == 10:
        await page.locator("#archive-create-submit").click()
        await page.locator("#detail-title").wait_for(timeout=60_000)
    elif number == 12:
        await page.locator('#filters input[name="search"]').fill(title)
        await page.locator("#record-picker-search").click()
        await page.locator("#session-list").get_by_text(title).first.wait_for()
        await page.locator(".secondary-filters summary").click()
        await page.locator('#filters select[name="sort"]').select_option("title")
        await page.locator("#record-picker-recent").click()
    elif number == 13:
        await page.locator('nav[aria-label="Аудиопортал"] a[href="Audio-Editor.html"]').click()
        await page.locator("#source-session-mode-archive").wait_for()
    elif number == 14:
        await page.locator("#source-session-mode-archive").click()
        item = page.locator("#source-session-list .source-session-item").filter(has_text=title).first
        await item.get_by_role("button", name="Выбрать").click()
        await page.locator("#workflow-choice").wait_for(state="visible", timeout=60_000)
    elif number == 15:
        await page.locator("#processor-file").set_input_files([str(path) for path in TRACKS])
        await page.locator("#source-session-use-local").click()
        await page.locator("#workflow-choice").wait_for(state="visible", timeout=60_000)
    elif number == 16:
        if await page.locator("#current-recording-archive-link").is_visible():
            raise RuntimeError("local import unexpectedly linked to Archive")
        await page.locator("#source-session-mode-device").click()
    elif number == 17:
        await page.locator("#source-session-mode-device").click()
        await page.locator("#processor-save-incoming").click()
        await page.locator("#source-session-ingest-dialog").wait_for(state="visible")
        await page.locator("#source-session-ingest-name").fill(title)
        await page.locator("#source-session-ingest-submit").click()
        await page.locator("#current-recording-heading").get_by_text(title).wait_for(timeout=60_000)
    elif number == 18:
        if not await page.locator("#open-local-announcement").is_visible() or not await page.locator("#open-local-speaker").is_visible():
            raise RuntimeError("both editor modes not visible")
    elif number == 23:
        await page.locator("#open-local-announcement").click()
        await page.locator("#announcement-processor-card").wait_for(state="visible", timeout=60_000)
    elif number == 30:
        await page.locator("#open-local-speaker").click()
        await page.locator("#speaker-editor").wait_for(state="visible", timeout=60_000)
    elif number == 24:
        rows = page.locator("#processor-file-info .processor-track")
        await rows.first.locator('[data-track-action="solo"]').click()
        await rows.nth(1).locator('[data-track-action="mute"]').click()
        if await rows.first.locator('[data-track-action="solo"]').get_attribute("aria-pressed") != "true":
            raise RuntimeError("announcement Solo did not engage")
    elif number == 25:
        await page.locator("#processor-source-zoom-in").click()
        await page.locator("#processor-source-zoom-fit").click()
        await page.locator("#processor-source-follow").click()
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
        await page.locator('#processor-file-info .processor-track input[type="color"]').first.fill("#27b3a0")
        await page.locator('#processor-file-info [data-track-action="move-down"]').first.click()
        await page.locator('#processor-file-info [data-track-action="remove"]').last.click()
        if await page.locator("#processor-file-info .processor-track").count() != 3:
            raise RuntimeError("erroneous announcement track not removed")
    elif number == 27:
        await page.locator("#processor-run").click()
        await page.locator("#processor-result").wait_for(state="visible", timeout=120_000)
    elif number == 28:
        await page.wait_for_function("document.querySelector('#processor-processed-duration').textContent.trim().length>0", timeout=30_000)
    elif number == 29:
        if not await page.locator("#processor-download").is_visible():
            raise RuntimeError("announcement MP3 download missing")
        await page.locator("#processor-download").click()
        await page.locator("#source-session-publish-announcement").click()
        await page.locator("#source-session-publication-dialog").wait_for(state="visible")
        await page.locator("#source-session-publication-submit").click()
        await page.locator("#source-session-publication-dialog").wait_for(state="hidden", timeout=120_000)
    elif number == 31:
        row = page.locator("#speaker-editor-tracks .speaker-track").first
        await row.locator('[data-dsp-field="enhancement"]').check()
        await row.locator('[data-dsp-field="leveling"]').check()
        await row.locator('[data-dsp-field="compression"]').evaluate("""input => {
          input.value='2'; input.dispatchEvent(new Event('input',{bubbles:true}));
          input.dispatchEvent(new Event('change',{bubbles:true}));}""")
        settings = await page.evaluate("""async () =>
          (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload.trackProcessing[0]""")
        if [settings[key] for key in ("enhancement", "leveling", "compression")] != ["gentle", "on", "medium"]:
            raise RuntimeError("independent track DSP selection failed")
    elif number == 32:
        await page.locator("#speaker-editor-source-audio-play").click()
        await page.locator("#speaker-editor-tracks .audio-meter").first.wait_for()
    elif number == 33:
        row = page.locator("#speaker-editor-tracks .speaker-track").last
        await row.locator('[data-action="solo"]').click()
        await row.locator('[data-action="mute"]').click()
        await row.get_by_role("button", name="Исключить из микса").click()
        if not await row.evaluate("element => element.classList.contains('is-excluded')"):
            raise RuntimeError("track exclusion did not affect project")
        await row.get_by_role("button", name="Вернуть в микс").click()
    elif number == 34:
        row = page.locator("#speaker-editor-tracks .speaker-track").first
        await row.locator('input[type="color"]').fill("#27b3a0")
        await row.get_by_role("button", name="Вниз").click()
        await page.locator("#speaker-editor-expand").click()
    elif number == 35:
        await page.locator("#speaker-editor-zoom-in").click()
        await page.locator("#speaker-editor-follow").click()
        await page.locator("#speaker-editor-zoom-fit").click()
        await page.locator("#speaker-editor-scale-mode").click()
    elif number == 36:
        await drag_speaker_selection(page)
        await page.locator("#speaker-editor-source-audio-loop").click()
        edge = page.locator("#speaker-editor-tracks .speaker-boundary--start").first
        if await edge.count():
            await edge.focus()
            await page.keyboard.press("ArrowRight")
        if await page.locator("#speaker-editor-source-audio-loop").get_attribute("aria-pressed") != "true":
            raise RuntimeError("Speaker Loop did not engage")
    elif number == 37:
        await select_speaker_range(page, "2", "3")
        await page.locator("#speaker-editor-set-start").click()
        await select_speaker_range(page, "15", "16")
        await page.locator("#speaker-editor-set-end").click()
    elif number == 38:
        await add_speaker_edit(page, "cut")
    elif number == 39:
        await restore_speaker_edit(page, "cut")
    elif number == 40:
        await add_speaker_edit(page, "silence")
    elif number == 41:
        await restore_speaker_edit(page, "silence")
    elif number == 42:
        edge = page.locator('#speaker-editor-tracks [data-edge="start"]').first
        before = await edge.get_attribute("aria-valuenow")
        await edge.focus()
        await page.keyboard.press("ArrowRight")
        if await edge.get_attribute("aria-valuenow") == before:
            raise RuntimeError("region boundary did not move")
        await page.locator("#speaker-editor-selection-start").fill("2.5")
    elif number == 43:
        await page.locator("#speaker-editor-undo").click()
        await page.locator("#speaker-editor-redo").click()
    elif number == 45:
        await save_speaker_project(page)
    elif number == 46:
        await page.locator("#speaker-editor-save").click()
        await page.locator("#speaker-local-save-confirm").click()
        await page.wait_for_function("document.querySelector('#speaker-editor-status').dataset.dirty === 'false'", timeout=120_000)
    elif number == 47:
        await page.wait_for_function("!document.getElementById('speaker-editor-render').disabled", timeout=60_000)
        await page.locator("#speaker-editor-render").click()
        await page.locator("#speaker-editor-result").wait_for(state="visible", timeout=120_000)
    elif number == 48:
        if not await page.locator("#speaker-editor-result-duration").inner_text():
            raise RuntimeError("final result duration missing")
    elif number == 49:
        if not await page.locator("#speaker-editor-download").is_visible():
            raise RuntimeError("local final download missing")
        await page.locator("#speaker-editor-download").click()
        await page.locator("#speaker-editor-archive-save").click()
        await page.locator("#speaker-editor-save-dialog").wait_for(state="visible")
        await page.locator("#speaker-editor-save-submit").click()
        await page.locator("#speaker-editor-save-dialog").wait_for(state="hidden", timeout=120_000)
    elif number == 51:
        async with page.expect_popup() as opened:
            await page.locator("#detail .project-section").get_by_role("link", name="Продолжить обработку").click()
        popup = await opened.value
        await popup.locator("#speaker-editor").wait_for(state="visible", timeout=60_000)
        return popup
    elif number == 52:
        history = page.locator("#detail .project-disclosure")
        await history.locator(":scope > summary").click()
        if await history.locator(".project-state-row").count() < 3:
            raise RuntimeError("three saved project states not visible")
    elif number == 53:
        history = page.locator("#detail .project-disclosure")
        await history.locator(":scope > summary").click()
        old = history.locator(".project-state-row").last
        await old.get_by_role("link", name="Продолжить с этого состояния").click()
        await page.locator("#speaker-editor").wait_for(state="visible", timeout=60_000)
    elif number == 54:
        versions = page.locator("#detail .version-history")
        await versions.locator(":scope > summary").click()
        speaker = versions.locator(".workflow-speaker")
        await speaker.get_by_role("button", name="Прослушать").first.click()
        await page.locator("#player").wait_for(state="visible", timeout=60_000)
    elif number == 55:
        history = page.locator("#detail .project-disclosure")
        await history.locator(":scope > summary").click()
        linked = history.locator(".project-state-row").filter(has_text="Связанные финальные версии:").first
        await linked.get_by_role("link", name="Продолжить с этого состояния").click()
        await page.locator("#speaker-editor").wait_for(state="visible", timeout=60_000)
    elif number == 56:
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
        await danger.get_by_role("button", name="Удалить запись полностью").click()
        await page.locator("#delete-dialog").wait_for(state="visible")
        if not await page.locator("#delete-removed").inner_text():
            raise RuntimeError("deletion consequence preview missing")
    else:
        raise RuntimeError(f"browser scene action not implemented: {scene['id']}")
    alerts = page.locator('[role="alert"]:visible')
    if await alerts.count():
        raise RuntimeError(f"unexpected error banner: {await alerts.first.inner_text()}")
