import test from "node:test";
import assert from "node:assert/strict";
import { AudioArchiveDomain } from "../src/domain.mjs";
import { assetName, computeProjectStateFingerprint, projectStatePath } from "../src/validation.mjs";
import { MemoryRepository, sha } from "./helpers.mjs";

const CLOCK = () => Date.parse("2026-09-15T10:00:00.000Z");
const SOURCE = Buffer.from("exact-speaker-source");
const ids = {
  trackA: "10000000-0000-4000-8000-000000000001", blobA: "10000000-0000-4000-8000-000000000002",
  trackB: "20000000-0000-4000-8000-000000000001", blobB: "20000000-0000-4000-8000-000000000002",
  output: "30000000-0000-4000-8000-000000000001", outputBlob: "30000000-0000-4000-8000-000000000002"
};

function payload(trackId, excluded = false) {
  return { trackIds: [trackId], excludedTrackIds: excluded ? [trackId] : [], globalCuts: [], trackSilenceRegions: [],
    trackProcessing: [{ trackId, enhancement: "off", leveling: "on", compression: "off" }] };
}

async function ingest(domain, key, trackId, blobId, supersedesSessionId = null, bytes = SOURCE) {
  const chunks = [];
  for (let offset = 0; offset < bytes.length; offset += 6) chunks.push(bytes.subarray(offset, Math.min(bytes.length, offset + 6)));
  const started = await domain.beginIngestion({ schemaVersion: 1, idempotencyKey: key, title: "Speaker source", recordedAt: null,
    origin: "device", supersedesSessionId, plan: { totalBytes: bytes.length, tracks: [{ trackId, blobId, ordinal: 1,
      originalName: "source.wav", mediaType: "audio/wav", sizeBytes: bytes.length, sha256: sha(bytes),
      parts: chunks.map((bytes, index) => ({ partNumber: index + 1, sizeBytes: bytes.length, sha256: sha(bytes), assetName: assetName(blobId, index + 1) })) }] } });
  for (const [index, bytes] of chunks.entries()) await domain.uploadPart(started.transactionId, blobId, index + 1, bytes, sha(bytes), `${key}:part:${index + 1}`);
  return (await domain.finalizeIngestion(started.transactionId)).session;
}

function saveEnvelope(session, draftRevision, nextPayload, key) {
  return { schemaVersion: 1, expectedDraftRevision: draftRevision, expectedSourceSessionRevision: session.revision,
    payloadSchema: "speaker/v1", payload: nextPayload, idempotencyKey: key };
}

async function fixture() {
  const repository = new MemoryRepository();
  const domain = new AudioArchiveDomain(repository, { acceptedPartBytes: 8, clock: CLOCK, speakerProjectHistory: true });
  const session = await ingest(domain, "s09d-source-a-0123456789", ids.trackA, ids.blobA);
  return { repository, domain, session };
}

test("S09D explicit saves atomically create immutable ordered states and exact replay never advances revision", async () => {
  const { repository, domain, session } = await fixture();
  const firstRequest = saveEnvelope(session, 0, payload(ids.trackA), "s09d-save-one-0123456789");
  const before = repository.commits.length;
  const first = await domain.saveDraft(session.id, "speaker", firstRequest);
  assert.equal(repository.commits.length, before + 1);
  assert.equal(first.draft.draftRevision, 1);
  assert.equal(first.state.draftRevision, 1);
  assert.equal(first.state.stateFingerprint.length, 64);
  assert.deepEqual(Object.keys(repository.commits.at(-1).files).filter(path => path.includes(session.id)).sort(), [
    `drafts/${session.id}/speaker.json`, `project-states/${session.id}/speaker/1.json`, `sessions/${session.id}.json`
  ]);

  const second = await domain.saveDraft(session.id, "speaker", saveEnvelope(first.session, 1, payload(ids.trackA, true), "s09d-save-two-0123456789"));
  const afterSecond = repository.commits.length;
  const replay = await domain.saveDraft(session.id, "speaker", firstRequest);
  assert.equal(replay.idempotent, true);
  assert.equal(replay.draft.draftRevision, 1);
  assert.equal(repository.commits.length, afterSecond);
  await assert.rejects(() => domain.saveDraft(session.id, "speaker", { ...firstRequest, payload: payload(ids.trackA, true) }),
    error => error.status === 409 && /mismatch/.test(error.message));

  const history = await domain.speakerProjectHistory(session.id);
  assert.deepEqual(history.states.map(state => [state.draftRevision, state.current]), [[2, true], [1, false]]);
  const restored = await domain.getSpeakerProjectState(session.id, 1);
  const third = await domain.saveDraft(session.id, "speaker", saveEnvelope(second.session, 2, restored.payload, "s09d-save-three-0123456789"));
  assert.equal(third.draft.draftRevision, 3);
  assert.deepEqual((await domain.speakerProjectHistory(session.id)).states.map(state => state.draftRevision), [3, 2, 1]);
  assert.deepEqual((await domain.getSpeakerProjectState(session.id, 2)).payload, payload(ids.trackA, true));
});

test("S09D stale devices conflict while local payload can be explicitly rebased into a new highest state", async () => {
  const { domain, session } = await fixture();
  const first = await domain.saveDraft(session.id, "speaker", saveEnvelope(session, 0, payload(ids.trackA), "s09d-device-a-0123456789"));
  const stale = saveEnvelope(first.session, 1, payload(ids.trackA, true), "s09d-device-b-0123456789");
  const second = await domain.saveDraft(session.id, "speaker", saveEnvelope(first.session, 1, payload(ids.trackA), "s09d-device-a2-0123456789"));
  await assert.rejects(() => domain.saveDraft(session.id, "speaker", stale), error => error.status === 409);
  const rebased = await domain.saveDraft(session.id, "speaker", saveEnvelope(second.session, 2, stale.payload, "s09d-device-b2-0123456789"));
  assert.equal(rebased.draft.draftRevision, 3);
  assert.deepEqual((await domain.getSpeakerProjectState(session.id, 2)).payload, payload(ids.trackA));
});

test("S09D concurrent exact save replay converges on one state", async () => {
  const { repository, domain, session } = await fixture();
  const request = saveEnvelope(session, 0, payload(ids.trackA), "s09d-concurrent-save-0123456789");
  const before = repository.commits.length;
  const [left, right] = await Promise.all([domain.saveDraft(session.id, "speaker", request), domain.saveDraft(session.id, "speaker", request)]);
  assert.equal(left.state.stateFingerprint, right.state.stateFingerprint);
  assert.equal(repository.commits.length, before + 1);
  assert.equal((await domain.speakerProjectHistory(session.id)).states.length, 1);
});

test("S09D a pre-existing immutable revision path cannot be overwritten", async () => {
  const { repository, domain, session } = await fixture();
  const first = await domain.saveDraft(session.id, "speaker", saveEnvelope(session, 0, payload(ids.trackA), "s09d-collision-one-0123456789"));
  repository.files.set(`project-states/${session.id}/speaker/2.json`, structuredClone(first.state));
  await assert.rejects(() => domain.saveDraft(session.id, "speaker", saveEnvelope(first.session, 1, payload(ids.trackA, true), "s09d-collision-two-0123456789")),
    error => error.status === 409 && /already exists/.test(error.message));
  assert.deepEqual(repository.files.get(`project-states/${session.id}/speaker/2.json`), first.state);
});

test("S09D continuation binds state provenance to available sources and deleted-source tombstones", async () => {
  const { repository, domain, session } = await fixture();
  const saved = await domain.saveDraft(session.id, "speaker", saveEnvelope(session, 0, payload(ids.trackA), "s09d-bind-save-0123456789"));
  const substitutedBytes = Buffer.from("substituted-speaker-source");
  const path = projectStatePath(session.id, 1);
  const substituted = structuredClone(saved.state);
  substituted.sources[0].sizeBytes = substitutedBytes.length;
  substituted.sources[0].sha256 = sha(substitutedBytes);
  substituted.stateFingerprint = computeProjectStateFingerprint(substituted);
  repository.files.set(path, substituted);
  const target = await ingest(domain, "s09d-bind-target-0123456789", ids.trackB, ids.blobB, session.id, substitutedBytes);
  const request = { schemaVersion: 1, expectedSourceSessionRevision: saved.session.revision, expectedTargetSessionRevision: target.revision,
    sourceDraftRevision: 1, sourceOutputId: null, targetSessionId: target.id, idempotencyKey: "s09d-bind-available-0123456789" };
  await assert.rejects(() => domain.continueSpeakerProject(session.id, request),
    error => error.status === 409 && /does not belong/.test(error.message));

  const deleted = await domain.deleteSources(session.id, { expectedRevision: saved.session.revision, idempotencyKey: "s09d-bind-delete-0123456789",
    confirmation: "Удалить исходники, сохранить результаты" });
  await assert.rejects(() => domain.continueSpeakerProject(session.id, { ...request, expectedSourceSessionRevision: deleted.session.revision,
    idempotencyKey: "s09d-bind-deleted-0123456789" }), error => error.status === 409 && /does not belong/.test(error.message));
  assert.equal((await domain.getSession(session.id)).relations.supersededBySessionId, null);
  assert.equal((await domain.getSession(target.id)).relations.supersedesSessionId, session.id);
});

test("S09D continuation cannot overwrite an orphan immutable state in the target session", async () => {
  const { repository, domain, session } = await fixture();
  const saved = await domain.saveDraft(session.id, "speaker", saveEnvelope(session, 0, payload(ids.trackA), "s09d-target-state-save-0123456789"));
  const target = await ingest(domain, "s09d-target-state-ingest-0123456789", ids.trackB, ids.blobB, session.id);
  const path = projectStatePath(target.id, 1);
  const orphan = domain.createSpeakerProjectState(target, 1, target.revision, "2026-09-15T10:00:00.000Z", payload(ids.trackB));
  repository.files.set(path, structuredClone(orphan));
  const beforeHead = await repository.getHead();
  await assert.rejects(() => domain.continueSpeakerProject(session.id, { schemaVersion: 1,
    expectedSourceSessionRevision: saved.session.revision, expectedTargetSessionRevision: target.revision,
    sourceDraftRevision: 1, sourceOutputId: null, targetSessionId: target.id, idempotencyKey: "s09d-target-state-continue-0123456789" }),
  error => error.status === 409 && /immutable Speaker project state/.test(error.message));
  assert.equal(await repository.getHead(), beforeHead);
  assert.equal(repository.files.get(path).stateFingerprint, orphan.stateFingerprint);
  assert.equal((await domain.getSession(session.id)).relations.supersededBySessionId, null);
});

test("S09D deleted-source recovery continues exact bytes in a new session with remapped IDs and bidirectional relations", async () => {
  const { domain, session } = await fixture();
  const saved = await domain.saveDraft(session.id, "speaker", saveEnvelope(session, 0, payload(ids.trackA), "s09d-origin-save-0123456789"));
  const deleted = await domain.deleteSources(session.id, { expectedRevision: saved.session.revision, idempotencyKey: "s09d-delete-source-0123456789",
    confirmation: "Удалить исходники, сохранить результаты" });
  const tombstone = structuredClone(deleted.session.deletedSources);
  const target = await ingest(domain, "s09d-source-b-0123456789", ids.trackB, ids.blobB, session.id);
  const request = { schemaVersion: 1, expectedSourceSessionRevision: deleted.session.revision, expectedTargetSessionRevision: target.revision,
    sourceDraftRevision: 1, sourceOutputId: null, targetSessionId: target.id, idempotencyKey: "s09d-continue-0123456789" };
  const continued = await domain.continueSpeakerProject(session.id, request);
  assert.equal(continued.sourceSession.relations.supersededBySessionId, target.id);
  assert.equal(continued.targetSession.relations.supersedesSessionId, session.id);
  assert.deepEqual(continued.state.payload.trackIds, [ids.trackB]);
  assert.equal(continued.state.draftRevision, 1);
  assert.deepEqual((await domain.getSession(session.id)).deletedSources, tombstone);
  assert.equal((await domain.speakerProjectHistory(session.id)).states.length, 1);
  assert.equal((await domain.continueSpeakerProject(session.id, request)).idempotent, true);
  await assert.rejects(() => domain.continueSpeakerProject(session.id, { ...request, sourceDraftRevision: 2 }), error => error.status === 409);
});

function renderer(trackId) {
  return { sampleRate: 48000, enhancement: "highpass=f=80,lowpass=f=16000",
    loudnorm: { integratedLufs: -19, truePeakDb: -3, loudnessRangeLufs: 11,
      measurements: [{ trackId, measured_I: -24, measured_TP: -5, measured_LRA: 4, measured_thresh: -34, offset: .2 }] },
    compression: { light: "acompressor=threshold=0.177828:ratio=2:attack=20:release=250:knee=2:makeup=1.25",
      medium: "acompressor=threshold=0.125893:ratio=3:attack=15:release=300:knee=2.5:makeup=1.5",
      strong: "acompressor=threshold=0.089125:ratio=4:attack=10:release=350:knee=3:makeup=1.75" },
    mix: "amix=duration=longest:normalize=0", limiter: "alimiter=limit=0.95:level=0:latency=1",
    codec: { name: "libmp3lame", bitrate: "128k" } };
}

function publication(session, state, statePayload = state.payload) {
  const bytes = Buffer.from("final");
  const source = state.sources[0];
  const recipeSources = [{ trackId: source.trackId, blobId: source.blobId, ordinal: source.ordinal, originalFilename: source.originalName,
    mediaType: source.mediaType, sizeBytes: source.sizeBytes, sha256: source.sha256 }];
  return { schemaVersion: 1, expectedRevision: session.revision, expectedDraftRevision: state.draftRevision,
    idempotencyKey: "s09d-final-save-0123456789", plan: { outputId: ids.output, blobId: ids.outputBlob,
      processorVersion: "speaker-editor-v1", sizeBytes: bytes.length, sha256: sha(bytes), parts: [{ partNumber: 1, sizeBytes: bytes.length,
        sha256: sha(bytes), assetName: assetName(ids.outputBlob, 1) }], recipe: { schemaVersion: 2, projectState: { sessionId: session.id,
        draftRevision: state.draftRevision, stateFingerprint: state.stateFingerprint }, renderedAt: "2026-09-15T09:59:00.000Z",
        sourceSessionRevision: session.revision, draft: { revision: state.draftRevision, payloadSchema: "speaker/v1", payload: statePayload },
        sources: recipeSources, editState: { orderedTrackIds: statePayload.trackIds, includedTrackIds: statePayload.trackIds.filter(id => !statePayload.excludedTrackIds.includes(id)),
          excludedTrackIds: statePayload.excludedTrackIds, globalCuts: statePayload.globalCuts, trackSilenceRegions: statePayload.trackSilenceRegions,
          trackProcessing: statePayload.trackProcessing }, renderer: renderer(source.trackId), candidateFingerprint: sha(Buffer.from("candidate")),
        result: { mediaType: "audio/mpeg", presentationFilename: "speaker.mp3", sizeBytes: bytes.length, sha256: sha(bytes),
          originalDurationSeconds: 10, resultDurationSeconds: 10, globallyRemovedDurationSeconds: 0 } } } };
}

test("S09D new Speaker finals require the exact current immutable state and fingerprint", async () => {
  const { repository, domain, session } = await fixture();
  const saved = await domain.saveDraft(session.id, "speaker", saveEnvelope(session, 0, payload(ids.trackA), "s09d-final-draft-0123456789"));
  const accepted = await domain.beginSpeakerPublication(session.id, publication(saved.session, saved.state));
  assert.equal(accepted.reservedVersion, 1);
  const other = await fixture();
  const otherSaved = await other.domain.saveDraft(other.session.id, "speaker", saveEnvelope(other.session, 0, payload(ids.trackA), "s09d-final-draft-abcdefghi"));
  const mismatched = publication(otherSaved.session, otherSaved.state);
  mismatched.plan.recipe.projectState.stateFingerprint = "0".repeat(64);
  await assert.rejects(() => other.domain.beginSpeakerPublication(other.session.id, mismatched), error => error.status === 409);
  repository.files.delete(`project-states/${session.id}/speaker/1.json`);
  const missing = publication(saved.session, saved.state); missing.idempotencyKey = "s09d-final-missing-0123456789";
  await assert.rejects(() => domain.beginSpeakerPublication(session.id, missing), error => error.status === 409 || error.status === 404);
});

test("S09D continuation from a new final resolves its exact state rather than MP3 bytes", async () => {
  const { domain, session } = await fixture();
  const saved = await domain.saveDraft(session.id, "speaker", saveEnvelope(session, 0, payload(ids.trackA), "s09d-final-source-0123456789"));
  const plan = publication(saved.session, saved.state);
  const started = await domain.beginSpeakerPublication(session.id, plan);
  const finalBytes = Buffer.from("final");
  await domain.uploadSpeakerPart(started.transactionId, ids.outputBlob, 1, finalBytes, sha(finalBytes), "s09d-final-part-0123456789");
  await domain.finalizeSpeakerPublication(started.transactionId);
  assert.deepEqual((await domain.speakerProjectHistory(session.id)).states[0].finalVersions.map(item => item.version), [1]);
  const finalSession = await domain.getSession(session.id);
  const deleted = await domain.deleteSources(session.id, { expectedRevision: finalSession.revision, idempotencyKey: "s09d-final-source-delete-0123456789",
    confirmation: "Удалить исходники, сохранить результаты" });
  const target = await ingest(domain, "s09d-final-target-0123456789", ids.trackB, ids.blobB, session.id);
  const continued = await domain.continueSpeakerProject(session.id, { schemaVersion: 1, expectedSourceSessionRevision: deleted.session.revision,
    expectedTargetSessionRevision: target.revision, sourceDraftRevision: null, sourceOutputId: ids.output,
    targetSessionId: target.id, idempotencyKey: "s09d-final-continue-0123456789" });
  assert.deepEqual(continued.state.payload.trackIds, [ids.trackB]);
  assert.deepEqual(continued.state.sources.map(source => source.sha256), [sha(SOURCE)]);
});

test("S09D source deletion retains states, output deletion cannot remove them, and purge removes them", async () => {
  const { repository, domain, session } = await fixture();
  const saved = await domain.saveDraft(session.id, "speaker", saveEnvelope(session, 0, payload(ids.trackA), "s09d-retention-0123456789"));
  assert.equal((await domain.dependencyPreview(session.id)).speakerProjectStates, 1);
  const deleted = await domain.deleteSources(session.id, { expectedRevision: saved.session.revision, idempotencyKey: "s09d-retain-delete-0123456789",
    confirmation: "Удалить исходники, сохранить результаты" });
  assert.equal(repository.files.has(`project-states/${session.id}/speaker/1.json`), true);
  await domain.purgeSession(session.id, { expectedRevision: deleted.session.revision, idempotencyKey: "s09d-purge-0123456789", confirmation: session.id });
  assert.equal(repository.files.has(`project-states/${session.id}/speaker/1.json`), false);
});
