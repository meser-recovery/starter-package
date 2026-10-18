import test from 'node:test';
import assert from 'node:assert/strict';
import { AudioArchiveDomain } from '../src/domain.mjs';
import { ArchiveReadModel } from '../src/read-model.mjs';
import { selectSessions, selectResults } from '../../../scripts/audio-archive-core.mjs';
import { validateArchivePage, validateSessionManifest, AudioArchiveGateway } from '../../../service/frontend/scripts/audio-archive-client.mjs';
import { managementFixture } from './archive-management-fixture.mjs';
import { sourceFixture, collection, clock, uuid } from './s13-fixtures.mjs';

test('S13 one cold build, global search and paging parity, two lifecycle consumers, bounded summaries', async () => {
  const h = await sourceFixture({ tracks: 1 }), sessions = collection(h.repository, h.session, 1000);
  const d = new AudioArchiveDomain(h.repository, { acceptedPartBytes: 4, clock });
  const [first, same, archived] = await Promise.all([d.querySessions({}), d.querySessions({}), d.querySessions({ lifecycle: 'archived' })]);
  assert.deepEqual(first, same); assert.equal(first.total, 1000); assert.equal(archived.total, 500);
  assert.equal(h.repository.blobReads.length, 1000); assert.equal(h.repository.trees, 1);
  assert.equal(first.items.length, 10); assert.ok(validateArchivePage(first)); assert.equal(validateSessionManifest(first.items[0]), false);
  const queries = [{}, { lifecycle: 'archived' }, { sources: 'available' }, { search: uuid(1000) }, { search: 'последняя' },
    { search: 'Дорожка-0' }, { search: 'НЕТ СОВПАДЕНИЙ' }, { search: 'Запись', sort: 'title' }, { sort: 'title-desc' },
    { sort: 'oldest' }, { sort: 'updated' }, { from: '2026-10-10', to: '2026-10-10' }, { announcementState: 'new' }, { speakerResult: 'no' }];
  for (const q of queries) {
    const expected = selectSessions(sessions, q).map(s => s.id), got = [];
    for (let page = 0; page < Math.max(1, Math.ceil(expected.length / 10)); page++) {
      const result = await d.querySessions({ ...q, page, snapshot: first.snapshot });
      assert.equal(result.total, expected.length); got.push(...result.items.map(s => s.id));
    }
    assert.deepEqual(got, expected, JSON.stringify(q));
  }
  assert.equal(h.repository.blobReads.length, 1000, 'warm pages/search never reread N manifests');
  assert.equal(h.repository.reads.filter(path => path.startsWith('drafts/')).length, 0);
  const invalid = structuredClone(first); invalid.items[0].untrusted = true; assert.equal(validateArchivePage(invalid), false);
});

test('S13 changed HEAD reuses unchanged validated blob identities and requires a page restart', async () => {
  const h = await sourceFixture({ tracks: 1 }); collection(h.repository, h.session, 10);
  const first = await h.domain.querySessions({});
  h.repository.files.get(`sessions/${uuid(10)}.json`).title = 'Новое название'; h.repository.head++;
  await assert.rejects(() => h.domain.querySessions({ snapshot: first.snapshot, page: 1 }), e => e.status === 409);
  const updated = await h.domain.querySessions({ search: 'Новое' });
  assert.equal(updated.items[0].id, uuid(10)); assert.equal(h.repository.blobReads.length, 11);
  assert.notEqual(updated.snapshot, first.snapshot);
  await assert.rejects(() => h.domain.querySessions({ search: 'Новое', page: 1, queryId: first.queryId, snapshot: updated.snapshot }), e => e.status === 409);
  h.repository.getHead = async () => { throw Object.assign(new Error('auth lost'), { status: 401 }); };
  await assert.rejects(() => h.domain.querySessions({}), e => e.status === 401, 'cached summaries do not mask auth failure');
});

test('S13 partial/invalid/truncated snapshots are never published; query validation is strict', async () => {
  const h = await sourceFixture({ tracks: 1 }); collection(h.repository, h.session, 3);
  const path = `sessions/${uuid(3)}.json`, valid = h.repository.files.get(path);
  h.repository.files.delete(path);
  await assert.rejects(() => h.domain.querySessions({})); assert.equal(h.domain.readModel.current, null);
  h.repository.files.set(path, { ...valid, revision: 0 });
  await assert.rejects(() => h.domain.querySessions({})); assert.equal(h.domain.readModel.current, null);
  h.repository.files.set(path, valid); h.repository.jsonIdentities = async () => { throw new Error('truncated tree'); };
  await assert.rejects(() => h.domain.querySessions({}), /truncated/);
  for (const q of [{ page: -1 }, { page: '1.5' }, { pageSize: 100 }, { sort: 'arbitrary' }, { search: [] }, { extra: true }, { from: '2026-02-31' }, { month: '2026-13' }, { attention: 'yes' }]) await assert.rejects(() => h.domain.querySessions(q));
});

test('S13 results preserve independent version order without recipes and project flags remain unverified', async () => {
  const h = await managementFixture();
  const canonical = [...(await h.gateway.listSessions('incoming')).sessions, ...(await h.gateway.listSessions('archived')).sessions];
  for (const workflow of ['announcement', 'speaker']) for (const sort of ['newest', 'oldest', 'version', 'version-desc', 'title']) {
    const result = await h.domain.querySessions({ view: workflow, sort });
    assert.ok(validateArchivePage(result));
    assert.deepEqual(result.items.map(i => [i.session.id, i.output.outputId]), selectResults(canonical, workflow, sort).map(i => [i.session.id, i.output.outputId]));
    assert.ok(result.items.every(i => !('recipe' in i) && !('sha256' in i.output)));
  }
  const projects = await h.domain.querySessions({ speakerProject: true });
  assert.ok(projects.items.length); assert.ok(projects.items.every(s => s.workflows.speaker.hasDraft));
});

test('S13 lightweight attention discovers session-less pending operations with zero session/release scans; malformed is unknown', async () => {
  const h = await sourceFixture({ tracks: 1 });
  const transaction = [...h.repository.files].find(([path]) => path.startsWith('transactions/ingest-'));
  const pending = structuredClone(transaction[1]); pending.state = 'uploading'; pending.uploadedParts = [];
  h.repository.files.set(transaction[0], pending);
  h.repository.files.delete(`sessions/${pending.sessionId}.json`);
  const calls = []; const list = h.repository.listJson.bind(h.repository);
  h.repository.listJson = async (...args) => { calls.push(args[0]); return list(...args); };
  h.repository.listReleases = async () => { throw new Error('ordinary attention must not scan releases'); };
  const attention = await h.domain.listAttention(); assert.equal(attention.transactions.length, 1); assert.equal(attention.transactions[0].sessionId, pending.sessionId);
  assert.deepEqual(calls, ['transactions/']);
  h.repository.files.set('transactions/broken.json', { kind: 'unknown' });
  await assert.rejects(() => h.domain.listAttention(), /cannot be confirmed/);
});

test('S13 concurrent client reads coalesce; unsupported and malformed projections fail explicitly', async () => {
  let calls = 0;
  const gateway = new AudioArchiveGateway('https://synthetic.test', async () => { calls++; await new Promise(r => setTimeout(r, 5)); return new Response('{"value":1}', { headers: { 'Content-Type': 'application/json' } }); });
  await Promise.all([gateway.request('/read'), gateway.request('/read')]); assert.equal(calls, 1);
  await assert.rejects(() => gateway.querySessions({}), e => e.code === 'unsupported_archive_list');
  gateway.archiveReadModelVersion = 1;
  await assert.rejects(() => gateway.querySessions({}), /Повреждён/);
});
