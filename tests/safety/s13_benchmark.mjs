// Read-only synthetic benchmark. No production URLs, credentials or archive writes.
// Run before runtime edits, then identically on the candidate:
// node tests/safety/s13_benchmark.mjs --output tests/safety/evidence/s13/base.json
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { writeFile, mkdir, readFile } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { pathToFileURL } from 'node:url';
import os from 'node:os';
import { performance } from 'node:perf_hooks';

const args = process.argv.slice(2), arg = (key, fallback) => args.includes(key) ? args[args.indexOf(key) + 1] : fallback;
const root = resolve(arg('--root', '.'));
const load = path => import(pathToFileURL(resolve(root, path)));
const { AudioArchiveDomain } = await load('gateway/audio-archive/src/domain.mjs');
const { GitHubArchiveRepository } = await load('gateway/audio-archive/src/github.mjs');
const { MemoryRepository, sha } = await load('gateway/audio-archive/test/helpers.mjs');
const client = await load('service/frontend/scripts/audio-archive-client.mjs');
const { catalogEntry } = await load('gateway/audio-archive/src/validation.mjs');
const clock = () => Date.parse('2026-10-18T08:00:00.000Z');
const uuid = n => `10000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const seed = 's13-fixture-v1';
const json = data => new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } });
const pause = ms => ms ? new Promise(resolve => setTimeout(resolve, ms)) : Promise.resolve();

async function fixture(trackCount = 1, partBytes = 4, bytes = Buffer.from('source-audio'), extension = 'wav') {
  const repository = new MemoryRepository();
  const domain = new AudioArchiveDomain(repository, { acceptedPartBytes: partBytes, clock });
  const files = Array.from({ length: trackCount }, (_, i) => new File([bytes], `Дорожка-${i + 1}.${extension}`, { type: extension === 'm4a' ? 'audio/mp4' : 'audio/wav' }));
  const idempotencyKey = seed + trackCount + partBytes;
  const plan = await client.createIngestionPlan(files, partBytes, { idempotencyKey });
  const op = await domain.beginIngestion({ schemaVersion: 1, idempotencyKey, title: 'Запись', recordedAt: null, origin: 'manual', supersedesSessionId: null, plan: client.serializeIngestionPlan(plan) });
  for (const track of plan.tracks) for (const part of track.parts) await domain.uploadPart(op.transactionId, track.blobId, part.partNumber,
    Buffer.from(await part.blob.arrayBuffer()), part.sha256, `${seed}:${track.blobId}:${part.partNumber}`);
  return { repository, session: (await domain.finalizeIngestion(op.transactionId)).session };
}

function mockRepository(files, latencyMs = 0) {
  const counts = { repository: {}, http: { jsonRequests: 0, jsonBytes: 0, assetRequests: 0, assetBytes: 0 }, reads: {} };
  const blobs = new Map([...files].map(([path, data]) => [path, { data, sha: sha(Buffer.from(JSON.stringify(data))) }]));
  const bySha = new Map([...blobs.values()].map(b => [b.sha, b]));
  const http = async (input, options = {}) => {
    assert.equal(options.method || 'GET', 'GET', 'benchmark cannot mutate remote storage');
    if (typeof latencyMs === 'number') await pause(latencyMs);
    const url = new URL(input), path = url.pathname.replace('/repos/meser-recovery/audio-archive', '');
    let data;
    if (path === '/git/ref/heads/main') data = { object: { sha: 'immutable-fixture-head' } };
    else if (path === '/git/trees/immutable-fixture-head') data = { truncated: false, tree: [...blobs].map(([path, b]) => ({ path, type: 'blob', sha: b.sha })) };
    else if (path.startsWith('/git/blobs/')) { const b = bySha.get(path.split('/').at(-1)); data = { encoding: 'base64', content: Buffer.from(JSON.stringify(b.data)).toString('base64') }; }
    else if (path.startsWith('/contents/')) { const b = blobs.get(decodeURIComponent(path.slice(10))); data = b ? { type: 'file', encoding: 'base64', sha: b.sha, content: Buffer.from(JSON.stringify(b.data)).toString('base64') } : null; }
    else if (path === '/releases') data = [];
    else throw new Error(`Unimplemented synthetic HTTP API ${path}`);
    const response = json(data); counts.http.jsonRequests++; counts.http.jsonBytes += Buffer.byteLength(JSON.stringify(data));
    if (typeof latencyMs === 'object') await pause(latencyMs.rttMs + Buffer.byteLength(JSON.stringify(data)) / latencyMs.bytesPerSecond * 1000);
    if (data === null) return new Response('{}', { status: 404, headers: { 'Content-Type': 'application/json' } });
    return response;
  };
  const repository = new GitHubArchiveRepository({ storageOwner: 'meser-recovery', storageRepository: 'audio-archive', storageBranch: 'main' }, http, clock);
  repository.installationToken = { value: 'synthetic-no-network', expiresAt: Number.MAX_SAFE_INTEGER };
  for (const key of Object.getOwnPropertyNames(GitHubArchiveRepository.prototype)) {
    if (key === 'constructor' || typeof repository[key] !== 'function' || ['api', 'headers', 'readJsonResponse', 'token'].includes(key)) continue;
    const method = repository[key].bind(repository);
    repository[key] = (...args) => {
      counts.repository[key] = (counts.repository[key] || 0) + 1;
      if (key === 'readJson') { const kind = args[0].split('/')[0]; counts.reads[kind] = (counts.reads[kind] || 0) + 1; }
      if (key === 'readJsonBlob') counts.reads.sessions = (counts.reads.sessions || 0) + 1;
      return method(...args);
    };
  }
  const reset = () => { counts.repository = {}; counts.reads = {}; counts.http = { jsonRequests: 0, jsonBytes: 0, assetRequests: 0, assetBytes: 0 }; };
  return { repository, counts, reset };
}
const summarize = values => {
  const ordered = [...values].sort((a, b) => a - b);
  return { repeats: values.length, medianMs: ordered[Math.floor(ordered.length / 2)],
    ...(values.length >= 20 ? { p95Ms: ordered[Math.ceil(.95 * ordered.length) - 1] } : { minMs: ordered[0], maxMs: ordered.at(-1) }) };
};
const template = await fixture();
if (args.includes('--metadata-network')) {
  const { selectSessions } = await load('service/frontend/scripts/audio-archive-core.mjs');
  const scenarios = [];
  for (const n of [1, 10, 100, 1000]) for (const profile of [{ name: 'ordinary', rttMs: 10, bytesPerSecond: 10_000_000 }, { name: 'high-rtt', rttMs: 80, bytesPerSecond: 1_000_000 }]) {
    const files = new Map(), sessions = [];
    for (let i = 1; i <= n; i++) {
      const id = uuid(i), session = JSON.parse(JSON.stringify(template.session).replaceAll(template.session.id, id));
      session.id = id; session.title = i === n ? 'Последняя запись' : `Запись ${i}`;
      session.lifecycle.state = i % 2 ? 'incoming' : 'archived';
      sessions.push(session); files.set(`sessions/${id}.json`, session);
    }
    files.set('catalog.json', { schemaVersion: 1, revision: n, updatedAt: new Date(clock()).toISOString(), entries: sessions.map(catalogEntry) });
    // Twenty isolated cold-start instances, not twenty queries against one shared
    // server. This bounds wall time while keeping cache/coalescing semantics clear.
    const raw = await Promise.all(Array.from({ length: 20 }, async (_, repeat) => {
      const f = mockRepository(files, profile), d = new AudioArchiveDomain(f.repository, { acceptedPartBytes: 4, clock });
      const modern = typeof d.querySessions === 'function';
      const read = async () => modern ? d.querySessions({}) : { sessions: (await Promise.all([d.listSessions('incoming'), d.listSessions('archived')])).flatMap(list => list.sessions) };
      let start = performance.now(); const cold = await read();
      const coldMs = performance.now() - start, coldCounts = structuredClone(f.counts);
      f.reset(); start = performance.now(); const warm = await read();
      const warmMs = performance.now() - start, warmCounts = structuredClone(f.counts);
      f.reset(); start = performance.now();
      const page = modern ? (await d.querySessions({ page: 1 })).items : selectSessions(warm.sessions, {}).slice(10, 20);
      const pageMs = performance.now() - start, pageCounts = structuredClone(f.counts);
      f.reset(); start = performance.now();
      const search = modern ? (await d.querySessions({ search: 'Последняя' })).items : selectSessions(warm.sessions, { search: 'Последняя' });
      const searchMs = performance.now() - start, searchCounts = structuredClone(f.counts);
      assert.equal(search.length, 1); assert.equal(search[0].id, uuid(n)); assert.ok(page.length <= 10);
      return { repeat, coldMs, warmMs, pageMs, searchMs, coldCounts, warmCounts, pageCounts, searchCounts,
        coldResponseBytes: Buffer.byteLength(JSON.stringify(cold)), warmResponseBytes: Buffer.byteLength(JSON.stringify(warm)) };
    }));
    scenarios.push({ n, profile, cold: summarize(raw.map(r => r.coldMs)), warmReopen: summarize(raw.map(r => r.warmMs)),
      page2: summarize(raw.map(r => r.pageMs)), search: summarize(raw.map(r => r.searchMs)), raw });
    console.log(`metadata network N=${n} ${profile.name}: 20 isolated repeats complete`);
  }
  const revision = { sha: arg('--sha', '') || execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim(),
    tree: arg('--tree', '') || execFileSync('git', ['rev-parse', 'HEAD^{tree}'], { cwd: root, encoding: 'utf8' }).trim() };
  const output = resolve(arg('--output', '/private/tmp/s13-checks/metadata-network.json'));
  await writeFile(output, JSON.stringify({ kind: 'isolated-synthetic-GitHub-Fetch-network-model', revision, seed,
    fixtureHash: createHash('sha256').update(JSON.stringify(template.session)).digest('hex'), scenarios,
    methodology: '20 concurrent isolated domain/repository instances per case; each cold then same-instance warm reopen. Delay at each mock GitHub JSON Response: RTT + encoded JSON bytes / bandwidth. No shared-link contention or production/geography inference. Legacy page/search operate on already returned client manifests; candidate pages/search incur a fresh HEAD check. Gateway→browser RTT not injected here. Resource/RSS claims excluded from this concurrent model.' }, null, 2) + '\n');
  process.exit(0);
}
const metadata = [], raw = [];
for (const n of [1, 10, 100, 1000]) {
  const files = new Map(), sessions = [];
  for (let i = 1; i <= n; i++) {
    const session = structuredClone(template.session), id = uuid(i);
    session.id = id; session.title = i === n ? 'Последняя Ё запись' : `Запись ${i}`;
    session.lifecycle.state = i % 2 ? 'incoming' : 'archived'; session.recordedAt = `2026-10-${String(i % 28 + 1).padStart(2, '0')}T08:00:00.000Z`;
    session.storage = { releaseId: i, tag: `audio-session-${id}` };
    for (const track of session.sourceTracks) for (const part of track.parts) part.downloadUrl = part.downloadUrl.replace(template.session.id, id);
    sessions.push(session); files.set(`sessions/${id}.json`, session);
  }
  files.set('catalog.json', { schemaVersion: 1, revision: n, updatedAt: new Date(clock()).toISOString(), entries: sessions.map(catalogEntry) });
  const f = mockRepository(files), domain = new AudioArchiveDomain(f.repository, { acceptedPartBytes: 4, clock });
  for (const scenario of ['cold-list', 'warm-list', 'page-2', 'last-page-search', 'empty-search', 'archived']) {
    const rows = [];
    for (let repeat = 0; repeat < 20; repeat++) {
      const d = scenario === 'cold-list' ? new AudioArchiveDomain(f.repository, { acceptedPartBytes: 4, clock }) : domain;
      f.reset(); const start = performance.now();
      let result;
      if (typeof d.querySessions === 'function') result = await d.querySessions({ page: scenario === 'page-2' ? 1 : 0,
        lifecycle: scenario === 'archived' ? 'archived' : '', search: scenario === 'last-page-search' ? 'Последняя' : scenario === 'empty-search' ? 'does-not-exist' : '' });
      else { const lists = await Promise.all([d.listSessions('incoming'), d.listSessions('archived')]); result = { sessions: lists.flatMap(list => list.sessions) }; }
      const row = { n, scenario, repeat, durationMs: performance.now() - start, responseBytes: Buffer.byteLength(JSON.stringify(result)), counts: structuredClone(f.counts) };
      rows.push(row); raw.push(row);
    }
    metadata.push({ n, scenario, ...summarize(rows.map(row => row.durationMs)), counts: rows.at(-1).counts, responseBytes: rows.at(-1).responseBytes });
  }
}
const audio = [];
for (const tracks of [1, 3]) for (const multipart of [false, true]) for (const profile of [{ name: 'ordinary', rttMs: 10, bytesPerSecond: 10_000_000 }, { name: 'high-rtt', rttMs: 80, bytesPerSecond: 1_000_000 }]) {
  const f = await fixture(tracks, multipart ? 4 : 64), rows = [];
  for (let repeat = 0; repeat < 5; repeat++) {
    let active = 0, peak = 0, calls = 0, bytes = 0, peakPayloadBytes = 0, payloadBytes = 0;
    const start = performance.now();
    const result = await client.reconstructSessionTracks(f.session, async url => {
      const part = f.session.sourceTracks.flatMap(t => t.parts).find(p => p.downloadUrl === url);
      active++; peak = Math.max(peak, active); payloadBytes += part.sizeBytes; peakPayloadBytes = Math.max(peakPayloadBytes, payloadBytes);
      await pause(profile.rttMs + part.sizeBytes / profile.bytesPerSecond * 1000); calls++; bytes += part.sizeBytes;
      active--; payloadBytes -= part.sizeBytes; return new Response(f.repository.assetBytes.get(part.assetId));
    });
    assert.equal(result.length, tracks);
    for (const file of result) assert.equal(sha(Buffer.from(await file.arrayBuffer())), f.session.sourceTracks[0].sha256);
    rows.push({ durationMs: performance.now() - start, calls, bytes, maxActiveTransfers: peak, peakActivePayloadBytes: peakPayloadBytes, rss: process.memoryUsage().rss });
  }
  audio.push({ tracks, multipart, profile, cache: 'cold', ...summarize(rows.map(row => row.durationMs)), raw: rows });
}
const realistic = [];
if (args.includes('--realistic')) {
  const bytes = await readFile(resolve('tests/safety/fixtures/s10a-long-aac-lc-3747s.m4a'));
  const f = await fixture(3, 256 * 1024, bytes, 'm4a');
  for (const profile of [{ name: 'ordinary', rttMs: 10, bytesPerSecond: 10_000_000 }, { name: 'high-rtt', rttMs: 80, bytesPerSecond: 1_000_000 }]) {
    const rows = [];
    for (let repeat = 0; repeat < 5; repeat++) {
      let active = 0, max = 0, calls = 0, transferred = 0, rss = 0;
      const start = performance.now();
      const files = await client.reconstructSessionTracks(f.session, async url => {
        const part = f.session.sourceTracks.flatMap(t => t.parts).find(p => p.downloadUrl === url);
        active++; max = Math.max(max, active); rss = Math.max(rss, process.memoryUsage().rss);
        await pause(profile.rttMs + part.sizeBytes / profile.bytesPerSecond * 1000);
        active--; calls++; transferred += part.sizeBytes;
        return new Response(f.repository.assetBytes.get(part.assetId));
      });
      const verifiedMs = performance.now() - start;
      for (const file of files) assert.equal(sha(Buffer.from(await file.arrayBuffer())), sha(bytes));
      rows.push({ verifiedMs, calls, assetBytes: transferred, maxActiveTransfers: max, rss });
    }
    realistic.push({ fixture: 'existing 3747-second AAC-LC M4A, three ordered logical tracks', fixtureSha256: sha(bytes), sourceBytes: bytes.length * 3,
      profile, ...summarize(rows.map(row => row.verifiedMs)), raw: rows });
  }
}
const git = (...args) => execFileSync('git', args, { cwd: root, encoding: 'utf8' }).trim();
const report = { kind: 'synthetic-fetch-boundaries-not-production', seed, fixtureHash: createHash('sha256').update(JSON.stringify(template.session)).digest('hex'),
  revision: { sha: arg('--sha', '') || git('rev-parse', 'HEAD'), tree: arg('--tree', '') || git('rev-parse', 'HEAD^{tree}'), dirty: arg('--sha', '') ? 'git archive snapshot; harness outside runtime tree' : git('status', '--short') },
  environment: { node: process.version, os: `${os.platform()} ${os.release()} ${os.arch()}`, cpu: os.cpus()[0]?.model, logicalCpus: os.cpus().length, totalMemory: os.totalmem(), browser: 'NOT_RUN' },
  methodology: { metadataRepeats: 20, metadataNetwork: 'in-process Fetch mock; zero injected delay', audioRepeats: 5, delayAppliedAt: 'part fetch before Response; RTT + bytes/bandwidth; no geography inference', memory: 'Node RSS samples, not browser or Gateway isolated RSS' },
  metadata, audio, realistic, raw, notRun: ['physical Safari/Android', 'remote geography', 'production', 'browser stage timings', ...(!realistic.length ? ['realistic audio'] : []), 'near-limit resources'] };
const output = resolve(arg('--output', '/private/tmp/s13-benchmark.json')); await mkdir(dirname(output), { recursive: true });
const countSets = [], countIndex = new Map();
const compactRaw = raw.map(row => {
  const key = JSON.stringify(row.counts);
  if (!countIndex.has(key)) { countIndex.set(key, countSets.length); countSets.push(row.counts); }
  return [row.n, row.scenario, row.repeat, row.durationMs, row.responseBytes, countIndex.get(key)];
});
delete report.raw;
report.rawColumns = ['n', 'scenario', 'repeat', 'durationMs', 'responseBytes', 'countSet']; report.countSets = countSets;
await writeFile(output, JSON.stringify(report, null, 2).slice(0, -2) + ',\n  "raw": [\n' + compactRaw.map(row => '    ' + JSON.stringify(row)).join(',\n') + '\n  ]\n}\n');
console.log(JSON.stringify({ output, revision: report.revision, metadataScenarios: metadata.length, audioScenarios: audio.length }));
