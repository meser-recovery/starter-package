#!/usr/bin/env node
import http from "node:http";
import { readFile } from "node:fs/promises";
import { extname, resolve } from "node:path";
import { Readable } from "node:stream";
import { createApp } from "../../gateway/audio-archive/src/app.mjs";
import { SessionRegistry, createPasswordVerifier, readSession } from "../../gateway/audio-archive/src/auth.mjs";
import { nodeResponseHeaders } from "../../gateway/audio-archive/src/http-adapter.mjs";
import { AudioArchiveDomain } from '../../gateway/audio-archive/src/domain.mjs';
import { MemoryRepository } from '../../gateway/audio-archive/test/helpers.mjs';
import { createHash } from 'node:crypto';
import { WAVEFORM_ALGORITHM, WAVEFORM_PEAK_COUNT, WAVEFORM_BODY_BYTES } from '../../gateway/audio-archive/src/waveform.mjs';

const port = Number(process.argv[2] || 4173);
const origin = process.argv[3] || `http://localhost:${port}`;
const acceptedPartBytes = Number(process.env.S11_PREVIEW_PART_BYTES || 1024);
if (!Number.isInteger(acceptedPartBytes) || acceptedPartBytes < 1024 || acceptedPartBytes > 1024 * 1024) throw new Error("Invalid preview part size");
const frontend = resolve(import.meta.dirname, "../../service/frontend");
const secret = "synthetic-preview-session-secret-0001";
const previewCookie = "meser_preview_service_session";
const canonicalCookie = "__Host-meser_service_session";
const verifier = await createPasswordVerifier("local-test-password", Buffer.alloc(16, 11), { N: 16384, r: 8, p: 1 });
const sessions = new SessionRegistry({ maxEntries: 16 });
// Synthetic, process-local archive. It cannot access production storage or credentials.
const repository = new MemoryRepository();
const domain = new AudioArchiveDomain(repository, { acceptedPartBytes });
function syntheticWavPeaks(bytes) {
  const channels = bytes.readUInt16LE(22), bits = bytes.readUInt16LE(34), format = bytes.readUInt16LE(20);
  if (format !== 1 || bits !== 16 || channels < 1 || channels > 2) throw new Error('Synthetic preview supports PCM16 WAV only');
  let offset = 12, dataStart = -1, dataBytes = 0;
  while (offset + 8 <= bytes.length) {
    const size = bytes.readUInt32LE(offset + 4), next = offset + 8 + size + (size & 1);
    if (next > bytes.length) throw new Error('Invalid synthetic WAV chunk');
    if (bytes.toString('ascii', offset, offset + 4) === 'data') {
      dataStart = offset + 8; dataBytes = size; break;
    }
    offset = next;
  }
  const frames = Math.floor(dataBytes / (channels * 2));
  if (dataStart < 0 || frames < 1) throw new Error('Synthetic WAV has no PCM samples');
  const peaks = new Float32Array(WAVEFORM_PEAK_COUNT);
  for (let frame = 0; frame < frames; frame++) {
    let value = 0;
    for (let channel = 0; channel < channels; channel++)
      value = Math.max(value, Math.abs(bytes.readInt16LE(dataStart + (frame * channels + channel) * 2)) / 32768);
    const bin = Math.min(WAVEFORM_PEAK_COUNT - 1, Math.floor(frame * WAVEFORM_PEAK_COUNT / frames));
    peaks[bin] = Math.max(peaks[bin], value);
  }
  const body = Buffer.allocUnsafe(WAVEFORM_BODY_BYTES);
  for (let index = 0; index < peaks.length; index++) body.writeFloatLE(peaks[index], index * 4);
  return { body, frames, channels };
}
const waveformService = { get: async (sessionId, blobId) => {
  const source = await domain.waveformSource(sessionId, blobId);
  const bytes = Buffer.concat(source.parts.map(part => repository.assetBytes.get(part.assetId)));
  if (createHash('sha256').update(bytes).digest('hex') !== source.sha256 || source.mediaType !== 'audio/wav' ||
      bytes.toString('ascii', 0, 4) !== 'RIFF' || bytes.toString('ascii', 8, 12) !== 'WAVE') throw new Error('Synthetic preview supports verified WAV waveform only');
  const sampleRate = bytes.readUInt32LE(24);
  const { body, frames } = syntheticWavPeaks(bytes);
  const durationSeconds = frames / sampleRate;
  if (!(durationSeconds > 0)) throw new Error('Invalid synthetic WAV duration');
  return { body, algorithm: WAVEFORM_ALGORITHM, peakCount: WAVEFORM_PEAK_COUNT,
    durationSeconds, sourceSha256: source.sha256,
    resultSha256: createHash('sha256').update(body).digest('hex'), cache: 'synthetic' };
} };
const config = {
  allowedOrigin: origin, acceptedPartBytes, sessionSigningSecret: secret,
  sessionLifetimeSeconds: 4 * 60 * 60, activeSessionLimit: 16, sharedPasswordVerifier: verifier
};
const app = createApp({ config, domain, waveformService, sessionRegistry: sessions });

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
  const request = new Request(new URL(incoming.url || "/", origin), {
    method: incoming.method, headers: gatewayHeaders(incoming.headers), body, duplex: body ? "half" : undefined
  });
  const response = await app(request);
  // The production cookie remains Secure + __Host-. This preview-only alias is
  // required because WebKit intentionally refuses Secure cookies over local HTTP.
  outgoing.writeHead(response.status, previewHeaders(response.headers));
  if (response.body) Readable.fromWeb(response.body).pipe(outgoing); else outgoing.end();
}

const server = http.createServer(async (request, response) => {
  try {
    const url = new URL(request.url || "/", origin);
    if (url.pathname.startsWith("/v1/") || url.pathname === "/healthz") return void await apiRequest(request, response);
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
    response.writeHead(error?.code === "ENOENT" ? 404 : 500, { "Content-Type": "text/plain; charset=utf-8" });
    response.end(error?.code === "ENOENT" ? "Not found" : "Preview error");
  }
});

server.listen(port, "127.0.0.1", () => console.log(`S10B in-memory preview listening at ${origin}`));
