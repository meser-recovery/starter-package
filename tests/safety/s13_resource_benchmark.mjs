// Separate near-limit process; synthetic bytes, no files/audio persisted.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { resolve } from 'node:path';
import { sourceFixture } from '../../gateway/audio-archive/test/s13-fixtures.mjs';
const root = process.argv[2] || '.', output = process.argv[3] || '/private/tmp/s13-checks/resource.json';
const { reconstructSessionTracks, assetName } = await import(pathToFileURL(resolve(root, 'service/frontend/scripts/audio-archive-client.mjs')));
const h = await sourceFixture(), session = structuredClone(h.session), MiB = 1024 * 1024;
const size = 165 * MiB, acceptedPartBytes = 16 * MiB, descriptor = new Map();
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
for (const [i, track] of session.sourceTracks.entries()) {
  const whole = createHash('sha256'); track.parts = []; track.sizeBytes = size;
  for (let offset = 0, partNumber = 1; offset < size; offset += acceptedPartBytes, partNumber++) {
    const count = Math.min(acceptedPartBytes, size - offset), fill = (i * 31 + partNumber) % 255;
    const bytes = Buffer.alloc(count, fill), name = assetName(track.blobId, partNumber);
    whole.update(bytes);
    const downloadUrl = `https://github.com/meser-recovery/audio-archive/releases/download/audio-session-${session.id}/${name}`;
    track.parts.push({ partNumber, sizeBytes: count, sha256: sha(bytes), assetName: name, assetId: i * 100 + partNumber, downloadUrl });
    descriptor.set(downloadUrl, { count, fill });
  }
  track.sha256 = whole.digest('hex');
}
let active = 0, maxActive = 0, peakRss = 0, maxReservedBytes = 0, maxSlots = 0, calls = 0, bytes = 0;
const sample = () => { peakRss = Math.max(peakRss, process.memoryUsage().rss); };
const started = performance.now();
const files = await reconstructSessionTracks(session, async url => {
  active++; maxActive = Math.max(maxActive, active); calls++; sample();
  const d = descriptor.get(url); assert.ok(d);
  await new Promise(resolve => setTimeout(resolve, 5));
  const result = new Response(Buffer.alloc(d.count, d.fill), { headers: { 'Content-Length': String(d.count) } });
  active--; bytes += d.count; return result;
}, { onResources: r => { maxReservedBytes = Math.max(maxReservedBytes, r.reservedPartBytes); maxSlots = Math.max(maxSlots, r.reservedParts); sample(); } });
const verifiedMs = performance.now() - started; sample();
assert.equal(files.length, 3); assert.equal(bytes, 495 * MiB);
for (const [index, file] of files.entries()) {
  const whole = createHash('sha256'); for await (const chunk of file.stream()) whole.update(chunk);
  assert.equal(whole.digest('hex'), session.sourceTracks[index].sha256);
}
sample();
assert.ok(maxActive <= 2); assert.ok(maxReservedBytes <= 2 * acceptedPartBytes); assert.ok(maxSlots <= 2);
const result = { kind: 'synthetic-near-limit-Node-resource-test', totalBytes: bytes, tracks: 3, acceptedPartBytes, calls,
  maxActiveTransfers: maxActive, maxReservedPartBytes: maxReservedBytes, maxSlots, peakRss, verifiedMs,
  identity: session.sourceTracks.map(t => ({ sizeBytes: t.sizeBytes, sha256: t.sha256 })),
  note: '495 MiB / 500 MiB; Node RSS includes runtime/copies; no browser RSS or browser crash claim. Baseline does not expose reorder-slot instrumentation.' };
await writeFile(output, JSON.stringify(result, null, 2) + '\n'); console.log(JSON.stringify(result));
