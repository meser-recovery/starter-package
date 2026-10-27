import test from 'node:test';
import assert from 'node:assert/strict';
import { moscowMonth, moscowDay } from '../../service/frontend/scripts/audio-archive-zoom.mjs';
import { AudioArchiveGateway } from '../../service/frontend/scripts/audio-archive-client.mjs';

test('S12 expiry ownership follows the real Gateway invalidation-before-throw, not UI generations', async () => {
  const gateway = new AudioArchiveGateway('', async () => new Response(JSON.stringify({ error: 'expired' }), { status: 401, headers: { 'Content-Type': 'application/json' } }));
  const generation = gateway.authGeneration;
  const results = await Promise.allSettled([gateway.request('/usage'), gateway.request('/usage')]);
  const error = results[0].reason;
  assert.equal(error.status, 401);
  assert.equal(results[1].reason, error, 'coalesced catches receive the same expiry');
  assert.equal(gateway.authGeneration, generation + 1, '401 already invalidates before UI catch');
  assert.equal(gateway.isCurrentAuthenticationFailure(error, generation), true);
  assert.equal(gateway.isCurrentAuthenticationFailure(error, generation + 1), false);
  gateway.invalidateAuthentication(); // existing clearSession path
  assert.equal(gateway.isCurrentAuthenticationFailure(error, generation), false, 'repeated expiry is no longer current');
  const direct = Object.assign(new Error('direct file expired'), { status: 401 });
  assert.equal(gateway.isCurrentAuthenticationFailure(direct, gateway.authGeneration), true);
  assert.equal(gateway.isCurrentAuthenticationFailure(direct, generation), false);
});

test('S12 a thrown 401 is no longer owned after a real successful replacement login', async () => {
  const gateway = new AudioArchiveGateway('', async url => new Response(JSON.stringify(url === '/old' ? { error: 'expired' } : { authenticated: true, csrfToken: 'replacement' }), { status: url === '/old' ? 401 : 200, headers: { 'Content-Type': 'application/json' } }));
  const generation = gateway.authGeneration;
  const error = await gateway.request('/old').catch(error => error);
  assert.equal(gateway.isCurrentAuthenticationFailure(error, generation), true);
  await gateway.login('synthetic');
  assert.equal(gateway.isCurrentAuthenticationFailure(error, generation), false);
  assert.equal(gateway.csrfToken, 'replacement');
});

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
