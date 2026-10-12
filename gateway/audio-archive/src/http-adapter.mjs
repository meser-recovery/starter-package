export function nodeResponseHeaders(headers) {
  const result = Object.fromEntries([...headers.entries()].filter(([name]) => name.toLowerCase() !== "set-cookie"));
  const cookies = typeof headers.getSetCookie === "function" ? headers.getSetCookie() : [];
  if (cookies.length) result["Set-Cookie"] = cookies;
  else if (headers.has("set-cookie")) result["Set-Cookie"] = headers.get("set-cookie");
  return result;
}

// Shared by the production server and the local streaming/disconnect rehearsal.
export function nodeHandler(app) {
  return async (incoming, outgoing) => {
    const controller = new AbortController();
    incoming.once('aborted', () => controller.abort());
    outgoing.once('close', () => { if (!outgoing.writableFinished) controller.abort(); });
    try {
      const request = new Request(new URL(incoming.url || '/', `http://${incoming.headers.host || 'localhost'}`), {
        method: incoming.method, headers: incoming.headers,
        body: ['GET', 'HEAD'].includes(incoming.method || 'GET') ? undefined : Readable.toWeb(incoming),
        duplex: 'half', signal: controller.signal
      });
      const response = await app(request);
      outgoing.writeHead(response.status, nodeResponseHeaders(response.headers));
      if (response.body) await pipeline(Readable.fromWeb(response.body), outgoing);
      else outgoing.end();
    } catch {
      if (outgoing.headersSent) { outgoing.destroy(); return; }
      outgoing.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' });
      outgoing.end(JSON.stringify({ error: 'Внутренняя ошибка шлюза.' }));
    }
  };
}
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
