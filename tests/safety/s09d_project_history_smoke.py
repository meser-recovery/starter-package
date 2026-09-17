#!/usr/bin/env python3
"""Focused browser checks for S10 capability fail-closed behavior and recovery controls."""
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
            capability = page.evaluate("""async () => {
                const calls = [];
                const fetchImpl = async (input, options = {}) => {
                    calls.push({url: String(input), method: options.method || 'GET'});
                    return new Response(JSON.stringify(String(input).endsWith('/v1/config') ?
                        {schemaVersion: 1, acceptedPartSize: 4} : {}), {status: 200, headers: {'Content-Type': 'application/json'}});
                };
                const {AudioArchiveGateway, sha256Hex, verifyLocalSourceAttachment} = await import('./scripts/audio-archive-client.mjs');
                const {createSpeakerRecoveryAttempt} = await import('./scripts/audio-archive-core.mjs');
                const {ingestSpeakerRecoverySources, ProjectSave} = await import('./scripts/audio-project.mjs');
                const gateway = new AudioArchiveGateway('https://incompatible.example', fetchImpl);
                await gateway.configuration();
                const file = new File(['source'], 'source.wav', {type: 'audio/wav'});
                const result = new Blob(['result'], {type: 'audio/mpeg'});
                const project = {cuts: [{start: 1, end: 2}]};
                const recoveryFile = new File(['exact recovery bytes'], 'renamed-recovery.wav', {type: 'audio/wav'});
                const recoveryBytes = new Uint8Array(await recoveryFile.arrayBuffer());
                const recoveryWork = {sources: [{trackId: '22222222-2222-4222-8222-222222222222',
                    blobId: '33333333-3333-4333-8333-333333333333', ordinal: 1, originalName: 'deleted-source.wav',
                    mediaType: 'audio/wav', sizeBytes: recoveryFile.size, sha256: await sha256Hex(recoveryBytes)}],
                    continuation: {sourceDraftRevision: 4, sourceOutputId: null}, project: {cuts: [{start: 2, end: 3}]}};
                const keys = ['recovery-ingestion-key', 'recovery-continuation-key'];
                const recovery = createSpeakerRecoveryAttempt({id: '11111111-1111-4111-8111-111111111111', title: 'Deleted source'},
                    recoveryWork, () => keys.shift());
                recovery.files = await verifyLocalSourceAttachment([recoveryFile], recovery.work.sources);
                let recoveryMessage = '';
                try { await ingestSpeakerRecoverySources(gateway, recovery); } catch (error) { recoveryMessage = error.userMessage || error.message; }
                const messages = [];
                for (const action of [
                    async () => gateway.saveDraft('11111111-1111-4111-8111-111111111111', 'speaker', {}),
                    async () => gateway.saveSpeaker({sessionId: '11111111-1111-4111-8111-111111111111', blob: result, recipe: {schemaVersion: 1}}),
                    async () => gateway.continueSpeakerProject('11111111-1111-4111-8111-111111111111', {}),
                    async () => new ProjectSave(gateway).sources({title: 'local'}, [file])
                ]) try { await action(); } catch (error) { messages.push(error.message); }
                await gateway.getSpeakerOutput('11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222');
                await gateway.saveDraft('11111111-1111-4111-8111-111111111111', 'announcement', {});
                return {calls, messages, fileSize: file.size, resultSize: result.size, project, recoveryMessage,
                    recovery: {sameFile: recovery.files[0] === recoveryFile, fileSize: recovery.files[0].size,
                        work: recovery.work, target: recovery.target, ingestionKey: recovery.ingestionKey,
                        continuationKey: recovery.continuationKey, continuationRequest: recovery.continuationRequest}};
            }""")
            assert len(capability["messages"]) == 4 and all("несовместима" in message for message in capability["messages"]), capability
            assert "несовместима" in capability["recoveryMessage"], capability
            mutations = [call for call in capability["calls"] if call["method"] in ("PUT", "POST")]
            assert len(mutations) == 1 and mutations[0]["url"].endswith("/drafts/announcement"), mutations
            assert capability["fileSize"] == 6 and capability["resultSize"] == 6
            assert capability["project"] == {"cuts": [{"start": 1, "end": 2}]}
            assert capability["recovery"] == {"sameFile": True, "fileSize": 20,
                "work": {"sources": [{"trackId": "22222222-2222-4222-8222-222222222222",
                    "blobId": "33333333-3333-4333-8333-333333333333", "ordinal": 1,
                    "originalName": "deleted-source.wav", "mediaType": "audio/wav", "sizeBytes": 20,
                    "sha256": capability["recovery"]["work"]["sources"][0]["sha256"]}],
                    "continuation": {"sourceDraftRevision": 4, "sourceOutputId": None},
                    "project": {"cuts": [{"start": 2, "end": 3}]}},
                "target": None, "ingestionKey": "recovery-ingestion-key",
                "continuationKey": "recovery-continuation-key", "continuationRequest": None}
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

    print("S10 project history smoke passed: 1280, 768, 390 and 320 px; recovery ingestion and other incompatible-gateway writes fail closed; local recovery state retained; conflict keyboard controls.")


if __name__ == "__main__":
    main()
