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
    fault = {'draft': None, 'list': False, 'hold': None, 'unauthorized': False, 'preview': False, 'wasm': False}
    headers = {'Access-Control-Allow-Origin': f'{site.scheme}://{site.netloc}', 'Access-Control-Allow-Credentials': 'true',
               'Access-Control-Allow-Headers': 'Content-Type, X-CSRF-Token, X-Part-SHA256, Idempotency-Key',
               'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, OPTIONS'}

    def fulfill(route, result):
        route.fulfill(status=result['status'], content_type=result.get('type') or 'application/json', headers=headers,
                      body=base64.b64decode(result['body']) if result.get('base64') else result['body'])

    def intercept(route):
        request = route.request; target = urlparse(request.url)
        if target.netloc == site.netloc:
            if fault['wasm'] and target.path.endswith('ffmpeg-core.wasm'): route.fulfill(status=503, body='Synthetic decoder unavailable')
            else: route.continue_()
            return
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
    page = context.new_page(); archive = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    archive.on('pageerror', lambda error: errors.append(str(error)))
    output = Path(screenshot_dir)/'s09a-corrective-management' if screenshot_dir else None
    if output: output.mkdir(parents=True, exist_ok=True)

    def shot(name, selector=None, target=None):
        target = target or page
        if output:
            if selector:
                target.evaluate('scrollTo(0,0)')
                target.screenshot(path=str(output/(name+'.png')), clip=target.locator(selector).bounding_box(), full_page=True)
            else: target.screenshot(path=str(output/(name+'.png')), full_page=True)
            if selector and 'dialog' in selector:
                previous=target.viewport_size
                for width in (320,390,768,1280):
                    target.set_viewport_size({'width':width,'height':900})
                    assert target.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    target.locator(selector).screenshot(path=str(output/(name+f'-{width}.png')))
                target.set_viewport_size(previous)

    def ready(): archive.wait_for_function("document.getElementById('status').textContent.includes('Данные загружены')")

    def detail():
        archive.goto(base_url.rstrip('/')+f'/Audio-Archive.html?session={primary["id"]}')
        archive.locator('#metadata-title').wait_for()

    def open_editor():
        page.goto(base_url.rstrip('/')+f'/Audio-Editor.html?session={primary["id"]}&workflow=speaker')
        page.wait_for_function("!document.getElementById('speaker-editor-render').disabled")
        page.locator('.speaker-selection details > summary').click()
        page.locator('#speaker-editor-selection-start').fill('0.05')
        page.locator('#speaker-editor-selection-end').fill('0.2')
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

    def output_delete(series=False, workflow='speaker'):
        detail()
        section = archive.locator(f'#detail .workflow-{workflow}')
        if series:
            section.get_by_text('Управление версиями', exact=True).click()
            label = 'Удалить все финальные версии спикерской' if workflow == 'speaker' else 'Удалить все версии для анонс-мейкера'
            section.get_by_role('button', name=label, exact=True).click()
        else:
            row = section.locator('.result-row').first
            row.locator('.audio-actions > summary').click()
            row.get_by_role('button', name='Удалить версию', exact=True).click()
        archive.locator('#delete-dialog').wait_for(state='visible')

    def source_delete():
        detail()
        archive.locator('#detail').get_by_text('Опасная зона', exact=True).click()
        archive.locator('#detail').get_by_role('button', name='Удалить исходные дорожки', exact=True).click()
        archive.locator('#delete-dialog').wait_for(state='visible')

    def wait_held():
        end = time.monotonic()+15
        while not held and time.monotonic()<end: page.wait_for_timeout(20)
        assert len(held)==1

    def deletion_during_preparation(kind):
        command('reset')
        page.goto(base_url.rstrip('/')+f'/Audio-Editor.html?review={kind}#review-preparation')
        if not page.locator('#import-zone').evaluate('e=>e.open'):
            page.locator('#import-zone > summary').click()
        page.locator('#source-session-mode-archive').click()
        row=page.locator(f'.source-session-item[data-session-id="{primary["id"]}"]')
        row.get_by_role('button', name='Открыть финальную обработку спикерской').click()
        page.wait_for_function('window.reviewPreparationPending === true')
        page.evaluate("""async () => {
          const s=(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState();
          window.preparingWork={files:s.files,payload:JSON.stringify(s.payload),epoch:s.sourceEpoch,session:s.session};
        }""")
        assert page.locator('#speaker-editor-render').is_disabled()
        before=len(trace)
        output_delete(series=kind == 'series')
        archive.locator('#delete-submit').click()
        archive.locator('#delete-dialog').wait_for(state='hidden')
        canonical=command('snapshot')['primary']
        assert canonical['revision'] > primary['revision']
        assert canonical['sourceTracks'] == primary['sourceTracks']
        assert len(canonical['workflows']['speaker']['outputs']) == (len(primary['workflows']['speaker']['outputs'])-1 if kind!='series' else 0)
        assert page.evaluate("""async canonical => {
          const s=(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState();
          return reviewPreparationPending && !s.ready && s.session.id===canonical.id && s.session.revision<canonical.revision;
        }""", canonical)
        shot('preparation-'+kind+'-deleted', '#speaker-editor')
        if kind == 'decoder-failure':
            fault['wasm']=True; page.evaluate('window.reviewRejectDecode=true')
        page.evaluate('window.releaseReviewPreparation()')
        if kind == 'decoder-failure':
            page.locator('#speaker-editor-source-retry').wait_for(state='visible')
            assert page.locator('#speaker-editor-render').is_disabled()
            assert primary['sourceTracks'][0]['originalName'] in page.locator('#speaker-editor-status').inner_text()
            fault['wasm']=False
            shot('preparation-delete-decoder-retry', '#speaker-editor')
            page.locator('#speaker-editor-source-retry').click()
        page.wait_for_function("!document.getElementById('speaker-editor-render').disabled", timeout=15000)
        retained=page.evaluate("""async () => {
          const s=(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState(), old=preparingWork;
          return {ready:s.ready,epoch:s.sourceEpoch===old.epoch,payload:JSON.stringify(s.payload)===old.payload,
            files:s.files.length===old.files.length && s.files.every((f,i)=>f===old.files[i]),session:s.session};
        }""")
        assert all(retained[key] for key in ('ready','epoch','payload','files')), retained
        assert retained['session']['id'] == canonical['id'] and retained['session']['revision'] < canonical['revision'], retained
        # Metadata refresh cannot roll revision back or replace source/track identity.
        assert page.evaluate("""async () => {
          const editor=await import('./scripts/speaker-editor.mjs'), original=editor.getSpeakerSaveState();
          const stale=structuredClone(original.session); stale.revision--;
          editor.updateSpeakerSession(stale);
          const changed=structuredClone(original.session); changed.revision++;
          changed.sourceTracks[0].sha256='0'.repeat(64);
          let rejected=false;
          try { editor.updateSpeakerSession(changed); } catch(error) { rejected=error.status===409; }
          const after=editor.getSpeakerSaveState();
          return rejected && JSON.stringify(after.session)===JSON.stringify(original.session) && after.ready &&
            after.sourceEpoch===original.sourceEpoch && after.files.every((f,i)=>f===original.files[i]);
        }""")
        writes=[(m,p) for m,p in trace[before:] if m not in ('GET','HEAD')]
        assert len(writes)==1 and writes[0][0]=='POST' and writes[0][1].endswith('/delete'), writes
        assert page.locator('#speaker-editor-source-retry').is_hidden()
        shot('preparation-'+kind+'-ready', '#speaker-editor')
        print(f'PR36 preparation/{kind}: actual decode held; Archive deletion succeeded; exact Files/order/payload/epoch retained in Editor while canonical revision advanced; ready with one delete write.', flush=True)

    # Hold only the first real native decode completion, not gateway responses or editor state.
    page.add_init_script("""(() => {
      if (location.hash !== '#review-preparation') return;
      const decode=AudioContext.prototype.decodeAudioData;
      let hold=true;
      AudioContext.prototype.decodeAudioData=async function(...args) {
        const buffer=await decode.apply(this,args);
        if (hold) {
          hold=false; window.reviewPreparationPending=true;
          await new Promise(resolve => { window.releaseReviewPreparation=() => { window.reviewPreparationPending=false; resolve(); }; });
        }
        if (window.reviewRejectDecode) { window.reviewRejectDecode=false; throw new Error('Synthetic native decode failure'); }
        return buffer;
      };
    })();""")

    try:
        for kind in ('version', 'series', 'decoder-failure'):
            deletion_during_preparation(kind)

        command('reset')
        detail()
        assert archive.locator('#detail-body').get_by_role('link', name='Продолжить обработку').count() == 1
        for mode in ('failed', 'unsupported'):
            fault['draft'] = mode
            # Detail must read the current draft and must never offer a destructive
            # replacement path when the saved project cannot be validated.
            detail()
            body = archive.locator('#detail-body')
            assert body.get_by_role('link', name='Продолжить обработку').count() == 0
            assert 'сохранённый проект не прошёл проверку' in body.inner_text()
            archive.goto(base_url.rstrip('/') + '/Audio-Archive.html'); ready()
            row = archive.locator(f'#session-list .archive-card[data-session-id="{primary["id"]}"]')
            assert 'Сохранённый проект недоступен' in row.inner_text()
            assert row.get_by_role('button', name='Открыть запись', exact=True).count() == 1
            shot('project-' + mode, '#records', archive)
        fault['draft'] = None

        # The replacement archive model is one compact recordings list leading to
        # a dedicated recording screen; both surfaces remain usable at all widths.
        for width in (320, 390, 768, 1280):
            archive.set_viewport_size({'width': width, 'height': 900})
            archive.goto(base_url.rstrip('/') + '/Audio-Archive.html'); ready()
            row = archive.locator(f'#session-list .archive-card[data-session-id="{primary["id"]}"]')
            assert archive.evaluate('document.documentElement.scrollWidth<=innerWidth')
            if width == 1280:
                assert row.bounding_box()['height'] < 220, row.bounding_box()
            open_button = row.get_by_role('button', name='Открыть запись', exact=True)
            open_button.focus()
            assert open_button.evaluate('e=>e===document.activeElement')
            open_button.click()
            archive.locator('#metadata-title').wait_for()
            assert archive.locator('#archive-index').is_hidden()
            assert archive.locator('#detail').is_visible()
            assert archive.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert archive.locator('#detail-body .workflow-announcement').is_visible()
            assert archive.locator('#detail-body .workflow-speaker').is_visible()
            shot(f'record-detail-{width}', '#detail', archive)
            archive.locator('#detail-close').click()
            assert archive.locator('#archive-index').is_visible()
            assert archive.locator('#detail').is_hidden()
            assert 'session=' not in archive.url

        archive.set_viewport_size({'width': 1280, 'height': 900})
        # A fresh dependency mismatch must reject deletion before the write.
        output_delete(series=True, workflow='announcement')
        fault['preview'] = True
        before = len(trace)
        archive.locator('#delete-submit').click()
        archive.wait_for_function("document.getElementById('delete-status').textContent.includes('Результат не подтверждён')")
        assert not [(method, path) for method, path in trace[before:] if method == 'POST' and path.endswith('/delete')]
        assert archive.locator('#delete-submit').is_disabled()
        fault['preview'] = False
        archive.locator('#delete-cancel').click()

        # Expired authorization clears the detail and destructive consent; it does
        # not silently retry the write after reconnecting.
        output_delete(series=True, workflow='announcement')
        fault['unauthorized'] = True
        before = len(trace)
        archive.locator('#delete-submit').click()
        archive.wait_for_function("document.getElementById('status').textContent.includes('Подключение к аудиоархиву истекло')")
        assert archive.locator('#delete-dialog').is_hidden()
        assert archive.locator('#login').is_visible() and archive.locator('#refresh').is_disabled()
        assert archive.locator('#matching').inner_text() == 'Список записей не загружен.'
        archive.locator('#login').click()
        archive.locator('#password').fill('local-test-password')
        archive.locator('#login-form button[type=submit]').click()
        archive.locator('#login-dialog').wait_for(state='hidden')
        ready()
        assert len([(method, path) for method, path in trace[before:] if method == 'POST' and path.endswith('/delete')]) == 1
        print('Corrective archive: only validated projects can continue; list/detail navigation, responsive layout, fresh deletion dependencies and expired consent passed.', flush=True)

        page.set_viewport_size({'width': 390, 'height': 900})
        command('reset')
        open_editor()
        preserved()

        # Version removal now belongs to the recording detail in the archive. An
        # already-open Editor keeps its exact local Files, recipe, epoch and Blob.
        output_delete()
        shot('version-target', '#delete-dialog', archive)
        archive.locator('#delete-submit').click()
        archive.locator('#delete-dialog').wait_for(state='hidden')
        preserved()
        assert len(command('snapshot')['primary']['workflows']['speaker']['outputs']) == len(primary['workflows']['speaker']['outputs']) - 1
        assert page.locator('#speaker-editor-status').get_attribute('data-dirty') == 'true'

        # Cancelling source removal from the Archive performs no write and cannot
        # disturb unsaved montage work in the separate Editor screen.
        before = len(trace)
        source_delete()
        shot('source-delete', '#delete-dialog', archive)
        archive.locator('#delete-cancel').click()
        preserved()
        assert all(method == 'GET' for method, _ in trace[before:])

        # A concurrent revision change invalidates the freshly reviewed target.
        source_delete()
        command('conflict', id=primary['id'])
        before = len(trace)
        archive.locator('#delete-submit').click()
        archive.wait_for_function("document.getElementById('delete-status').textContent.includes('изменились')")
        assert archive.locator('#delete-submit').is_disabled()
        preserved()
        assert all(method == 'GET' for method, _ in trace[before:])
        shot('stale-deletion', '#delete-dialog', archive)
        archive.locator('#delete-cancel').click()

        command('reset')
        open_editor()
        output_delete()
        fault['unauthorized'] = True
        archive.locator('#delete-submit').click()
        archive.wait_for_function("document.getElementById('status').textContent.includes('Подключение')")
        preserved()
        assert archive.locator('#delete-dialog').is_hidden()
        before = len(trace)
        archive.locator('#login').click()
        archive.locator('#password').fill('local-test-password')
        archive.locator('#login-form button[type=submit]').click()
        archive.locator('#login-dialog').wait_for(state='hidden')
        ready()
        preserved()
        assert not [(method, path) for method, path in trace[before:] if method == 'POST' and path.endswith('/delete')]

        # Unknown list data remains unknown in Editor and is never presented as a
        # confirmed empty result set for the current recording.
        fault['list'] = True
        if not page.locator('#import-zone').evaluate('e=>e.open'):
            page.locator('#import-zone > summary').click()
        page.locator('#source-session-refresh').click()
        page.wait_for_function("document.getElementById('source-session-status').textContent.includes('временно недоступен')")
        assert page.locator('#source-session-results-speaker-count').inner_text() == '—'
        assert 'Результаты не загружены' in page.locator('#source-session-results-speaker-list').inner_text()
        preserved()
        shot('unknown-counts', '#source-session-results')
        fault['list'] = False
        print('Corrective deletion: Archive owns destructive actions; current Editor work survives version/source removal, stale revision and reconnect paths.', flush=True)

        # A delayed Archive deletion response cannot close newer local work opened
        # through the Editor API in the other page.
        command('reset')
        open_editor()
        source_delete()
        fault['hold'] = lambda method, path: method == 'POST' and path.endswith('/delete')
        archive.locator('#delete-submit').click()
        wait_held()
        await_new = page.evaluate("""async () => {
          const editor=await import('./scripts/speaker-editor.mjs'), {localSourceContext}=await import('./scripts/audio-project.mjs');
          const files=editor.getSpeakerSaveState().files;
          await editor.closeSpeakerEditor(true);
          await editor.openSpeakerEditor({session:localSourceContext(files),files});
          const s=editor.getSpeakerSaveState(); window.newWork=s; return s.sourceEpoch;
        }""")
        fulfill(*held.pop())
        archive.locator('#delete-dialog').wait_for(state='hidden')
        assert page.evaluate("""async epoch => {
          const s=(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState();
          return s.ready && s.sourceEpoch===epoch && s.files.every((f,i)=>f===newWork.files[i]);
        }""", await_new)
        assert page.locator('#speaker-editor').is_visible()
        assert not errors, errors
        assert not blocked, blocked
        print('Corrective epochs: delayed Archive source deletion cannot close newer local Editor work; no outbound archive access.', flush=True)
    finally:
        context.close(); bridge.terminate(); bridge.wait(timeout=5)
