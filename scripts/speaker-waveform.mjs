// Preview analysis only. Does not alter source bytes or the render/DSP recipe.
const WIDTH = 1400;
const HEIGHT = 100;

export function createWaveformReader(signal) {
  let engine;
  const check = () => { if (signal?.aborted) throw new DOMException("cancelled", "AbortError"); };
  const terminate = () => { engine?.terminate(); engine = null; };
  signal?.addEventListener("abort", terminate, { once: true });

  async function nativeSamples(file) {
    const AudioContextClass = globalThis.AudioContext || globalThis.webkitAudioContext;
    if (!AudioContextClass) throw new Error("Web Audio unavailable");
    const context = new AudioContextClass();
    try {
      const buffer = await context.decodeAudioData(await file.arrayBuffer()); check();
      const data = buffer.getChannelData(0); const samples = new Float32Array(WIDTH);
      for (let x = 0; x < WIDTH; x++) {
        for (let i = Math.floor(x * data.length / WIDTH); i < Math.floor((x + 1) * data.length / WIDTH); i++) {
          samples[x] = Math.max(samples[x], Math.abs(data[i]));
        }
      }
      return samples;
    } finally { await context.close(); }
  }

  async function ffmpegSamples(file) {
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
      const code = await currentEngine.exec(["-hide_banner", "-nostats", "-xerror", "-protocol_whitelist", "file", "-i", input,
        "-filter_complex", `aformat=channel_layouts=mono,aresample=8000,showwavespic=s=${WIDTH}x${HEIGHT}:colors=white`,
        "-frames:v", "1", "-an", "-pix_fmt", "rgba", "-f", "rawvideo", output]);
      check();
      if (code !== 0) throw new Error("FFmpeg waveform decoding failed");
      const pixels = await currentEngine.readFile(output); check();
      if (pixels.length !== WIDTH * HEIGHT * 4) throw new Error("Incomplete waveform image");
      const samples = new Float32Array(WIDTH);
      for (let x = 0; x < WIDTH; x++) for (let y = 0; y < HEIGHT; y++) {
        if (pixels[(y * WIDTH + x) * 4] > 0) samples[x] = Math.max(samples[x], Math.abs(y - HEIGHT / 2) / (HEIGHT / 2));
      }
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
      return ffmpegSamples(file);
    },
    dispose() { signal?.removeEventListener("abort", terminate); terminate(); }
  };
}
