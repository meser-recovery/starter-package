// A shared continuous peak envelope for every editor and scale. Source-anchored
// points never regroup when Follow moves. A bounded guard area lets the browser
// scroll the retained bitmap instead of clearing/repainting it every frame.
const painted = new WeakMap();
export function drawWaveformViewport(canvas, samples, duration, pixelsPerSecond, left, width, height = 112, dpr = globalThis.devicePixelRatio || 1, sampleStart = 0) {
  dpr = Math.max(1, Math.min(3, dpr));
  width = Math.max(1, Math.ceil(width)); height = Math.max(1, Math.ceil(height));
  const theme = typeof getComputedStyle === 'function' ? getComputedStyle(canvas) : null;
  const background = theme?.getPropertyValue('--studio-bg').trim() || '#13293d';
  const color = theme?.getPropertyValue('--track-wave').trim() || theme?.getPropertyValue('--studio-wave').trim() || '#74b2e6';
  const key = [samples, duration, pixelsPerSecond, width, height, dpr, sampleStart, background, color];
  const previous = painted.get(canvas);
  const sourceLeft = sampleStart * pixelsPerSecond, sourceRight = (sampleStart + duration) * pixelsPerSecond;
  const neededLeft = Math.max(sourceLeft, left), neededRight = Math.min(sourceRight, left + width);
  if (previous?.key.every((value, i) => value === key[i]) &&
      previous.left <= neededLeft && previous.right >= neededRight) return;
  const pixelOrigin = Math.max(0, Math.floor((left - 192) * dpr / 128) * 128);
  const pixelRight = Math.ceil((left + width + 192) * dpr / 128) * 128;
  const origin = pixelOrigin / dpr, right = pixelRight / dpr;
  const bitmapWidth = pixelRight - pixelOrigin, bitmapHeight = Math.ceil(height * dpr);
  if (canvas.width !== bitmapWidth) canvas.width = bitmapWidth;
  if (canvas.height !== bitmapHeight) canvas.height = bitmapHeight;
  canvas.style.width = `${right - origin}px`; canvas.style.height = `${height}px`;
  canvas.style.left = `${origin}px`;
  const context = canvas.getContext('2d');
  context.fillStyle = background; context.fillRect(0, 0, bitmapWidth, bitmapHeight);
  const count = samples?.length || 0;
  if (!count || !(duration > 0) || !(pixelsPerSecond > 0)) return;
  const rate = samples.sampleRate || count / duration;
  function contour(ink, tileLeft, tileRight) {
    const start = Math.max(Math.floor(sourceLeft), Math.floor(tileLeft) - 1);
    const end = Math.min(Math.ceil(sourceRight), Math.ceil(tileRight) + 1);
    const peaks = [];
    // One connected contour, at a fixed CSS-pixel grid, with full peak coverage.
    // Device resolution affects raster quality, never the style or source bins.
    for (let column = start; column < end; column++) {
      const from = Math.max(0, Math.floor((column / pixelsPerSecond - sampleStart) * rate + 1e-7));
      const to = Math.min(count, Math.max(from + 1, Math.ceil(((column + 1) / pixelsPerSecond - sampleStart) * rate - 1e-7)));
      let peak = 0;
      for (let i = from; i < to; i++) peak = Math.max(peak, Math.abs(samples[i]));
      peaks.push(Math.max(.5, Math.min(1, peak) * height * .46) * dpr);
    }
    if (peaks.length) {
      const mid = bitmapHeight / 2;
      ink.fillStyle = color; ink.beginPath();
      ink.moveTo((start - tileLeft) * dpr, mid - peaks[0]);
      for (let i = 0; i < peaks.length; i++) ink.lineTo((start + i + .5 - tileLeft) * dpr, mid - peaks[i]);
      ink.lineTo((end - tileLeft) * dpr, mid - peaks.at(-1));
      ink.lineTo((end - tileLeft) * dpr, mid + peaks.at(-1));
      for (let i = peaks.length - 1; i >= 0; i--) ink.lineTo((start + i + .5 - tileLeft) * dpr, mid + peaks[i]);
      ink.lineTo((start - tileLeft) * dpr, mid + peaks[0]);
      ink.closePath(); ink.fill();
    }
  }
  // Rasterize fixed source tiles. Drawing a different-length antialiased polygon
  // can change a few edge pixels even when its points match. Fixed tile shapes
  // keep those pixels identical as the viewport and detail cache move.
  if (canvas.ownerDocument) {
    const tile = canvas.ownerDocument.createElement('canvas');
    tile.width = 128; tile.height = bitmapHeight;
    const ink = tile.getContext('2d');
    for (let x = pixelOrigin; x < pixelRight; x += 128) {
      ink.clearRect(0, 0, tile.width, tile.height);
      contour(ink, x / dpr, (x + 128) / dpr);
      context.drawImage(tile, x - pixelOrigin, 0);
    }
  } else contour(context, origin, right);
  painted.set(canvas, { key, left: Math.max(origin, sourceLeft), right: Math.min(right, sourceRight) });
}
