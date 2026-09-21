import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { WaveformService, WAVEFORM_PEAK_COUNT } from "../../gateway/audio-archive/src/waveform.mjs";
import { verifyFfmpegToolchain } from "../../gateway/audio-archive/tools/verify-ffmpeg-toolchain.mjs";

const directory = resolve(process.argv[2] || "");
if (!process.argv[2]) throw new Error("usage: node s10a_realistic_waveform_load.mjs FIXTURE_DIR");
const { ffmpeg: ffmpegPath, ffprobe: ffprobePath } = await verifyFfmpegToolchain();
const sha = bytes => createHash("sha256").update(bytes).digest("hex");
const ids = [
  ["11111111-1111-4111-8111-111111111111", "44444444-4444-4444-8444-444444444441"],
  ["11111111-1111-4111-8111-111111111111", "44444444-4444-4444-8444-444444444442"],
  ["11111111-1111-4111-8111-111111111111", "44444444-4444-4444-8444-444444444443"]
];
const assets = new Map(); const sources = new Map(); let assetId = 100; let totalBytes = 0;
for (const [index, [sessionId, blobId]] of ids.entries()) {
  const bytes = await readFile(join(directory, `track-${index + 1}.m4a`)); totalBytes += bytes.length;
  assert.ok(bytes.includes(Buffer.from("ftyp"))); assert.ok(bytes.includes(Buffer.from("mp4a")));
  const parts = [];
  for (let offset = 0, number = 1; offset < bytes.length; offset += 8 * 1024 * 1024, number++) {
    const partBytes = bytes.subarray(offset, Math.min(bytes.length, offset + 8 * 1024 * 1024));
    const id = assetId++; assets.set(id, Buffer.from(partBytes));
    parts.push({ partNumber: number, assetId: id, sizeBytes: partBytes.length, sha256: sha(partBytes) });
  }
  sources.set(blobId, { sessionId, blobId, sizeBytes: bytes.length, sha256: sha(bytes), mediaType: "audio/mp4", parts });
}
assert.ok(totalBytes >= 40 * 1024 * 1024 && totalBytes <= 60 * 1024 * 1024, `fixture total ${totalBytes} is not approximately 49 MB`);

const cacheDir = await mkdtemp(join(tmpdir(), "meser-realistic-waveform-"));
const makeService = async ({ failFirstOpen = false } = {}) => {
  let pendingFailure = failFirstOpen;
  const service = new WaveformService({ cacheDir, ffmpegPath, ffprobePath,
    resolveSource: async (_sessionId, blobId) => sources.get(blobId),
    openPart: async asset => {
      if (pendingFailure) { pendingFailure = false; throw new Error("synthetic read failure"); }
      return new Response(assets.get(asset), { headers: { "Content-Length": String(assets.get(asset).length), "Content-Type": "application/octet-stream" } });
    } });
  await service.initialize(); return service;
};
let service = await makeService(); const cold = [];
try {
  for (const [sessionId, blobId] of ids) cold.push(await service.get(sessionId, blobId));
  assert.deepEqual(cold.map(item => item.peakCount), [WAVEFORM_PEAK_COUNT, WAVEFORM_PEAK_COUNT, WAVEFORM_PEAK_COUNT]);
  assert.deepEqual(cold.map(item => item.cache), ["miss", "miss", "miss"]);
  const warm = [];
  for (const [sessionId, blobId] of ids) warm.push(await service.get(sessionId, blobId));
  assert.deepEqual(warm.map(item => item.cache), ["hit", "hit", "hit"]);
  await service.close(); service = await makeService();
  const afterRestart = await service.get(...ids[0]);
  assert.equal(afterRestart.cache, "hit");

  const cacheName = source => `meser-peaks-f32le-v1-${source.sha256}-${WAVEFORM_PEAK_COUNT}.waveform`;
  await writeFile(join(cacheDir, cacheName(sources.get(ids[0][1]))), "corrupt");
  assert.equal((await service.get(...ids[0])).cache, "miss");

  await rm(join(cacheDir, cacheName(sources.get(ids[1][1]))), { force: true });
  const controller = new AbortController();
  const aborted = service.get(...ids[1], controller.signal); controller.abort();
  await assert.rejects(aborted, error => error.name === "AbortError");
  await service.close(); service = await makeService();
  assert.equal((await service.get(...ids[1])).cache, "miss");

  await rm(join(cacheDir, cacheName(sources.get(ids[2][1]))), { force: true });
  await service.close(); service = await makeService({ failFirstOpen: true });
  await assert.rejects(service.get(...ids[2]), error => error.stage === "source-reconstruction");
  assert.equal((await service.get(...ids[2])).cache, "miss");
  assert.equal((await readdir(cacheDir)).some(name => name.endsWith(".source") || name.endsWith(".tmp")), false);
  assert.ok((await stat(cacheDir)).isDirectory());
  console.log(`REALISTIC_FIXTURE_TRACKS=3 TOTAL_BYTES=${totalBytes} COLD_CACHE=PASS WARM_CACHE=PASS RESTART_CACHE=PASS CORRUPTION_REGENERATION=PASS ABORT_RETRY=PASS FAILURE_RETRY=PASS ARCHIVE_MUTATIONS=0`);
  for (const [index, item] of cold.entries()) console.log(`TRACK_${index + 1}_BYTES=${sources.get(ids[index][1]).sizeBytes} DURATION=${item.durationSeconds} PEAKS=${item.peakCount} RESULT_SHA256=${item.resultSha256}`);
} finally { await service.close(); await rm(cacheDir, { recursive: true, force: true }); }
