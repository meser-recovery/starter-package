import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  SpeakerHistory, buildLevelingAnalysisFilter, buildSpeakerCandidate, buildSpeakerFilterGraph,
  buildTrackFilter, candidateAffectedBy, createSpeakerRenderSnapshot, defaultSpeakerPayload, mapSilenceToResult, microseconds,
  normalizeSpeakerPayload, originalToResultTime, parseLoudnormMeasurements, rebindSpeakerCandidate,
  removedDuration, resultDuration, SPEAKER_FRAME_TOLERANCE_SECONDS
} from "../../../scripts/speaker-editor-core.mjs";
import { SPEAKER_PAYLOAD_MAX_BYTES, validateAnnouncementDraftPayload, validateDraft, validateSpeakerDraftPayload } from "../src/validation.mjs";
import { IDS } from "./helpers.mjs";

const TRACK_2 = "77777777-7777-4777-8777-777777777777";
const BLOB_2 = "88888888-8888-4888-8888-888888888888";
const REGION_A = "99999999-9999-4999-8999-999999999999";
const REGION_B = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const REGION_C = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";

function payload() {
  const value = defaultSpeakerPayload([IDS.track, TRACK_2]);
  value.globalCuts = [
    { regionId: REGION_B, startSeconds: 2, endSeconds: 3 },
    { regionId: REGION_A, startSeconds: 1, endSeconds: 2.25 }
  ];
  value.trackSilenceRegions = [
    { regionId: REGION_C, trackId: TRACK_2, startSeconds: 4, endSeconds: 5 }
  ];
  return value;
}

test("regions use microseconds, stable union IDs, track identity, bounds, and original timeline mapping", () => {
  const normalized = normalizeSpeakerPayload(payload(), [IDS.track, TRACK_2], 10);
  assert.deepEqual(normalized.globalCuts, [{ regionId: REGION_A, startSeconds: 1, endSeconds: 3 }]);
  assert.equal(removedDuration(normalized.globalCuts), 2);
  assert.equal(resultDuration(10, normalized.globalCuts), 8);
  assert.equal(originalToResultTime(4, normalized.globalCuts), 2);
  assert.deepEqual(mapSilenceToResult(normalized.trackSilenceRegions[0], normalized.globalCuts), [[2, 3]]);
  assert.equal(microseconds(1.23456749), 1.234567);
  assert.throws(() => normalizeSpeakerPayload({ ...payload(), globalCuts: [{ regionId: REGION_A, startSeconds: 3, endSeconds: 3 }] }, [IDS.track, TRACK_2], 10));
  assert.throws(() => normalizeSpeakerPayload({ ...payload(), trackSilenceRegions: [{ regionId: REGION_C, trackId: crypto.randomUUID(), startSeconds: 1, endSeconds: 2 }] }, [IDS.track, TRACK_2], 10));
});

test("speaker/v1 validation is exact while announcement/v1 and legacy draft reads stay compatible", () => {
  const normalized = normalizeSpeakerPayload(payload(), [IDS.track, TRACK_2], 10);
  assert.deepEqual(validateSpeakerDraftPayload(normalized, [TRACK_2, IDS.track]).trackIds, [IDS.track, TRACK_2]);
  assert.deepEqual(validateAnnouncementDraftPayload({ trackIds: [IDS.track] }), { trackIds: [IDS.track] });
  assert.doesNotThrow(() => validateDraft({ schemaVersion: 1, sessionId: IDS.session, workflow: "speaker", draftRevision: 1,
    sourceSessionRevision: 1, savedAt: "2026-01-01T00:00:00.000Z", payloadSchema: "speaker-foundation/v1", payload: { markers: [1] } }));
  assert.throws(() => validateSpeakerDraftPayload({ ...normalized, surprise: true }));
  assert.throws(() => validateSpeakerDraftPayload({ ...normalized, excludedTrackIds: [IDS.track, IDS.track] }));
  assert.throws(() => validateSpeakerDraftPayload({ ...normalized, trackProcessing: normalized.trackProcessing.slice(1) }));
  assert.throws(() => validateSpeakerDraftPayload({ ...normalized, globalCuts: [{ ...normalized.globalCuts[0], startSeconds: 1.0000001 }] }));
  assert.equal(SPEAKER_PAYLOAD_MAX_BYTES < 1024 * 1024, true);
  const oversized = structuredClone(normalized);
  oversized.globalCuts = Array.from({ length: 10000 }, (_, index) => ({
    regionId: `${index.toString(16).padStart(8, "0")}-0000-4000-8000-000000000000`,
    startSeconds: index * 2, endSeconds: index * 2 + 1
  }));
  oversized.trackSilenceRegions = Array.from({ length: 10000 }, (_, index) => ({
    regionId: `${(index + 10000).toString(16).padStart(8, "0")}-0000-4000-8000-000000000000`, trackId: IDS.track,
    startSeconds: index * 2, endSeconds: index * 2 + 1
  }));
  assert.throws(() => validateSpeakerDraftPayload(oversized), /too large/);
});

test("Undo/Redo includes edit state, clears a Redo branch, and reset establishes a remote baseline", () => {
  const initial = defaultSpeakerPayload([IDS.track, TRACK_2]);
  const history = new SpeakerHistory(initial);
  const excluded = structuredClone(initial); excluded.excludedTrackIds = [TRACK_2]; history.commit(excluded);
  const enhanced = structuredClone(excluded); enhanced.trackProcessing[0].enhancement = "gentle"; history.commit(enhanced);
  assert.equal(history.canUndo, true); assert.equal(history.canRedo, false);
  assert.deepEqual(history.undo().excludedTrackIds, [TRACK_2]);
  assert.equal(history.canRedo, true);
  const reordered = structuredClone(history.value()); reordered.trackIds.reverse(); reordered.trackProcessing.reverse(); history.commit(reordered);
  assert.equal(history.canRedo, false);
  history.reset(initial); assert.equal(history.canUndo, false); assert.equal(history.canRedo, false);
});

test("centralized filters use identical cuts, equal-duration silence, every DSP enum, mix and limiter", () => {
  const normalized = normalizeSpeakerPayload(payload(), [IDS.track, TRACK_2], 10);
  const first = buildTrackFilter({ inputIndex: 0, trackId: IDS.track, duration: 10, payload: normalized, outputLabel: "one" });
  const second = buildTrackFilter({ inputIndex: 1, trackId: TRACK_2, duration: 10, payload: normalized, outputLabel: "two" });
  const cut = "gte(t,1.000000)*lt(t,3.000000)";
  assert.match(first, new RegExp(cut.replace(/[()*+.]/g, "\\$&")));
  assert.match(second, new RegExp(cut.replace(/[()*+.]/g, "\\$&")));
  assert.match(second, /volume=volume=0/);
  assert.ok(second.lastIndexOf("volume=volume=0") > second.lastIndexOf("acompressor="));
  assert.match(second, /apad=whole_len=480000,atrim=end=10\.000000/);
  for (const compression of ["light", "medium", "strong"]) {
    const variant = structuredClone(normalized); variant.trackProcessing[0] = { trackId: IDS.track, enhancement: "gentle", leveling: "off", compression };
    const graph = buildSpeakerFilterGraph(variant, 10);
    assert.match(graph, /highpass=f=80,lowpass=f=16000/); assert.match(graph, new RegExp(`acompressor=.*ratio=${compression === "light" ? 2 : compression === "medium" ? 3 : 4}`));
    assert.match(graph, /amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0\.95:level=0:latency=1/);
  }
  const leveled = structuredClone(normalized); leveled.trackProcessing[0].leveling = "on";
  assert.match(buildLevelingAnalysisFilter({ inputIndex: 0, trackId: IDS.track, duration: 10, payload: leveled }), /loudnorm=I=-19:TP=-3:LRA=11:print_format=json/);
  const measured = parseLoudnormMeasurements('{"input_i":"-24.1","input_tp":"-4","input_lra":"3","input_thresh":"-34","target_offset":"0.1"}');
  assert.match(buildSpeakerFilterGraph(leveled, 10, { [IDS.track]: measured }), /measured_I=-24\.1/);
  assert.throws(() => parseLoudnormMeasurements('{"input_i":"-inf"}'));
});

test("candidate hash, durations, invalidation, unchanged-save rebinding and frame tolerance are exact", async () => {
  const normalized = normalizeSpeakerPayload(payload(), [IDS.track, TRACK_2], 10);
  normalized.trackIds.reverse();
  normalized.trackProcessing.reverse();
  const bytes = new TextEncoder().encode("mp3-bytes");
  const blob = new Blob([bytes], { type: "audio/mpeg" });
  const session = { id: IDS.session, revision: 4, title: "Запись", sourceTracks: [
    { trackId: IDS.track, blobId: IDS.blob, ordinal: 1, originalName: "one.wav", mediaType: "audio/wav", sizeBytes: 10, sha256: "1".repeat(64) },
    { trackId: TRACK_2, blobId: BLOB_2, ordinal: 2, originalName: "two.wav", mediaType: "audio/wav", sizeBytes: 20, sha256: "2".repeat(64) }
  ] };
  const hash = async (input) => createHash("sha256").update(input).digest("hex");
  const snapshot = createSpeakerRenderSnapshot({ session, draftRevision: 0, payload: normalized, originalDurationSeconds: 10,
    tracks: [{ trackId: IDS.track, file: new Blob([new Uint8Array(10)]) }, { trackId: TRACK_2, file: new Blob([new Uint8Array(20)]) }] });
  const candidate = await buildSpeakerCandidate({ blob, snapshot,
    resultDurationSeconds: 8 + SPEAKER_FRAME_TOLERANCE_SECONDS / 2, sha256: hash });
  assert.equal(candidate.sha256, await hash(bytes)); assert.equal(candidate.sizeBytes, bytes.byteLength);
  assert.deepEqual(candidate.sources.map((source) => source.trackId), [TRACK_2, IDS.track]);
  assert.deepEqual(candidate.sources.map((source) => source.ordinal), [2, 1]);
  assert.equal(candidate.globallyRemovedDurationSeconds, 2); assert.equal(candidate.trackSilenceRegions.length, 1);
  assert.equal(rebindSpeakerCandidate(candidate, normalized, 5, 1).draftRevision, 1);
  normalized.excludedTrackIds = [TRACK_2]; session.revision = 99;
  assert.deepEqual(snapshot.payload.excludedTrackIds, []); assert.equal(snapshot.sourceSessionRevision, 4);
  assert.equal(Object.isFrozen(snapshot.payload), true); assert.equal(Object.isFrozen(snapshot.sources), true);
  const changed = structuredClone(snapshot.payload); changed.excludedTrackIds = [TRACK_2];
  assert.equal(rebindSpeakerCandidate(candidate, changed, 5, 1), null);
  for (const action of ["globalCuts", "trackSilenceRegions", "excludedTrackIds", "trackIds", "enhancement", "leveling", "compression", "sourceReplacement"]) assert.equal(candidateAffectedBy(action), true);
  for (const action of ["solo", "mute", "seek", "zoom", "pan", "follow"]) assert.equal(candidateAffectedBy(action), false);
  await assert.rejects(() => buildSpeakerCandidate({ blob, snapshot, resultDurationSeconds: 8.1, sha256: hash }));
});
