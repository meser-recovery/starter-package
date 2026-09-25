#!/usr/bin/env python3
"""Targeted Editor save/reopen regression with one source and differing browser durations.

Uses generated in-memory WAV files and a verified-waveform stub; no Archive writes.
"""

import argparse
import json

from playwright.sync_api import sync_playwright


def run(base_url):
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
          function wav() {
            const rate = 8000, samples = rate * 10, bytes = new ArrayBuffer(44 + samples * 2);
            const view = new DataView(bytes);
            for (const [offset, word] of [[0,'RIFF'],[8,'WAVE'],[12,'fmt '],[36,'data']])
              for (let index = 0; index < 4; index++) view.setUint8(offset + index, word.charCodeAt(index));
            view.setUint32(4, bytes.byteLength - 8, true); view.setUint32(16, 16, true);
            view.setUint16(20, 1, true); view.setUint16(22, 1, true);
            view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true);
            view.setUint16(32, 2, true); view.setUint16(34, 16, true);
            view.setUint32(40, samples * 2, true);
            return bytes;
          }
          const files = ids.map((_, index) => new File([wav()], `source-${index + 1}.wav`, {type:'audio/wav'}));
          const baseSession = {id:'99999999-9999-4999-8999-999999999999', title:'Canonical timeline test', revision:1,
            lifecycle:{state:'incoming'}, sourceState:'available',
            sourceTracks:ids.map((trackId, index) => ({trackId, ordinal:index + 1, originalName:files[index].name}))};
          let browserDuration = 10.4;
          Object.defineProperty(HTMLMediaElement.prototype, 'duration', {
            configurable:true, get() { return browserDuration; }
          });
          const editor = await import('./scripts/speaker-editor.mjs');
          const waveformProvider = async () => ({duration:10, samples:new Float32Array(65536).fill(.25)});
          const results = [];
          let saveCalls = 0;
          for (const [name, boundaries] of [
            ['start', ['start']], ['end', ['end']], ['start+end', ['start','end']]
          ]) {
            browserDuration = 10.4;
            const session = structuredClone(baseSession);
            const saveDraft = async ({payload}) => {
              saveCalls += 1;
              return {session:{...session, revision:2}, draft:{payloadSchema:'speaker/v1', draftRevision:1,
                payload:structuredClone(payload)}};
            };
            if (!await editor.openSpeakerEditor({session, files, waveformProvider, saveDraft})) throw Error(`${name}: desktop open failed`);
            for (const kind of boundaries) {
              const start = document.getElementById('speaker-editor-selection-start');
              const end = document.getElementById('speaker-editor-selection-end');
              start.value = kind === 'start' ? '2' : '7';
              end.value = kind === 'start' ? '3' : '8';
              start.dispatchEvent(new Event('input', {bubbles:true}));
              end.dispatchEvent(new Event('input', {bubbles:true}));
              const action = document.getElementById(`speaker-editor-set-${kind}`);
              if (action.disabled) throw Error(`${name}: ${kind} action disabled`);
              action.click();
            }
            if (!await editor.saveSpeakerProject()) throw Error(`${name}: explicit project save failed`);
            const saved = structuredClone(editor.getSpeakerSaveState().draft.payload);
            browserDuration = 9.9;
            if (!await editor.openSpeakerEditor({session:{...session, revision:2}, files,
                draft:{payloadSchema:'speaker/v1', draftRevision:1, payload:saved}, waveformProvider, saveDraft})) {
              throw Error(`${name}: mobile reopen failed`);
            }
            const reopened = editor.getSpeakerSaveState();
            results.push({name, desktopDuration:10.4, canonicalDuration:reopened.originalDuration,
              mobileDuration:browserDuration, cuts:saved.globalCuts, waveforms:reopened.waveformSampleCounts,
              ready:reopened.ready, warningHidden:document.getElementById('speaker-editor-legacy-warning').hidden,
              saveCalls});
          }
          return {results, saveCalls};
        }""")
        assert result["saveCalls"] == 3, result
        for index, item in enumerate(result["results"], 1):
            assert item["canonicalDuration"] == 10 and item["mobileDuration"] == 9.9, item
            assert item["ready"] and item["warningHidden"], item
            assert item["waveforms"] == [65536, 65536, 65536], item
            assert item["saveCalls"] == index, item
            if item["name"] in ("end", "start+end"):
                assert any(cut["startSeconds"] == 8 and cut["endSeconds"] == 10 for cut in item["cuts"]), item
        assert not errors, errors
        browser.close()
    print("S10A canonical Source Session timeline browser regression: PASS; start/end save/reopen, three waveforms, 3 explicit mock saves, ARCHIVE_MUTATIONS=0")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:4181")
    args = parser.parse_args()
    run(args.base_url.rstrip("/"))
