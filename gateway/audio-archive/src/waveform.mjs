import { createHash, randomUUID } from "node:crypto";
import { constants, createWriteStream } from "node:fs";
import { chmod, lstat, mkdir, open, readdir, rename, rm, stat } from "node:fs/promises";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { join } from "node:path";
import { pipeline } from "node:stream/promises";
import { Readable, Transform } from "node:stream";

export const WAVEFORM_ALGORITHM = "meser-peaks-f32le-v1";
export const WAVEFORM_PEAK_COUNT = 65_536;
export const WAVEFORM_BODY_BYTES = WAVEFORM_PEAK_COUNT * 4;
export const WAVEFORM_MAX_SOURCE_BYTES = 500 * 1024 * 1024;
export const WAVEFORM_MAX_DURATION_SECONDS = 8 * 60 * 60;
export const WAVEFORM_MAX_ACTIVE_PROCESSES = 1;
export const WAVEFORM_MAX_QUEUE = 4;
export const WAVEFORM_JOB_TIMEOUT_MS = 12 * 60 * 1000;
export const WAVEFORM_CACHE_MAX_BYTES = 256 * 1024 * 1024;
const MAX_STDERR_BYTES = 32 * 1024;

export class WaveformError extends Error {
  constructor(message, { status = 502, stage = "load", cause, exitStatus = null } = {}) {
    super(message, cause === undefined ? undefined : { cause });
    this.name = "WaveformError";
    this.status = status;
    this.stage = stage;
    this.exitStatus = Number.isInteger(exitStatus) ? exitStatus : null;
  }
}

const abortError = (stage = "aborted") => Object.assign(new WaveformError("Waveform request was cancelled", { status: 499, stage }), { name: "AbortError" });
const throwIfAborted = (signal, stage) => { if (signal?.aborted) throw abortError(stage); };
const digest = bytes => createHash("sha256").update(bytes).digest("hex");
const safeKey = sourceSha256 => `${WAVEFORM_ALGORITHM}-${sourceSha256}-${WAVEFORM_PEAK_COUNT}`;

function cacheHeader(source, body) {
  return Buffer.from(`${JSON.stringify({
    schemaVersion: 1,
    algorithm: WAVEFORM_ALGORITHM,
    sourceSha256: source.sha256,
    sourceBytes: source.sizeBytes,
    durationSeconds: source.durationSeconds,
    peakCount: WAVEFORM_PEAK_COUNT,
    format: "float32",
    endianness: "little",
    minimum: 0,
    maximum: 1,
    bodyBytes: body.byteLength,
    resultSha256: digest(body)
  })}\n`);
}

function parseCache(bytes, source) {
  const newline = bytes.indexOf(10);
  if (newline < 1 || newline > 4096) throw new WaveformError("Cached waveform header is invalid", { stage: "read" });
  let header;
  try { header = JSON.parse(bytes.subarray(0, newline).toString("utf8")); } catch { throw new WaveformError("Cached waveform header is invalid", { stage: "read" }); }
  const body = bytes.subarray(newline + 1);
  if (header.schemaVersion !== 1 || header.algorithm !== WAVEFORM_ALGORITHM || header.sourceSha256 !== source.sha256 ||
      header.sourceBytes !== source.sizeBytes || header.peakCount !== WAVEFORM_PEAK_COUNT || header.format !== "float32" ||
      header.endianness !== "little" || header.minimum !== 0 || header.maximum !== 1 || header.bodyBytes !== WAVEFORM_BODY_BYTES ||
      body.byteLength !== WAVEFORM_BODY_BYTES || header.resultSha256 !== digest(body) || !(header.durationSeconds > 0) ||
      header.durationSeconds > WAVEFORM_MAX_DURATION_SECONDS) {
    throw new WaveformError("Cached waveform integrity check failed", { stage: "read" });
  }
  validatePeakBody(body);
  return Object.freeze({ body: Buffer.from(body), ...header, cache: "hit" });
}

function validatePeakBody(body) {
  if (!(body instanceof Uint8Array) || body.byteLength !== WAVEFORM_BODY_BYTES) {
    throw new WaveformError("Waveform peak body has an invalid size", { stage: "peak-conversion" });
  }
  const bytes = Buffer.from(body.buffer, body.byteOffset, body.byteLength);
  for (let offset = 0; offset < bytes.byteLength; offset += 4) {
    const value = bytes.readFloatLE(offset);
    if (!Number.isFinite(value) || value < 0 || value > 1) {
      throw new WaveformError("Waveform peak body contains an invalid value", { stage: "peak-conversion" });
    }
  }
}

class DigestingLimit extends Transform {
  constructor(expected, maximum, signal) {
    super({ highWaterMark: 64 * 1024 });
    this.expected = expected; this.maximum = maximum; this.signal = signal;
    this.bytes = 0; this.hash = createHash("sha256");
  }
  _transform(chunk, _encoding, callback) {
    try {
      throwIfAborted(this.signal, "source-reconstruction");
      this.bytes += chunk.byteLength;
      if (this.bytes > this.maximum || this.bytes > this.expected.sizeBytes) throw new WaveformError("Waveform source exceeds its declared limit", { status: 413, stage: "source-reconstruction" });
      this.hash.update(chunk); callback(null, chunk);
    } catch (error) { callback(error); }
  }
  verify() {
    if (this.bytes !== this.expected.sizeBytes || this.hash.digest("hex") !== this.expected.sha256) {
      throw new WaveformError("Waveform source integrity check failed", { status: 409, stage: "source-reconstruction" });
    }
  }
}

async function streamPartToFile(response, part, output, combined, signal) {
  if (!response?.ok || !response.body) throw new WaveformError("Archive source part is unavailable", { stage: "source-reconstruction" });
  const declared = Number(response.headers.get("content-length"));
  if (Number.isFinite(declared) && declared !== part.sizeBytes) throw new WaveformError("Archive source part size is invalid", { stage: "source-reconstruction" });
  const partCheck = new DigestingLimit(part, part.sizeBytes, signal);
  const combinedTap = new Transform({ highWaterMark: 64 * 1024, transform(chunk, _encoding, callback) {
    try { combined.update(chunk); callback(null, chunk); } catch (error) { callback(error); }
  } });
  await pipeline(Readable.fromWeb(response.body), partCheck, combinedTap, output, { end: false, signal });
  partCheck.verify();
}

async function reconstructSource(source, path, openPart, signal) {
  if (!Number.isSafeInteger(source.sizeBytes) || source.sizeBytes < 1 || source.sizeBytes > WAVEFORM_MAX_SOURCE_BYTES) {
    throw new WaveformError("Waveform source size is outside the allowed range", { status: 413, stage: "source-reconstruction" });
  }
  const output = createWriteStream(path, { flags: "wx", mode: 0o600, highWaterMark: 64 * 1024 });
  const combined = createHash("sha256"); let total = 0;
  try {
    for (const part of source.parts) {
      throwIfAborted(signal, "source-reconstruction");
      let response;
      try { response = await openPart(part.assetId, signal); }
      catch (error) {
        if (error instanceof WaveformError || error?.name === "AbortError") throw error;
        throw new WaveformError("Archive source part could not be opened", { stage: "source-reconstruction", cause: error });
      }
      await streamPartToFile(response, part, output, combined, signal);
      total += part.sizeBytes;
      if (total > WAVEFORM_MAX_SOURCE_BYTES) throw new WaveformError("Waveform source exceeds the size limit", { status: 413, stage: "source-reconstruction" });
    }
    output.end(); await once(output, "close");
    if (total !== source.sizeBytes || combined.digest("hex") !== source.sha256) {
      throw new WaveformError("Combined waveform source integrity check failed", { status: 409, stage: "source-reconstruction" });
    }
  } catch (error) {
    const closed = output.closed ? Promise.resolve() : new Promise(resolve => output.once("close", resolve));
    output.on("error", () => {});
    output.destroy();
    await closed;
    if (error instanceof WaveformError || error?.name === "AbortError") throw error;
    throw new WaveformError("Temporary waveform source could not be written", { stage: "write", cause: error });
  }
}

function runProcess(command, args, { signal, timeoutMs, stage, consumeStdout }) {
  return new Promise((resolve, reject) => {
    throwIfAborted(signal, stage);
    const child = spawn(command, args, { stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
    let stderr = ""; let settled = false; let forcedError = null; let consumerError = null;
    const kill = () => { if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL"); };
    const timer = setTimeout(() => { forcedError ||= new WaveformError("Native waveform process timed out", { stage }); kill(); }, timeoutMs);
    const aborted = () => { forcedError ||= abortError(stage); kill(); };
    const finish = (error, value) => {
      if (settled) return; settled = true; clearTimeout(timer); signal?.removeEventListener("abort", aborted);
      error ? reject(error) : resolve(value);
    };
    signal?.addEventListener("abort", aborted, { once: true });
    child.stderr.on("data", chunk => { if (stderr.length < MAX_STDERR_BYTES) stderr += chunk.toString("utf8", 0, MAX_STDERR_BYTES - stderr.length); });
    const consumer = Promise.resolve().then(() => consumeStdout(child.stdout));
    consumer.catch(error => {
      consumerError = error instanceof WaveformError ? error : new WaveformError("Native waveform output failed", { stage, cause: error });
      kill();
    });
    child.on("error", error => finish(new WaveformError("Native waveform process could not start", { stage, cause: error })));
    child.on("close", async code => {
      try {
        const value = await consumer;
        if (forcedError) return finish(forcedError);
        if (consumerError) return finish(consumerError);
        if (code !== 0) return finish(new WaveformError("Native waveform process failed", { stage, exitStatus: code }));
        finish(null, value);
      } catch (error) { finish(forcedError || consumerError || (error instanceof WaveformError ? error : new WaveformError("Native waveform output failed", { stage, cause: error }))); }
    });
  });
}

async function probeDuration(path, options, signal) {
  let bytes = 0; const chunks = [];
  await runProcess(options.ffprobePath, ["-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path], {
    signal, timeoutMs: options.timeoutMs, stage: "metadata", consumeStdout: async stream => {
      for await (const chunk of stream) { bytes += chunk.byteLength; if (bytes > 4096) throw new WaveformError("Native metadata output exceeded its limit", { stage: "metadata" }); chunks.push(chunk); }
    }
  });
  const durationSeconds = Number(Buffer.concat(chunks).toString("utf8").trim());
  if (!(durationSeconds > 0) || durationSeconds > WAVEFORM_MAX_DURATION_SECONDS) throw new WaveformError("Waveform duration is outside the allowed range", { status: 413, stage: "metadata" });
  return durationSeconds;
}

async function nativePeaks(path, durationSeconds, options, signal) {
  const totalSamples = Math.max(1, Math.round(durationSeconds * 48_000));
  const peaks = new Float32Array(WAVEFORM_PEAK_COUNT); let sampleIndex = 0; let remainder = Buffer.alloc(0);
  await runProcess(options.ffmpegPath, ["-hide_banner", "-nostats", "-xerror", "-i", path, "-vn", "-ac", "1", "-ar", "48000", "-f", "f32le", "pipe:1"], {
    signal, timeoutMs: options.timeoutMs, stage: "exec", consumeStdout: async stream => {
      for await (const chunk of stream) {
        throwIfAborted(signal, "exec");
        const data = remainder.length ? Buffer.concat([remainder, chunk]) : chunk;
        const complete = data.byteLength - data.byteLength % 4;
        for (let offset = 0; offset < complete; offset += 4) {
          const value = Math.min(1, Math.abs(data.readFloatLE(offset)));
          const bin = Math.min(WAVEFORM_PEAK_COUNT - 1, Math.floor(sampleIndex * WAVEFORM_PEAK_COUNT / totalSamples));
          if (Number.isFinite(value) && value > peaks[bin]) peaks[bin] = value;
          sampleIndex++;
        }
        remainder = data.subarray(complete);
      }
      if (remainder.length) throw new WaveformError("Native waveform output was truncated", { stage: "read" });
    }
  });
  if (sampleIndex < 1) throw new WaveformError("Native waveform output was empty", { stage: "read" });
  const body = Buffer.allocUnsafe(WAVEFORM_BODY_BYTES);
  for (let index = 0; index < peaks.length; index++) body.writeFloatLE(peaks[index], index * 4);
  return body;
}

export class WaveformService {
  constructor({ resolveSource, openPart, cacheDir = "/var/cache/meser-waveforms", ffmpegPath = "/usr/bin/ffmpeg",
    ffprobePath = "/usr/bin/ffprobe", timeoutMs = WAVEFORM_JOB_TIMEOUT_MS, cacheMaxBytes = WAVEFORM_CACHE_MAX_BYTES, generate = null } = {}) {
    if (typeof resolveSource !== "function" || typeof openPart !== "function") throw new Error("Waveform source adapters are required");
    this.resolveSource = resolveSource; this.openPart = openPart; this.cacheDir = cacheDir;
    if (!Number.isSafeInteger(cacheMaxBytes) || cacheMaxBytes < WAVEFORM_BODY_BYTES + 4096) throw new Error("Waveform cache limit is invalid");
    this.options = { ffmpegPath, ffprobePath, timeoutMs }; this.cacheMaxBytes = cacheMaxBytes; this.generate = generate;
    this.inFlight = new Map(); this.queue = []; this.active = 0; this.closed = false;
  }

  async initialize() {
    await mkdir(this.cacheDir, { recursive: true, mode: 0o770 });
    const cacheInfo = await lstat(this.cacheDir);
    if (!cacheInfo.isDirectory() || cacheInfo.isSymbolicLink()) throw new WaveformError("Waveform cache directory is unsafe", { status: 503, stage: "load" });
    if (cacheInfo.uid === process.getuid?.()) await chmod(this.cacheDir, 0o770);
    else if (cacheInfo.uid !== 0 || cacheInfo.gid !== 0 || (cacheInfo.mode & 0o777) !== 0o770 ||
      ![process.getgid?.(), ...(process.getgroups?.() || [])].includes(0)) {
      throw new WaveformError("Waveform cache directory ownership or mode is unsafe", { status: 503, stage: "load" });
    }
    for (const name of await readdir(this.cacheDir)) {
      if (name.startsWith(".") && (name.endsWith(".source") || name.endsWith(".tmp"))) {
        await rm(join(this.cacheDir, name), { force: true });
      }
    }
  }

  async readCache(key, source) {
    const path = join(this.cacheDir, `${key}.waveform`);
    try {
      const info = await stat(path); if (!info.isFile() || info.isSymbolicLink()) throw new Error("unsafe cache entry");
      const handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
      try {
        if (info.size > WAVEFORM_BODY_BYTES + 4096) throw new Error("oversized cache entry");
        return parseCache(await handle.readFile(), source);
      } finally { await handle.close(); }
    } catch (error) {
      if (error?.code !== "ENOENT") await rm(path, { force: true });
      return null;
    }
  }

  async publishCache(key, source, body) {
    const target = join(this.cacheDir, `${key}.waveform`), temporary = join(this.cacheDir, `.${key}.${randomUUID()}.tmp`);
    const bytes = Buffer.concat([cacheHeader(source, body), body]);
    let published = false;
    try {
      const handle = await open(temporary, "wx", 0o600);
      try { await handle.writeFile(bytes); await handle.sync(); } finally { await handle.close(); }
      await rename(temporary, target); published = true; await chmod(target, 0o600); await this.evict();
      return parseCache(bytes, source);
    } finally {
      if (!published) await rm(temporary, { force: true });
    }
  }

  async evict() {
    const entries = [];
    for (const name of (await readdir(this.cacheDir)).sort()) {
      if (!name.endsWith(".waveform")) continue;
      const path = join(this.cacheDir, name); const info = await stat(path);
      if (info.isFile() && !info.isSymbolicLink()) entries.push({ path, name, size: info.size, mtime: info.mtimeMs });
    }
    let total = entries.reduce((sum, item) => sum + item.size, 0);
    entries.sort((a, b) => a.mtime - b.mtime || a.name.localeCompare(b.name));
    for (const item of entries) if (total > this.cacheMaxBytes) { await rm(item.path, { force: true }); total -= item.size; }
  }

  pump() {
    while (!this.closed && this.active < WAVEFORM_MAX_ACTIVE_PROCESSES && this.queue.length) {
      const job = this.queue.shift(); this.active++; job.started = true;
      void this.run(job).then(job.resolve, job.reject).finally(() => {
        this.active--; this.inFlight.delete(job.key); this.pump();
      }).catch(() => {});
    }
  }

  async run(job) {
    const temp = join(this.cacheDir, `.${job.key}.${randomUUID()}.source`);
    let primary = null; let result = null; let cleanupFailure = null;
    try {
      await reconstructSource(job.source, temp, this.openPart, job.controller.signal);
      throwIfAborted(job.controller.signal, "aborted");
      const generated = this.generate ? await this.generate({ path: temp, source: job.source, signal: job.controller.signal }) : await (async () => {
        const durationSeconds = await probeDuration(temp, this.options, job.controller.signal);
        const body = await nativePeaks(temp, durationSeconds, this.options, job.controller.signal);
        return { durationSeconds, body };
      })();
      if (!(generated.body instanceof Uint8Array) || generated.body.byteLength !== WAVEFORM_BODY_BYTES ||
          !(generated.durationSeconds > 0) || generated.durationSeconds > WAVEFORM_MAX_DURATION_SECONDS) {
        throw new WaveformError("Generated waveform did not satisfy the peak contract", { stage: "read" });
      }
      validatePeakBody(generated.body);
      result = Object.freeze({ ...(await this.publishCache(job.key, { ...job.source, durationSeconds: generated.durationSeconds }, Buffer.from(generated.body))), cache: "miss" });
    } catch (error) {
      primary = error instanceof WaveformError || error?.name === "AbortError"
        ? error : new WaveformError("Waveform generation failed", { stage: "exec", cause: error });
    }
    finally {
      try { await rm(temp, { force: true }); }
      catch (error) { cleanupFailure = new WaveformError("Temporary waveform source cleanup failed", { stage: "cleanup", cause: error }); }
    }
    if (primary) throw primary;
    if (cleanupFailure) throw cleanupFailure;
    return result;
  }

  subscribe(job, signal) {
    job.subscribers++;
    return new Promise((resolve, reject) => {
      let done = false;
      const detach = () => {
        if (done) return; done = true; signal?.removeEventListener("abort", aborted); job.subscribers--;
        if (job.subscribers === 0) job.controller.abort();
      };
      const aborted = () => { detach(); reject(abortError()); };
      signal?.addEventListener("abort", aborted, { once: true });
      if (signal?.aborted) return aborted();
      job.promise.then(value => { if (!done) { detach(); resolve(value); } }, error => { if (!done) { detach(); reject(error); } });
    });
  }

  async get(sessionId, blobId, signal) {
    if (this.closed) throw new WaveformError("Waveform service is stopping", { status: 503, stage: "load" });
    throwIfAborted(signal, "load");
    const source = await this.resolveSource(sessionId, blobId);
    if (!/^[0-9a-f]{64}$/.test(source.sha256)) throw new WaveformError("Canonical source identity is invalid", { status: 409, stage: "load" });
    const key = safeKey(source.sha256);
    const cached = await this.readCache(key, source); if (cached) return cached;
    let job = this.inFlight.get(key);
    if (!job) {
      if (this.queue.length >= WAVEFORM_MAX_QUEUE) throw new WaveformError("Waveform queue is full", { status: 503, stage: "load" });
      const controller = new AbortController();
      job = { key, source, controller, subscribers: 0, started: false };
      job.promise = new Promise((resolve, reject) => Object.assign(job, { resolve, reject }));
      this.inFlight.set(key, job); this.queue.push(job); this.pump();
    }
    return this.subscribe(job, signal);
  }

  async close() {
    this.closed = true;
    for (const job of this.inFlight.values()) job.controller.abort();
    await Promise.allSettled([...this.inFlight.values()].map(job => job.promise));
    for (const name of await readdir(this.cacheDir).catch(() => [])) if (name.startsWith(".") && (name.endsWith(".source") || name.endsWith(".tmp"))) await rm(join(this.cacheDir, name), { force: true });
  }
}

export function waveformResponse(result) {
  return new Response(result.body, { status: 200, headers: {
    "Content-Type": "application/vnd.meser.waveform-f32le",
    "Content-Length": String(result.body.byteLength),
    "X-Meser-Waveform-Algorithm": result.algorithm,
    "X-Meser-Waveform-Peaks": String(result.peakCount),
    "X-Meser-Waveform-Duration": String(result.durationSeconds),
    "X-Meser-Source-SHA256": result.sourceSha256,
    "X-Meser-Waveform-SHA256": result.resultSha256,
    "X-Meser-Waveform-Cache": result.cache,
    "Cache-Control": "no-store"
  } });
}
