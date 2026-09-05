import test from "node:test";
import assert from "node:assert/strict";
import { AudioArchiveDomain } from "../src/domain.mjs";
import { assetName } from "../src/validation.mjs";
import { IDS, MemoryRepository, sampleOutput, sha } from "./helpers.mjs";

const KEY = "0123456789abcdef";
const CLOCK = () => Date.parse("2026-01-02T03:04:05.000Z");

function ingestionBody(bytes = Buffer.from("source-audio")) {
  const parts = [bytes.subarray(0, 4), bytes.subarray(4, 8), bytes.subarray(8)].filter((part) => part.length);
  return {
    bytes,
    body: {
      schemaVersion: 1, idempotencyKey: KEY, title: "Запись", recordedAt: null, origin: "manual", supersedesSessionId: null,
      plan: {
        totalBytes: bytes.length,
        tracks: [{ trackId: IDS.track, blobId: IDS.blob, ordinal: 1, originalName: "source.wav", mediaType: "audio/wav",
          sizeBytes: bytes.length, sha256: sha(bytes), parts: parts.map((part, index) => ({
            partNumber: index + 1, sizeBytes: part.length, sha256: sha(part), assetName: assetName(IDS.blob, index + 1)
          })) }]
      }
    },
    parts
  };
}

async function finalizedFixture() {
  const repository = new MemoryRepository();
  const domain = new AudioArchiveDomain(repository, { acceptedPartBytes: 4, clock: CLOCK });
  const fixture = ingestionBody();
  const started = await domain.beginIngestion(fixture.body);
  assert.deepEqual(await domain.listSessions("incoming"), { revision: 0, sessions: [] });
  for (const [index, bytes] of fixture.parts.entries()) {
    await domain.uploadPart(started.transactionId, IDS.blob, index + 1, bytes, sha(bytes), `${KEY}:part:${index}`);
  }
  const finalized = await domain.finalizeIngestion(started.transactionId);
  return { repository, domain, fixture, started, session: finalized.session };
}

test("ingestion is idempotent, hidden until finalization, integrity checked, and recoverable", async () => {
  const repository = new MemoryRepository();
  const domain = new AudioArchiveDomain(repository, { acceptedPartBytes: 4, clock: CLOCK });
  const fixture = ingestionBody();
  const first = await domain.beginIngestion(fixture.body);
  const second = await domain.beginIngestion(fixture.body);
  assert.deepEqual(second, first);
  assert.equal(repository.releases.size, 1);
  assert.equal((await domain.listIncomplete()).transactions.length, 1);
  await assert.rejects(() => domain.finalizeIngestion(first.transactionId), (error) => error.status === 409);
  await assert.rejects(() => domain.uploadPart(first.transactionId, IDS.blob, 1, Buffer.from("xxxx"), fixture.body.plan.tracks[0].parts[0].sha256, `${KEY}:bad`), /SHA-256/);
  for (const [index, bytes] of fixture.parts.entries()) {
    const uploaded = await domain.uploadPart(first.transactionId, IDS.blob, index + 1, bytes, sha(bytes), `${KEY}:part:${index}`);
    const retried = await domain.uploadPart(first.transactionId, IDS.blob, index + 1, bytes, sha(bytes), `${KEY}:part:${index}`);
    assert.equal(retried.assetId, uploaded.assetId);
  }
  const finalized = await domain.finalizeIngestion(first.transactionId);
  assert.equal(finalized.session.sourceTracks[0].sha256, sha(fixture.bytes));
  assert.equal((await domain.finalizeIngestion(first.transactionId)).idempotent, true);
  assert.equal((await domain.listSessions("incoming")).sessions.length, 1);
  assert.equal((await domain.listIncomplete()).transactions.length, 0);
});

test("workflow states are independent and stale session mutations conflict", async () => {
  const { domain, session } = await finalizedFixture();
  const announcement = await domain.updateWorkflow(session.id, "announcement", {
    expectedRevision: session.revision, status: "in_progress", idempotencyKey: `${KEY}:announcement`
  });
  assert.equal(announcement.workflows.announcement.status, "in_progress");
  assert.equal(announcement.workflows.speaker.status, "new");
  await assert.rejects(() => domain.updateWorkflow(session.id, "speaker", {
    expectedRevision: session.revision, status: "in_progress", idempotencyKey: `${KEY}:speaker`
  }), (error) => error.status === 409);
  await assert.rejects(() => domain.updateWorkflow(session.id, "speaker", {
    expectedRevision: announcement.revision, status: "result_ready", idempotencyKey: `${KEY}:ready`
  }), /cannot manually set result_ready/);
});

test("shared draft reopens and stale draft or source revisions cannot overwrite it", async () => {
  const { domain, session } = await finalizedFixture();
  const saved = await domain.saveDraft(session.id, "speaker", {
    schemaVersion: 1, expectedDraftRevision: 0, expectedSourceSessionRevision: session.revision,
    payloadSchema: "speaker-foundation/v1", payload: { markers: [1, 2] }, idempotencyKey: `${KEY}:draft-one`
  });
  assert.deepEqual((await domain.loadDraft(session.id, "speaker")).payload, { markers: [1, 2] });
  await assert.rejects(() => domain.saveDraft(session.id, "speaker", {
    schemaVersion: 1, expectedDraftRevision: 0, expectedSourceSessionRevision: saved.session.revision,
    payloadSchema: "speaker-foundation/v1", payload: {}, idempotencyKey: `${KEY}:draft-two`
  }), (error) => error.status === 409);
  await assert.rejects(() => domain.saveDraft(session.id, "speaker", {
    schemaVersion: 1, expectedDraftRevision: 1, expectedSourceSessionRevision: session.revision,
    payloadSchema: "speaker-foundation/v1", payload: {}, idempotencyKey: `${KEY}:draft-three`
  }), (error) => error.status === 409);
});

test("archive and restore mutate metadata without touching release assets", async () => {
  const { repository, domain, session } = await finalizedFixture();
  const before = JSON.stringify([...repository.releases.values()]);
  const archived = await domain.setLifecycle(session.id, "archived", { expectedRevision: session.revision, idempotencyKey: `${KEY}:archive` });
  assert.equal(archived.lifecycle.state, "archived");
  assert.equal((await domain.listSessions("incoming")).sessions.length, 0);
  assert.equal((await domain.listSessions("archived")).sessions.length, 1);
  const restored = await domain.setLifecycle(session.id, "incoming", { expectedRevision: archived.revision, idempotencyKey: `${KEY}:restore` });
  assert.equal(restored.lifecycle.state, "incoming");
  assert.equal(JSON.stringify([...repository.releases.values()]), before);
});

test("deletion is explicit, non-cascading, resumable, and version numbers are not reused", async () => {
  const { repository, domain, session } = await finalizedFixture();
  const stored = structuredClone(repository.files.get(`sessions/${session.id}.json`));
  const output = sampleOutput(session.id);
  stored.workflows.announcement.outputs.push(output);
  stored.workflows.announcement.status = "result_ready";
  stored.workflows.announcement.nextVersion = 2;
  repository.releases.get(stored.storage.releaseId).assets.push({ id: 90, name: output.parts[0].assetName, size: output.sizeBytes,
    digest: `sha256:${output.sha256}`, browser_download_url: output.parts[0].downloadUrl });
  repository.files.set(`sessions/${session.id}.json`, stored);
  const preview = await domain.dependencyPreview(session.id);
  assert.deepEqual({ sources: preview.sourceTracks, outputs: preview.announcementVersions }, { sources: 1, outputs: 1 });
  const deleted = await domain.deleteSources(session.id, {
    expectedRevision: stored.revision, idempotencyKey: `${KEY}:sources`, confirmation: "Удалить исходники, сохранить результаты"
  });
  assert.equal(deleted.session.sourceState, "deleted");
  assert.equal(deleted.session.workflows.announcement.outputs.length, 1);
  assert.equal(repository.releases.get(stored.storage.releaseId).assets.some((asset) => asset.id === 90), true);
  assert.equal((await domain.deleteSources(session.id, {
    expectedRevision: stored.revision, idempotencyKey: `${KEY}:sources`, confirmation: "Удалить исходники, сохранить результаты"
  })).completed, true);
  const afterOutput = await domain.deleteOutputVersion(session.id, "announcement", 1, {
    expectedRevision: deleted.session.revision, idempotencyKey: `${KEY}:output`, confirmation: ""
  });
  assert.deepEqual(afterOutput.session.workflows.announcement.deletedVersions, [1]);
  assert.equal(afterOutput.session.workflows.announcement.nextVersion, 2);
});

test("purge writes a tombstone, removes only its release/drafts, and catalog rebuild reports orphans", async () => {
  const { repository, domain, session } = await finalizedFixture();
  await domain.saveDraft(session.id, "announcement", {
    schemaVersion: 1, expectedDraftRevision: 0, expectedSourceSessionRevision: session.revision,
    payloadSchema: "foundation/v1", payload: {}, idempotencyKey: `${KEY}:draft-purge`
  });
  const current = await domain.getSession(session.id);
  const orphan = await repository.createDraftRelease("audio-session-77777777-7777-4777-8777-777777777777");
  const purged = await domain.purgeSession(session.id, {
    expectedRevision: current.revision, idempotencyKey: `${KEY}:purge`, confirmation: session.id
  });
  assert.equal(purged.tombstone.kind, "deletion_tombstone");
  assert.equal(repository.files.has(`drafts/${session.id}/announcement.json`), false);
  assert.equal(repository.releases.has(current.storage.releaseId), false);
  await assert.rejects(() => domain.getSession(session.id), (error) => error.status === 404);
  const rebuilt = await domain.rebuildCatalog();
  assert.equal(rebuilt.catalog.entries.length, 0);
  assert.deepEqual(rebuilt.orphans.map((item) => item.releaseId), [orphan.id]);
});

test("explicit incomplete ingestion discard is recoverable and does not become visible", async () => {
  const repository = new MemoryRepository();
  const domain = new AudioArchiveDomain(repository, { acceptedPartBytes: 4, clock: CLOCK });
  const started = await domain.beginIngestion(ingestionBody().body);
  const result = await domain.recoverIncomplete(started.transactionId, "discard");
  assert.equal(result.discarded, true);
  assert.equal(repository.releases.size, 0);
  assert.equal((await domain.listSessions("incoming")).sessions.length, 0);
});

test("malformed persisted transactions fail closed and are never offered for recovery", async () => {
  const repository = new MemoryRepository();
  repository.files.set(`transactions/ingest-${IDS.transaction}.json`, {
    schemaVersion: 1, kind: "ingestion", transactionId: IDS.transaction, sessionId: IDS.transaction,
    releaseId: 999, state: "uploading", unexpected: "unsafe"
  });
  const domain = new AudioArchiveDomain(repository, { acceptedPartBytes: 4, clock: CLOCK });
  assert.deepEqual((await domain.listIncomplete()).transactions, []);
  await assert.rejects(() => domain.recoverIncomplete(IDS.transaction, "resume"), /unsupported fields|idempotencyHash/);
});
