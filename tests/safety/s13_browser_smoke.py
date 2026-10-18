#!/usr/bin/env python3
"""S13 paired UI benchmark/regressions. Only loopback synthetic preview allowed."""
import argparse
import json
import statistics
import time
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect


def measured(page, action, ready):
    start = time.perf_counter()
    action()
    ready()
    elapsed = (time.perf_counter() - start) * 1000
    resources = page.evaluate("""() => performance.getEntriesByType('resource').filter(r => r.name.includes('/v1/')).map(r => ({path: new URL(r.name).pathname, bytes: r.encodedBodySize, transferBytes: r.transferSize, durationMs: r.duration}))""")
    return {'durationMs': elapsed, 'resources': resources}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://localhost:4186')
    parser.add_argument('--output', default='/private/tmp/s13-checks/browser.json')
    parser.add_argument('--mode', choices=['base', 'candidate'], default='candidate')
    parser.add_argument('--repeats', type=int, default=20)
    parser.add_argument('--engine', choices=['all', 'chromium', 'firefox', 'webkit'], default='all')
    parser.add_argument('--complete-refresh', action='store_true')
    args = parser.parse_args()
    assert urlparse(args.base_url).hostname in ['localhost', '127.0.0.1']
    records = []
    with sync_playwright() as p:
        for engine in (['chromium', 'firefox', 'webkit'] if args.engine == 'all' else [args.engine]):
            browser = getattr(p, engine).launch()
            context = browser.new_context(viewport={'width': 1280, 'height': 900})
            blocked = []
            def restrict(route):
                if urlparse(route.request.url).netloc != urlparse(args.base_url).netloc:
                    blocked.append(route.request.url)
                    route.abort()
                else:
                    route.continue_()
            # WebKit exposes blob media requests to routing; leave local Blob
            # decoding native while fencing every HTTP(S) destination.
            context.route('http**/*', restrict)
            context.add_init_script("window.__s13Errors=[];addEventListener('unhandledrejection',e=>window.__s13Errors.push(String(e.reason)))")
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('dialog', lambda d: d.accept())
            page.goto(args.base_url + '/login?return=%2F')
            page.locator('#admin-password').fill('local-test-password')
            page.locator('#admin-access-form button[type=submit]').click()
            page.wait_for_url(args.base_url + '/')
            if args.mode == 'candidate':
                assert not page.evaluate("performance.getEntriesByType('resource').some(r=>r.name.includes('/v1/archive-list')||r.name.includes('/v1/source-sessions?'))"), 'portal entry loaded Archive'
                context.request.post(f'{args.base_url}/__test/s13-seed?n=1')
                held = {}
                def hold_first_list(route):
                    held['route'] = route
                page.route(args.base_url + '/v1/archive-list?*', hold_first_list)
                page.goto(args.base_url + '/Audio-Archive.html', wait_until='domcontentloaded')
                page.locator('#filters input[name=month]').focus()
                for _ in range(100):
                    if 'route' in held:
                        break
                    page.wait_for_timeout(10)
                assert 'route' in held
                held['route'].continue_()
                expect(page.locator('#status')).to_contain_text('Данные загружены')
                page.wait_for_load_state('networkidle')
                assert page.evaluate("document.activeElement === document.querySelector('#filters input[name=month]')"), 'late initial list stole focus'
                page.unroute(args.base_url + '/v1/archive-list?*', hold_first_list)
            for n in [1, 10, 100, 1000]:
                for repeat in range(args.repeats):
                    seed = context.request.post(f'{args.base_url}/__test/s13-seed?n={n}').json()
                    context.request.post(args.base_url + '/__test/s13-counts')
                    first = measured(page, lambda: page.goto(args.base_url + '/Audio-Archive.html'),
                                     lambda: expect(page.locator('#status')).to_contain_text('Данные загружены', timeout=60000))
                    if args.complete_refresh:
                        page.wait_for_load_state('networkidle')
                        first['completeRefreshLastApiResponseEndMs'] = page.evaluate("Math.max(0,...performance.getEntriesByType('resource').filter(r=>r.name.includes('/v1/')).map(r=>r.responseEnd))")
                        first['completeRefreshResources'] = page.evaluate("performance.getEntriesByType('resource').filter(r=>r.name.includes('/v1/')).map(r=>({path:new URL(r.name).pathname,bytes:r.encodedBodySize,transferBytes:r.transferSize,durationMs:r.duration}))")
                    counts = context.request.get(args.base_url + '/__test/s13-counts').json()
                    if args.mode == 'candidate':
                        assert counts['calls'].get('listReleases', 0) == 0, counts
                        assert counts['calls'].get('listReleaseAssets', 0) == 0, counts
                        assert counts['reads'].get('drafts', 0) == 0, counts
                        assert counts['reads'].get('recipes', 0) == 0, counts
                        assert counts['reads'].get('project-states', 0) == 0, counts
                        expect(page.locator('#session-list > article')).to_have_count(min(10, n))
                    page.evaluate('performance.clearResourceTimings()')
                    warm = measured(page, lambda: page.locator('#refresh').click(),
                                    lambda: expect(page.locator('#status')).to_contain_text('Данные загружены', timeout=60000))
                    if args.complete_refresh:
                        page.wait_for_load_state('networkidle')
                        warm['completeRefreshResources'] = page.evaluate("performance.getEntriesByType('resource').filter(r=>r.name.includes('/v1/')).map(r=>({path:new URL(r.name).pathname,bytes:r.encodedBodySize,transferBytes:r.transferSize,durationMs:r.duration}))")
                    # Wait for the actual list request, not the prior ready label.
                    page.wait_for_timeout(50)
                    if args.mode == 'candidate':
                        page.locator('#filters input[name=search]').fill(seed['primary'])
                        page.locator('#record-picker-search').click()
                        expect(page.locator('#session-list > article')).to_have_count(1)
                        assert page.locator('#session-list > article').get_attribute('data-session-id') == seed['primary']
                    records.append({'engine': engine, 'version': browser.version, 'n': n, 'repeat': repeat, 'firstUsefulList': first, 'warmRefresh': warm, 'repository': counts})
            if args.mode == 'candidate':
                seed = context.request.post(f'{args.base_url}/__test/s13-seed?n=1000').json()
                page.goto(args.base_url + '/Audio-Archive.html')
                expect(page.locator('#matching')).to_contain_text('1000')
                first_ids = page.locator('#session-list > article').evaluate_all('(els)=>els.map(e=>e.dataset.sessionId)')
                page.locator('#record-next').click()
                expect(page.locator('#record-page')).to_have_text('2 из 100')
                second_ids = page.locator('#session-list > article').evaluate_all('(els)=>els.map(e=>e.dataset.sessionId)')
                assert not set(first_ids).intersection(second_ids)
                # Snapshot change between pages must restart explicitly, not mix pages.
                context.request.post(f'{args.base_url}/__test/s13-seed?n=1000')
                page.locator('#record-next').click()
                expect(page.locator('#record-page')).to_have_text('1 из 100')
                page.locator('#filters input[name=search]').fill(seed['primary'])
                page.locator('#record-picker-search').click()
                expect(page.locator('#session-list > article')).to_have_count(1)
                context.request.post(args.base_url + '/__test/s13-counts')
                page.get_by_role('button', name='Открыть запись', exact=True).click()
                expect(page.locator('#detail-title')).to_be_visible()
                counts = context.request.get(args.base_url + '/__test/s13-counts').json()
                assert counts['reads'].get('recipes', 0) == 0, counts
                assert counts['reads'].get('project-states', 0) == 0, counts
                page.locator('.project-disclosure > summary').click()
                expect(page.locator('.project-state-row')).not_to_have_count(0)
                for width in [320, 390, 768, 1280]:
                    page.set_viewport_size({'width': width, 'height': 900})
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                # Opening the Editor itself fetches no hidden record collection.
                page.goto(args.base_url + '/Audio-Editor.html')
                assert not page.evaluate("performance.getEntriesByType('resource').some(r=>r.name.includes('/v1/archive-list')||r.name.includes('/v1/source-sessions?'))")
                # Selected source verification, waveform and readiness are separate marks.
                for workflow in ['announcement', 'speaker']:
                    page.goto(f'{args.base_url}/Audio-Editor.html?session={seed["primary"]}&workflow={workflow}')
                    try:
                        page.wait_for_function("name=>performance.getEntriesByName('archive-source-'+name+'-interactive').length>0", arg=workflow, timeout=60000)
                    except Exception:
                        page.screenshot(path=str(Path(args.output).with_name(f's13-{engine}-{workflow}-failure.png')))
                        print(json.dumps({'engine': engine, 'workflow': workflow, 'errors': errors, 'blocked': blocked, 'text': page.locator('body').inner_text(), 'marks': page.evaluate("performance.getEntriesByType('mark').map(m=>m.name)")}, ensure_ascii=False), flush=True)
                        raise
                    marks = page.evaluate("performance.getEntriesByType('mark').filter(m=>m.name.startsWith('archive-source-')).map(m=>({name:m.name,time:m.startTime}))")
                    assert next(m['time'] for m in marks if m['name'] == 'archive-source-verified') <= next(m['time'] for m in marks if m['name'].endswith('-interactive'))
                    records.append({'engine': engine, 'workflow': workflow, 'marks': marks, 'resources': page.evaluate("performance.getEntriesByType('resource').filter(r=>r.name.includes('/v1/')).map(r=>({path:new URL(r.name).pathname,bytes:r.encodedBodySize,durationMs:r.duration}))")})
                assert not page.evaluate('window.__s13Errors'), page.evaluate('window.__s13Errors')
                page.screenshot(path=str(Path(args.output).with_name(f's13-{engine}-editor.png')))
            assert not errors, errors
            assert not blocked, blocked
            records.append({'engine': engine, 'pageErrors': errors, 'externalRequests': blocked, 'status': 'PASS', 'lateListFocusPreserved': args.mode == 'candidate'})
            checkpoint = Path(args.output)
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            checkpoint.write_text(json.dumps({'kind': 'local-synthetic-browser-checkpoint', 'mode': args.mode, 'records': records}, ensure_ascii=False, separators=(',', ':')) + '\n')
            print(f'{engine}: metadata N=1/10/100/1000 ({args.repeats} repeats) PASS', flush=True)
            context.close()
            browser.close()
    result = {'kind': 'local-synthetic-browser', 'mode': args.mode, 'repeats': args.repeats, 'records': records,
              'physicalMobile': 'NOT_RUN', 'production': 'NOT_RUN', 'network': 'loopback; browser cache disabled by routing; no geography inference'}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':')) + '\n')
    print(json.dumps({'output': str(output), 'status': 'PASS', 'rows': len(records)}))


if __name__ == '__main__':
    main()
