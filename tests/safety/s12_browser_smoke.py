#!/usr/bin/env python3
"""S12 real protected UI against a disposable synthetic Gateway only."""
import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from s10b_browser_smoke import source


def login(page, url):
    page.goto(f'{url}/login?return=%2FAudio-Archive.html', wait_until='domcontentloaded')
    page.locator('#admin-password').fill('local-test-password')
    page.locator('#admin-access-form button[type=submit]').click()
    page.wait_for_url('**/Audio-Archive.html')


def usage_refresh_regression(page):
    used = {'bytes': 40_000_000_000}
    held = {}
    def response(route):
        payload = route.fetch().json()
        payload.update(usedBytes=used['bytes'], assetCount=1 if used['bytes'] else 0,
                       warning=used['bytes'] >= payload['softLimitBytes'] * payload['warningPercent'] / 100)
        if used.get('hold'):
            held.update(route=route, payload=payload)
            used['hold'] = False
        else:
            route.fulfill(json=payload)
    page.route('**/v1/storage-usage?refresh=1', response)
    page.locator('#archive-usage-refresh').click()
    expect(page.locator('#archive-storage-usage')).to_contain_text('40 GB')
    expect(page.locator('#archive-storage-warning-text')).to_contain_text('40 GB')
    assert not page.locator('#archive-storage-warning').evaluate('(el) => el.hidden')
    used['bytes'] = 0
    page.locator('#archive-usage-refresh').click()
    expect(page.locator('#archive-storage-usage')).to_contain_text('0 MB')
    expect(page.locator('#archive-storage-warning-text')).to_contain_text('0 MB')
    assert page.locator('#archive-storage-warning').evaluate('(el) => el.hidden')
    used.update(bytes=40_000_000_000, hold=True)
    page.locator('#archive-usage-refresh').click()
    for _ in range(100):
        if 'route' in held:
            break
        page.wait_for_timeout(20)
    assert 'route' in held
    used['bytes'] = 0
    page.locator('#archive-usage-refresh').click()
    expect(page.locator('#archive-storage-usage')).to_contain_text('0 MB')
    held['route'].fulfill(json=held['payload'])
    page.wait_for_timeout(100)
    expect(page.locator('#archive-storage-usage')).to_contain_text('0 MB')
    assert page.locator('#archive-storage-warning').evaluate('(el) => el.hidden')
    used['bytes'] = 40_000_000_000
    page.locator('#archive-usage-refresh').click()
    expect(page.locator('#archive-storage-usage')).to_contain_text('40 GB')
    assert not page.locator('#archive-storage-warning').evaluate('(el) => el.hidden')
    # An ordinary list refresh cannot supersede a held explicit recount.
    held.clear()
    used.update(bytes=40_000_000_000, hold=True)
    page.locator('#archive-usage-refresh').click()
    for _ in range(100):
        if 'route' in held:
            break
        page.wait_for_timeout(20)
    assert 'route' in held
    ordinary = []
    def cached(route):
        ordinary.append(True)
        payload = route.fetch().json()
        payload.update(usedBytes=40_000_000_000, warning=True, stale=False)
        route.fulfill(json=payload)
        ordinary.append('done')
    page.route('**/v1/storage-usage', cached)
    page.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}))")
    page.wait_for_timeout(100)
    assert not ordinary, 'ordinary read superseded an in-flight explicit recount'
    held['route'].fulfill(json=held['payload'])
    expect(page.locator('#archive-storage-usage')).to_contain_text('40 GB')
    assert not page.locator('#archive-storage-warning').evaluate('(el) => el.hidden')
    for _ in range(100):
        if ordinary and ordinary[-1] == 'done':
            break
        page.wait_for_timeout(20)
    assert ordinary and ordinary[-1] == 'done'
    page.unroute('**/v1/storage-usage', cached)
    page.unroute('**/v1/storage-usage?refresh=1', response)
    page.locator('#archive-usage-refresh').click()
    expect(page.locator('#archive-storage-usage')).to_contain_text('0 MB')


def manual_storage_regression(page, context, url, output, engine):
    context.request.post(f'{url}/__test/s12-reset')
    page.goto(f'{url}/Audio-Archive.html')
    page.locator('#archive-settings-open').click()
    expect(page.locator('#archive-settings-status')).to_have_text('Настройки загружены.')
    page.locator('#archive-soft-limit').fill('0.000001')
    page.locator('#archive-storage-form button[type=submit]').click()
    expect(page.locator('#archive-settings-status')).to_have_text('Сохранение подтверждено архивом.')
    page.locator('#archive-settings-close').click()
    expect(page.locator('#archive-storage-warning')).to_be_hidden()
    page.locator('#archive-create-open').click()
    page.locator('#archive-create-name').fill('Manual storage threshold regression')
    page.locator('#archive-create-files').set_input_files(source('manual.wav'))
    page.locator('#archive-create-submit').click()
    expect(page.locator('#detail-title')).to_have_text('Manual storage threshold regression')
    page.locator('#detail-close').click()
    expect(page.locator('#archive-storage-warning')).to_be_visible()
    assert not page.locator('#archive-storage-usage').inner_text().startswith('0 MB ·')
    page.screenshot(path=str(output / f'{engine}-usage-after-upload.png'))
    page.get_by_role('button', name='Открыть запись', exact=True).click()
    page.get_by_text('Опасная зона', exact=True).click()
    page.get_by_role('button', name='Удалить исходные дорожки', exact=True).click()
    page.locator('#delete-submit').click()
    expect(page.locator('#delete-dialog')).to_be_hidden()
    page.locator('#detail-close').click()
    expect(page.locator('#archive-storage-warning')).to_be_hidden()
    expect(page.locator('#archive-storage-usage')).to_contain_text('0 MB')
    page.screenshot(path=str(output / f'{engine}-usage-after-delete.png'))


def discard_ui_regression(page, context, url):
    for origin in ['manual', 'zoom_cloud']:
        context.request.post(f'{url}/__test/s12-reset')
        fixture = context.request.post(f'{url}/__test/s12-discard-fixture?origin={origin}')
        assert fixture.ok, fixture.text()
        # A newly opened page discovers the durable discarding claim, without the transfer context.
        page.goto(f'{url}/Audio-Archive.html')
        page.locator('#maintenance-title').click()
        expect(page.locator('#operations article')).to_have_count(1)
        operation = page.locator('#operations article')
        expect(operation.get_by_role('button')).to_have_count(1)
        operation.get_by_role('button', name='Завершить удаление незавершённого сохранения', exact=True).click()
        expect(page.locator('#operations article')).to_have_count(0)
        state = context.request.get(f'{url}/__test/s12-state').json()
        transaction = next(value for path, value in state['files'] if path == f"transactions/ingest-{fixture.json()['transactionId']}.json")
        assert transaction['state'] == 'discarded' and not state['assets']



def attention_diagnostics_regression(page, context, url):
    context.request.post(f'{url}/__test/s12-reset')
    page.add_init_script("window.__attentionErrors=[];addEventListener('unhandledrejection',e=>window.__attentionErrors.push(String(e.reason)))")
    page.goto(f'{url}/Audio-Archive.html')
    expect(page.locator('#attention-status')).to_contain_text('операции: 0.')
    empty = context.request.get(f'{url}/v1/archive-attention').json()
    mode = {'attention': 'hold', 'diagnostics': 'ok'}
    held = []
    diagnostic = {'transactions': [], 'orphans': [{'kind': 'synthetic_orphan', 'releaseId': 'attention-independent-diagnostic'}]}
    current = {'payload': empty}

    def attention(route):
        if mode['attention'] == 'hold':
            held.append(route)
        elif mode['attention'] == 'invalid':
            route.fulfill(json={'snapshot': 'invalid', 'transactions': [{}]})
        elif mode['attention'] == 'error':
            route.fulfill(status=503, json={'error': 'Strict canonical attention unavailable'})
        else:
            route.fulfill(json=current['payload'])

    def diagnostics(route):
        route.fulfill(status=503 if mode['diagnostics'] == 'error' else 200,
                      json={'error': 'diagnostic unavailable'} if mode['diagnostics'] == 'error' else diagnostic)

    def wait_held(count):
        for _ in range(100):
            if len(held) == count:
                break
            page.wait_for_timeout(10)
        assert len(held) == count, 'explicit strict attention joined an obsolete in-flight read'

    page.route('**/v1/archive-attention', attention)
    page.route('**/v1/maintenance/incomplete', diagnostics)
    page.locator('#maintenance-title').click()
    wait_held(1)
    expect(page.locator('#observations')).to_contain_text('attention-independent-diagnostic')
    expect(page.locator('#operations')).to_contain_text('ещё не подтверждены')
    # Canonical attention changes while an earlier read is held. The explicit
    # maintenance action must request a fresh strict projection, never use the
    # lenient diagnostic transactions (which deliberately remain empty).
    fixture = context.request.post(f'{url}/__test/s12-discard-fixture?origin=manual')
    assert fixture.ok, fixture.text()
    current['payload'] = context.request.get(f'{url}/v1/archive-attention').json()
    assert len(current['payload']['transactions']) == 1
    page.locator('#maintenance-refresh').click()
    wait_held(2)
    held[1].fulfill(json=current['payload'])
    expect(page.locator('#attention-status')).to_contain_text('операции: 1.')
    expect(page.locator('#operations article')).to_have_count(1)
    held[0].fulfill(json=empty)
    page.wait_for_load_state('networkidle')
    expect(page.locator('#attention-status')).to_contain_text('операции: 1.')
    expect(page.locator('#operations article')).to_have_count(1)
    for failure in ['error', 'invalid']:
        mode['attention'] = failure
        page.locator('#maintenance-refresh').click()
        expect(page.locator('#attention-status')).to_contain_text('сведения не подтверждены')
        expect(page.locator('#operations')).to_contain_text('ещё не подтверждены')
        expect(page.locator('#operations article')).to_have_count(0)
        expect(page.locator('#observations')).to_contain_text('attention-independent-diagnostic')
    # An attention completion cannot erase a diagnostic error either.
    mode.update(attention='hold', diagnostics='error')
    page.locator('#maintenance-refresh').click()
    wait_held(3)
    expect(page.locator('#observations')).to_contain_text('Не удалось загрузить диагностику')
    held[2].fulfill(json=current['payload'])
    expect(page.locator('#attention-status')).to_contain_text('операции: 1.')
    expect(page.locator('#observations')).to_contain_text('Не удалось загрузить диагностику')
    # The main explicit refresh must also bypass an earlier attention GET.
    mode.update(attention='hold', diagnostics='ok')
    page.locator('#maintenance-refresh').click()
    wait_held(4)
    page.locator('#refresh').click()
    wait_held(5)
    held[4].fulfill(json=current['payload'])
    expect(page.locator('#attention-status')).to_contain_text('операции: 1.')
    held[3].fulfill(json=empty)
    page.wait_for_load_state('networkidle')
    expect(page.locator('#attention-status')).to_contain_text('операции: 1.')
    assert not page.evaluate('window.__attentionErrors'), page.evaluate('window.__attentionErrors')
    page.unroute('**/v1/archive-attention', attention)
    page.unroute('**/v1/maintenance/incomplete', diagnostics)


def isolation_regression(page, context, url):
    import uuid
    # Simulate transports that finish despite AbortSignal; visible UI must still fence them.
    page.add_init_script("""const originalFetch = window.fetch.bind(window);
      window.fetch = (input, options={}) => originalFetch(input,
        String(input).includes('/v1/zoom/') ? {...options, signal:undefined} : options);
      window.__zoomUnhandled=[];
      addEventListener('unhandledrejection', e=>window.__zoomUnhandled.push(String(e.reason)));
    """)
    def wait_held(held):
        for _ in range(200):
            if held:
                return
            page.wait_for_timeout(10)
        raise AssertionError('synthetic barrier not reached')

    def seed():
        context.request.post(f'{url}/__test/s12-reset')
        csrf = context.request.get(f'{url}/v1/session').json()['csrfToken']
        headers = {'Origin': url, 'X-CSRF-Token': csrf}
        settings = context.request.get(f'{url}/v1/archive-settings').json()
        connection = {'connectionId': str(uuid.uuid4()), 'name': 'Isolation B', 'accountId': 'isolation-b',
                      'clientId': 'isolation-client-b', 'clientSecret': 'synthetic-only', 'meetingId': '12345678901'}
        checked = context.request.post(f'{url}/v1/archive-settings/check', headers=headers,
                                      data={'revision': settings['revision'], 'connection': connection})
        assert checked.ok, checked.text()
        result = context.request.post(f'{url}/v1/archive-settings', headers=headers,
            data={'revision': settings['revision'], 'mutationId': str(uuid.uuid4()), 'action': 'save',
                  'connection': connection, 'receipt': checked.json()['receipt']})
        assert result.ok, result.text()
        page.goto(f'{url}/Audio-Archive.html')
        page.locator('#archive-zoom-open').click()
        expect(page.locator('#zoom-occurrences article')).to_have_count(2)
        return headers, connection

    def open_settings():
        page.locator('#archive-zoom-close').click()
        page.locator('#archive-settings-open').click()
        expect(page.locator('#archive-settings-status')).to_have_text('Настройки загружены.')

    for mutation in ['save', 'activate', 'disable', 'delete', 'reload', 'reconcile', 'aba']:
        headers, b = seed()
        held = {}
        def hold_calendar(route):
            if not held:
                payload = route.fetch().json()
                for row in payload['recordings']:
                    row['reason'] = 'OBSOLETE A DETAILS'
                held.update(route=route, payload=payload)
            else:
                route.continue_()
        page.route('**/v1/zoom/calendar?*', hold_calendar)
        page.locator('#zoom-refresh').click()
        wait_held(held)
        open_settings()
        # Closing/reloading immediately clears rows and selection before any response.
        expect(page.locator('#zoom-occurrences article')).to_have_count(0)
        expect(page.locator('#zoom-day-title')).to_have_text('Выберите день')
        a = page.locator('#zoom-connections article').filter(has_text='Synthetic Zoom')
        if mutation == 'save':
            a.get_by_role('button', name='Изменить', exact=True).click()
            page.locator('#zoom-name').fill('Renamed synthetic A')
            page.locator('#zoom-connection-form button[type=submit]').click()
        elif mutation in ['activate', 'aba']:
            page.locator('#zoom-connections article').filter(has_text='Isolation B').get_by_role('button', name='Активировать', exact=True).click()
        elif mutation == 'disable':
            a.get_by_role('button', name='Отключить', exact=True).click()
        elif mutation == 'delete':
            a.get_by_role('button', name='Удалить подключение', exact=True).click()
        elif mutation == 'reload':
            page.locator('#archive-settings-reload').click()
        else:
            settings = context.request.get(f'{url}/v1/archive-settings').json()
            changed = context.request.post(f'{url}/v1/archive-settings', headers=headers,
                data={'revision': settings['revision'], 'mutationId': str(uuid.uuid4()), 'action': 'activate', 'connectionId': b['connectionId'], 'confirmed': True})
            assert changed.ok
            # Stale settings POST conflicts; reconciliation must read current state.
            a.get_by_role('button', name='Активировать', exact=True).click()
        if mutation in ['save', 'activate', 'disable', 'delete', 'aba']:
            expect(page.locator('#archive-settings-status')).to_have_text('Сохранение подтверждено архивом.')
        elif mutation == 'reconcile':
            expect(page.locator('#archive-settings-status')).to_contain_text('Настройки изменились')
            expect(page.locator('#zoom-connections article').filter(has_text='Isolation B')).to_contain_text('Активно')
        if mutation == 'aba':
            a.get_by_role('button', name='Активировать', exact=True).click()
            expect(a).to_contain_text('Активно')
        page.locator('#archive-settings-close').click()
        page.locator('#archive-zoom-open').click()
        if mutation in ['disable', 'delete']:
            expect(page.locator('#archive-zoom-status')).to_contain_text('Активное подключение не настроено')
        else:
            expect(page.locator('#zoom-occurrences article')).to_have_count(2)
        status = page.locator('#archive-zoom-status').inner_text()
        held['route'].fulfill(json=held['payload'])
        page.wait_for_timeout(80)
        assert page.locator('#archive-zoom-status').inner_text() == status
        assert 'OBSOLETE A DETAILS' not in page.locator('#zoom-occurrences').inner_text()
        expect(page.locator('#detail')).to_be_hidden()
        page.unroute('**/v1/zoom/calendar?*', hold_calendar)
        page.locator('#archive-zoom-close').click()

    # Delayed file body/error and old finally must not touch B's new controller.
    for failure in [False, True]:
        headers, b = seed()
        held_file, held_b = {}, {}
        def file_response(route):
            if not held_file:
                held_file.update(route=route, response=route.fetch())
            else:
                route.continue_()
        page.route('**/v1/zoom/imports/*/files/*', file_response)
        page.locator('#zoom-occurrences button').filter(has_text='Импортировать запись').first.click()
        wait_held(held_file)
        open_settings()
        page.locator('#zoom-connections article').filter(has_text='Isolation B').get_by_role('button', name='Активировать', exact=True).click()
        expect(page.locator('#archive-settings-status')).to_have_text('Сохранение подтверждено архивом.')
        page.locator('#archive-settings-close').click()
        page.locator('#archive-zoom-open').click()
        expect(page.locator('#zoom-occurrences article')).to_have_count(2)
        def reserve_b(route):
            held_b.update(route=route, response=route.fetch())
        page.route('**/v1/zoom/imports', reserve_b)
        page.locator('#zoom-occurrences button').filter(has_text='Импортировать запись').first.click()
        wait_held(held_b)
        expect(page.locator('#zoom-stop')).to_be_visible()
        if failure:
            held_file['route'].fulfill(status=503, json={'error': 'OBSOLETE A ERROR'})
        else:
            held_file['route'].fulfill(response=held_file['response'])
        page.wait_for_timeout(80)
        expect(page.locator('#zoom-stop')).to_be_visible()
        assert 'OBSOLETE A' not in page.locator('#archive-zoom-status').inner_text()
        held_b['route'].fulfill(response=held_b['response'])
        expect(page.locator('#zoom-occurrences h4').first).to_contain_text('В Аудиоархиве', timeout=20000)
        state = context.request.get(f'{url}/__test/s12-state').json()
        sessions = [v for path, v in state['files'] if path.startswith('sessions/')]
        assert len(sessions) == 1 and sessions[0]['origin']['kind'] == 'zoom_cloud'
        assert len(state['assets']) == 4, 'stale A uploaded bytes or duplicated B parts'
        expect(page.locator('#detail')).to_be_hidden()
        page.unroute('**/v1/zoom/imports/*/files/*', file_response)
        page.unroute('**/v1/zoom/imports', reserve_b)
        page.locator('#archive-zoom-close').click()
    # Observe an external change on focus; a late A error cannot erase B status.
    headers, b = seed()
    held = {}
    def focus_calendar(route):
        payload = route.fetch().json()
        if not held:
            held.update(route=route)
        else:
            for row in payload['recordings']:
                row['reason'] = 'FRESH CONTEXT'
            route.fulfill(json=payload)
    page.route('**/v1/zoom/calendar?*', focus_calendar)
    page.locator('#zoom-refresh').click()
    wait_held(held)
    settings = context.request.get(f'{url}/v1/archive-settings').json()
    changed = context.request.post(f'{url}/v1/archive-settings', headers=headers,
        data={'revision': settings['revision'], 'mutationId': str(uuid.uuid4()), 'action': 'activate', 'connectionId': b['connectionId'], 'confirmed': True})
    assert changed.ok
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    expect(page.locator('#zoom-occurrences')).to_contain_text('FRESH CONTEXT')
    status = page.locator('#archive-zoom-status').inner_text()
    held['route'].fulfill(status=503, json={'error': 'OBSOLETE A ERROR'})
    page.wait_for_timeout(80)
    assert page.locator('#archive-zoom-status').inner_text() == status
    page.unroute('**/v1/zoom/calendar?*', focus_calendar)
    page.locator('#archive-zoom-close').click()

    # A delayed completed reserve and a detached old Open action cannot open A in B.
    headers, b = seed()
    page.locator('#zoom-occurrences button').filter(has_text='Импортировать запись').first.click()
    expect(page.locator('#zoom-occurrences h4').first).to_contain_text('В Аудиоархиве', timeout=20000)
    page.evaluate("window.__oldZoomAction = [...document.querySelectorAll('#zoom-occurrences button')].find(b=>b.textContent==='Открыть в Аудиоархиве')")
    held = {}
    def stale_calendar(route):
        payload = route.fetch().json()
        payload['recordings'][0]['state'] = 'reserved'
        route.fulfill(json=payload)
    page.route('**/v1/zoom/calendar?*', stale_calendar)
    page.locator('#zoom-refresh').click()
    expect(page.locator('#zoom-occurrences h4').first).to_contain_text('Импорт не завершён')
    def completed_reserve(route):
        held.update(route=route, response=route.fetch())
    page.route('**/v1/zoom/imports', completed_reserve)
    page.locator('#zoom-occurrences button').filter(has_text='Проверить и продолжить').first.click()
    wait_held(held)
    open_settings()
    page.locator('#zoom-connections article').filter(has_text='Isolation B').get_by_role('button', name='Активировать', exact=True).click()
    expect(page.locator('#archive-settings-status')).to_have_text('Сохранение подтверждено архивом.')
    page.locator('#archive-settings-close').click()
    page.unroute('**/v1/zoom/calendar?*', stale_calendar)
    page.locator('#archive-zoom-open').click()
    expect(page.locator('#zoom-occurrences article')).to_have_count(2)
    held['route'].fulfill(response=held['response'])
    page.evaluate('window.__oldZoomAction.click()')
    page.wait_for_timeout(80)
    expect(page.locator('#detail')).to_be_hidden()
    expect(page.locator('#archive-zoom-dialog')).to_be_visible()
    expect(page.locator('#zoom-stop')).to_be_hidden()
    page.unroute('**/v1/zoom/imports', completed_reserve)
    page.locator('#archive-zoom-close').click()

    # Expiry/session invalidation clears an open calendar and fences a pending file.
    headers, b = seed()
    held = {}
    def auth_file(route):
        held.update(route=route, response=route.fetch())
    page.route('**/v1/zoom/imports/*/files/*', auth_file)
    page.locator('#zoom-occurrences button').filter(has_text='Импортировать запись').first.click()
    wait_held(held)
    context.request.post(f'{url}/__test/expire')
    page.dispatch_event('#refresh', 'click')
    expect(page.locator('#zoom-occurrences article')).to_have_count(0)
    expect(page.locator('#zoom-stop')).to_be_hidden()
    held['route'].fulfill(response=held['response'])
    page.wait_for_timeout(80)
    expect(page.locator('#detail')).to_be_hidden()
    state = context.request.get(f'{url}/__test/s12-state').json()
    assert not state['assets']
    page.unroute('**/v1/zoom/imports/*/files/*', auth_file)

    assert not page.evaluate('window.__zoomUnhandled')


def warning_expiry_regression(browser, url, output, engine, errors, delayed=False):
    # Fresh context: use native AbortSignal, not isolation_regression's transport shim.
    context = browser.new_context(viewport={'width': 390, 'height': 900})
    page = context.new_page()
    page.clock.install(time=datetime(2026, 10, 12, 12, tzinfo=timezone.utc))
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.add_init_script("window.__warningUnhandled=[]; addEventListener('unhandledrejection', e=>window.__warningUnhandled.push(String(e.reason)))")
    page.on('dialog', lambda dialog: dialog.accept())
    context.request.post(f'{url}/__test/s12-reset')
    login(page, url)
    page.locator('#archive-zoom-open').click()
    expect(page.locator('#zoom-occurrences article')).to_have_count(2)
    file, warning = {}, {}

    def wait_held(held):
        for _ in range(200):
            if held:
                return
            page.wait_for_timeout(10)
        raise AssertionError('warning expiry barrier missing')

    def hold_file(route):
        file.update(route=route, response=route.fetch())

    def hold_expired_warning(route):
        response = route.fetch()
        assert response.status == 401
        warning.update(route=route, response=response)

    page.route('**/v1/zoom/imports/*/files/*', hold_file)
    page.locator('#zoom-occurrences button').filter(has_text='Импортировать запись').first.click()
    wait_held(file)
    context.request.post(f'{url}/__test/expire')
    if delayed:
        page.route('**/v1/config', hold_expired_warning)
        page.locator('#zoom-stop').click()
        wait_held(warning)
        # Another entry observes expiry first. A new confirmed login/calendar must
        # survive the older warning's delayed 401 and the older import's finally.
        page.dispatch_event('#refresh', 'click')
    else:
        with page.expect_response(lambda r: r.url.endswith('/v1/config') and r.status == 401):
            page.locator('#zoom-stop').click()
    expect(page.locator('#zoom-occurrences article')).to_have_count(0)
    expect(page.locator('#zoom-days button')).to_have_count(0)
    expect(page.locator('#zoom-day-title')).to_have_text('Выберите день')
    expect(page.locator('#zoom-stop')).to_be_hidden()
    if not delayed:
        expect(page.locator('#archive-zoom-status')).to_contain_text('сессия истекла')
    page.locator('#archive-zoom-close').click()
    expect(page.locator('#login')).to_be_visible()
    if delayed:
        page.unroute('**/v1/config', hold_expired_warning)
    page.locator('#login').click()
    page.locator('#password').fill('local-test-password')
    page.locator('#login-form button[type=submit]').click()
    expect(page.locator('#login-dialog')).not_to_be_visible()
    page.locator('#archive-zoom-open').click()
    expect(page.locator('#zoom-occurrences article')).to_have_count(2)
    if delayed:
        warning['route'].fulfill(response=warning['response'])
    file['route'].fulfill(response=file['response'])
    page.wait_for_timeout(100)
    expect(page.locator('#zoom-occurrences article')).to_have_count(2)
    expect(page.locator('#archive-zoom-status')).not_to_contain_text('сессия истекла')
    expect(page.locator('#zoom-stop')).to_be_hidden()
    assert not context.request.get(f'{url}/__test/s12-state').json()['assets']
    assert not page.evaluate('window.__warningUnhandled')
    page.screenshot(path=str(output / f'{engine}-warning-expiry-{"delayed" if delayed else "observed"}.png'))
    context.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://localhost:4185')
    parser.add_argument('--output', default='/tmp/s12-browser-evidence')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'results.json').unlink(missing_ok=True)
    results = []
    with sync_playwright() as p:
        for engine in ['chromium', 'firefox', 'webkit']:
            browser = getattr(p, engine).launch()
            context = browser.new_context(timezone_id='America/Los_Angeles', viewport={'width': 1280, 'height': 900})
            page = context.new_page()
            page.clock.install(time=datetime(2026, 10, 12, 12, tzinfo=timezone.utc))
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('dialog', lambda dialog: dialog.accept())
            context.request.post(f'{args.base_url}/__test/s12-reset')
            login(page, args.base_url)
            page.locator('#archive-settings-open').click()
            expect(page.locator('#archive-settings-status')).to_have_text('Настройки загружены.')
            expect(page.locator('#zoom-client-secret')).to_have_value('')
            for width in [320, 390, 768, 1280]:
                page.set_viewport_size({'width': width, 'height': 900})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (engine, width, 'page overflow')
                assert page.locator('#archive-settings-dialog').evaluate('(el) => el.scrollWidth <= el.clientWidth + 1'), (engine, width, 'dialog overflow')
                page.screenshot(path=str(output / f'{engine}-settings-{width}.png'))
            page.locator('#zoom-add').click()
            page.locator('#zoom-name').fill('Second synthetic profile')
            page.locator('#zoom-meeting-id').fill('12345678901')
            page.locator('#zoom-account-id').fill('synthetic-account-2')
            page.locator('#zoom-client-id').fill('synthetic-client-2')
            page.locator('#zoom-client-secret').fill('synthetic-secret-2')
            page.locator('#zoom-check').click()
            expect(page.locator('#archive-settings-status')).to_contain_text('Проверено.')
            page.locator('#zoom-connection-form button[type=submit]').click()
            expect(page.locator('#archive-settings-status')).to_have_text('Сохранение подтверждено архивом.')
            expect(page.locator('#zoom-connections article')).to_have_count(2)
            usage_refresh_regression(page)
            page.keyboard.press('Escape')
            expect(page.locator('#archive-settings-open')).to_be_focused()
            page.locator('#archive-zoom-open').click()
            expect(page.locator('#zoom-occurrences article')).to_have_count(2)
            expect(page.locator('#zoom-occurrences h4').first).to_contain_text('11:17 МСК')
            assert page.locator('#archive-zoom-dialog input[type=password]').count() == 0
            for width in [320, 390, 768, 1280]:
                page.set_viewport_size({'width': width, 'height': 900})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (engine, width)
                assert page.locator('#archive-zoom-dialog').evaluate('(el) => el.scrollWidth <= el.clientWidth + 1'), (engine, width, 'calendar overflow')
                page.screenshot(path=str(output / f'{engine}-calendar-{width}.png'))
            # A late response for October cannot replace the selected November.
            held = {}
            def hold_old_calendar(route):
                if 'month=2026-10' in route.request.url and not held:
                    held['route'] = route
                    held['response'] = route.fetch()
                else:
                    route.continue_()
            page.route('**/v1/zoom/calendar?*', hold_old_calendar)
            page.locator('#zoom-refresh').click()
            page.wait_for_timeout(200)
            assert 'route' in held
            page.locator('#zoom-month-next').click()
            expect(page.locator('#archive-zoom-status')).to_have_text('В этом месяце записей нет.')
            held['route'].fulfill(response=held['response'])
            page.wait_for_timeout(100)
            expect(page.locator('#zoom-month')).to_have_value('2026-11')
            expect(page.locator('#zoom-occurrences article')).to_have_count(0)
            page.unroute('**/v1/zoom/calendar?*', hold_old_calendar)
            page.locator('#zoom-month-prev').click()
            expect(page.locator('#zoom-occurrences article')).to_have_count(2)
            # Drop a real successful part response, leaving canonical accepted bytes.
            context.request.post(f'{args.base_url}/__test/s12-fault')
            page.locator('#zoom-occurrences button').filter(has_text='Импортировать запись').first.click()
            page.wait_for_function("document.querySelector('#zoom-stop').hidden", timeout=20000)
            interrupted = context.request.get(f'{args.base_url}/__test/s12-state').json()
            assert len(interrupted['assets']) == 1, (engine, page.locator('#archive-zoom-status').inner_text(), interrupted['assets'])
            page.wait_for_timeout(300)
            assert len(context.request.get(f'{args.base_url}/__test/s12-state').json()['assets']) == 1, 'background upload after failure'
            cookies = context.storage_state()
            context.close()
            context = browser.new_context(storage_state=cookies, timezone_id='America/Los_Angeles', viewport={'width': 390, 'height': 900})
            page = context.new_page()
            page.clock.install(time=datetime(2026, 10, 12, 12, tzinfo=timezone.utc))
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('dialog', lambda dialog: dialog.accept())
            page.goto(f'{args.base_url}/Audio-Archive.html')
            page.locator('#archive-zoom-open').click()
            expect(page.locator('#zoom-occurrences h4').first).to_contain_text('Импорт не завершён')
            page.locator('#zoom-occurrences button').filter(has_text='Проверить и продолжить').first.click()
            try:
                expect(page.locator('#zoom-occurrences h4').first).to_contain_text('В Аудиоархиве', timeout=20000)
            except Exception:
                print(engine, page.locator('#archive-zoom-status').inner_text(), errors, flush=True)
                page.screenshot(path=str(output / f'{engine}-failure.png'))
                raise
            state = context.request.get(f'{args.base_url}/__test/s12-state').json()
            assert len(state['assets']) == 4, 'resume duplicated accepted assets'
            assert page.evaluate('localStorage.length === 0 && sessionStorage.length === 0')
            sources = [value for path, value in state['files'] if path.startswith('sessions/')]
            assert len(sources) == 1 and len(sources[0]['sourceTracks']) == 2
            assert sources[0]['origin']['kind'] == 'zoom_cloud'
            assert sources[0]['sourceTracks'][0]['originalName'] == sources[0]['sourceTracks'][1]['originalName']
            # The same physical bytes/hashes passed browser plan, upload and domain finalization.
            asset_hashes = dict(state['assets'])
            for track in sources[0]['sourceTracks']:
                for part in track['parts']:
                    assert asset_hashes[part['assetId']] == part['sha256']
            page.locator('#zoom-occurrences button').filter(has_text='Открыть в Аудиоархиве').first.click()
            expect(page.locator('#detail-title')).to_have_text(sources[0]['title'])
            expect(page.locator('#detail-heading')).to_contain_text('Zoom Cloud')
            expect(page.locator('#detail-body a[href*="workflow=announcement"]')).to_be_visible()
            expect(page.locator('#detail-body a[href*="workflow=speaker"]')).to_be_visible()
            expect(page.locator('#detail-title')).to_be_focused()
            page.locator('#detail-close').click()
            page.locator('#archive-settings-open').click()
            expect(page.locator('#archive-settings-status')).to_have_text('Настройки загружены.')
            page.locator('#archive-soft-limit').fill('0.000001')
            page.locator('#archive-warning-percent').fill('80')
            page.locator('#archive-storage-form button[type=submit]').click()
            expect(page.locator('#archive-settings-status')).to_have_text('Сохранение подтверждено архивом.')
            page.locator('#archive-settings-close').click()
            expect(page.locator('#archive-storage-warning')).to_be_visible()
            page.locator('#archive-zoom-open').click()
            page.locator('#zoom-occurrences button').filter(has_text='Импортировать запись').first.click()
            expect(page.locator('#zoom-occurrences h4').last).to_contain_text('В Аудиоархиве', timeout=20000)
            page.locator('#archive-zoom-close').click()
            expect(page.locator('#archive-zoom-open')).to_be_focused()
            manual_storage_regression(page, context, args.base_url, output, engine)
            discard_ui_regression(page, context, args.base_url)
            attention_diagnostics_regression(page, context, args.base_url)
            isolation_regression(page, context, args.base_url)
            context.close()
            warning_expiry_regression(browser, args.base_url, output, engine, errors)
            warning_expiry_regression(browser, args.base_url, output, engine, errors, delayed=True)
            assert not errors, (engine, errors)
            results.append({'engine': engine, 'widths': [320, 390, 768, 1280], 'status': 'PASS', 'pageErrors': errors, 'timezone': 'America/Los_Angeles', 'sourceSessions': 2, 'lostPartAndNewContextResume': 'PASS', 'lateMonthResponse': 'PASS', 'keyboardEscapeFocus': 'PASS', 'usageRefreshAndManualThresholdBothDirections': 'PASS', 'manualAndZoomLostDeleteDiscardUI': 'PASS', 'strictAttentionIndependentDiagnosticsAndFreshRefresh': 'PASS', 'zoomContextMutationsAndReconcile': 'PASS', 'lateFileBodyErrorAndControllerFinally': 'PASS', 'newAccountImport': 'PASS', 'ABAAndFocusExternalChange': 'PASS', 'lateCompletedReserveAndDetachedAction': 'PASS', 'sessionExpiryPendingFile': 'PASS', 'stopWarningObserved401ClearAndReconnect': 'PASS', 'delayedWarning401AfterNewLogin': 'PASS'})
            browser.close()
    evidence = {'checkedHead': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(), 'uncommittedTrackedChanges': bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], text=True).strip()), 'results': results}
    (output / 'results.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(results))


if __name__ == '__main__':
    main()
