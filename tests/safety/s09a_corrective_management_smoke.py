"""Corrective library/deletion regressions using the actual in-memory gateway."""
import base64
import json
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]


def check_s09a_corrective_management(browser, base_url, screenshot_dir=None):
    site = urlparse(base_url)
    bridge = subprocess.Popen(['node', str(ROOT/'tests/safety/archive_management_bridge.mjs')], cwd=ROOT,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    seed = json.loads(bridge.stdout.readline())
    primary = seed['primary']

    def command(action, **data):
        bridge.stdin.write(json.dumps({'action': action, **data})+'\n'); bridge.stdin.flush()
        result = json.loads(bridge.stdout.readline()); assert 'bridgeError' not in result, result
        return result

    context = browser.new_context(viewport={'width': 1280, 'height': 900})
    context.add_init_script("sessionStorage.setItem('meser_service_access_v1','granted');window.__MESER_AUDIO_ARCHIVE_GATEWAY__='https://gateway.test';")
    blocked, errors, trace, held = [], [], [], []
    fault = {'draft': None, 'list': False, 'hold': None, 'unauthorized': False, 'preview': False}
    headers = {'Access-Control-Allow-Origin': f'{site.scheme}://{site.netloc}', 'Access-Control-Allow-Credentials': 'true',
               'Access-Control-Allow-Headers': 'Content-Type, X-CSRF-Token, X-Part-SHA256, Idempotency-Key',
               'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, OPTIONS'}

    def fulfill(route, result):
        route.fulfill(status=result['status'], content_type=result.get('type') or 'application/json', headers=headers,
                      body=base64.b64decode(result['body']) if result.get('base64') else result['body'])

    def intercept(route):
        request = route.request; target = urlparse(request.url)
        if target.netloc == site.netloc: route.continue_(); return
        if target.netloc != 'gateway.test': blocked.append(request.url); route.abort(); return
        if request.method == 'OPTIONS': route.fulfill(status=204, headers=headers); return
        path = target.path+('?' + target.query if target.query else '')
        trace.append((request.method, path))
        if fault['list'] and target.path == '/v1/source-sessions':
            fulfill(route, {'status': 503, 'body': '{}'}); return
        if fault['unauthorized'] and request.method == 'POST' and target.path.endswith('/delete'):
            fault['unauthorized'] = False; fulfill(route, {'status': 403, 'body': '{}'}); return
        if fault['draft'] == 'failed' and path.endswith('/drafts/speaker'):
            fulfill(route, {'status': 503, 'body': '{}'}); return
        result = command('request', path=path, method=request.method, headers=request.headers,
                         bodyBase64=base64.b64encode(request.post_data_buffer).decode() if request.post_data_buffer else None)
        if fault['draft'] == 'unsupported' and path.endswith('/drafts/speaker') and result['status'] == 200:
            data = json.loads(base64.b64decode(result['body']))
            if data.get('draft'): data['draft']['payloadSchema'] = 'speaker/unsupported'
            result = {'status': 200, 'body': json.dumps(data)}
        if fault['preview'] and path.endswith('/deletion-preview') and result['status'] == 200:
            data = json.loads(base64.b64decode(result['body'])); data['announcementVersions'] += 1
            result = {'status': 200, 'body': json.dumps(data)}
        if fault['hold'] and fault['hold'](request.method, path):
            fault['hold'] = None; held.append((route, result)); return
        fulfill(route, result)

    context.route('**/*', intercept)  # Isolation is installed before any navigation.
    page = context.new_page(); page.on('pageerror', lambda error: errors.append(str(error)))
    output = Path(screenshot_dir)/'s09a-corrective-management' if screenshot_dir else None
    if output: output.mkdir(parents=True, exist_ok=True)

    def shot(name, selector=None):
        if output:
            if selector:
                page.evaluate('scrollTo(0,0)')
                page.screenshot(path=str(output/(name+'.png')), clip=page.locator(selector).bounding_box(), full_page=True)
            else: page.screenshot(path=str(output/(name+'.png')), full_page=True)
            if selector and 'dialog' in selector:
                previous=page.viewport_size
                for width in (320,390,768,1280):
                    page.set_viewport_size({'width':width,'height':900})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.locator(selector).screenshot(path=str(output/(name+f'-{width}.png')))
                page.set_viewport_size(previous)

    def ready(): page.wait_for_function("document.getElementById('status').textContent.includes('Данные загружены')")

    def detail():
        row = page.locator('#session-list .archive-card').filter(has_text=primary['title'])
        row.locator('.audio-actions > summary').click()
        row.get_by_role('button', name='Сведения о записи').click()
        page.locator('#metadata-title').wait_for()

    def open_editor():
        page.goto(base_url.rstrip('/')+f'/Audio-Editor.html?session={primary["id"]}&workflow=speaker')
        page.wait_for_function("!document.getElementById('speaker-editor-render').disabled")
        page.locator('.speaker-selection details > summary').click()
        page.locator('#speaker-editor-selection-start').fill('0.05')
        page.locator('#speaker-editor-set-start').click()
        page.locator('#speaker-editor-render').click()
        page.wait_for_function("!document.getElementById('speaker-editor-result').hidden", timeout=60000)
        page.evaluate("""async () => {
          const s=(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState();
          window.correctiveWork={files:s.files,payload:JSON.stringify(s.payload),epoch:s.sourceEpoch,blob:s.candidate.blob,url:document.getElementById('speaker-editor-download').href};
        }""")

    def preserved():
        assert page.evaluate("""async () => {
          const s=(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState(), old=correctiveWork;
          return s.sourceEpoch===old.epoch && JSON.stringify(s.payload)===old.payload && s.files.length===old.files.length && s.files.every((f,i)=>f===old.files[i]) &&
            s.candidate?.blob===old.blob && document.getElementById('speaker-editor-download').href===old.url && (await fetch(old.url)).ok;
        }""")

    def source_menu():
        if not page.locator('#import-zone').evaluate('e=>e.open'): page.locator('#import-zone > summary').click()
        page.locator('#source-session-mode-archive').click()
        row = page.locator(f'.source-session-item[data-session-id="{primary["id"]}"]')
        row.locator('.audio-actions > summary').click()
        return row

    def output_delete():
        page.locator('#source-session-results-speaker').click()
        page.locator('#source-session-results-speaker-list .result-archive-item').filter(has_text=primary['title']).get_by_role('button', name='Удалить версию').first.click()
        page.locator('#source-session-delete-dialog').wait_for(state='visible')
        assert page.locator('#source-session-delete-dialog input[type=radio]').count() == 0

    def wait_held():
        end = time.monotonic()+15
        while not held and time.monotonic()<end: page.wait_for_timeout(20)
        assert len(held)==1

    try:
        page.goto(base_url.rstrip('/')+'/Audio-Archive.html'); ready()
        detail()
        assert page.locator('#detail-body').get_by_role('link', name='Продолжить обработку').count() == 1
        for mode in ('failed', 'unsupported'):
            fault['draft'] = mode
            # Detail must read the current draft, never reuse the old successful list projection.
            detail()
            assert page.locator('#detail-body').get_by_role('link', name='Продолжить обработку').count() == 0
            assert 'Последнее сохранение' not in page.locator('#detail-body').inner_text()
            page.locator('#refresh').click(); ready()
            row = page.locator('#session-list .archive-card').filter(has_text=primary['title'])
            assert 'Сохранён проект' not in row.inner_text()
            assert 'Проект не проверен' in row.inner_text()
            assert page.locator('#project-list').get_by_role('link', name='Продолжить обработку').count()==0
            shot('project-'+mode, '#records')
        fault['draft'] = None; page.locator('#refresh').click(); ready()
        for width in (320, 390, 768, 1280):
            page.set_viewport_size({'width':width,'height':900})
            row = page.locator('#session-list .archive-card').filter(has_text=primary['title'])
            summary = row.locator('.audio-actions > summary'); summary.focus(); page.keyboard.press('Enter')
            page.keyboard.press('Tab')
            assert row.get_by_role('button', name='Сведения о записи').evaluate('e=>e===document.activeElement')
            assert row.locator('.audio-actions').evaluate('e=>e.open')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            shot(f'library-menu-{width}', '#records')
            page.keyboard.press('Escape')
            assert summary.evaluate('e=>e===document.activeElement')
            assert not row.locator('.audio-actions').evaluate('e=>e.open')
            if width==1280: assert row.bounding_box()['height'] < 150, row.bounding_box()
            shot(f'library-projects-{width}', '#projects')
            shot(f'library-results-{width}', '#results')
        detail()
        page.locator('#detail').get_by_role('button', name='Удалить всю серию «Для анонс-мейкера»').click()
        page.locator('#delete-dialog').wait_for(state='visible'); fault['preview']=True; before=len(trace)
        page.locator('#delete-submit').click()
        page.wait_for_function("document.getElementById('delete-status').textContent.includes('Результат не подтверждён')")
        assert not [(m,p) for m,p in trace[before:] if m=='POST' and p.endswith('/delete')]
        assert page.locator('#delete-submit').is_disabled()
        fault['preview']=False; page.locator('#delete-cancel').click()
        detail(); page.locator('#detail').get_by_role('button', name='Удалить всю серию «Для анонс-мейкера»').click()
        page.locator('#delete-dialog').wait_for(state='visible'); fault['unauthorized']=True
        page.locator('#delete-submit').click()
        page.wait_for_function("document.getElementById('status').textContent.includes('Подключение к аудиоархиву истекло')")
        assert page.locator('#delete-dialog').is_hidden()
        assert page.locator('#login').is_visible() and page.locator('#refresh').is_disabled()
        assert page.locator('#project-list').inner_text()=='Проекты не загружены.'
        print('Corrective library: fresh supported draft only, honest failure states, compact rows, keyboard/touch menus, fresh deletion dependencies and auth consent at four widths passed.', flush=True)

        page.set_viewport_size({'width':390,'height':900}); open_editor(); preserved()
        output_delete(); shot('version-target', '#source-session-delete-dialog')
        page.locator('#source-session-delete-submit').click()
        page.locator('#source-session-delete-dialog').wait_for(state='hidden'); preserved()
        assert len(command('snapshot')['primary']['workflows']['speaker']['outputs']) == len(primary['workflows']['speaker']['outputs'])-1
        assert page.locator('#speaker-editor-status').get_attribute('data-dirty')=='true'
        # Source deletion must first protect current unsaved work. Cancel means no write/teardown.
        before=len(trace); source_menu().get_by_role('button', name='Удалить исходники', exact=True).click()
        page.locator('#speaker-unsaved-dialog').wait_for(state='visible'); shot('source-unsaved', '#speaker-unsaved-dialog')
        page.locator('#speaker-unsaved-cancel').click(); preserved()
        assert all(method=='GET' for method,_ in trace[before:])
        # Explicit discard permits preview, not a stale mutation after another writer advances revision.
        source_menu().get_by_role('button', name='Удалить исходники', exact=True).click()
        page.locator('#speaker-unsaved-discard').click(); page.locator('#source-session-delete-dialog').wait_for(state='visible')
        command('conflict', id=primary['id']); before=len(trace)
        page.locator('#source-session-delete-confirmation').fill('Удалить исходники, сохранить результаты')
        page.locator('#source-session-delete-submit').click()
        page.wait_for_function("document.getElementById('source-session-delete-status').textContent.includes('изменились')")
        assert page.locator('#source-session-delete-submit').is_disabled(); preserved()
        assert all(method=='GET' for method,_ in trace[before:])
        shot('stale-deletion', '#source-session-delete-dialog'); page.locator('#source-session-delete-cancel').click()

        command('reset'); open_editor(); output_delete(); fault['unauthorized']=True
        page.locator('#source-session-delete-submit').click()
        page.wait_for_function("document.getElementById('source-session-delete-status').textContent.includes('Подключение')")
        preserved(); assert page.locator('#source-session-delete-submit').is_disabled()
        before=len(trace); page.locator('#source-session-delete-cancel').click()
        page.locator('#archive-reconnect-login').click(); page.locator('#source-session-password').fill('local-test-password')
        page.locator('#source-session-login-form button[type=submit]').click()
        page.locator('#source-session-login-dialog').wait_for(state='hidden'); preserved()
        assert page.locator('#archive-reconnect-retry').is_hidden(), 'Destructive consent became a retry action'
        assert not [(m,p) for m,p in trace[before:] if m=='POST' and p.endswith('/delete')]
        # Unknown data never turns into a confirmed empty archive.
        fault['list']=True
        if not page.locator('#import-zone').evaluate('e=>e.open'): page.locator('#import-zone > summary').click()
        page.locator('#source-session-refresh').click()
        page.wait_for_function("document.getElementById('source-session-status').textContent.includes('временно недоступен')")
        assert page.locator('#source-session-results-speaker-count').inner_text()=='—'
        assert 'Результаты не загружены' in page.locator('#source-session-results-speaker-list').inner_text()
        preserved(); shot('unknown-counts', '#source-session-results')
        fault['list']=False
        print('Corrective deletion: concrete target, retained montage/File/Blob after version removal, source unsaved protection, stale revision and expired-consent rejection passed.', flush=True)

        # Hold a successful destructive response, then open new work through the editor API.
        # This models an independent local-source intent arriving during the request.
        command('reset'); open_editor()
        source_menu().get_by_role('button', name='Удалить исходники', exact=True).click()
        page.locator('#speaker-unsaved-discard').click(); page.locator('#source-session-delete-dialog').wait_for(state='visible')
        page.locator('#source-session-delete-confirmation').fill('Удалить исходники, сохранить результаты')
        fault['hold'] = lambda method,path: method=='POST' and path.endswith('/delete')
        page.locator('#source-session-delete-submit').click(); wait_held()
        await_new = page.evaluate("""async () => {
          const editor=await import('./scripts/speaker-editor.mjs'), {localSourceContext}=await import('./scripts/audio-project.mjs');
          const files=editor.getSpeakerSaveState().files;
          await editor.closeSpeakerEditor(true);
          await editor.openSpeakerEditor({session:localSourceContext(files),files});
          const s=editor.getSpeakerSaveState(); window.newWork=s; return s.sourceEpoch;
        }""")
        fulfill(*held.pop()); page.locator('#source-session-delete-dialog').wait_for(state='hidden')
        assert page.evaluate("""async epoch => {
          const s=(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState();
          return s.ready && s.sourceEpoch===epoch && s.files.every((f,i)=>f===newWork.files[i]);
        }""", await_new)
        assert page.locator('#speaker-editor').is_visible()
        assert not errors, errors
        assert not blocked, blocked
        print('Corrective epochs: delayed source deletion cannot close a newer local project; no outbound archive access.', flush=True)
    finally:
        context.close(); bridge.terminate(); bridge.wait(timeout=5)
