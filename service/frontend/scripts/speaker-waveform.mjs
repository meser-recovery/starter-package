// Preview analysis only. Does not alter source bytes or the render/DSP recipe.
// Retain the established 65,536 overview peaks, but never materialize their
// 25 MiB RGBA image at once. Long and detailed waveforms are decoded into
// deterministic, sequential chunks with a fixed output-memory ceiling.
export const WAVEFORM_SAMPLE_COUNT = 65536;
export const WAVEFORM_HEIGHT = 100;
export const WAVEFORM_CHUNK_WIDTH = 4096;
export const WAVEFORM_CHUNK_RGBA_BYTES = WAVEFORM_CHUNK_WIDTH * WAVEFORM_HEIGHT * 4;

import { waveformImageSpec } from './audio-waveform-image.mjs';

let readerSequence = 0;
const defaultNow = () => globalThis.performance?.now?.() ?? Date.now();
const safeExceptionType = error => {
  const value = String(error?.name || error?.constructor?.name || 'Error');
  return /^[A-Za-z][A-Za-z0-9_.-]{0,63}$/.test(value) ? value : 'Error';
};
const finite = value => Number.isFinite(value) ? value : null;
const decimal = value => Number(value.toFixed(9)).toString();

export class WaveformStageError extends Error {
  constructor(diagnostic, cause) {
    super(`Waveform processing failed at ${diagnostic.stage}`, cause === undefined ? undefined : { cause });
    this.name = diagnostic.stage === 'aborted' ? 'AbortError' : 'WaveformStageError';
    this.waveformDiagnostic = Object.freeze({ ...diagnostic });
  }
}

export function planWaveformChunks(duration, totalWidth, maximumWidth = WAVEFORM_CHUNK_WIDTH) {
  if (!(duration > 0) || !Number.isFinite(duration) || !Number.isInteger(totalWidth) || totalWidth < 1 ||
      !Number.isInteger(maximumWidth) || maximumWidth < 1 || maximumWidth > WAVEFORM_CHUNK_WIDTH) {
    throw new Error('Invalid waveform chunk plan');
  }
  const overview = waveformImageSpec(duration, totalWidth, WAVEFORM_HEIGHT);
  const count = Math.ceil(totalWidth / maximumWidth);
  const chunks = [];
  let previousEnd = 0;
  for (let index = 0; index < count; index++) {
    const binStart = index * maximumWidth;
    const binEnd = Math.min(totalWidth, binStart + maximumWidth);
    // Use the overview's single sample grid. Only its final chunk may contain
    // padding, exactly like the former monolithic image; intermediate chunks
    // neither stretch nor insert silence at their boundaries.
    const endSeconds = index === count - 1 ? duration : Math.min(duration, binEnd / overview.sampleRate);
    chunks.push(Object.freeze({
      index: index + 1,
      count,
      binStart,
      binEnd,
      width: binEnd - binStart,
      startSeconds: previousEnd,
      endSeconds,
      durationSeconds: endSeconds - previousEnd,
      samplesPerColumn: overview.samplesPerColumn,
      expectedOutputBytes: (binEnd - binStart) * WAVEFORM_HEIGHT * 4
    }));
    previousEnd = endSeconds;
  }
  return Object.freeze(chunks);
}

export function createWaveformReader(signal, sharedEngine = null, options = {}) {
  const now = options.now || defaultNow;
  const report = options.onDiagnostic || (value => console.error('S10A_WAVEFORM_DIAGNOSTIC', JSON.stringify(value)));
  const maximumChunkWidth = options.maximumChunkWidth || WAVEFORM_CHUNK_WIDTH;
  const readerId = ++readerSequence;
  let operationSequence = 0;
  let queue = Promise.resolve();
  let disposed = false;
  const activeEngines = new Set();

  const diagnostic = (stageName, context, started, cause, exitCode = null) => Object.freeze({
    stage: stageName,
    trackIndex: Number.isInteger(context.trackIndex) && context.trackIndex > 0 ? context.trackIndex : null,
    chunkIndex: Number.isInteger(context.chunkIndex) ? context.chunkIndex : 0,
    chunkCount: Number.isInteger(context.chunkCount) ? context.chunkCount : 0,
    durationSeconds: finite(context.durationSeconds),
    sourceBytes: Number.isSafeInteger(context.sourceBytes) && context.sourceBytes >= 0 ? context.sourceBytes : null,
    expectedOutputBytes: Number.isSafeInteger(context.expectedOutputBytes) && context.expectedOutputBytes >= 0 ? context.expectedOutputBytes : null,
    elapsedMs: Math.max(0, Math.round((now() - started) * 1000) / 1000),
    exitCode: Number.isInteger(exitCode) ? exitCode : null,
    exceptionType: cause ? safeExceptionType(cause) : null
  });
  const abortError = context => new WaveformStageError(diagnostic('aborted', context, now(),
    typeof DOMException === 'function' ? new DOMException('cancelled', 'AbortError') : Object.assign(new Error('cancelled'), { name: 'AbortError' })));
  const check = context => {
    if (disposed || signal?.aborted) throw abortError(context);
  };

  async function stage(stageName, context, task, { respectAbort = true } = {}) {
    const started = now();
    try {
      if (respectAbort) check(context);
      const value = await task();
      if (respectAbort) check(context);
      return value;
    } catch (error) {
      if (error instanceof WaveformStageError) throw error;
      const failedStage = respectAbort && (disposed || signal?.aborted) ? 'aborted' : stageName;
      throw new WaveformStageError(diagnostic(failedStage, context, started, error), error);
    }
  }

  async function loadEngine(context) {
    let instance;
    try {
      return await stage('engine-load', context, async () => {
        if (options.createEngine) instance = await options.createEngine();
        else {
          const { FFmpeg } = await import('../vendor/ffmpeg/ffmpeg/index.js');
          instance = new FFmpeg();
        }
        activeEngines.add(instance);
        await instance.load({
          coreURL: new URL('../vendor/ffmpeg/core/ffmpeg-core.js', import.meta.url).href,
          wasmURL: new URL('../vendor/ffmpeg/core/ffmpeg-core.wasm', import.meta.url).href
        });
        return instance;
      });
    } catch (error) {
      if (instance) {
        const cleanupErrors = [];
        await terminateEngine(instance, context, cleanupErrors);
        if (cleanupErrors.length) error.cleanupDiagnostics = Object.freeze(cleanupErrors.map(item => item.waveformDiagnostic));
        for (const cleanupError of cleanupErrors) report(cleanupError.waveformDiagnostic);
      }
      throw error;
    }
  }

  async function cleanupPath(engine, path, context, errors) {
    try {
      await stage('cleanup', context, () => engine.deleteFile(path), { respectAbort: false });
    } catch (error) {
      errors.push(error);
    }
  }

  async function terminateEngine(engine, context, errors) {
    if (!engine || !activeEngines.has(engine)) return;
    activeEngines.delete(engine);
    try {
      await stage('cleanup', context, () => engine.terminate(), { respectAbort: false });
    } catch (error) {
      errors.push(error);
    }
  }

  async function ffmpegSamples({ file, path, duration, sourceStart = 0, targetWidth, trackIndex }) {
    const chunks = planWaveformChunks(duration, targetWidth, maximumChunkWidth);
    const operationId = ++operationSequence;
    const input = path || `speaker-waveform-${readerId}-${operationId}-input`;
    const sourceBytes = file?.size ?? null;
    const base = { trackIndex, chunkIndex: 0, chunkCount: chunks.length, durationSeconds: duration,
      sourceBytes, expectedOutputBytes: Math.min(targetWidth, maximumChunkWidth) * WAVEFORM_HEIGHT * 4 };
    let engine = sharedEngine;
    let inputMayExist = false;
    let primary = null;
    let result = null;
    const cleanupErrors = [];
    try {
      check(base);
      if (!engine) engine = await loadEngine(base);
      else activeEngines.add(engine);
      if (file) {
        const bytes = await stage('input-read', base, async () => new Uint8Array(await file.arrayBuffer()));
        inputMayExist = true;
        await stage('wasm-write', base, () => engine.writeFile(input, bytes));
      }
      const samples = new Float32Array(targetWidth);
      for (const chunk of chunks) {
        const output = `speaker-waveform-${readerId}-${operationId}-chunk-${chunk.index}.rgba`;
        const context = { ...base, chunkIndex: chunk.index, expectedOutputBytes: chunk.expectedOutputBytes,
          durationSeconds: duration };
        let outputMayExist = false;
        let chunkFailure = null;
        try {
          const spec = waveformImageSpec(chunk.durationSeconds, chunk.width, WAVEFORM_HEIGHT, 'white', chunk.samplesPerColumn);
          const start = sourceStart + chunk.startSeconds;
          const args = ['-hide_banner', '-nostats', '-xerror', '-protocol_whitelist', 'file',
            ...(start > 0 ? ['-ss', decimal(start)] : []), '-t', decimal(chunk.durationSeconds), '-i', input,
            '-filter_complex', spec.filter, '-frames:v', '1', '-an', '-pix_fmt', 'rgba', '-f', 'rawvideo', output];
          const started = now();
          let code;
          try {
            check(context);
            outputMayExist = true;
            code = await engine.exec(args);
            check(context);
          } catch (error) {
            if (error instanceof WaveformStageError) throw error;
            const failedStage = disposed || signal?.aborted ? 'aborted' : 'ffmpeg-exec';
            throw new WaveformStageError(diagnostic(failedStage, context, started, error), error);
          }
          if (code !== 0) throw new WaveformStageError(diagnostic('ffmpeg-exec', context, started, null, code));
          const pixels = await stage('wasm-read', context, () => engine.readFile(output));
          const chunkSamples = await stage('peak-conversion', context, () => {
            if (!(pixels instanceof Uint8Array) || pixels.byteLength !== chunk.expectedOutputBytes) {
              throw new TypeError('Unexpected waveform output shape');
            }
            const peaks = new Float32Array(chunk.width);
            for (let x = 0; x < chunk.width; x++) for (let y = 0; y < WAVEFORM_HEIGHT; y++) {
              if (pixels[(y * chunk.width + x) * 4] > 0) {
                peaks[x] = Math.max(peaks[x], Math.abs(y - WAVEFORM_HEIGHT / 2) / (WAVEFORM_HEIGHT / 2));
              }
            }
            return peaks;
          });
          samples.set(chunkSamples, chunk.binStart);
        } catch (error) {
          chunkFailure = error;
        } finally {
          if (outputMayExist && engine) await cleanupPath(engine, output, context, cleanupErrors);
        }
        if (chunkFailure) throw chunkFailure;
        if (cleanupErrors.length) throw cleanupErrors[0];
      }
      check(base);
      samples.sampleRate = 48000 / chunks[0].samplesPerColumn;
      result = samples;
    } catch (error) {
      primary = error instanceof WaveformStageError ? error : new WaveformStageError(diagnostic(
        disposed || signal?.aborted ? 'aborted' : 'peak-conversion', base, now(), error), error);
    } finally {
      if (engine && inputMayExist) await cleanupPath(engine, input, base, cleanupErrors);
      if (engine && (!sharedEngine || primary)) await terminateEngine(engine, base, cleanupErrors);
      else if (engine === sharedEngine) activeEngines.delete(engine);
    }
    if (primary) {
      if (cleanupErrors.length) primary.cleanupDiagnostics = Object.freeze(cleanupErrors.map(error => error.waveformDiagnostic));
      for (const error of cleanupErrors) report(error.waveformDiagnostic);
      report(primary.waveformDiagnostic);
      throw primary;
    }
    if (cleanupErrors.length) {
      for (const error of cleanupErrors) report(error.waveformDiagnostic);
      throw cleanupErrors[0];
    }
    return result;
  }

  async function nativeSamples(file, trackIndex) {
    const context = { trackIndex, chunkIndex: 0, chunkCount: 0, durationSeconds: null,
      sourceBytes: file?.size ?? null, expectedOutputBytes: null };
    const AudioContextClass = globalThis.AudioContext || globalThis.webkitAudioContext;
    if (!AudioContextClass) throw new Error('Web Audio unavailable');
    const audioContext = new AudioContextClass();
    try {
      const buffer = await audioContext.decodeAudioData(await file.arrayBuffer()); check(context);
      const samples = new Float32Array(WAVEFORM_SAMPLE_COUNT);
      for (let channel = 0; channel < buffer.numberOfChannels; channel++) {
        const data = buffer.getChannelData(channel);
        for (let x = 0; x < WAVEFORM_SAMPLE_COUNT; x++) {
          for (let i = Math.floor(x * data.length / WAVEFORM_SAMPLE_COUNT); i < Math.min(data.length,
            Math.max(Math.floor(x * data.length / WAVEFORM_SAMPLE_COUNT) + 1, Math.floor((x + 1) * data.length / WAVEFORM_SAMPLE_COUNT))); i++) {
            samples[x] = Math.max(samples[x], Math.abs(data[i]));
          }
        }
      }
      samples.sampleRate = WAVEFORM_SAMPLE_COUNT / buffer.duration;
      return samples;
    } finally { await audioContext.close(); }
  }

  const enqueue = task => {
    const scheduled = queue.then(task, task);
    queue = scheduled.catch(() => undefined);
    return scheduled;
  };
  const stopActive = () => {
    for (const engine of [...activeEngines]) {
      activeEngines.delete(engine);
      try { engine.terminate(); } catch { /* Final cleanup preserves the primary stage. */ }
    }
  };
  signal?.addEventListener('abort', stopActive, { once: true });

  return {
    read(file, duration, metadata = {}) {
      return enqueue(async () => {
        const trackIndex = metadata.trackIndex;
        const context = { trackIndex, chunkIndex: 0, chunkCount: 0, durationSeconds: duration,
          sourceBytes: file?.size ?? null, expectedOutputBytes: WAVEFORM_CHUNK_RGBA_BYTES };
        check(context);
        if (Number.isFinite(duration) && duration <= 120) {
          try { return await nativeSamples(file, trackIndex); } catch (error) {
            if (disposed || signal?.aborted || error instanceof WaveformStageError) throw error;
          }
        }
        return ffmpegSamples({ file, duration, targetWidth: Math.min(WAVEFORM_SAMPLE_COUNT,
          Math.max(1, Math.floor(duration * 4000))), trackIndex });
      });
    },
    readWindow(file, start, duration, metadata = {}) {
      return enqueue(async () => {
        if (!Number.isFinite(start) || start < 0 || !(duration > 0) || duration > 32) throw new Error('Invalid waveform window');
        return ffmpegSamples({ file, duration, sourceStart: start,
          targetWidth: Math.max(1, Math.ceil(duration * 2000)), trackIndex: metadata.trackIndex });
      });
    },
    readPath(path, duration, metadata = {}) {
      return enqueue(async () => {
        if (!sharedEngine || typeof path !== 'string' || !path) throw new Error('Prepared waveform input is unavailable');
        return ffmpegSamples({ path, duration, targetWidth: Math.min(WAVEFORM_SAMPLE_COUNT,
          Math.max(1, Math.floor(duration * 4000))), trackIndex: metadata.trackIndex });
      });
    },
    dispose() {
      disposed = true;
      signal?.removeEventListener('abort', stopActive);
      stopActive();
    }
  };
}
