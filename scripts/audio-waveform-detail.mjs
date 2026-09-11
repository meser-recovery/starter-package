import { createWaveformReader } from './speaker-waveform.mjs';
import { drawWaveformViewport } from './audio-waveform-view.mjs';

// Detailed decoding is restricted to a small visible source-time window. One
// sequential decoder, one cached window per File; stale/detached views cannot
// receive results. No source File, edit recipe or playback state is modified.
export function createWaveformDetail({ makeReader = createWaveformReader } = {}) {
  const cache = new Map(), pending = new Map(), views = new WeakMap();
  let timer, controller, running = false, epoch = 0;
  function paint(view, detail) {
    const { canvas, duration, pps, left, width, height, dpr } = view;
    drawWaveformViewport(canvas, detail.samples, detail.duration, pps, left, width, height, dpr, detail.start);
    canvas.hidden = false;
    canvas.dataset.waveDetail = 'ready';
    canvas.dataset.detailStart = String(detail.start);
    canvas.dataset.detailDuration = String(detail.duration);
    canvas.dataset.detailBins = String(detail.samples.length);
    canvas.dataset.sourceDuration = String(duration);
  }
  async function run() {
    if (running || !pending.size) return;
    running = true;
    const generation = epoch;
    controller = new AbortController();
    const reader = makeReader(controller.signal);
    try {
      while (pending.size && generation === epoch) {
        const [file, request] = pending.entries().next().value;
        pending.delete(file);
        try {
          const cached = cache.get(file);
          if (cached?.key === request.key && (!cached.failed || Date.now() < cached.retryAfter)) {
            const view = views.get(request.canvas);
            if (!cached.failed && request.canvas.isConnected && view?.key === request.key) paint(view, cached);
            continue;
          }
          const samples = await reader.readWindow(file, request.start, request.duration);
          if (generation !== epoch) break;
          const detail = { key: request.key, start: request.start, duration: request.duration, samples };
          cache.set(file, detail);
          const view = views.get(request.canvas);
          if (request.canvas.isConnected && view?.key === request.key) paint(view, detail);
        } catch (error) {
          if (generation !== epoch) break;
          cache.set(file, { key: request.key, failed: true, retryAfter: Date.now() + 3000 });
          if (views.get(request.canvas)?.key === request.key) { request.canvas.dataset.waveDetail = 'unavailable'; request.canvas.dataset.detailError = error.message; }
        }
      }
    } finally {
      reader.dispose();
      if (generation === epoch) { running = false; controller = null; }
    }
  }
  return {
    draw(canvas, file, duration, pps, left, width, height, coarseRate) {
      const dpr = Math.max(1, Math.min(3, globalThis.devicePixelRatio || 1));
      if (!(duration > 0) || pps * dpr <= coarseRate || width / pps > 16) {
        views.delete(canvas); pending.delete(file); canvas.dataset.waveDetail = 'overview'; return;
      }
      const start = Math.max(0, Math.floor(left / pps / 8) * 8);
      const span = Math.min(32, duration - start);
      if (!(span > 0)) return;
      const key = `${start}:${span}`;
      const view = { canvas, duration, pps, left, width, height, dpr, key };
      views.set(canvas, view);
      const detail = cache.get(file);
      if (detail?.key === key && (!detail.failed || Date.now() < detail.retryAfter)) {
        if (!detail.failed) paint(view, detail);
        else canvas.dataset.waveDetail = 'unavailable';
        return;
      }
      canvas.dataset.waveDetail = 'loading';
      pending.set(file, { start, duration: span, key, canvas });
      clearTimeout(timer); timer = setTimeout(run, 180);
    },
    clear() {
      epoch++; clearTimeout(timer); controller?.abort(); controller = null;
      pending.clear(); cache.clear(); running = false;
    }
  };
}
