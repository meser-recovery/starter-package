#!/usr/bin/env node
import http from "node:http";
import { readFile } from "node:fs/promises";
import { extname, resolve } from "node:path";
import { Readable } from "node:stream";
import { createApp } from "../../gateway/audio-archive/src/app.mjs";
import { SessionRegistry, createPasswordVerifier, readSession } from "../../gateway/audio-archive/src/auth.mjs";
import { nodeResponseHeaders } from "../../gateway/audio-archive/src/http-adapter.mjs";

const port = Number(process.argv[2] || 4173);
const origin = process.argv[3] || `http://localhost:${port}`;
const frontend = resolve(import.meta.dirname, "../../service/frontend");
const secret = "synthetic-preview-session-secret-0001";
const previewCookie = "meser_preview_service_session";
const canonicalCookie = "__Host-meser_service_session";
const verifier = await createPasswordVerifier("local-test-password", Buffer.alloc(16, 11), { N: 16384, r: 8, p: 1 });
const sessions = new SessionRegistry({ maxEntries: 16 });
const domain = new Proxy({}, { get: (_target, name) => async () => {
  if (name === "listSessions") return { revision: 1, sessions: [] };
  if (name === "listIncomplete") return { transactions: [], orphans: [] };
  return {};
} });
const config = {
  allowedOrigin: origin, acceptedPartBytes: 1024, sessionSigningSecret: secret,
  sessionLifetimeSeconds: 4 * 60 * 60, activeSessionLimit: 16, sharedPasswordVerifier: verifier
};
const app = createApp({ config, domain, sessionRegistry: sessions });

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

server.listen(port, "127.0.0.1", () => console.log(`S10A preview listening at ${origin}`));
