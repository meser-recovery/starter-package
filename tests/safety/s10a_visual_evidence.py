#!/usr/bin/env python3
"""Capture redacted synthetic S10A UI states from the actual local pages."""

from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:4173"
OUT = Path(__file__).parent / "evidence" / "s10a"


def no_overflow(page, label):
    assert not page.evaluate("document.documentElement.scrollWidth > window.innerWidth"), label


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context()
        context.add_init_script("sessionStorage.setItem('meser_service_access_v1', 'granted'); window.__MESER_AUDIO_ARCHIVE_GATEWAY__ = '';")
        page = context.new_page()

        page.set_viewport_size({"width": 320, "height": 760})
        page.goto(BASE + "/Audio-Editor.html", wait_until="domcontentloaded")
        page.evaluate("""() => {
          const overlay = document.getElementById('source-session-loading');
          overlay.hidden = false; document.body.setAttribute('data-source-loading', '');
          document.getElementById('source-session-loading-record').textContent = 'Тестовая запись · дорожка 2/3, часть 4/8';
          document.getElementById('source-session-loading-progress').value = 43;
          document.querySelector('[data-loading-step="tracks"]').classList.add('is-active');
        }""")
        page.locator("#source-session-loading-cancel").focus()
        assert page.locator("#source-session-loading-cancel").evaluate("el => document.activeElement === el")
        no_overflow(page, "loading-320")
        page.screenshot(path=OUT / "loading-progress-cancel-320.png", full_page=True)

        page.set_viewport_size({"width": 390, "height": 844})
        page.evaluate("""() => {
          document.getElementById('source-session-loading').hidden = true;
          document.body.removeAttribute('data-source-loading');
          const dialog = document.getElementById('source-session-login-dialog');
          if (!dialog.open) dialog.showModal();
          document.getElementById('source-session-login-status').textContent = 'Подтверждаем защищённый сеанс…';
          document.getElementById('source-session-storage-help').hidden = true;
        }""")
        no_overflow(page, "verified-login-390")
        page.screenshot(path=OUT / "verified-login-390.png", full_page=True)

        page.set_viewport_size({"width": 768, "height": 900})
        page.evaluate("""() => {
          document.getElementById('source-session-login-status').textContent = 'Пароль принят, но Safari пока не разрешил странице использовать защищённый сеанс.';
          document.getElementById('source-session-storage-help').hidden = false;
          const frame = document.getElementById('source-session-storage-frame');
          frame.hidden = false; frame.textContent = 'Здесь Safari покажет отдельную кнопку разрешения доступа.';
        }""")
        page.locator("#source-session-bootstrap").focus()
        assert page.locator("#source-session-bootstrap").evaluate("el => document.activeElement === el")
        no_overflow(page, "storage-access-768")
        page.screenshot(path=OUT / "storage-access-required-768.png", full_page=True)

        page.set_viewport_size({"width": 1280, "height": 900})
        page.evaluate("""() => {
          document.getElementById('source-session-login-dialog').close();
          document.getElementById('source-session-status').textContent = 'Проверка целостности не пройдена. Предыдущая работа сохранена; после восстановления подключения можно повторить.';
          const choice = document.getElementById('workflow-choice'); choice.hidden = false;
          document.getElementById('current-recording-heading').textContent = 'Проверенная тестовая запись';
          document.getElementById('current-recording-state').textContent = '3 дорожки · полный проверенный batch готов';
          document.getElementById('current-recording').dataset.recordingState = 'archive';
        }""")
        no_overflow(page, "ready-error-reconnect-1280")
        page.screenshot(path=OUT / "ready-integrity-reconnect-1280.png", full_page=True)

        context.close()
        browser.close()
    print("S10A visual evidence passed: 320/390/768/1280; no horizontal overflow; focusable primary actions.")


if __name__ == "__main__":
    main()
