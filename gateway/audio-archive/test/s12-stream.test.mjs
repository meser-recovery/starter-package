import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { once } from 'node:events';
import { openZoomStream } from '../src/zoom.mjs';
import { nodeHandler } from '../src/http-adapter.mjs';
import { A } from './s12-fixtures.mjs';

const listen = async server => { server.listen(0, '127.0.0.1'); await once(server, 'listening'); return server.address().port; };
const close = server => new Promise(resolve => { server.close(resolve); server.closeAllConnections(); });
const timeout = (promise, ms = 5000) => Promise.race([promise, new Promise((_, reject) => { const t = setTimeout(() => reject(new Error('Fixture deadline exceeded')), ms); t.unref(); })]);

test('S12 A16 real HTTP stream: bytes, backpressure, disconnect reaches upstream, bounded queues and safe redirects', async () => {
  let closed, sent = 0, token, upstreamSignal;
  const disconnected = new Promise(resolve => { closed = resolve; });
  const largeSize = 40 * 1024 * 1024;
  const upstream = http.createServer((req, res) => {
    token = req.headers.authorization;
    if (req.url === '/unsafe') { res.writeHead(302, { Location: 'http://127.0.0.1/private' }); res.end(); return; }
    if (req.url === '/length') { res.writeHead(200, { 'Content-Type': 'audio/mp4', 'Content-Length': A.length + 1 }); res.end(A); return; }
    if (req.url === '/short') { res.writeHead(200, { 'Content-Type': 'audio/mp4' }); res.end(A.subarray(0, 20)); return; }
    if (req.url === '/cdn') { res.writeHead(302, { Location: 'https://cdn.zoomcdn.net/bytes' }); res.end(); return; }
    if (req.url !== '/slow') { res.writeHead(200, { 'Content-Type': 'audio/mp4', 'Content-Length': A.length }); res.end(A); return; }
    res.writeHead(200, { 'Content-Type': 'audio/mp4', 'Content-Length': largeSize });
    const chunk = Buffer.alloc(64 * 1024, 17);
    const send = () => {
      while (sent < largeSize) { sent += chunk.length; if (!res.write(chunk)) { res.once('drain', send); return; } }
      res.end();
    };
    res.once('close', closed); send();
  });
  const port = await listen(upstream);
  // Production URL/redirect/DNS validation still runs. The fixture replaces only
  // the transport socket with native local HTTP, never relaxing the public API.
  const options = {
    lookupImpl: async () => [{ address: '8.8.8.8', family: 4 }],
    requestImpl: (url, opts, callback) => { upstreamSignal = opts.signal; return http.request(`http://127.0.0.1:${port}${url.pathname}`, { ...opts, lookup: undefined }, callback); }
  };
  const gateway = http.createServer(nodeHandler(request => openZoomStream(`https://zoom.us${new URL(request.url).pathname}`, 'synthetic-token', new URL(request.url).pathname === '/slow' ? largeSize : A.length, request.signal, options)));
  const gatewayPort = await listen(gateway);
  try {
    const bytes = await openZoomStream('https://zoom.us/bytes', 'synthetic-token', A.length, undefined, options);
    assert.deepEqual(Buffer.from(await bytes.arrayBuffer()), A); assert.equal(token, 'Bearer synthetic-token');
    await assert.rejects(() => openZoomStream('https://zoom.us/unsafe', 'synthetic-token', A.length, undefined, options), /Небезопасный/);
    await assert.rejects(() => openZoomStream('https://zoom.us/length', 'synthetic-token', A.length, undefined, options), /не подтвердил/);
    const short = await openZoomStream('https://zoom.us/short', 'synthetic-token', A.length, undefined, options);
    await assert.rejects(() => short.arrayBuffer(), /Неполная/);
    const cdn = await openZoomStream('https://zoom.us/cdn', 'synthetic-token', A.length, undefined, options);
    await cdn.arrayBuffer(); assert.equal(token, undefined, 'Bearer must not cross to CDN');
    let requests = 0;
    await assert.rejects(() => openZoomStream('https://zoom.us/bytes', 'synthetic-token', A.length, undefined, { lookupImpl: async () => [{ address: '127.0.0.1', family: 4 }], requestImpl: () => { requests++; } }));
    assert.equal(requests, 0);
    const response = await fetch(`http://127.0.0.1:${gatewayPort}/slow`);
    const reader = response.body.getReader(); await reader.read();
    await new Promise(resolve => setTimeout(resolve, 100));
    assert.ok(sent < largeSize / 2, `upstream was buffered: ${sent}`);
    await reader.cancel('browser tab closed');
    await timeout(disconnected); assert.equal(upstreamSignal.aborted, true);
    const stoppedAt = sent; await new Promise(resolve => setTimeout(resolve, 50)); assert.equal(sent, stoppedAt);
  } finally { await close(gateway); await close(upstream); }
});
