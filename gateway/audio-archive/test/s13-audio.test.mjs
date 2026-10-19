import test from 'node:test';
import assert from 'node:assert/strict';
import { reconstructSessionTracks, prepareRemoteSourceBatch, AudioArchiveGateway } from '../../../service/frontend/scripts/audio-archive-client.mjs';
import { sourceFixture } from './s13-fixtures.mjs';

test('S13 global two-slot queue overlaps tracks/parts; delayed first part cannot grow reorder buffers', async () => {
  const h = await sourceFixture(), resources = [], progress = [];
  let active = 0, max = 0, calls = 0;
  const firstUrl = h.session.sourceTracks[0].parts[0].downloadUrl;
  const files = await reconstructSessionTracks(h.session, async (url, { signal }) => {
    calls++; active++; max = Math.max(max, active);
    await new Promise(resolve => setTimeout(resolve, url === firstUrl ? 30 : 2));
    active--; assert.equal(signal.aborted, false); return h.fetchPart(url);
  }, { onResources: event => resources.push(event), onProgress: event => progress.push(event) });
  assert.equal(max, 2); assert.equal(calls, h.session.sourceTracks.reduce((n, track) => n + track.parts.length, 0));
  assert.ok(resources.every(r => r.reservedParts <= 2 && r.reservedPartBytes <= 8));
  assert.equal(resources.at(-1).reservedParts, 0); assert.equal(resources.at(-1).activeTransfers, 0);
  for (let i = 0; i < files.length; i++) {
    assert.deepEqual(Buffer.from(await files[i].arrayBuffer()), h.originals[i]); assert.equal(files[i].name, h.session.sourceTracks[i].originalName);
  }
  assert.ok(progress.every((p, i) => !i || p.verifiedBytes >= progress[i - 1].verifiedBytes));
  assert.equal(progress.at(-1).verifiedBytes, progress.at(-1).totalBytes);
});

test('S13 corruption, oversize/short response, whole hash mismatch, reordered/missing/duplicate identities never become ready', async () => {
  const h = await sourceFixture();
  for (const bytes of [Buffer.alloc(4, 99), Buffer.alloc(5), Buffer.alloc(1)]) {
    await assert.rejects(() => reconstructSessionTracks(h.session, async () => new Response(bytes)));
  }
  const changed = structuredClone(h.session); changed.sourceTracks[0].sha256 = '0'.repeat(64);
  await assert.rejects(() => reconstructSessionTracks(changed, h.fetchPart), /целостности/);
  for (const change of [s => s.sourceTracks[0].parts.reverse(), s => s.sourceTracks[0].parts.pop(),
    s => s.sourceTracks[1].blobId = s.sourceTracks[0].blobId, s => s.sourceTracks[1].parts[0].assetId = s.sourceTracks[0].parts[0].assetId]) {
    const invalid = structuredClone(h.session); change(invalid); let calls = 0;
    await assert.rejects(() => reconstructSessionTracks(invalid, async () => { calls++; return new Response(); })); assert.equal(calls, 0);
  }
});

test('S13 abort stops active fetch, schedules nothing new, drains slots and permits retry; late response ignored', async () => {
  const h = await sourceFixture(), controller = new AbortController(), events = [];
  let calls = 0, stopped = 0;
  const start = performance.now();
  const work = reconstructSessionTracks(h.session, async (url, { signal }) => {
    calls++;
    await new Promise(resolve => { signal.addEventListener('abort', () => { stopped++; resolve(); }, { once: true }); });
    return h.fetchPart(url); // Deliberately late bytes after abort.
  }, { signal: controller.signal, onResources: e => events.push(e) });
  await new Promise(r => setTimeout(r, 5)); controller.abort();
  await assert.rejects(() => work, e => e.name === 'AbortError');
  assert.ok(performance.now() - start < 250); assert.equal(calls, 2); assert.equal(stopped, 2); assert.equal(events.at(-1).reservedParts, 0);
  assert.equal((await reconstructSessionTracks(h.session, h.fetchPart)).length, 3);
});

test('S13 verified current batch reuse confirms initial/final access and survives metadata-only revision; source/auth change invalidates', async () => {
  const h = await sourceFixture(); let calls = 0, reads = 0, manifest = h.session;
  const gateway = { authGeneration: 0, getSession: async () => { reads++; return structuredClone(manifest); }, sourcePartFetch: () => async url => { calls++; return h.fetchPart(url); } };
  const batch = await prepareRemoteSourceBatch({ gateway, sessionId: h.session.id });
  const coldCalls = calls; assert.ok(coldCalls > 0); assert.equal(reads, 2);
  manifest = { ...manifest, title: 'Новое название', revision: manifest.revision + 1 };
  const warm = await prepareRemoteSourceBatch({ gateway, sessionId: manifest.id, reuseBatch: batch });
  assert.equal(warm.reused, true); assert.equal(warm.files, batch.files); assert.equal(calls, coldCalls); assert.equal(reads, 4);
  gateway.authGeneration++;
  const reauth = await prepareRemoteSourceBatch({ gateway, sessionId: manifest.id, reuseBatch: warm });
  assert.equal(reauth.reused, false); assert.equal(calls, coldCalls * 2);
  manifest = { ...manifest, lifecycle: { state: 'archived' } };
  await assert.rejects(() => prepareRemoteSourceBatch({ gateway, sessionId: manifest.id, reuseBatch: reauth }), /доступна/);
  gateway.getSession = async () => { throw Object.assign(new Error('gone'), { status: 404 }); };
  await assert.rejects(() => prepareRemoteSourceBatch({ gateway, sessionId: manifest.id, reuseBatch: reauth }), e => e.status === 404);
});

test('S13 a final source change and auth failure during transfer reject the entire batch', async () => {
  const h = await sourceFixture(); let reads = 0;
  const changed = structuredClone(h.session); changed.sourceTracks[0].sha256 = '0'.repeat(64);
  const gateway = { authGeneration: 0, getSession: async () => ++reads === 1 ? h.session : changed, sourcePartFetch: () => h.fetchPart };
  await assert.rejects(() => prepareRemoteSourceBatch({ gateway, sessionId: h.session.id }), e => e.code === 'remote_source_changed');
  gateway.getSession = async () => h.session;
  gateway.sourcePartFetch = () => async () => new Response(null, { status: 401 });
  await assert.rejects(() => prepareRemoteSourceBatch({ gateway, sessionId: h.session.id }));
});

test('S13 rapid source intents drain earlier transfers before starting another two-slot batch', async () => {
  const h = await sourceFixture(); let active = 0, max = 0, calls = 0;
  const gateway = { authGeneration: 0, getSession: async () => h.session, sourcePartFetch: () => async (url, { signal }) => {
    active++; max = Math.max(max, active); calls++;
    await new Promise(resolve => { const timer = setTimeout(resolve, 5); signal.addEventListener('abort', () => { clearTimeout(timer); resolve(); }, { once: true }); });
    active--; return h.fetchPart(url);
  } };
  const first = prepareRemoteSourceBatch({ gateway, sessionId: h.session.id });
  const settled = Promise.allSettled([first]);
  await new Promise(r => setTimeout(r, 1));
  const second = await prepareRemoteSourceBatch({ gateway, sessionId: h.session.id });
  assert.equal((await settled)[0].status, 'rejected'); assert.equal(second.files.length, 3); assert.equal(max, 2); assert.equal(active, 0);
});

test('S13 auth loss keeps status 401 even if cancellation of the error body also fails', async () => {
  const h = await sourceFixture();
  const gateway = new AudioArchiveGateway('https://synthetic.test', async () => new Response(new ReadableStream({
    cancel() { throw new DOMException('Body already aborted', 'AbortError'); }
  }), { status: 401 }));
  gateway.getSession = async () => h.session;
  await assert.rejects(() => prepareRemoteSourceBatch({ gateway, sessionId: h.session.id }), e => e.status === 401);
  assert.ok(gateway.authGeneration > 0); assert.equal(gateway.activeSourcePreparation, null);
});
