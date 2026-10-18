// Disposable near-limit WAV source server. Generated buffers only; no archive,
// credentials, disk audio, decoding, production network or write endpoints.
import http from 'node:http';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { sourceFixture } from '../../gateway/audio-archive/test/s13-fixtures.mjs';
const port = Number(process.argv[2] || 4191), MiB = 1024 * 1024;
const { session } = await sourceFixture();
const descriptors = new Map(), byUrl = new Map(); let assetId = 1;
const partBytes = 16 * MiB, trackBytes = 165 * MiB;
function bytesFor(d) {
  const bytes = Buffer.alloc(d.size, d.fill);
  if (d.first) {
    bytes.write('RIFF'); bytes.writeUInt32LE(trackBytes - 8, 4); bytes.write('WAVEfmt ', 8);
    bytes.writeUInt32LE(16, 16); bytes.writeUInt16LE(1, 20); bytes.writeUInt16LE(1, 22);
    bytes.writeUInt32LE(8000, 24); bytes.writeUInt32LE(16000, 28); bytes.writeUInt16LE(2, 32); bytes.writeUInt16LE(16, 34);
    bytes.write('data', 36); bytes.writeUInt32LE(trackBytes - 44, 40);
  }
  return bytes;
}
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
for (const [index, track] of session.sourceTracks.entries()) {
  track.sizeBytes = trackBytes; track.parts = []; const whole = createHash('sha256');
  for (let offset = 0, partNumber = 1; offset < trackBytes; offset += partBytes, partNumber++) {
    const descriptor = { size: Math.min(partBytes, trackBytes - offset), fill: (index * 31 + partNumber) % 255, first: partNumber === 1 };
    const bytes = bytesFor(descriptor); whole.update(bytes);
    const assetName = `blob-${track.blobId}-part-${String(partNumber).padStart(4, '0')}.bin`;
    const downloadUrl = `https://github.com/meser-recovery/audio-archive/releases/download/audio-session-${session.id}/${assetName}`;
    track.parts.push({ partNumber, sizeBytes: bytes.length, sha256: hash(bytes), assetName, assetId, downloadUrl });
    descriptors.set(assetId, descriptor); byUrl.set(downloadUrl, `/part/${assetId++}`);
  }
  track.sha256 = whole.digest('hex');
}
const stats = { active: 0, maxActive: 0, requests: 0, attemptedSourceBytes: 0, rssSamplePeak: 0 };
const server = http.createServer(async (request, response) => {
  const path = new URL(request.url, `http://127.0.0.1:${port}`).pathname;
  response.setHeader('Cache-Control', 'no-store');
  if (path === '/client.mjs') { response.setHeader('Content-Type', 'text/javascript'); response.end(await readFile(new URL('../../service/frontend/scripts/audio-archive-client.mjs', import.meta.url))); return; }
  if (path === '/fixture') { response.setHeader('Content-Type', 'application/json'); response.end(JSON.stringify({ session, parts: Object.fromEntries(byUrl) })); return; }
  if (path === '/stats') { response.setHeader('Content-Type', 'application/json'); response.end(JSON.stringify(stats)); return; }
  if (/^\/part\/[0-9]+$/.test(path)) {
    const d = descriptors.get(Number(path.split('/').at(-1)));
    if (!d) { response.writeHead(404); response.end(); return; }
    stats.active++; stats.requests++; stats.maxActive = Math.max(stats.maxActive, stats.active);
    response.once('close', () => { stats.active--; });
    const bytes = bytesFor(d); stats.attemptedSourceBytes += bytes.length;
    stats.rssSamplePeak = Math.max(stats.rssSamplePeak, process.memoryUsage().rss);
    response.writeHead(200, { 'Content-Type': 'application/octet-stream', 'Content-Length': String(bytes.length) }); response.end(bytes); return;
  }
  if (path !== '/') { response.writeHead(404); response.end(); return; }
  response.setHeader('Content-Type', 'text/html');
  response.end(`<!doctype html><html><title>S13 disposable 495 MiB resource fixture</title><body><p>Generated WAV bytes only. No production access.</p><script type="module">
import {prepareRemoteSourceBatch,Sha256} from '/client.mjs';
window.runResource = async () => {
  window.resourceStage='fixture';
  const fixture = await (await fetch('/fixture')).json(), session = fixture.session;
  let manifestReads=0, activePeak=0, slotsPeak=0, bytesPeak=0, heapPeak=null, progressLast=0, transfers=0;
  const memory=()=>{if(performance.memory)heapPeak=Math.max(heapPeak||0,performance.memory.usedJSHeapSize)};
  const resources=r=>{activePeak=Math.max(activePeak,r.activeTransfers);slotsPeak=Math.max(slotsPeak,r.reservedParts);bytesPeak=Math.max(bytesPeak,r.reservedPartBytes);memory()};
  const gateway={authGeneration:0,getSession:async()=>{manifestReads++;return structuredClone(session)},sourcePartFetch:()=>async(url,options)=>{if(!fixture.parts[url])throw Error('Unexpected source URL');transfers++;return fetch(fixture.parts[url],options)}};
  const controller=new AbortController(); let abortAt;
  window.resourceStage='cancel';const cancelled=prepareRemoteSourceBatch({gateway,sessionId:session.id,signal:controller.signal,onResources:resources});
  setTimeout(()=>{abortAt=performance.now();controller.abort()},5);
  try{await cancelled;throw Error('Cancelled batch became ready')}catch(e){if(e.name!=='AbortError')throw e}
  const cancellationMs=performance.now()-abortAt;
  manifestReads=0;transfers=0;
  const start=performance.now();
  window.resourceStage='cold-transfer';const batch=await prepareRemoteSourceBatch({gateway,sessionId:session.id,onResources:resources,onProgress:p=>{if(p.verifiedBytes<progressLast)throw Error('Non-monotonic progress');progressLast=p.verifiedBytes}});
  const verifiedMs=performance.now()-start;
  if(batch.files.length!==3||batch.files.reduce((n,f)=>n+f.size,0)!==495*1024*1024)throw Error('Incomplete near-limit batch');
  window.resourceStage='independent-File-readback';for(let i=0;i<batch.files.length;i++){
    const hasher=new Sha256();
    // Match the existing browser ingestion/waveform File.slice read contract.
    // Read every byte, bounded to 4 MiB, rather than adding a File.stream API
    // dependency to the resource test (not used by the product).
    for(let offset=0;offset<batch.files[i].size;offset+=4*1024*1024){
      const chunk=await batch.files[i].slice(offset,Math.min(batch.files[i].size,offset+4*1024*1024)).arrayBuffer();
      hasher.update(new Uint8Array(chunk));memory();
    }
    if(hasher.digestHex()!==session.sourceTracks[i].sha256)throw Error('File differs from Node canonical bytes');
  }
  window.resourceStage='warm-reuse';const before=transfers,warmStart=performance.now();
  const warm=await prepareRemoteSourceBatch({gateway,sessionId:session.id,reuseBatch:batch});
  if(!warm.reused||warm.files!==batch.files||transfers!==before)throw Error('Unexpected warm transfer');
  if(activePeak>2||slotsPeak>2||bytesPeak>32*1024*1024)throw Error('Part budget exceeded');
  memory();return {totalBytes:495*1024*1024,tracks:3,partBytes:16*1024*1024,verifiedMs,cancellationMs,warmMs:performance.now()-warmStart,
    coldPartRequests:before,warmPartRequests:transfers-before,manifestReads,activePeak,slotsPeak,reservedPartBytesPeak:bytesPeak,
    browserHeapSamplePeak:heapPeak,heapMetric:heapPeak===null?'NOT_AVAILABLE':'performance.memory.usedJSHeapSize (excludes Blob/native memory)',
    byteIdenticalFiles:true,sourceHashes:session.sourceTracks.map(t=>t.sha256),editorDecode:'NOT_RUN; separate source transfer/hash resource test'};
};</script></body></html>`);
});
server.listen(port, '127.0.0.1', () => console.log(`S13 disposable resource fixture http://127.0.0.1:${port}`));
