const cancelled = () => new DOMException("cancelled", "AbortError");

export function chooseSpeakerAnalysisConcurrency({ missCount, hardwareConcurrency, deviceMemory, override = null }) {
  if (!Number.isInteger(missCount) || missCount < 0) throw new Error("Некорректное число измерений громкости.");
  if (missCount < 2) return 1;
  if (override === 1 || override === 2) return override;
  const cores = Number(hardwareConcurrency);
  const memory = Number(deviceMemory);
  // deviceMemory is unavailable in some browsers. That is an unknown capacity,
  // so the normal path stays conservative; benchmarks can compare both modes.
  return Number.isFinite(cores) && cores >= 4 && Number.isFinite(memory) && memory >= 8 ? 2 : 1;
}

export async function runSpeakerAnalysisQueue({ tasks, concurrency, signal, runTask, onProgress = () => {} }) {
  if (!Array.isArray(tasks) || ![1, 2].includes(concurrency) || typeof runTask !== "function") {
    throw new Error("Некорректная очередь измерения громкости.");
  }
  let cursor = 0;
  let completed = 0;
  let failure = null;
  const running = new Map();
  const results = new Map();
  const report = () => onProgress({ completed, total: tasks.length, running: [...running.values()] });
  const worker = async slot => {
    while (!failure && cursor < tasks.length) {
      if (signal?.aborted) throw cancelled();
      const task = tasks[cursor++];
      running.set(slot, task);
      report();
      try {
        const value = await runTask(task, slot);
        if (signal?.aborted) throw cancelled();
        results.set(task.operationKey, value);
        completed += 1;
      } catch (error) {
        if (error && typeof error === "object") {
          error.speakerAnalysisSlot = slot;
          error.speakerAnalysisTask = task;
        }
        failure ||= error;
        throw error;
      } finally {
        running.delete(slot);
        report();
      }
    }
  };
  report();
  const settled = await Promise.allSettled(Array.from({ length: Math.min(concurrency, tasks.length) }, (_, slot) => worker(slot)));
  if (failure) {
    if (failure && typeof failure === "object") failure.speakerAnalysisResults = results;
    throw failure;
  }
  const rejected = settled.find(item => item.status === "rejected");
  if (rejected) throw rejected.reason;
  return results;
}
