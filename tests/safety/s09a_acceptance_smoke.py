"""PR #35 Acceptance regressions: delayed transitions and project-list authentication.

Actual browser modules + synthetic in-memory gateway; route interception precedes navigation.
"""
import base64
import json
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
RECONNECT = 'Подключение к аудиоархиву истекло. Подключитесь снова, чтобы продолжить.'


def check_s09a_acceptance(browser, base_url, screenshot_dir=None, scenario='all'):
    site = urlparse(base_url)
    origin = f'{site.scheme}://{site.netloc}'
    bridge = subprocess.Popen(['node', str(ROOT/'tests/safety/archive_management_bridge.mjs')], cwd=ROOT,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    seed = json.loads(bridge.stdout.readline())
    primary, other = seed['primary'], seed['empty']
    context = browser.new_context(viewport={'width': 390, 'height': 900})
    context.add_init_script("""(() => {
      sessionStorage.setItem('meser_service_access_v1','granted');
      window.__MESER_AUDIO_ARCHIVE_GATEWAY__='https://gateway.test';
      const nativeFetch = window.fetch.bind(window);
      let heldPart = null;
      window.__s10aHoldPartResponse = sessionId => {
        let release;
        const gate = new Promise(resolve => { release = resolve; });
        heldPart = {sessionId, gate, release, armed: true, held: false};
      };
      window.__s10aPartResponseHeld = () => Boolean(heldPart?.held);
      window.__s10aReleasePartResponse = () => heldPart?.release();
      window.fetch = async (input, options = {}) => {
        const url = String(typeof input === 'string' ? input : input.url);
        if (heldPart?.armed && url.includes(`/v1/source-sessions/${heldPart.sessionId}/blobs/`) && url.includes('/parts/')) {
          heldPart.armed = false;
          const {signal: _ignoredSignal, ...detachedOptions} = options;
          const response = await nativeFetch(input, detachedOptions);
          heldPart.held = true;
          await heldPart.gate;
          return response;
        }
        return nativeFetch(input, options);
      };
    })();""")
    trace, blocked, errors, held = [], [], [], []
    fault = {'match': None, 'status': None, 'hold': False}
    headers = {'Access-Control-Allow-Origin': origin, 'Access-Control-Allow-Credentials': 'true',
               'Access-Control-Allow-Headers': 'Content-Type, X-CSRF-Token, X-Part-SHA256, Idempotency-Key',
               'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, OPTIONS'}

    def fulfill(route, result):
        route.fulfill(status=result['status'], content_type=result.get('type') or 'application/json', headers=headers,
                      body=base64.b64decode(result['body']) if result.get('base64') else result['body'])

    def intercept(route):
        request = route.request
        target = urlparse(request.url)
        if target.netloc == site.netloc:
            route.continue_(); return
        if target.netloc != 'gateway.test':
            blocked.append(request.url); route.abort(); return
        if request.method == 'OPTIONS':
            route.fulfill(status=204, headers=headers); return
        path = target.path + ('?'+target.query if target.query else '')
        trace.append((request.method, path))
        matches = request.method == 'GET' and fault['match'] and fault['match'](target.path)
        if matches and fault['status']:
            status = fault['status']; fault['status'] = None
            fulfill(route, {'status': status, 'body': '{"error":"Expired test session"}'}); return
        bridge.stdin.write(json.dumps({'action': 'request', 'path': path, 'method': request.method,
            'headers': request.headers, 'bodyBase64': base64.b64encode(request.post_data_buffer).decode() if request.post_data_buffer else None})+'\n')
        bridge.stdin.flush()
        result = json.loads(bridge.stdout.readline()); assert 'bridgeError' not in result, result
        if matches and fault['hold']:
            fault['hold'] = False; held.append((route, result)); return
        fulfill(route, result)

    context.route('**/*', intercept)
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    output = Path(screenshot_dir)/'s09a-acceptance' if screenshot_dir else None
    if output: output.mkdir(parents=True, exist_ok=True)

    def shot(name):
        if output:
            page.screenshot(path=str(output/(name+'.png')), full_page=True)
            if page.locator('dialog[open]').count():
                page.screenshot(path=str(output/(name+'-viewport.png')))

    def wait_held():
        deadline = time.monotonic()+15
        while not held and time.monotonic() < deadline: page.wait_for_timeout(20)
        assert len(held) == 1, 'Expected a deliberately delayed source response'

    def release():
        route, result = held.pop(); fulfill(route, result)

    def open_primary(render=True):
        fault.update(match=None, status=None, hold=False)
        page.goto(base_url.rstrip('/')+f'/Audio-Editor.html?session={primary["id"]}&workflow=speaker')
        page.wait_for_function("document.getElementById('speaker-editor-status').textContent==='Все изменения сохранены'")
        if render:
            page.locator('#speaker-editor-render').click()
            page.wait_for_function("!document.getElementById('speaker-editor-result').hidden", timeout=60000)

    def remember():
        return page.evaluate("""async () => {
          const s=(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState();
          window.__acceptanceWork={files:s.files,blob:s.candidate?.blob,url:document.getElementById('speaker-editor-download').getAttribute('href')};
          return {session:s.session,payload:s.payload,draft:s.draft,epoch:s.sourceEpoch};
        }""")

    def preserved(before):
        after = page.evaluate("""async () => {
          const s=(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState(), old=window.__acceptanceWork;
          if(s.files.length!==old.files.length || s.files.some((file,i)=>file!==old.files[i]) || s.candidate?.blob!==old.blob) throw new Error('Working File/Blob references changed');
          if(document.getElementById('speaker-editor-download').getAttribute('href')!==old.url) throw new Error('Result URL changed');
          if(old.url && !(await fetch(old.url)).ok) throw new Error('Result URL revoked');
          return {session:s.session,payload:s.payload,draft:s.draft,epoch:s.sourceEpoch};
        }""")
        assert after == before
        assert page.locator('#speaker-editor').is_visible()
        assert page.locator('#announcement-processor-card').is_hidden()

    def activate(selector):
        """Invoke a transition control even when the approved full-screen workspace hides the chooser."""
        page.locator(selector).evaluate('element => element.click()')

    def choose(session, workflow, wait_context=True):
        activate('#source-session-mode-archive')
        page.locator('#source-session-recent').click()
        page.locator(f'.source-session-item[data-session-id="{session["id"]}"]').get_by_role('button', name='Выбрать', exact=True).click()
        if not wait_context:
            return
        page.wait_for_function('(title) => document.getElementById("current-recording-heading").textContent === title', arg=session['title'])
        page.locator('#open-local-speaker' if workflow == 'speaker' else '#open-local-announcement').click()

    def login(editor=True):
        if editor:
            activate('#archive-reconnect-login')
            page.locator('#source-session-password').fill('local-test-password')
            page.locator('#source-session-login-form button[type=submit]').click()
            page.locator('#source-session-login-dialog').wait_for(state='hidden')
        else:
            page.locator('#login').click(); page.locator('#password').fill('local-test-password')
            page.locator('#login-form button[type=submit]').click()
            page.locator('#login-dialog').wait_for(state='hidden')

    def no_archive_writes(start):
        assert not [(m,p) for m,p in trace[start:] if m != 'GET' and p not in ('/v1/session/login','/v1/session/logout')]

    try:
        if scenario in ('all', 'rapid-selection'):
            page.goto(base_url.rstrip('/')+'/Audio-Editor.html')
            page.wait_for_function("document.getElementById('source-session-recent').disabled === false")
            activate('#source-session-mode-archive'); page.locator('#source-session-recent').click()
            page.wait_for_function('(id) => Boolean(document.querySelector(`.source-session-item[data-session-id="${id}"]`))', arg=other['id'])
            start = len(trace)

            # A deliberately late response ignores AbortSignal so generation fencing, not
            # transport cooperation, must keep A from replacing the newer completed B.
            page.evaluate('(id) => window.__s10aHoldPartResponse(id)', primary['id'])
            page.locator(f'.source-session-item[data-session-id="{primary["id"]}"]').get_by_role('button', name='Выбрать', exact=True).evaluate('button => button.click()')
            page.wait_for_function('window.__s10aPartResponseHeld()')
            page.locator(f'.source-session-item[data-session-id="{other["id"]}"]').get_by_role('button', name='Выбрать', exact=True).evaluate('button => button.click()')
            page.wait_for_function('(title) => document.getElementById("current-recording-heading").textContent === title', arg=other['title'])
            page.locator('#source-session-loading').wait_for(state='hidden')
            ready_status = page.locator('#source-session-status').inner_text()
            assert page.locator('#speaker-editor').is_hidden()
            assert page.locator('#announcement-processor-card').is_hidden()
            page.evaluate('window.__s10aReleasePartResponse()')
            page.wait_for_timeout(250)
            assert page.locator('#current-recording-heading').inner_text() == other['title']
            assert page.locator('#source-session-status').inner_text() == ready_status
            assert page.locator('#speaker-editor').is_hidden()
            assert page.locator('#announcement-processor-card').is_hidden()

            other_part_gets = [p for m,p in trace if m == 'GET' and p.startswith(f'/v1/source-sessions/{other["id"]}/blobs/')]
            activate('#open-local-speaker')
            page.wait_for_function("async(id)=>{const state=(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState();return state.ready&&state.session?.id===id}", arg=other['id'], timeout=60000)
            page.wait_for_function("document.getElementById('source-session-status').textContent.includes('Открыта работа «Спикерская»')")
            speaker_identity = page.evaluate("""async () => {
              const state = (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState();
              window.__s10aSelectedFiles = state.files;
              return {sessionId: state.session.id, count: state.files.length};
            }""")
            assert speaker_identity == {'sessionId': other['id'], 'count': len(other['sourceTracks'])}
            assert [p for m,p in trace if m == 'GET' and p.startswith(f'/v1/source-sessions/{other["id"]}/blobs/')] == other_part_gets
            page.locator('#speaker-editor-close').click()
            if page.locator('#speaker-unsaved-dialog').is_visible():
                page.locator('#speaker-unsaved-discard').click()
            page.locator('#speaker-editor').wait_for(state='hidden')
            activate('#open-local-announcement')
            page.locator('#announcement-processor-card').wait_for(state='visible')
            page.wait_for_function("!document.getElementById('processor-run').disabled")
            assert page.evaluate("""async () => {
              const files = (await import('./scripts/audio-processor.mjs')).getProcessorFiles();
              return files.length === window.__s10aSelectedFiles.length && files.every((file, index) => file === window.__s10aSelectedFiles[index]);
            }""")
            assert [p for m,p in trace if m == 'GET' and p.startswith(f'/v1/source-sessions/{other["id"]}/blobs/')] == other_part_gets

            # Explicit cancel while A is late preserves the already committed B batch and
            # the exact File objects currently owned by Announcement.
            page.evaluate('(id) => window.__s10aHoldPartResponse(id)', primary['id'])
            activate('#source-session-mode-archive'); page.locator('#source-session-recent').click()
            page.locator(f'.source-session-item[data-session-id="{primary["id"]}"]').get_by_role('button', name='Выбрать', exact=True).evaluate('button => button.click()')
            page.wait_for_function('window.__s10aPartResponseHeld()')
            page.locator('#source-session-loading-cancel').click()
            assert page.locator('#current-recording-heading').inner_text() == other['title']
            assert page.evaluate("""async () => {
              const files = (await import('./scripts/audio-processor.mjs')).getProcessorFiles();
              return files.length === window.__s10aSelectedFiles.length && files.every((file, index) => file === window.__s10aSelectedFiles[index]);
            }""")
            cancelled_status = page.locator('#source-session-status').inner_text()
            assert 'отменена' in cancelled_status.lower()
            page.evaluate('window.__s10aReleasePartResponse()')
            page.locator('#source-session-loading').wait_for(state='hidden')
            page.wait_for_timeout(250)
            assert page.locator('#current-recording-heading').inner_text() == other['title']
            assert page.locator('#source-session-status').inner_text() == cancelled_status
            assert page.locator('#announcement-processor-card').is_visible()
            assert page.locator('#speaker-editor').is_hidden()
            assert page.evaluate("""async () => {
              const files = (await import('./scripts/audio-processor.mjs')).getProcessorFiles();
              return files.length === window.__s10aSelectedFiles.length && files.every((file, index) => file === window.__s10aSelectedFiles[index]);
            }""")
            no_archive_writes(start)
            print('S10A rapid selection: late A cannot replace B; exact Files persist through workflow reuse and cancelled replacement.', flush=True)

        if scenario in ('all', 'delayed-speaker'):
            open_primary()
            start = len(trace)
            if not page.locator('.speaker-selection > details:first-of-type').evaluate('e=>e.open'):
                page.get_by_text('Точное редактирование', exact=True).click()
            page.locator('#speaker-editor-selection-start').fill('.05'); page.locator('#speaker-editor-selection-end').fill('.2'); page.locator('#speaker-editor-set-start').click()
            page.locator('#speaker-editor-render').click()
            page.wait_for_function("!document.getElementById('speaker-editor-result').hidden", timeout=60000)
            changed = remember()
            # The new chooser changes context before a workflow starts. Dirty work is
            # therefore protected before any bytes for the other recording are read.
            activate('#source-session-mode-archive'); page.locator('#source-session-recent').click()
            page.locator(f'.source-session-item[data-session-id="{other["id"]}"]').get_by_role('button', name='Выбрать', exact=True).click()
            page.locator('#speaker-unsaved-dialog').wait_for(state='visible')
            shot('chooser-context-new-edits-protected')
            page.locator('#speaker-unsaved-cancel').click(); preserved(changed)
            assert changed['payload']['globalCuts'][0]['endSeconds'] == .05
            activate('#source-session-mode-archive'); page.locator('#source-session-recent').click()
            page.locator(f'.source-session-item[data-session-id="{other["id"]}"]').get_by_role('button', name='Выбрать', exact=True).click()
            page.locator('#speaker-unsaved-discard').click()
            page.wait_for_function('(title) => document.getElementById("current-recording-heading").textContent === title', arg=other['title'])
            assert page.locator('#speaker-editor').is_hidden()
            assert page.evaluate("async()=>!(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().session")
            assert page.locator('#speaker-unsaved-dialog').is_hidden()
            # The prepared batch is reused when the workflow opens: no second source download.
            prepared_gets = [p for m,p in trace if m == 'GET' and p.startswith(f'/v1/source-sessions/{other["id"]}/blobs/')]
            activate('#open-local-speaker')
            page.wait_for_function("async()=>Boolean((await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().ready)", timeout=60000)
            reused_gets = [p for m,p in trace if m == 'GET' and p.startswith(f'/v1/source-sessions/{other["id"]}/blobs/')]
            assert reused_gets == prepared_gets
            page.locator('#speaker-editor-close').click()
            if page.locator('#speaker-unsaved-dialog').is_visible():
                page.locator('#speaker-unsaved-discard').click()
            page.locator('#speaker-editor').wait_for(state='hidden')
            activate('#source-session-mode-archive'); page.locator('#source-session-recent').click()
            page.locator(f'.source-session-item[data-session-id="{primary["id"]}"]').get_by_role('button', name='Выбрать', exact=True).click()
            page.wait_for_function('(title) => document.getElementById("current-recording-heading").textContent === title', arg=primary['title'])
            assert page.locator('#speaker-editor').is_hidden()
            assert primary['title'] in page.locator('#current-recording-heading').inner_text()
            shot('chooser-reuses-prepared-source')
            no_archive_writes(start)
            # Saving in the final transition guard advances this same source's lineage.
            activate('#open-local-speaker')
            page.wait_for_function("document.getElementById('speaker-editor-status').textContent==='Все изменения сохранены'")
            if not page.locator('.speaker-selection > details:first-of-type').evaluate('e=>e.open'):
                page.get_by_text('Точное редактирование', exact=True).click()
            page.locator('#speaker-editor-selection-start').fill('.05'); page.locator('#speaker-editor-selection-end').fill('.2'); page.locator('#speaker-editor-set-start').click()
            activate('#source-session-mode-archive'); page.locator('#source-session-recent').click()
            page.locator(f'.source-session-item[data-session-id="{primary["id"]}"]').get_by_role('button', name='Выбрать', exact=True).click()
            page.locator('#speaker-unsaved-save').click()
            page.locator('#speaker-editor').wait_for(state='hidden')
            activate('#open-local-speaker')
            page.locator('#speaker-editor').wait_for(state='visible')
            page.wait_for_function("async () => Boolean((await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload)")
            page.wait_for_function("document.getElementById('speaker-editor-status').textContent==='Все изменения сохранены'")
            page.wait_for_load_state('networkidle')
            assert page.evaluate("async()=>(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload.globalCuts[0].endSeconds") == .05
            if not page.locator('.speaker-selection > details:first-of-type').evaluate('e=>e.open'):
                page.get_by_text('Точное редактирование', exact=True).click()
            page.locator('#speaker-editor-selection-start').fill('.08'); page.locator('#speaker-editor-selection-end').fill('.2'); page.locator('#speaker-editor-set-start').click()
            activate('#open-local-announcement'); page.locator('#speaker-unsaved-save').click()
            page.locator('#announcement-processor-card').wait_for(state='visible')
            page.wait_for_function("!document.getElementById('processor-run').disabled")
            page.locator('#processor-run').click()
            page.wait_for_function("!document.getElementById('processor-result').hidden", timeout=60000)
            bridge.stdin.write('{"action":"snapshot"}\n'); bridge.stdin.flush()
            current_session = json.loads(bridge.stdout.readline())['primary']
            revision = page.evaluate("async()=>(await import('./scripts/audio-processor.mjs')).getProcessorResult().provenance.sourceSessionRevision")
            assert revision == current_session['revision']
            print('Acceptance P1: new edits/Blob protected; close/newer intent fence delayed Speaker loads.', flush=True)

        if scenario in ('all', 'announcement-auth'):
            for status in (401, 403):
                for stage in ('session', 'draft', 'part'):
                    open_primary()
                    dirty = status == 403 and stage == 'part'
                    if dirty:
                        if not page.locator('.speaker-selection > details:first-of-type').evaluate('e=>e.open'):
                            page.get_by_text('Точное редактирование', exact=True).click()
                        page.locator('#speaker-editor-selection-start').fill('.1'); page.locator('#speaker-editor-selection-end').fill('.2'); page.locator('#speaker-editor-set-start').click()
                        page.locator('#speaker-editor-render').click()
                        page.wait_for_function("!document.getElementById('speaker-editor-result').hidden", timeout=60000)
                    before = remember(); start = len(trace)
                    # Exercise both canonical mode switching and contextual source opening.
                    target = primary if stage == 'session' else other
                    prefix = f'/v1/source-sessions/{target["id"]}'
                    fault.update(status=status, match=lambda p, prefix=prefix, stage=stage:
                        p == prefix if stage == 'session' else p == prefix+'/drafts/announcement' if stage == 'draft' else p.startswith(prefix+'/blobs/'))
                    if target is primary: activate('#open-local-announcement')
                    else: choose(target, 'announcement', wait_context=stage != 'part')
                    page.wait_for_function("expected => document.getElementById('archive-reconnect-message').textContent===expected", arg=RECONNECT)
                    page.locator('#archive-reconnect').wait_for(state='visible')
                    if target is primary or dirty: preserved(before)
                    shot(f'announcement-{stage}-{status}-keeps-work')
                    activate('#archive-reconnect-login'); page.locator('#source-session-login-cancel').click()
                    if target is primary or dirty: preserved(before)
                    login()
                    if target is primary or dirty: preserved(before)
                    activate('#archive-reconnect-retry')
                    if dirty:
                        page.locator('#speaker-unsaved-dialog').wait_for(state='visible')
                        page.locator('#speaker-unsaved-cancel').click(); preserved(before)
                        assert page.locator('#speaker-editor-status').inner_text() == 'Есть несохранённые изменения'
                        activate('#source-session-mode-archive')
                        page.locator('#source-session-recent').click()
                        page.locator(f'.source-session-item[data-session-id="{target["id"]}"]').get_by_role('button', name='Выбрать', exact=True).click()
                        page.locator('#speaker-unsaved-dialog').wait_for(state='visible')
                        page.locator('#speaker-unsaved-discard').click()
                    if stage == 'part':
                        page.wait_for_function('(title) => document.getElementById("current-recording-heading").textContent === title', arg=target['title'])
                        activate('#open-local-announcement')
                    page.locator('#announcement-processor-card').wait_for(state='visible')
                    page.wait_for_function("document.getElementById('source-session-status').textContent.includes('Целостность исходников проверена')")
                    assert target['title'] in page.locator('#source-session-announcement-identity').inner_text()
                    assert page.locator('#speaker-editor').is_hidden()
                    assert page.locator('#processor-result').is_hidden()  # Reconnect never renders automatically.
                    no_archive_writes(start)
            print('Acceptance P1: Announcement session/draft/part 401+403 preserve work through cancel/reconnect and explicit retry.', flush=True)

        if scenario in ('all', 'archive-auth'):
            for status in (401, 403):
                fault.update(status=status, match=lambda p: p.endswith('/drafts/speaker'))
                start = len(trace)
                page.goto(base_url.rstrip('/')+'/Audio-Archive.html')
                page.wait_for_function("expected => document.getElementById('status').textContent===expected", arg=RECONNECT)
                assert page.locator('#login').is_visible()
                assert page.locator('#logout').is_hidden()
                assert page.locator('#refresh').is_disabled()
                assert page.locator('#matching').inner_text() == 'Список записей не загружен.'
                assert page.locator('#session-list .archive-card').count() == 0
                assert 'Данные загружены' not in page.locator('#status').inner_text()
                shot(f'archive-project-{status}-reconnect')
                login(False)
                page.wait_for_function("document.getElementById('status').textContent.includes('Данные загружены')")
                primary_row = page.locator(f'#session-list [data-session-id="{primary["id"]}"]')
                assert primary['title'] in primary_row.inner_text()
                assert 'Проект' in primary_row.text_content()
                assert page.locator('#login').is_hidden()
                no_archive_writes(start)
            fault.update(status=None, hold=True, match=lambda p: p.endswith('/drafts/speaker'))
            page.locator('#refresh').click(); wait_held()
            page.locator('#logout').click()
            page.wait_for_function("document.getElementById('status').textContent==='Аудиоархив отключён.'")
            release(); page.wait_for_load_state('networkidle')
            assert page.locator('#status').inner_text() == 'Аудиоархив отключён.'
            assert page.locator('#matching').inner_text() == 'Список записей не загружен.'
            assert page.locator('#session-list .archive-card').count() == 0
            print('Acceptance P2: recording-list project state handles 401+403 honestly; late draft response cannot restore logged-out state.', flush=True)
        assert not errors, errors
        assert not blocked, blocked
    finally:
        context.close(); bridge.terminate(); bridge.wait(timeout=10)


if __name__ == '__main__':
    import argparse
    from playwright.sync_api import sync_playwright
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--screenshot-dir', type=Path)
    parser.add_argument('--scenario', default='all', choices=['all','rapid-selection','delayed-speaker','announcement-auth','archive-auth'])
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        check_s09a_acceptance(browser, args.base_url, args.screenshot_dir, args.scenario)
        browser.close()
