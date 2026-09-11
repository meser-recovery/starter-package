import test from 'node:test';
import assert from 'node:assert/strict';
import { createWaveformDetail } from '../../scripts/audio-waveform-detail.mjs';
const wait = () => new Promise(resolve => setTimeout(resolve, 220));
const canvas = () => ({ style: {}, dataset: {}, isConnected: true, getContext: () => ({ fillRect() {} }) });
test('detail decoding uses a bounded source window and reuses it across panning', async () => {
  const calls = [], file = {}, c = canvas();
  const detail = createWaveformDetail({ makeReader: () => ({
    async readWindow(...args) { calls.push(args); return new Float32Array(65536).fill(.3); }, dispose() {}
  }) });
  detail.draw(c, file, 3747, 1000, 80000, 800, 100, 17);
  await wait();
  assert.deepEqual(calls, [[file, 80, 32]]);
  assert.equal(c.dataset.waveDetail, 'ready'); assert.equal(c.width, 800);
  detail.draw(c, file, 3747, 1000, 81000, 800, 100, 17);
  await wait(); assert.equal(calls.length, 1);
  detail.clear();
});
test('late decode cannot paint a changed viewport or a replaced File session', async () => {
  let complete, signal;
  const file = {}, c = canvas();
  const detail = createWaveformDetail({ makeReader: s => {
    signal = s; return { readWindow: () => new Promise(resolve => { complete = resolve; }), dispose() {} };
  } });
  detail.draw(c, file, 3747, 1000, 80000, 800, 100, 17);
  await wait();
  detail.draw(c, file, 3747, 1000, 180000, 800, 100, 17);
  detail.clear(); assert.equal(signal.aborted, true);
  complete(new Float32Array(8)); await wait();
  assert.notEqual(c.dataset.waveDetail, 'ready');
});
test('zooming out during a decode does not replace the overview with stale detail', async () => {
  let complete;
  const file = {}, c = canvas();
  const detail = createWaveformDetail({ makeReader: () => ({
    readWindow: () => new Promise(resolve => { complete = resolve; }), dispose() {}
  }) });
  detail.draw(c, file, 3747, 1000, 80000, 800, 100, 17); await wait();
  detail.draw(c, file, 3747, .2, 0, 800, 100, 17);
  complete(new Float32Array(8)); await wait();
  assert.equal(c.dataset.waveDetail, 'overview'); detail.clear();
});

test('continuous Follow does not starve decoding and retains detail through prefetch', async () => {
  const file = {}, c = canvas(), calls = []; let release;
  const detail = createWaveformDetail({ makeReader: () => ({
    async readWindow(f, start, duration) {
      calls.push([start,duration]);
      if (calls.length > 1) await new Promise(resolve => { release = resolve; });
      const samples = new Float32Array(64000).fill(.3); samples.sampleRate = 2000; return samples;
    }, dispose() {}
  }) });
  const motion = setInterval(() => detail.draw(c, file, 73.3, 1000, 1000, 800, 100, 20), 16);
  try { await new Promise(resolve => setTimeout(resolve, 300)); } finally { clearInterval(motion); }
  assert.equal(c.dataset.waveDetail, 'ready'); assert.equal(calls.length, 1);
  assert.equal(detail.draw(c, file, 73.3, 1000, 9000, 800, 100, 20), true);
  assert.equal(calls.length, 1); // crossing an 8s key still uses the covering cache
  assert.equal(detail.draw(c, file, 73.3, 1000, 25000, 800, 100, 20), true);
  await new Promise(resolve => setTimeout(resolve, 30));
  assert.deepEqual(calls, [[0,32],[24,32]]);
  assert.equal(detail.draw(c, file, 73.3, 1000, 26000, 800, 100, 20), true);
  assert.equal(c.dataset.waveDetail, 'ready');
  release(); await new Promise(resolve => setTimeout(resolve, 30));
  assert.equal(c.dataset.waveDetail, 'ready'); assert.equal(c.dataset.detailStart, '24');
  detail.clear();
});

test('prefetch failure retains the covering detail and applies retry backoff', async () => {
  const file = {}, c = canvas(); let calls = 0;
  const detail = createWaveformDetail({ makeReader: () => ({
    async readWindow() { if (++calls > 1) throw new Error('temporary decoder failure'); return new Float32Array(64000).fill(.4); }, dispose() {}
  }) });
  detail.draw(c, file, 73.3, 1000, 1000, 800, 100, 20); await wait();
  assert.equal(detail.draw(c, file, 73.3, 1000, 25000, 800, 100, 20), true);
  await new Promise(resolve => setTimeout(resolve, 30));
  assert.equal(detail.draw(c, file, 73.3, 1000, 26000, 800, 100, 20), true);
  assert.equal(c.dataset.waveDetail, 'ready'); assert.equal(calls, 2);
  detail.clear();
});
