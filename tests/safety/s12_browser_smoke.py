#!/usr/bin/env python3
"""S12 real protected UI against a disposable synthetic Gateway only."""
import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright, expect


def login(page, url):
    page.goto(f'{url}/Audio-Archive.html')
    page.locator('#admin-password').fill('local-test-password')
    page.locator('#admin-access-form button[type=submit]').click()
    page.wait_for_url('**/Audio-Archive.html')


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
            assert not errors, (engine, errors)
            results.append({'engine': engine, 'widths': [320, 390, 768, 1280], 'status': 'PASS', 'pageErrors': errors, 'timezone': 'America/Los_Angeles', 'sourceSessions': 2, 'lostPartAndNewContextResume': 'PASS', 'lateMonthResponse': 'PASS', 'keyboardEscapeFocus': 'PASS'})
            context.close()
            browser.close()
    evidence = {'checkedHead': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(), 'uncommittedTrackedChanges': bool(subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], text=True).strip()), 'results': results}
    (output / 'results.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps(results))


if __name__ == '__main__':
    main()
