#!/usr/bin/env python3
"""Focused browser shell checks for S09D capability fallback and recovery controls."""
from __future__ import annotations

import argparse
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


def assert_no_overflow(page, width, label):
    result = page.evaluate("""() => ({viewport: innerWidth, document: document.documentElement.scrollWidth,
      offenders: [...document.querySelectorAll('main, main *, dialog[open], dialog[open] *')].map(node => {
        const box = node.getBoundingClientRect(), style = getComputedStyle(node);
        return {id: node.id, left: box.left, right: box.right, width: box.width,
          visible: style.display !== 'none' && style.visibility !== 'hidden' && box.height > 0};
      }).filter(item => item.visible && (item.left < -1 || item.right > innerWidth + 1)).slice(0, 10)});""")
    assert result["document"] <= width + 1, (label, result)
    assert not result["offenders"], (label, result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    gateway_requests = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width in (1280, 768, 390, 320):
            context = browser.new_context(viewport={"width": width, "height": 900})
            context.add_init_script("sessionStorage.setItem('meser_service_access_v1', 'granted')")

            def route_request(route):
                parsed = urlparse(route.request.url)
                if route.request.url.startswith(base + "/"):
                    route.continue_()
                    return
                gateway_requests.append(parsed.path)
                headers = {"Access-Control-Allow-Origin": base, "Access-Control-Allow-Credentials": "true",
                           "Content-Type": "application/json"}
                if parsed.path == "/v1/config":
                    route.fulfill(status=200, headers=headers, body='{"schemaVersion":1,"acceptedPartSize":16777216,"maximumPartSize":67108864,"maximumSessionSize":524288000}')
                else:
                    route.fulfill(status=401, headers=headers, body='{"error":"Archive session is required"}')

            context.route("**/*", route_request)
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base + "/Audio-Editor.html")
            page.wait_for_load_state("networkidle")
            assert page.locator("#speaker-project-recovery").count() == 1
            assert page.locator("#speaker-editor-project-history").is_hidden()
            page.evaluate("document.getElementById('speaker-save-conflict-dialog').showModal()")
            assert page.get_by_role("button", name="Открыть последнее сохранённое состояние").is_visible()
            assert page.get_by_role("button", name="Оставить мои изменения на этом устройстве").is_visible()
            assert page.get_by_role("button", name="Сохранить мои изменения как новое состояние проекта").is_visible()
            page.get_by_role("button", name="Оставить мои изменения на этом устройстве").focus()
            assert page.evaluate("document.activeElement.id") == "speaker-save-conflict-keep"
            assert_no_overflow(page, width, f"conflict-{width}")
            assert not errors, errors
            context.close()

        assert not any("/projects/" in path for path in gateway_requests), gateway_requests
        browser.close()

    print("S09D project history smoke passed: 1280, 768, 390 and 320 px; old-gateway fallback; conflict keyboard controls.")


if __name__ == "__main__":
    main()
