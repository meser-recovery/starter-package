import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { AudioArchiveGateway, sha256Hex, validateSpeakerProjectHistory, verifySpeakerProjectState, verifyLocalSourceAttachment } from "../../scripts/audio-archive-client.mjs";
import { parseEditorIntent, deletionImpact, RequestGeneration } from "../../scripts/audio-archive-core.mjs";

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

test("S09D capability gate preserves old gateway mode and enables only exact version 1", async () => {
  const configurations = [{ acceptedPartSize: 4 }, { acceptedPartSize: 4, speakerProjectHistory: 1 }];
  const fetchImpl = async () => new Response(JSON.stringify(configurations.shift()), { status: 200, headers: { "Content-Type": "application/json" } });
  const gateway = new AudioArchiveGateway("https://archive.example", fetchImpl);
  await gateway.configuration(); assert.equal(gateway.speakerProjectHistoryVersion, 0);
  await assert.rejects(() => gateway.speakerProjectHistory(sessionId), /не поддерживается/);
  await gateway.configuration(); assert.equal(gateway.speakerProjectHistoryVersion, 1);
});

test("S09D deletion copy retains project states and request generation fences late responses", () => {
  const preview = { sourceTracks: 1, announcementVersions: 0, speakerVersions: 1, drafts: 1, speakerProjectStates: 3 };
  assert.match(deletionImpact(preview, { kind: "sources" }).retained, /История проекта \(3\)/);
  assert.match(deletionImpact(preview, { kind: "output-version", workflow: "speaker", version: 1 }).retained, /не удаляет состояние проекта/);
  const generation = new RequestGeneration(), old = generation.next(), latest = generation.next();
  assert.equal(generation.current(old), false); assert.equal(generation.current(latest), true);
});
