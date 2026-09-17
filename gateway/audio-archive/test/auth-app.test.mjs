import test from "node:test";
import assert from "node:assert/strict";
import {
  LoginThrottle, PARTITIONED_COOKIE_NAME, STORAGE_ACCESS_COOKIE_NAME, clearSessionCookie, createPasswordVerifier, createSession, readSession, requireCsrf, verifyPassword
} from "../src/auth.mjs";
import { createApp } from "../src/app.mjs";
import { nodeResponseHeaders } from "../src/http-adapter.mjs";

const ORIGIN = "https://meser-recovery.github.io";
const SECRET = "0123456789abcdef0123456789abcdef";

test("scrypt password verifier accepts only the original password", async () => {
  const verifier = await createPasswordVerifier("correct horse battery staple", Buffer.alloc(16, 7), { N: 16384, r: 8, p: 1 });
  assert.equal(await verifyPassword("correct horse battery staple", verifier), true);
  assert.equal(await verifyPassword("wrong password", verifier), false);
  assert.equal(await verifyPassword("anything", "malformed"), false);
});

test("session cookie is signed, HttpOnly cross-site capable, expiring, and CSRF bound", () => {
  const created = createSession(SECRET, 3600, 1_000_000);
  assert.equal(created.cookies.length, 2);
  for (const attribute of ["Path=/", "Secure", "HttpOnly", "SameSite=None", "Partitioned", "Max-Age=3600"]) assert.match(created.cookie, new RegExp(attribute));
  assert.match(created.cookies[1], new RegExp(`^${STORAGE_ACCESS_COOKIE_NAME}=`));
  assert.doesNotMatch(created.cookies[1], /Partitioned/);
  assert.equal(created.cookies[0].split("=", 2)[1].split(";", 1)[0], created.cookies[1].split("=", 2)[1].split(";", 1)[0]);
  const cookie = created.cookie.split(";", 1)[0];
  const request = new Request("https://gateway.test/v1/session", { headers: { cookie } });
  const session = readSession(request, SECRET, 1_000_001);
  assert.equal(session.csrfToken, created.csrfToken);
  assert.equal(readSession(request, SECRET, 5_000_000), null);
  assert.equal(readSession(new Request(request.url, { headers: { cookie: `${cookie}x` } }), SECRET, 1_000_001), null);
  assert.throws(() => requireCsrf(new Request(request.url), session), /CSRF/);
  assert.doesNotThrow(() => requireCsrf(new Request(request.url, { headers: { "X-CSRF-Token": created.csrfToken } }), session));
  assert.equal(clearSessionCookie().length, 2);
  for (const cleared of clearSessionCookie()) assert.match(cleared, /Max-Age=0/);

  const value = created.cookie.split(";", 1)[0].split("=")[1];
  const storage = `${STORAGE_ACCESS_COOKIE_NAME}=${value}`;
  assert.equal(readSession(new Request(request.url, { headers: { cookie: storage } }), SECRET, 1_000_001).csrfToken, created.csrfToken);
  assert.equal(readSession(new Request(request.url, { headers: { cookie: `${cookie}; ${storage}` } }), SECRET, 1_000_001).csrfToken, created.csrfToken);
  assert.equal(readSession(new Request(request.url, { headers: { cookie: `${cookie}; ${STORAGE_ACCESS_COOKIE_NAME}=${value}x` } }), SECRET, 1_000_001), null);
});

test("Node adapter preserves two independent Set-Cookie headers", () => {
  const headers = new Headers();
  headers.append("Set-Cookie", `${PARTITIONED_COOKIE_NAME}=a; Path=/; Partitioned`);
  headers.append("Set-Cookie", `${STORAGE_ACCESS_COOKIE_NAME}=a; Path=/`);
  const adapted = nodeResponseHeaders(headers);
  assert.deepEqual(adapted["Set-Cookie"], headers.getSetCookie());
  assert.equal(adapted["Set-Cookie"].length, 2);
});

test("login throttle is bounded and blocks repeated failures", () => {
  let now = 0;
  const throttle = new LoginThrottle({ clock: () => now, maxEntries: 2, windowMs: 1000, maxFailures: 2, blockMs: 5000 });
  const request = new Request("https://gateway.test", { headers: { "x-forwarded-for": "203.0.113.1", "user-agent": "test" } });
  throttle.failure(request); throttle.failure(request);
  assert.throws(() => throttle.check(request), (error) => error.status === 429 && error.retryAfter === 5);
  now = 6000;
  assert.doesNotThrow(() => throttle.check(request));
});

test("gateway enforces exact origin, authentication, CORS, cookie and CSRF", async () => {
  const verifier = await createPasswordVerifier("correct horse battery staple", Buffer.alloc(16, 8), { N: 16384, r: 8, p: 1 });
  const calls = [];
  const domain = new Proxy({}, { get: (_target, name) => async (...args) => { calls.push([name, args]); return { revision: 0, sessions: [] }; } });
  const app = createApp({ config: {
    allowedOrigin: ORIGIN, acceptedPartBytes: 16 * 1024 * 1024, sessionSigningSecret: SECRET,
    sessionLifetimeSeconds: 3600, sharedPasswordVerifier: verifier
  }, domain, clock: () => 1_000_000 });
  let response = await app(new Request("https://gateway.test/healthz"));
  assert.equal(response.status, 200);
  response = await app(new Request("https://gateway.test/v1/config", { headers: { Origin: "https://evil.example" } }));
  assert.equal(response.status, 403);
  assert.equal(response.headers.get("access-control-allow-origin"), null);
  response = await app(new Request("https://gateway.test/v1/config", { headers: { Origin: ORIGIN } }));
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("access-control-allow-origin"), ORIGIN);
  assert.equal(response.headers.get("access-control-allow-credentials"), "true");
  assert.equal((await response.clone().json()).speakerProjectHistory, 1);
  response = await app(new Request("https://gateway.test/v1/source-sessions", { headers: { Origin: ORIGIN } }));
  assert.equal(response.status, 401);
  response = await app(new Request("https://gateway.test/v1/session/login", {
    method: "POST", headers: { Origin: ORIGIN, "Content-Type": "application/json" }, body: JSON.stringify({ password: "wrong" })
  }));
  assert.equal(response.status, 401);
  response = await app(new Request("https://gateway.test/v1/session/login", {
    method: "POST", headers: { Origin: ORIGIN, "Content-Type": "application/json" }, body: JSON.stringify({ password: "correct horse battery staple" })
  }));
  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.equal(response.headers.getSetCookie().length, 2);
  const cookie = response.headers.get("set-cookie").split(";", 1)[0];
  response = await app(new Request("https://gateway.test/v1/source-sessions/11111111-1111-4111-8111-111111111111/archive", {
    method: "POST", headers: { Origin: ORIGIN, cookie, "Content-Type": "application/json" },
    body: JSON.stringify({ expectedRevision: 1, idempotencyKey: "0123456789abcdef" })
  }));
  assert.equal(response.status, 403);
  response = await app(new Request("https://gateway.test/v1/source-sessions/11111111-1111-4111-8111-111111111111/archive", {
    method: "POST", headers: { Origin: ORIGIN, cookie, "Content-Type": "application/json", "X-CSRF-Token": payload.csrfToken },
    body: JSON.stringify({ expectedRevision: 1, idempotencyKey: "0123456789abcdef" })
  }));
  assert.equal(response.status, 200);
  assert.equal(calls.at(-1)[0], "setLifecycle");
  response = await app(new Request("https://gateway.test/v1/source-sessions/%E0%A4%A", { headers: { Origin: ORIGIN, cookie } }));
  assert.equal(response.status, 400);

  const publicationPath = "/v1/source-sessions/11111111-1111-4111-8111-111111111111/outputs/announcement/publications";
  response = await app(new Request(`https://gateway.test${publicationPath}`, {
    method: "POST", headers: { Origin: ORIGIN, cookie, "Content-Type": "application/json" }, body: "{}"
  }));
  assert.equal(response.status, 403);
  response = await app(new Request(`https://gateway.test${publicationPath}`, {
    method: "POST", headers: { Origin: ORIGIN, cookie, "Content-Type": "application/json", "X-CSRF-Token": payload.csrfToken }, body: "{}"
  }));
  assert.equal(response.status, 201);
  assert.equal(calls.at(-1)[0], "beginAnnouncementPublication");
  const transactionId = "22222222-2222-4222-8222-222222222222";
  const blobId = "33333333-3333-4333-8333-333333333333";
  response = await app(new Request(`https://gateway.test/v1/announcement-publications/${transactionId}/blobs/${blobId}/parts/1`, {
    method: "PUT", headers: { Origin: ORIGIN, cookie, "Content-Type": "application/octet-stream", "Content-Length": String(16 * 1024 * 1024 + 1),
      "X-CSRF-Token": payload.csrfToken, "X-Part-SHA256": "0".repeat(64), "Idempotency-Key": "0123456789abcdef" }, body: Uint8Array.of(1)
  }));
  assert.equal(response.status, 413);
  response = await app(new Request(`https://gateway.test/v1/announcement-publications/${transactionId}/cancel`, {
    method: "POST", headers: { Origin: ORIGIN, cookie, "Content-Type": "application/json", "X-CSRF-Token": payload.csrfToken },
    body: JSON.stringify({ idempotencyKey: "0123456789abcdef" })
  }));
  assert.equal(response.status, 200);
  assert.equal(calls.at(-1)[0], "cancelAnnouncementPublication");
  const speakerPath = "/v1/source-sessions/11111111-1111-4111-8111-111111111111/outputs/speaker/saves";
  response = await app(new Request(`https://gateway.test${speakerPath}`, {
    method: "POST", headers: { Origin: ORIGIN, cookie, "Content-Type": "application/json", "X-CSRF-Token": payload.csrfToken }, body: "{}"
  }));
  assert.equal(response.status, 201);
  assert.equal(calls.at(-1)[0], "beginSpeakerPublication");
  response = await app(new Request(`https://gateway.test/v1/speaker-saves/${transactionId}/cancel`, {
    method: "POST", headers: { Origin: ORIGIN, cookie, "Content-Type": "application/json", "X-CSRF-Token": payload.csrfToken },
    body: JSON.stringify({ idempotencyKey: "0123456789abcdef" })
  }));
  assert.equal(response.status, 200);
  assert.equal(calls.at(-1)[0], "cancelSpeakerPublication");
  const projectPath = "/v1/source-sessions/11111111-1111-4111-8111-111111111111/projects/speaker";
  response = await app(new Request(`https://gateway.test${projectPath}`, { headers: { Origin: ORIGIN, cookie } }));
  assert.equal(response.status, 200);
  assert.equal(calls.at(-1)[0], "speakerProjectHistory");
  response = await app(new Request(`https://gateway.test${projectPath}/states/2`, { headers: { Origin: ORIGIN, cookie } }));
  assert.equal(response.status, 200);
  assert.deepEqual(calls.at(-1), ["getSpeakerProjectState", ["11111111-1111-4111-8111-111111111111", 2]]);
  response = await app(new Request(`https://gateway.test${projectPath}/continuations`, {
    method: "POST", headers: { Origin: ORIGIN, cookie, "Content-Type": "application/json" }, body: "{}"
  }));
  assert.equal(response.status, 403);
  response = await app(new Request(`https://gateway.test${projectPath}/continuations`, {
    method: "POST", headers: { Origin: ORIGIN, cookie, "Content-Type": "application/json", "X-CSRF-Token": payload.csrfToken }, body: "{}"
  }));
  assert.equal(response.status, 200);
  assert.equal(calls.at(-1)[0], "continueSpeakerProject");

  response = await app(new Request("https://gateway.test/v1/session/logout", {
    method: "POST", headers: { Origin: ORIGIN, cookie, "X-CSRF-Token": payload.csrfToken }
  }));
  assert.equal(response.status, 200);
  assert.equal(response.headers.getSetCookie().length, 2);
  assert.ok(response.headers.getSetCookie().every(value => value.includes("Max-Age=0")));

  response = await app(new Request("https://gateway.test/v1/session/logout", {
    method: "POST", headers: { Origin: ORIGIN, cookie: `${cookie}; ${STORAGE_ACCESS_COOKIE_NAME}=conflict` }
  }));
  assert.equal(response.status, 200);
  assert.equal(response.headers.getSetCookie().length, 2);

  response = await app(new Request("https://gateway.test/safari-bootstrap"));
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.match(response.headers.get("content-security-policy"), /frame-ancestors 'none'/);
  assert.match(response.headers.get("content-security-policy"), /connect-src 'self'/);
  assert.doesNotMatch(await response.text(), /csrfToken|sessionId/);
  response = await app(new Request("https://gateway.test/storage-access-bridge"));
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-security-policy"), /frame-ancestors https:\/\/meser-recovery\.github\.io/);
  const bridge = await response.text();
  assert.match(bridge, /document\.hasStorageAccess/);
  assert.match(bridge, /document\.requestStorageAccess/);
  assert.doesNotMatch(bridge, /postMessage\([^,]+,\s*["']\*["']/);

  response = await app(new Request("https://gateway.test/safari-bootstrap", {
    method: "POST", headers: { Origin: "https://evil.example", "Content-Type": "application/x-www-form-urlencoded" }, body: "password=correct+horse+battery+staple"
  }));
  assert.equal(response.status, 403);
  response = await app(new Request("https://gateway.test/safari-bootstrap", {
    method: "POST", headers: { Origin: "https://meserproject.duckdns.org", "Content-Type": "application/x-www-form-urlencoded" }, body: "password=correct+horse+battery+staple"
  }));
  assert.equal(response.status, 303);
  assert.equal(response.headers.getSetCookie().length, 2);
  assert.equal(response.headers.get("location"), "/safari-bootstrap?verify=1");
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.match(response.headers.get("content-security-policy"), /frame-ancestors 'none'/);
  const bootstrapCookies = response.headers.getSetCookie().map(value => value.split(";", 1)[0]).join("; ");
  response = await app(new Request("https://gateway.test/v1/session", {
    headers: { Origin: "https://meserproject.duckdns.org", cookie: bootstrapCookies }
  }));
  assert.equal(response.status, 200);
  assert.equal((await response.json()).authenticated, true);
});
