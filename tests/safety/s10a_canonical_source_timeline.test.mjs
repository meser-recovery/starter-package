import assert from 'node:assert/strict';
import { test } from 'node:test';
import { canonicalSourceDuration, rebaseRecordingEnd, setRecordingBoundary } from '../../service/frontend/scripts/audio-project.mjs';
import { defaultSpeakerPayload, normalizeSpeakerPayload, prepareLegacySpeakerPayload } from '../../service/frontend/scripts/speaker-editor-core.mjs';

const tracks = [
  '11111111-1111-4111-8111-111111111111',
  '22222222-2222-4222-8222-222222222222',
  '33333333-3333-4333-8333-333333333333'
];
const desktopDuration = 10.4;
const sourceDuration = 10;
const mobileDuration = 9.9;

for (const [name, boundaries] of [
  ['start only', [['start', 2]]],
  ['end only', [['end', 8]]],
  ['start and end', [['start', 2], ['end', 8]]]
]) {
  test(`${name}: saved original-source coordinates reopen despite browser duration drift`, () => {
    const desktopTimeline = canonicalSourceDuration(
      [desktopDuration, desktopDuration, desktopDuration], [sourceDuration, sourceDuration, sourceDuration]);
    let payload = defaultSpeakerPayload(tracks);
    for (const [kind, value] of boundaries) payload = setRecordingBoundary(payload, desktopTimeline, kind, value);
    const saved = structuredClone(payload);
    const mobileTimeline = canonicalSourceDuration(
      [mobileDuration, mobileDuration, mobileDuration], [sourceDuration, sourceDuration, sourceDuration]);
    const reopened = prepareLegacySpeakerPayload(saved, tracks, mobileTimeline);
    assert.equal(desktopTimeline, sourceDuration);
    assert.equal(mobileTimeline, sourceDuration);
    assert.deepEqual(reopened.invalidGlobalCuts, []);
    assert.deepEqual(reopened.payload, saved);
    if (boundaries.some(([kind]) => kind === 'end')) {
      assert.equal(saved.globalCuts.find(cut => cut.startSeconds === 8).endSeconds, sourceDuration);
    }
  });
}

test('first local save rebases only the trailing boundary after Source Session verification', () => {
  let payload = defaultSpeakerPayload(tracks);
  payload = setRecordingBoundary(payload, desktopDuration, 'start', 2);
  payload = setRecordingBoundary(payload, desktopDuration, 'end', 8);
  payload.globalCuts.push({ regionId: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', startSeconds: 3, endSeconds: 4 });
  payload.trackSilenceRegions.push({ regionId: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', trackId: tracks[0], startSeconds: 5, endSeconds: 6 });
  const source = structuredClone(payload);
  const rebased = rebaseRecordingEnd(payload, desktopDuration, sourceDuration);
  const normalized = normalizeSpeakerPayload(rebased, tracks, sourceDuration);
  assert.deepEqual(payload, source, 'the original local working copy is not mutated');
  assert.equal(normalized.globalCuts.find(cut => cut.startSeconds === 8).endSeconds, sourceDuration);
  assert.deepEqual(normalized.globalCuts.find(cut => cut.startSeconds === 3), source.globalCuts.find(cut => cut.startSeconds === 3));
  assert.deepEqual(normalized.trackSilenceRegions, source.trackSilenceRegions);
  assert.deepEqual(prepareLegacySpeakerPayload(normalized, tracks, sourceDuration).invalidGlobalCuts, []);
});

test('duration provenance refuses drift beyond tolerance and does not clamp an invalid interior cut', () => {
  assert.throws(() => canonicalSourceDuration([10.501], [10]), /не совпадает/);
  assert.throws(() => canonicalSourceDuration([10, 10.4], [10, 10.6]), /различается/);
  const payload = defaultSpeakerPayload(tracks);
  payload.globalCuts.push({ regionId: 'cccccccc-cccc-4ccc-8ccc-cccccccccccc', startSeconds: 9, endSeconds: 10.2 });
  const rebased = rebaseRecordingEnd(payload, desktopDuration, sourceDuration);
  assert.equal(rebased.globalCuts[0].endSeconds, 10.2);
  assert.throws(() => normalizeSpeakerPayload(rebased, tracks, sourceDuration), /Глобальный вырез 1/);
  assert.deepEqual(prepareLegacySpeakerPayload(rebased, tracks, sourceDuration).invalidGlobalCuts.map(cut => cut.index), [1]);
});
