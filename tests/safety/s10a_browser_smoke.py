#!/usr/bin/env python3
"""Focused S10A same-origin service regression in Chromium, Firefox and WebKit.

The suite uses only synthetic local data. Playwright is regression evidence, not
proof of behavior on a real iPhone/Safari or Android/Chrome device.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import struct
import wave
from io import BytesIO

from playwright.sync_api import sync_playwright


PASSWORD = "local-test-password"
EXPIRED = "Служебная сессия истекла. Войдите снова, чтобы продолжить."


def wav_fixture() -> bytes:
    output = BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(struct.pack("<" + "h" * 1600, *([0] * 1600)))
    return output.getvalue()


def login(page, base_url: str, expected_path: str = "/") -> list[tuple[str, str]]:
    trace: list[tuple[str, str]] = []

    def record(request):
        if "/v1/session" in request.url:
            trace.append((request.method, request.url.split(base_url, 1)[-1]))

    page.on("request", record)
    page.locator("#admin-password").fill(PASSWORD)
    page.locator("#admin-access-form button[type=submit]").click()
    page.wait_for_url(f"**{expected_path}", timeout=10_000)
    page.wait_for_load_state("domcontentloaded")
    filtered = [(method, path.split("?", 1)[0]) for method, path in trace if path.startswith("/v1/session")]
    if filtered[:2] != [("POST", "/v1/session/login"), ("GET", "/v1/session")]:
        raise AssertionError(f"login was not proven by immediate replay: {filtered}")
    return filtered


def exercise(browser_type, base_url: str, screenshot_dir: Path | None):
    browser = browser_type.launch()
    context = browser.new_context(viewport={"width": 390, "height": 844})
    page = context.new_page()
    blocked = []

    def observe(request):
        if request.url.startswith(("https://meserproject.duckdns.org", "https://meser-recovery.github.io")):
            blocked.append(request.url)

    page.on("request", observe)

    response = page.goto(base_url + "/", wait_until="domcontentloaded")
    assert response is not None
    page.wait_for_url("**/login?return=*", timeout=5000)
    assert page.get_by_role("heading", name="Для служащих").is_visible()
    login(page, base_url, "/")
    assert page.get_by_role("heading", name="Служебная страница").is_visible()

    for path, heading in (
        ("/Calendar.html", "Календарь событий"),
        ("/Google-Drive.html", "Материалы"),
        ("/Audio-Archive.html", "Аудиоархив"),
        ("/Audio-Editor.html", "Редактирование аудио"),
    ):
        page.goto(base_url + path, wait_until="domcontentloaded")
        page.get_by_role("heading", name=heading, exact=True).wait_for(state="visible")
        assert page.locator("text=Дополнительное подтверждение Safari").count() == 0
        assert page.get_by_role("button", name="Подключить архив").count() == 0
        assert page.get_by_role("button", name="Отключить архив").count() == 0

    page.goto(base_url + "/Audio-Archive.html", wait_until="domcontentloaded")
    page.locator("#status").wait_for()
    assert page.locator("#login").is_hidden(), "Archive must be automatic after service login"
    assert not page.locator("#login-dialog").is_visible()

    page.goto(base_url + "/Audio-Editor.html", wait_until="domcontentloaded")
    page.locator("#processor-file").set_input_files({
        "name": "synthetic.wav", "mimeType": "audio/wav", "buffer": wav_fixture()
    })
    page.wait_for_function("document.getElementById('processor-file').files.length === 1")
    page.locator("#workflow-choice").wait_for(state="visible", timeout=30_000)
    page.request.post(base_url + "/__test/expire")
    page.locator("#source-session-mode-archive").click()
    page.locator("#source-session-refresh").click()
    page.get_by_text(EXPIRED, exact=True).first.wait_for(state="visible")
    assert page.locator("#processor-file").evaluate("input => input.files[0].name") == "synthetic.wav"

    page.locator("#source-session-authenticate").click()
    page.locator("#source-session-login-dialog").wait_for(state="visible")
    page.locator("#source-session-password").fill(PASSWORD)
    page.locator("#source-session-login-form button[type=submit]").click()
    page.locator("#source-session-login-dialog").wait_for(state="hidden")
    assert page.locator("#processor-file").evaluate("input => input.files[0].name") == "synthetic.wav"
    assert page.locator("#open-local-announcement").is_visible()
    assert page.locator("#open-local-speaker").is_visible()

    csrf_denied = {"active": True}

    def deny_reads(route):
        if csrf_denied["active"]:
            route.fulfill(status=403, content_type="application/json", body='{"error":"Origin/CSRF denied"}')
        else:
            route.continue_()

    context.route("**/v1/source-sessions?*", deny_reads)
    page.locator("#source-session-refresh").click()
    page.wait_for_timeout(250)
    assert not page.locator("#source-session-login-dialog").is_visible(), "403 must not be misclassified as expiry"
    assert "Origin, CSRF" in page.locator("#source-session-status").inner_text()
    csrf_denied["active"] = False
    context.unroute("**/v1/source-sessions?*", deny_reads)

    for width in (320, 390, 768, 1280):
        page.set_viewport_size({"width": width, "height": 900})
        for path in ("/", "/Audio-Archive.html", "/Audio-Editor.html"):
            page.goto(base_url + path, wait_until="domcontentloaded")
            assert not page.evaluate("document.documentElement.scrollWidth > window.innerWidth"), (width, path)
            if screenshot_dir:
                screenshot_dir.mkdir(parents=True, exist_ok=True)
                name = path.strip("/").replace(".", "-") or "landing"
                page.screenshot(path=screenshot_dir / f"s10a-{browser_type.name}-{name}-{width}.png", full_page=True)

    page.goto(base_url + "/Audio-Editor.html", wait_until="domcontentloaded")
    page.locator("#processor-file").set_input_files({
        "name": "unsaved-speaker.wav", "mimeType": "audio/wav", "buffer": wav_fixture()
    })
    page.locator("#workflow-choice").wait_for(state="visible", timeout=30_000)
    page.locator("#open-local-speaker").click()
    page.wait_for_function("document.getElementById('speaker-editor-status').dataset.dirty === 'true'", timeout=30_000)
    page.locator("#service-logout").click()
    page.locator("#speaker-unsaved-dialog").wait_for(state="visible")
    page.locator("#speaker-unsaved-cancel").click()
    assert "/Audio-Editor.html" in page.url
    assert page.evaluate("async () => (await fetch('/v1/session')).status") == 200
    page.locator("#service-logout").click()
    page.locator("#speaker-unsaved-dialog").wait_for(state="visible")
    page.locator("#speaker-unsaved-discard").click()
    page.wait_for_url("**/login", timeout=5000)
    assert page.evaluate("async () => (await fetch('/v1/session')).status") == 401
    page.goto(base_url + "/Audio-Archive.html", wait_until="domcontentloaded")
    page.wait_for_url("**/login?return=*", timeout=5000)

    assert not blocked, blocked
    context.close()
    browser.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:4173")
    parser.add_argument("--browser", choices=("chromium", "firefox", "webkit", "all"), default="all")
    parser.add_argument("--screenshot-dir", type=Path)
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    with sync_playwright() as playwright:
        names = ("chromium", "firefox", "webkit") if args.browser == "all" else (args.browser,)
        for name in names:
            exercise(getattr(playwright, name), base_url, args.screenshot_dir)
            print(f"S10A focused same-origin browser smoke passed: {name}")
    print("Playwright is regression evidence, not proof of real iPhone/Safari or Android/Chrome behavior.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
