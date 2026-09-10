import test from 'node:test';
import assert from 'node:assert/strict';
import { managementFixture, managementHarness } from './archive-management-fixture.mjs';
import { mergeSessions, selectSessions, selectResults, overview, recoveryPolicy, parseEditorIntent, editorUrl, deletionImpact, RequestGeneration, dateLabel } from '../../../scripts/audio-archive-core.mjs';
import { reconstructAnnouncementOutput, reconstructSpeakerOutput } from '../../../scripts/audio-archive-client.mjs';

const fixture = await managementFixture();
const { primary, archived, empty } = fixture;
const sessions = [primary, archived, empty];

test('S09 both lifecycle observations retain higher revision once and reject malformed manifests', () => {
  const older = structuredClone(primary); older.revision--;
  assert.deepEqual(mergeSessions([older, empty], [archived, primary]), [primary, empty, archived]);
  assert.deepEqual(mergeSessions([primary], [older]), [primary]);
  assert.throws(() => mergeSessions([{ id: 'broken' }]));
});
test('S09 normalized title, filename and exact identity search; AND filters and inclusive UTC dates', () => {
  assert.equal(selectSessions(sessions, { search: 'встреча и\u0306' })[0], primary);
  assert.equal(selectSessions(sessions, { search: 'ИСХОДНИК И\u0306.WAV' }).length, 3);
  assert.equal(selectSessions(sessions, { search: primary.id.toUpperCase() }).length, 1);
  const filters = { search: 'встреча', lifecycle: 'incoming', sources: 'available', announcementState: 'result_ready', announcementResult: 'yes', speakerState: 'result_ready', speakerResult: 'yes', attention: true, from: '2026-09-09', to: '2026-09-09' };
  assert.deepEqual(selectSessions(sessions, filters, [{ sessionId: primary.id }]), [primary]);
  for (const [key, value] of Object.entries({ lifecycle: 'archived', sources: 'unavailable', announcementState: 'new', announcementResult: 'no', speakerState: 'new', speakerResult: 'no', from: '2026-09-10', search: 'нет совпадений' })) {
    if (key === 'from') continue;
    assert.equal(selectSessions(sessions, { ...filters, [key]: value }, [{ sessionId: primary.id }]).length, 0, key);
  }
  assert.equal(selectSessions(sessions, { from: '2026-09-10' }).length, 0);
  assert.throws(() => selectSessions(sessions, { from: '2026-10-01', to: '2026-01-01' }));
  assert.throws(() => selectSessions(sessions, { from: '2026-02-30' }));
  assert.equal(dateLabel(null), 'Дата не указана');
  assert.match(dateLabel(primary.recordedAt), /19:30:00 UTC$/);
});
test('S09 every session/result sort is stable, immutable, preserves missing-date placement and workflow ownership', () => {
  const before = JSON.stringify(sessions);
  assert.deepEqual(selectSessions(sessions, { sort: 'newest' }), [primary, empty, archived]);
  assert.deepEqual(selectSessions(sessions, { sort: 'oldest' }), [empty, primary, archived]);
  assert.deepEqual(selectSessions(sessions, { sort: 'title' }), [archived, primary, empty]);
  assert.deepEqual(selectSessions(sessions, { sort: 'title-desc' }), [empty, primary, archived]);
  assert.deepEqual(selectSessions(sessions, { sort: 'updated' }).map(s => s.id), [...sessions].map(s => s.id).sort());
  for (const workflow of ['announcement', 'speaker']) for (const sort of ['newest', 'oldest', 'version', 'version-desc', 'title']) {
    const result = selectResults(sessions, workflow, sort);
    assert.deepEqual(result, selectResults([...sessions].reverse(), workflow, sort));
    assert.ok(result.every(r => r.session.workflows[workflow].outputs.includes(r.output)));
    if (sort === 'version') assert.ok(result.every((r, i) => !i || result[i - 1].output.version <= r.output.version));
    if (sort === 'version-desc') assert.ok(result.every((r, i) => !i || result[i - 1].output.version >= r.output.version));
  }
  const dated = structuredClone(sessions);
  dated[0].workflows.announcement.outputs[0].createdAt = '2026-01-01T00:00:00Z';
  dated[0].workflows.announcement.outputs[1].createdAt = '2026-03-01T00:00:00Z';
  dated[1].workflows.announcement.outputs[0].createdAt = '2026-02-01T00:00:00Z';
  assert.deepEqual(selectResults(dated, 'announcement', 'newest').map(r => r.output.createdAt),
    ['2026-03-01T00:00:00Z', '2026-02-01T00:00:00Z', '2026-01-01T00:00:00Z']);
  assert.deepEqual(selectResults(dated, 'announcement', 'oldest').map(r => r.output.createdAt),
    ['2026-01-01T00:00:00Z', '2026-02-01T00:00:00Z', '2026-03-01T00:00:00Z']);
  assert.deepEqual(selectResults(dated, 'announcement', 'title').map(r => r.session.title), [archived.title, primary.title, primary.title]);
  dated[0].updatedAt = '2026-01-01T00:00:00Z';
  assert.equal(selectSessions(dated, { sort: 'updated' }).at(-1).id, primary.id);
  assert.equal(JSON.stringify(sessions), before);
  assert.deepEqual(primary.workflows.announcement.outputs.map(o => o.version), [1, 3]);
  assert.deepEqual(primary.workflows.announcement.deletedVersions, [2]);
});
test('S09 overview counts operations independently and never fabricates unavailable zeros', () => {
  assert.deepEqual(overview(sessions, { transactions: [{ sessionId: primary.id }, { sessionId: primary.id }, { sessionId: 'unfinalized' }], orphans: [{}] }), { incoming: 2, archived: 1, announcement: 3, speaker: 1, attention: 3, orphans: 1 });
  assert.ok(Object.values(overview(null, null)).every(value => value === null));
});
test('S09 recovery matrix denies malformed/unknown/discarding finalization and pending-delete discard', () => {
  const base = { transactionId: primary.id, kind: 'publication', workflow: 'speaker', state: 'uploading', uploadedParts: 1, totalParts: 2, canFinalize: false };
  const actions = o => recoveryPolicy(o).actions.map(([action]) => action);
  assert.deepEqual(actions(base), ['discard']);
  assert.deepEqual(actions({ ...base, uploadedParts: 2, canFinalize: true }), ['resume']);
  assert.deepEqual(actions({ ...base, kind: 'ingestion' }), ['discard']);
  assert.deepEqual(actions({ ...base, kind: 'ingestion', uploadedParts: 2, canFinalize: true }), ['resume']);
  assert.deepEqual(actions({ ...base, workflow: 'announcement', uploadedParts: 2, canFinalize: true }), ['resume']);
  assert.deepEqual(actions({ ...base, state: 'discarding', uploadedParts: 2, canFinalize: false }), ['discard']);
  assert.deepEqual(actions({ ...base, kind: 'pending_delete', state: 'pending_delete' }), ['retry']);
  for (const patch of [{ state: 'finalized' }, { workflow: 'other' }, { kind: 'unknown' }, { totalParts: null }, { uploadedParts: -1 }, { canFinalize: true }, { transactionId: 'bad' }]) assert.deepEqual(actions({ ...base, ...patch }), []);
});
test('S09 validated navigation contains identity/workflow only and rejects duplicates and ineligible sessions', () => {
  for (const workflow of ['announcement', 'speaker']) {
    const url = editorUrl(primary, workflow);
    assert.deepEqual(parseEditorIntent(url.slice(url.indexOf('?'))), { sessionId: primary.id, workflow });
  }
  assert.equal(parseEditorIntent('?id=legacy'), null);
  for (const query of ['?session=bad&workflow=speaker', `?session=${primary.id}&workflow=unknown`, `?session=${primary.id}&session=${primary.id}&workflow=speaker`]) assert.throws(() => parseEditorIntent(query));
  assert.throws(() => editorUrl(archived, 'speaker'));
  assert.throws(() => editorUrl({ ...primary, sourceState: 'deleted' }, 'announcement'));
});
test('S09 request generations discard late results after a newer view/logout', async () => {
  const fence = new RequestGeneration(), old = fence.next();
  let release; const pending = new Promise(resolve => { release = resolve; }).then(() => fence.current(old));
  fence.next(); release(); assert.equal(await pending, false);
});
test('S09 real gateway metadata conflicts and lifecycle retain canonical bytes and other metadata', async () => {
  const h = await managementHarness(); let session = await h.ingest('Исходное', 'metadata');
  const updated = await h.gateway.updateSession(session.id, session.revision, { title: 'Новое', recordedAt: '2026-09-10T10:01:02.345+03:00' });
  await assert.rejects(() => h.gateway.updateSession(session.id, session.revision, { title: 'Устаревшее', recordedAt: null }), error => error.status === 409);
  session = await h.gateway.getSession(session.id); assert.equal(session.title, 'Новое');
  assert.equal(session.recordedAt, '2026-09-10T10:01:02.345+03:00');
  const before = JSON.stringify(session.sourceTracks);
  await h.gateway.setLifecycle(session.id, 'archive', session.revision); session = await h.gateway.getSession(session.id);
  assert.equal(session.lifecycle.state, 'archived'); assert.equal(JSON.stringify(session.sourceTracks), before);
  await h.gateway.setLifecycle(session.id, 'restore', session.revision); assert.equal((await h.gateway.getSession(session.id)).lifecycle.state, 'incoming');
  session = await h.gateway.getSession(session.id);
  await h.gateway.updateSession(session.id, session.revision, { recordedAt: null });
  assert.equal((await h.gateway.getSession(session.id)).recordedAt, null);
  assert.ok(updated);
});
test('S09 real gateway deletion previews, stale writes, non-cascade series/source deletion, exact purge and retained playback', async () => {
  const h = await managementFixture(); let session = h.primary;
  let preview = await h.gateway.dependencyPreview(session.id);
  assert.match(deletionImpact(preview, { kind: 'output-series', workflow: 'announcement' }).retained, /сохранённые настройки обработки \(2\)/);
  assert.match(deletionImpact(preview, { kind: 'sources' }).retained, /все сохранённые результаты/);
  await h.gateway.setLifecycle(session.id, 'archive', session.revision);
  await assert.rejects(() => h.gateway.deleteOutputSeries(session.id, 'announcement', { expectedRevision: preview.revision, idempotencyKey: 's09-stale-delete-test', confirmation: '' }), e => e.status === 409);
  session = await h.gateway.getSession(session.id); preview = await h.gateway.dependencyPreview(session.id);
  await h.gateway.deleteOutputSeries(session.id, 'announcement', { expectedRevision: preview.revision, idempotencyKey: 's09-series-delete-test', confirmation: '' });
  session = await h.gateway.getSession(session.id);
  assert.equal(session.sourceTracks.length, 1); assert.ok(session.workflows.announcement.currentDraft); assert.equal(session.workflows.speaker.outputs.length, 1);
  assert.deepEqual(session.workflows.announcement.deletedVersions, [1, 2, 3]); assert.equal(session.workflows.announcement.nextVersion, 4);
  await h.gateway.deleteSources(session.id, { expectedRevision: session.revision, idempotencyKey: 's09-source-delete-test', confirmation: 'Удалить исходники, сохранить результаты' });
  session = await h.gateway.getSession(session.id); assert.equal(session.sourceState, 'deleted');
  const metadata = await h.gateway.getSpeakerOutput(session.id, session.workflows.speaker.outputs[0].outputId);
  const restored = await reconstructSpeakerOutput(metadata, h.gateway.speakerPartFetch(metadata)); assert.ok(restored.size > 0);
  await assert.rejects(() => h.gateway.purgeSession(session.id, { expectedRevision: session.revision, idempotencyKey: 's09-purge-wrong-test', confirmation: 'yes' }), e => e.status === 400);
  await h.gateway.purgeSession(session.id, { expectedRevision: session.revision, idempotencyKey: 's09-purge-exact-test', confirmation: session.id });
  await assert.rejects(() => h.gateway.getSession(session.id), e => e.status === 404);
});
test('S09 read-only discovery and verified playback trace; corrupted, missing, reordered and wrong-workflow parts fail closed', async () => {
  const h = fixture; h.trace.length = 0;
  const incoming = await h.gateway.listSessions('incoming'), old = await h.gateway.listSessions('archived');
  const all = mergeSessions(incoming.sessions, old.sessions), operations = await h.gateway.listIncomplete();
  selectSessions(all, { search: 'исходник' }); selectResults(all, 'speaker'); overview(all, operations);
  await h.gateway.getSession(primary.id);
  assert.ok(h.trace.every(r => r.method === 'GET' && !r.path.includes('/content') && !r.path.includes('/outputs/')));
  for (const workflow of ['announcement', 'speaker']) {
    const output = primary.workflows[workflow].outputs[0];
    const metadata = await (workflow === 'announcement' ? h.gateway.getAnnouncementOutput(primary.id, output.outputId) : h.gateway.getSpeakerOutput(primary.id, output.outputId));
    const reconstruct = workflow === 'announcement' ? reconstructAnnouncementOutput : reconstructSpeakerOutput;
    const adapter = workflow === 'announcement' ? h.gateway.announcementPartFetch(metadata) : h.gateway.speakerPartFetch(metadata);
    assert.ok((await reconstruct(metadata, adapter)).size > 0);
    await assert.rejects(() => reconstruct(metadata, async () => new Response(new Uint8Array(output.parts[0].sizeBytes))));
    await assert.rejects(() => reconstruct(metadata, async () => new Response(null, { status: 404 })));
    const reversed = structuredClone(metadata); reversed.output.parts.reverse(); await assert.rejects(() => reconstruct(reversed, adapter));
    await assert.rejects(() => reconstruct({ ...metadata, recipe: { ...metadata.recipe, workflow: 'wrong' } }, adapter));
    await assert.rejects(() => adapter('https://github.com/not-this-output'));
  }
  assert.ok(h.trace.every(r => r.method === 'GET')); assert.ok(h.trace.every(r => !r.path.includes('rebuild')));
});
