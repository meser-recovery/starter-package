import test from 'node:test';
import assert from 'node:assert/strict';
import { managementHarness, wav } from './archive-management-fixture.mjs';
import { localSourceContext, bindLocalPayload, ProjectSave, recordingBoundaries, setRecordingBoundary, projectProjection } from '../../../scripts/audio-project.mjs';
import { defaultSpeakerPayload, buildSpeakerFilterGraph, SpeakerHistory } from '../../../scripts/speaker-editor-core.mjs';
import { reconstructSessionTracks, reconstructTrack } from '../../../scripts/audio-archive-client.mjs';

function local() {
  const bytes = wav(), other = Buffer.from(bytes); other[100] ^= 1;
  const files = [new File([bytes], 'duplicate.wav', { type: 'audio/wav' }), new File([other], 'duplicate.wav', { type: 'audio/wav' })];
  const context = localSourceContext(files), payload = defaultSpeakerPayload(context.sourceTracks.map(t => t.trackId));
  payload.trackIds.reverse(); payload.excludedTrackIds = [payload.trackIds[1]];
  payload.trackProcessing.reverse(); payload.trackProcessing[0].enhancement = 'gentle'; payload.trackProcessing[0].compression = 'medium';
  payload.globalCuts = [{ regionId: crypto.randomUUID(), startSeconds: 0, endSeconds: .05 }];
  payload.trackSilenceRegions = [{ regionId: crypto.randomUUID(), trackId: payload.trackIds[0], startSeconds: .1, endSeconds: .2 }];
  return { files, context, payload };
}
test('S09A: local identity, reordered duplicate names, exact bytes and montage bind only to finalized canonical tracks', async () => {
  const h = await managementHarness(), { files, context, payload } = local();
  assert.equal(context.id, undefined); assert.equal(context.revision, undefined);
  assert.equal(localSourceContext([...files].reverse()).sourceTracks[0].trackId, context.sourceTracks[1].trackId);
  const writes = h.trace.length; buildSpeakerFilterGraph(payload, .5); assert.equal(h.trace.length, writes);
  const save = new ProjectSave(h.gateway), session = await save.sources(context, files);
  const bound = bindLocalPayload(context, payload, save.plan, session, .5);
  assert.equal(bound.payload.trackIds[0], session.sourceTracks[1].trackId);
  assert.equal(bound.payload.trackSilenceRegions[0].trackId, session.sourceTracks[1].trackId);
  assert.deepEqual(bound.payload.globalCuts, payload.globalCuts);
  assert.equal(bound.payload.trackProcessing[0].compression, 'medium');
  const damaged = structuredClone(session); damaged.sourceTracks[0].sha256 = '0'.repeat(64);
  assert.throws(() => bindLocalPayload(context, payload, save.plan, damaged, .5));
  const saved = await save.save(session, null, bound.payload);
  const projection = projectProjection(saved.session, saved.draft); assert.equal(projection.savedAt, saved.draft.savedAt);
  assert.equal(projectProjection(session, saved.draft), null);
  const restored = await reconstructSessionTracks(saved.session, h.gateway.sourcePartFetch(saved.session));
  for (let i = 0; i < files.length; i++) assert.deepEqual(await restored[i].arrayBuffer(), await files[i].arrayBuffer());
  assert.equal(buildSpeakerFilterGraph(bound.payload, .5), buildSpeakerFilterGraph(saved.draft.payload, .5));
});
test('S09A: failure after finalization and uncertain project write retry without duplicate source sessions or drafts', async () => {
  const h = await managementHarness(), { files, context, payload } = local(), save = new ProjectSave(h.gateway);
  const session = await save.sources(context, files), bound = bindLocalPayload(context, payload, save.plan, session, .5);
  const fetch = h.gateway.fetchImpl; let fail = true;
  h.gateway.fetchImpl = async (url, options = {}) => {
    if (fail && options.method === 'PUT' && url.endsWith('/drafts/speaker')) { fail = false; throw Object.assign(new Error('Expired'), { status: 401 }); }
    return fetch(url, options);
  };
  await assert.rejects(save.save(session, null, bound.payload), { status: 401 });
  assert.equal((await save.sources(context, files)).id, session.id);
  const key = save.attempt.envelope.idempotencyKey;
  let uncertain = true;
  h.gateway.fetchImpl = async (url, options = {}) => { const response = await fetch(url, options);
    if (uncertain && options.method === 'PUT' && url.endsWith('/drafts/speaker')) { uncertain = false; throw new TypeError('Response lost'); } return response; };
  await assert.rejects(save.save(session, null, bound.payload)); assert.equal(save.attempt.envelope.idempotencyKey, key);
  const saved = await save.save(session, null, bound.payload);
  assert.equal(saved.draft.draftRevision, 1);
  assert.equal((await h.gateway.listSessions()).sessions.length, 1);
  assert.equal(h.trace.filter(t => t.path === '/v1/source-sessions/ingestions').length, 1);
});
test('S09A: uncertainty after source finalization reuses ingestion identity; changed targets fail closed', async () => {
  const h = await managementHarness(), { files, context, payload } = local(), save = new ProjectSave(h.gateway);
  const fetch = h.gateway.fetchImpl; let fail = true;
  h.gateway.fetchImpl = async (url, options) => { const response = await fetch(url, options);
    if (fail && url.endsWith('/finalize')) { fail = false; throw new TypeError('Response lost'); } return response; };
  await assert.rejects(save.sources(context, files)); const session = await save.sources(context, files);
  assert.equal((await h.gateway.listSessions()).sessions.length, 1);
  const bound = bindLocalPayload(context, payload, save.plan, session, .5);
  await h.gateway.updateSession(session.id, session.revision, { title: 'Changed elsewhere' });
  await assert.rejects(save.save(session, null, bound.payload), { status: 409 });
});
test('S09A: boundaries use only compatible cuts, preserve interior/silence, undo/redo and reject empty range', () => {
  const { payload } = local(); const interior = { regionId: crypto.randomUUID(), startSeconds: .2, endSeconds: .3 }; payload.globalCuts.push(interior);
  const history = new SpeakerHistory(payload);
  const start = setRecordingBoundary(payload, .5, 'start', .1), end = setRecordingBoundary(start, .5, 'end', .4);
  history.commit(end); assert.deepEqual(recordingBoundaries(end, .5), { start: .1, end: .4 });
  assert.ok(end.globalCuts.some(c => c.regionId === interior.regionId)); assert.deepEqual(end.trackSilenceRegions, payload.trackSilenceRegions);
  assert.deepEqual(history.undo(), payload); assert.deepEqual(history.redo(), end);
  assert.throws(() => setRecordingBoundary(end, .5, 'start', .4));
  assert.throws(() => setRecordingBoundary(end, .5, 'end', .25), /пересекает/);
});
test('S09A: edits after a failed or uncertain save reconcile the prior attempt before saving the latest montage', async () => {
  for (const persisted of [false, true]) {
    const h = await managementHarness(), { files, context, payload } = local(), save = new ProjectSave(h.gateway);
    const session = await save.sources(context, files), bound = bindLocalPayload(context, payload, save.plan, session, .5);
    const fetch = h.gateway.fetchImpl; let fail = true;
    h.gateway.fetchImpl = async (url, options) => {
      if (fail && options?.method === 'PUT' && url.endsWith('/drafts/speaker')) {
        fail = false; if (persisted) await fetch(url, options);
        throw new TypeError('Response lost');
      }
      return fetch(url, options);
    };
    await assert.rejects(save.save(session, null, bound.payload));
    const changed = structuredClone(bound.payload); changed.trackProcessing[0].compression = 'off';
    const result = await save.save(session, null, changed);
    assert.deepEqual(result.draft.payload, changed);
    assert.equal(result.draft.draftRevision, persisted ? 2 : 1);
    assert.equal(h.trace.filter(t => t.path === '/v1/source-sessions/ingestions').length, 1);
  }
});
test('S09A: byte download authentication errors retain status for reconnect', async () => {
  const h = await managementHarness(), { files, context } = local(), save = new ProjectSave(h.gateway);
  const session = await save.sources(context, files);
  for (const status of [401, 403]) await assert.rejects(reconstructTrack(session.sourceTracks[0], session.id,
    async () => new Response('expired', { status })), { status });
});
test('S09A: cancelled source upload preserves the plan/key and retries the same source session', async () => {
  const h = await managementHarness(), { files, context } = local(), save = new ProjectSave(h.gateway), controller = new AbortController();
  await assert.rejects(save.sources(context, files, { signal: controller.signal, onProgress: () => controller.abort() }), { name: 'AbortError' });
  assert.ok(save.plan); assert.equal(save.finalized, null);
  const session = await save.sources(context, files);
  assert.equal((await h.gateway.listSessions()).sessions.length, 1);
  assert.deepEqual((await reconstructSessionTracks(session, h.gateway.sourcePartFetch(session))).map(f => f.size), files.map(f => f.size));
});
