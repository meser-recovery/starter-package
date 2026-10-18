import test from 'node:test';
import assert from 'node:assert/strict';
import { AudioArchiveGateway as ProtectedGateway, prepareRemoteSourceBatch as protectedPrepare } from '../../../service/frontend/scripts/audio-archive-client.mjs';
import { AudioArchiveGateway as PublicGateway, prepareRemoteSourceBatch as publicPrepare } from '../../../scripts/audio-archive-client.mjs';
import { sourceFixture } from './s13-fixtures.mjs';

const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
const stale = error => error.name === 'AbortError' && error.code === 'stale_auth_response' && error.status !== 401;
const surfaces = [['protected', ProtectedGateway, protectedPrepare, ['json', 'binary', 'part']], ['public', PublicGateway, publicPrepare, ['json', 'part']]];

async function fixture(Gateway) {
  const h = await sourceFixture(); let sourceCalls = 0;
  const gateway = new Gateway('', async url => {
    if (url.endsWith('/session/login')) return json({});
    if (url.endsWith('/session')) return json({ authenticated: true, csrfToken: 'new-session-token' });
    const track = h.session.sourceTracks.find(t => url.includes(`/blobs/${t.blobId}/`));
    const part = track?.parts.find(p => url.includes(`/parts/${p.partNumber}/content`));
    assert.ok(part, url); sourceCalls++; return h.fetchPart(part.downloadUrl);
  });
  gateway.getSession = async () => structuredClone(h.session);
  return { h, gateway, sourceCalls: () => sourceCalls };
}
function invoke(gateway, h, boundary) {
  if (boundary === 'binary') return gateway.requestBinary('/late-waveform');
  if (boundary === 'part') return gateway.sourcePartFetch(h.session)(h.session.sourceTracks[0].parts[0].downloadUrl);
  return gateway.request('/late-json');
}

for (const [surface, Gateway, prepare, boundaries] of surfaces) {
  for (const boundary of boundaries) {
    test(`S13 ${surface} late ${boundary} 401 cannot clear new CSRF, abort new preparation or invalidate its reuse`, async () => {
      const f = await fixture(Gateway), { gateway, h } = f, gate = deferred(), started = deferred();
      const fetch = gateway.fetchImpl;
      gateway.fetchImpl = async (...args) => { started.resolve(); return gate.promise; };
      const old = invoke(gateway, h, boundary); const rejected = assert.rejects(old, stale);
      await started.promise; gateway.fetchImpl = fetch;
      await gateway.login('synthetic-password');
      const batch = await prepare({ gateway, sessionId: h.session.id });
      const generation = gateway.authGeneration, calls = f.sourceCalls(), controller = new AbortController();
      gateway.activeSourcePreparation = { controller };
      let cancelled = 0;
      gate.resolve(new Response(new ReadableStream({ cancel() { cancelled++; } }), { status: 401 }));
      await rejected;
      assert.equal(cancelled, 1); assert.equal(gateway.csrfToken, 'new-session-token');
      assert.equal(gateway.authGeneration, generation); assert.equal(controller.signal.aborted, false);
      gateway.activeSourcePreparation = null;
      const warm = await prepare({ gateway, sessionId: h.session.id, reuseBatch: batch });
      assert.equal(warm.reused, true); assert.equal(f.sourceCalls(), calls);
    });

    test(`S13 ${surface} current ${boundary} 401 aborts preparation and invalidates verified reuse`, async () => {
      const f = await fixture(Gateway), { gateway, h } = f;
      const batch = await prepare({ gateway, sessionId: h.session.id }), fetch = gateway.fetchImpl;
      gateway.csrfToken = 'current'; const controller = new AbortController(); gateway.activeSourcePreparation = { controller };
      gateway.fetchImpl = async () => json({ error: 'expired' }, 401);
      const generation = gateway.authGeneration;
      await assert.rejects(invoke(gateway, h, boundary), error => error.status === 401);
      assert.equal(gateway.csrfToken, null); assert.ok(gateway.authGeneration > generation);
      assert.equal(controller.signal.aborted, true); assert.equal(controller.signal.reason.status, 401);
      gateway.activeSourcePreparation = null; gateway.fetchImpl = fetch;
      await gateway.login('synthetic-password'); const calls = f.sourceCalls();
      const fresh = await prepare({ gateway, sessionId: h.session.id, reuseBatch: batch });
      assert.equal(fresh.reused, false); assert.ok(f.sourceCalls() > calls);
    });
  }

  test(`S13 ${surface} delayed JSON 401 body and late login replay cannot poison a new session`, async () => {
    for (const replay of [false, true]) {
      const f = await fixture(Gateway), { gateway } = f, fetch = gateway.fetchImpl;
      const body = deferred(), entered = deferred();
      const response = json({}, 401);
      response.json = async () => { entered.resolve(); return body.promise; };
      gateway.fetchImpl = async url => url.endsWith('/session/login') ? json({}) : response;
      const old = replay ? gateway.login('old') : gateway.request('/old-body');
      const settled = replay ? old : assert.rejects(old, stale);
      await entered.promise; gateway.fetchImpl = fetch; await gateway.login('new');
      const generation = gateway.authGeneration; body.resolve({ error: 'expired old session' });
      if (replay) assert.deepEqual(await settled, { authenticated: false, stale: true }); else await settled;
      assert.equal(gateway.csrfToken, 'new-session-token'); assert.equal(gateway.authGeneration, generation);
    }
  });

  test(`S13 ${surface} late logout completion cannot clear a newly replayed CSRF`, async () => {
    const { gateway } = await fixture(Gateway), fetch = gateway.fetchImpl, gate = deferred(), entered = deferred();
    gateway.fetchImpl = async () => { entered.resolve(); return gate.promise; };
    const logout = assert.rejects(gateway.logout(), stale); await entered.promise;
    gateway.fetchImpl = fetch; await gateway.login('new');
    gate.resolve(new Response(null, { status: 204 })); await logout;
    assert.equal(gateway.csrfToken, 'new-session-token');
  });

  test(`S13 ${surface} explicit strict attention refresh does not join an earlier in-flight read`, async () => {
    const gate = deferred(); let calls = 0;
    const gateway = new Gateway('', async () => ++calls === 1 ? gate.promise : json({ snapshot: 'b'.repeat(40), transactions: [] }));
    const old = gateway.listAttention(), shared = gateway.listAttention();
    const freshRead = gateway.listAttention({ refresh: true }), callsBeforeOldRelease = calls;
    gate.resolve(json({ snapshot: 'a'.repeat(40), transactions: [] }));
    const fresh = await freshRead;
    assert.equal(callsBeforeOldRelease, 2); assert.equal(fresh.snapshot, 'b'.repeat(40));
    assert.equal((await old).snapshot, 'a'.repeat(40)); assert.deepEqual(await shared, await old);
  });
}

test('S13 protected late successful binary body cannot be adopted by the new session', async () => {
  const { gateway } = await fixture(ProtectedGateway), fetch = gateway.fetchImpl, body = deferred(), entered = deferred();
  const response = new Response(null, { headers: { 'Content-Type': 'application/vnd.meser.waveform-f32le' } });
  response.arrayBuffer = async () => { entered.resolve(); return body.promise; };
  gateway.fetchImpl = async () => response;
  const old = assert.rejects(gateway.requestBinary('/old-waveform'), stale);
  await entered.promise; gateway.fetchImpl = fetch; await gateway.login('new');
  body.resolve(new ArrayBuffer(4)); await old;
  assert.equal(gateway.csrfToken, 'new-session-token');
});

for (const [surface, Gateway] of surfaces) test(`S13 ${surface} late login POST 401 cannot invalidate the new login`, async () => {
  const { gateway } = await fixture(Gateway), fetch = gateway.fetchImpl, gate = deferred(), entered = deferred();
  gateway.fetchImpl = async () => { entered.resolve(); return gate.promise; };
  const old = gateway.login('old'); await entered.promise;
  gateway.fetchImpl = fetch; await gateway.login('new');
  const generation = gateway.authGeneration; gate.resolve(json({ error: 'old password' }, 401));
  assert.deepEqual(await old, { authenticated: false, stale: true });
  assert.equal(gateway.authGeneration, generation); assert.equal(gateway.csrfToken, 'new-session-token');
});

test('S13 current binary 401 aborts immediately; its delayed error body cannot affect a later login', async () => {
  const { gateway } = await fixture(ProtectedGateway), fetch = gateway.fetchImpl, entered = deferred(), body = deferred();
  const response = json({}, 401); response.json = async () => { entered.resolve(); return body.promise; };
  gateway.fetchImpl = async () => response;
  const controller = new AbortController(); gateway.activeSourcePreparation = { controller };
  const old = assert.rejects(gateway.requestBinary('/expired-waveform'), stale);
  await entered.promise;
  assert.equal(controller.signal.aborted, true); assert.equal(controller.signal.reason.status, 401);
  gateway.activeSourcePreparation = null; gateway.fetchImpl = fetch; await gateway.login('new');
  const generation = gateway.authGeneration; body.resolve({ error: 'old expired response' }); await old;
  assert.equal(gateway.authGeneration, generation); assert.equal(gateway.csrfToken, 'new-session-token');
});

for (const [surface, Gateway, , boundaries] of surfaces) for (const boundary of boundaries) {
  test(`S13 ${surface} ${boundary} error-body cancellation cannot emit an old 401 into a newer session`, async () => {
    const { gateway, h } = await fixture(Gateway), fetch = gateway.fetchImpl, entered = deferred(), cancel = deferred();
    gateway.fetchImpl = async () => new Response(new ReadableStream({ cancel() { entered.resolve(); return cancel.promise; } }), { status: 401 });
    const controller = new AbortController(); gateway.activeSourcePreparation = { controller };
    const old = assert.rejects(invoke(gateway, h, boundary), stale);
    await entered.promise; assert.equal(controller.signal.aborted, true);
    gateway.activeSourcePreparation = null; gateway.fetchImpl = fetch; await gateway.login('new');
    const generation = gateway.authGeneration; cancel.resolve(); await old;
    assert.equal(gateway.csrfToken, 'new-session-token'); assert.equal(gateway.authGeneration, generation);
  });
}
