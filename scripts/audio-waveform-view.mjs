// Draw only the visible time window at device resolution. Never stretch a
// whole-recording canvas: its bitmap and memory stay bounded by the viewport.
const painted = new WeakMap();
export function drawWaveformViewport(canvas, samples, duration, pixelsPerSecond, left, width, height = 112, dpr = globalThis.devicePixelRatio || 1, sampleStart = 0) {
  dpr = Math.max(1, Math.min(3, dpr));
  left = Math.floor(left * dpr) / dpr;
  width = Math.max(1, Math.ceil(width)); height = Math.max(1, Math.ceil(height));
  const bitmapWidth = Math.ceil(width * dpr), bitmapHeight = Math.ceil(height * dpr);
  const theme = typeof getComputedStyle === 'function' ? getComputedStyle(canvas) : null;
  const background = theme?.getPropertyValue('--studio-bg').trim() || '#13293d';
  const color = theme?.getPropertyValue('--track-wave').trim() || theme?.getPropertyValue('--studio-wave').trim() || '#74b2e6';
  const airy = theme?.getPropertyValue('--wave-bar-step').trim();
  const key = [samples, duration, pixelsPerSecond, left, width, height, dpr, sampleStart, background, color, airy];
  const previous = painted.get(canvas);
  if (canvas.width === bitmapWidth && canvas.height === bitmapHeight && previous?.every((value, i) => value === key[i])) return;
  painted.set(canvas, key);
  if (canvas.width !== bitmapWidth) canvas.width = bitmapWidth;
  if (canvas.height !== bitmapHeight) canvas.height = bitmapHeight;
  canvas.style.width = `${width}px`; canvas.style.height = `${height}px`;
  canvas.style.left = `${left}px`;
  const context = canvas.getContext('2d');
  context.fillStyle = background; context.fillRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = color;
  const count = samples?.length || 0;
  if (!count || !(duration > 0) || !(pixelsPerSecond > 0)) return;
  const rate = samples.sampleRate || count / duration;
  // The overview uses A's fine, spaced strokes. Aggregate the whole cell,
  // including its visual gap, so short peaks cannot disappear. At word zoom
  // return to every device pixel instead of sacrificing temporal detail.
  const step = airy && pixelsPerSecond < 160 ? Math.max(1, Math.round(3 * dpr)) : 1;
  const ink = step > 1 ? 1.5 * dpr : 1;
  // The cells belong to the source timeline, not to the moving viewport.
  // Panning changes their position only, never which peaks they aggregate.
  const origin = left * dpr;
  for (let column = Math.floor(origin / step) * step; column < origin + canvas.width; column += step) {
    const x = column - origin;
    const start = column / dpr / pixelsPerSecond;
    if (start >= sampleStart + duration) break;
    const end = (column + step) / dpr / pixelsPerSecond;
    if (end <= sampleStart) continue;
    const from = Math.max(0, Math.floor((start - sampleStart) * rate + 1e-7));
    const to = Math.min(count, Math.max(from + 1, Math.ceil((end - sampleStart) * rate - 1e-7)));
    let peak = 0;
    for (let i = from; i < to; i++) peak = Math.max(peak, samples[i]);
    const amplitude = peak * canvas.height * .46;
    context.fillRect(x, canvas.height / 2 - amplitude, ink, Math.max(1, amplitude * 2));
  }
}
