import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { AudioArchiveGateway } from "../../service/frontend/scripts/audio-archive-client.mjs";

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
  assert.equal(result.duration, 3747.648); assert.equal(result.cache, "miss");
  assert.equal(requests[0].url, `/v1/source-sessions/${SESSION}/blobs/${BLOB}/waveform`);
  assert.equal(requests[0].url.includes("sha"), false); assert.equal(requests[0].options.credentials, "include");
});

test("source identity mismatch and server stage fail closed without exposing request data", async () => {
  const mismatch = new AudioArchiveGateway("", async () => waveformResponse({ sourceSha: "b".repeat(64) }));
  await assert.rejects(mismatch.sourceWaveform(SESSION, BLOB, { sha256: SOURCE_SHA }), /Проверка server waveform/);
  const failed = new AudioArchiveGateway("", async () => waveformResponse({ status: 502 }));
  await assert.rejects(failed.sourceWaveform(SESSION, BLOB, { sha256: SOURCE_SHA }), error =>
    error.status === 502 && error.waveformDiagnostic.stage === "exec" && error.waveformDiagnostic.exitStatus === 7);
});

test("malformed, NaN and out-of-range Float32 responses fail before peak publication", async () => {
  for (const secondPeak of [Number.NaN, -0.01, 1.01]) {
    const gateway = new AudioArchiveGateway("", async () => waveformResponse({ secondPeak }));
    await assert.rejects(gateway.sourceWaveform(SESSION, BLOB, { sha256: SOURCE_SHA }), /[Ss]erver waveform/);
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
  assert.match(editor, /exceptionMessage: messages\[exceptionName\]/);
  assert.doesNotMatch(editor.slice(editor.indexOf("function safeDiagnostic"), editor.indexOf("function currentDirty")), /file\.name|session\.title|cookie|csrf|downloadUrl/i);
  assert.match(html, /id="speaker-editor-diagnostics-copy"/);
  assert.match(html, /Отчёт не содержит имён, содержимого записи или данных сеанса/);
});
