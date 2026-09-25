#!/usr/bin/env python3
"""S10B browser checks against the process-local in-memory preview only."""
import argparse
import hashlib
import io
import struct
import wave

from playwright.sync_api import sync_playwright


def source(name, sample=0):
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(struct.pack('<h', sample) * 800)
    return {'name': name, 'mimeType': 'audio/wav', 'buffer': output.getvalue()}


def login(page, url):
    page.goto(f'{url}/Audio-Archive.html')
    page.locator('#admin-password').fill('local-test-password')
    page.locator('#admin-access-form button[type=submit]').click()
    page.wait_for_url('**/Audio-Archive.html')


def assert_fits(page, widths):
    for width in widths:
        page.set_viewport_size({'width': width, 'height': 850})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'horizontal overflow at {width}px'


def speaker_source_transition(page, base_url, writes, same_name):
    a = source('same.wav' if same_name else 'A.wav', 0)
    b = source('same.wav' if same_name else 'B.wav', 200)
    assert len(a['buffer']) == len(b['buffer']) and a['buffer'] != b['buffer']
    title = 'S10B B same-name' if same_name else 'S10B B different-name'
    page.goto(f'{base_url}/Audio-Editor.html')
    page.locator('#source-session-mode-device').click()
    page.locator('#processor-file').set_input_files(a)
    page.wait_for_function("document.querySelector('#import-files').textContent.includes('.wav')")
    page.locator('#source-session-use-local').click()
    page.locator('#open-local-speaker').click()
    page.wait_for_function("async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().ready", timeout=30_000)
    page.evaluate("async () => { const speaker = (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState(); window.__s10bA = speaker.files[0]; window.__s10bPayload = JSON.stringify(speaker.payload); }")
    page.wait_for_function("!document.querySelector('#processor-save-incoming').disabled", timeout=30_000)
    # The focused Speaker layout hides source selection, but the already-open
    # ingestion action can still run while that local project remains active.
    page.evaluate("document.getElementById('processor-save-incoming').click()")
    page.locator('#source-session-ingest-dialog').wait_for(state='visible')
    page.locator('#source-session-ingest-name').fill(title)
    page.locator('#source-session-ingest-replace').click()
    page.locator('#source-session-ingest-files').set_input_files(b)
    before = len(writes)
    page.locator('#source-session-ingest-submit').click()
    page.locator('#speaker-unsaved-dialog').wait_for(state='visible')
    page.locator('#speaker-unsaved-cancel').click()
    assert len(writes) == before, 'declined transition made an Archive write'
    assert page.locator('#source-session-ingest-name').input_value() == title
    assert b['name'] in page.locator('#source-session-ingest-list').inner_text()
    assert page.evaluate("async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().files[0] === window.__s10bA")
    assert page.evaluate("async () => JSON.stringify((await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload) === window.__s10bPayload")
    page.locator('#source-session-ingest-submit').click()
    page.locator('#speaker-unsaved-dialog').wait_for(state='visible')
    page.locator('#speaker-unsaved-discard').click()
    page.locator('#source-session-ingest-dialog').wait_for(state='hidden', timeout=30_000)
    assert len([method for method, url in writes[before:] if method == 'POST' and url.endswith('/ingestions')]) == 1
    assert page.locator('#current-recording-heading').inner_text() == title
    assert page.locator('#speaker-editor').is_hidden()
    session_id = page.evaluate("new URL(document.querySelector('#current-recording-archive-link').href).searchParams.get('session')")
    session = page.evaluate("async id => (await (await fetch(`/v1/source-sessions/${id}`)).json())", session_id)
    assert session['sourceTracks'][0]['sha256'] == hashlib.sha256(b['buffer']).hexdigest()
    assert session['sourceTracks'][0]['originalName'] == b['name']
    assert page.evaluate("async () => (await import('./scripts/audio-processor.mjs')).getProcessorFiles()[0] !== window.__s10bA")
    page.locator('#open-local-speaker').click()
    page.wait_for_function("async id => { const speaker = (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState(); return speaker.ready && speaker.session?.id === id; }", arg=session_id, timeout=30_000)
    page.locator('#speaker-editor').wait_for(state='visible')
    assert page.evaluate("async () => (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().files[0] !== window.__s10bA")
    page.locator('#speaker-editor-save').click()
    page.wait_for_function("document.querySelector('#speaker-editor-status').dataset.dirty === 'false'", timeout=30_000)
    draft = page.evaluate("async id => (await (await fetch(`/v1/source-sessions/${id}/drafts/speaker`)).json()).draft", session_id)
    assert draft['sessionId'] == session_id
    assert draft['payload']['trackIds'] == [session['sourceTracks'][0]['trackId']]


def run(browser_type, base_url):
    browser = browser_type.launch(headless=True)
    page = browser.new_page(viewport={'width': 390, 'height': 850})
    page_errors = []
    writes = []
    outbound = []
    page.on('pageerror', lambda error: page_errors.append(str(error)))
    page.on('request', lambda request: (
        writes.append((request.method, request.url)) if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and '/v1/source-sessions' in request.url else None,
        outbound.append(request.url) if not (request.url.startswith(base_url) or request.url.startswith(f'blob:{base_url}/')) else None
    ))
    login(page, base_url)
    assert page.locator('#archive-create-open').is_visible()
    assert page.locator('#archive-create-files').get_attribute('multiple') is not None
    page.locator('#archive-create-open').click()
    assert page.evaluate('document.activeElement.id') == 'archive-create-title'
    page.keyboard.press('Tab')
    assert page.evaluate('document.activeElement.id') == 'archive-create-name'
    assert_fits(page, (320, 390, 768, 1280))
    page.locator('#archive-create-files').set_input_files(source('first.wav'))
    assert 'first.wav' in page.locator('#archive-create-list').inner_text()
    page.locator('#archive-create-files').dispatch_event('change')  # empty input after handler reset = cancelled picker
    assert 'first.wav' in page.locator('#archive-create-list').inner_text()
    page.locator('#archive-create-add').click()
    page.locator('#archive-create-files').set_input_files(source('second.wav'))
    assert page.locator('#archive-create-list li').count() == 2
    page.locator('#archive-create-replace').click()
    page.locator('#archive-create-files').set_input_files(source('final.wav'))
    assert page.locator('#archive-create-list li').count() == 1
    assert 'final.wav' in page.locator('#archive-create-list').inner_text()
    page.locator('#archive-create-replace').click()
    page.locator('#archive-create-files').set_input_files({'name': 'wrong.txt', 'mimeType': 'text/plain', 'buffer': b'a'})
    assert 'final.wav' in page.locator('#archive-create-list').inner_text()
    assert 'MP3' in page.locator('#archive-create-status').inner_text()
    page.locator('#archive-create-replace').click()
    page.locator('#archive-create-files').set_input_files(source('very-long-' + 'a' * 180 + '.wav'))
    assert_fits(page, (320, 390, 768, 1280))
    page.locator('#archive-create-replace').click()
    page.locator('#archive-create-files').set_input_files(source('final.wav'))
    page.locator('#archive-create-name').fill('   ')
    page.locator('#archive-create-submit').click()
    assert not writes
    assert 'название' in page.locator('#archive-create-status').inner_text().lower()
    page.locator('#archive-create-name').fill('S10B браузер')
    page.locator('#archive-create-cancel').click()
    assert not writes
    page.locator('#archive-create-open').click()
    page.locator('#archive-create-name').fill('S10B браузер')
    page.locator('#archive-create-files').set_input_files(source('final.wav'))
    page.locator('#archive-create-submit').click()
    page.locator('#detail-title').wait_for()
    assert page.locator('#detail-title').inner_text() == 'S10B браузер'
    assert 'Дата не указана' in page.locator('#detail-heading').inner_text()
    assert 'final.wav' in page.locator('#detail-body').inner_text()
    assert len([x for x in writes if x[0] == 'POST' and x[1].endswith('/ingestions')]) == 1
    assert_fits(page, (320, 390, 768, 1280))

    page.goto(f'{base_url}/Audio-Editor.html')
    page.locator('#source-session-mode-device').click()
    assert_fits(page, (320, 390, 768, 1280))
    page.locator('#processor-file').set_input_files(source('one.wav'))
    page.wait_for_function("document.querySelector('#import-files').textContent.includes('one.wav')")
    page.locator('#processor-file').set_input_files({'name': 'bad.txt', 'mimeType': 'text/plain', 'buffer': b'a'})
    assert 'one.wav' in page.locator('#import-files').inner_text()
    assert 'MP3' in page.locator('#device-import-status').inner_text()
    page.locator('#import-add-files').set_input_files(source('two.wav'))
    page.wait_for_function("document.querySelector('#import-files').textContent.includes('two.wav')")
    assert page.locator('#import-files li').count() == 2
    page.locator('#processor-file').set_input_files(source('three.wav'))
    page.wait_for_function("document.querySelector('#import-files').textContent.includes('three.wav')")
    assert page.locator('#import-files li').count() == 1
    assert not page.locator('#processor-file').is_visible()

    page.goto(f'{base_url}/Audio-Archive.html')
    page.locator('#archive-create-open').click()
    page.locator('#archive-create-name').fill('S10B после входа')
    page.locator('#archive-create-files').set_input_files(source('retry.wav'))
    page.request.post(f'{base_url}/__test/expire')
    page.locator('#archive-create-submit').click()
    page.get_by_text('После входа продолжите сохранение.', exact=False).wait_for()
    assert 'retry.wav' in page.locator('#archive-create-list').inner_text()
    assert page.locator('#archive-create-name').input_value() == 'S10B после входа'
    page.locator('#login').click()
    page.locator('#password').fill('local-test-password')
    page.locator('#login-form button[type=submit]').click()
    page.locator('#login-dialog').wait_for(state='hidden')
    page.locator('#archive-create-submit').click()
    page.locator('#detail-title').wait_for()
    assert page.locator('#detail-title').inner_text() == 'S10B после входа'
    assert 'retry.wav' in page.locator('#detail-body').inner_text()
    assert len([x for x in writes if x[0] == 'POST' and x[1].endswith('/ingestions')]) == 3
    speaker_source_transition(page, base_url, writes, False)
    speaker_source_transition(page, base_url, writes, True)
    assert not page_errors, page_errors
    assert not outbound, outbound
    browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://localhost:4183')
    parser.add_argument('--browser', choices=('chromium', 'firefox', 'webkit', 'all'), default='chromium')
    args = parser.parse_args()
    with sync_playwright() as playwright:
        names = ('chromium', 'firefox', 'webkit') if args.browser == 'all' else (args.browser,)
        for name in names:
            run(getattr(playwright, name), args.base_url)
            print(f'PASS S10B {name}: Archive create/cancel/save/reconnect, Editor A→B transition, 320/390/768/1280px')
