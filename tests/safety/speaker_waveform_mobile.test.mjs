import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import {
  WAVEFORM_CHUNK_RGBA_BYTES,
  WAVEFORM_CHUNK_WIDTH,
  WAVEFORM_SAMPLE_COUNT,
  createWaveformReader,
  planWaveformChunks
} from '../../scripts/speaker-waveform.mjs';

const DURATION = 3747.648;
const FIXTURE = new URL('./fixtures/s10a-long-aac-lc-3747s.m4a', import.meta.url);

function mp4Duration(bytes) {
  const marker = Buffer.from('mvhd');
  const index = bytes.indexOf(marker);
  assert.ok(index > 0, 'mvhd box missing');
  const version = bytes[index + 4];
  if (version === 0) return bytes.readUInt32BE(index + 20) / bytes.readUInt32BE(index + 16);
  assert.equal(version, 1);
  return Number(bytes.readBigUInt64BE(index + 28)) / bytes.readUInt32BE(index + 24);
}

function widthFromArgs(args) {
  const filter = args[args.indexOf('-filter_complex') + 1];
  const match = /showwavespic=s=(\d+)x100/.exec(filter);
  assert.ok(match, filter);
  return Number(match[1]);
}

function harness({ fail = null, abort = null, controller = null, cleanupFailure = false, exitCode = 0 } = {}) {
  const metrics = { engines: 0, terminated: 0, activeEngines: 0, maximumActiveEngines: 0,
    activeOutputs: 0, maximumActiveOutputs: 0, execWidths: [], execArgs: [], paths: new Set(), deletes: [] };
  let failed = false;
  const trigger = stage => {
    if (abort === stage) controller.abort();
    if (fail === stage && !failed) { failed = true; throw Object.assign(new Error('private participant filename must not escape'), { name: `${stage}Failure` }); }
  };
  class Engine {
    constructor() { this.files = new Map(); this.live = true; metrics.engines++; metrics.activeEngines++;
      metrics.maximumActiveEngines = Math.max(metrics.maximumActiveEngines, metrics.activeEngines); }
    async load() { trigger('engine-load'); }
    async writeFile(path, bytes) { trigger('wasm-write'); this.files.set(path, bytes); metrics.paths.add(path); }
    async exec(args) {
      trigger('ffmpeg-exec');
      const width = widthFromArgs(args), output = args.at(-1);
      metrics.execWidths.push(width); metrics.execArgs.push(args); metrics.activeOutputs++;
      metrics.maximumActiveOutputs = Math.max(metrics.maximumActiveOutputs, metrics.activeOutputs);
      const pixels = new Uint8Array(width * 100 * 4);
      for (let x = 0; x < width; x++) pixels[(25 * width + x) * 4] = 255;
      this.files.set(output, pixels); metrics.paths.add(output);
      return exitCode;
    }
    async readFile(path) {
      trigger('wasm-read');
      const bytes = this.files.get(path);
      if (fail === 'peak-conversion' && !failed) { failed = true; return bytes.subarray(1); }
      if (abort === 'peak-conversion') {
        class AbortBytes extends Uint8Array {
          get byteLength() { controller.abort(); return super.byteLength; }
        }
        return new AbortBytes(bytes);
      }
      return bytes;
    }
    async deleteFile(path) {
      metrics.deletes.push(path);
      if (cleanupFailure && path.endsWith('.rgba') && !failed) { failed = true; throw Object.assign(new Error('private cleanup detail'), { name: 'CleanupFailure' }); }
      if (path.endsWith('.rgba') && this.files.has(path)) metrics.activeOutputs--;
      this.files.delete(path); metrics.paths.delete(path);
    }
    terminate() { if (!this.live) return; this.live = false; metrics.terminated++; metrics.activeEngines--; this.files.clear(); metrics.paths.clear(); metrics.activeOutputs = 0; }
  }
  return { metrics, createEngine: async () => new Engine(), trigger };
}

test('non-zero FFmpeg exit code is retained without unsafe process output', async () => {
  const fake = harness({ exitCode: 37 });
  const reader = createWaveformReader(undefined, null, { createEngine: fake.createEngine, onDiagnostic() {} });
  await assert.rejects(reader.read(longFile(), DURATION, { trackIndex: 3 }), error => {
    assert.equal(error.waveformDiagnostic.stage, 'ffmpeg-exec');
    assert.equal(error.waveformDiagnostic.exitCode, 37);
    assert.equal(error.waveformDiagnostic.exceptionType, null);
    return true;
  });
  reader.dispose();
});

const longFile = (arrayBuffer = async () => Uint8Array.of(1, 2, 3).buffer) => ({
  name: 'private-participant-name.m4a', type: 'audio/mp4', size: 3, arrayBuffer
});

test('exact committed fixture is AAC-LC/M4A and longer than 60 minutes', async () => {
  const bytes = await readFile(FIXTURE);
  assert.equal(bytes.length, 1767839);
  assert.equal(createHash('sha256').update(bytes).digest('hex'), 'dc6446f9e6f32145ca1d6173726a129f28bcfe1479939a4b37279383580f1d0b');
  assert.equal(bytes.includes(Buffer.from('M4A ')), true);
  assert.equal(bytes.includes(Buffer.from('mp4a')), true);
  assert.equal(mp4Duration(bytes), DURATION);
  assert.ok(mp4Duration(bytes) > 3600);
});

test('chunk plan is deterministic, gapless and bounded through the final remainder', () => {
  const plan = planWaveformChunks(DURATION, WAVEFORM_SAMPLE_COUNT);
  assert.equal(plan.length, 16);
  assert.equal(plan[0].startSeconds, 0);
  assert.equal(plan.at(-1).endSeconds, DURATION);
  assert.equal(plan.reduce((sum, chunk) => sum + chunk.width, 0), WAVEFORM_SAMPLE_COUNT);
  for (const [index, chunk] of plan.entries()) {
    assert.ok(chunk.width <= WAVEFORM_CHUNK_WIDTH);
    assert.ok(chunk.expectedOutputBytes <= WAVEFORM_CHUNK_RGBA_BYTES);
    if (index) {
      assert.equal(chunk.binStart, plan[index - 1].binEnd);
      assert.equal(chunk.startSeconds, plan[index - 1].endSeconds);
    }
  }
  const remainder = planWaveformChunks(73.3, 65535);
  assert.equal(remainder.at(-1).width, 4095);
  assert.equal(remainder.at(-1).endSeconds, 73.3);
});

test('long source bypasses Web Audio and produces equivalent full-resolution peaks sequentially', async () => {
  const previous = globalThis.AudioContext;
  let nativeCalls = 0;
  globalThis.AudioContext = class { constructor() { nativeCalls++; } };
  const fake = harness();
  const diagnostics = [];
  try {
    const reader = createWaveformReader(undefined, null, { createEngine: fake.createEngine, onDiagnostic: value => diagnostics.push(value) });
    const samples = await reader.read(longFile(), DURATION, { trackIndex: 1 });
    reader.dispose();
    assert.equal(nativeCalls, 0);
    assert.equal(samples.length, WAVEFORM_SAMPLE_COUNT);
    assert.equal(samples.sampleRate, 48000 / planWaveformChunks(DURATION, WAVEFORM_SAMPLE_COUNT)[0].samplesPerColumn);
    assert.ok(samples.every(value => Math.abs(value - .5) < 1e-6));
    assert.deepEqual(fake.metrics.execWidths, Array(16).fill(WAVEFORM_CHUNK_WIDTH));
    assert.equal(fake.metrics.maximumActiveOutputs, 1);
    assert.equal(fake.metrics.paths.size, 0);
    assert.equal(fake.metrics.terminated, 1);
    assert.deepEqual(diagnostics, []);
    assert.equal(fake.metrics.execArgs.some(args => args.join(' ').includes('65536x100')), false);
  } finally {
    if (previous) globalThis.AudioContext = previous; else delete globalThis.AudioContext;
  }
});

for (const failedStage of ['engine-load', 'input-read', 'wasm-write', 'ffmpeg-exec', 'wasm-read', 'peak-conversion', 'cleanup']) {
  test(`safe diagnostic preserves ${failedStage} without private source identity`, async () => {
    const fake = harness({ fail: failedStage === 'input-read' ? null : failedStage, cleanupFailure: failedStage === 'cleanup' });
    const diagnostics = [];
    const file = failedStage === 'input-read' ? longFile(async () => { throw Object.assign(new Error('private body'), { name: 'InputFailure' }); }) : longFile();
    const reader = createWaveformReader(undefined, null, { createEngine: fake.createEngine, onDiagnostic: value => diagnostics.push(value) });
    await assert.rejects(reader.read(file, DURATION, { trackIndex: 2 }), error => {
      assert.equal(error.waveformDiagnostic.stage, failedStage);
      const value = JSON.stringify(error.waveformDiagnostic);
      assert.equal(value.includes(file.name), false);
      assert.equal(value.includes('private'), false);
      assert.equal(error.waveformDiagnostic.trackIndex, 2);
      assert.equal(error.waveformDiagnostic.sourceBytes, 3);
      assert.ok(error.waveformDiagnostic.elapsedMs >= 0);
      return true;
    });
    reader.dispose();
    assert.ok(diagnostics.some(value => value.stage === failedStage));
    assert.equal(fake.metrics.activeEngines, 0);
  });
}

for (const abortedStage of ['engine-load', 'input-read', 'wasm-write', 'ffmpeg-exec', 'wasm-read', 'peak-conversion']) {
  test(`abort during ${abortedStage} terminates lifecycle and publishes no peaks`, async () => {
    const controller = new AbortController();
    const fake = harness({ abort: abortedStage === 'input-read' ? null : abortedStage, controller });
    const file = abortedStage === 'input-read' ? longFile(async () => { controller.abort(); return Uint8Array.of(1).buffer; }) : longFile();
    const diagnostics = [];
    const reader = createWaveformReader(controller.signal, null, { createEngine: fake.createEngine, onDiagnostic: value => diagnostics.push(value) });
    await assert.rejects(reader.read(file, DURATION, { trackIndex: 1 }), error =>
      error.name === 'AbortError' && error.waveformDiagnostic.stage === 'aborted');
    reader.dispose();
    assert.equal(fake.metrics.activeEngines, 0);
    assert.equal(fake.metrics.paths.size, 0);
    assert.ok(diagnostics.some(value => value.stage === 'aborted'));
  });
}

test('retry after fatal failure creates a clean engine and three tracks never overlap workers or outputs', async () => {
  let first = true;
  const base = harness();
  const createEngine = async () => {
    const engine = await base.createEngine();
    const exec = engine.exec.bind(engine);
    engine.exec = async args => {
      if (first) { first = false; throw Object.assign(new Error('first failure'), { name: 'ExecFailure' }); }
      return exec(args);
    };
    return engine;
  };
  const reader = createWaveformReader(undefined, null, { createEngine, onDiagnostic() {} });
  await assert.rejects(reader.read(longFile(), DURATION, { trackIndex: 1 }), error => error.waveformDiagnostic.stage === 'ffmpeg-exec');
  const retried = await reader.read(longFile(), DURATION, { trackIndex: 1 });
  assert.equal(retried.length, WAVEFORM_SAMPLE_COUNT);
  const three = await Promise.all([1, 2, 3].map(trackIndex => reader.read(longFile(), DURATION, { trackIndex })));
  reader.dispose();
  assert.deepEqual(three.map(value => value.length), [WAVEFORM_SAMPLE_COUNT, WAVEFORM_SAMPLE_COUNT, WAVEFORM_SAMPLE_COUNT]);
  assert.equal(base.metrics.maximumActiveEngines, 1);
  assert.equal(base.metrics.maximumActiveOutputs, 1);
  assert.equal(base.metrics.activeEngines, 0);
  assert.equal(base.metrics.paths.size, 0);
  assert.equal(base.metrics.terminated, 5);
});
