import test from "node:test";
import assert from "node:assert/strict";
import {
  LoginThrottle, RETIRED_COOKIE_NAMES, SERVICE_COOKIE_NAME, SessionRegistry, clearSessionCookies,
  createPasswordVerifier, createSession, readSession, requireCsrf, verifyPassword
} from "../src/auth.mjs";
import { createApp } from "../src/app.mjs";

const ORIGIN = "https://meserproject.duckdns.org";
const SECRET = "0123456789abcdef0123456789abcdef";

function canonicalCookie(response) {
  const header = response.headers.getSetCookie().find(value => value.startsWith(`${SERVICE_COOKIE_NAME}=`));
  return header.split(";", 1)[0];
}

test("scrypt password verifier accepts only the original password", async () => {
  const verifier = await createPasswordVerifier("correct horse battery staple", Buffer.alloc(16, 7), { N: 16384, r: 8, p: 1 });
  assert.equal(await verifyPassword("correct horse battery staple", verifier), true);
  assert.equal(await verifyPassword("wrong password", verifier), false);
  assert.equal(await verifyPassword("anything", "malformed"), false);
});

test("one signed host-only Lax cookie binds a bounded in-memory session and CSRF", () => {
  let now = 1_000_000;
  const registry = new SessionRegistry({ clock: () => now, maxEntries: 2 });
  const created = createSession(SECRET, 3600, registry, now);
  assert.match(created.cookie, new RegExp(`^${SERVICE_COOKIE_NAME}=`));
  for (const attribute of ["Path=/", "Secure", "HttpOnly", "SameSite=Lax", "Max-Age=3600"]) assert.match(created.cookie, new RegExp(attribute));
  assert.doesNotMatch(created.cookie, /Domain=|Partitioned|SameSite=None/);
  assert.equal(created.cookies.filter(value => !value.includes("Max-Age=0")).length, 1);
  assert.equal(created.cookies.length, 3);
  for (const retired of RETIRED_COOKIE_NAMES) assert.ok(created.cookies.some(value => value.startsWith(`${retired}=;`) && value.includes("Max-Age=0")));

  const cookie = created.cookie.split(";", 1)[0];
  const request = new Request(`${ORIGIN}/v1/session`, { headers: { cookie } });
  const session = readSession(request, SECRET, registry, now + 1);
  assert.equal(session.csrfToken, created.session.csrfToken);
  assert.throws(() => requireCsrf(request, session), error => error.status === 403);
  assert.doesNotThrow(() => requireCsrf(new Request(request.url, { headers: { cookie, "X-CSRF-Token": session.csrfToken } }), session));
  assert.equal(readSession(new Request(request.url, { headers: { cookie: `${cookie}x` } }), SECRET, registry, now), null);
  assert.equal(readSession(new Request(request.url, { headers: { cookie: `${RETIRED_COOKIE_NAMES[0]}=legacy` } }), SECRET, registry, now), null);

  createSession(SECRET, 3600, registry, now);
  const newest = createSession(SECRET, 3600, registry, now);
  assert.equal(registry.sessions.size, 2);
  assert.equal(readSession(request, SECRET, registry, now), null, "oldest session is evicted at the bound");
  assert.ok(readSession(new Request(request.url, { headers: { cookie: newest.cookie.split(";", 1)[0] } }), SECRET, registry, now));

  now += 4_000_000;
  registry.prune();
  assert.equal(registry.sessions.size, 0);
  assert.equal(clearSessionCookies().length, 3);
  const restarted = new SessionRegistry({ clock: () => now });
  assert.equal(readSession(request, SECRET, restarted, now), null, "gateway restart invalidates prior sessions");
});

test("login throttle is bounded and blocks repeated failures", () => {
  let now = 0;
  const throttle = new LoginThrottle({ clock: () => now, maxEntries: 2, windowMs: 1000, maxFailures: 2, blockMs: 5000 });
  const request = new Request(ORIGIN, { headers: { "x-forwarded-for": "203.0.113.1", "user-agent": "test" } });
  throttle.failure(request); throttle.failure(request);
  assert.throws(() => throttle.check(request), error => error.status === 429 && error.retryAfter === 5);
  now = 6000;
  assert.doesNotThrow(() => throttle.check(request));
});

test("same-origin service login requires replay; config/data, mutations, auth-check and logout fail closed", async () => {
  const verifier = await createPasswordVerifier("correct horse battery staple", Buffer.alloc(16, 8), { N: 16384, r: 8, p: 1 });
  const calls = [];
  const domain = new Proxy({}, { get: (_target, name) => async (...args) => {
    calls.push([name, args]);
    return name === "listSessions" ? { revision: 0, sessions: [] } : {};
  } });
  const registry = new SessionRegistry({ clock: () => 1_000_000, maxEntries: 4 });
  const app = createApp({ config: {
    allowedOrigin: ORIGIN, acceptedPartBytes: 16 * 1024 * 1024, sessionSigningSecret: SECRET,
    sessionLifetimeSeconds: 3600, activeSessionLimit: 4, sharedPasswordVerifier: verifier
  }, domain, clock: () => 1_000_000, sessionRegistry: registry });

  assert.equal((await app(new Request(`${ORIGIN}/healthz`))).status, 200);
  assert.equal((await app(new Request(`${ORIGIN}/v1/config`))).status, 401);
  assert.equal((await app(new Request(`${ORIGIN}/internal/auth-check`))).status, 401);
  let documentAuth = await app(new Request(`${ORIGIN}/internal/document-auth`, {
    headers: { "X-Forwarded-Uri": "/Audio-Editor.html?workflow=speaker&projectRevision=7" }
  }));
  assert.equal(documentAuth.status, 303);
  assert.equal(documentAuth.headers.get("location"), "/login?return=%2FAudio-Editor.html%3Fworkflow%3Dspeaker%26projectRevision%3D7");
  for (const unsafe of [
    "https://evil.example/Audio-Editor.html", "/Calendar.html?next=https://evil.example",
    "/Audio-Archive.html?session=bad", "/Audio-Editor.html?workflow=speaker&workflow=announcement"
  ]) {
    documentAuth = await app(new Request(`${ORIGIN}/internal/document-auth`, { headers: { "X-Forwarded-Uri": unsafe } }));
    assert.equal(documentAuth.status, 303);
    assert.ok(["/login?return=%2F", "/login?return=%2FAudio-Archive.html", "/login?return=%2FAudio-Editor.html"].includes(documentAuth.headers.get("location")), unsafe);
  }

  let response = await app(new Request(`${ORIGIN}/v1/session/login`, {
    method: "POST", headers: { Origin: "https://meser-recovery.github.io", "Content-Type": "application/json" },
    body: JSON.stringify({ password: "correct horse battery staple" })
  }));
  assert.equal(response.status, 403);

  response = await app(new Request(`${ORIGIN}/v1/session/login`, {
    method: "POST", headers: { Origin: ORIGIN, "Content-Type": "application/json" }, body: JSON.stringify({ password: "wrong" })
  }));
  assert.equal(response.status, 401);

  response = await app(new Request(`${ORIGIN}/v1/session/login`, {
    method: "POST", headers: { Origin: ORIGIN, "Content-Type": "application/json" },
    body: JSON.stringify({ password: "correct horse battery staple" })
  }));
  assert.equal(response.status, 200);
  assert.deepEqual(await response.clone().json(), { authenticated: true }, "login POST never returns CSRF");
  assert.equal(response.headers.getSetCookie().filter(value => value.startsWith(`${SERVICE_COOKIE_NAME}=`) && !value.includes("Max-Age=0")).length, 1);
  const cookie = canonicalCookie(response);

  response = await app(new Request(`${ORIGIN}/internal/auth-check`, { headers: { cookie } }));
  assert.equal(response.status, 200);
  assert.equal(await response.text(), "");
  assert.equal(response.headers.get("x-service-authenticated"), "true");
  response = await app(new Request(`${ORIGIN}/internal/document-auth`, {
    headers: { cookie, "X-Forwarded-Uri": "/Audio-Editor.html?workflow=speaker" }
  }));
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("x-service-authenticated"), "true");

  response = await app(new Request(`${ORIGIN}/v1/session`, { headers: { cookie } }));
  assert.equal(response.status, 200);
  const proof = await response.json();
  assert.equal(proof.authenticated, true);
  assert.match(proof.csrfToken, /^[A-Za-z0-9_-]+$/);

  response = await app(new Request(`${ORIGIN}/v1/config`, { headers: { cookie } }));
  assert.equal(response.status, 200);
  assert.equal((await response.json()).speakerProjectHistory, 1);
  response = await app(new Request(`${ORIGIN}/v1/source-sessions`, { headers: { cookie } }));
  assert.equal(response.status, 200);

  const mutation = `${ORIGIN}/v1/source-sessions/11111111-1111-4111-8111-111111111111/archive`;
  const body = JSON.stringify({ expectedRevision: 1, idempotencyKey: "0123456789abcdef" });
  response = await app(new Request(mutation, { method: "POST", headers: { cookie, "Content-Type": "application/json" }, body }));
  assert.equal(response.status, 403, "missing Origin fails closed");
  response = await app(new Request(mutation, { method: "POST", headers: { Origin: "https://evil.example", cookie, "Content-Type": "application/json", "X-CSRF-Token": proof.csrfToken }, body }));
  assert.equal(response.status, 403, "foreign Origin fails closed");
  response = await app(new Request(mutation, { method: "POST", headers: { Origin: ORIGIN, cookie, "Content-Type": "application/json" }, body }));
  assert.equal(response.status, 403, "missing CSRF fails closed");
  response = await app(new Request(mutation, { method: "POST", headers: { Origin: ORIGIN, cookie, "Content-Type": "application/json", "X-CSRF-Token": proof.csrfToken }, body }));
  assert.equal(response.status, 200);
  assert.equal(calls.at(-1)[0], "setLifecycle");

  response = await app(new Request(`${ORIGIN}/v1/session/logout`, {
    method: "POST", headers: { Origin: ORIGIN, cookie, "X-CSRF-Token": proof.csrfToken }
  }));
  assert.equal(response.status, 200);
  assert.equal(response.headers.getSetCookie().length, 3);
  assert.ok(response.headers.getSetCookie().every(value => value.includes("Max-Age=0")));
  assert.equal((await app(new Request(`${ORIGIN}/v1/session`, { headers: { cookie } }))).status, 401);
  assert.equal((await app(new Request(`${ORIGIN}/internal/auth-check`, { headers: { cookie } }))).status, 401);
});
