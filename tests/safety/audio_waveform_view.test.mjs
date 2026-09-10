import test from 'node:test';
import assert from 'node:assert/strict';
import { drawWaveformViewport } from '../../scripts/audio-waveform-view.mjs';
function canvas() {
  const fills = []; const context = { fillRect(...args) { fills.push(args); } };
  return { style: {}, fills, getContext: () => context };
}
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
