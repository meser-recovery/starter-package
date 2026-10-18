#!/usr/bin/env python3
"""Selected-click→verified→real Editor readiness, on three synthetic WAV tracks."""
import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect


def verified(page):
    # The shared status can change when an independent list request finishes.
    # Canonical batch adoption + completed overlay are the readiness boundary.
    page.wait_for_function("""document.getElementById('source-session-loading').hidden &&
      !document.body.dataset.editing && document.getElementById('current-recording-heading').textContent.includes('три дорожки')""", timeout=60000)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--mode', choices=['base', 'candidate'], required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    assert urlparse(args.base_url).hostname in ['127.0.0.1', 'localhost']
    rows = []
    with sync_playwright() as p:
        for engine in ['chromium', 'firefox', 'webkit']:
            b = getattr(p, engine).launch()
            c = b.new_context(viewport={'width': 390, 'height': 900})
            def fence(route):
                if urlparse(route.request.url).netloc == urlparse(args.base_url).netloc:
                    route.continue_()
                else:
                    raise AssertionError('External HTTP destination blocked: ' + route.request.url)
            c.route('http**/*', fence)
            page = c.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(args.base_url + '/login?return=%2F')
            page.locator('#admin-password').fill('local-test-password')
            page.locator('#admin-access-form button[type=submit]').click()
            page.wait_for_url(args.base_url + '/')
            for delay in [10, 80]:
                for workflow in ['announcement', 'speaker']:
                    for repeat in range(5):
                        seed = c.request.post(f'{args.base_url}/__test/s13-seed?n=1&audio=3&delay={delay}').json()
                        page.goto(args.base_url + '/Audio-Editor.html')
                        page.locator('#source-session-mode-archive').click()
                        page.locator('#source-session-recent').click()
                        card = page.locator(f'[data-session-id="{seed["primary"]}"]')
                        expect(card).to_be_visible()
                        c.request.post(args.base_url + '/__test/s13-counts')
                        start = time.perf_counter()
                        card.get_by_role('button', name='Выбрать', exact=True).click()
                        verified(page)
                        verified_ms = (time.perf_counter() - start) * 1000
                        page.locator('#open-local-' + workflow).click()
                        if workflow == 'speaker':
                            page.wait_for_function("async()=> (await import('./scripts/speaker-editor.mjs')).getSpeakerSaveState().ready", timeout=60000)
                        else:
                            page.wait_for_function("async()=> (await import('./scripts/audio-processor.mjs')).getProcessorFiles().length===3 && !document.getElementById('processor-run').disabled", timeout=60000)
                        interactive_ms = (time.perf_counter() - start) * 1000
                        counts = c.request.get(args.base_url + '/__test/s13-counts').json()
                        if workflow == 'speaker':
                            page.evaluate("async()=>{await (await import('./scripts/speaker-editor.mjs')).closeSpeakerEditor(true)}")
                        else:
                            page.locator('#source-session-announcement-close').click()
                        # Offer the same current verified batch for another explicit selection.
                        page.locator('#source-session-mode-archive').click()
                        page.locator('#source-session-recent').click()
                        expect(card).to_be_visible()
                        c.request.post(args.base_url + '/__test/s13-counts')
                        warm_start = time.perf_counter()
                        card.get_by_role('button', name='Выбрать', exact=True).click()
                        verified(page)
                        warm_counts = c.request.get(args.base_url + '/__test/s13-counts').json()
                        if args.mode == 'candidate':
                            assert counts['maxActive'] <= 2, counts
                            assert warm_counts['assetBytes'] == 0, warm_counts
                        rows.append({'engine': engine, 'version': b.version, 'workflow': workflow, 'repeat': repeat, 'gatewayAssetDelayMs': delay,
                                     'verifiedMs': verified_ms, 'interactiveMs': interactive_ms,
                                     'preparationAfterVerifiedMs': interactive_ms - verified_ms,
                                     'counts': counts, 'warmVerifiedMs': (time.perf_counter() - warm_start) * 1000, 'warmCounts': warm_counts})
                        Path(args.output).write_text(json.dumps({'kind': 'local-synthetic-selected-click-checkpoint', 'mode': args.mode, 'rows': rows}, ensure_ascii=False, separators=(',', ':')) + '\n')
                    print(f'{engine} {workflow} RTT={delay}: 5 repeats PASS', flush=True)
            assert not errors, errors
            c.close()
            b.close()
    Path(args.output).write_text(json.dumps({'kind': 'local-synthetic-selected-click', 'mode': args.mode, 'rows': rows,
        'network': 'fixed per-asset delay at synthetic Gateway repository download, loopback browser→Gateway; not remote geography',
        'memory': 'NOT_RUN browser memory', 'fixture': '3×8044 byte deterministic 0.5s WAV; single native/WASM waveform worker; no production traffic'}, ensure_ascii=False, separators=(',', ':')) + '\n')


if __name__ == '__main__':
    main()
