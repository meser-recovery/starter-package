import test from "node:test";
import assert from "node:assert/strict";
import {
  LoginThrottle, clearSessionCookie, createPasswordVerifier, createSession, readSession, requireCsrf, verifyPassword
} from "../src/auth.mjs";
import { createApp } from "../src/app.mjs";

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
  for (const attribute of ["Path=/", "Secure", "HttpOnly", "SameSite=None", "Partitioned", "Max-Age=3600"]) assert.match(created.cookie, new RegExp(attribute));
  const cookie = created.cookie.split(";", 1)[0];
  const request = new Request("https://gateway.test/v1/session", { headers: { cookie } });
  const session = readSession(request, SECRET, 1_000_001);
  assert.equal(session.csrfToken, created.csrfToken);
  assert.equal(readSession(request, SECRET, 5_000_000), null);
  assert.equal(readSession(new Request(request.url, { headers: { cookie: `${cookie}x` } }), SECRET, 1_000_001), null);
  assert.throws(() => requireCsrf(new Request(request.url), session), /CSRF/);
  assert.doesNotThrow(() => requireCsrf(new Request(request.url, { headers: { "X-CSRF-Token": created.csrfToken } }), session));
  assert.match(clearSessionCookie(), /Max-Age=0/);
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
});
