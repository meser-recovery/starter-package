import test from 'node:test';
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { AudioArchiveDomain } from '../src/domain.mjs';
import { ZoomArchive } from '../src/zoom-archive.mjs';
import { createApp } from '../src/app.mjs';
import { SessionRegistry, createSession } from '../src/auth.mjs';
import { SETTINGS_PATH, encryptSettings, decryptSettings, connectionFingerprint, importPath, opaqueIdentity } from '../src/settings.mjs';
import { createIngestionPlan, serializeIngestionPlan } from '../../../service/frontend/scripts/audio-archive-client.mjs';
import { A, B, CONNECTION, SyntheticZoom, SyntheticArchiveRepository } from './s12-fixtures.mjs';

const key = Buffer.alloc(32, 47), origin = 'https://synthetic.test';
const forbidden = e => e.status === 409;
function instance(repository, zoom = new SyntheticZoom()) {
  const domain = new AudioArchiveDomain(repository, { acceptedPartBytes: 1024 });
  const service = new ZoomArchive(domain, { key, zoom });
  return { repository, domain, service, zoom };
}
async function fixture(repository = new SyntheticArchiveRepository()) {
  const t = instance(repository);
  t.profiles = [CONNECTION, { ...CONNECTION, connectionId: randomUUID(), accountId: 'synthetic-b', name: 'Synthetic B' }].map(c => ({ ...c, revision: 1, verification: { fingerprint: connectionFingerprint(c), checkedAt: '2026-10-26T10:00:00Z', tracks: 'confirmed' } }));
  await context(t, 0);
  const calendar = await t.service.calendar('2026-10');
  t.op = await t.service.reserve({ id: calendar.recordings[0].id, month: '2026-10', settingsRevision: calendar.settingsRevision });
  t.plan = await createIngestionPlan([A, B].map(b => new File([b], 'participant.m4a', { type: 'audio/mp4' })), 1024, { idempotencyKey: t.op.idempotencyKey });
  return t;
}
async function context(t, index, change = () => {}) {
  const settings = t.repository.files.has(SETTINGS_PATH) ? decryptSettings(t.repository.files.get(SETTINGS_PATH), key) : { version: 1, revision: 0, lastMutationId: null, connections: t.profiles, storage: { softLimitBytes: 50e9, warningPercent: 80 } };
  settings.revision++; settings.activeConnectionId = index === null ? null : t.profiles[index].connectionId;
  change(settings);
  await t.repository.commitJson(await t.repository.getHead(), { [SETTINGS_PATH]: encryptSettings(settings, key) }, 'Synthetic settings change');
  return settings;
}
async function upload(t, limit = Infinity) {
  await t.service.bind(t.op.id, { plan: serializeIngestionPlan(t.plan) });
  let n = 0;
  for (const track of t.plan.tracks) for (const part of track.parts) {
    if (n++ >= limit) return;
    await t.domain.uploadPart(t.op.transactionId, track.blobId, part.partNumber, Buffer.from(await part.blob.arrayBuffer()), part.sha256, randomUUID());
  }
}
function effects(t) { return JSON.stringify({ files: [...t.repository.files], commits: t.repository.commits.length, releases: [...t.repository.releases], bytes: [...t.repository.assetBytes] }); }
function api(t) {
  const registry = new SessionRegistry(), secret = 'synthetic-session-secret-0000000000000', created = createSession(secret, 3600, registry);
  const app = createApp({ domain: t.domain, zoomArchive: t.service, sessionRegistry: registry, config: { allowedOrigin: origin, acceptedPartBytes: 1024, sessionSigningSecret: secret } });
  return async (path, method = 'GET', body, extra = {}) => app(new Request(origin + path, { method, headers: { cookie: created.cookie.split(';')[0], origin, 'x-csrf-token': created.session.csrfToken, 'content-type': 'application/json', ...extra }, body: body === undefined ? undefined : Buffer.isBuffer(body) ? body : JSON.stringify(body) }));
}
function countZoom(t) {
  const counts = { list: 0, recording: 0, download: 0 };
  for (const name of Object.keys(counts)) { const fn = t.zoom[name].bind(t.zoom); t.zoom[name] = (...args) => { counts[name]++; return fn(...args); }; }
  return counts;
}
function barrier(object, method, match = () => true) {
  const fn = object[method].bind(object); let release, entered;
  const waiting = new Promise(r => { entered = r; }); let used = false;
  object[method] = async (...args) => {
    if (!used && match(...args)) { used = true; entered(); await new Promise(r => { release = r; }); }
    return fn(...args);
  };
  return { waiting, release: () => release() };
}

// Hold the resolved immutable storage response, after its HEAD/data were captured.
function settingsResponseBarrier(repository, nth) {
  const read = repository.readJson.bind(repository); let count = 0, entered, release;
  const waiting = new Promise(r => { entered = r; }), blocked = new Promise(r => { release = r; });
  repository.readJson = async (path, ref) => {
    const result = await read(path, ref);
    if (path === SETTINGS_PATH && ++count === nth) { entered(); await blocked; }
    return result;
  };
  return { waiting, release };
}

test('FIX ACCEPT F1: settings authority changes while an immutable guard read is held', async tcase => {
  for (const phase of ['operation', 'calendar', 'download', 'upload', 'disabled-calendar']) await tcase.test(phase, { timeout: 10000 }, async () => {
    const t = await fixture(), second = instance(t.repository), request = api(t);
    if (phase === 'upload') await upload(t, 0);
    if (phase === 'disabled-calendar') await t.service.discard(t.op.id);
    const track = t.plan.tracks[0], part = track.parts[0], bytes = Buffer.from(await part.blob.arrayBuffer());
    // Calendar's final read is #2; the other cases hold guard #3 immediately
    // before returning the DTO, requesting metadata, or uploading an asset.
    const gate = settingsResponseBarrier(t.repository, phase.includes('calendar') ? 2 : 3), counts = countZoom(t);
    const before = effects(t);
    const action = phase === 'operation' ? () => request(`/v1/zoom/imports/${t.op.id}`)
      : phase.includes('calendar') ? () => t.service.calendar('2026-10')
      : phase === 'download' ? () => t.service.download(t.op.id, 'file-1')
      : () => request(`/v1/source-sessions/ingestions/${t.op.transactionId}/blobs/${track.blobId}/parts/${part.partNumber}`, 'PUT', bytes,
        { 'content-type': 'application/octet-stream', 'x-part-sha256': part.sha256, 'idempotency-key': randomUUID() });
    const pending = action().then(value => ({ value }), error => ({ error }));
    await gate.waiting;
    // Use the real settings mutation path on another Gateway instance.
    await second.service.mutate({ revision: 1, mutationId: randomUUID(), action: phase === 'disabled-calendar' ? 'disable' : 'activate',
      connectionId: t.profiles[phase === 'disabled-calendar' ? 0 : 1].connectionId, confirmed: true });
    const afterMutation = effects(t);
    assert.notEqual(afterMutation, before);
    gate.release();
    const { value, error } = await pending;
    assert.equal(error?.status ?? value?.status, 409, phase);
    if (value) assert.ok(!(await value.text()).includes('participant.m4a'));
    assert.equal(effects(t), afterMutation, 'no archive effect after the authority switch');
    assert.deepEqual(counts, { list: 0, recording: 0, download: 0 });
  });
});

test('FIX ACCEPT F1: an unrelated archive commit during a settings read preserves the coherent snapshot', async () => {
  const t = await fixture(), head = await t.repository.getHead(), gate = settingsResponseBarrier(t.repository, 1);
  const pending = t.service.settingsSnapshot(head);
  await gate.waiting;
  await t.repository.commitJson(head, { 'synthetic-unrelated.json': { value: 1 } }, 'Synthetic unrelated archive commit');
  gate.release();
  const snapshot = await pending;
  assert.equal(snapshot.head, head);
  assert.equal(snapshot.settings.revision, 1);
  assert.equal((await t.service.ordinaryOperation(t.op.id)).id, t.op.id);
});

test('FIX A01-A04: exact ownership in every durable state, Moscow months, warm cache, restart, ABA and collision', async tcase => {
  for (const state of ['reserved', 'bound', 'completed', 'discarded', 'deleted']) await tcase.test(state, async () => {
    const t = await fixture();
    if (state === 'bound') await upload(t, 0);
    if (['completed', 'deleted'].includes(state)) { await upload(t); await t.domain.finalizeIngestion(t.op.transactionId); }
    if (state === 'discarded') await t.service.discard(t.op.id);
    if (state === 'deleted') {
      const session = await t.domain.getSession(t.op.transactionId);
      await t.domain.purgeSession(session.id, { expectedRevision: session.revision, idempotencyKey: randomUUID(), confirmation: session.id });
    }
    assert.equal((await t.service.calendar('2026-10')).recordings.find(r => r.id === t.op.id).state, state);
    assert.equal((await t.service.calendar('2026-09')).recordings.length, 0);
    await context(t, 1);
    for (const service of [t.service, instance(t.repository).service]) {
      assert.ok((await service.calendar('2026-10')).recordings.every(r => r.id !== t.op.id));
      await assert.rejects(() => service.ordinaryOperation(t.op.id), forbidden);
    }
    await context(t, 0);
    assert.equal((await t.service.ordinaryOperation(t.op.id)).state, state);
    // Same account/occurrence identity through a distinct connection must not take over.
    await context(t, 1, s => { s.connections[1].accountId = CONNECTION.accountId; s.connections[1].verification.fingerprint = connectionFingerprint(s.connections[1]); });
    const before = effects(t);
    assert.ok((await t.service.calendar('2026-10', true)).recordings.every(r => r.id !== t.op.id));
    await assert.rejects(async () => t.service.reserve({ id: t.op.id, month: '2026-10', settingsRevision: (await t.service.settings()).revision }), forbidden);
    assert.equal(effects(t), before);
    assert.equal(t.op.id, opaqueIdentity(CONNECTION.accountId, CONNECTION.meetingId, 'same-day-A'));
  });
});

test('FIX A02/A03/A05: null, removed, revised and unverified profiles block HTTP and generic domain ingress without effects', async tcase => {
  for (const mode of ['B', 'null', 'removed', 'revised', 'unverified']) await tcase.test(mode, async () => {
    const t = await fixture(); await upload(t, 1);
    const settings = await context(t, mode === 'B' ? 1 : mode === 'null' ? null : 0, s => {
      if (mode === 'removed') { s.connections.shift(); s.activeConnectionId = null; }
      if (mode === 'revised') s.connections[0].revision++;
      if (mode === 'unverified') { s.connections[0].verification = null; s.activeConnectionId = null; }
    });
    const counts = countZoom(t), request = api(t), before = effects(t);
    const id = t.op.id, tx = t.op.transactionId, track = t.plan.tracks[0], part = track.parts[0];
    for (const [path, method, body, headers] of [
      [`/v1/zoom/imports/${id}`], ['/v1/zoom/imports', 'POST', { id, month: '2026-10', settingsRevision: settings.revision }],
      [`/v1/zoom/imports/${id}/plan`, 'POST', { plan: serializeIngestionPlan(t.plan) }], [`/v1/zoom/imports/${id}/files/file-1`],
      [`/v1/zoom/imports/${id}/finalize`, 'POST', { confirmed: true }], [`/v1/zoom/imports/${id}/discard`, 'POST', { confirmed: true }], [`/v1/source-sessions/ingestions/${tx}/finalize`, 'POST', { idempotencyKey: randomUUID(), recovery: true }],
      [`/v1/source-sessions/ingestions/${tx}/blobs/${track.blobId}/parts/1`, 'PUT', Buffer.from(await part.blob.arrayBuffer()), { 'content-type': 'application/octet-stream', 'x-part-sha256': part.sha256, 'idempotency-key': randomUUID() }]
    ]) {
      const response = await request(path, method, body, headers); assert.equal(response.status, 409, path);
      const payload = await response.text(); assert.ok(!payload.includes('participant.m4a') && !payload.includes(t.op.title), payload);
    }
    await assert.rejects(() => t.domain.beginIngestion({ schemaVersion: 1, idempotencyKey: t.op.idempotencyKey, title: t.op.title, recordedAt: t.op.recordedAt, origin: 'zoom_cloud', supersedesSessionId: null, plan: serializeIngestionPlan(t.plan) }, id), forbidden);
    await assert.rejects(() => t.domain.finalizeIngestion(tx, { allowInactive: true }), forbidden);
    await assert.rejects(() => t.domain.recoverIncomplete(tx, 'resume'), /Original files/);
    assert.equal(effects(t), before); assert.deepEqual(counts, { list: 0, recording: 0, download: 0 });
    if (settings.activeConnectionId === null) { const c = await t.service.calendar('2026-10'); assert.equal(c.state, 'unconfigured'); assert.deepEqual(c.recordings, []); assert.equal(counts.list, 0); }
  });
});

test('FIX A03/A06: barriers fence calendar, reserve, bind, acquisition and response reconciliation across two instances', async tcase => {
  for (const phase of ['list', 'recording', 'reserve-recording', 'reserve-CAS', 'reserve-lost', 'bind-CAS', 'begin-release', 'download-recording', 'download-stream', 'upload-list', 'finalize-parts', 'finalize-publish', 'finalize-lost']) await tcase.test(phase, async () => {
    const t = await fixture(); const second = instance(t.repository);
    let target, method, match, action;
    if (phase.startsWith('finalize')) { await upload(t); target = t.repository; method = phase === 'finalize-parts' ? 'downloadReleaseAsset' : phase === 'finalize-publish' ? 'publishRelease' : 'commitJson'; match = phase === 'finalize-lost' ? (_h, _f, m) => m.startsWith('Finalize audio session') : undefined; action = () => t.domain.finalizeIngestion(t.op.transactionId); }
    else if (phase === 'upload-list') { await upload(t, 0); target = t.repository; method = 'listReleaseAssets'; const tr = t.plan.tracks[0], p = tr.parts[0]; const bytes = Buffer.from(await p.blob.arrayBuffer()); action = () => t.domain.uploadPart(t.op.transactionId, tr.blobId, 1, bytes, p.sha256, randomUUID()); }
    else if (phase.startsWith('download')) { target = t.zoom; method = phase === 'download-stream' ? 'download' : 'recording'; action = () => t.service.download(t.op.id, 'file-1'); }
    else if (phase.startsWith('bind') || phase === 'begin-release') { target = t.repository; method = phase === 'begin-release' ? 'createDraftRelease' : 'commitJson'; match = phase === 'bind-CAS' ? (_h, _f, m) => m === 'Bind exact Zoom ingestion plan' : undefined; action = () => t.service.bind(t.op.id, { plan: serializeIngestionPlan(t.plan) }); }
    else if (phase.startsWith('reserve')) {
      const c = await t.service.calendar('2026-10'); target = phase === 'reserve-recording' ? t.zoom : t.repository; method = phase === 'reserve-recording' ? 'recording' : 'commitJson'; match = phase !== 'reserve-recording' ? (_h, _f, m) => m === 'Reserve Zoom occurrence' : undefined;
      action = () => t.service.reserve({ id: c.recordings[1].id, month: '2026-10', settingsRevision: c.settingsRevision });
    } else { target = t.zoom; method = phase; action = () => t.service.calendar('2026-10', true); }
    // Lost responses pause AFTER the write, then throw; other barriers pause before the awaited effect completes.
    if (phase.endsWith('lost')) {
      const fn = target[method].bind(target);
      target[method] = async (...args) => { const result = await fn(...args); if (match(...args)) { await gate.wait(); throw new Error('Synthetic lost response'); } return result; };
      let enter, release; const waiting = new Promise(r => { enter = r; }); const blocked = new Promise(r => { release = r; });
      var gate = { wait: () => { enter(); return blocked; } };
      const pending = action(); const outcome = assert.rejects(pending); await waiting; await context(t, 1); release(); await outcome;
    } else {
      const b = barrier(target, method, match); const pending = action(); const outcome = assert.rejects(pending); await b.waiting; await context(t, 1); b.release(); await outcome;
    }
    await assert.rejects(() => second.service.ordinaryOperation(t.op.id), forbidden);
    assert.ok([...t.repository.files.keys()].filter(p => p.startsWith('sessions/')).length <= 1);
    if (phase === 'upload-list') assert.equal(t.repository.assetBytes.size, 0);
    if (['list', 'recording', 'reserve-recording', 'download-recording'].includes(phase)) assert.equal(t.zoom.downloads, 0);
    if (phase === 'finalize-parts') assert.equal([...t.repository.releases.values()][0].draft, true);
  });
});

test('FIX A03: foreign durable records cannot mask outage; expired/warm cache and restart preserve same-context fallback only', async () => {
  const t = await fixture();
  t.zoom.fail = true;
  assert.match((await t.service.calendar('2026-10', true)).warning, /неполный/);
  await context(t, 1);
  await assert.rejects(() => t.service.calendar('2026-10', true), /outage/);
  const restarted = instance(t.repository); restarted.zoom.fail = true;
  await assert.rejects(() => restarted.service.calendar('2026-10'), /outage/);
  await context(t, 0); t.service.clock = () => Date.now() + 60_000;
  assert.deepEqual((await t.service.calendar('2026-10')).recordings.map(r => r.id), [t.op.id]);
});

test('FIX A07/A08: explicit HTTP maintenance after restart completes accepted parts without credentials or Zoom; ordinary finalize remains guarded', async () => {
  const t = await fixture(); await upload(t);
  await context(t, null, s => { s.connections = []; });
  const restarted = instance(t.repository); restarted.zoom.list = restarted.zoom.recording = restarted.zoom.download = () => { throw new Error('Forbidden Zoom recovery call'); };
  const request = api(restarted), before = effects(t);
  assert.equal((await request(`/v1/zoom/imports/${t.op.id}/finalize`, 'POST', { confirmed: true })).status, 409);
  assert.equal(effects(t), before);
  for (const action of ['resume', 'retry']) {
    const response = await request(`/v1/maintenance/incomplete/${t.op.transactionId}/${action}`, 'POST', { idempotencyKey: randomUUID() });
    assert.equal(response.status, 200, await response.clone().text()); assert.equal((await response.json()).session.id, t.op.transactionId);
  }
  assert.equal(t.repository.releases.size, 1); assert.equal(t.repository.assetBytes.size, 4);
  assert.equal([...t.repository.files.keys()].filter(p => p.startsWith('sessions/')).length, 1);
});

test('FIX A08: corrupt/missing/duplicate parts, changed linkage/plan/staged manifest and tombstone never recover or resurrect', async tcase => {
  for (const fault of ['missing', 'corrupt-part', 'whole-hash', 'duplicate', 'asset-alias', 'linkage', 'plan', 'tombstone', 'staged-manifest', 'discarding', 'discarded']) await tcase.test(fault, async () => {
    const t = await fixture(); await upload(t);
    const path = `transactions/ingest-${t.op.transactionId}.json`, tx = structuredClone(t.repository.files.get(path)), r = structuredClone(t.repository.files.get(importPath(t.op.id)));
    if (fault === 'staged-manifest') { const original = t.repository.publishRelease; t.repository.publishRelease = async () => { throw new Error('Synthetic stop after staging'); }; await assert.rejects(() => t.domain.finalizeIngestion(t.op.transactionId)); t.repository.publishRelease = original; const staged = structuredClone(t.repository.files.get(path)); staged.stagedManifest.title = 'Forged staged title'; await t.repository.commitJson(await t.repository.getHead(), { [path]: staged }, 'Synthetic staged corruption'); }
    else {
      if (fault === 'missing') { t.repository.assetBytes.delete(tx.uploadedParts[0].assetId); t.repository.releases.get(tx.releaseId).assets.shift(); }
      if (fault === 'corrupt-part') t.repository.assetBytes.get(tx.uploadedParts[0].assetId)[20] ^= 1;
      if (fault === 'whole-hash') { tx.plan.tracks[0].sha256 = '0'.repeat(64); r.plan = tx.plan; }
      if (fault === 'duplicate') tx.uploadedParts[1] = structuredClone(tx.uploadedParts[0]);
      if (fault === 'asset-alias') tx.uploadedParts[1].assetId = tx.uploadedParts[0].assetId;
      if (fault === 'linkage') r.title = 'Changed import title';
      if (fault === 'plan') r.plan.tracks[0].originalName = 'changed.m4a';
      if (fault === 'tombstone') { await t.domain.finalizeIngestion(t.op.transactionId); const session = await t.domain.getSession(t.op.transactionId); await t.domain.purgeSession(session.id, { expectedRevision: session.revision, idempotencyKey: randomUUID(), confirmation: session.id }); }
      else { if (['discarding', 'discarded'].includes(fault)) tx.state = fault; await t.repository.commitJson(await t.repository.getHead(), { [path]: tx, [importPath(r.id)]: r }, 'Synthetic integrity fault'); }
    }
    await context(t, 1); const before = effects(t), restarted = instance(t.repository);
    await assert.rejects(() => restarted.domain.recoverIncomplete(t.op.transactionId, 'resume'));
    assert.equal(effects(t), before);
  });
});


test('FIX A11: independent manual/device source, drafts, Speaker history, recipes, catalog entries and asset bytes remain exact', async () => {
  const { managementFixture } = await import('./archive-management-fixture.mjs');
  const h = await managementFixture(), repository = new SyntheticArchiveRepository();
  repository.files = structuredClone(h.repository.files); repository.releases = structuredClone(h.repository.releases);
  repository.assetBytes = new Map([...h.repository.assetBytes].map(([id, bytes]) => [id, Buffer.from(bytes)]));
  repository.nextAsset = h.repository.nextAsset; repository.nextRelease = h.repository.nextRelease;
  repository.history.set(await repository.getHead(), structuredClone(repository.files));
  const preservedFiles = structuredClone(repository.files), preservedBytes = new Map([...repository.assetBytes].map(([id, bytes]) => [id, Buffer.from(bytes)]));
  const t = await fixture(repository); await upload(t); await context(t, null, s => { s.connections = []; });
  await assert.rejects(() => t.domain.finalizeIngestion(t.op.transactionId), forbidden);
  await instance(repository).domain.recoverIncomplete(t.op.transactionId, 'retry');
  for (const [path, value] of preservedFiles) {
    if (path === 'catalog.json') { for (const entry of value.entries) assert.deepEqual(repository.files.get(path).entries.find(e => e.id === entry.id), entry); }
    else assert.deepEqual(repository.files.get(path), value, path);
  }
  for (const [id, bytes] of preservedBytes) assert.deepEqual(repository.assetBytes.get(id), bytes);
  assert.equal((await t.domain.getSession(h.primary.id)).origin.kind, 'manual');
  const history = await t.domain.speakerProjectHistory(h.primary.id); assert.ok(history.states.length);
});

test('FIX A06: ordinary finalize fences an ABA settings revision change during accepted-byte verification', async () => {
  const t = await fixture(); await upload(t);
  const b = barrier(t.repository, 'downloadReleaseAsset');
  const pending = t.domain.finalizeIngestion(t.op.transactionId), outcome = assert.rejects(pending, forbidden);
  await b.waiting; await context(t, 1); await context(t, 0); const before = effects(t); b.release(); await outcome;
  assert.equal(effects(t), before);
  assert.equal((await t.service.ordinaryOperation(t.op.id)).state, 'bound');
  await t.domain.finalizeIngestion(t.op.transactionId);
});
