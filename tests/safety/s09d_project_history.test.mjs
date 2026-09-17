import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { AudioArchiveGateway, sha256Hex, validateSpeakerProjectHistory, verifySpeakerProjectState, verifyLocalSourceAttachment } from "../../scripts/audio-archive-client.mjs";
import { parseEditorIntent, deletionImpact, RequestGeneration, createSpeakerRecoveryAttempt,
  recoveryContinuationRequest } from "../../scripts/audio-archive-core.mjs";
import { exactProjectStateForDraft, loadExactConflictProjectState, ProjectSave } from "../../scripts/audio-project.mjs";

if (!globalThis.crypto) globalThis.crypto = webcrypto;
const sessionId = "11111111-1111-4111-8111-111111111111";
const trackId = "22222222-2222-4222-8222-222222222222";
const blobId = "33333333-3333-4333-8333-333333333333";

const canonical = value => Array.isArray(value) ? value.map(canonical) : value && typeof value === "object" ?
  Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;

async function stateFixture(bytes = new TextEncoder().encode("exact bytes")) {
  const payload = { trackIds: [trackId], excludedTrackIds: [], globalCuts: [], trackSilenceRegions: [],
    trackProcessing: [{ trackId, enhancement: "off", leveling: "off", compression: "off" }] };
  const source = { trackId, blobId, ordinal: 1, originalName: "source.wav", mediaType: "audio/wav", sizeBytes: bytes.byteLength,
    sha256: await sha256Hex(bytes) };
  const value = { schemaVersion: 1, sessionId, workflow: "speaker", draftRevision: 4, sourceSessionRevision: 9,
    savedAt: "2026-09-15T10:00:00.000Z", payloadSchema: "speaker/v1", payload, sources: [source], stateFingerprint: "" };
  const identity = { sessionId, workflow: "speaker", draftRevision: 4, sourceSessionRevision: 9,
    payloadSchema: "speaker/v1", payload, sources: [source] };
  value.stateFingerprint = await sha256Hex(JSON.stringify(canonical(identity)));
  return { value, bytes };
}

test("S09D deep links accept exactly one strict Speaker recovery intent", () => {
  assert.deepEqual(parseEditorIntent(`?session=${sessionId}&workflow=speaker&projectRevision=12`),
    { sessionId, workflow: "speaker", projectRevision: 12 });
  assert.deepEqual(parseEditorIntent(`?session=${sessionId}&workflow=speaker&speakerOutput=${blobId}`),
    { sessionId, workflow: "speaker", speakerOutput: blobId });
  for (const query of [
    `?session=${sessionId}&workflow=speaker&projectRevision=1&speakerOutput=${blobId}`,
    `?session=${sessionId}&workflow=speaker&projectRevision=01`,
    `?session=${sessionId}&workflow=speaker&projectRevision=1&projectRevision=2`,
    `?session=${sessionId}&workflow=announcement&projectRevision=1`,
    `?session=${sessionId}&workflow=speaker&identity=unknown`
  ]) assert.throws(() => parseEditorIntent(query));
});

test("S09D recovery retries preserve ingestion key and the exact continuation request", () => {
  const source = { id: sessionId, revision: 7 };
  const target = { id: "44444444-4444-4444-8444-444444444444", revision: 3 };
  const keys = ["stable-ingestion-key", "stable-continuation-key"];
  const recovery = createSpeakerRecoveryAttempt(source, { continuation: { sourceDraftRevision: 4, sourceOutputId: null } }, () => keys.shift());
  assert.equal(recovery.ingestionKey, "stable-ingestion-key");
  assert.equal(recovery.ingestionKey, "stable-ingestion-key");
  const first = recoveryContinuationRequest(recovery, source, target);
  const retry = recoveryContinuationRequest(recovery, { ...source, revision: 8 }, { ...target, revision: 4 });
  assert.deepEqual(retry, first);
  assert.equal(retry.idempotencyKey, "stable-continuation-key");
  assert.equal(retry.expectedSourceSessionRevision, 7);
  assert.equal(retry.expectedTargetSessionRevision, 3);
});

test("S09D conflict-open retains only an exact immutable state and fences a late response", async () => {
  const { value: projectState } = await stateFixture();
  const session = { id: sessionId, sourceTracks: projectState.sources.map(source => ({ ...source })) };
  const draft = { draftRevision: projectState.draftRevision, payload: structuredClone(projectState.payload) };
  assert.equal(exactProjectStateForDraft(projectState, session, draft), true);
  assert.deepEqual(await loadExactConflictProjectState(async () => structuredClone(projectState), session, draft, null), projectState);
  assert.equal(exactProjectStateForDraft({ ...projectState, sources: [{ ...projectState.sources[0], sha256: "0".repeat(64) }] }, session, draft), false);

  let resolve;
  const pending = loadExactConflictProjectState(() => new Promise(done => { resolve = done; }), session, draft, null, () => false);
  resolve(structuredClone(projectState));
  await assert.rejects(pending, error => error.name === "AbortError");
});

test("S09D project states fail closed on fingerprint, identity and unknown fields", async () => {
  const { value } = await stateFixture();
  assert.equal((await verifySpeakerProjectState(value)).draftRevision, 4);
  await assert.rejects(() => verifySpeakerProjectState({ ...value, stateFingerprint: "0".repeat(64) }), /Fingerprint/);
  await assert.rejects(() => verifySpeakerProjectState({ ...value, unexpected: true }), /повреждено/);
  const changed = structuredClone(value); changed.payload.excludedTrackIds = [trackId];
  await assert.rejects(() => verifySpeakerProjectState(changed), /Fingerprint/);
});

test("S09D history summary is newest-first, unambiguous and version-aware", async () => {
  const { value } = await stateFixture();
  const item = revision => ({ draftRevision: revision, savedAt: value.savedAt, current: revision === 4,
    canonicalSourcesAvailable: true, canonicalEditingAvailable: true, stateFingerprint: value.stateFingerprint, finalVersions: [] });
  const history = { schemaVersion: 1, sessionId, workflow: "speaker", currentDraftRevision: 4,
    lifecycle: "incoming", sourceState: "available", states: [item(4), item(2)] };
  assert.deepEqual(validateSpeakerProjectHistory(history, sessionId).states.map(item => item.draftRevision), [4, 2]);
  assert.throws(() => validateSpeakerProjectHistory({ ...history, states: [item(2), item(4)] }, sessionId), /повреждена/);
  assert.throws(() => validateSpeakerProjectHistory({ ...history, states: [{ ...item(4), current: false }] }, sessionId), /неоднозначно/);
});

test("S09D exact local reattachment ignores filenames but rejects wrong, incomplete and duplicate-ambiguous sets", async () => {
  const { value, bytes } = await stateFixture();
  const renamed = new Blob([bytes], { type: "application/octet-stream" });
  Object.defineProperty(renamed, "name", { value: "renamed.mp3" });
  assert.deepEqual(await verifyLocalSourceAttachment([renamed], value.sources), [renamed]);
  await assert.rejects(() => verifyLocalSourceAttachment([], value.sources), /полный набор/);
  await assert.rejects(() => verifyLocalSourceAttachment([new Blob(["wrong bytes"])], value.sources), /не совпадают/);
  await assert.rejects(() => verifyLocalSourceAttachment([renamed, renamed], [value.sources[0], { ...value.sources[0], trackId: blobId, blobId: trackId, ordinal: 2 }]), /неоднозначные/);
});

test("S10 capability gate blocks every new Speaker mutation while retaining local work and safe reads", async () => {
  for (const capability of [undefined, 0, 2, "1", null]) {
    const calls = [];
    const fetchImpl = async (input, options = {}) => {
      calls.push({ url: String(input), method: options.method || "GET" });
      const payload = String(input).endsWith("/v1/config") ? { acceptedPartSize: 4, ...(capability === undefined ? {} : { speakerProjectHistory: capability }) } : {};
      return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
    };
    const gateway = new AudioArchiveGateway("https://archive.example", fetchImpl);
    await gateway.configuration();
    const localFile = new Blob(["source"]), localResult = new Blob(["result"], { type: "audio/mpeg" });
    const localProject = { cuts: [{ start: 1, end: 2 }] };
    assert.throws(() => gateway.saveDraft(sessionId, "speaker", {}), /несовместима/);
    await assert.rejects(() => gateway.saveSpeaker({ sessionId, blob: localResult, recipe: { schemaVersion: 1 } }), /несовместима/);
    assert.throws(() => gateway.continueSpeakerProject(sessionId, {}), /несовместима/);
    await assert.rejects(() => new ProjectSave(gateway).sources({ title: "local" }, [localFile]), /несовместима/);
    assert.equal(localFile.size, 6); assert.equal(localResult.size, 6); assert.deepEqual(localProject, { cuts: [{ start: 1, end: 2 }] });
    await gateway.getSpeakerOutput(sessionId, blobId);
    await gateway.saveDraft(sessionId, "announcement", {});
    assert.equal(calls.filter(call => call.method === "POST" || call.method === "PUT").length, 1);
    assert.match(calls.find(call => call.method === "PUT").url, /drafts\/announcement$/);
  }
});

test("S10 exact capability enables canonical Speaker writes but never recipe v1 finals", async () => {
  const calls = [];
  const fetchImpl = async (input, options = {}) => {
    calls.push({ url: String(input), method: options.method || "GET" });
    const payload = String(input).endsWith("/v1/config") ? { acceptedPartSize: 4, speakerProjectHistory: 1 } : {};
    return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
  };
  const gateway = new AudioArchiveGateway("https://archive.example", fetchImpl);
  await gateway.configuration();
  assert.equal(gateway.speakerProjectHistoryVersion, 1);
  await assert.rejects(() => gateway.saveSpeaker({ sessionId, blob: new Blob(["result"]), recipe: { schemaVersion: 1 } }), /неизменяемое состояние/);
  assert.equal(calls.some(call => call.method === "POST" || call.method === "PUT"), false);
});

test("S09D deletion copy retains project states and request generation fences late responses", () => {
  const preview = { sourceTracks: 1, announcementVersions: 0, speakerVersions: 1, drafts: 1, speakerProjectStates: 3 };
  assert.match(deletionImpact(preview, { kind: "sources" }).retained, /История проекта \(3\)/);
  assert.match(deletionImpact(preview, { kind: "output-version", workflow: "speaker", version: 1 }).retained, /не удаляет состояние проекта/);
  const generation = new RequestGeneration(), old = generation.next(), latest = generation.next();
  assert.equal(generation.current(old), false); assert.equal(generation.current(latest), true);
});
