import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { access } from "node:fs/promises";
import {
  WAVEFORM_BODY_BYTES, WAVEFORM_PEAK_COUNT, WaveformService
} from "../src/waveform.mjs";

const sha = value => createHash("sha256").update(value).digest("hex");
const SESSION = "11111111-1111-4111-8111-111111111111";
const BLOB = "44444444-4444-4444-8444-444444444444";

function fixture() {
  const parts = [Buffer.from("ftypM4A first"), Buffer.from(" second AAC-LC")];
  const combined = Buffer.concat(parts);
  const source = Object.freeze({ sessionId: SESSION, blobId: BLOB, sizeBytes: combined.length, sha256: sha(combined), mediaType: "audio/mp4",
    parts: Object.freeze(parts.map((bytes, index) => Object.freeze({ partNumber: index + 1, assetId: index + 1, sizeBytes: bytes.length, sha256: sha(bytes) }))) });
  return { parts, source };
}

async function withService(run, overrides = {}) {
  const directory = await mkdtemp(join(tmpdir(), "meser-waveform-test-"));
  const { parts, source } = fixture(); let generations = 0;
  const service = new WaveformService({
    cacheDir: directory,
    resolveSource: async (sessionId, blobId) => { assert.equal(sessionId, SESSION); assert.equal(blobId, BLOB); return source; },
    openPart: async assetId => new Response(parts[assetId - 1], { status: 200, headers: { "Content-Length": String(parts[assetId - 1].length) } }),
    generate: async ({ path, signal }) => {
      generations++; assert.deepEqual(await readFile(path), Buffer.concat(parts));
      if (overrides.pause) await overrides.pause(signal);
      const peaks = new Float32Array(WAVEFORM_PEAK_COUNT); peaks[0] = 1; peaks[peaks.length - 1] = .5;
      return { durationSeconds: 3747.648, body: Buffer.from(peaks.buffer) };
    }
  });
  await service.initialize();
  try { await run({ service, directory, source, generations: () => generations }); }
  finally { await service.close(); await rm(directory, { recursive: true, force: true }); }
}

test("cold generation streams exact parts, publishes a fixed f32le contract and warm cache is verified", async () => {
  await withService(async ({ service, directory, source, generations }) => {
    const cold = await service.get(SESSION, BLOB);
    assert.equal(cold.body.byteLength, WAVEFORM_BODY_BYTES);
    assert.equal(cold.peakCount, WAVEFORM_PEAK_COUNT);
    assert.equal(cold.format, "float32"); assert.equal(cold.endianness, "little");
    assert.equal(cold.sourceSha256, source.sha256); assert.equal(cold.cache, "miss");
    assert.equal(generations(), 1);
    const warm = await service.get(SESSION, BLOB);
    assert.equal(warm.cache, "hit"); assert.equal(warm.resultSha256, cold.resultSha256); assert.equal(generations(), 1);
    assert.equal((await readdir(directory)).some(name => name.endsWith(".source") || name.endsWith(".tmp")), false);
  });
});

test("corrupt cache is deleted and deterministically regenerated", async () => {
  await withService(async ({ service, directory, generations }) => {
    await service.get(SESSION, BLOB);
    const cache = (await readdir(directory)).find(name => name.endsWith(".waveform"));
    await writeFile(join(directory, cache), "corrupt");
    const regenerated = await service.get(SESSION, BLOB);
    assert.equal(regenerated.cache, "miss"); assert.equal(generations(), 2);
  });
});

test("initialization removes stale temporary files left by an interrupted gateway process", async () => {
  const directory = await mkdtemp(join(tmpdir(), "meser-waveform-startup-"));
  const { parts, source } = fixture();
  await writeFile(join(directory, ".interrupted.source"), "stale");
  await writeFile(join(directory, ".interrupted.tmp"), "stale");
  const service = new WaveformService({ cacheDir: directory, resolveSource: async () => source,
    openPart: async assetId => new Response(parts[assetId - 1]),
    generate: async () => ({ durationSeconds: 1, body: Buffer.alloc(WAVEFORM_BODY_BYTES) }) });
  await service.initialize();
  try { assert.deepEqual(await readdir(directory), []); }
  finally { await service.close(); await rm(directory, { recursive: true, force: true }); }
});

test("duplicate requests coalesce and one disconnect does not cancel a remaining subscriber", async () => {
  let release;
  await withService(async ({ service, generations }) => {
    const firstController = new AbortController();
    const first = service.get(SESSION, BLOB, firstController.signal);
    const second = service.get(SESSION, BLOB);
    while (!release) await new Promise(resolve => setTimeout(resolve, 1));
    firstController.abort(); release();
    await assert.rejects(first, error => error.name === "AbortError");
    assert.equal((await second).peakCount, WAVEFORM_PEAK_COUNT);
    assert.equal(generations(), 1);
  }, { pause: signal => new Promise((resolve, reject) => {
    if (signal.aborted) return reject(Object.assign(new Error("cancelled"), { name: "AbortError" }));
    release = resolve; signal.addEventListener("abort", () => reject(Object.assign(new Error("cancelled"), { name: "AbortError" })), { once: true });
  }) });
});

test("last subscriber cancellation removes temporary source and publishes no cache", async () => {
  await withService(async ({ service, directory }) => {
    const controller = new AbortController();
    const pending = service.get(SESSION, BLOB, controller.signal);
    await new Promise(resolve => setTimeout(resolve, 5));
    controller.abort();
    await assert.rejects(pending, error => error.name === "AbortError");
    await new Promise(resolve => setTimeout(resolve, 20));
    assert.equal((await readdir(directory)).some(name => name.endsWith(".source") || name.endsWith(".waveform")), false);
  }, { pause: signal => new Promise((_resolve, reject) => {
    if (signal.aborted) return reject(Object.assign(new Error("cancelled"), { name: "AbortError" }));
    signal.addEventListener("abort", () => reject(Object.assign(new Error("cancelled"), { name: "AbortError" })), { once: true });
  }) });
});

test("generation failure and abort both permit a clean retry without stale cache", async () => {
  const directory = await mkdtemp(join(tmpdir(), "meser-waveform-retry-"));
  const { parts, source } = fixture(); let attempt = 0;
  const service = new WaveformService({ cacheDir: directory, resolveSource: async () => source,
    openPart: async assetId => new Response(parts[assetId - 1], { headers: { "Content-Length": String(parts[assetId - 1].length) } }),
    generate: async ({ signal }) => {
      attempt++;
      if (attempt === 1) throw new Error("synthetic native failure");
      if (attempt === 2) await new Promise((_resolve, reject) => {
        if (signal.aborted) return reject(Object.assign(new Error("cancelled"), { name: "AbortError" }));
        signal.addEventListener("abort", () => reject(Object.assign(new Error("cancelled"), { name: "AbortError" })), { once: true });
      });
      return { durationSeconds: 3747.648, body: Buffer.alloc(WAVEFORM_BODY_BYTES) };
    } });
  await service.initialize();
  try {
    await assert.rejects(service.get(SESSION, BLOB), error => error.name === "WaveformError" && error.stage === "exec");
    const controller = new AbortController(); const aborted = service.get(SESSION, BLOB, controller.signal);
    await new Promise(resolve => setTimeout(resolve, 5)); controller.abort();
    await assert.rejects(aborted, error => error.name === "AbortError");
    await new Promise(resolve => setTimeout(resolve, 10));
    const retried = await service.get(SESSION, BLOB);
    assert.equal(retried.cache, "miss"); assert.equal(attempt, 3);
    assert.equal((await readdir(directory)).filter(name => name.endsWith(".waveform")).length, 1);
    assert.equal((await readdir(directory)).some(name => name.endsWith(".source") || name.endsWith(".tmp")), false);
  } finally { await service.close(); await rm(directory, { recursive: true, force: true }); }
});

test("cache limit evicts deterministically and never retains more than the configured bound", async () => {
  const directory = await mkdtemp(join(tmpdir(), "meser-waveform-evict-"));
  const blobs = [BLOB, "44444444-4444-4444-8444-444444444445"];
  const bytes = blobs.map((_, index) => Buffer.from(`ftypM4A cache source ${index}`));
  const sources = new Map(blobs.map((blobId, index) => [blobId, { sessionId: SESSION, blobId, sizeBytes: bytes[index].length,
    sha256: sha(bytes[index]), mediaType: "audio/mp4", parts: [{ partNumber: 1, assetId: index + 1, sizeBytes: bytes[index].length, sha256: sha(bytes[index]) }] }]));
  const service = new WaveformService({ cacheDir: directory, cacheMaxBytes: 300_000,
    resolveSource: async (_sessionId, blobId) => sources.get(blobId),
    openPart: async assetId => new Response(bytes[assetId - 1], { headers: { "Content-Length": String(bytes[assetId - 1].length) } }),
    generate: async () => ({ durationSeconds: 61, body: Buffer.alloc(WAVEFORM_BODY_BYTES) }) });
  await service.initialize();
  try {
    await service.get(SESSION, blobs[0]); await new Promise(resolve => setTimeout(resolve, 2)); await service.get(SESSION, blobs[1]);
    const entries = (await readdir(directory)).filter(name => name.endsWith(".waveform"));
    assert.equal(entries.length, 1); assert.match(entries[0], new RegExp(sources.get(blobs[1]).sha256));
  } finally { await service.close(); await rm(directory, { recursive: true, force: true }); }
});

test("source-size and duration limits fail closed before cache publication", async () => {
  const directory = await mkdtemp(join(tmpdir(), "meser-waveform-limits-"));
  const { parts, source } = fixture(); let oversized = true;
  const service = new WaveformService({ cacheDir: directory,
    resolveSource: async () => oversized ? { ...source, sizeBytes: 500 * 1024 * 1024 + 1 } : source,
    openPart: async assetId => new Response(parts[assetId - 1], { headers: { "Content-Length": String(parts[assetId - 1].length) } }),
    generate: async () => ({ durationSeconds: 8 * 60 * 60 + 1, body: Buffer.alloc(WAVEFORM_BODY_BYTES) }) });
  await service.initialize();
  try {
    await assert.rejects(service.get(SESSION, BLOB), error => error.status === 413 && error.stage === "source-reconstruction");
    oversized = false;
    await assert.rejects(service.get(SESSION, BLOB), error => error.stage === "read");
    assert.equal((await readdir(directory)).some(name => name.endsWith(".waveform")), false);
  } finally { await service.close(); await rm(directory, { recursive: true, force: true }); }
});

test("pinned native contract decodes the exact 3747-second AAC-LC/M4A fixture", { timeout: 120_000 }, async t => {
  const ffmpeg = process.env.MESER_TEST_FFMPEG || "/opt/homebrew/bin/ffmpeg";
  const ffprobe = process.env.MESER_TEST_FFPROBE || "/opt/homebrew/bin/ffprobe";
  try { await access(ffmpeg); await access(ffprobe); } catch { t.skip("native ffmpeg is unavailable"); return; }
  const bytes = await readFile(new URL("../../../tests/safety/fixtures/s10a-long-aac-lc-3747s.m4a", import.meta.url));
  const directory = await mkdtemp(join(tmpdir(), "meser-waveform-native-"));
  const source = { sessionId: SESSION, blobId: BLOB, sizeBytes: bytes.length, sha256: sha(bytes), mediaType: "audio/mp4",
    parts: [{ partNumber: 1, assetId: 1, sizeBytes: bytes.length, sha256: sha(bytes) }] };
  const service = new WaveformService({ cacheDir: directory, ffmpegPath: ffmpeg, ffprobePath: ffprobe,
    resolveSource: async () => source, openPart: async () => new Response(bytes, { headers: { "Content-Length": String(bytes.length) } }) });
  await service.initialize();
  try {
    const result = await service.get(SESSION, BLOB);
    assert.equal(result.peakCount, WAVEFORM_PEAK_COUNT); assert.equal(result.body.byteLength, WAVEFORM_BODY_BYTES);
    assert.ok(Math.abs(result.durationSeconds - 3747.648) < .01); assert.equal(result.cache, "miss");
    assert.equal((await service.get(SESSION, BLOB)).cache, "hit");
  } finally { await service.close(); await rm(directory, { recursive: true, force: true }); }
});
