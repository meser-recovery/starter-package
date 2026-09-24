const STAGES = new Set(["load", "source-reconstruction", "metadata", "ffmpeg-core-load", "engine-load",
  "write", "wasm-write", "seek-chunk", "exec", "ffmpeg-exec", "read", "wasm-read", "peak-conversion", "cleanup",
  "worker-termination", "parse", "validate", "render", "aborted"]);

function safeExceptionMessage(error, source) {
  const raw = typeof source.exceptionMessage === "string" ? source.exceptionMessage :
    typeof error?.cause?.message === "string" ? error.cause.message : error?.message;
  if (typeof raw !== "string") return null;
  const message = raw.replace(/\s+/g, " ").trim();
  if (!message) return null;
  // Browser exceptions are useful, but a fetch/DOM error may contain a source
  // path, filename or credential. Do not place those in the copyable report.
  if (message.length > 200 || /https?:|[\\/@]|\b(?:cookie|csrf|token|password|secret|bearer)\b|\b[0-9a-f]{32,}\b|\.(?:m4a|mp3|wav)\b/i.test(message)) {
    return "Error details redacted";
  }
  return message;
}

export function safeWaveformDiagnostic(error, context = {}) {
  const source = error?.waveformDiagnostic || {};
  const stage = STAGES.has(source.stage) ? source.stage : error?.name === "AbortError" ? "aborted" :
    STAGES.has(context.stage) ? context.stage : "load";
  const rawName = String(source.exceptionType || error?.cause?.name || error?.name || "Error");
  const exceptionName = /^[A-Za-z][A-Za-z0-9_.-]{0,63}$/.test(rawName) ? rawName : "Error";
  return Object.freeze({
    stage,
    trackIndex: Number.isInteger(context.trackIndex) ? context.trackIndex : Number.isInteger(source.trackIndex) ? source.trackIndex : null,
    sourceBytes: Number.isSafeInteger(context.sourceBytes) ? context.sourceBytes : Number.isSafeInteger(source.sourceBytes) ? source.sourceBytes : null,
    chunkIndex: Number.isInteger(source.chunkIndex) ? source.chunkIndex : 0,
    chunkCount: Number.isInteger(source.chunkCount) ? source.chunkCount : 0,
    elapsedMs: Number.isFinite(context.elapsedMs) ? Math.max(0, Math.round(context.elapsedMs)) : Number.isFinite(source.elapsedMs) ? source.elapsedMs : null,
    exceptionName,
    exceptionMessage: safeExceptionMessage(error, source),
    exitStatus: Number.isInteger(source.exitStatus) ? source.exitStatus : Number.isInteger(source.exitCode) ? source.exitCode : null,
    expectedOutputBytes: Number.isSafeInteger(source.expectedOutputBytes) ? source.expectedOutputBytes : null
  });
}
