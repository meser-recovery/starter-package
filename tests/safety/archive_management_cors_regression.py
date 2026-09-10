"""Run the real S09 browser suite at root and subpath with normal browser CORS protection."""
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

from archive_management_smoke import ROOT, check_archive_management


class MountedSiteHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        self.server.request_paths.append(self.path)
        try:
            super().do_GET()
        except (BrokenPipeError, ConnectionResetError):
            # Page navigation can cancel an in-flight static resource response.
            pass

    def translate_path(self, path):
        # Keep the browser's URL unchanged; map only filesystem lookup under this test mount.
        if path.startswith('/starter-package/'):
            path = path[len('/starter-package'):]
        return super().translate_path(path)

    def log_message(self, format, *args):
        pass


@contextmanager
def local_site():
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(MountedSiteHandler, directory=str(ROOT)))
    server.request_paths = []
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', server.request_paths
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def check_archive_management_cors(browser):
    # No browser security flags, direct GitHub assets, or real archive requests.
    # check_archive_management retains its gateway.test -> in-memory bridge route
    # and denies every destination except this local site and the intercepted mock.
    with local_site() as (site_origin, request_paths):
        for path in ('', '/starter-package/'):
            site_url = site_origin + path
            print(f'S09 CORS regression: {site_url}', flush=True)
            start = len(request_paths)
            check_archive_management(browser, site_url)
            if path:
                served = request_paths[start:]
                assert served and all(urlsplit(url).path.startswith('/starter-package/') for url in served), served
    print('S09 CORS root/subpath regression passed (default Chromium web security).', flush=True)


if __name__ == '__main__':
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            check_archive_management_cors(browser)
        finally:
            browser.close()
