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
    context.add_init_script("sessionStorage.setItem('meser_service_access_v1','granted');window.__MESER_AUDIO_ARCHIVE_GATEWAY__='https://gateway.test';")
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

    def choose(session, workflow):
        if not page.locator('#import-zone').evaluate('e=>e.open'): page.locator('#import-zone > summary').click()
        page.locator('#source-session-mode-archive').click()
        label = 'Открыть финальную обработку спикерской' if workflow == 'speaker' else 'Редактировать для анонс-мейкера'
        page.locator(f'.source-session-item[data-session-id="{session["id"]}"]').get_by_role('button', name=label, exact=True).click()

    def login(editor=True):
        if editor:
            page.locator('#archive-reconnect-login').click()
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
        if scenario in ('all', 'delayed-speaker'):
            open_primary()
            start = len(trace)
            fault.update(match=lambda p: p.startswith(f'/v1/source-sessions/{other["id"]}/blobs/'), hold=True)
            choose(other, 'speaker'); wait_held()
            assert page.locator('#speaker-editor').is_visible()
            if not page.locator('.speaker-selection details').evaluate('e=>e.open'):
                page.get_by_text('Точное редактирование', exact=True).click()
            page.locator('#speaker-editor-selection-start').fill('.05'); page.locator('#speaker-editor-selection-end').fill('.2'); page.locator('#speaker-editor-set-start').click()
            page.locator('#speaker-editor-render').click()
            page.wait_for_function("!document.getElementById('speaker-editor-result').hidden", timeout=60000)
            changed = remember()
            release()
            page.locator('#speaker-unsaved-dialog').wait_for(state='visible')
            shot('delayed-source-new-edits-protected')
            page.locator('#speaker-unsaved-cancel').click(); preserved(changed)
            assert changed['payload']['globalCuts'][0]['endSeconds'] == .05
            fault['hold'] = True
            choose(other, 'speaker'); wait_held()
            page.locator('#speaker-editor-close').click()
            page.locator('#speaker-unsaved-discard').click()
            page.locator('#speaker-editor').wait_for(state='hidden')
            release(); page.wait_for_load_state('networkidle')
            assert page.locator('#speaker-editor').is_hidden()
            assert page.evaluate("async()=>!(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().session")
            assert page.locator('#speaker-unsaved-dialog').is_hidden()
            shot('closed-work-rejects-delayed-source')
            no_archive_writes(start)
            # A newer source/mode intent must also win over an earlier held download.
            open_primary(False)
            fault.update(match=lambda p: p.startswith(f'/v1/source-sessions/{other["id"]}/blobs/'), hold=True)
            choose(other, 'speaker'); wait_held()
            page.locator('#open-local-announcement').click()
            page.locator('#announcement-processor-card').wait_for(state='visible')
            release(); page.wait_for_load_state('networkidle')
            assert page.locator('#speaker-editor').is_hidden()
            assert primary['title'] in page.locator('#source-session-announcement-identity').inner_text()
            # Saving in the final transition guard advances this same source's lineage.
            # Reopening must use the newly saved payload, never the previously fetched draft.
            open_primary(False)
            if not page.locator('.speaker-selection details').evaluate('e=>e.open'):
                page.get_by_text('Точное редактирование', exact=True).click()
            page.locator('#speaker-editor-selection-start').fill('.05'); page.locator('#speaker-editor-selection-end').fill('.2'); page.locator('#speaker-editor-set-start').click()
            choose(primary, 'speaker')
            page.locator('#speaker-unsaved-save').click()
            page.wait_for_function("document.getElementById('speaker-editor-status').textContent==='Все изменения сохранены'")
            page.wait_for_load_state('networkidle')
            assert page.evaluate("async()=>(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().payload.globalCuts[0].endSeconds") == .05
            if not page.locator('.speaker-selection details').evaluate('e=>e.open'):
                page.get_by_text('Точное редактирование', exact=True).click()
            page.locator('#speaker-editor-selection-start').fill('.08'); page.locator('#speaker-editor-selection-end').fill('.2'); page.locator('#speaker-editor-set-start').click()
            page.locator('#open-local-announcement').click(); page.locator('#speaker-unsaved-save').click()
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
                        if not page.locator('.speaker-selection details').evaluate('e=>e.open'):
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
                    if stage == 'session': page.locator('#open-local-announcement').click()
                    else: choose(target, 'announcement')
                    page.wait_for_function("expected => document.getElementById('archive-reconnect-message').textContent===expected", arg=RECONNECT)
                    page.locator('#archive-reconnect').wait_for(state='visible')
                    preserved(before)
                    shot(f'announcement-{stage}-{status}-keeps-work')
                    page.locator('#archive-reconnect-login').click(); page.locator('#source-session-login-cancel').click()
                    preserved(before)
                    login(); preserved(before)
                    page.locator('#archive-reconnect-retry').click()
                    if dirty:
                        page.locator('#speaker-unsaved-dialog').wait_for(state='visible')
                        page.locator('#speaker-unsaved-cancel').click(); preserved(before)
                        assert page.locator('#speaker-editor-status').inner_text() == 'Есть несохранённые изменения'
                        choose(target, 'announcement'); page.locator('#speaker-unsaved-discard').click()
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
                assert 'Проекты не загружены.' in page.locator('#project-list').inner_text()
                assert 'Данные загружены' not in page.locator('#status').inner_text()
                shot(f'archive-project-{status}-reconnect')
                login(False)
                page.wait_for_function("document.getElementById('status').textContent.includes('Данные загружены')")
                assert primary['title'] in page.locator('#project-list').inner_text()
                assert page.locator('#login').is_hidden()
                no_archive_writes(start)
            fault.update(status=None, hold=True, match=lambda p: p.endswith('/drafts/speaker'))
            page.locator('#refresh').click(); wait_held()
            page.locator('#logout').click()
            page.wait_for_function("document.getElementById('status').textContent==='Архив отключён.'")
            release(); page.wait_for_load_state('networkidle')
            assert page.locator('#status').inner_text() == 'Архив отключён.'
            assert page.locator('#project-list').inner_text() == 'Проекты не загружены.'
            print('Acceptance P2: project-list 401+403 reconnect honestly; late draft response cannot restore logged-out state.', flush=True)
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
    parser.add_argument('--scenario', default='all', choices=['all','delayed-speaker','announcement-auth','archive-auth'])
    args = parser.parse_args()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        check_s09a_acceptance(browser, args.base_url, args.screenshot_dir, args.scenario)
        browser.close()
