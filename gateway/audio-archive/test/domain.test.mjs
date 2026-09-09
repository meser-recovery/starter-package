import test from "node:test";
import assert from "node:assert/strict";
import { AudioArchiveDomain } from "../src/domain.mjs";
import { assetName, uuidFromIdempotencyKey } from "../src/validation.mjs";
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
  const ready = (await domain.listIncomplete()).transactions[0];
  assert.equal(ready.canFinalize, true);
  assert.equal(ready.requiresOriginalFiles, false);
  const finalized = await domain.recoverIncomplete(first.transactionId, "resume");
  assert.equal(finalized.session.sourceTracks[0].sha256, sha(fixture.bytes));
  assert.equal((await domain.finalizeIngestion(first.transactionId)).idempotent, true);
  assert.equal((await domain.listSessions("incoming")).sessions.length, 1);
  assert.equal((await domain.listIncomplete()).transactions.length, 0);
});

test("an idempotency key cannot be reused with changed immutable ingestion data", async () => {
  const repository = new MemoryRepository();
  const domain = new AudioArchiveDomain(repository, { acceptedPartBytes: 4, clock: CLOCK });
  const fixture = ingestionBody();
  await domain.beginIngestion(fixture.body);
  const changedPlan = ingestionBody(Buffer.from("source-budio")).body.plan;
  const variants = [
    { ...fixture.body, title: "Другая запись" },
    { ...fixture.body, origin: "device" },
    { ...fixture.body, supersedesSessionId: IDS.session },
    { ...fixture.body, plan: changedPlan }
  ];
  for (const body of variants) {
    await assert.rejects(() => domain.beginIngestion(body), (error) => error.status === 409 && /request mismatch/.test(error.message));
  }
  assert.equal(repository.releases.size, 1);
});

test("partial maintenance recovery requires original files and never finalizes early", async () => {
  const repository = new MemoryRepository();
  const domain = new AudioArchiveDomain(repository, { acceptedPartBytes: 4, clock: CLOCK });
  const fixture = ingestionBody();
  const started = await domain.beginIngestion(fixture.body);
  await domain.uploadPart(started.transactionId, IDS.blob, 1, fixture.parts[0], sha(fixture.parts[0]), `${KEY}:part:1`);
  const [incomplete] = (await domain.listIncomplete()).transactions;
  assert.deepEqual(
    { uploadedParts: incomplete.uploadedParts, totalParts: incomplete.totalParts, canFinalize: incomplete.canFinalize, requiresOriginalFiles: incomplete.requiresOriginalFiles },
    { uploadedParts: 1, totalParts: fixture.parts.length, canFinalize: false, requiresOriginalFiles: true }
  );
  await assert.rejects(
    () => domain.recoverIncomplete(started.transactionId, "resume"),
    (error) => error.status === 409 && /Original files are required/.test(error.message)
  );
  assert.equal((await domain.listSessions("incoming")).sessions.length, 0);
  assert.equal(repository.releases.get(started.releaseId).draft, true);
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
  const speakerPayload = { trackIds: [IDS.track], excludedTrackIds: [], globalCuts: [], trackSilenceRegions: [],
    trackProcessing: [{ trackId: IDS.track, enhancement: "off", leveling: "off", compression: "off" }] };
  const saved = await domain.saveDraft(session.id, "speaker", {
    schemaVersion: 1, expectedDraftRevision: 0, expectedSourceSessionRevision: session.revision,
    payloadSchema: "speaker/v1", payload: speakerPayload, idempotencyKey: `${KEY}:draft-one`
  });
  assert.deepEqual((await domain.loadDraft(session.id, "speaker")).payload, speakerPayload);
  await assert.rejects(() => domain.saveDraft(session.id, "speaker", {
    schemaVersion: 1, expectedDraftRevision: 0, expectedSourceSessionRevision: saved.session.revision,
    payloadSchema: "speaker/v1", payload: speakerPayload, idempotencyKey: `${KEY}:draft-two`
  }), (error) => error.status === 409);
  await assert.rejects(() => domain.saveDraft(session.id, "speaker", {
    schemaVersion: 1, expectedDraftRevision: 1, expectedSourceSessionRevision: session.revision,
    payloadSchema: "speaker/v1", payload: speakerPayload, idempotencyKey: `${KEY}:draft-three`
  }), (error) => error.status === 409);
});

test("archive and restore mutate metadata without touching release assets", async () => {
  const { repository, domain, session } = await finalizedFixture();
  const before = JSON.stringify([...repository.releases.values()]);
  const archived = await domain.setLifecycle(session.id, "archived", { expectedRevision: session.revision, idempotencyKey: `${KEY}:archive` });
  assert.equal(archived.lifecycle.state, "archived");
  await assert.rejects(() => domain.saveDraft(session.id, "speaker", {
    schemaVersion: 1, expectedDraftRevision: 0, expectedSourceSessionRevision: archived.revision,
    payloadSchema: "speaker/v1", payload: { trackIds: [IDS.track], excludedTrackIds: [], globalCuts: [], trackSilenceRegions: [],
      trackProcessing: [{ trackId: IDS.track, enhancement: "off", leveling: "off", compression: "off" }] },
    idempotencyKey: `${KEY}:archived-speaker-draft`
  }), (error) => error.status === 409);
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

test("retained S08A v1 output descriptors remain readable without rewrite", async () => {
  const { repository, domain, session } = await finalizedFixture();
  const stored = structuredClone(repository.files.get(`sessions/${session.id}.json`));
  const legacy = sampleOutput(session.id);
  legacy.recipeSnapshotRef = `drafts/${session.id}/announcement.json#1`;
  stored.workflows.announcement.outputs = [legacy];
  stored.workflows.announcement.nextVersion = 2;
  stored.workflows.announcement.status = "result_ready";
  repository.files.set(`sessions/${session.id}.json`, stored);
  assert.equal((await domain.getSession(session.id)).workflows.announcement.outputs[0].recipeSnapshotRef, legacy.recipeSnapshotRef);
});

test("purge writes a tombstone, removes only its release/drafts, and catalog rebuild reports orphans", async () => {
  const { repository, domain, session } = await finalizedFixture();
  await domain.saveDraft(session.id, "announcement", {
    schemaVersion: 1, expectedDraftRevision: 0, expectedSourceSessionRevision: session.revision,
    payloadSchema: "announcement/v1", payload: { trackIds: [IDS.track] }, idempotencyKey: `${KEY}:draft-purge`
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

function publicationBody(session, bytes, key = `${KEY}:publication`, ids = { output: IDS.output, blob: IDS.outputBlob }) {
  const chunks = [];
  for (let offset = 0; offset < bytes.length; offset += 4) chunks.push(bytes.subarray(offset, offset + 4));
  return {
    chunks,
    body: {
      schemaVersion: 1, expectedRevision: session.revision, expectedDraftRevision: 1, idempotencyKey: key,
      plan: {
        outputId: ids.output, blobId: ids.blob, processorVersion: "s07-v1", sizeBytes: bytes.length, sha256: sha(bytes),
        parts: chunks.map((part, index) => ({ partNumber: index + 1, sizeBytes: part.length, sha256: sha(part), assetName: assetName(ids.blob, index + 1) })),
        recipe: {
          sourceSessionRevision: session.revision,
          sources: [{ trackId: IDS.track, blobId: IDS.blob, ordinal: 1, sizeBytes: Buffer.from("source-audio").length,
            sha256: sha(Buffer.from("source-audio")), mediaType: "audio/wav" }],
          draft: { revision: 1, payloadSchema: "announcement/v1", payload: { trackIds: [IDS.track] } },
          processing: { mode: "processed_single", silenceThresholdDb: -45, minimumSilenceSeconds: 2,
            retainedSilenceSeconds: 0.35, detectedIntervals: [[2, 5]], removalRanges: [[2.175, 4.825]],
            mix: null, limiter: null, codec: { name: "libmp3lame", bitrate: "128k" } },
          result: { mediaType: "audio/mpeg", presentationFilename: "source-edited.mp3", sizeBytes: bytes.length,
            sha256: sha(bytes), originalDurationSeconds: 8, resultDurationSeconds: 5.35, removedDurationSeconds: 2.65, pauseCount: 1 }
        }
      }
    }
  };
}

async function announcementFixture() {
  const fixture = await finalizedFixture();
  const saved = await fixture.domain.saveDraft(fixture.session.id, "announcement", {
    schemaVersion: 1, expectedDraftRevision: 0, expectedSourceSessionRevision: fixture.session.revision,
    payloadSchema: "announcement/v1", payload: { trackIds: [IDS.track] }, idempotencyKey: `${KEY}:announcement-draft`
  });
  return { ...fixture, session: saved.session, draft: saved.draft };
}

test("Announcement publication reserves once, finalizes atomically, and verifies stored bytes", async () => {
  const { repository, domain, session } = await announcementFixture();
  const resultBytes = Buffer.from("result-mp3");
  const publication = publicationBody(session, resultBytes);
  const started = await domain.beginAnnouncementPublication(session.id, publication.body);
  assert.equal(started.reservedVersion, 1);
  assert.equal((await domain.getSession(session.id)).workflows.announcement.outputs.length, 0);
  assert.deepEqual(await domain.beginAnnouncementPublication(session.id, publication.body), started);
  await assert.rejects(() => domain.beginAnnouncementPublication(session.id, {
    ...publication.body, plan: { ...publication.body.plan, processorVersion: "s07-changed" }
  }), (error) => error.status === 409 && /mismatch/.test(error.message));
  for (const [index, bytes] of publication.chunks.entries()) {
    await domain.uploadAnnouncementPart(started.transactionId, IDS.outputBlob, index + 1, bytes, sha(bytes), `${KEY}:publication-part:${index}`);
  }
  const finalized = await domain.finalizeAnnouncementPublication(started.transactionId);
  assert.equal(finalized.output.version, 1);
  assert.equal(finalized.job.state, "finalized");
  assert.equal((await domain.getSession(session.id)).workflows.announcement.status, "result_ready");
  assert.equal((await domain.finalizeAnnouncementPublication(started.transactionId)).idempotent, true);
  assert.deepEqual((await domain.getAnnouncementOutput(session.id, IDS.output)).recipe.result.sha256, sha(resultBytes));
  const downloaded = [];
  for (let part = 1; part <= publication.chunks.length; part++) {
    downloaded.push((await domain.downloadAnnouncementPart(session.id, IDS.output, IDS.outputBlob, part)).bytes);
  }
  assert.deepEqual(Buffer.concat(downloaded), resultBytes);
  const firstAsset = finalized.output.parts[0].assetId;
  repository.assetBytes.set(firstAsset, Buffer.from("xxxx"));
  await assert.rejects(() => domain.downloadAnnouncementPart(session.id, IDS.output, IDS.outputBlob, 1), (error) => error.status === 409);
  repository.assetBytes.set(firstAsset, Buffer.from(publication.chunks[0]));
  const current = await domain.getSession(session.id);
  const deleted = await domain.deleteOutputVersion(session.id, "announcement", 1, {
    expectedRevision: current.revision, idempotencyKey: `${KEY}:delete-published`, confirmation: ""
  });
  assert.equal(deleted.session.sourceTracks.length, 1);
  assert.equal(deleted.session.workflows.speaker.outputs.length, 0);
  assert.equal(deleted.session.workflows.announcement.nextVersion, 2);
  assert.equal(deleted.session.workflows.announcement.status, "in_progress");
  assert.equal(repository.files.has(`recipes/${session.id}/announcement/${IDS.output}.json`), false);
});

test("Announcement publication replays the legacy S08B transaction identity", async () => {
  const { repository, domain, session } = await announcementFixture();
  const idempotencyKey = `${KEY}:legacy-announcement-publication`;
  const publication = publicationBody(session, Buffer.from("legacy-result"), idempotencyKey);
  const legacyTransactionId = uuidFromIdempotencyKey(`publication:${session.id}:${idempotencyKey}`);
  const incompatiblePrefixedId = uuidFromIdempotencyKey(`publication:announcement:${session.id}:${idempotencyKey}`);
  const started = await domain.beginAnnouncementPublication(session.id, publication.body);
  assert.equal(started.transactionId, legacyTransactionId);
  assert.equal(repository.files.has(`transactions/publish-${legacyTransactionId}.json`), true);
  assert.equal(repository.files.has(`transactions/publish-${incompatiblePrefixedId}.json`), false);
  assert.deepEqual(await domain.beginAnnouncementPublication(session.id, publication.body), started);
  assert.equal((await domain.getSession(session.id)).workflows.announcement.nextVersion, 2);
});

test("Announcement upload failures persist only bounded safe metadata and retry the same reserved job", async () => {
  const { repository, domain, session } = await announcementFixture();
  const publication = publicationBody(session, Buffer.from("result-mp3"));
  const started = await domain.beginAnnouncementPublication(session.id, publication.body);
  const upload = repository.uploadReleaseAsset.bind(repository);
  repository.uploadReleaseAsset = async () => { throw new Error("provider https://private.invalid token=secret body=/tmp/output.bin"); };

  await assert.rejects(() => domain.uploadAnnouncementPart(started.transactionId, IDS.outputBlob, 1,
    publication.chunks[0], sha(publication.chunks[0]), `${KEY}:failed-upload`), /private\.invalid/);

  const path = `transactions/publish-${started.transactionId}.json`;
  let job = repository.files.get(path);
  assert.deepEqual(job.failure, {
    code: "upload_failed", message: "Announcement part upload failed; retry is safe.", at: "2026-01-02T03:04:05.000Z"
  });
  assert.equal(JSON.stringify(job).includes("private.invalid"), false);
  assert.equal(JSON.stringify(job).includes("secret"), false);
  assert.deepEqual((await domain.getAnnouncementPublication(started.transactionId)).failure, job.failure);
  assert.deepEqual((await domain.listIncomplete()).transactions.find((item) => item.transactionId === started.transactionId).failure, job.failure);

  repository.uploadReleaseAsset = upload;
  for (const [index, bytes] of publication.chunks.entries()) {
    await domain.uploadAnnouncementPart(started.transactionId, IDS.outputBlob, index + 1, bytes, sha(bytes), `${KEY}:retry-upload:${index}`);
    job = repository.files.get(path);
    assert.equal(job.failure, null);
    assert.equal(job.reservedVersion, 1);
  }
  const finalized = await domain.finalizeAnnouncementPublication(started.transactionId);
  assert.equal(finalized.job.transactionId, started.transactionId);
  assert.equal(finalized.output.version, 1);
  assert.equal((await domain.getSession(session.id)).workflows.announcement.nextVersion, 2);
});

test("Announcement finalize failures remain safely recoverable without reserving another version", async () => {
  const { repository, domain, session } = await announcementFixture();
  const publication = publicationBody(session, Buffer.from("result-mp3"));
  const started = await domain.beginAnnouncementPublication(session.id, publication.body);
  for (const [index, bytes] of publication.chunks.entries()) {
    await domain.uploadAnnouncementPart(started.transactionId, IDS.outputBlob, index + 1, bytes, sha(bytes), `${KEY}:finalize-part:${index}`);
  }
  const download = repository.downloadReleaseAsset.bind(repository);
  repository.downloadReleaseAsset = async () => { throw new Error("provider body cookie=secret https://private.invalid/asset"); };

  await assert.rejects(() => domain.finalizeAnnouncementPublication(started.transactionId), /private\.invalid/);

  const path = `transactions/publish-${started.transactionId}.json`;
  let job = repository.files.get(path);
  assert.deepEqual(job.failure, {
    code: "finalize_failed", message: "Announcement finalization failed; retry or discard is required.", at: "2026-01-02T03:04:05.000Z"
  });
  assert.equal(JSON.stringify(job).includes("cookie"), false);
  assert.equal(JSON.stringify(job).includes("private.invalid"), false);
  assert.equal(job.reservedVersion, 1);

  repository.downloadReleaseAsset = download;
  const recovered = await domain.recoverIncomplete(started.transactionId, "retry");
  job = repository.files.get(path);
  assert.equal(recovered.job.transactionId, started.transactionId);
  assert.equal(recovered.output.version, 1);
  assert.equal(job.failure, null);
  assert.equal(job.state, "finalized");
  assert.equal((await domain.getSession(session.id)).workflows.announcement.nextVersion, 2);
});

test("cancelled publications block destruction until discard and reserved versions are burned", async () => {
  const { domain, session } = await announcementFixture();
  const first = publicationBody(session, Buffer.from("result-one"));
  const started = await domain.beginAnnouncementPublication(session.id, first.body);
  await assert.rejects(() => domain.recoverIncomplete(started.transactionId, "resume"),
    (error) => error.status === 409 && /Local processor result/.test(error.message));
  await domain.cancelAnnouncementPublication(started.transactionId, { idempotencyKey: `${KEY}:cancel` });
  const current = await domain.getSession(session.id);
  assert.equal((await domain.dependencyPreview(session.id)).pendingAnnouncementPublications, 1);
  await assert.rejects(() => domain.setLifecycle(session.id, "archived", { expectedRevision: current.revision, idempotencyKey: `${KEY}:archive-blocked` }), /pending/);
  const discarded = await domain.cancelAnnouncementPublication(started.transactionId, { idempotencyKey: `${KEY}:discard` }, true);
  assert.equal(discarded.job.state, "discarded");
  assert.equal(discarded.session.workflows.announcement.nextVersion, 2);
  const secondIds = { output: "77777777-7777-4777-8777-777777777777", blob: "88888888-8888-4888-8888-888888888888" };
  const second = publicationBody(discarded.session, Buffer.from("result-two"), `${KEY}:publication-two`, secondIds);
  const reserved = await domain.beginAnnouncementPublication(session.id, second.body);
  assert.equal(reserved.reservedVersion, 2);
  assert.equal((await domain.listIncomplete()).transactions.some((job) => job.kind === "publication" && job.reservedVersion === 2), true);
});

test("passthrough publication accepts only exact source bytes, hash, size, and media type", async () => {
  const { domain, session } = await announcementFixture();
  const sourceBytes = Buffer.from("source-audio");
  const exact = publicationBody(session, sourceBytes);
  exact.body.plan.recipe.processing = { mode: "passthrough", silenceThresholdDb: -45, minimumSilenceSeconds: 2,
    retainedSilenceSeconds: 0.35, detectedIntervals: [], removalRanges: [], mix: null, limiter: null, codec: null };
  exact.body.plan.recipe.result = { mediaType: "audio/wav", presentationFilename: "source.wav", sizeBytes: sourceBytes.length,
    sha256: sha(sourceBytes), originalDurationSeconds: 3, resultDurationSeconds: 3, removedDurationSeconds: 0, pauseCount: 0 };
  assert.equal((await domain.beginAnnouncementPublication(session.id, exact.body)).reservedVersion, 1);

  const other = await announcementFixture();
  const changed = publicationBody(other.session, Buffer.from("different"), `${KEY}:passthrough-changed`, {
    output: "99999999-9999-4999-8999-999999999999", blob: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
  });
  changed.body.plan.recipe.processing = exact.body.plan.recipe.processing;
  changed.body.plan.recipe.result = { ...exact.body.plan.recipe.result, sizeBytes: changed.body.plan.sizeBytes, sha256: changed.body.plan.sha256 };
  await assert.rejects(() => other.domain.beginAnnouncementPublication(other.session.id, changed.body),
    (error) => error.status === 409 && /byte-identical/.test(error.message));
});

test("Archived Source Sessions deny new Announcement publication until explicit restore", async () => {
  const { domain, session } = await announcementFixture();
  const archived = await domain.setLifecycle(session.id, "archived", { expectedRevision: session.revision, idempotencyKey: `${KEY}:archive-announcement` });
  const denied = publicationBody(archived, Buffer.from("result-mp3"), `${KEY}:archived-publication`);
  await assert.rejects(() => domain.beginAnnouncementPublication(session.id, denied.body),
    (error) => error.status === 409 && /restored/.test(error.message));
  const restored = await domain.setLifecycle(session.id, "incoming", { expectedRevision: archived.revision, idempotencyKey: `${KEY}:restore-announcement` });
  const allowed = publicationBody(restored, Buffer.from("result-mp3"), `${KEY}:restored-publication`);
  assert.equal((await domain.beginAnnouncementPublication(session.id, allowed.body)).reservedVersion, 1);
});
