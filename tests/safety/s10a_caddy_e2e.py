#!/usr/bin/env python3
"""Caddy-backed S10A runtime proof with synthetic data and no archive writes."""

from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path
import re
import struct
import wave

from playwright.sync_api import expect, sync_playwright


PASSWORD = "synthetic-caddy-password"
LONG_M4A = Path(__file__).parent / "fixtures" / "s10a-long-aac-lc-3747s.m4a"


def wav_fixture() -> bytes:
    output = BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(struct.pack("<" + "h" * 24_000, *([0] * 24_000)))
    return output.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context()
        request = context.request

        redirect = request.get(base + "/Audio-Editor.html?workflow=announcement", max_redirects=0)
        assert redirect.status == 303, redirect.status
        assert redirect.headers["location"] == "/login?return=%2FAudio-Editor.html%3Fworkflow%3Dannouncement"
        assert request.get(base + "/scripts/audio-processor.mjs", max_redirects=0).status == 401
        assert request.get(base + "/v1/config", max_redirects=0).status == 401
        assert request.get(base + "/internal/auth-check", max_redirects=0).status == 404

        page = context.new_page()
        response = page.goto(base + redirect.headers["location"], wait_until="domcontentloaded")
        assert response is not None
        csp = response.headers.get("content-security-policy", "")
        assert "'wasm-unsafe-eval'" in csp
        assert "'unsafe-eval'" not in csp
        page.locator("#admin-password").fill(PASSWORD)
        page.locator("#admin-access-form button[type=submit]").click()
        page.wait_for_url("**/Audio-Editor.html?workflow=announcement")
        page.get_by_role("heading", name="Редактирование аудио", exact=True).wait_for()
        api = page.evaluate("async () => { const r = await fetch('/v1/config'); return [r.status, await r.json()]; }")
        assert api[0] == 200 and api[1]["schemaVersion"] == 1

        page.evaluate("""() => { const input = document.createElement('input'); input.type = 'file';
            input.id = 's10a-long-waveform-fixture'; document.body.appendChild(input); }""")
        page.locator("#s10a-long-waveform-fixture").set_input_files(LONG_M4A)
        waveform = page.evaluate("""async () => {
          const diagnostics = [];
          const { createWaveformReader } = await import('/scripts/speaker-waveform.mjs');
          const input = document.getElementById('s10a-long-waveform-fixture');
          const reader = createWaveformReader(undefined, null, { onDiagnostic: value => diagnostics.push(value) });
          try {
            const peaks = await reader.read(input.files[0], 3747.648, { trackIndex: 1 });
            return { peaks: peaks.length, diagnostics };
          } finally { reader.dispose(); input.remove(); }
        }""")
        assert waveform == {"peaks": 65536, "diagnostics": []}, waveform

        page.locator("#source-session-mode-device").click()
        page.locator("#processor-file").set_input_files({
            "name": "caddy-wasm.wav", "mimeType": "audio/wav", "buffer": wav_fixture()
        })
        page.locator("#source-session-use-local").wait_for(state="visible", timeout=30_000)
        expect(page.locator("#source-session-use-local")).to_be_enabled(timeout=30_000)
        page.locator("#source-session-use-local").click()
        page.locator("#workflow-choice").wait_for(state="visible", timeout=30_000)
        page.locator("#open-local-announcement").click()
        page.locator("#processor-run").wait_for(state="visible", timeout=30_000)
        expect(page.locator("#processor-run")).to_be_enabled(timeout=30_000)
        page.locator("#processor-run").click()
        page.locator("#processor-result").wait_for(state="visible", timeout=120_000)
        expect(page.locator("#processor-status")).to_have_text(
            re.compile(r"^(?:Готово\.|Длинные паузы не найдены\. Файл не изменён\.)$"),
            timeout=120_000,
        )
        result = page.evaluate("() => window.__lastCaddyWasmResult || ({ href: document.getElementById('processor-download').href, status: document.getElementById('processor-status').textContent })")
        assert result["href"].startswith("blob:"), result
        assert result["status"] in ("Готово.", "Длинные паузы не найдены. Файл не изменён."), result

        page.locator("#service-logout").click()
        page.wait_for_url("**/login")
        assert request.get(base + "/v1/session", max_redirects=0).status == 401
        assert request.get(base + "/Audio-Editor.html", max_redirects=0).status == 303
        context.close()
        browser.close()
    print("Caddy-backed auth, protected routes, bounded long-audio waveform, logout and FFmpeg/WASM processing: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
