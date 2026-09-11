"""S09A operator flows. Synthetic audio, real in-memory gateway, no external access."""
import base64
import io
import json
import math
import struct
import subprocess
import wave
from s09a_edit_modes_smoke import apply_selection

from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]

def fixture(frequency):
    out = io.BytesIO()
    with wave.open(out, 'wb') as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000)
        audio.writeframes(b''.join(struct.pack('<h', int(3000 * math.sin(i / 8000 * 2 * math.pi * frequency))) for i in range(24000)))
    return {'name': 'duplicate.wav', 'mimeType': 'audio/wav', 'buffer': out.getvalue()}

def check_s09a(browser, base_url, screenshot_dir=None):
    base_url = base_url.rstrip('/')
    site = urlparse(base_url); origin = f'{site.scheme}://{site.netloc}'
    bridge = subprocess.Popen(['node', str(ROOT/'tests/safety/archive_management_bridge.mjs')], cwd=ROOT,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    initial = json.loads(bridge.stdout.readline())
    def command(action, **data):
        bridge.stdin.write(json.dumps({'action': action, **data})+'\n'); bridge.stdin.flush()
        result = json.loads(bridge.stdout.readline()); assert 'bridgeError' not in result, result; return result
    context = browser.new_context(viewport={'width': 1280, 'height': 900}, has_touch=True)
    context.add_init_script("sessionStorage.setItem('meser_service_access_v1','granted');window.__MESER_AUDIO_ARCHIVE_GATEWAY__='https://gateway.test';")
    trace, blocked, errors = [], [], []
    fault = {'draft': None, 'part': None}
    def intercept(route):
        req = route.request; target = urlparse(req.url)
        if target.netloc == site.netloc: route.continue_(); return
        if target.netloc != 'gateway.test': blocked.append(req.url); route.abort(); return
        headers = {'Access-Control-Allow-Origin': origin, 'Access-Control-Allow-Credentials': 'true',
            'Access-Control-Allow-Headers': 'Content-Type, X-CSRF-Token, X-Part-SHA256, Idempotency-Key', 'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, OPTIONS'}
        if req.method == 'OPTIONS': route.fulfill(status=204, headers=headers); return
        path = target.path + ('?'+target.query if target.query else '')
        trace.append((req.method, path))
        injected = fault['draft'] if req.method == 'PUT' and path.endswith('/drafts/speaker') else fault['part'] if path.endswith('/content') else None
        if injected:
            if path.endswith('/drafts/speaker'):
                if isinstance(injected, list):
                    injected = fault['draft'].pop(0)
                    if not fault['draft']: fault['draft'] = None
                else: fault['draft'] = None
            else: fault['part'] = None
            route.fulfill(status=injected, content_type='application/json', body='{"error":"Injected failure"}', headers=headers); return
        result = command('request', path=path, method=req.method, headers=req.headers,
            bodyBase64=base64.b64encode(req.post_data_buffer).decode() if req.post_data_buffer else None)
        route.fulfill(status=result['status'], content_type=result.get('type') or 'application/json',
            body=base64.b64decode(result['body']) if result.get('base64') else result['body'], headers=headers)
    context.route('**/*', intercept)  # Installed before every navigation, including authentication.
    page = context.new_page(); page.on('pageerror', lambda e: errors.append(str(e)))
    output = Path(screenshot_dir)/'s09a' if screenshot_dir else None
    if output: output.mkdir(parents=True, exist_ok=True)
    def shot(name):
        if output:
            page.evaluate('document.activeElement?.blur(); scrollTo(0,0)')
            page.screenshot(path=str(output/(name+'.png')), full_page=True)
            if name.startswith(('speaker-edits-help-', 'project-reopened-')):
                page.locator('.speaker-source').scroll_into_view_if_needed()
                page.screenshot(path=str(output/(name+'-viewport.png')))
            elif 'reconnect' in name or 'unsaved' in name:
                page.screenshot(path=str(output/(name+'-viewport.png')))
            if any(part in name for part in ('reconnect', 'unsaved', 'failed', '403')):
                previous=page.viewport_size
                for width in (320,390,768,1280):
                    page.set_viewport_size({'width':width,'height':900})
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    page.screenshot(path=str(output/(name+f'-{width}-viewport.png')))
                page.set_viewport_size(previous)
    def snapshot():
        return page.evaluate("async()=>{const s=(await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState();return {session:s.session,payload:s.payload,draft:s.draft,files:s.files.map(f=>[f.name,f.size]),epoch:s.sourceEpoch,candidate:s.candidate?.candidateType}}")
    def unchanged(before):
        after=snapshot(); assert after['payload']==before['payload']; assert after['files']==before['files']; assert after['epoch']==before['epoch']
    def overflow(): assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), page.viewport_size
    try:
        page.goto(base_url+'/Audio-Editor.html'); page.wait_for_function("document.getElementById('source-session-session-status').textContent.includes('активен')")
        page.locator('#source-session-mode-device').click()
        page.locator('#processor-file').set_input_files([fixture(330),fixture(440)])
        page.wait_for_function("document.querySelectorAll('#import-files li').length===2")
        if not page.locator('#import-zone').evaluate('e=>e.open'):
            page.locator('#import-zone > summary').click()
        for width in (320,390,768,1280):
            page.set_viewport_size({'width':width,'height':900}); overflow(); shot(f'import-{width}')
        writes=len([t for t in trace if t[0]!='GET'])
        page.locator('#open-local-announcement').click()
        page.locator('#processor-run').click(); page.wait_for_function("!document.getElementById('processor-result').hidden", timeout=60000)
        page.wait_for_function("document.getElementById('processor-download').href.startsWith('blob:')")
        assert page.locator('#speaker-editor').is_hidden()
        for width in (320,390,768,1280):
            page.set_viewport_size({'width':width,'height':900}); overflow(); shot(f'announcement-{width}')
        page.locator('#open-local-speaker').click(); page.wait_for_function("!document.getElementById('speaker-editor-render').disabled")
        assert page.locator('#announcement-processor-card').is_hidden()
        assert page.locator('#source-session-announcement-workspace').is_hidden()
        assert not page.locator('#announcement-processor-card').evaluate("el=>[...el.querySelectorAll('button,input,a')].some(e=>e.getClientRects().length)")
        original=snapshot(); assert original['session'].get('id') is None
        page.locator('.speaker-track').nth(1).get_by_role('button',name='Вверх',exact=True).click()
        page.locator('.speaker-track').nth(1).get_by_role('button',name='Исключить из микса',exact=True).click()
        page.locator('.speaker-dsp input').nth(0).check()
        page.get_by_text('Точное редактирование',exact=True).click()
        page.locator('#speaker-editor-selection-start').fill('.2');page.locator('#speaker-editor-selection-end').fill('.8');page.locator('#speaker-editor-set-start').click()
        page.locator('#speaker-editor-selection-end').fill('2.8');page.locator('#speaker-editor-set-end').click()
        page.locator('#speaker-editor-selection-start').fill('1');page.locator('#speaker-editor-selection-end').fill('1.2');apply_selection(page, 'silence')
        edited=snapshot();
        page.locator('#source-session-results-speaker').click();page.locator('#source-session-results-announcement').click()
        assert page.locator('#speaker-editor').is_visible();unchanged(edited)
        assert edited['payload']['trackIds']==list(reversed(original['payload']['trackIds']))
        assert len(edited['payload']['globalCuts'])==2
        page.locator('#speaker-editor-undo').click();page.locator('#speaker-editor-redo').click();unchanged(edited)
        # Zoom + scroll + pointer selection use source coordinates, keyboard extends selection.
        page.locator('#speaker-editor-zoom').fill('4');page.locator('#speaker-editor-zoom').dispatch_event('input')
        wave_control=page.locator('.speaker-track .speaker-waveform').first
        scroll=page.locator('.speaker-track .speaker-waveform-scroll').first
        scroll.evaluate('e=>e.scrollLeft=e.clientWidth')
        box=scroll.bounding_box();page.mouse.move(box['x']+20,box['y']+40);page.mouse.down();page.mouse.move(box['x']+70,box['y']+40);page.mouse.up()
        assert float(page.locator('#speaker-editor-selection-end').input_value())>float(page.locator('#speaker-editor-selection-start').input_value())
        wave_control.focus();page.keyboard.press('Shift+ArrowRight')
        assert page.locator('.speaker-selection-overlay').count()==1
        page.locator('#speaker-editor-zoom-fit').click()
        page.set_viewport_size({'width':320,'height':900})
        help_summary=page.get_by_text('Как работают Solo, Mute и обработка звука',exact=True)
        page.evaluate("""() => {
          window.__s09aTouchTrace = [];
          for (const type of ['touchstart','touchend','pointerdown','pointerup','pointercancel','click'])
            document.addEventListener(type, e => window.__s09aTouchTrace.push({type, target:e.target.tagName, id:e.target.id, x:e.clientX, y:e.clientY}), {capture:true, once:true});
        }""")
        help_summary.scroll_into_view_if_needed();help_summary.tap()
        try:
            page.get_by_text('Уменьшает разницу между тихими и громкими фрагментами речи.',exact=False).wait_for(state='visible')
        except Exception:
            print('S09A touch help failure:', page.evaluate('window.__s09aTouchTrace'), flush=True)
            raise
        page.locator('#speaker-editor-selection-start').fill('0')
        page.locator('#speaker-editor-selection-end').fill('0')
        scroll.scroll_into_view_if_needed();box=scroll.bounding_box()
        assert scroll.evaluate('(e)=>{const r=e.getBoundingClientRect();return e.contains(document.elementFromPoint(r.x+20,r.y+r.height*.7))}'), 'Sticky transport covers the touch selection target'
        assert scroll.evaluate('(e)=>{const r=e.getBoundingClientRect();return !document.elementFromPoint(r.x+20,r.y+r.height*.7).closest(".speaker-boundary")}'), 'Select the waveform body, below the draggable flags'
        touch=context.new_cdp_session(page)
        touch.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':box['x']+20,'y':box['y']+box['height']*.7}]})
        touch.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':box['x']+70,'y':box['y']+box['height']*.7}]})
        touch.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
        assert float(page.locator('#speaker-editor-selection-end').input_value())>float(page.locator('#speaker-editor-selection-start').input_value())
        touch.detach()
        page.locator('.speaker-track').first.get_by_role('button',name='S · Solo').click();unchanged(edited)
        assert page.locator('.speaker-track.is-solo').count()==1
        for width in (320,390,768,1280):
            page.set_viewport_size({'width':width,'height':900});overflow();shot(f'speaker-edits-help-{width}')
        page.locator('#speaker-editor-render').click();page.wait_for_function("!document.getElementById('speaker-editor-result').hidden",timeout=60000)
        assert page.locator('#speaker-editor-download').get_attribute('href').startswith('blob:')
        assert len([t for t in trace if t[0]!='GET'])==writes, trace
        local_url=page.locator('#speaker-editor-download').get_attribute('href')
        # Unsaved transition: cancel, failed save, then reconnect all preserve the same project.
        page.locator('#open-local-announcement').click();page.locator('#speaker-unsaved-dialog').wait_for(state='visible');shot('unsaved-cancel')
        page.locator('#speaker-unsaved-cancel').click();unchanged(edited)
        assert page.locator('#open-local-announcement').evaluate('e=>e===document.activeElement')
        fault['draft']=503
        page.locator('#open-local-announcement').click();page.locator('#speaker-unsaved-save').click();page.locator('#speaker-local-save-confirm').click()
        page.wait_for_function("document.getElementById('speaker-editor-status').textContent.includes('Не удалось сохранить')")
        unchanged(edited);assert page.locator('#speaker-editor').is_visible();shot('sources-finalized-project-failed')
        sessions=command('snapshot')['sessions'];assert len(sessions)==len(initial['sessions'])+1
        source=next(s for s in sessions if s['title']=='duplicate')
        assert source['workflows']['speaker']['currentDraft'] is None
        ingestion_writes=sum(path=='/v1/source-sessions/ingestions' for method,path in trace if method=='POST')
        fault['draft']=[401,403]
        page.locator('#speaker-editor-save').click();page.locator('#source-session-login-dialog').wait_for(state='visible')
        page.locator('#source-session-password').fill('local-test-password');page.locator('#source-session-login-form button[type=submit]').click()
        page.wait_for_function("document.getElementById('speaker-editor-status').textContent.includes('Подключение к аудиоархиву истекло')")
        assert page.locator('#source-session-login-dialog').is_hidden();unchanged(edited);shot('repeated-403-no-login-loop')
        page.locator('#speaker-editor-save').click();page.locator('#source-session-login-dialog').wait_for(state='visible')
        page.locator('#source-session-login-cancel').click();unchanged(edited)
        page.wait_for_function("!document.getElementById('speaker-editor-save').disabled")
        page.locator('#speaker-editor-save').click();page.locator('#source-session-login-dialog').wait_for(state='visible');unchanged(edited);shot('reconnect')
        page.locator('#source-session-password').fill('incorrect-password');page.locator('#source-session-login-form button[type=submit]').click()
        page.wait_for_function("document.getElementById('source-session-password').value==='' ")
        assert page.locator('#source-session-login-dialog').is_visible();unchanged(edited)
        page.locator('#source-session-password').fill('local-test-password');page.locator('#source-session-login-form button[type=submit]').click()
        page.wait_for_function("document.getElementById('speaker-editor-status').textContent==='Все изменения сохранены'")
        saved=snapshot();assert saved['session']['id']==source['id'];assert saved['draft']['draftRevision']==1
        assert sum(path=='/v1/source-sessions/ingestions' for method,path in trace if method=='POST')==ingestion_writes
        assert page.locator('#speaker-editor-download').get_attribute('href')==local_url
        assert page.locator('#speaker-editor-archive-save').is_disabled()
        page.locator('.speaker-track').first.get_by_role('button',name='M · Mute').click()
        assert page.locator('#speaker-editor-status').inner_text()=='Все изменения сохранены'
        shot('project-saved-local-result-retained')
        page.locator('#speaker-editor-render').click();page.wait_for_function("!document.getElementById('speaker-editor-archive-save').disabled",timeout=60000)
        page.locator('#speaker-editor-archive-save').click();page.locator('#speaker-editor-save-submit').click()
        page.wait_for_function("document.getElementById('speaker-editor-save-status').textContent.includes('сохранена')",timeout=60000)
        page.locator('#speaker-editor-save-dialog').wait_for(state='hidden');shot('final-version-saved')
        # Expired part downloads reconnect without touching the active montage or its local result.
        before_download = snapshot(); fault['part'] = 401
        page.locator('#source-session-results-speaker').click()
        output_card = page.locator('#source-session-results-speaker-list .result-archive-item').filter(has_text='duplicate').first
        output_card.get_by_role('button',name='Прослушать',exact=True).click()
        page.wait_for_function("document.getElementById('source-session-results-status').textContent.includes('Подключение к аудиоархиву истекло')")
        unchanged(before_download);shot('part-download-reconnect-keeps-project')
        page.locator('#archive-reconnect-login').click()
        page.locator('#source-session-password').fill('local-test-password');page.locator('#source-session-login-form button[type=submit]').click()
        page.locator('#source-session-login-dialog').wait_for(state='hidden')
        page.locator('#archive-reconnect-retry').click()
        page.wait_for_function("document.getElementById('source-session-results-status').textContent==='Файл проверен и готов к воспроизведению.'")
        unchanged(before_download)
        # Reopening retrieves canonical files/current project, no mutation or file picker.
        start=len(trace);page.goto(base_url+f'/Audio-Editor.html?session={source["id"]}&workflow=speaker')
        page.wait_for_function("document.getElementById('speaker-editor-status').textContent==='Все изменения сохранены'")
        reopened=snapshot();assert reopened['payload']==saved['payload'];assert all(method=='GET' for method,path in trace[start:])
        for width in (320,390,768,1280):
            page.set_viewport_size({'width':width,'height':900});overflow();shot(f'project-reopened-{width}')
        # Save-and-continue waits for the confirmed project; explicit discard and close cancellation are distinct.
        page.get_by_text('Точное редактирование',exact=True).click()
        page.locator('#speaker-editor-selection-start').fill('.3');page.locator('#speaker-editor-selection-end').fill('.8');page.locator('#speaker-editor-set-start').click()
        page.locator('#open-local-announcement').click();page.locator('#speaker-unsaved-save').click()
        page.wait_for_function("!document.getElementById('announcement-processor-card').hidden")
        assert page.locator('#speaker-editor').is_hidden()
        assert command('snapshot')['sessions'][-1] is not None
        page.goto(base_url+f'/Audio-Editor.html?session={source["id"]}&workflow=speaker')
        page.wait_for_function("document.getElementById('speaker-editor-status').textContent==='Все изменения сохранены'")
        page.get_by_text('Точное редактирование',exact=True).click();page.locator('#speaker-editor-selection-start').fill('.4');page.locator('#speaker-editor-selection-end').fill('.8');page.locator('#speaker-editor-set-start').click()
        page.locator('#speaker-editor-close').click();page.locator('#speaker-unsaved-cancel').click();assert page.locator('#speaker-editor').is_visible()
        page.locator('#speaker-editor-close').click();page.locator('#speaker-unsaved-discard').click();assert page.locator('#speaker-editor').is_hidden()
        page.goto(base_url+'/Audio-Archive.html');page.wait_for_function("document.getElementById('status').textContent.includes('Данные загружены')")
        assert page.locator('#project-list').get_by_text('duplicate',exact=True).count()==1
        for width in (320,390,768,1280):
            page.set_viewport_size({'width':width,'height':900});overflow();shot(f'archive-{width}')
        assert not errors, errors
        assert not blocked, blocked
        print('S09A browser: local processing, exact project save/retry/reconnect, result save/reopen, 4 widths passed.')
    finally:
        context.close();bridge.terminate();bridge.wait(timeout=10)

if __name__=='__main__':
    import argparse
    from playwright.sync_api import sync_playwright
    args=argparse.ArgumentParser();args.add_argument('--base-url',default='http://127.0.0.1:8000');args.add_argument('--screenshot-dir',type=Path);args=args.parse_args()
    with sync_playwright() as p:
        browser=p.chromium.launch();check_s09a(browser,args.base_url,args.screenshot_dir);browser.close()
