import test from "node:test";
import assert from "node:assert/strict";
import { buildSpeakerFilterGraph, defaultSpeakerPayload, speakerAnalysisCacheKey } from "../../scripts/speaker-editor-core.mjs";
import { LoudnessMeasurementCache, SourceIdentityRegistry } from "../../scripts/speaker-render-cache.mjs";

const TRACKS = [
  "11111111-1111-4111-8111-111111111111",
  "22222222-2222-4222-8222-222222222222",
  "33333333-3333-4333-8333-333333333333"
];
const measured = { measured_I: -23.1, measured_TP: -4.2, measured_LRA: 2.5, measured_thresh: -33.8, offset: .1 };

function leveledPayload() {
  const payload = defaultSpeakerPayload(TRACKS);
  for (const setting of payload.trackProcessing) setting.leveling = "on";
  return payload;
}

function key(payload, sourceIdentity = "source-1", trackId = TRACKS[0], duration = 3600) {
  return speakerAnalysisCacheKey({ sourceIdentity, trackId, duration, payload });
}

test("speaker analysis keys describe signal semantics rather than UI state or track order", () => {
  const initial = leveledPayload();
  const base = key(initial);
  const compression = structuredClone(initial);
  compression.trackProcessing[0].compression = "strong";
  assert.equal(key(compression), base);

  const reordered = structuredClone(initial);
  reordered.trackIds = [TRACKS[2], TRACKS[0], TRACKS[1]];
  reordered.trackProcessing = reordered.trackIds.map(trackId => initial.trackProcessing.find(item => item.trackId === trackId));
  assert.equal(key(reordered), base);

  const unrelated = structuredClone(initial);
  unrelated.trackProcessing[1].enhancement = "gentle";
  assert.equal(key(unrelated), base);

  const renamedRegion = structuredClone(initial);
  renamedRegion.globalCuts = [{ regionId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", startSeconds: 10, endSeconds: 11 }];
  const sameTimes = structuredClone(renamedRegion);
  sameTimes.globalCuts[0].regionId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
  assert.equal(key(renamedRegion), key(sameTimes));

  const enhanced = structuredClone(initial);
  enhanced.trackProcessing[0].enhancement = "gentle";
  assert.notEqual(key(enhanced), base);
  const silenced = structuredClone(initial);
  silenced.trackSilenceRegions = [{ regionId: "cccccccc-cccc-4ccc-8ccc-cccccccccccc", trackId: TRACKS[0], startSeconds: 1, endSeconds: 2 }];
  assert.notEqual(key(silenced), base);
  const cut = structuredClone(initial);
  cut.globalCuts = [{ regionId: "dddddddd-dddd-4ddd-8ddd-dddddddddddd", startSeconds: 1, endSeconds: 2 }];
  assert.notEqual(key(cut), base);
  assert.notEqual(key(initial, "source-2"), base);
  assert.notEqual(key(initial, "source-1", TRACKS[0], 3600.000001), base);
  assert.match(base, /speaker-leveling-analysis-v1/);
  assert.match(base, /core-0\.12\.10/);
});

test("measurement cache copies values, promotes hits, evicts LRU entries and rejects failures", () => {
  const cache = new LoudnessMeasurementCache(2);
  cache.set("one", measured);
  cache.set("two", { ...measured, measured_I: -20 });
  assert.deepEqual(cache.get("one"), measured);
  cache.set("three", { ...measured, measured_I: -18 });
  assert.equal(cache.get("two"), null);
  const hit = cache.get("one");
  hit.measured_I = 0;
  assert.equal(cache.get("one").measured_I, measured.measured_I);
  const size = cache.size;
  assert.throws(() => cache.set("bad", { ...measured, measured_I: NaN }));
  assert.throws(() => cache.set("bad", { measured_I: -20 }));
  assert.equal(cache.size, size);
  cache.clear();
  assert.equal(cache.size, 0);
});

test("source identity is object-bound, weakly held and reset with the source context", () => {
  const identities = new SourceIdentityRegistry();
  const first = new Blob(["same bytes"], { type: "audio/wav" });
  const second = new Blob(["same bytes"], { type: "audio/wav" });
  assert.equal(identities.identity(first), identities.identity(first));
  assert.notEqual(identities.identity(first), identities.identity(second));
  const previous = identities.identity(first);
  identities.reset();
  assert.equal(identities.identity(first), "source-1");
  assert.equal(previous, "source-1");
  assert.throws(() => identities.identity({ name: "same.wav" }));
});

test("final graph accepts compact FFmpeg indexes for non-contiguous included tracks", () => {
  const payload = leveledPayload();
  payload.excludedTrackIds = [TRACKS[1]];
  const measurements = { [TRACKS[0]]: measured, [TRACKS[2]]: { ...measured, measured_I: -21 } };
  const graph = buildSpeakerFilterGraph(payload, 10, measurements, new Map([[TRACKS[0], 0], [TRACKS[2], 1]]));
  assert.match(graph, /^\[0:a:0\]/);
  assert.match(graph, /;\[1:a:0\]/);
  assert.doesNotMatch(graph, /\[2:a:0\]/);
  assert.match(graph, /amix=inputs=2/);
  assert.throws(() => buildSpeakerFilterGraph(payload, 10, measurements, new Map([[TRACKS[0], 0]])));
});
