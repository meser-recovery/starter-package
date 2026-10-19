import test from 'node:test';
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { AudioArchiveDomain } from '../src/domain.mjs';
import { ZoomArchive } from '../src/zoom-archive.mjs';
import { ZoomClient, monthRange, encodeZoomUuid, safeDownloadUrl, publicAddress, participantFiles } from '../src/zoom.mjs';
import { SETTINGS_PATH, encryptSettings, decryptSettings, connectionFingerprint, opaqueIdentity, importPath } from '../src/settings.mjs';
import { GitHubArchiveRepository } from '../src/github.mjs';
import { createApp } from '../src/app.mjs';
import { SessionRegistry, createSession } from '../src/auth.mjs';
import { AudioArchiveGateway, createIngestionPlan, serializeIngestionPlan, validateSessionManifest, prepareRemoteSourceBatch } from '../../../service/frontend/scripts/audio-archive-client.mjs';
import { MemoryRepository, sha } from './helpers.mjs';
import { A, B, CONNECTION, SyntheticZoom, SyntheticArchiveRepository } from './s12-fixtures.mjs';

const key = Buffer.alloc(32, 31), origin = 'https://meserproject.duckdns.org';
const mutation = (revision, action, extras = {}) => ({ revision, mutationId: randomUUID(), action, connection: null, connectionId: null, receipt: null, storage: null, confirmed: false, ...extras });
function setup(repository = new MemoryRepository()) {
  const domain = new AudioArchiveDomain(repository, { acceptedPartBytes: 1024 });
  const zoom = new SyntheticZoom(), service = new ZoomArchive(domain, { key, zoom }); return { repository, domain, zoom, service };
}
async function configured() {
  const t = setup();
  const check = await t.service.check({ revision: 0, connection: CONNECTION });
  await t.service.mutate(mutation(0, 'save', { connection: CONNECTION, receipt: check.receipt }));
  await t.service.mutate(mutation(1, 'activate', { connectionId: CONNECTION.connectionId, confirmed: true })); return t;
}
async function reserve(t, index = 0) {
  const calendar = await t.service.calendar('2026-10');
  return t.service.reserve({ id: calendar.recordings[index].id, month: '2026-10', settingsRevision: calendar.settingsRevision });
}
async function planFor(op, bytes = [A, B]) {
  return createIngestionPlan(bytes.map(b => new File([b], 'participant.m4a', { type: 'audio/mp4' })), 1024, { idempotencyKey: op.idempotencyKey });
}
async function upload(t, op, plan, count = Infinity) {
  await t.service.bind(op.id, { plan: serializeIngestionPlan(plan) }); let n = 0;
  for (const track of plan.tracks) for (const part of track.parts) {
    if (n++ >= count) return;
    await t.domain.uploadPart(op.transactionId, track.blobId, part.partNumber, Buffer.from(await part.blob.arrayBuffer()), part.sha256, randomUUID());
  }
}

test('S12 A01-A05 encrypted settings, explicit Check, verification invalidation, restart, CAS and lost response', async () => {
  const t = setup(); assert.equal((await t.service.settings()).revision, 0);
  const checked = await t.service.check({ revision: 0, connection: CONNECTION }); assert.equal(t.repository.commits.length, 0);
  let dto = await t.service.mutate(mutation(0, 'save', { connection: CONNECTION, receipt: checked.receipt }));
  const stored = t.repository.files.get(SETTINGS_PATH);
  assert.doesNotMatch(JSON.stringify(stored), /synthetic-account|synthetic-client|synthetic-secret/);
  assert.doesNotMatch(JSON.stringify(dto), /accountId|clientId|clientSecret|synthetic-secret/);
  const restarted = new ZoomArchive(t.domain, { key, zoom: t.zoom });
  dto = await restarted.mutate(mutation(dto.revision, 'activate', { connectionId: CONNECTION.connectionId, confirmed: true }));
  assert.equal(dto.activeConnectionId, CONNECTION.connectionId);
  await assert.rejects(() => restarted.mutate(mutation(1, 'storage', { storage: { softLimitBytes: 50e9, warningPercent: 80 } })), e => e.status === 409);
  dto = await restarted.mutate(mutation(dto.revision, 'save', { connection: { ...CONNECTION, accountId: '', clientId: '', clientSecret: '' } }));
  assert.ok(dto.connections[0].verification);
  dto = await restarted.mutate(mutation(dto.revision, 'save', { connection: { ...CONNECTION, clientSecret: 'invalid' } }));
  assert.equal(dto.activeConnectionId, null); assert.equal(dto.connections[0].verification, null);
  await assert.rejects(() => restarted.mutate(mutation(dto.revision, 'activate', { connectionId: CONNECTION.connectionId, confirmed: true })), e => e.status === 409);
  const originalCommit = t.repository.commitJson.bind(t.repository);
  t.repository.commitJson = async (...args) => { await originalCommit(...args); throw new Error('lost settings response'); };
  dto = await restarted.mutate(mutation(dto.revision, 'storage', { storage: { softLimitBytes: 60e9, warningPercent: 90 } })); assert.equal(dto.storage.softLimitBytes, 60e9);
  const nonces = t.repository.commits.map(c => c.files[SETTINGS_PATH]?.nonce).filter(Boolean); assert.equal(new Set(nonces).size, nonces.length);
  assert.throws(() => decryptSettings(stored, Buffer.alloc(32, 3)), /зашифрованные/);
  assert.throws(() => decryptSettings({ ...stored, tag: Buffer.alloc(16).toString('base64') }, key), /зашифрованные/);
  assert.equal(decryptSettings(encryptSettings({ test: true }, key), key).test, true);
  assert.equal((await t.domain.listSessions('incoming')).sessions.length, 0);
  await assert.rejects(() => new ZoomArchive(t.domain).settings(), e => e.status === 503);
});

test('S12 A06-A08 Zoom month boundaries, pagination, exact UUID, safe fields, limits, no mixed fallback', async () => {
  assert.deepEqual(monthRange('2026-10'), { start: Date.parse('2026-09-30T21:00:00Z'), end: Date.parse('2026-10-31T21:00:00Z') });
  assert.equal(encodeZoomUuid('/a//b'), '%252Fa%252F%252Fb');
  const calls = [];
  const client = new ZoomClient({ fetchImpl: async (url, options) => {
    calls.push([url, options]); let body;
    if (url.endsWith('/oauth/token')) body = { access_token: 'server-only', expires_in: 3600 };
    else if (/\/meetings\//.test(url)) body = { id: CONNECTION.meetingId, host_id: 'host' };
    else {
      const u = new URL(url), next = u.searchParams.get('next_page_token');
      body = { meetings: [{ id: CONNECTION.meetingId, uuid: next ? 'second' : 'first', start_time: next ? '2026-10-31T20:59:00Z' : '2026-09-30T21:00:00Z' },
        { id: 'other', uuid: 'wrong-meeting', start_time: '2026-10-01T00:00:00Z' }], next_page_token: next ? '' : 'page-two' };
    }
    return Response.json(body);
  } });
  const rows = await client.list(CONNECTION, monthRange('2026-10'));
  assert.deepEqual(rows.map(r => r.uuid), ['first', 'second']); assert.equal(calls.filter(([u]) => u.endsWith('/oauth/token')).length, 1);
  assert.equal(calls.filter(([u]) => u.includes('/users/')).length, 4);
  const recording = await new SyntheticZoom().recording(CONNECTION, 'A');
  assert.equal(participantFiles(recording).length, 2);
  assert.throws(() => participantFiles({ ...recording, participant_audio_files: [] }));
  assert.throws(() => participantFiles({ ...recording, participant_audio_files: Array(33).fill(recording.participant_audio_files[0]) }));
  assert.throws(() => participantFiles({ ...recording, participant_audio_files: recording.participant_audio_files.map(f => ({ ...f, file_size: 300 * 1024 * 1024 })) }));
  const rate = new ZoomClient({ fetchImpl: async () => new Response('secret upstream error', { status: 429, headers: { 'Retry-After': '120' } }) });
  await assert.rejects(() => rate.token(CONNECTION), e => e.status === 429 && e.retryAfter === 120 && !e.message.includes('secret'));
});

test('S12 A08-A15 frozen plan, byte preservation, lost reserve/part/finalize, restart, no duplicate or resurrection', async () => {
  const t = await configured(), op = await reserve(t), plan = await planFor(op);
  const parallel = await Promise.all([reserve(t), reserve(t)]); assert.ok(parallel.every(r => r.idempotencyKey === op.idempotencyKey));
  const other = await reserve(t, 1); assert.notEqual(other.idempotencyKey, op.idempotencyKey);
  await upload(t, op, plan, 1);
  const restarted = new ZoomArchive(t.domain, { key, zoom: t.zoom });
  assert.equal((await restarted.operation(op.id)).uploadedParts.length, 1);
  const changed = Buffer.from(B); changed[changed.length - 1] ^= 1;
  await assert.rejects(async () => restarted.bind(op.id, { plan: serializeIngestionPlan(await planFor(op, [A, changed])) }), e => e.status === 409);
  await assert.rejects(() => t.service.mutate(mutation(2, 'save', { connection: { ...CONNECTION, clientSecret: 'replacement' } })), e => e.status === 409);
  await assert.rejects(() => t.service.mutate(mutation(2, 'delete', { connectionId: CONNECTION.connectionId, confirmed: true })), e => e.status === 409);
  await upload(t, op, plan); assert.equal([...t.repository.assetBytes].length, 4);
  assert.equal((await restarted.operation(op.id)).canFinalize, true);
  t.zoom.fail = true;
  const result = await t.domain.finalizeIngestion(op.transactionId);
  assert.equal(validateSessionManifest(result.session), true); assert.equal(result.session.origin.kind, 'zoom_cloud'); assert.equal(result.session.origin.externalId, op.id);
  assert.equal((await t.domain.finalizeIngestion(op.transactionId)).session.id, result.session.id);
  assert.equal((await restarted.operation(op.id)).state, 'completed');
  for (const [i, track] of result.session.sourceTracks.entries()) {
    const bytes = Buffer.concat(track.parts.map(p => t.repository.assetBytes.get(p.assetId))); assert.deepEqual(bytes, i === 0 ? A : B); assert.equal(track.sha256, sha(bytes));
  }
  assert.equal(t.repository.releases.size, 1);
  await assert.rejects(() => restarted.discard(op.id), e => e.status === 409);
  const deleted = await t.domain.deleteSources(op.transactionId, { expectedRevision: result.session.revision, idempotencyKey: randomUUID(), confirmation: 'Удалить исходники, сохранить результаты' });
  assert.equal((await restarted.operation(op.id)).state, 'deleted');
  await t.domain.purgeSession(op.transactionId, { expectedRevision: deleted.session.revision, idempotencyKey: randomUUID(), confirmation: op.transactionId });
  assert.equal((await restarted.operation(op.id)).state, 'deleted');
  assert.equal((await restarted.reserve({ id: op.id, month: '2026-10', settingsRevision: 2 })).state, 'deleted');
});

test('S12 A14-A15 CAS discard claim prevents simultaneous finalization and maintenance removes no completed source', async () => {
  const t = await configured(), op = await reserve(t), plan = await planFor(op); await upload(t, op, plan);
  const commit = t.repository.commitJson.bind(t.repository); let finish;
  const gate = new Promise(resolve => { finish = resolve; });
  t.repository.commitJson = async (head, files, message) => { const value = await commit(head, files, message); if (message.startsWith('Claim ingestion discard')) await gate; return value; };
  const discard = t.service.discard(op.id); await new Promise(resolve => setImmediate(resolve));
  await assert.rejects(() => t.domain.finalizeIngestion(op.transactionId), e => e.status === 409);
  finish(); await discard; assert.equal((await t.service.operation(op.id)).state, 'discarded');
  await assert.rejects(() => t.service.bind(op.id, { plan: serializeIngestionPlan(plan) }), e => e.status === 409);
});

test('S12 A16 allowlisted IDs/HTTPS/DNS, credentials never sent to unsafe addresses', () => {
  for (const u of ['http://zoom.us/a', 'https://zoom.us.evil.test/a', 'https://127.0.0.1/a', 'https://zoom.us@evil.test/a', 'https://zoom.us:444/a']) assert.throws(() => safeDownloadUrl(u));
  assert.equal(safeDownloadUrl('https://us02web.zoom.us/rec/download/a').hostname, 'us02web.zoom.us');
  for (const ip of ['127.0.0.1', '10.0.0.1', '169.254.169.254', '172.31.1.1', '192.168.0.1', '::1', '::ffff:127.0.0.1', 'fe80::1', 'fd00::1']) assert.equal(publicAddress(ip), false);
});

test('S12 A17-A18 complete >100 Releases/>1000 assets pagination, dedup, stale fallback, 40GB soft warning', async () => {
  const repo = new GitHubArchiveRepository({}); repo.api = async path => {
    const page = Number(new URL(path, 'https://test').searchParams.get('page'));
    return Array.from({ length: path.includes('/assets') ? page <= 10 ? 100 : 1 : page === 1 ? 100 : 1 }, (_, i) => ({ id: (page - 1) * 100 + i + 1, size: 1 }));
  };
  assert.equal((await repo.listReleases()).length, 101); assert.equal((await repo.listReleaseAssets(1)).length, 1001);
  const t = await configured();
  t.repository.listReleases = async () => [{ id: 1, draft: true }, { id: 2 }];
  t.repository.listReleaseAssets = async () => [{ id: 9, size: 40e9 }];
  let usage = await t.service.usage(true); assert.equal(usage.usedBytes, 40e9); assert.equal(usage.warning, true); assert.equal(usage.assetCount, 1);
  t.repository.listReleaseAssets = async () => { throw new Error('partial failure'); };
  usage = await t.service.usage(true); assert.equal(usage.stale, true); assert.equal(usage.usedBytes, 40e9);
  const fresh = new ZoomArchive(t.domain, { key, zoom: t.zoom }); assert.equal((await fresh.usage(true)).usedBytes, null);
});

test('S12 A09/A16/A22 actual authenticated API and browser ingestFiles preserve bytes, enforce CSRF and capability', async () => {
  const t = await configured(), registry = new SessionRegistry(), secret = 'synthetic-session-secret-0000000000000';
  const created = createSession(secret, 3600, registry);
  const app = createApp({ domain: t.domain, zoomArchive: t.service, sessionRegistry: registry, config: { allowedOrigin: origin, acceptedPartBytes: 1024, sessionSigningSecret: secret } });
  assert.equal((await app(new Request(`${origin}/v1/archive-settings`))).status, 401);
  assert.equal((await app(new Request(`${origin}/v1/archive-settings`, { method: 'POST', headers: { cookie: created.cookie.split(';')[0], origin }, body: '{}' }))).status, 403);
  const client = new AudioArchiveGateway(origin, (url, options = {}) => {
    const headers = new Headers(options.headers); headers.set('cookie', created.cookie.split(';')[0]); headers.set('origin', origin);
    return app(new Request(url, { ...options, headers }));
  });
  client.csrfToken = created.session.csrfToken; await client.configuration();
  const op = await reserve(t);
  const result = await client.ingestFiles({ files: [A, B].map(b => new File([b], 'participant.m4a', { type: 'audio/mp4' })), zoomImportId: op.id, idempotencyKey: op.idempotencyKey, origin: 'zoom_cloud', title: op.title, recordedAt: op.recordedAt });
  assert.equal(result.session.sourceTracks.length, 2);
  assert.equal((await client.request(`/v1/zoom/imports/${op.id}`)).state, 'completed');
  const prepared = await prepareRemoteSourceBatch({ gateway: client, sessionId: result.session.id });
  assert.deepEqual(Buffer.from(await prepared.files[0].arrayBuffer()), A);
  assert.deepEqual(Buffer.from(await prepared.files[1].arrayBuffer()), B);
  const legacySource = execFileSync('git', ['show', 'abb64d92a01c3028aad67ef883661e1c26e98b98:gateway/audio-archive/src/validation.mjs'], { encoding: 'utf8' });
  const legacyReader = await import(`data:text/javascript;base64,${Buffer.from(legacySource).toString('base64')}`);
  assert.throws(() => legacyReader.validateSourceSession(result.session), /Origin/);
  assert.equal(legacyReader.validateSourceSession({ ...structuredClone(result.session), origin: { kind: 'manual', externalId: null } }).origin.kind, 'manual');
  client.zoomCloudVersion = 0;
  await assert.rejects(() => client.ingestFiles({ files: [], zoomImportId: op.id }), /не поддерживает/);
  const legacyResult = await client.ingestFiles({ files: [new File([A], 'manual.m4a', { type: 'audio/mp4' })], title: 'Legacy manual without S12 capability', origin: 'manual' });
  assert.equal(legacyResult.session.origin.kind, 'manual');
  await assert.rejects(async () => t.domain.beginIngestion({ schemaVersion: 1, idempotencyKey: 'forged-zoom-ingestion', title: 'Fake', recordedAt: null, origin: 'zoom_cloud', supersedesSessionId: null, plan: serializeIngestionPlan(await planFor(op)) }), /origin/);
});

const failOnceAfter = (object, method, predicate = () => true) => {
  const original = object[method].bind(object); let fired = false;
  object[method] = async (...args) => { const result = await original(...args); if (!fired && predicate(...args)) { fired = true; throw new Error(`Lost ${method} response`); } return result; };
};

test('S12 A10-A14 two Gateway instances reserve concurrently and recover actual lost mutations/crashes without duplicate assets', async () => {
  const repository = new SyntheticArchiveRepository(), t = setup(repository);
  const receipt = await t.service.check({ revision: 0, connection: CONNECTION });
  await t.service.mutate(mutation(0, 'save', { connection: CONNECTION, receipt: receipt.receipt }));
  await t.service.mutate(mutation(1, 'activate', { connectionId: CONNECTION.connectionId, confirmed: true }));
  const second = setup(repository);
  failOnceAfter(repository, 'commitJson', (_head, _files, message) => message === 'Reserve Zoom occurrence');
  const [op, raced] = await Promise.all([reserve(t), reserve(second)]);
  assert.equal(op.idempotencyKey, raced.idempotencyKey); assert.equal(op.transactionId, raced.transactionId);
  assert.equal([...repository.files.keys()].filter(p => p.startsWith('zoom-imports/')).length, 1);
  const plan = await planFor(op);
  failOnceAfter(repository, 'createDraftRelease');
  await assert.rejects(() => t.service.bind(op.id, { plan: serializeIngestionPlan(plan) }), /Lost/);
  await second.service.bind(op.id, { plan: serializeIngestionPlan(plan) }); assert.equal(repository.releases.size, 1);
  const part = plan.tracks[0].parts[0], bytes = Buffer.from(await part.blob.arrayBuffer());
  failOnceAfter(repository, 'uploadReleaseAsset');
  await assert.rejects(() => t.domain.uploadPart(op.transactionId, plan.tracks[0].blobId, 1, bytes, part.sha256, randomUUID()), /Lost/);
  failOnceAfter(repository, 'commitJson', (_h, _f, message) => message.startsWith('Record audio part'));
  await assert.rejects(() => second.domain.uploadPart(op.transactionId, plan.tracks[0].blobId, 1, bytes, part.sha256, randomUUID()), /Lost/);
  const afterCrash = setup(repository);
  await upload(afterCrash, op, plan); assert.equal(repository.assetBytes.size, 4);
  failOnceAfter(repository, 'publishRelease');
  await assert.rejects(() => t.domain.finalizeIngestion(op.transactionId), /Lost/);
  await assert.rejects(() => second.service.discard(op.id), e => e.status === 409);
  failOnceAfter(repository, 'commitJson', (_h, _f, message) => message.startsWith('Finalize audio session'));
  await assert.rejects(() => afterCrash.domain.finalizeIngestion(op.transactionId), /Lost/);
  const completed = await setup(repository).domain.finalizeIngestion(op.transactionId);
  assert.equal(completed.session.id, op.transactionId); assert.equal(repository.assetBytes.size, 4); assert.equal(repository.releases.size, 1);
  assert.equal([...repository.files.keys()].filter(p => p.startsWith('sessions/')).length, 1);
  assert.equal((await second.service.operation(op.id)).state, 'completed');
});

test('S12 A03/A07/A11/A13 calendar preserves durable operations during outage and active switch; original file set required', async () => {
  const t = await configured(), op = await reserve(t), plan = await planFor(op);
  const another = { ...CONNECTION, connectionId: randomUUID(), name: 'Another profile', accountId: 'another-account', clientId: 'another-client' };
  const checked = await t.service.check({ revision: 2, connection: another });
  await t.service.mutate(mutation(2, 'save', { connection: another, receipt: checked.receipt }));
  await t.service.mutate(mutation(3, 'activate', { connectionId: another.connectionId, confirmed: true }));
  let downloadAccount;
  const download = t.zoom.download.bind(t.zoom);
  t.zoom.download = async (c, ...args) => { downloadAccount = c.accountId; return download(c, ...args); };
  assert.deepEqual(Buffer.from(await (await t.service.download(op.id, 'file-1')).arrayBuffer()), A);
  assert.equal(downloadAccount, CONNECTION.accountId);
  const recording = t.zoom.recording.bind(t.zoom);
  t.zoom.recording = async (...args) => { const value = await recording(...args); value.participant_audio_files.pop(); return value; };
  await assert.rejects(() => t.service.download(op.id, 'file-1'), e => e.status === 409);
  t.zoom.recording = recording; await upload(t, op, plan);
  t.zoom.fail = true;
  const calendar = await t.service.calendar('2026-10', true);
  assert.match(calendar.warning, /неполный/); assert.equal(calendar.recordings.find(r => r.id === op.id).state, 'bound');
  assert.equal((await t.service.operation(op.id)).canFinalize, true);
  await t.domain.finalizeIngestion(op.transactionId);
  assert.equal((await t.service.calendar('2026-10', true)).recordings[0].state, 'completed');
  const noSample = new ZoomClient({ clock: () => Date.parse('2026-10-12T00:00:00Z') });
  noSample.list = async () => []; let downloads = 0; noSample.download = async () => { downloads++; };
  assert.equal((await noSample.check(CONNECTION)).tracks, 'unconfirmed'); assert.equal(downloads, 0);
  t.zoom.fail = false; t.zoom.check = c => noSample.check(c);
  const unconfirmed = { ...CONNECTION, connectionId: randomUUID() };
  const check = await t.service.check({ revision: 4, connection: unconfirmed });
  await t.service.mutate(mutation(4, 'save', { connection: unconfirmed, receipt: check.receipt }));
  assert.equal((await t.service.mutate(mutation(5, 'activate', { connectionId: unconfirmed.connectionId, confirmed: true }))).activeConnectionId, unconfirmed.connectionId);
  const before = [...t.repository.files.keys()];
  await assert.rejects(() => t.service.check({ revision: 6, connection: { ...unconfirmed, clientSecret: 'invalid' }, verified: true }));
  assert.deepEqual([...t.repository.files.keys()], before);
});

test('S12 A17 moving physical listings and in-flight known mutation never replace last complete usage', async () => {
  const t = await configured(); let count = 0;
  t.repository.listReleases = async () => [{ id: 1 }];
  t.repository.listReleaseAssets = async () => [{ id: 1, size: 20 }];
  assert.equal((await t.service.usage(true)).usedBytes, 20);
  t.repository.listReleaseAssets = async () => [{ id: 1, size: ++count * 100 }];
  assert.equal((await t.service.usage(true)).stale, true); assert.equal(t.service.usageCache.usedBytes, 20);
  t.repository.activeStorageMutations = 1;
  assert.equal((await t.service.usage()).stale, true);
  t.repository.activeStorageMutations = 0; t.repository.storageMutationVersion = 1;
  t.repository.listReleaseAssets = async () => [{ id: 1, size: 50 }];
  assert.equal((await t.service.usage()).usedBytes, 20); // ordinary read retains the last complete total
  assert.equal((await t.service.usage()).stale, true);
  assert.equal((await t.service.usage(true)).usedBytes, 50);
});

test('S12 A03 Check searches all paginated occurrences and never masks API/download failures', async () => {
  const sample = await new SyntheticZoom().recording(CONNECTION, 'eligible');
  const make = ({ rows = ['empty', 'eligible'], fail = null, downloadFailure = false } = {}) => {
    const inspected = [], downloaded = [];
    const client = new ZoomClient({ clock: () => Date.parse('2026-10-12T00:00:00Z'),
      fetchImpl: async url => {
        const u = new URL(url); let phase, body;
        if (u.pathname === '/oauth/token') { phase = 'auth'; body = { access_token: 'synthetic-token', expires_in: 3600 }; }
        else if (u.pathname === `/v2/meetings/${CONNECTION.meetingId}`) { phase = 'meeting'; body = { id: CONNECTION.meetingId, host_id: 'host' }; }
        else if (u.pathname.startsWith('/v2/users/')) {
          phase = 'list'; const index = Number(u.searchParams.get('next_page_token') || 0);
          body = { meetings: rows.slice(index, index + 1).map(uuid => ({ id: CONNECTION.meetingId, uuid, start_time: '2026-10-04T08:17:00Z' })), next_page_token: index + 1 < rows.length ? String(index + 1) : '' };
        } else {
          phase = 'recording'; const uuid = u.pathname.split('/')[3]; inspected.push(uuid);
          body = uuid === 'eligible' ? sample : { ...sample, uuid, participant_audio_files: uuid === 'oversized' ? sample.participant_audio_files.map(file => ({ ...file, file_size: 300 * 1024 * 1024 })) : [] };
        }
        if (fail?.phase === phase && (!fail.uuid || inspected.at(-1) === fail.uuid)) return new Response('sensitive upstream body', { status: fail.status });
        return Response.json(body);
      }, streamImpl: async url => {
        downloaded.push(url);
        if (downloadFailure) throw Object.assign(new Error('Synthetic download denied'), { status: 502 });
        return new Response(A);
      }
    });
    return { client, inspected, downloaded };
  };
  const usable = make(); assert.equal((await usable.client.check(CONNECTION)).tracks, 'confirmed');
  assert.deepEqual(usable.inspected, ['empty', 'eligible']); assert.equal(usable.downloaded.length, 2);
  const none = make({ rows: ['empty', 'oversized', 'also-empty'] });
  assert.equal((await none.client.check(CONNECTION)).tracks, 'unconfirmed');
  assert.deepEqual(none.inspected, ['empty', 'oversized', 'also-empty']); assert.equal(none.downloaded.length, 0);
  const t = setup(), unconfirmed = new ZoomArchive(t.domain, { key, zoom: none.client });
  const checked = await unconfirmed.check({ revision: 0, connection: CONNECTION });
  await unconfirmed.mutate(mutation(0, 'save', { connection: CONNECTION, receipt: checked.receipt }));
  assert.equal((await unconfirmed.mutate(mutation(1, 'activate', { connectionId: CONNECTION.connectionId, confirmed: true }))).activeConnectionId, CONNECTION.connectionId);
  assert.equal((await make({ rows: [] }).client.check(CONNECTION)).tracks, 'unconfirmed');
  for (const fail of [{ phase: 'auth', status: 401 }, { phase: 'meeting', status: 404 }, { phase: 'list', status: 403 },
    { phase: 'recording', uuid: 'eligible', status: 403 }, { phase: 'recording', uuid: 'eligible', status: 401 }, { phase: 'list', status: 429 }]) {
    await assert.rejects(() => make({ fail }).client.check(CONNECTION), e => e.status === (fail.status === 429 ? 429 : 422) && !e.message.includes('sensitive'));
  }
  const denied = make({ rows: ['empty', 'eligible', 'later'], downloadFailure: true });
  await assert.rejects(() => denied.client.check(CONNECTION), /Synthetic download denied/);
  assert.deepEqual(denied.inspected, ['empty', 'eligible']); assert.equal(denied.downloaded.length, 1);
});

test('S12 A15 manual and Zoom discard survive lost DELETE/commit replies and new Gateway instances', async () => {
  for (const origin of ['manual', 'zoom_cloud']) {
    const t = origin === 'zoom_cloud' ? await configured() : setup(new SyntheticArchiveRepository());
    const op = origin === 'zoom_cloud' ? await reserve(t) : { idempotencyKey: randomUUID() };
    const plan = await planFor(op);
    if (origin === 'zoom_cloud') await upload(t, op, plan);
    else {
      const started = await t.domain.beginIngestion({ schemaVersion: 1, idempotencyKey: op.idempotencyKey, title: 'Manual interrupted discard', recordedAt: null, origin, supersedesSessionId: null, plan: serializeIngestionPlan(plan) });
      op.transactionId = started.transactionId;
      for (const track of plan.tracks) for (const part of track.parts) await t.domain.uploadPart(op.transactionId, track.blobId, part.partNumber, Buffer.from(await part.blob.arrayBuffer()), part.sha256, randomUUID());
    }
    const remove = t.repository.deleteRelease.bind(t.repository); let lostDelete = true, deletes = 0;
    t.repository.deleteRelease = async id => { deletes++; await remove(id); if (lostDelete) { lostDelete = false; throw new Error('Lost successful DELETE reply'); } };
    await assert.rejects(() => t.domain.recoverIncomplete(op.transactionId, 'discard'), /Lost successful DELETE/);
    const restarted = new AudioArchiveDomain(t.repository, { acceptedPartBytes: 1024 });
    const pending = (await restarted.listIncomplete()).transactions.find(row => row.transactionId === op.transactionId);
    assert.equal(pending.state, 'discarding'); assert.equal(pending.canFinalize, false); assert.equal(pending.requiresOriginalFiles, false);
    await assert.rejects(() => restarted.recoverIncomplete(op.transactionId, 'resume'), e => e.status === 409 && /discard/.test(e.message));
    await assert.rejects(() => restarted.finalizeIngestion(op.transactionId), e => e.status === 409);
    if (origin === 'zoom_cloud') {
      const zoom = new ZoomArchive(restarted, { key, zoom: t.zoom });
      assert.equal((await zoom.operation(op.id)).state, 'discarding'); assert.equal((await zoom.operation(op.id)).canFinalize, false);
    }
    const commit = t.repository.commitJson.bind(t.repository); let lostCommit = true;
    t.repository.commitJson = async (...args) => { const result = await commit(...args); if (lostCommit && args[2].startsWith('Discard ingestion ')) { lostCommit = false; throw new Error('Lost discard commit reply'); } return result; };
    await assert.rejects(() => restarted.recoverIncomplete(op.transactionId, 'discard'), /Lost discard commit/);
    const afterRestart = new AudioArchiveDomain(t.repository, { acceptedPartBytes: 1024 });
    assert.equal((await afterRestart.recoverIncomplete(op.transactionId, 'discard')).discarded, true);
    assert.equal((await afterRestart.listIncomplete()).transactions.length, 0);
    assert.equal(t.repository.releases.size, 0); assert.equal(deletes, 2);
    await assert.rejects(() => afterRestart.getSession(op.transactionId), e => e.status === 404);
    if (origin === 'zoom_cloud') assert.equal((await new ZoomArchive(afterRestart, { key, zoom: t.zoom }).operation(op.id)).state, 'discarded');
  }
});
