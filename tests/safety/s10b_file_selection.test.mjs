import test from 'node:test';
import assert from 'node:assert/strict';
import { AudioFileSelection, ingestionSessionId, recordedTimestamp, validateAudioSelection,
  sameFileReferences, prepareLocalIngestionSelection } from '../../service/frontend/scripts/audio-file-selection.mjs';
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

test('A to B requires protected Speaker transition before replacing sources or writing to Archive', async () => {
  for (const [a, b] of [
    [audio('A.wav', [1, 2]), audio('B.wav', [3, 4])],
    [audio('same.wav', [1, 2]), audio('same.wav', [3, 4])]
  ]) {
    if (a.name === b.name) {
      assert.equal(a.size, b.size);
      assert.notDeepEqual(new Uint8Array(await a.arrayBuffer()), new Uint8Array(await b.arrayBuffer()));
    }
    assert.equal(sameFileReferences([a], [b]), false);
    let current = [a], writes = 0, closes = 0, loads = 0;
    const controls = {
      speakerFiles: [a], currentFiles: () => current,
      closeSpeaker: async () => { closes++; return false; },
      waitForIdle: async () => {},
      loadFiles: files => { loads++; current = [...files]; }
    };
    const declined = await prepareLocalIngestionSelection([b], controls);
    assert.deepEqual(declined, { switched: false, declined: true });
    assert.equal(closes, 1); assert.equal(loads, 0); assert.equal(writes, 0);
    assert.deepEqual(current, [a]);
    controls.closeSpeaker = async () => { closes++; return true; };
    const accepted = await prepareLocalIngestionSelection([b], controls);
    assert.deepEqual(accepted, { switched: true, declined: false });
    assert.equal(closes, 2); assert.equal(loads, 1); assert.equal(writes, 0);
    assert.equal(current[0], b);
    // The caller may begin its one keyed ingestion only after B is current.
    if (sameFileReferences(current, [b])) writes++;
    assert.equal(writes, 1);
  }
});

test('unchanged Speaker File references preserve the active montage and picker cancellation is not replacement', async () => {
  const a = audio('same.wav', [1, 2]);
  let calls = 0;
  const controls = { speakerFiles: [a], currentFiles: () => [a], closeSpeaker: async () => { calls++; return true; },
    waitForIdle: async () => { calls++; }, loadFiles: () => { calls++; } };
  assert.deepEqual(await prepareLocalIngestionSelection([a], controls), { switched: false, declined: false });
  const selected = new AudioFileSelection(); selected.choose([a]);
  assert.equal(selected.choose([], 'replace'), false);
  assert.deepEqual(await prepareLocalIngestionSelection(selected.files, controls), { switched: false, declined: false });
  assert.equal(calls, 0);
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
