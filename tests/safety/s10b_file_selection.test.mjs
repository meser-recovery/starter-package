import test from 'node:test';
import assert from 'node:assert/strict';
import { AudioFileSelection, ingestionSessionId, recordedTimestamp, validateAudioSelection } from '../../service/frontend/scripts/audio-file-selection.mjs';
import { AudioArchiveGateway } from '../../service/frontend/scripts/audio-archive-client.mjs';
import { uuidFromIdempotencyKey } from '../../gateway/audio-archive/src/validation.mjs';

const audio = (name = 'track.wav', bytes = [1]) => new File([Uint8Array.from(bytes)], name, { type: 'audio/wav' });

test('local add, replace and cancelled picker retain exact File references and order', () => {
  const first = audio('first.wav'), second = audio('second.wav'), replacement = audio('new.wav');
  const selected = new AudioFileSelection();
  assert.equal(selected.choose([first]), true);
  assert.equal(selected.choose([], 'replace'), false);
  assert.deepEqual(selected.files, [first]);
  selected.choose([second], 'add');
  assert.deepEqual(selected.files, [first, second]);
  assert.throws(() => selected.choose([audio('wrong.txt')], 'replace'));
  assert.deepEqual(selected.files, [first, second]);
  selected.choose([replacement], 'replace');
  assert.deepEqual(selected.files, [replacement]);
});

test('selection validation and optional timestamp reject invalid form values before upload', () => {
  assert.match(validateAudioSelection([]), /хотя бы одну/);
  assert.match(validateAudioSelection([audio('empty.wav', [])]), /Пустые/);
  assert.match(validateAudioSelection([audio('wrong.txt')]), /MP3/);
  assert.equal(validateAudioSelection([audio()]), '');
  assert.equal(recordedTimestamp({ value: '', validity: { valid: true } }), null);
  assert.equal(recordedTimestamp({ value: '2026-09-25T12:30', validity: { valid: true } }), new Date('2026-09-25T12:30').toISOString());
  assert.throws(() => recordedTimestamp({ value: 'bad', validity: { valid: false } }));
});

test('client derives canonical ingestion identity and finalized replay skips part writes', async () => {
  const key = 's10b-repeat-identity-123456789';
  assert.equal(await ingestionSessionId(key), uuidFromIdempotencyKey(key));
  const gateway = new AudioArchiveGateway('');
  const calls = [];
  gateway.request = async (path, options = {}) => {
    calls.push({ path, method: options.method || 'GET', body: options.body });
    if (path === '/v1/source-sessions/ingestions') return { state: 'finalized', transactionId: uuidFromIdempotencyKey(key), sessionId: uuidFromIdempotencyKey(key) };
    if (path.startsWith('/v1/source-sessions/')) return { id: uuidFromIdempotencyKey(key) };
    throw new Error(`Unexpected call: ${path}`);
  };
  const file = audio();
  const result = await gateway.ingestFiles({ files: [file], title: 'Запись', origin: 'manual', recordedAt: null, idempotencyKey: key });
  assert.equal(result.idempotent, true);
  assert.equal(result.session.id, uuidFromIdempotencyKey(key));
  assert.deepEqual(calls.map(({ method }) => method), ['POST', 'GET']);
  assert.equal(calls[0].body.origin, 'manual');
  assert.equal(calls[0].body.recordedAt, null);
  assert.equal(calls[0].body.plan.tracks[0].originalName, file.name);
});

test('lost finalization response repeats one identity and never uploads a second record', async () => {
  const key = 's10b-final-response-lost-12345', sessionId = uuidFromIdempotencyKey(key);
  const gateway = new AudioArchiveGateway('');
  const writes = [], stages = [];
  let finalized = false, lost = false;
  gateway.request = async (path, options = {}) => {
    if (options.method === 'POST' || options.method === 'PUT') writes.push({ path, body: options.body });
    if (path === '/v1/source-sessions/ingestions') return { state: finalized ? 'finalized' : 'uploading', transactionId: sessionId, sessionId };
    if (path.endsWith('/finalize')) {
      finalized = true;
      if (!lost) { lost = true; throw new TypeError('response lost'); }
      return { session: { id: sessionId } };
    }
    if (path === `/v1/source-sessions/${sessionId}`) return { id: sessionId };
    if (options.method === 'PUT') return { accepted: true };
    throw new Error(`Unexpected call: ${path}`);
  };
  const request = { files: [audio()], title: 'Запись', recordedAt: null, origin: 'manual', idempotencyKey: key };
  await assert.rejects(() => gateway.ingestFiles({ ...request, onFinalizing: () => stages.push('finalizing') }), TypeError);
  const partsAfterLoss = writes.filter(item => item.path.includes('/parts/')).length;
  const replay = await gateway.ingestFiles(request);
  assert.equal(replay.session.id, sessionId);
  assert.equal(replay.idempotent, true);
  assert.equal(writes.filter(item => item.path.includes('/parts/')).length, partsAfterLoss);
  assert.equal(writes.filter(item => item.path.endsWith('/finalize')).length, 1);
  assert.deepEqual(stages, ['finalizing']);
  assert.equal(new Set(writes.filter(item => item.path.endsWith('/ingestions')).map(item => item.body.idempotencyKey)).size, 1);
});
