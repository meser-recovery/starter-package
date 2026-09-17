#!/usr/bin/env python3
"""Focused S10A auth/storage-access regression in Chromium and WebKit.

This deterministic mock proves frontend state transitions and origin/source fencing;
it is not evidence of real iPhone Safari ITP behavior.
"""

from __future__ import annotations

import argparse
import json
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


GATEWAY = "https://gateway.test"


def cors_headers(origin, content_type="application/json"):
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Allow-Headers": "Content-Type, X-CSRF-Token",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Content-Type": content_type,
    }


def exercise(browser_type, base_url: str):
    site_origin = urlparse(base_url)._replace(path="", params="", query="", fragment="").geturl().rstrip("/")
    site_authority = urlparse(site_origin).netloc
    context = browser_type.launch().new_context(viewport={"width": 390, "height": 844})
    context.add_init_script(f"sessionStorage.setItem('meser_service_access_v1', 'granted'); window.__MESER_AUDIO_ARCHIVE_GATEWAY__ = {json.dumps(GATEWAY)}")
    scenario = {"replay": "direct", "bridge": "granted", "session_gets": 0, "login_done": False}
    trace = []
    blocked = []

    def route_request(route):
        request = route.request
        parsed = urlparse(request.url)
        if parsed.scheme == "blob":
            route.continue_()
            return
        if parsed.netloc == site_authority:
            route.continue_()
            return
        if parsed.netloc != "gateway.test":
            blocked.append(request.url)
            route.abort()
            return
        trace.append((request.method, parsed.path))
        if request.method == "OPTIONS":
            route.fulfill(status=204, headers=cors_headers(site_origin), body="")
            return
        if parsed.path == "/v1/config":
            route.fulfill(status=200, headers=cors_headers(site_origin), body=json.dumps({"acceptedPartSize": 1024, "speakerProjectHistory": 1}))
            return
        if parsed.path == "/v1/session/login":
            scenario["login_done"] = True
            if scenario["replay"] == "wrong":
                route.fulfill(status=401, headers=cors_headers(site_origin), body=json.dumps({"error": "Неверный пароль."}))
            else:
                route.fulfill(status=200, headers=cors_headers(site_origin), body=json.dumps({"authenticated": True, "csrfToken": "unproven"}))
            return
        if parsed.path == "/v1/session":
            scenario["session_gets"] += 1
            success = scenario["login_done"] and (scenario["replay"] == "direct" or
                (scenario["replay"] == "blocked" and scenario["bridge"] == "granted-after-click"))
            route.fulfill(status=200 if success else 401, headers=cors_headers(site_origin), body=json.dumps(
                {"authenticated": True, "expiresAt": 9999999999, "csrfToken": "replayed"} if success else {"error": "cookie unavailable"}
            ))
            return
        if parsed.path in ("/v1/source-sessions", "/v1/maintenance/incomplete"):
            body = {"revision": 1, "sessions": []} if parsed.path == "/v1/source-sessions" else {"transactions": [], "observations": []}
            route.fulfill(status=200, headers=cors_headers(site_origin), body=json.dumps(body))
            return
        if parsed.path == "/safari-bootstrap":
            route.fulfill(status=200, headers={"Content-Type": "text/html"}, body="<!doctype html><title>Bootstrap</title><p>first-party</p>")
            return
        if parsed.path == "/storage-access-bridge":
            mode = scenario["bridge"]
            automatic = "unsupported" if mode == "unsupported" else "required"
            clicked = "denied" if mode == "denied" else "granted"
            body = f'''<!doctype html><button id="grant">grant</button><script>
              const send = status => parent.postMessage({{type:'meser-storage-access',version:1,status}}, {json.dumps(site_origin)});
              send({json.dumps(automatic)});
              grant.onclick = () => send({json.dumps(clicked)});
            </script>'''
            route.fulfill(status=200, headers={"Content-Type": "text/html"}, body=body)
            return
        route.fulfill(status=404, headers=cors_headers(site_origin), body=json.dumps({"error": "unexpected"}))

    context.route("**/*", route_request)
    page = context.new_page()

    def open_login():
        page.goto(base_url.rstrip("/") + "/Audio-Archive.html", wait_until="domcontentloaded")
        page.locator("#login").click()
        page.locator("#password").fill("local-test-password")
        page.locator("#login-form button[type=submit]").click()

    # Direct path: POST is immediately followed by the replay proof.
    scenario.update(replay="direct", bridge="granted", session_gets=0, login_done=False)
    open_login()
    page.locator("#logout").wait_for(state="visible")
    assert [(method, path) for method, path in trace if path in ("/v1/session/login", "/v1/session")][-2:] == [
        ("POST", "/v1/session/login"), ("GET", "/v1/session")
    ]

    # Correct password with an unavailable cookie must not authenticate.
    trace.clear()
    scenario.update(replay="blocked", bridge="required", session_gets=0, login_done=False)
    page = context.new_page()
    open_login()
    page.locator("#storage-help").wait_for(state="visible")
    assert page.locator("#logout").is_hidden()
    assert "Safari" in page.locator("#login-status").inner_text()
    page.evaluate("""() => window.dispatchEvent(new MessageEvent('message', {
      origin: 'https://gateway.test', source: window,
      data: {type: 'meser-storage-access', version: 1, status: 'granted'}
    }))""")
    assert page.locator("#logout").is_hidden()

    # Bootstrap is explicit and opens the fixed gateway URL.
    with page.expect_popup() as popup_info:
        page.locator("#storage-bootstrap").click()
    popup = popup_info.value
    popup.wait_for_load_state("domcontentloaded")
    assert popup.url == GATEWAY + "/safari-bootstrap"
    popup.close()
    page.evaluate("""() => {
      const frame = document.querySelector('#storage-frame iframe');
      window.dispatchEvent(new MessageEvent('message', {
        origin: 'https://evil.example', source: frame.contentWindow,
        data: {type: 'meser-storage-access', version: 1, status: 'granted'}
      }));
    }""")
    assert page.locator("#logout").is_hidden()

    # Unsupported Storage Access API is distinct and keeps local/archive auth disconnected.
    scenario["bridge"] = "unsupported"
    page.locator("#storage-retry").click()
    page.wait_for_function("document.getElementById('login-status').textContent.includes('не поддерживает')")
    assert page.locator("#logout").is_hidden()

    # Denial remains disconnected and retry is safe.
    scenario["bridge"] = "denied"
    page.locator("#storage-retry").click()
    frame = page.frame_locator("#storage-frame iframe")
    frame.locator("#grant").click()
    page.wait_for_function("document.getElementById('login-status').textContent.includes('не разрешён')")
    assert page.locator("#logout").is_hidden()

    # A grant is followed by one final /v1/session replay before connected UI.
    scenario["bridge"] = "granted-after-click"
    before = scenario["session_gets"]
    page.locator("#storage-retry").click()
    page.frame_locator("#storage-frame iframe").locator("#grant").click()
    page.locator("#logout").wait_for(state="visible")
    assert scenario["session_gets"] == before + 1

    # Wrong password is distinct and never exposes the Safari fallback.
    scenario.update(replay="wrong", bridge="required", login_done=False)
    page = context.new_page()
    open_login()
    page.wait_for_function("document.getElementById('login-status').textContent.includes('Неверный пароль')")
    assert page.locator("#storage-help").is_hidden()
    assert page.locator("#logout").is_hidden()

    assert not blocked, blocked
    context.browser.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:4173")
    parser.add_argument("--browser", choices=("chromium", "webkit", "both"), default="both")
    args = parser.parse_args()
    with sync_playwright() as playwright:
        names = ("chromium", "webkit") if args.browser == "both" else (args.browser,)
        for name in names:
            exercise(getattr(playwright, name), args.base_url)
            print(f"S10A focused browser smoke passed: {name}")
    print("Playwright WebKit is regression evidence, not proof of real iPhone Safari/ITP behavior.")


if __name__ == "__main__":
    main()
