// Shared visual source ruler; coordinates follow the actual waveform viewport.
export function renderSourceTimeline(id, duration, pixelsPerSecond, left = 0) {
  const ruler = document.getElementById(id);
  if (!ruler) return;
  ruler.replaceChildren();
  if (!Number.isFinite(duration) || duration <= 0 || !Number.isFinite(pixelsPerSecond) || pixelsPerSecond <= 0) return;
  const intervals = [.01, .02, .05, .1, .2, .5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600];
  const step = intervals.find(value => value * pixelsPerSecond >= 70) || 3600;
  const start = Math.max(0, Math.ceil(left / pixelsPerSecond / step) * step);
  const end = Math.min(duration, (left + ruler.clientWidth) / pixelsPerSecond);
  for (let time = start; time <= end; time += step) {
    const tick = document.createElement("span");
    const rounded = Math.round(time * 1000) / 1000;
    const minutes = Math.floor(rounded / 60), seconds = (rounded % 60).toFixed(step < 1 ? 2 : 0).padStart(step < 1 ? 5 : 2, "0");
    tick.textContent = `${minutes}:${seconds}`;
    tick.style.left = `${time * pixelsPerSecond - left}px`;
    ruler.append(tick);
  }
}
