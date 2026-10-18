import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { once } from 'node:events';
import { createApp } from '../src/app.mjs';
import { createPasswordVerifier } from '../src/auth.mjs';
import { nodeHandler } from '../src/http-adapter.mjs';
import { GitHubArchiveRepository } from '../src/github.mjs';
import { sourceFixture } from './s13-fixtures.mjs';
const listen = async server => { server.listen(0, '127.0.0.1'); await once(server, 'listening'); return `http://127.0.0.1:${server.address().port}`; };
const close = server => new Promise(resolve => { server.close(resolve); server.closeAllConnections(); });
const deadline = promise => Promise.race([promise, new Promise((_, reject) => { const timer = setTimeout(() => reject(new Error('Upstream did not stop after client cancellation')), 2000); timer.unref(); })]);

test('S13 actual HTTP source cancellation reaches GitHub asset reader and permits verified retry', async () => {
  const h = await sourceFixture({ tracks: 1 }), track = h.session.sourceTracks[0], part = track.parts[0];
  const bytes = h.repository.assetBytes.get(part.assetId); let opened, stopped, hold = true, active = 0, sent = 0;
  const opening = new Promise(resolve => { opened = resolve; }), stopping = new Promise(resolve => { stopped = resolve; });
  const upstream = http.createServer((_request, response) => {
    active++; response.once('close', () => { active--; stopped(); });
    response.writeHead(200, { 'Content-Type': 'application/octet-stream', 'Content-Length': String(bytes.length) });
    if (hold) { response.write(bytes.subarray(0, 1)); sent++; opened(); }
    else response.end(bytes);
  });
  const upstreamUrl = await listen(upstream);
  const remote = new GitHubArchiveRepository({ storageOwner: 'meser-recovery', storageRepository: 'audio-archive', storageBranch: 'main' },
    (_url, options) => fetch(upstreamUrl, options));
  remote.installationToken = { value: 'synthetic', expiresAt: Number.MAX_SAFE_INTEGER };
  h.repository.downloadReleaseAsset = (id, signal) => { assert.equal(id, part.assetId); return remote.downloadReleaseAsset(id, signal); };
  const verifier = await createPasswordVerifier('synthetic-password', Buffer.alloc(16, 3), { N: 16384, r: 8, p: 1 });
  const app = createApp({ config: { allowedOrigin: 'https://site.test', acceptedPartBytes: 4,
    sharedPasswordVerifier: verifier, sessionSigningSecret: 's13-synthetic-session-key-0000000000', sessionLifetimeSeconds: 3600 }, domain: h.domain });
  const gateway = http.createServer(nodeHandler(app)), gatewayUrl = await listen(gateway);
  try {
    const login = await fetch(gatewayUrl + '/v1/session/login', { method: 'POST', headers: { Origin: 'https://site.test', 'Content-Type': 'application/json' }, body: JSON.stringify({ password: 'synthetic-password' }) });
    assert.equal(login.status, 200);
    const headers = { Origin: 'https://site.test', Cookie: login.headers.get('set-cookie').split(';')[0] };
    const url = `${gatewayUrl}/v1/source-sessions/${h.session.id}/blobs/${track.blobId}/parts/1/content`;
    const controller = new AbortController();
    const request = fetch(url, { headers, signal: controller.signal }).then(response => response.arrayBuffer());
    const rejected = assert.rejects(request, error => error.name === 'AbortError');
    await deadline(opening); controller.abort(); await rejected; await deadline(stopping);
    assert.equal(active, 0); assert.equal(sent, 1, 'cancel must not finish the held source part');
    hold = false;
    const retried = await fetch(url, { headers }); assert.equal(retried.status, 200);
    assert.deepEqual(Buffer.from(await retried.arrayBuffer()), bytes);
  } finally { await close(gateway); await close(upstream); }
});
