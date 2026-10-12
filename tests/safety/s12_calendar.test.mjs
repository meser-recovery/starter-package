import test from 'node:test';
import assert from 'node:assert/strict';
import { moscowMonth, moscowDay } from '../../service/frontend/scripts/audio-archive-zoom.mjs';

test('S12 Moscow month/day use exact UTC boundary and ignore device timezone', () => {
  assert.equal(moscowMonth(new Date('2026-09-30T20:59:59Z')), '2026-09');
  assert.equal(moscowMonth(new Date('2026-09-30T21:00:00Z')), '2026-10');
  assert.equal(moscowDay('2026-10-04T20:59:59Z'), '2026-10-04');
  assert.equal(moscowDay('2026-10-04T21:00:00Z'), '2026-10-05');
});
