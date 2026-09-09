import test from "node:test";
import assert from "node:assert/strict";
import { AudioArchiveDomain } from "../src/domain.mjs";
import { assetName, validateSpeakerPublicationPlan, validateSpeakerRecipe } from "../src/validation.mjs";
import { IDS, MemoryRepository, sha } from "./helpers.mjs";

const KEY = "speaker-save-key-0123456789";
const CLOCK = () => Date.parse("2026-09-08T12:00:00.000Z");
const OUTPUT = "77777777-7777-4777-8777-777777777777";
const OUTPUT_BLOB = "88888888-8888-4888-8888-888888888888";

function draftPayload() {
  return { trackIds: [IDS.track], excludedTrackIds: [], globalCuts: [], trackSilenceRegions: [],
    trackProcessing: [{ trackId: IDS.track, enhancement: "gentle", leveling: "on", compression: "light" }] };
}

async function fixture(repository = new MemoryRepository()) {
  const domain = new AudioArchiveDomain(repository, { acceptedPartBytes: 4, clock: CLOCK });
  const source = Buffer.from("source-audio");
  const sourceParts = [source.subarray(0, 4), source.subarray(4, 8), source.subarray(8)];
  const start = await domain.beginIngestion({ schemaVersion: 1, idempotencyKey: `${KEY}:ingest`, title: "Спикер",
    recordedAt: null, origin: "manual", supersedesSessionId: null, plan: { totalBytes: source.length, tracks: [{
      trackId: IDS.track, blobId: IDS.blob, ordinal: 1, originalName: "source.wav", mediaType: "audio/wav", sizeBytes: source.length,
      sha256: sha(source), parts: sourceParts.map((bytes, index) => ({ partNumber: index + 1, sizeBytes: bytes.length,
        sha256: sha(bytes), assetName: assetName(IDS.blob, index + 1) })) }] } });
  for (const [index, bytes] of sourceParts.entries()) await domain.uploadPart(start.transactionId, IDS.blob, index + 1, bytes, sha(bytes), `${KEY}:source:${index}`);
  const ingested = await domain.finalizeIngestion(start.transactionId);
  const saved = await domain.saveDraft(ingested.session.id, "speaker", { schemaVersion: 1, expectedDraftRevision: 0,
    expectedSourceSessionRevision: ingested.session.revision, payloadSchema: "speaker/v1", payload: draftPayload(), idempotencyKey: `${KEY}:draft` });
  return { repository, domain, session: saved.session, draft: saved.draft, source };
}

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

class ControlledRepository extends MemoryRepository {
  constructor() {
    super();
    this.commitGate = null;
    this.interruptDelete = false;
  }

  pauseAfterCommit(messagePrefix) {
    this.commitGate = { messagePrefix, entered: deferred(), release: deferred() };
    return this.commitGate;
  }

  async commitJson(expectedHead, files, message) {
    const result = await super.commitJson(expectedHead, files, message);
    if (this.commitGate?.messagePrefix && message.startsWith(this.commitGate.messagePrefix)) {
      const gate = this.commitGate;
      this.commitGate = null;
      gate.entered.resolve();
      await gate.release.promise;
    }
    return result;
  }

  async deleteAsset(assetId) {
    await super.deleteAsset(assetId);
    if (this.interruptDelete) {
      this.interruptDelete = false;
      throw new Error("simulated interrupted discard");
    }
  }
}

async function beginUploadedSpeakerSave(domain, session, key = `${KEY}:race`) {
  const save = saveBody(session, Buffer.from("speaker-result"), key);
  const started = await domain.beginSpeakerPublication(session.id, save.body);
  for (const [index, chunk] of save.chunks.entries()) {
    await domain.uploadSpeakerPart(started.transactionId, OUTPUT_BLOB, index + 1, chunk, sha(chunk), `${key}:part:${index}`);
  }
  return { save, started };
}

function saveBody(session, bytes = Buffer.from("speaker-result"), key = `${KEY}:save`, outputId = OUTPUT, blobId = OUTPUT_BLOB) {
  const chunks = [];
  for (let offset = 0; offset < bytes.length; offset += 4) chunks.push(bytes.subarray(offset, offset + 4));
  const payload = draftPayload();
  const sources = [{ trackId: IDS.track, blobId: IDS.blob, ordinal: 1, originalFilename: "source.wav", mediaType: "audio/wav",
    sizeBytes: Buffer.from("source-audio").length, sha256: sha(Buffer.from("source-audio")) }];
  const result = { mediaType: "audio/mpeg", presentationFilename: "speaker-speaker.mp3", sizeBytes: bytes.length, sha256: sha(bytes),
    originalDurationSeconds: 10, resultDurationSeconds: 10, globallyRemovedDurationSeconds: 0 };
  const renderer = { sampleRate: 48000, enhancement: "highpass=f=80,lowpass=f=16000",
    loudnorm: { integratedLufs: -19, truePeakDb: -3, loudnessRangeLufs: 11,
      measurements: [{ trackId: IDS.track, measured_I: -24, measured_TP: -5, measured_LRA: 4, measured_thresh: -34, offset: 0.2 }] },
    compression: {
      light: "acompressor=threshold=0.177828:ratio=2:attack=20:release=250:knee=2:makeup=1.25",
      medium: "acompressor=threshold=0.125893:ratio=3:attack=15:release=300:knee=2.5:makeup=1.5",
      strong: "acompressor=threshold=0.089125:ratio=4:attack=10:release=350:knee=3:makeup=1.75"
    }, mix: "amix=duration=longest:normalize=0", limiter: "alimiter=limit=0.95:level=0:latency=1",
    codec: { name: "libmp3lame", bitrate: "128k" } };
  return { chunks, body: { schemaVersion: 1, expectedRevision: session.revision, expectedDraftRevision: 1, idempotencyKey: key,
    plan: { outputId, blobId, processorVersion: "speaker-editor-v1", sizeBytes: bytes.length, sha256: sha(bytes),
      parts: chunks.map((chunk, index) => ({ partNumber: index + 1, sizeBytes: chunk.length, sha256: sha(chunk), assetName: assetName(blobId, index + 1) })),
      recipe: { renderedAt: "2026-09-08T11:59:00.000Z", sourceSessionRevision: session.revision,
        draft: { revision: 1, payloadSchema: "speaker/v1", payload }, sources,
        editState: { orderedTrackIds: payload.trackIds, includedTrackIds: payload.trackIds, excludedTrackIds: [], globalCuts: [],
          trackSilenceRegions: [], trackProcessing: payload.trackProcessing }, renderer, candidateFingerprint: sha(Buffer.from("candidate")), result } } } };
}

test("Speaker recipe and save plan are strict, versioned, and require a non-zero canonical draft", async () => {
  const { domain, session } = await fixture();
  const save = saveBody(session);
  assert.equal(validateSpeakerPublicationPlan(save.body.plan, 4).processorVersion, "speaker-editor-v1");
  const recipe = { schemaVersion: 1, workflow: "speaker", sessionId: session.id, outputId: OUTPUT, version: 1,
    processorVersion: "speaker-editor-v1", createdAt: "2026-09-08T12:00:00.000Z", ...save.body.plan.recipe };
  assert.equal(validateSpeakerRecipe(recipe).draft.revision, 1);
  await assert.rejects(async () => validateSpeakerRecipe({ ...recipe, unexpected: true }), /unsupported fields/);
  await assert.rejects(async () => validateSpeakerPublicationPlan({ ...save.body.plan,
    recipe: { ...save.body.plan.recipe, draft: { ...save.body.plan.recipe.draft, revision: 0 } } }, 4), /revision/);
  const spoofedSource = structuredClone(save.body);
  spoofedSource.plan.recipe.sources[0].originalFilename = "different.wav";
  await assert.rejects(() => domain.beginSpeakerPublication(session.id, spoofedSource),
    (error) => error.status === 409 && /provenance/.test(error.message));
});

test("Speaker save reserves independently, uploads exact parts, finalizes once, restores after source deletion, and deletes without reuse", async () => {
  const { repository, domain, session } = await fixture();
  const bytes = Buffer.from("speaker-result");
  const save = saveBody(session, bytes);
  const started = await domain.beginSpeakerPublication(session.id, save.body);
  assert.equal(started.reservedVersion, 1);
  assert.equal((await domain.getSession(session.id)).workflows.announcement.nextVersion, 1);
  assert.deepEqual(await domain.beginSpeakerPublication(session.id, save.body), started);
  await assert.rejects(() => domain.beginSpeakerPublication(session.id, { ...save.body, expectedDraftRevision: 2 }), (error) => error.status === 409);
  for (const [index, chunk] of save.chunks.entries()) {
    const first = await domain.uploadSpeakerPart(started.transactionId, OUTPUT_BLOB, index + 1, chunk, sha(chunk), `${KEY}:part:${index}`);
    const replay = await domain.uploadSpeakerPart(started.transactionId, OUTPUT_BLOB, index + 1, chunk, sha(chunk), `${KEY}:part:${index}`);
    assert.equal(replay.assetId, first.assetId);
  }
  const finalized = await domain.finalizeSpeakerPublication(started.transactionId);
  assert.equal(finalized.output.version, 1);
  assert.equal((await domain.finalizeSpeakerPublication(started.transactionId)).idempotent, true);
  assert.equal((await domain.getSession(session.id)).workflows.speaker.status, "result_ready");
  const metadata = await domain.getSpeakerOutput(session.id, OUTPUT);
  assert.equal(metadata.recipe.candidateFingerprint, sha(Buffer.from("candidate")));
  const restored = [];
  for (let part = 1; part <= save.chunks.length; part++) restored.push((await domain.downloadSpeakerPart(session.id, OUTPUT, OUTPUT_BLOB, part)).bytes);
  assert.deepEqual(Buffer.concat(restored), bytes);
  const beforeSources = await domain.getSession(session.id);
  const sourceDeleted = await domain.deleteSources(session.id, { expectedRevision: beforeSources.revision, idempotencyKey: `${KEY}:sources`,
    confirmation: "Удалить исходники, сохранить результаты" });
  assert.equal(sourceDeleted.session.workflows.speaker.outputs.length, 1);
  assert.deepEqual(Buffer.concat(await Promise.all(save.chunks.map(async (_, index) => (await domain.downloadSpeakerPart(session.id, OUTPUT, OUTPUT_BLOB, index + 1)).bytes))), bytes);
  const deleted = await domain.deleteOutputVersion(session.id, "speaker", 1, { expectedRevision: sourceDeleted.session.revision,
    idempotencyKey: `${KEY}:delete-version`, confirmation: "" });
  assert.equal(deleted.session.workflows.speaker.status, "in_progress");
  assert.equal(deleted.session.workflows.speaker.nextVersion, 2);
  assert.deepEqual(deleted.session.workflows.speaker.deletedVersions, [1]);
  assert.equal(repository.files.has(`recipes/${session.id}/speaker/${OUTPUT}.json`), false);
});

test("Speaker cancelled jobs recover only when complete; discard removes attributable assets and burns the version", async () => {
  const { repository, domain, session } = await fixture();
  const save = saveBody(session);
  const started = await domain.beginSpeakerPublication(session.id, save.body);
  await domain.uploadSpeakerPart(started.transactionId, OUTPUT_BLOB, 1, save.chunks[0], sha(save.chunks[0]), `${KEY}:partial`);
  await domain.cancelSpeakerPublication(started.transactionId, { idempotencyKey: `${KEY}:cancel` });
  await assert.rejects(() => domain.recoverIncomplete(started.transactionId, "resume"), /Local processor result/);
  const assetsBefore = repository.releases.get(1).assets.length;
  assert.equal(assetsBefore > 0, true);
  const discarded = await domain.cancelSpeakerPublication(started.transactionId, { idempotencyKey: `${KEY}:discard` }, true);
  assert.equal(discarded.job.state, "discarded");
  assert.equal(repository.releases.get(1).assets.some((asset) => asset.name.startsWith(`blob-${OUTPUT_BLOB}`)), false);
  assert.equal(discarded.session.workflows.speaker.nextVersion, 2);
  const next = saveBody(discarded.session, Buffer.from("second-result"), `${KEY}:second`,
    "99999999-9999-4999-8999-999999999999", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");
  assert.equal((await domain.beginSpeakerPublication(session.id, next.body)).reservedVersion, 2);
});

test("fully uploaded Speaker save finalizes after reload without local bytes and archived sessions deny new saves", async () => {
  const { domain, session } = await fixture();
  const save = saveBody(session);
  const started = await domain.beginSpeakerPublication(session.id, save.body);
  for (const [index, chunk] of save.chunks.entries()) await domain.uploadSpeakerPart(started.transactionId, OUTPUT_BLOB, index + 1, chunk, sha(chunk), `${KEY}:complete:${index}`);
  const ready = (await domain.listIncomplete()).transactions.find((job) => job.transactionId === started.transactionId);
  assert.equal(ready.canFinalize, true);
  assert.equal(ready.requiresLocalResult, false);
  assert.equal((await domain.recoverIncomplete(started.transactionId, "resume")).output.version, 1);
  const current = await domain.getSession(session.id);
  const archived = await domain.setLifecycle(session.id, "archived", { expectedRevision: current.revision, idempotencyKey: `${KEY}:archive` });
  const denied = saveBody(archived, Buffer.from("another-result"), `${KEY}:denied`,
    "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "cccccccc-cccc-4ccc-8ccc-cccccccccccc");
  denied.body.expectedDraftRevision = archived.workflows.speaker.currentDraft.revision;
  denied.body.plan.recipe.draft.revision = archived.workflows.speaker.currentDraft.revision;
  denied.body.plan.recipe.sourceSessionRevision = archived.revision;
  await assert.rejects(() => domain.beginSpeakerPublication(session.id, denied.body), (error) => error.status === 409 && /restored/.test(error.message));
});

test("Speaker finalize and discard are mutually exclusive when finalization commits first", async () => {
  const repository = new ControlledRepository();
  const { domain, session } = await fixture(repository);
  const { save, started } = await beginUploadedSpeakerSave(domain, session, `${KEY}:finalize-wins`);
  const gate = repository.pauseAfterCommit("Finalize speaker version");
  const finalizing = domain.finalizeSpeakerPublication(started.transactionId);
  await gate.entered.promise;
  await assert.rejects(
    () => domain.cancelSpeakerPublication(started.transactionId, { idempotencyKey: `${KEY}:discard-late` }, true),
    (error) => error.status === 409 && /finalized/i.test(error.message)
  );
  gate.release.resolve();
  const finalized = await finalizing;
  assert.equal(finalized.output.version, 1);
  const restored = await Promise.all(save.chunks.map(async (_, index) =>
    (await domain.downloadSpeakerPart(session.id, OUTPUT, OUTPUT_BLOB, index + 1)).bytes));
  assert.deepEqual(Buffer.concat(restored), Buffer.from("speaker-result"));
});

test("Speaker finalize and discard are mutually exclusive when discard claims first", async () => {
  const repository = new ControlledRepository();
  const { domain, session } = await fixture(repository);
  const { started } = await beginUploadedSpeakerSave(domain, session, `${KEY}:discard-wins`);
  const gate = repository.pauseAfterCommit("Claim speaker discard");
  const discarding = domain.cancelSpeakerPublication(started.transactionId, { idempotencyKey: `${KEY}:discard-first` }, true);
  await gate.entered.promise;
  await assert.rejects(
    () => domain.finalizeSpeakerPublication(started.transactionId),
    (error) => error.status === 409 && /discard/.test(error.message)
  );
  gate.release.resolve();
  const discarded = await discarding;
  assert.equal(discarded.job.state, "discarded");
  assert.equal(repository.releases.get(1).assets.some((asset) => asset.name.startsWith(`blob-${OUTPUT_BLOB}`)), false);
  assert.equal(repository.files.has(`recipes/${session.id}/speaker/${OUTPUT}.json`), false);
});

test("Speaker discard resumes safely after deletion is interrupted", async () => {
  const repository = new ControlledRepository();
  const { domain, session } = await fixture(repository);
  const { started } = await beginUploadedSpeakerSave(domain, session, `${KEY}:interrupted-discard`);
  repository.interruptDelete = true;
  await assert.rejects(
    () => domain.cancelSpeakerPublication(started.transactionId, { idempotencyKey: `${KEY}:discard-interrupted` }, true),
    /simulated interrupted discard/
  );
  assert.equal((await domain.getSpeakerPublication(started.transactionId)).state, "discarding");
  const discarded = await domain.cancelSpeakerPublication(started.transactionId, { idempotencyKey: `${KEY}:discard-retry` }, true);
  assert.equal(discarded.job.state, "discarded");
  assert.equal(discarded.session.workflows.speaker.nextVersion, 2);
  assert.equal(repository.releases.get(1).assets.some((asset) => asset.name.startsWith(`blob-${OUTPUT_BLOB}`)), false);
});

test("Speaker series deletion removes only its recipes and assets while retaining draft, sources, and counter", async () => {
  const { repository, domain, session } = await fixture();
  const identities = [
    [OUTPUT, OUTPUT_BLOB],
    ["99999999-9999-4999-8999-999999999999", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"],
  ];
  let current = session;
  for (const [index, [outputId, blobId]] of identities.entries()) {
    const save = saveBody(current, Buffer.from(`speaker-${index + 1}`), `${KEY}:series:${index}`, outputId, blobId);
    const started = await domain.beginSpeakerPublication(session.id, save.body);
    for (const [partIndex, chunk] of save.chunks.entries()) {
      await domain.uploadSpeakerPart(started.transactionId, blobId, partIndex + 1, chunk, sha(chunk), `${KEY}:series-part:${index}:${partIndex}`);
    }
    await domain.finalizeSpeakerPublication(started.transactionId);
    current = await domain.getSession(session.id);
  }
  const deleted = await domain.deleteOutputSeries(session.id, "speaker", { expectedRevision: current.revision,
    idempotencyKey: `${KEY}:delete-series`, confirmation: "" });
  assert.equal(deleted.session.workflows.speaker.outputs.length, 0);
  assert.deepEqual(deleted.session.workflows.speaker.deletedVersions, [1, 2]);
  assert.equal(deleted.session.workflows.speaker.nextVersion, 3);
  assert.equal(deleted.session.sourceState, "available");
  assert.equal((await domain.loadDraft(session.id, "speaker")).draftRevision, 1);
  for (const [outputId, blobId] of identities) {
    assert.equal(repository.files.has(`recipes/${session.id}/speaker/${outputId}.json`), false);
    assert.equal(repository.releases.get(1).assets.some((asset) => asset.name.startsWith(`blob-${blobId}`)), false);
  }
  assert.equal(repository.releases.get(1).assets.some((asset) => asset.name.startsWith(`blob-${IDS.blob}`)), true);
});
