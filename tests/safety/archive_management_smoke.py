"""S09 browser checks against the real in-memory gateway through a local JSON-lines bridge."""
import base64
import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]


def check_archive_management(browser, base_url, screenshot_dir=None):
    base_url = base_url.rstrip('/')  # Retain the site mount when building page URLs.
    parsed_site = urlparse(base_url)
    site_origin = f'{parsed_site.scheme}://{parsed_site.netloc}'
    site_authority = parsed_site.netloc
    bridge = subprocess.Popen(['node', str(ROOT / 'tests/safety/archive_management_bridge.mjs')], cwd=ROOT,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    snapshot = json.loads(bridge.stdout.readline())

    def command(action, **data):
        bridge.stdin.write(json.dumps({'action': action, **data}) + '\n')
        bridge.stdin.flush()
        result = json.loads(bridge.stdout.readline())
        assert 'bridgeError' not in result, result
        return result

    context = browser.new_context(viewport={'width': 390, 'height': 900})
    context.add_init_script("sessionStorage.setItem('meser_service_access_v1', 'granted'); window.__MESER_AUDIO_ARCHIVE_GATEWAY__ = 'https://gateway.test';")
    errors, trace, blocked, held = [], [], [], []
    fault = {'list': False, 'hold': None, 'corrupt': False, 'ambiguous': False}

    def fulfill(route, result):
        data = base64.b64decode(result['body']) if result.get('base64') else result['body']
        if fault['corrupt'] and route.request.url.endswith('/content'):
            data = bytes(len(data))
        route.fulfill(status=result['status'], content_type=result.get('type') or 'application/json', body=data,
                      headers={'Access-Control-Allow-Origin': site_origin, 'Access-Control-Allow-Credentials': 'true',
                               'Access-Control-Allow-Headers': 'Content-Type, X-CSRF-Token', 'Access-Control-Allow-Methods': 'GET, POST, PATCH, PUT, OPTIONS'})

    def route_request(route):
        request = route.request
        parsed = urlparse(request.url)
        if parsed.netloc == site_authority:
            route.continue_()
            return
        if parsed.netloc != 'gateway.test':
            blocked.append(request.url)
            route.abort()
            return
        if request.method == 'OPTIONS':
            fulfill(route, {'status': 204, 'body': '', 'type': 'application/json'})
            return
        path = parsed.path + ('?' + parsed.query if parsed.query else '')
        trace.append((request.method, path, request.post_data))
        if fault['list'] and parsed.path == '/v1/source-sessions':
            fulfill(route, {'status': 503, 'body': '{"error":"Fixture listing unavailable"}', 'type': 'application/json'})
            return
        result = command('request', path=path, method=request.method, headers=request.headers, body=request.post_data)
        if fault['hold'] and fault['hold'] in path:
            held.append((route, result))
            return
        if fault['ambiguous'] and path.endswith('/delete'):
            fault['ambiguous'] = False
            route.abort()
            return
        fulfill(route, result)

    context.route('**/*', route_request)
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))
    output = Path(screenshot_dir) / 's09' if screenshot_dir else None
    if output:
        output.mkdir(parents=True, exist_ok=True)

    def shot(name, selector=None):
        if output:
            # Capture from page origin: avoid offscreen fixed skip-link artifacts in tall element screenshots.
            page.evaluate('scrollTo(0, 0)')
            if selector:
                page.screenshot(path=str(output / f'{name}.png'), clip=page.locator(selector).bounding_box(), full_page=True)
            else:
                page.screenshot(path=str(output / f'{name}.png'), full_page=True)

    def ready():
        page.wait_for_function("document.getElementById('status').textContent.includes('Данные загружены')")

    def load():
        page.goto(base_url + '/Audio-Archive.html')
        ready()

    def readonly(start):
        assert all(method == 'GET' for method, _, _ in trace[start:]), trace[start:]

    def primary_card():
        return page.locator('#session-list .archive-card').filter(has_text='Встреча Й')

    def open_primary():
        primary_card().get_by_role('button', name='Сведения о записи').click()
        page.locator('#metadata-title').wait_for()

    def no_overflow():
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), page.viewport_size
        assert page.locator('main').count() == 1
        for control in page.locator('button, input, select').all():
            if control.is_visible():
                assert control.evaluate('el => el.getBoundingClientRect().width > 0')

    try:
        load()
        # Browser-visible statuses prove that credentialed success, OPTIONS and
        # error responses all pass CORS through the mock's shared fulfill path.
        probe = page.evaluate("""async () => {
            const options = await fetch('https://gateway.test/v1/session', {
                method: 'OPTIONS', credentials: 'include', headers: {'X-CSRF-Token': 'cors-probe'}
            });
            const missing = await fetch('https://gateway.test/v1/cors-probe-not-found', {credentials: 'include'});
            return [options.status, missing.status];
        }""")
        assert probe == [204, 404], probe
        fault['list'] = True
        try:
            unavailable = page.evaluate("""async () => (await fetch(
                'https://gateway.test/v1/source-sessions?lifecycle=incoming', {credentials: 'include'}
            )).status""")
            assert unavailable == 503, unavailable
        finally:
            fault['list'] = False
        assert page.locator('#session-list .archive-card').count() == 2
        page.get_by_text('Фильтры', exact=True).click()
        page.locator('[name=showRemoved]').check()
        assert page.locator('#session-list .archive-card').count() == 3
        assert page.locator('#project-list .archive-card').count() >= 1
        assert not any('ffmpeg' in url.lower() or 'audio-processor' in url for url in page.evaluate('performance.getEntriesByType("resource").map(r => r.name)'))
        start = len(trace)
        for width in (320, 390, 768, 1280):
            page.set_viewport_size({'width': width, 'height': 900})
            page.locator('#records').scroll_into_view_if_needed()
            shot(f'overview-{width}', '#records')
            page.locator('[name="search"]').fill('ИСХОДНИК И\u0306.WAV')
            page.locator('[name=showRemoved]').uncheck()
            page.locator('[name=availableOnly]').check()
            assert page.locator('#session-list .archive-card').count() == 2  # Both matching available sources; workflow status filters were removed by S09A.
            shot(f'combined-filters-{width}', '#records')
            for sort in ('oldest', 'newest', 'title'):
                page.locator('[name="sort"]').select_option(sort)
            page.locator('[name="search"]').fill('совпадений нет')
            assert 'Нет записей' in page.locator('#matching').inner_text()
            shot(f'no-matches-{width}', '#records')
            page.get_by_role('button', name='Сбросить поиск и фильтры').click()
            open_primary()
            assert 'deletedVersions' not in page.locator('#detail').inner_text()
            assert '"deletedVersions": [\n    2' in page.locator('#detail').text_content()
            assert 'Версия 3' in page.locator('#detail').inner_text()
            assert page.locator('#metadata-date').input_value().startswith('2026-09-09T19:30')
            assert page.locator('#detail details').first.get_attribute('open') is None
            shot(f'detail-{width}', '#detail')
            page.locator('#detail').get_by_role('button', name='Удалить всю серию «Для анонс-мейкера»').click()
            page.locator('#delete-dialog').wait_for(state='visible')
            assert 'сохранённые настройки обработки (2)' in page.locator('#delete-retained').inner_text()
            assert 'Спикерская' not in page.locator('#delete-removed').inner_text()
            shot(f'delete-impact-{width}', '#delete-dialog')
            no_overflow()
            page.keyboard.press('Escape')
            assert not page.locator('#delete-dialog').is_visible()
            assert page.locator('#detail').get_by_role('button', name='Удалить всю серию «Для анонс-мейкера»').evaluate('el => el === document.activeElement')
        readonly(start)
        assert not any('/outputs/' in path or path.endswith('/content') for _, path, _ in trace[:])

        # A late detail response must not replace a more recently selected session.
        fault['hold'] = '/v1/source-sessions/' + snapshot['primary']['id']
        primary_card().get_by_role('button', name='Сведения о записи').click()
        page.wait_for_timeout(150)
        assert held
        fault['hold'] = None
        page.locator('#session-list .archive-card').filter(has_text='Новая запись').get_by_role('button', name='Сведения о записи').click()
        page.wait_for_function("document.getElementById('metadata-title')?.value === 'Новая запись'")
        while held:
            fulfill(*held.pop(0))
        page.wait_for_timeout(100)
        assert page.locator('#metadata-title').input_value() == 'Новая запись'
        open_primary()

        # Metadata conflict: preserve entered fields, canonical newer title and original timestamp.
        page.set_viewport_size({'width': 390, 'height': 900})
        page.locator('#metadata-title').fill('Моё исправление')
        command('conflict', id=snapshot['primary']['id'])
        page.get_by_role('button', name='Сохранить метаданные').click()
        page.wait_for_function("document.getElementById('metadata-status').textContent.includes('Введённые значения')")
        assert page.locator('#metadata-title').input_value() == 'Моё исправление'
        assert command('snapshot')['primary']['title'] == 'Изменено в другом окне'
        shot('metadata-conflict-390', '#detail')
        page.get_by_role('button', name='Загрузить актуальные сведения').click()
        page.wait_for_function("document.getElementById('metadata-title')?.value === 'Изменено в другом окне'")
        page.locator('#metadata-title').fill('Исправленная запись')
        page.get_by_role('button', name='Сохранить метаданные').click()
        page.wait_for_function("document.getElementById('metadata-title')?.value === 'Исправленная запись' && !document.querySelector('#detail form button').disabled")
        saved = command('snapshot')['primary']
        assert saved['recordedAt'] == snapshot['primary']['recordedAt']
        patches = [json.loads(body) for method, _, body in trace if method == 'PATCH']
        assert all(set(body['patch']) == {'title', 'recordedAt'} for body in patches)

        # A canonical result is lazily verified; browser decodes real tiny WAV/MP3 fixtures.
        start = len(trace)
        for workflow in ('announcement', 'speaker'):
            page.locator(f'#results-{workflow}').get_by_role('button', name='Прослушать').first.click()
            page.wait_for_function("document.getElementById('audio').src.startsWith('blob:')")
            page.wait_for_function("document.getElementById('audio').readyState >= 1")
            assert page.locator('#download').get_attribute('download') in ('Анонс.wav', 'Спикерская.mp3')
            with page.expect_download() as download:
                page.locator('#download').click()
            assert download.value.failure() is None
            page.locator('#audio').evaluate('async el => { await el.play(); el.pause(); }')
            shot(f'verified-{workflow}-390', '#player')
        readonly(start)
        # Replacing selection fences a delayed result's bytes and object URL.
        fault['hold'] = '/content'
        page.locator('#results-announcement').get_by_role('button', name='Прослушать').first.click()
        page.wait_for_timeout(150)
        assert held
        fault['hold'] = None
        page.locator('#results-speaker').get_by_role('button', name='Прослушать').first.click()
        page.wait_for_function("!document.getElementById('player').hidden && document.getElementById('player-title').textContent.startsWith('Финальные версии спикерских')")
        selected_url = page.locator('#audio').get_attribute('src')
        while held:
            fulfill(*held.pop(0))
        page.wait_for_timeout(150)
        assert page.locator('#audio').get_attribute('src') == selected_url

        # Hold an old response, replace selection, then logout; late bytes cannot revive playback.
        fault['hold'] = '/content'
        page.locator('#results-announcement').get_by_role('button', name='Прослушать').first.click()
        page.wait_for_timeout(200)
        assert held
        page.locator('#logout').click()
        page.wait_for_function("document.getElementById('status').textContent === 'Архив отключён.'")
        fault['hold'] = None
        while held:
            fulfill(*held.pop(0))
        page.wait_for_timeout(200)
        assert not page.locator('#player').is_visible()
        assert page.locator('#audio').get_attribute('src') is None
        page.locator('#login').click()
        page.locator('#password').fill('local-test-password')
        page.locator('#login-form').get_by_role('button', name='Подключить', exact=True).click()
        ready()
        fault['corrupt'] = True
        page.locator('#results-speaker').get_by_role('button', name='Прослушать').first.click()
        page.wait_for_function("document.getElementById('playback-status').textContent.includes('недоступны')")
        assert not page.locator('#player').is_visible()
        fault['corrupt'] = False

        # Archived results and source-deleted outputs survive a page reload.
        page.locator('#session-list .archive-card').filter(has_text='Исправленная запись').get_by_role('button', name='Сведения о записи').click()
        page.locator('#detail').get_by_role('button', name='Убрать из рабочего списка', exact=True).click()
        page.locator('#detail').get_by_role('button', name='Вернуть для обработки', exact=True).wait_for()
        page.locator('#detail').get_by_role('button', name='Удалить исходники', exact=True).click()
        page.locator('#delete-submit').click()
        page.wait_for_function("document.getElementById('detail-body').textContent.includes('Доступных исходных дорожек нет.')")
        load()
        page.locator('#results-speaker').get_by_role('button', name='Прослушать').first.click()
        page.wait_for_function("document.getElementById('audio').src.startsWith('blob:') && document.getElementById('audio').readyState >= 1")
        shot('results-restored-after-source-deletion-390', '#results')

        # Incoming sessions with deleted sources must also reject processing intent.
        page.get_by_text('Фильтры', exact=True).click()
        page.locator('[name=showRemoved]').check()
        page.locator('#session-list .archive-card').filter(has_text='Исправленная запись').get_by_role('button', name='Сведения о записи').click()
        page.locator('#detail').get_by_role('button', name='Вернуть для обработки', exact=True).click()
        page.locator('#detail').get_by_role('button', name='Убрать из рабочего списка', exact=True).wait_for()
        start = len(trace)
        page.goto(base_url + f"/Audio-Editor.html?session={snapshot['primary']['id']}&workflow=speaker")
        page.wait_for_function("document.getElementById('source-session-status').textContent.includes('Новая обработка недоступна')")
        readonly(start)
        shot('ineligible-deleted-sources-390', '#source-session-archive-panel')
        load()

        # Strong purge confirmation; cancel leaves state untouched.
        page.locator('#session-list .archive-card').filter(has_text='Исправленная запись').get_by_role('button', name='Сведения о записи').click()
        page.locator('#detail').get_by_text('Опасная зона', exact=True).click()
        page.locator('#detail').get_by_role('button', name='Удалить запись полностью').click()
        page.locator('#purge-confirmation').fill('да')
        start = len(trace)
        page.locator('#delete-submit').click()
        assert 'точный ID' in page.locator('#delete-status').inner_text()
        readonly(start)
        shot('purge-confirmation-390', '#delete-dialog')
        page.locator('#delete-cancel').click()

        # Ambiguous response to a completed deletion: reconcile, do not claim success/retry blindly.
        page.locator('#detail').get_by_role('button', name='Удалить всю серию «Для анонс-мейкера»').click()
        fault['ambiguous'] = True
        page.locator('#delete-submit').click()
        page.wait_for_function("document.getElementById('delete-status').textContent.includes('Результат не подтверждён')")
        assert page.locator('#delete-submit').is_disabled()
        assert command('snapshot')['primary']['workflows']['announcement']['outputs'] == []
        shot('ambiguous-deletion-390', '#delete-dialog')
        page.locator('#delete-cancel').click()

        # Failed listing counts remain unknown. Late older listing cannot overwrite a newer refresh.
        fault['list'] = True
        page.locator('#refresh').click()
        page.wait_for_function("document.getElementById('status').textContent.includes('Не удалось загрузить оба')")
        assert page.locator('#matching').inner_text() == 'Список записей не загружен.'
        assert page.locator('#session-list .archive-card').count() == 0
        shot('listing-error-390', '#records')
        fault['list'] = False
        page.locator('#refresh').click()
        ready()
        fault['hold'] = '?lifecycle='
        page.locator('#refresh').click()
        page.wait_for_timeout(200)
        assert len(held) == 2
        fault['hold'] = None
        page.locator('#refresh').click()
        ready()
        old_counts = page.locator('#session-list').inner_text()
        while held:
            fulfill(*held.pop(0))
        page.wait_for_timeout(100)
        assert page.locator('#session-list').inner_text() == old_counts

        # Real incomplete transaction states, including pre-finalized ingestion and pending delete.
        command('reset')
        recovery = command('recovery')
        load()
        page.locator('#maintenance-title').click()
        assert page.locator('#operations .archive-card').count() == len(recovery['maintenance']['transactions'])
        pending = page.locator('#operations .archive-card').filter(has_text='Удаление данных')
        assert pending.get_by_role('button').all_text_contents() == ['Продолжить удаление']
        discarding = page.locator('#operations .archive-card').filter(has_text='Возобновление сохранения недоступно')
        assert discarding.get_by_role('button').all_text_contents() == ['Завершить удаление незавершённого сохранения']
        assert 'Запись ещё не определена' in page.locator('#operations').inner_text()
        for width in (320, 390, 768, 1280):
            page.set_viewport_size({'width': width, 'height': 900})
            no_overflow()
            assert page.locator('#maintenance').get_attribute('open') is not None
            shot(f'recovery-{width}', '#maintenance')
            shot(f'contextual-recovery-{width}', '#records')
        page.set_viewport_size({'width': 390, 'height': 900})
        page.on('dialog', lambda dialog: dialog.accept())
        pending.get_by_role('button').click()
        page.wait_for_function("!document.getElementById('operations').textContent.includes('Продолжить удаление')")
        complete = page.locator('#operations .archive-card').filter(has_text='Все части переданы')
        complete.first.get_by_role('button', name='Завершить сохранение').click()
        page.wait_for_function("document.querySelectorAll('#operations .archive-card').length === 5")
        start = len(trace)
        page.locator('#rebuild').click()
        page.wait_for_function("!document.getElementById('rebuild').disabled")
        assert [path for method, path, _ in trace[start:] if method == 'POST'] == ['/v1/maintenance/catalog/rebuild']

        # Direct editor arrival uses existing loaders, no canonical write, and is consumed once after login.
        snapshot = command('reset')
        for workflow in ('announcement', 'speaker'):
            command('auth', value=False)
            start = len(trace)
            page.goto(base_url + f"/Audio-Editor.html?session={snapshot['primary']['id']}&workflow={workflow}")
            page.wait_for_function("document.getElementById('source-session-status').textContent.includes('подключите архив')")
            page.locator('#source-session-authenticate').click()
            page.locator('#source-session-password').fill('local-test-password')
            page.locator('#source-session-login-form').get_by_role('button', name='Подключить', exact=True).click()
            expected = 'Открыта работа «Спикерская»' if workflow == 'speaker' else 'Загружено дорожек:'
            page.wait_for_function('text => document.getElementById("source-session-status").textContent.includes(text)', arg=expected)
            assert 'session=' not in page.url
            assert all(method == 'GET' or path == '/v1/session/login' for method, path, _ in trace[start:]), trace[start:]
            shot(f'editor-arrival-{workflow}-390')
            start = len(trace)
            page.reload()
            page.wait_for_function("document.getElementById('source-session-status').textContent.includes('Показано') || document.getElementById('source-session-list').children.length > 0")
            assert not any('/drafts/' in path or path.endswith('/content') for _, path, _ in trace[start:])
        for session_id, workflow, expected in [(snapshot['archived']['id'], 'speaker', 'Новая обработка недоступна'), ('bad', 'speaker', 'Некорректная ссылка')]:
            start = len(trace)
            page.goto(base_url + f'/Audio-Editor.html?session={session_id}&workflow={workflow}')
            page.wait_for_function('text => document.getElementById("source-session-status").textContent.includes(text)', arg=expected)
            readonly(start)
            shot(f'ineligible-{session_id[:3]}-390', '#source-session-archive-panel')
        command('purge-empty')
        start = len(trace)
        page.goto(base_url + f"/Audio-Editor.html?session={snapshot['empty']['id']}&workflow=announcement")
        page.wait_for_function("document.getElementById('source-session-status').textContent.includes('Запись по ссылке недоступна или удалена')")
        readonly(start)
        shot('ineligible-purged-390', '#source-session-archive-panel')
        assert not errors, errors
        assert not blocked, blocked
        print(f'S09 browser: PASS; 320/390/768/1280; {len(trace)} local gateway requests; no outbound archive access.')
    finally:
        context.close()
        bridge.terminate()
        bridge.wait(timeout=10)
