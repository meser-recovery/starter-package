#!/usr/bin/env python3
"""Serve this checkout on loopback and open its real Audio Editor before merge."""
import argparse
import functools
import http.server
from pathlib import Path
import subprocess
import webbrowser


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=0, help='0 selects an available port automatically')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if not (root / 'Audio-Editor.html').is_file():
        parser.error('Audio-Editor.html is missing from this checkout')
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    try:
        server = http.server.ThreadingHTTPServer(('127.0.0.1', args.port), handler)
    except OSError as error:
        parser.error(f'{error}. Use --port 0 to select an available port.')
    url = f'http://127.0.0.1:{server.server_port}/Audio-Editor.html'
    revision = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=root, capture_output=True, text=True)
    dirty = subprocess.run(['git', 'status', '--porcelain'], cwd=root, capture_output=True, text=True)
    print(f'Просмотр: {url}', flush=True)
    print(f'Checkout: {revision.stdout.strip() or "unknown"}' + (' + локальные изменения' if dirty.stdout else ''), flush=True)
    print('Остановить: Ctrl+C. Файлы обслуживаются из этого checkout.', flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
