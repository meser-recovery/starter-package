#!/usr/bin/env python3
"""Targeted browser regression for a legacy out-of-bounds Speaker global cut.

Uses an in-memory draft and generated WAV files; it never writes to Archive.
"""

import argparse
import json

from playwright.sync_api import sync_playwright


def run(base_url, screenshot=None):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 390, "height": 844})
        login = context.request.post(
            f"{base_url}/v1/session/login",
            data=json.dumps({"password": "local-test-password"}),
            headers={"Content-Type": "application/json", "Origin": base_url},
        )
        assert login.ok, f"preview login returned {login.status}"
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"{base_url}/Audio-Editor.html", wait_until="domcontentloaded")
        result = page.evaluate("""async () => {
          const ids = [
            '11111111-1111-4111-8111-111111111111',
            '22222222-2222-4222-8222-222222222222',
            '33333333-3333-4333-8333-333333333333'
          ];
          const validId = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
          const invalidId = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
          function wav() {
            const rate = 8000, samples = rate * 10, bytes = new ArrayBuffer(44 + samples * 2);
            const view = new DataView(bytes);
            for (const [offset, word] of [[0,'RIFF'],[8,'WAVE'],[12,'fmt '],[36,'data']])
              for (let i = 0; i < 4; i++) view.setUint8(offset + i, word.charCodeAt(i));
            view.setUint32(4, bytes.byteLength - 8, true); view.setUint32(16, 16, true);
            view.setUint16(20, 1, true); view.setUint16(22, 1, true);
            view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true);
            view.setUint16(32, 2, true); view.setUint16(34, 16, true);
            view.setUint32(40, samples * 2, true);
            return bytes;
          }
          const files = ids.map((_, index) => new File([wav()], `test-${index + 1}.wav`, {type:'audio/wav'}));
          const session = {kind:'local', id:'99999999-9999-4999-8999-999999999999', title:'Legacy test', revision:1,
            sourceTracks: ids.map((trackId, index) => ({trackId, ordinal:index + 1, originalName:files[index].name}))};
          const payload = {trackIds:ids, excludedTrackIds:[ids[2]],
            globalCuts:[
              {regionId:validId, startSeconds:1, endSeconds:2},
              {regionId:invalidId, startSeconds:9, endSeconds:12}
            ], trackSilenceRegions:[],
            trackProcessing:ids.map(trackId => ({trackId, enhancement:'off', leveling:'off', compression:'off'}))};
          const draft = {payloadSchema:'speaker/v1', draftRevision:1, payload:structuredClone(payload)};
          const editor = await import('./scripts/speaker-editor.mjs');
          window.__legacyEditor = editor;
          window.__legacySaveCalls = [];
          window.__legacyOpen = () => editor.openSpeakerEditor({session, files, draft,
            waveformProvider: async () => ({duration:10, samples:new Float32Array(65536).fill(.25)}),
            saveDraft: async ({payload:submitted}) => {
              window.__legacySaveCalls.push(structuredClone(submitted));
              return {session:{...session, revision:2}, draft:{...draft, draftRevision:2, payload:structuredClone(submitted)}};
            }});
          const opened = await window.__legacyOpen();
          const state = editor.getSpeakerSaveState();
          const blocked = await editor.saveSpeakerProject();
          return {opened, blocked, saveCalls:window.__legacySaveCalls.length,
            waveformSamples:state.waveformSampleCounts, ready:state.ready,
            activeCuts:state.payload.globalCuts, excluded:state.payload.excludedTrackIds,
            archivedCuts:draft.payload.globalCuts,
            invalidTrackOverlays:document.querySelectorAll(`#speaker-editor-tracks [data-region-id="${invalidId}"]`).length,
            warning:document.getElementById('speaker-editor-legacy-warning').textContent,
            saveDisabled:document.getElementById('speaker-editor-save').disabled};
        }""")
        assert result["opened"] and result["ready"], result
        assert result["waveformSamples"] == [65536, 65536, 65536], result
        assert len(result["activeCuts"]) == 1 and result["activeCuts"][0]["startSeconds"] == 1, result
        assert len(result["archivedCuts"]) == 2 and result["excluded"] == ["33333333-3333-4333-8333-333333333333"], result
        assert result["invalidTrackOverlays"] == 0 and "вырез 2" in result["warning"], result
        assert result["saveDisabled"] and result["blocked"] is False and result["saveCalls"] == 0, result
        if screenshot:
            page.screenshot(path=screenshot, full_page=True)
        page.locator(".speaker-regions summary").click()
        page.get_by_role("button", name="Удалить проблемный вырез").click()
        assert not page.locator("#speaker-editor-save").is_disabled()
        saved = page.evaluate("""async () => {
          const result = await window.__legacyEditor.saveSpeakerProject();
          return {result, calls:window.__legacySaveCalls, warningHidden:document.getElementById('speaker-editor-legacy-warning').hidden};
        }""")
        assert saved["result"] and saved["warningHidden"] and len(saved["calls"]) == 1, saved
        assert len(saved["calls"][0]["globalCuts"]) == 1 and saved["calls"][0]["globalCuts"][0]["startSeconds"] == 1, saved
        assert saved["calls"][0]["excludedTrackIds"] == ["33333333-3333-4333-8333-333333333333"], saved
        assert page.evaluate("window.__legacyOpen()")
        page.locator(".speaker-regions").evaluate("element => { element.open = true; }")
        page.get_by_role("button", name="Исправить границы").click()
        assert page.locator("#speaker-editor-save").is_disabled()
        page.get_by_role("spinbutton", name="Глобальный вырез 2, конец в секундах").fill("9.5")
        page.get_by_role("button", name="Исправить границы").click()
        corrected = page.evaluate("""() => ({
          cuts:window.__legacyEditor.getSpeakerSaveState().payload.globalCuts,
          warningHidden:document.getElementById('speaker-editor-legacy-warning').hidden,
          saveDisabled:document.getElementById('speaker-editor-save').disabled
        })""")
        assert corrected["warningHidden"] and not corrected["saveDisabled"] and len(corrected["cuts"]) == 2, corrected
        assert corrected["cuts"][1]["endSeconds"] == 9.5, corrected
        assert page.evaluate("window.__legacyEditor.saveSpeakerProject()")
        assert len(page.evaluate("window.__legacySaveCalls")) == 2
        assert not errors, errors
        browser.close()
    print("S10A legacy Speaker state browser regression: PASS; three waveforms, valid edits preserved, explicit remove/correct before in-memory save, ARCHIVE_MUTATIONS=0")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:4179")
    parser.add_argument("--screenshot")
    args = parser.parse_args()
    run(args.base_url.rstrip("/"), args.screenshot)
