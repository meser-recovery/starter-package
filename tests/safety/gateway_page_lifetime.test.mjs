import test from 'node:test';
import assert from 'node:assert/strict';
import { AudioArchiveGateway } from '../../service/frontend/scripts/audio-archive-client.mjs';
const json = value => new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } });

test('document departure fences late config continuations without invalidating authentication', async () => {
  const page = new EventTarget();
  let release, calls = 0;
  const gateway = new AudioArchiveGateway('', async () => { calls++; return new Promise(resolve => { release = resolve; }); }, page);
  const generation = gateway.authGeneration;
  const pending = gateway.configuration().then(() => gateway.request('/v1/storage-usage'));
  page.dispatchEvent(new Event('beforeunload'));
  release(json({ zoomCloudImport: 1 }));
  await assert.rejects(pending, { name: 'AbortError' });
  await assert.rejects(gateway.request('/v1/storage-usage'), { name: 'AbortError' });
  assert.equal(calls, 1, 'no fetch may start in the departing document');
  assert.equal(gateway.authGeneration, generation);
});

test('restored page gets a fresh read while abandoned response cannot clear new state', async () => {
  const page = new EventTarget();
  let release, calls = 0;
  const gateway = new AudioArchiveGateway('', async () => {
    if (++calls === 1) return new Promise(resolve => { release = resolve; });
    return json({ value: 'new' });
  }, page);
  gateway.csrfToken = 'synthetic-current';
  const old = gateway.request('/same');
  page.dispatchEvent(new Event('pagehide'));
  page.dispatchEvent(new Event('pageshow'));
  assert.deepEqual(await gateway.request('/same'), { value: 'new' });
  release(new Response('{"error":"old"}', { status: 401, headers: { 'Content-Type': 'application/json' } }));
  await assert.rejects(old, { name: 'AbortError' });
  assert.equal(gateway.authGeneration, 0);
  assert.equal(gateway.csrfToken, 'synthetic-current');
});

test('binary and JSON requests keep caller cancellation as well as document lifetime', async () => {
  const page = new EventTarget();
  let calls = 0;
  const gateway = new AudioArchiveGateway('', async () => { calls++; return json({}); }, page);
  const controller = new AbortController(); controller.abort();
  await assert.rejects(gateway.request('/json', { signal: controller.signal }), { name: 'AbortError' });
  await assert.rejects(gateway.requestBinary('/binary', { signal: controller.signal }), { name: 'AbortError' });
  page.dispatchEvent(new Event('beforeunload'));
  await assert.rejects(gateway.requestBinary('/binary'), { name: 'AbortError' });
  assert.equal(calls, 0);
});
