import assert from "node:assert/strict";
import { test } from "node:test";
import {
  defaultSpeakerPayload, normalizeSpeakerPayload, prepareLegacySpeakerPayload
} from "../../service/frontend/scripts/speaker-editor-core.mjs";

const tracks = [
  "11111111-1111-4111-8111-111111111111",
  "22222222-2222-4222-8222-222222222222",
  "33333333-3333-4333-8333-333333333333"
];
const validId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const invalidId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";

function legacyPayload() {
  const payload = defaultSpeakerPayload(tracks);
  payload.globalCuts = [
    { regionId: validId, startSeconds: 1, endSeconds: 2 },
    { regionId: invalidId, startSeconds: 9, endSeconds: 12 }
  ];
  payload.excludedTrackIds = [tracks[2]];
  return payload;
}

test("legacy out-of-bounds cut is retained for explicit resolution, not applied", () => {
  const source = legacyPayload();
  const original = structuredClone(source);
  assert.throws(() => normalizeSpeakerPayload(source, tracks, 10), /Глобальный вырез 2/);
  const prepared = prepareLegacySpeakerPayload(source, tracks, 10);
  assert.deepEqual(source, original, "the archived draft must remain untouched");
  assert.deepEqual(prepared.payload.globalCuts, [source.globalCuts[0]], "valid edits remain active");
  assert.deepEqual(prepared.payload.excludedTrackIds, [tracks[2]], "other valid edits remain active");
  assert.deepEqual(prepared.invalidGlobalCuts, [{ index: 2, region: source.globalCuts[1] }]);
  assert.notStrictEqual(prepared.invalidGlobalCuts[0].region, source.globalCuts[1]);
  assert.doesNotThrow(() => normalizeSpeakerPayload(prepared.payload, tracks, 10));
});

test("legacy tolerance does not accept malformed cuts or duplicate identities", () => {
  const malformed = legacyPayload();
  malformed.globalCuts[1].endSeconds = malformed.globalCuts[1].startSeconds;
  assert.throws(() => prepareLegacySpeakerPayload(malformed, tracks, 10));
  const duplicate = legacyPayload();
  duplicate.globalCuts[1].regionId = validId;
  assert.throws(() => prepareLegacySpeakerPayload(duplicate, tracks, 10));
  const negative = legacyPayload();
  negative.globalCuts[1].startSeconds = -1;
  assert.throws(() => prepareLegacySpeakerPayload(negative, tracks, 10));
  const valid = legacyPayload();
  valid.globalCuts[1].endSeconds = 9.5;
  assert.deepEqual(prepareLegacySpeakerPayload(valid, tracks, 10).invalidGlobalCuts, []);
});
