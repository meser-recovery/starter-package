import test from "node:test";
import assert from "node:assert/strict";
import { defaultTrackColor, normalizedWheelDelta, zoomFromGesture } from "../../scripts/audio-timeline-ux.mjs";

test("track palette is deterministic through identity-preserving reorder", () => {
  const colors = Array.from({ length: 8 }, (_, index) => defaultTrackColor(index));
  assert.equal(colors[0], colors[6]);
  assert.notEqual(colors[0], colors[1]);
});

test("pinch wheel normalization respects deltaMode and stays bounded", () => {
  assert.equal(normalizedWheelDelta({ deltaY: 2, deltaMode: 1 }), 32);
  assert.equal(normalizedWheelDelta({ deltaY: 1, deltaMode: 2 }), 240);
  assert.equal(normalizedWheelDelta({ deltaY: -1000, deltaMode: 0 }), -240);
  assert.ok(zoomFromGesture(20, -100) > 20);
  assert.ok(zoomFromGesture(20, 100) < 20);
});
