// Preview analysis only. Does not alter source bytes or the render/DSP recipe.
// 256 KiB of retained peaks per track; roughly 57 ms per bin for a 62-minute
// recording. The decoder's temporary image is released after extraction.
const WIDTH = 65536;
const HEIGHT = 100;
import { waveformImageSpec } from './audio-waveform-image.mjs';

export function createWaveformReader(signal, sharedEngine = null) {
  let engine = sharedEngine;
  const check = () => { if (signal?.aborted) throw new DOMException("cancelled", "AbortError"); };
  const terminate = () => { if (!sharedEngine) engine?.terminate(); engine = null; };
  signal?.addEventListener("abort", terminate, { once: true });

  async function nativeSamples(file) {
    const AudioContextClass = globalThis.AudioContext || globalThis.webkitAudioContext;
    if (!AudioContextClass) throw new Error("Web Audio unavailable");
    const context = new AudioContextClass();
    try {
      const buffer = await context.decodeAudioData(await file.arrayBuffer()); check();
      const samples = new Float32Array(WIDTH);
      for (let channel = 0; channel < buffer.numberOfChannels; channel++) {
        const data = buffer.getChannelData(channel);
        for (let x = 0; x < WIDTH; x++) {
          for (let i = Math.floor(x * data.length / WIDTH); i < Math.min(data.length, Math.max(Math.floor(x * data.length / WIDTH) + 1, Math.floor((x + 1) * data.length / WIDTH))); i++) {
            samples[x] = Math.max(samples[x], Math.abs(data[i]));
          }
        }
      }
      samples.sampleRate = WIDTH / buffer.duration;
      return samples;
    } finally { await context.close(); }
  }

  async function ffmpegSamples(file, duration, start = null) {
    // All detail windows share a 0.5ms grid, including the final short window.
    // Shifting the cached window must not regroup the samples under a word.
    const width = start === null ? Math.min(WIDTH, Math.max(1, Math.floor(duration * 4000))) : Math.max(1, Math.ceil(duration * 2000));
    const spec = waveformImageSpec(duration, width, HEIGHT);
    if (!engine) {
      const { FFmpeg } = await import("../vendor/ffmpeg/ffmpeg/index.js"); check();
      engine = new FFmpeg();
      await engine.load({ coreURL: new URL("../vendor/ffmpeg/core/ffmpeg-core.js", import.meta.url).href,
        wasmURL: new URL("../vendor/ffmpeg/core/ffmpeg-core.wasm", import.meta.url).href });
    }
    check();
    const currentEngine = engine;
    const input = "speaker-waveform-input", output = "speaker-waveform.rgba";
    try {
      await currentEngine.writeFile(input, new Uint8Array(await file.arrayBuffer())); check();
      // A fixed-size image avoids retaining an hour of decoded PCM in Web Audio.
      const code = await currentEngine.exec(["-hide_banner", "-nostats", "-xerror", "-protocol_whitelist", "file", ...(start === null ? [] : ["-ss", String(start), "-t", String(duration)]), "-i", input,
        "-filter_complex", spec.filter,
        "-frames:v", "1", "-an", "-pix_fmt", "rgba", "-f", "rawvideo", output]);
      check();
      if (code !== 0) throw new Error("FFmpeg waveform decoding failed");
      const pixels = await currentEngine.readFile(output); check();
      if (pixels.length !== width * HEIGHT * 4) throw new Error("Incomplete waveform image");
      const samples = new Float32Array(width);
      for (let x = 0; x < width; x++) for (let y = 0; y < HEIGHT; y++) {
        if (pixels[(y * width + x) * 4] > 0) samples[x] = Math.max(samples[x], Math.abs(y - HEIGHT / 2) / (HEIGHT / 2));
      }
      samples.sampleRate = spec.sampleRate;
      return samples;
    } finally {
      if (engine === currentEngine) {
        for (const path of [input, output]) { try { await currentEngine.deleteFile(path); } catch { /* May not have been written. */ } }
      }
    }
  }

  return {
    async read(file, duration) {
      check();
      // Short clips retain the fast native path. Long recordings and unsupported
      // native codecs use the same bundled decoder as Announcement, sequentially.
      if (Number.isFinite(duration) && duration <= 120) {
        try { return await nativeSamples(file); } catch { check(); }
      }
      return ffmpegSamples(file, duration);
    },
    async readWindow(file, start, duration) {
      check();
      if (!Number.isFinite(start) || start < 0 || !(duration > 0) || duration > 32) throw new Error("Invalid waveform window");
      return ffmpegSamples(file, duration, start);
    },
    dispose() { signal?.removeEventListener("abort", terminate); terminate(); }
  };
}
