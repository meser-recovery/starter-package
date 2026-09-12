import test from "node:test";
import assert from "node:assert/strict";
import { chooseSpeakerAnalysisConcurrency, runSpeakerAnalysisQueue } from "../../scripts/speaker-analysis-queue.mjs";

const task = index => ({ operationKey: `operation:track-${index}:key-${index}`, trackId: `track-${index}`, analysisIndex: index });
const deferred = () => { let resolve; let reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };

test("analysis concurrency is bounded and conservative when capacity is unknown", () => {
  for (const missCount of [0, 1]) assert.equal(chooseSpeakerAnalysisConcurrency({ missCount, hardwareConcurrency: 16, deviceMemory: 16 }), 1);
  assert.equal(chooseSpeakerAnalysisConcurrency({ missCount: 3, hardwareConcurrency: 8, deviceMemory: 8 }), 2);
  assert.equal(chooseSpeakerAnalysisConcurrency({ missCount: 3, hardwareConcurrency: 2, deviceMemory: 16 }), 1);
  assert.equal(chooseSpeakerAnalysisConcurrency({ missCount: 3, hardwareConcurrency: 8, deviceMemory: undefined }), 1);
  assert.equal(chooseSpeakerAnalysisConcurrency({ missCount: 3, hardwareConcurrency: 2, deviceMemory: 2, override: 2 }), 2);
  assert.equal(chooseSpeakerAnalysisConcurrency({ missCount: 3, hardwareConcurrency: 16, deviceMemory: 16, override: 1 }), 1);
});

test("two workers bind reverse completions by operation key and never exceed two", async () => {
  const gates = [deferred(), deferred(), deferred()];
  let active = 0; let maximum = 0;
  const promise = runSpeakerAnalysisQueue({ tasks: [task(0), task(1), task(2)], concurrency: 2,
    runTask: async (item, slot) => { active += 1; maximum = Math.max(maximum, active); await gates[item.analysisIndex].promise; active -= 1; return `${item.trackId}:${slot}`; } });
  gates[1].resolve(); await new Promise(resolve => setTimeout(resolve, 0));
  gates[2].resolve(); gates[0].resolve();
  const result = await promise;
  assert.equal(maximum, 2);
  assert.equal(result.get(task(0).operationKey), "track-0:0");
  assert.equal(result.get(task(1).operationKey), "track-1:1");
  assert.equal(result.get(task(2).operationKey), "track-2:1");
});

test("failure stops the queue after in-flight work and exposes only complete results", async () => {
  const started = [];
  await assert.rejects(runSpeakerAnalysisQueue({ tasks: [task(0), task(1), task(2)], concurrency: 2,
    runTask: async (item, slot) => {
      started.push(item.analysisIndex);
      if (slot === 1) { const error = new Error("Worker terminated"); throw error; }
      await new Promise(resolve => setTimeout(resolve, 5)); return item.trackId;
    } }), error => {
      assert.equal(error.speakerAnalysisSlot, 1);
      assert.equal(error.speakerAnalysisResults.size, 1);
      return true;
    });
  assert.deepEqual(started.sort(), [0, 1]);
});

test("abort prevents queued work and a later queue remains usable", async () => {
  const controller = new AbortController(); const gate = deferred(); const started = [];
  const first = runSpeakerAnalysisQueue({ tasks: [task(0), task(1), task(2)], concurrency: 1, signal: controller.signal,
    runTask: async item => { started.push(item.analysisIndex); await gate.promise; return item.trackId; } });
  controller.abort(); gate.resolve();
  await assert.rejects(first, error => error.name === "AbortError");
  assert.deepEqual(started, [0]);
  const second = await runSpeakerAnalysisQueue({ tasks: [task(2)], concurrency: 1, runTask: async item => item.trackId });
  assert.equal(second.get(task(2).operationKey), "track-2");
});
