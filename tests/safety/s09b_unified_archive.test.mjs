import test from 'node:test';
import assert from 'node:assert/strict';
import { managementFixture } from '../../gateway/audio-archive/test/archive-management-fixture.mjs';
import {
  mergeSessions, selectSessions, parseArchiveIntent, lifecycleLabel, sourceLabel, eligible, recoveryPolicy
} from '../../scripts/audio-archive-core.mjs';
import { projectProjection } from '../../scripts/audio-project.mjs';
import { validateAnnouncementOutput, validateSpeakerOutput } from '../../scripts/audio-archive-client.mjs';

test('S09B recording collection defaults to all records and secondary filters keep one UUID once', async () => {
  const h = await managementFixture();
  const incoming = (await h.gateway.listSessions('incoming')).sessions;
  const archived = (await h.gateway.listSessions('archived')).sessions;
  const newer = structuredClone(incoming[0]); newer.revision += 1;
  const all = mergeSessions(incoming, archived, [newer]);
  assert.equal(all.length, incoming.length + archived.length);
  assert.equal(all.find(item => item.id === newer.id).revision, newer.revision);
  assert.equal(selectSessions(all, {}).length, all.length);
  assert.ok(selectSessions(all, { lifecycle: 'archived' }).every(item => item.lifecycle.state === 'archived'));
  assert.ok(selectSessions(all, { sources: 'available' }).every(item => item.sourceState === 'available'));
  assert.ok(selectSessions(all, { speakerProject: true }).every(item => item.workflows.speaker.currentDraft));
  assert.ok(selectSessions(all, { announcementResult: true }).every(item => item.workflows.announcement.outputs.length));
  assert.ok(selectSessions(all, { speakerResult: true }).every(item => item.workflows.speaker.outputs.length));
});

test('S09B recording vocabulary separates work-list, source availability and processing eligibility', async () => {
  const h = await managementFixture();
  const incoming = await h.gateway.getSession(h.primary.id), archived = await h.gateway.getSession(h.archived.id);
  assert.equal(lifecycleLabel(incoming), 'В рабочем списке');
  assert.equal(lifecycleLabel(archived), 'Убрана из рабочего списка');
  assert.equal(sourceLabel(incoming), 'Исходники доступны');
  assert.equal(sourceLabel({ ...incoming, sourceState: 'deleted' }), 'Исходники удалены');
  assert.equal(sourceLabel({ ...incoming, sourceState: 'unavailable' }), 'Исходники недоступны');
  assert.equal(eligible(incoming), true); assert.equal(eligible(archived), false);
});

test('S09B archive intent accepts exactly one UUID and remains read-only', async () => {
  const h = await managementFixture(); h.trace.length = 0;
  assert.deepEqual(parseArchiveIntent(`?session=${h.primary.id}`), { sessionId: h.primary.id });
  assert.equal(parseArchiveIntent(''), null);
  for (const query of [`?session=${h.primary.id}&session=${h.primary.id}`, '?session=bad', `?session=${h.primary.id}&workflow=speaker`]) assert.throws(() => parseArchiveIntent(query));
  const session = await h.gateway.getSession(h.primary.id);
  const draft = await h.gateway.loadDraft(h.primary.id, 'speaker');
  assert.ok(projectProjection(session, draft.draft));
  for (const workflow of ['announcement', 'speaker']) for (const output of session.workflows[workflow].outputs) {
    const metadata = await (workflow === 'announcement' ? h.gateway.getAnnouncementOutput(session.id, output.outputId) : h.gateway.getSpeakerOutput(session.id, output.outputId));
    assert.equal(workflow === 'announcement' ? validateAnnouncementOutput(metadata.output, metadata.recipe, session.id) : validateSpeakerOutput(metadata.output, metadata.recipe, session.id), true);
    assert.ok(metadata.recipe.result.presentationFilename);
  }
  assert.ok(h.trace.every(item => item.method === 'GET'));
  assert.ok(h.trace.every(item => !item.path.endsWith('/content')));
});

test('S09B canonical deleted and reserved versions are never inferred from numeric gaps', async () => {
  const h = await managementFixture(), session = await h.gateway.getSession(h.primary.id);
  assert.deepEqual(session.workflows.announcement.outputs.map(output => output.version), [1, 3]);
  assert.deepEqual(session.workflows.announcement.deletedVersions, [2]);
  assert.equal(session.workflows.announcement.nextVersion, 4);
  const unknownGap = structuredClone(session); unknownGap.workflows.announcement.deletedVersions = [];
  assert.equal(unknownGap.workflows.announcement.outputs.some(output => output.version === 2), false);
  assert.equal(unknownGap.workflows.announcement.deletedVersions.includes(2), false);
});

test('S09B recovery remains canonical-action-only', () => {
  const id = crypto.randomUUID();
  assert.deepEqual(recoveryPolicy({ transactionId: id, kind: 'pending_delete', state: 'pending_delete' }).actions, [['retry', 'Продолжить удаление']]);
  assert.deepEqual(recoveryPolicy({ transactionId: id, kind: 'publication', workflow: 'speaker', state: 'uploading', totalParts: 2, uploadedParts: 2, canFinalize: true }).actions, [['resume', 'Завершить сохранение']]);
  assert.deepEqual(recoveryPolicy({ transactionId: id, kind: 'publication', workflow: 'speaker', state: 'unknown' }).actions, []);
});
