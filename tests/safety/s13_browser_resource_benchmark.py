#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright


parser = argparse.ArgumentParser()
parser.add_argument('--base-url', default='http://127.0.0.1:4191')
parser.add_argument('--output', default='/private/tmp/s13-checks/browser-resource.json')
parser.add_argument('--engine', choices=['all', 'chromium', 'firefox', 'webkit'], default='all')
args = parser.parse_args()
assert urlparse(args.base_url).hostname in ['127.0.0.1', 'localhost']
rows = []
with sync_playwright() as p:
    for engine in (['chromium', 'firefox', 'webkit'] if args.engine == 'all' else [args.engine]):
        b = getattr(p, engine).launch()
        c = b.new_context()
        def fence(route):
            assert urlparse(route.request.url).netloc == urlparse(args.base_url).netloc
            route.continue_()
        c.route('http**/*', fence)
        page = c.new_page()
        page.set_default_timeout(240000)
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.add_init_script("window.unhandled=[];addEventListener('unhandledrejection',e=>window.unhandled.push(String(e.reason)))")
        page.goto(args.base_url)
        page.wait_for_function('typeof window.runResource === "function"')
        try:
            result = page.evaluate('window.runResource()')
        except Exception as error:
            print(json.dumps({'engine': engine, 'failure': str(error), 'stage': page.evaluate('window.resourceStage'), 'pageErrors': errors}), flush=True)
            raise
        assert not errors, errors
        assert not page.evaluate('window.unhandled'), page.evaluate('window.unhandled')
        for _ in range(100):
            stats = c.request.get(args.base_url + '/stats').json()
            if stats['active'] == 0:
                break
            page.wait_for_timeout(10)
        assert stats['active'] == 0, stats
        rows.append({'engine': engine, 'version': b.version, 'status': 'PASS', 'pageErrors': errors, 'result': result, 'server': stats})
        Path(args.output).write_text(json.dumps({'kind': 'real-browser-generated-WAV-near-limit-resource', 'rows': rows,
            'scope': '495 MiB source transfer/hash, cancel/retry, byte identity, warm reuse; no FFmpeg/Editor near-limit decode or physical mobile claim'}, separators=(',', ':')) + '\n')
        print(engine + ': 495 MiB transfer/hash, cancel/retry, warm reuse PASS', flush=True)
        c.close()
        b.close()
