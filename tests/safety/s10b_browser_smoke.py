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


def waveform_navigation_transition(page, base_url, writes):
    """Release pending metadata at navigation, before the old document's pagehide.

    This retains a main-world File and does not revoke any application URL or
    depend on Playwright's input-file payload implementation.
    """
    events = []
    page.on('console', lambda message: events.append(message.text) if message.text.startswith('S10B_NAV_') else None)
    page.add_init_script("""(() => {
      const add = HTMLMediaElement.prototype.addEventListener;
      let pendingMetadata;
      HTMLMediaElement.prototype.addEventListener = function(type, listener, options) {
        if (type === 'loadedmetadata' && this.preload === 'metadata' && !this.isConnected) {
          return add.call(this, type, event => {
            pendingMetadata = () => listener.call(this, event);
            window.__s10bMetadataReady = true;
          }, options);
        }
        return add.call(this, type, listener, options);
      };
      addEventListener('beforeunload', () => {
        if (pendingMetadata) {
          console.debug('S10B_NAV_METADATA_RELEASED');
          pendingMetadata();
        }
      });
      const read = FileReader.prototype.readAsArrayBuffer;
      FileReader.prototype.readAsArrayBuffer = function(file) {
        if (window.__s10bMetadataReady) console.debug('S10B_NAV_LATE_READ ' + file.name + ' ' + new Error().stack);
        return read.call(this, file);
      };
    })();""")
    page.goto(f'{base_url}/Audio-Editor.html')
    page.evaluate("document.getElementById('source-session-mode-device').click()")
    fixture = source('navigation.wav')
    page.evaluate("""async bytes => {
      await import('./scripts/audio-processor.mjs');
      const file = new File([new Uint8Array(bytes)], 'navigation.wav', { type: 'audio/wav' });
      window.__s10bRetainedNavigationFile = file;
      if ((await file.arrayBuffer()).byteLength !== bytes.length) throw new Error('Invalid navigation fixture');
      const transfer = new DataTransfer(); transfer.items.add(file);
      const input = document.getElementById('processor-file');
      input.files = transfer.files;
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }""", list(fixture['buffer']))
    page.wait_for_function('window.__s10bMetadataReady === true', timeout=30_000)
    before = len(writes)
    page.goto(f'{base_url}/Audio-Archive.html')
    assert 'S10B_NAV_METADATA_RELEASED' in events, events
    assert not any(event.startswith('S10B_NAV_LATE_READ ') for event in events), events
    assert len(writes) == before, 'leaving waveform preparation made an Archive write'


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
    pagehide_revokes = []
    blob_events = []
    file_events = []
    failed_requests = []
    phase = ['initial page']
    page.on('pageerror', lambda error: page_errors.append({
        'phase': phase[0], 'page': page.url, 'message': str(error),
        'stack': getattr(error, 'stack', None),
        'recent_blob_events': blob_events[-16:], 'recent_failed_requests': failed_requests[-8:],
        'recent_file_events': file_events[-32:]
    }))
    page.on('console', lambda message: (
        pagehide_revokes.append(message.text) if message.type == 'error' and message.text.startswith('S10B_REVOKE_DURING_PAGEHIDE ') else None,
        blob_events.append(message.text) if message.text.startswith('S10B_BLOB_') else None,
        file_events.append({'phase': phase[0], 'event': message.text}) if message.text.startswith('S10B_FILE_') else None
    ))
    page.on('requestfailed', lambda request: failed_requests.append((request.url, request.failure)))
    page.add_init_script("""(() => {
      let readId = 0;
      const trace = (event, data = {}) => console.debug('S10B_FILE_' + JSON.stringify({
        event, time: performance.now(), wall: Date.now(), url: location.href, ...data
      }));
      for (const type of ['beforeunload', 'pagehide', 'pageshow']) {
        addEventListener(type, event => trace(type, { persisted: event.persisted }), { capture: true });
      }
      const read = FileReader.prototype.readAsArrayBuffer;
      const abort = FileReader.prototype.abort;
      FileReader.prototype.readAsArrayBuffer = function(file) {
        const id = ++readId;
        this.__s10bReadId = id;
        trace('read-start', { id, name: file.name, size: file.size });
        for (const type of ['load', 'error', 'abort', 'loadend']) {
          this.addEventListener(type, () => trace(type, { id, state: this.readyState, error: this.error?.name }));
        }
        return read.call(this, file);
      };
      FileReader.prototype.abort = function() {
        trace('read-cancel', { id: this.__s10bReadId, state: this.readyState });
        return abort.call(this);
      };
      let pageHiding = false;
      addEventListener('pagehide', () => {
        pageHiding = true;
        queueMicrotask(() => { pageHiding = false; });
      }, { capture: true });
      const create = URL.createObjectURL.bind(URL);
      URL.createObjectURL = blob => {
        const url = create(blob);
        console.debug('S10B_BLOB_CREATE ' + url + ' ' + new Error().stack);
        return url;
      };
      const revoke = URL.revokeObjectURL.bind(URL);
      URL.revokeObjectURL = url => {
        if (pageHiding) console.error('S10B_REVOKE_DURING_PAGEHIDE ' + url);
        console.debug('S10B_BLOB_REVOKE ' + url + ' ' + new Error().stack);
        return revoke(url);
      };
    })();""")
    page.on('request', lambda request: (
        writes.append((request.method, request.url)) if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and '/v1/source-sessions' in request.url else None,
        outbound.append(request.url) if not (request.url.startswith(base_url) or request.url.startswith(f'blob:{base_url}/')) else None
    ))
    phase[0] = 'Archive create/save'
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

    phase[0] = 'Editor device source replacement'
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

    phase[0] = 'Archive session expiry and reconnect'
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
    phase[0] = 'Speaker source A to B, different names'
    speaker_source_transition(page, base_url, writes, False)
    phase[0] = 'Speaker source A to B, same name'
    speaker_source_transition(page, base_url, writes, True)
    phase[0] = 'Editor pending metadata during navigation'
    waveform_navigation_transition(page, base_url, writes)
    assert not page_errors, page_errors
    assert not pagehide_revokes, pagehide_revokes
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
            print(f'PASS S10B {name}: Archive create/cancel/save/reconnect, Editor A→B transition, pending metadata navigation, 320/390/768/1280px')
