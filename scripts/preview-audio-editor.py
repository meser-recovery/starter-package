#!/usr/bin/env python3
"""Serve the real audio UI with a test-only in-memory archive gateway."""
import argparse
import base64
import http.server
import json
from pathlib import Path
import re
import subprocess
import threading
import webbrowser


class SyntheticGateway:
    """Serialize browser HTTP requests through the existing JSON-lines test bridge."""

    def __init__(self, root):
        self.process = subprocess.Popen(
            ['node', str(root / 'tests/safety/archive_management_bridge.mjs')],
            cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True,
        )
        self.lock = threading.Lock()
        self.snapshot = json.loads(self.process.stdout.readline())
        self.command('recovery')

    def command(self, action, **data):
        with self.lock:
            self.process.stdin.write(json.dumps({'action': action, **data}) + '\n')
            self.process.stdin.flush()
            result = json.loads(self.process.stdout.readline())
        if result.get('bridgeError'):
            raise RuntimeError(result['bridgeError'])
        return result

    def request(self, method, path, headers, body):
        request_headers = {key: value for key, value in headers.items()}
        # The fixture intentionally preserves the production exact-origin policy.
        request_headers['Origin'] = 'https://site.test'
        return self.command(
            'request', method=method, path=path, headers=request_headers,
            bodyBase64=base64.b64encode(body).decode('ascii') if body else None,
        )

    def close(self):
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()


def preview_handler(root, gateway, origin):
    class PreviewHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def _gateway(self):
            length = int(self.headers.get('Content-Length', '0'))
            body = self.rfile.read(length) if length else b''
            try:
                result = gateway.request(self.command, self.path, dict(self.headers), body)
                payload = base64.b64decode(result['body']) if result.get('base64') else result.get('body', '').encode()
                self.send_response(result['status'])
                self.send_header('Content-Type', result.get('type') or 'application/json')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(payload)
            except (BrokenPipeError, RuntimeError, ValueError) as error:
                payload = json.dumps({'error': f'Preview gateway: {error}'}).encode()
                self.send_response(502)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        def do_OPTIONS(self):
            if self.path.startswith('/v1/'):
                self.send_response(204)
                self.send_header('Allow', 'GET, POST, PUT, PATCH, OPTIONS')
                self.end_headers()
            else:
                self.send_error(404)

        def do_GET(self):
            if self.path.startswith('/v1/'):
                self._gateway()
                return
            pathname = self.path.split('?', 1)[0]
            if pathname in ('/Audio-Editor.html', '/Audio-Archive.html'):
                body = (root / pathname.lstrip('/')).read_text(encoding='utf-8')
                body, count = re.subn(
                    r'(<meta name="audio-archive-gateway" content=")[^"]*(">)',
                    rf'\g<1>{origin}\2', body, count=1,
                )
                if count != 1:
                    self.send_error(500, 'audio-archive-gateway hook missing')
                    return
                body = body.replace(
                    '<head>',
                    '<head><script>sessionStorage.setItem("meser_service_access_v1", "granted")</script>',
                    1,
                )
                script_version = (root / 'scripts/audio-archive.mjs').stat().st_mtime_ns
                style_version = (root / 'styles/audio-archive.css').stat().st_mtime_ns
                body = body.replace('scripts/audio-archive.mjs"', f'scripts/audio-archive.mjs?v={script_version}"')
                body = body.replace('styles/audio-archive.css"', f'styles/audio-archive.css?v={style_version}"')
                payload = body.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            super().do_GET()

        do_POST = _gateway
        do_PUT = _gateway
        do_PATCH = _gateway

    return PreviewHandler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=0, help='0 selects an available port automatically')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if not (root / 'Audio-Editor.html').is_file():
        parser.error('Audio-Editor.html is missing from this checkout')
    gateway = SyntheticGateway(root)
    try:
        server = http.server.ThreadingHTTPServer(('127.0.0.1', args.port), http.server.SimpleHTTPRequestHandler)
    except OSError as error:
        gateway.close()
        parser.error(f'{error}. Use --port 0 to select an available port.')
    origin = f'http://127.0.0.1:{server.server_port}'
    server.RequestHandlerClass = preview_handler(root, gateway, origin)
    editor_url = f'{origin}/Audio-Editor.html'
    archive_url = f'{origin}/Audio-Archive.html'
    revision = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=root, capture_output=True, text=True)
    dirty = subprocess.run(['git', 'status', '--porcelain'], cwd=root, capture_output=True, text=True)
    print(f'Editor: {editor_url}', flush=True)
    print(f'Archive: {archive_url}', flush=True)
    print(f'Checkout: {revision.stdout.strip() or "unknown"}' + (' + локальные изменения' if dirty.stdout else ''), flush=True)
    print('Остановить: Ctrl+C. Данные синтетические; production gateway не используется.', flush=True)
    if not args.no_browser:
        webbrowser.open(editor_url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        gateway.close()


if __name__ == '__main__':
    main()
