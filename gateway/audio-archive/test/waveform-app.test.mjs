import test from "node:test";
import assert from "node:assert/strict";
import { createApp } from "../src/app.mjs";
import { SessionRegistry, createSession } from "../src/auth.mjs";
import { waveformResponse, WAVEFORM_PEAK_COUNT } from "../src/waveform.mjs";

const ORIGIN = "https://meserproject.duckdns.org";
const SECRET = "0123456789abcdef0123456789abcdef";
const SESSION = "11111111-1111-4111-8111-111111111111";
const BLOB = "44444444-4444-4444-8444-444444444444";

test("waveform route requires the common session, accepts only canonical ids and exposes fixed binary metadata", async () => {
  const registry = new SessionRegistry({ clock: () => 1_000_000 });
  const cookie = createSession(SECRET, 3600, registry, 1_000_000).cookie.split(";", 1)[0];
  const body = Buffer.alloc(WAVEFORM_PEAK_COUNT * 4);
  const result = { body, algorithm: "meser-peaks-f32le-v1", peakCount: WAVEFORM_PEAK_COUNT, durationSeconds: 3747.648,
    sourceSha256: "a".repeat(64), resultSha256: "b".repeat(64), cache: "hit" };
  const calls = [];
  const app = createApp({
    config: { allowedOrigin: ORIGIN, acceptedPartBytes: 16 * 1024 * 1024, sessionSigningSecret: SECRET,
      sessionLifetimeSeconds: 3600, activeSessionLimit: 4, sharedPasswordVerifier: "unused" },
    domain: {}, sessionRegistry: registry, clock: () => 1_000_000,
    waveformService: { get: async (...args) => { calls.push(args); return result; } }
  });
  const path = `/v1/source-sessions/${SESSION}/blobs/${BLOB}/waveform`;
  assert.equal((await app(new Request(`${ORIGIN}${path}`))).status, 401);
  assert.equal((await app(new Request(`${ORIGIN}${path}?sha256=${"a".repeat(64)}`, { headers: { cookie } }))).status, 400);
  assert.equal((await app(new Request(`${ORIGIN}/v1/source-sessions/not-a-uuid/blobs/${BLOB}/waveform`, { headers: { cookie } }))).status, 400);
  assert.equal((await app(new Request(`${ORIGIN}/v1/source-sessions/${SESSION}/blobs/not-a-uuid/waveform`, { headers: { cookie } }))).status, 400);
  assert.equal((await app(new Request(`${ORIGIN}/v1/source-sessions/${SESSION}/blobs/%2e%2e/waveform`, { headers: { cookie } }))).status, 404);
  const response = await app(new Request(`${ORIGIN}${path}`, { headers: { cookie } }));
  assert.equal(response.status, 200); assert.equal(response.headers.get("content-type"), "application/vnd.meser.waveform-f32le");
  assert.equal(response.headers.get("x-meser-waveform-peaks"), "65536");
  assert.equal((await response.arrayBuffer()).byteLength, body.byteLength);
  assert.equal(calls.length, 1); assert.equal(calls[0][0], SESSION); assert.equal(calls[0][1], BLOB);
  assert.equal((await app(new Request(`${ORIGIN}/internal/waveform`, { headers: { cookie } }))).status, 404);
  assert.equal(waveformResponse(result).status, 200);
});
