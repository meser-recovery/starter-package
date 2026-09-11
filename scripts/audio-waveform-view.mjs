// Draw only the visible time window at device resolution. Never stretch a
// whole-recording canvas: its bitmap and memory stay bounded by the viewport.
export function drawWaveformViewport(canvas, samples, duration, pixelsPerSecond, left, width, height = 112, dpr = globalThis.devicePixelRatio || 1, sampleStart = 0) {
  dpr = Math.max(1, Math.min(3, dpr));
  width = Math.max(1, Math.ceil(width)); height = Math.max(1, Math.ceil(height));
  canvas.width = Math.ceil(width * dpr); canvas.height = Math.ceil(height * dpr);
  canvas.style.width = `${width}px`; canvas.style.height = `${height}px`;
  canvas.style.left = `${left}px`;
  const context = canvas.getContext('2d');
  context.fillStyle = '#13293d'; context.fillRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = '#74b2e6';
  const count = samples?.length || 0;
  if (!count || !(duration > 0) || !(pixelsPerSecond > 0)) return;
  const rate = count / duration;
  for (let x = 0; x < canvas.width; x++) {
    const start = (left + x / dpr) / pixelsPerSecond;
    if (start >= sampleStart + duration) break;
    if (start < sampleStart) continue;
    const end = (left + (x + 1) / dpr) / pixelsPerSecond;
    const from = Math.max(0, Math.floor((start - sampleStart) * rate));
    const to = Math.min(count, Math.max(from + 1, Math.ceil((end - sampleStart) * rate)));
    let peak = 0;
    for (let i = from; i < to; i++) peak = Math.max(peak, samples[i]);
    const amplitude = peak * canvas.height * .46;
    context.fillRect(x, canvas.height / 2 - amplitude, 1, Math.max(1, amplitude * 2));
  }
}
