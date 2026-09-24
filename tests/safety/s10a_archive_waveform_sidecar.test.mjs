import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { AudioArchiveGateway } from "../../service/frontend/scripts/audio-archive-client.mjs";
import { parseEditorIntent } from "../../service/frontend/scripts/audio-archive-core.mjs";
import { defaultSpeakerPayload, normalizeSpeakerPayload } from "../../service/frontend/scripts/speaker-editor-core.mjs";
import { drawWaveformViewport } from "../../service/frontend/scripts/audio-waveform-view.mjs";
import { safeWaveformDiagnostic } from "../../service/frontend/scripts/speaker-waveform-diagnostics.mjs";
import { WaveformStageError } from "../../service/frontend/scripts/speaker-waveform.mjs";

const SESSION = "11111111-1111-4111-8111-111111111111";
const BLOB = "44444444-4444-4444-8444-444444444444";
const SOURCE_SHA = "a".repeat(64);
const sha = value => createHash("sha256").update(value).digest("hex");

function waveformResponse({ status = 200, sourceSha = SOURCE_SHA, mutate = false, secondPeak = 0 } = {}) {
  const peaks = new Float32Array(65536);
  peaks[0] = 1; peaks[1] = secondPeak; peaks[65535] = .5;
  const bytes = new Uint8Array(peaks.buffer.slice(0));
  if (mutate) bytes[4] = 255;
  return new Response(status === 200 ? bytes : JSON.stringify({ error: "safe failure", waveformDiagnostic: { stage: "exec", exitStatus: 7 } }), {
    status,
    headers: status === 200 ? {
      "Content-Type": "application/vnd.meser.waveform-f32le",
      "X-Meser-Waveform-Algorithm": "meser-peaks-f32le-v1",
      "X-Meser-Waveform-Peaks": "65536",
      "X-Meser-Waveform-Duration": "3747.648",
      "X-Meser-Source-SHA256": sourceSha,
      "X-Meser-Waveform-SHA256": sha(bytes),
      "X-Meser-Waveform-Cache": "miss"
    } : { "Content-Type": "application/json" }
  });
}

test("Archive waveform request sends only canonical ids and validates the fixed peak contract", async () => {
  const requests = [];
  const gateway = new AudioArchiveGateway("", async (url, options) => { requests.push({ url, options }); return waveformResponse(); });
  const result = await gateway.sourceWaveform(SESSION, BLOB, { sha256: SOURCE_SHA }, new AbortController().signal);
  assert.equal(result.samples.length, 65536); assert.equal(result.samples[0], 1); assert.equal(result.samples.at(-1), .5);
  assert.equal(result.samples.byteLength, 262144, "exact Float32LE payload is retained without conversion loss");
  assert.equal(result.duration, 3747.648); assert.equal(result.cache, "miss");
  assert.equal(requests[0].url, `/v1/source-sessions/${SESSION}/blobs/${BLOB}/waveform`);
  assert.equal(requests[0].url.includes("sha"), false); assert.equal(requests[0].options.credentials, "include");
});

test("three exact Float32LE sidecar responses validate and render without Array.at or Object.hasOwn", async () => {
  const blobs = [BLOB, "55555555-5555-4555-8555-555555555555", "66666666-6666-4666-8666-666666666666"];
  const tracks = ["11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222", "33333333-3333-4333-8333-333333333333"];
  const responses = blobs.map(() => waveformResponse());
  const originalAt = Object.getOwnPropertyDescriptor(Array.prototype, "at");
  const originalHasOwn = Object.getOwnPropertyDescriptor(Object, "hasOwn");
  const requests = [];
  const gateway = new AudioArchiveGateway("", async (url) => { requests.push(url); return responses.shift(); });
  try {
    Object.defineProperty(Array.prototype, "at", { value: undefined, configurable: true, writable: true });
    Object.defineProperty(Object, "hasOwn", { value: undefined, configurable: true, writable: true });
    assert.deepEqual(parseEditorIntent(`?session=${SESSION}&workflow=speaker`), { sessionId: SESSION, workflow: "speaker" });
    const samples = [];
    for (const blob of blobs) {
      const result = await gateway.sourceWaveform(SESSION, blob, { sha256: SOURCE_SHA });
      assert.equal(result.samples.byteLength, 262144);
      samples.push(result.samples);
    }
    const payload = normalizeSpeakerPayload(defaultSpeakerPayload(tracks), tracks, 3747.648);
    assert.equal(payload.trackIds.length, 3);
    const rendered = samples.map((peaks) => {
      const points = [];
      const context = { fillRect() {}, beginPath() {}, moveTo(...point) { points.push(point); },
        lineTo(...point) { points.push(point); }, closePath() {}, fill() {} };
      const canvas = { style: {}, getContext: () => context };
      drawWaveformViewport(canvas, peaks, 3747.648, 2, 0, 800, 100, 2);
      assert.ok(points.length > 0);
      return peaks.length;
    });
    assert.deepEqual(rendered, [65536, 65536, 65536]);
    assert.equal(requests.length, 3);
  } finally {
    if (originalAt) Object.defineProperty(Array.prototype, "at", originalAt); else delete Array.prototype.at;
    if (originalHasOwn) Object.defineProperty(Object, "hasOwn", originalHasOwn); else delete Object.hasOwn;
  }
});

test("post-read validation and render exceptions preserve stage, name and safe message", () => {
  const validation = safeWaveformDiagnostic(new TypeError("Object.hasOwn is not a function"), { stage: "validate" });
  assert.equal(validation.stage, "validate");
  assert.equal(validation.exceptionName, "TypeError");
  assert.equal(validation.exceptionMessage, "Object.hasOwn is not a function");
  const render = safeWaveformDiagnostic(new TypeError("canvas.getContext is not a function"), { stage: "render" });
  assert.equal(render.stage, "render");
  assert.equal(render.exceptionName, "TypeError");
  assert.equal(render.exceptionMessage, "canvas.getContext is not a function");
  assert.notEqual(render.stage, "load");
  const wrapped = safeWaveformDiagnostic(new Error("Waveform preparation failed", {
    cause: new TypeError("canvas.getContext is not a function")
  }), { stage: "render" });
  assert.equal(wrapped.exceptionName, "TypeError");
  assert.equal(wrapped.exceptionMessage, "canvas.getContext is not a function");
  const stageCause = new TypeError("WASM read failed");
  assert.equal(new WaveformStageError({ stage: "wasm-read" }, stageCause).cause, stageCause);
  assert.equal(safeWaveformDiagnostic(new DOMException("cancelled", "AbortError"), { stage: "render" }).stage, "aborted");
  assert.equal(safeWaveformDiagnostic(new Error("https://example.test/?token=private"), { stage: "render" }).exceptionMessage,
    "Error details redacted");
});

test("source identity mismatch and server stage fail closed without exposing request data", async () => {
  const mismatch = new AudioArchiveGateway("", async () => waveformResponse({ sourceSha: "b".repeat(64) }));
  await assert.rejects(mismatch.sourceWaveform(SESSION, BLOB, { sha256: SOURCE_SHA }), /Проверка server waveform/);
  const failed = new AudioArchiveGateway("", async () => waveformResponse({ status: 502 }));
  await assert.rejects(failed.sourceWaveform(SESSION, BLOB, { sha256: SOURCE_SHA }), error =>
    error.status === 502 && error.waveformDiagnostic.stage === "exec" && error.waveformDiagnostic.exitStatus === 7);
});

test("unexpected binary media type is reported as parse before peak validation", async () => {
  const gateway = new AudioArchiveGateway("", async () => new Response(new Uint8Array(262144), { status: 200, headers: { "Content-Type": "application/octet-stream" } }));
  await assert.rejects(gateway.sourceWaveform(SESSION, BLOB, { sha256: SOURCE_SHA }), error =>
    error.waveformDiagnostic?.stage === "parse" && /неожиданном формате/.test(error.message));
});

test("malformed, NaN and out-of-range Float32 responses fail before peak publication", async () => {
  for (const secondPeak of [Number.NaN, -0.01, 1.01]) {
    const gateway = new AudioArchiveGateway("", async () => waveformResponse({ secondPeak }));
    await assert.rejects(gateway.sourceWaveform(SESSION, BLOB, { sha256: SOURCE_SHA }), error =>
      /[Ss]erver waveform/.test(error.message) && error.waveformDiagnostic?.stage === "validate");
  }
  const truncated = new AudioArchiveGateway("", async () => new Response(new Uint8Array(12), { status: 200, headers: {
    "Content-Type": "application/vnd.meser.waveform-f32le", "X-Meser-Waveform-Algorithm": "meser-peaks-f32le-v1",
    "X-Meser-Waveform-Peaks": "65536", "X-Meser-Waveform-Duration": "3747.648", "X-Meser-Source-SHA256": SOURCE_SHA,
    "X-Meser-Waveform-SHA256": sha(new Uint8Array(12))
  } }));
  await assert.rejects(truncated.sourceWaveform(SESSION, BLOB, { sha256: SOURCE_SHA }), /[Ss]erver waveform/);
});

test("implementation contains no Safari, iPhone or Android waveform branch", async () => {
  const { readFile } = await import("node:fs/promises");
  const files = [
    "service/frontend/scripts/audio-archive-client.mjs",
    "service/frontend/scripts/speaker-editor.mjs",
    "gateway/audio-archive/src/waveform.mjs"
  ];
  for (const file of files) {
    const source = await readFile(new URL(`../../${file}`, import.meta.url), "utf8");
    assert.doesNotMatch(source, /(?:if|switch)[^\n]*(?:navigator\.userAgent|iPhone|iPad|Safari|Android)/);
  }
});

test("Editor routes Archive peaks through the provider, commits atomically and exposes only redacted diagnostics", async () => {
  const { readFile } = await import("node:fs/promises");
  const editor = await readFile(new URL("../../service/frontend/scripts/speaker-editor.mjs", import.meta.url), "utf8");
  const html = await readFile(new URL("../../service/frontend/Audio-Editor.html", import.meta.url), "utf8");
  assert.match(editor, /if \(state\.waveformProvider\)/);
  assert.match(editor, /preparedSamples\.push\(remote\.samples\)/);
  assert.ok(editor.indexOf("tracks.forEach((track, index) => { track.samples = preparedSamples[index]; })") > editor.indexOf("for (const [index, track] of tracks.entries())"));
  assert.match(editor, /for \(const track of tracks\) track\.samples = null/);
  const diagnostics = await readFile(new URL("../../service/frontend/scripts/speaker-waveform-diagnostics.mjs", import.meta.url), "utf8");
  assert.match(editor, /safeWaveformDiagnostic\(error, \{ stage,/);
  assert.match(editor, /stage = "validate";[\s\S]*stage = "render";\s*setupPlayback\(\)/);
  assert.doesNotMatch(diagnostics, /file\.name|session\.title|downloadUrl/i);
  assert.match(html, /id="speaker-editor-diagnostics-copy"/);
  assert.match(html, /Отчёт не содержит имён, содержимого записи или данных сеанса/);
});
