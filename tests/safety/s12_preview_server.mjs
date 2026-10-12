#!/usr/bin/env node
import http from "node:http";
import { readFile } from "node:fs/promises";
import { extname, resolve } from "node:path";
import { Readable } from "node:stream";
import { pipeline } from 'node:stream/promises';
import { createApp } from "../../gateway/audio-archive/src/app.mjs";
import { SessionRegistry, createPasswordVerifier, readSession } from "../../gateway/audio-archive/src/auth.mjs";
import { nodeResponseHeaders } from "../../gateway/audio-archive/src/http-adapter.mjs";
import { AudioArchiveDomain } from '../../gateway/audio-archive/src/domain.mjs';
import { createHash } from 'node:crypto';
import { createIngestionPlan, serializeIngestionPlan } from '../../service/frontend/scripts/audio-archive-client.mjs';
import { WAVEFORM_ALGORITHM, WAVEFORM_PEAK_COUNT, WAVEFORM_BODY_BYTES } from '../../gateway/audio-archive/src/waveform.mjs';

import { ZoomArchive } from '../../gateway/audio-archive/src/zoom-archive.mjs';
import { encryptSettings, SETTINGS_PATH, connectionFingerprint } from '../../gateway/audio-archive/src/settings.mjs';
import { A, B, CONNECTION, SyntheticZoom, SyntheticArchiveRepository } from '../../gateway/audio-archive/test/s12-fixtures.mjs';
const port = Number(process.argv[2] || 4173);
const origin = process.argv[3] || `http://localhost:${port}`;
const frontend = resolve(import.meta.dirname, "../../service/frontend");
const secret = "synthetic-preview-session-secret-0001";
const previewCookie = "meser_preview_service_session";
const canonicalCookie = "__Host-meser_service_session";
const verifier = await createPasswordVerifier("local-test-password", Buffer.alloc(16, 11), { N: 16384, r: 8, p: 1 });
const sessions = new SessionRegistry({ maxEntries: 16 });
// Synthetic, process-local archive. It cannot access production storage or credentials.
const repository = new SyntheticArchiveRepository();
const domain = new AudioArchiveDomain(repository, { acceptedPartBytes: 1024 });
const emptyPeaks = Buffer.alloc(WAVEFORM_BODY_BYTES);
const peakDigest = createHash('sha256').update(emptyPeaks).digest('hex');
const waveformService = { get: async (sessionId, blobId) => {
  const source = await domain.waveformSource(sessionId, blobId);
  const bytes = Buffer.concat(source.parts.map(part => repository.assetBytes.get(part.assetId)));
  if (source.mediaType === 'audio/mp4' && [A, B].some(fixture => fixture.equals(bytes)) && createHash('sha256').update(bytes).digest('hex') === source.sha256) {
    return { body: emptyPeaks, algorithm: WAVEFORM_ALGORITHM, peakCount: WAVEFORM_PEAK_COUNT, durationSeconds: 0.12, sourceSha256: source.sha256, resultSha256: peakDigest, cache: 'synthetic' };
  }
  if (createHash('sha256').update(bytes).digest('hex') !== source.sha256 || source.mediaType !== 'audio/wav' ||
      bytes.toString('ascii', 0, 4) !== 'RIFF' || bytes.toString('ascii', 8, 12) !== 'WAVE') throw new Error('Synthetic preview supports verified WAV waveform only');
  const sampleRate = bytes.readUInt32LE(24), channels = bytes.readUInt16LE(22), bits = bytes.readUInt16LE(34);
  const durationSeconds = (bytes.length - 44) / (sampleRate * channels * bits / 8);
  if (!(durationSeconds > 0)) throw new Error('Invalid synthetic WAV duration');
  return { body: emptyPeaks, algorithm: WAVEFORM_ALGORITHM, peakCount: WAVEFORM_PEAK_COUNT,
    durationSeconds, sourceSha256: source.sha256, resultSha256: peakDigest, cache: 'synthetic' };
} };
const config = {
  allowedOrigin: origin, acceptedPartBytes: 1024, sessionSigningSecret: secret,
  sessionLifetimeSeconds: 4 * 60 * 60, activeSessionLimit: 16, sharedPasswordVerifier: verifier
};
const zoom = new SyntheticZoom();
const key = Buffer.alloc(32, 29);
const zoomArchive = new ZoomArchive(domain, { key, zoom });
const seed = { ...CONNECTION, revision: 1, verification: { fingerprint: connectionFingerprint(CONNECTION), checkedAt: new Date().toISOString(), tracks: 'confirmed' } };
await repository.commitJson(await repository.getHead(), { [SETTINGS_PATH]: encryptSettings({ version: 1, revision: 1, lastMutationId: null, activeConnectionId: seed.connectionId, connections: [seed], storage: { softLimitBytes: 50_000_000_000, warningPercent: 80 } }, key) }, 'Seed synthetic encrypted settings');
const faults = { dropNextPartReply: false };
const app = createApp({ config, domain, waveformService, zoomArchive, sessionRegistry: sessions });

const publicPaths = new Set([
  "/login", "/login.html", "/scripts/origin-guard.js", "/scripts/service-login.mjs",
  "/scripts/service-session.mjs", "/scripts/service-session-client.mjs", "/styles/foundation.css",
  "/styles/components.css", "/styles/admin-access.css", "/images/favicon.png", "/images/NALogo.png"
]);
const types = new Map([
  [".html", "text/html; charset=utf-8"], [".css", "text/css; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"], [".mjs", "text/javascript; charset=utf-8"],
  [".png", "image/png"], [".wasm", "application/wasm"], [".txt", "text/plain; charset=utf-8"], [".md", "text/markdown; charset=utf-8"]
]);

function gatewayHeaders(headers) {
  const result = new Headers(headers);
  const cookie = result.get("cookie");
  if (cookie) result.set("cookie", cookie.replace(new RegExp(`(^|;\\s*)${previewCookie}=`), `$1${canonicalCookie}=`));
  return result;
}

function previewHeaders(headers) {
  const result = nodeResponseHeaders(headers);
  const cookies = result["Set-Cookie"];
  if (!cookies) return result;
  const rewrite = cookie => cookie.startsWith(`${canonicalCookie}=`) ?
    cookie.replace(`${canonicalCookie}=`, `${previewCookie}=`).replace(/; Secure/gi, "") : cookie;
  result["Set-Cookie"] = Array.isArray(cookies) ? cookies.map(rewrite) : rewrite(cookies);
  return result;
}

function currentSession(headers) {
  return readSession(new Request(`${origin}/internal/auth-check`, { headers: gatewayHeaders(headers) }), secret, sessions);
}

async function apiRequest(incoming, outgoing) {
  const body = ["GET", "HEAD"].includes(incoming.method || "GET") ? undefined : Readable.toWeb(incoming);
  const controller = new AbortController();
  incoming.once('aborted', () => controller.abort());
  outgoing.once('close', () => { if (!outgoing.writableFinished) controller.abort(); });
  const request = new Request(new URL(incoming.url || "/", origin), {
    signal: controller.signal, method: incoming.method, headers: gatewayHeaders(incoming.headers), body, duplex: body ? "half" : undefined
  });
  const response = await app(request);
  if (faults.dropNextPartReply && request.method === 'PUT' && /\/parts\/\d+$/.test(new URL(request.url).pathname) && response.ok) {
    faults.dropNextPartReply = false;
    await response.body?.cancel();
    // A failed reply after the successful canonical mutation. A socket reset can
    // be transparently retried by native browsers for idempotent PUT requests.
    outgoing.writeHead(503, { 'Content-Type': 'application/json' });
    outgoing.end(JSON.stringify({ error: 'Synthetic lost part response.' })); return;
  }
  // The production cookie remains Secure + __Host-. This preview-only alias is
  // required because WebKit intentionally refuses Secure cookies over local HTTP.
  outgoing.writeHead(response.status, previewHeaders(response.headers));
  if (response.body) await pipeline(Readable.fromWeb(response.body), outgoing); else outgoing.end();
}

const server = http.createServer(async (request, response) => {
  try {
    const url = new URL(request.url || "/", origin);
    if (url.pathname.startsWith("/v1/") || url.pathname === "/healthz") return void await apiRequest(request, response);
    if (url.pathname === '/__test/s12-fault' && request.method === 'POST') {
      faults.dropNextPartReply = true; response.writeHead(204); response.end(); return;
    }
    if (url.pathname === '/__test/s12-reset' && request.method === 'POST') {
      repository.files.clear(); repository.releases.clear(); repository.assetBytes.clear(); repository.head++; repository.nextAsset = 1; repository.nextRelease = 1;
      await repository.commitJson(await repository.getHead(), { [SETTINGS_PATH]: encryptSettings({ version: 1, revision: 1, lastMutationId: null, activeConnectionId: seed.connectionId, connections: [seed], storage: { softLimitBytes: 50_000_000_000, warningPercent: 80 } }, key) }, 'Reset synthetic settings');
      faults.dropNextPartReply = false; zoomArchive.calendarCache.clear(); zoomArchive.usageCache = null;
      response.writeHead(204); response.end(); return;
    }
    if (url.pathname === '/__test/s12-state'  && request.method === 'GET') {
      response.writeHead(200, { 'Content-Type': 'application/json' }); response.end(JSON.stringify({ files: [...repository.files], assets: [...repository.assetBytes].map(([id, bytes]) => [id, createHash('sha256').update(bytes).digest('hex')]), downloads: zoom.downloads })); return;
    }
    if (url.pathname === '/__test/s12-discard-fixture' && request.method === 'POST') {
      const kind = url.searchParams.get('origin');
      if (!['manual', 'zoom_cloud'].includes(kind)) throw new Error('Invalid synthetic origin');
      const files = [A, B].map(bytes => new File([bytes], 'participant.m4a', { type: 'audio/mp4' }));
      let transactionId, plan;
      if (kind === 'zoom_cloud') {
        const calendar = await zoomArchive.calendar('2026-10', true);
        const op = await zoomArchive.reserve({ id: calendar.recordings[0].id, month: '2026-10', settingsRevision: calendar.settingsRevision });
        plan = await createIngestionPlan(files, 1024, { idempotencyKey: op.idempotencyKey });
        await zoomArchive.bind(op.id, { plan: serializeIngestionPlan(plan) }); transactionId = op.transactionId;
      } else {
        const idempotencyKey = crypto.randomUUID();
        plan = await createIngestionPlan(files, 1024, { idempotencyKey });
        const started = await domain.beginIngestion({ schemaVersion: 1, idempotencyKey, title: 'Synthetic manual discard', recordedAt: null, origin: kind, supersedesSessionId: null, plan: serializeIngestionPlan(plan) });
        transactionId = started.transactionId;
      }
      for (const track of plan.tracks) for (const part of track.parts) await domain.uploadPart(transactionId, track.blobId, part.partNumber, Buffer.from(await part.blob.arrayBuffer()), part.sha256, crypto.randomUUID());
      const remove = repository.deleteRelease.bind(repository);
      repository.deleteRelease = async id => { await remove(id); throw new Error('Synthetic lost successful DELETE reply'); };
      try { await domain.recoverIncomplete(transactionId, 'discard'); }
      catch (error) { if (error.message !== 'Synthetic lost successful DELETE reply') throw error; }
      finally { repository.deleteRelease = remove; }
      response.writeHead(200, { 'Content-Type': 'application/json' }); response.end(JSON.stringify({ transactionId })); return;
    }
    if (url.pathname.startsWith("/internal/")) { response.writeHead(404); response.end(); return; }
    if (url.pathname === "/__test/expire" && request.method === "POST") {
      sessions.sessions.clear(); response.writeHead(204); response.end(); return;
    }
    if (!publicPaths.has(url.pathname) && !currentSession(request.headers)) {
      response.writeHead(303, { Location: `/login?return=${encodeURIComponent(url.pathname + url.search)}`, "Cache-Control": "no-store" });
      response.end(); return;
    }
    let pathname = url.pathname;
    if (pathname === "/") pathname = "/index.html";
    if (pathname === "/login") pathname = "/login.html";
    const file = resolve(frontend, `.${pathname}`);
    if (!file.startsWith(`${frontend}/`)) { response.writeHead(404); response.end(); return; }
    const bytes = await readFile(file);
    response.writeHead(200, {
      "Content-Type": types.get(extname(file)) || "application/octet-stream",
      "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"
    });
    response.end(bytes);
  } catch (error) {
    if (response.headersSent) { response.destroy(); return; }
    response.writeHead(error?.code === "ENOENT" ? 404 : 500, { "Content-Type": "text/plain; charset=utf-8" });
    response.end(error?.code === "ENOENT" ? "Not found" : "Preview error");
  }
});

server.listen(port, "127.0.0.1", () => console.log(`S12 synthetic in-memory preview listening at ${origin}`));
