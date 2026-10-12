import test from 'node:test';
import assert from 'node:assert/strict';
import { moscowMonth, moscowDay } from '../../service/frontend/scripts/audio-archive-zoom.mjs';

test('S12 Moscow month/day use exact UTC boundary and ignore device timezone', () => {
  assert.equal(moscowMonth(new Date('2026-09-30T20:59:59Z')), '2026-09');
  assert.equal(moscowMonth(new Date('2026-09-30T21:00:00Z')), '2026-10');
  assert.equal(moscowDay('2026-10-04T20:59:59Z'), '2026-10-04');
  assert.equal(moscowDay('2026-10-04T21:00:00Z'), '2026-10-05');
});

test('S12 A15 canonical ingestion recovery UI allows only discard after deletion starts', async () => {
  const { recoveryPolicy } = await import('../../service/frontend/scripts/audio-archive-core.mjs');
  for (const uploadedParts of [1, 2]) {
    const op = { transactionId: '22222222-2222-4222-8222-222222222222', kind: 'ingestion', state: 'discarding', totalParts: 2, uploadedParts, canFinalize: false };
    assert.deepEqual(recoveryPolicy(op).actions, [['discard', 'Завершить удаление незавершённого сохранения']]);
  }
});
