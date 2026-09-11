import test from 'node:test';
import assert from 'node:assert/strict';
import { drawWaveformViewport } from '../../scripts/audio-waveform-view.mjs';
import { waveformImageSpec } from '../../scripts/audio-waveform-image.mjs';
function canvas() {
  const fills = []; const context = { fillRect(...args) { fills.push(args); } };
  return { style: {}, fills, getContext: () => context };
}
test('FFmpeg columns retain their actual sample clock, including padded final windows', () => {
  for (const duration of [32, 17.3, 9.37, 129.37, 3747]) {
    const width = Math.min(65536, Math.floor(duration * 4000));
    const spec = waveformImageSpec(duration, width, 100);
    assert.ok(spec.duration >= duration && spec.duration - duration < width / 48000);
    assert.ok(Math.abs(spec.duration * spec.sampleRate - width) < 1e-8);
    assert.match(spec.filter, /scale=lin:filter=peak:draw=full/);
    const samples = new Float32Array(width); samples.sampleRate = spec.sampleRate;
    const onset = Math.min(2.5, duration / 2);
    samples[Math.floor(onset * spec.sampleRate)] = .25;
    const c = canvas();
    drawWaveformViewport(c, samples, duration, 1000, (onset - .1) * 1000, 200, 100, 2, 0);
    const ink = c.fills.slice(1).filter(r => r[3] > 2);
    assert.ok(ink.length > 0);
    const drawnOnset = onset - .1 + ink[0][0] / 2000;
    assert.ok(Math.abs(drawnOnset - onset) <= 1 / spec.sampleRate + .001);
    assert.equal(Math.max(...ink.map(r => r[3])), 46);
  }
});
test('visible bitmap is Retina sharp and bounded by viewport, not full recording width', () => {
  const c = canvas();
  drawWaveformViewport(c, new Float32Array(65536).fill(.5), 3600, 100, 100000, 900, 112, 2);
  assert.equal(c.width, 1800); assert.equal(c.height, 224);
  assert.equal(c.style.width, '900px'); assert.equal(c.style.left, '100000px');
  assert.equal(c.fills.length, 1801);
});
test('zoomed-out bins retain narrow peaks rather than subsampling them away', () => {
  const c = canvas(), samples = new Float32Array(1000); samples[79] = 1;
  drawWaveformViewport(c, samples, 10, 1, 0, 10, 100, 1);
  assert.deepEqual(c.fills[1], [0, 4, 1, 92]);
  assert.equal(c.fills[2][3], 1);
});
test('panning and zoom use source time; shorter tracks do not stretch to longest track', () => {
  const c = canvas(), samples = new Float32Array([0, .5, 1, 0]);
  drawWaveformViewport(c, samples, 4, 10, 20, 40, 100, 1);
  assert.deepEqual(c.fills[1], [0, 4, 1, 92]);
  assert.equal(c.fills.length, 21); // only two seconds remain in this track
});

test('detail window keeps absolute source time after seek, including a short final window', () => {
  const c = canvas();
  drawWaveformViewport(c, new Float32Array([0, 1, .5, 0]), .4, 1000, 80050, 500, 100, 2, 80);
  // starts 50ms into the decoded 80.0–80.4s window, peak starts at 80.1s
  assert.equal(c.fills[1][3], 1);
  assert.equal(c.fills[102][3], 184);
  assert.equal(c.fills.length, 701); // final 150ms beyond track end is blank
});

test('airy overview preserves a transient in the visual gap; word zoom remains pixel detailed', () => {
  const previous=globalThis.getComputedStyle;
  globalThis.getComputedStyle=()=>({getPropertyValue:key=>key==='--wave-bar-step'?'3':''});
  try {
    const c=canvas(),samples=new Float32Array(1000);samples[299]=1;
    drawWaveformViewport(c,samples,10,1,0,10,100,2);
    assert.deepEqual(c.fills[1],[0,8,3,184]);
    assert.equal(c.fills[2][0],6);
    drawWaveformViewport(c,samples,10,1000,0,10,100,2);
    assert.equal(c.fills.at(-1)[2],1);
  } finally { if(previous)globalThis.getComputedStyle=previous;else delete globalThis.getComputedStyle; }
});
