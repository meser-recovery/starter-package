#!/usr/bin/env node
// Allowlisted, secret-free preview for physical-device S10A waveform checks.
// It intentionally serves neither the repository nor the protected service.
import http from 'node:http';
import { createReadStream } from 'node:fs';
import { lstat, realpath } from 'node:fs/promises';
import { extname, resolve } from 'node:path';

const root = resolve(import.meta.dirname, '../..');
const port = Number(process.argv[2] || 4180);
const host = process.argv[3] || '127.0.0.1';
const harness = '/tests/safety/s10a-mobile-waveform-harness.html';
const exactFiles = new Set([
  harness,
  '/tests/safety/s10a-mobile-waveform-harness.mjs',
  '/tests/safety/fixtures/s10a-long-aac-lc-3747s.m4a',
  '/scripts/speaker-waveform.mjs',
  '/scripts/audio-waveform-image.mjs'
]);
const vendorPrefix = '/vendor/ffmpeg/';
const types = new Map([
  ['.html', 'text/html; charset=utf-8'], ['.mjs', 'text/javascript; charset=utf-8'],
  ['.js', 'text/javascript; charset=utf-8'], ['.wasm', 'application/wasm'], ['.m4a', 'audio/mp4']
]);
const csp = "default-src 'self'; base-uri 'none'; object-src 'none'; form-action 'self'; frame-ancestors 'none'; connect-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; script-src 'self' 'wasm-unsafe-eval'; style-src 'self'; worker-src 'self' blob:";

const server = http.createServer(async (request, response) => {
  try {
    if (!['GET', 'HEAD'].includes(request.method || '')) {
      response.writeHead(405, { Allow: 'GET, HEAD' }); response.end(); return;
    }
    const url = new URL(request.url || '/', 'http://preview.invalid');
    if (url.pathname === '/') {
      response.writeHead(303, { Location: harness, 'Cache-Control': 'no-store' }); response.end(); return;
    }
    if (!exactFiles.has(url.pathname) && !url.pathname.startsWith(vendorPrefix)) {
      response.writeHead(404); response.end(); return;
    }
    if (url.pathname.includes('/.') || url.pathname.includes('..')) {
      response.writeHead(404); response.end(); return;
    }
    const candidate = resolve(root, `.${url.pathname}`);
    const actual = await realpath(candidate);
    const vendorRoot = await realpath(resolve(root, `.${vendorPrefix}`));
    if (actual !== candidate || (url.pathname.startsWith(vendorPrefix) && !actual.startsWith(`${vendorRoot}/`))) {
      response.writeHead(404); response.end(); return;
    }
    const metadata = await lstat(actual);
    if (!metadata.isFile() || metadata.isSymbolicLink()) { response.writeHead(404); response.end(); return; }
    response.writeHead(200, {
      'Content-Type': types.get(extname(actual)) || 'application/octet-stream',
      'Content-Length': metadata.size,
      'Cache-Control': 'no-store',
      'Content-Security-Policy': csp,
      'Referrer-Policy': 'no-referrer',
      'X-Content-Type-Options': 'nosniff'
    });
    if (request.method === 'HEAD') response.end(); else createReadStream(actual).pipe(response);
  } catch (error) {
    response.writeHead(error?.code === 'ENOENT' ? 404 : 500); response.end();
  }
});

server.listen(port, host, () => {
  console.log(`S10A secret-free physical-device harness: http://${host}:${port}${harness}`);
});
