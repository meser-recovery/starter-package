import { createWaveformReader } from './speaker-waveform.mjs';
import { drawWaveformViewport } from './audio-waveform-view.mjs';

// One sequential decoder and one retained source window per File. Prefetch the
// next window while the current one still covers the viewport; playback must
// not alternate between detailed and overview data at each scroll boundary.
export function createWaveformDetail({ makeReader = createWaveformReader } = {}) {
  const cache = new Map(), pending = new Map(), inFlight = new Map(), failures = new Map(), views = new WeakMap();
  let timer, controller, running = false, epoch = 0;
  const covers = (detail, view) => detail && detail.start <= view.left / view.pps &&
    detail.start + detail.duration >= Math.min(view.duration, (view.left + view.width) / view.pps) - 1e-6;
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
    timer = null;
    if (running || !pending.size) return;
    running = true;
    const generation = epoch;
    controller = new AbortController();
    const reader = makeReader(controller.signal);
    try {
      while (pending.size && generation === epoch) {
        const [file, request] = pending.entries().next().value;
        pending.delete(file); inFlight.set(file, request.key);
        try {
          const samples = await reader.readWindow(file, request.start, request.duration);
          if (generation !== epoch) break;
          const detail = { key: request.key, start: request.start, duration: request.duration, samples };
          cache.set(file, detail); failures.delete(file);
          const view = views.get(request.canvas);
          if (request.canvas.isConnected && view?.file === file && covers(detail, view)) paint(view, detail);
        } catch (error) {
          if (generation !== epoch) break;
          failures.set(file, { key: request.key, retryAfter: Date.now() + 3000 });
          const view = views.get(request.canvas);
          if (view?.key === request.key && !covers(cache.get(file), view)) {
            request.canvas.dataset.waveDetail = 'unavailable'; request.canvas.dataset.detailError = error.message;
          }
        } finally { if (generation === epoch) inFlight.delete(file); }
      }
    } finally {
      reader.dispose();
      if (generation === epoch) { running = false; controller = null; }
    }
  }
  return {
    // True means this call painted valid detail; the caller must not overwrite
    // it with an overview or hide it during an asynchronous prefetch.
    draw(canvas, file, duration, pps, left, width, height, coarseRate) {
      const dpr = Math.max(1, Math.min(3, globalThis.devicePixelRatio || 1));
      if (!(duration > 0) || pps * dpr <= coarseRate || width / pps > 16) {
        views.delete(canvas); pending.delete(file); canvas.dataset.waveDetail = 'overview'; return false;
      }
      const view = { canvas, file, duration, pps, left, width, height, dpr };
      const detail = cache.get(file), available = covers(detail, view);
      const end = Math.min(duration, (left + width) / pps);
      const prefetch = available && detail.start + detail.duration < duration && detail.start + detail.duration - end < 8;
      const start = available && !prefetch ? detail.start : Math.max(0, Math.floor(left / pps / 8) * 8);
      const span = Math.min(32, duration - start);
      if (!(span > 0)) return false;
      const key = `${start}:${span}`;
      view.key = key; views.set(canvas, view);
      if (available) paint(view, detail);
      const failure = failures.get(file);
      if (failure?.key === key && Date.now() < failure.retryAfter) {
        if (!available) canvas.dataset.waveDetail = 'unavailable';
        return Boolean(available);
      }
      if (detail?.key !== key && inFlight.get(file) !== key) {
        pending.set(file, { start, duration: span, key, canvas });
        // Do not restart the debounce on every animation frame: continuous
        // Follow used to starve decoding until playback stopped.
        if (!timer && !running) timer = setTimeout(run, available ? 0 : 180);
      }
      if (!available) canvas.dataset.waveDetail = 'loading';
      return Boolean(available);
    },
    clear() {
      epoch++; clearTimeout(timer); timer = null; controller?.abort(); controller = null;
      pending.clear(); inFlight.clear(); failures.clear(); cache.clear(); running = false;
    }
  };
}
