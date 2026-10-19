// Actual host FFmpeg measurement; never claims the pinned production toolchain.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { pathToFileURL } from 'node:url';
const root = process.argv[2] || '.', output = process.argv[3] || '/private/tmp/s13-checks/waveform.json';
const { WaveformService } = await import(pathToFileURL(resolve(root, 'gateway/audio-archive/src/waveform.mjs')));
const ffmpegPath = '/opt/homebrew/bin/ffmpeg', ffprobePath = '/opt/homebrew/bin/ffprobe';
const directory = await mkdtemp(join(tmpdir(), 's13-native-waveform-'));
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const sources = [], assets = new Map(); let assetId = 1;
try {
  for (let index = 1; index <= 3; index++) {
    const path = join(directory, `track-${index}.m4a`);
    execFileSync(ffmpegPath, ['-loglevel', 'error', '-nostdin', '-i', resolve('tests/safety/fixtures/s10a-long-aac-lc-3747s.m4a'),
      '-map', '0:a', '-c:a', 'copy', '-metadata', `comment=S13 synthetic track ${index}`, path]);
    const bytes = await readFile(path), parts = [];
    for (let offset = 0, partNumber = 1; offset < bytes.length; offset += 256 * 1024, partNumber++) {
      const data = bytes.subarray(offset, Math.min(bytes.length, offset + 256 * 1024));
      assets.set(assetId, data); parts.push({ partNumber, assetId: assetId++, sizeBytes: data.length, sha256: hash(data) });
    }
    sources.push({ sessionId: '11111111-1111-4111-8111-111111111111', blobId: `44444444-4444-4444-8444-${String(index).padStart(12, '0')}`,
      sizeBytes: bytes.length, sha256: hash(bytes), mediaType: 'audio/mp4', parts });
  }
  const rows = [];
  for (let repeat = 0; repeat < 5; repeat++) {
    const cacheDir = join(directory, `cache-${repeat}`); let calls = 0, bytes = 0, rss = 0;
    const service = new WaveformService({ cacheDir, ffmpegPath, ffprobePath,
      resolveSource: async (_sessionId, blobId) => sources.find(s => s.blobId === blobId),
      openPart: async id => { calls++; bytes += assets.get(id).length; rss = Math.max(rss, process.memoryUsage().rss); return new Response(assets.get(id), { headers: { 'Content-Length': String(assets.get(id).length) } }); } });
    await service.initialize();
    try {
      const coldStart = performance.now(), cold = [];
      for (const source of sources) cold.push(await service.get(source.sessionId, source.blobId));
      const coldMs = performance.now() - coldStart, coldCalls = calls, coldBytes = bytes, warmStart = performance.now(), warm = [];
      for (const source of sources) warm.push(await service.get(source.sessionId, source.blobId));
      const warmMs = performance.now() - warmStart;
      assert.ok(cold.every(s => s.cache === 'miss')); assert.ok(warm.every(s => s.cache === 'hit'));
      assert.equal(calls, coldCalls); assert.equal(bytes, coldBytes);
      assert.equal(service.active, 0); assert.equal(service.queue.length, 0); assert.equal(service.inFlight.size, 0);
      assert.ok((await readdir(cacheDir)).every(name => !name.endsWith('.source') && !name.endsWith('.tmp')));
      rows.push({ repeat, coldMs, warmMs, coldCalls, coldSourceBytes: coldBytes, warmSourceCalls: calls - coldCalls,
        warmSourceBytes: bytes - coldBytes, gatewayRssSample: rss, durations: cold.map(s => s.durationSeconds), activeAtEnd: service.active, tempFilesAtEnd: 0 });
      console.log(`repeat ${repeat}: cold ${coldMs.toFixed(0)} ms; hit ${warmMs.toFixed(0)} ms; bytes ${coldBytes}`);
    } finally { await service.close(); }
  }
  await writeFile(output, JSON.stringify({ kind: 'local-actual-native-waveform-not-pinned-production',
    ffmpeg: execFileSync(ffmpegPath, ['-version'], { encoding: 'utf8' }).split('\n')[0],
    ffmpegSha256: hash(await readFile(ffmpegPath)), ffprobeSha256: hash(await readFile(ffprobePath)),
    fixture: 'Three stream-copy metadata variants of existing 3747s AAC-LC fixture; differing SHA identities, unchanged AAC payload; generated only in temporary directory',
    sources: sources.map(({ parts, ...source }) => source), rows, pinnedContainer: 'NOT_RUN; Docker daemon unavailable' }, null, 2) + '\n');
} finally { await rm(directory, { recursive: true, force: true }); }
