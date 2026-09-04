// Stage 7: local-only, single-thread processing. No engine import before Run.
const MIN_SILENCE_SECONDS = 2.0;
const TARGET_SILENCE_SECONDS = 0.35;
const SILENCE_THRESHOLD_DB = -45;
const OUTPUT_BITRATE = "128k";
const MAX_INPUT_BYTES = 500 * 1024 * 1024; // 500 MiB
const MAX_DURATION_DIFFERENCE_SECONDS = 0.5;
// A shared sample/frame grid prevents cumulative cut drift across different input rates.
// Only multi-track mixing uses this clock; single-track processing stays unchanged.
const MIX_SAMPLE_RATE = 48000;
const OUTPUT_PATH = "processor-output.mp3";
const PROGRESS_PATH = "processor-analysis.txt";
const FILTER_PATH = "processor-filter.txt";
const TEMP_PATHS = [OUTPUT_PATH, PROGRESS_PATH, FILTER_PATH];
const UNSUPPORTED = "Обработка аудио не поддерживается в этом браузере.";
const CANCELLED = "Обработка отменена.";
const DURATION_MISMATCH = "Дорожки имеют разную длительность. Проверьте, что они относятся к одной записи Zoom.";
const MIXED_WITHOUT_CUTS = "Длинные общие паузы не найдены. Дорожки сведены без сокращения пауз.";

export function validateFile(file) {
  return validateFiles([file]);
}

export function validateFiles(files) {
  if (files.some((file) => !/\.(mp3|m4a|wav)$/i.test(file.name))) return "Поддерживаются файлы MP3, M4A и WAV.";
  if (files.reduce((sum, file) => sum + file.size, 0) > MAX_INPUT_BYTES) {
    return "Общий размер файлов слишком большой для обработки в браузере. Максимальный размер — 500 МБ.";
  }
  return "";
}

export function parseSilences(logs, duration, minimum = MIN_SILENCE_SECONDS) {
  if (!Number.isFinite(duration) || duration <= 0) return [];
  const intervals = [];
  let start = null;
  const close = (end) => {
    if (start !== null && Number.isFinite(end)) {
      const left = Math.max(0, Math.min(start, duration));
      const right = Math.max(0, Math.min(end, duration));
      if (right > left && right - left >= minimum) intervals.push([left, right]);
    }
    start = null;
  };
  for (const line of logs) {
    for (const match of line.matchAll(/silence_(start|end):\s*([^\s|]+)/g)) {
      const value = Number(match[2]);
      if (match[1] === "start") {
        // An invalid or duplicate start must not create a spurious long interval.
        start = Number.isFinite(value) ? value : null;
      } else close(value);
    }
  }
  if (start !== null) close(duration); // silencedetect may omit the final end at EOF.
  intervals.sort((a, b) => a[0] - b[0]);
  const merged = [];
  for (const interval of intervals) {
    const previous = merged.at(-1);
    if (previous && interval[0] <= previous[1]) previous[1] = Math.max(previous[1], interval[1]);
    else merged.push(interval);
  }
  return merged;
}

export function commonTimeline(analyses) {
  const durations = analyses.map((track) => track.duration);
  const duration = Math.max(...durations);
  if (duration - Math.min(...durations) > MAX_DURATION_DIFFERENCE_SECONDS) throw new Error(DURATION_MISMATCH);
  return duration;
}

export function commonSilences(analyses, duration) {
  let common = [[0, duration]];
  for (const track of analyses) {
    const intervals = track.silences.map((interval) => [...interval]);
    if (track.duration < duration) {
      const tail = intervals.at(-1);
      if (tail && tail[1] === track.duration) tail[1] = duration;
      else intervals.push([track.duration, duration]);
    }
    const intersection = [];
    let left = 0;
    let right = 0;
    while (left < common.length && right < intervals.length) {
      const start = Math.max(common[left][0], intervals[right][0]);
      const end = Math.min(common[left][1], intervals[right][1]);
      if (end > start) intersection.push([start, end]);
      if (common[left][1] < intervals[right][1]) left++;
      else right++;
    }
    common = intersection;
  }
  // Eligibility is decided only after every track has contributed its silence mask.
  return common.filter(([start, end]) => end - start >= MIN_SILENCE_SECONDS);
}

export function removalRanges(intervals, duration) {
  return intervals.map(([start, end]) => {
    // An entirely silent recording retains its first 0.35 seconds.
    if (end === duration) return [start + TARGET_SILENCE_SECONDS, end];
    if (start === 0) return [start, end - TARGET_SILENCE_SECONDS];
    return [start + TARGET_SILENCE_SECONDS / 2, end - TARGET_SILENCE_SECONDS / 2];
  });
}

export function makeFilter(ranges) {
  if (!ranges.length) return "asetpts=N/SR/TB";
  const excluded = ranges.map(([start, end]) => `gte(t,${start.toFixed(6)})*lt(t,${end.toFixed(6)})`).join("+");
  // Small frames bound cut rounding without resampling or changing channel layout.
  // All analysis/cut timestamps use the same decoded, zero-based audio timeline.
  return `asetpts=N/SR/TB,asetnsamples=n=256:p=0,aselect='not(${excluded})',asetpts=N/SR/TB`;
}

export function makeMixFilter(trackCount, ranges, duration) {
  const cuts = makeFilter(ranges); // The exact same expression and frame grid for ALL inputs.
  const wholeLength = Math.ceil(duration * MIX_SAMPLE_RATE);
  const inputs = Array.from({ length: trackCount }, (_, index) =>
    `[${index}:a:0]asetpts=N/SR/TB,aresample=${MIX_SAMPLE_RATE},apad=whole_len=${wholeLength},${cuts}[track${index}]`);
  const labels = Array.from({ length: trackCount }, (_, index) => `[track${index}]`).join("");
  // Unity weights: no per-speaker attenuation/boost. Disable the limiter's auto-level
  // and compensate its lookahead delay (including buffered audio at EOF).
  return `${inputs.join(";")};${labels}amix=inputs=${trackCount}:duration=longest:normalize=0,` +
    "alimiter=limit=0.95:level=0:latency=1[mixed]";
}

export function analysisDuration(progress) {
  const times = [...progress.matchAll(/^out_time_us=(\d+)$/gm)].map((match) => Number(match[1]) / 1e6);
  const duration = times.at(-1);
  if (!progress.includes("progress=end") || !Number.isFinite(duration) || duration <= 0) {
    throw new Error("Не удалось определить длительность аудио.");
  }
  return duration;
}

export function formatDuration(seconds) {
  const total = Math.round(Math.max(0, seconds) * 100) / 100;
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(total % 60);
  return `${hours ? `${hours} ч ` : ""}${minutes ? `${minutes} мин ` : ""}${rest} с`;
}

const byId = (id) => document.getElementById(`processor-${id}`);
const input = byId("file");
const run = byId("run");
const cancel = byId("cancel");
const status = byId("status");
const progress = byId("progress");
const sourceAudio = byId("source-audio");
const resultAudio = byId("result-audio");
const result = byId("result");
const download = byId("download");
let selectedFiles = [];
let sourceURL = null;
let resultURL = null;
let engine = null;
let active = null;

const supported = typeof WebAssembly === "object" && typeof WebAssembly.instantiate === "function" && typeof Worker === "function" &&
  typeof File === "function" && typeof File.prototype.arrayBuffer === "function" &&
  typeof URL.createObjectURL === "function" && typeof URL.revokeObjectURL === "function";

function clearAudio(audio) {
  audio.pause();
  audio.removeAttribute("src");
  audio.load();
}

function clearResult() {
  result.hidden = true;
  clearAudio(resultAudio);
  if (resultURL) URL.revokeObjectURL(resultURL);
  resultURL = null;
  download.removeAttribute("href");
  download.removeAttribute("download");
  byId("mixed-count").hidden = true;
  byId("mixed-count").textContent = "";
  byId("pause-label").textContent = "Сокращено длинных пауз";
  for (const id of ["original-duration", "processed-duration", "removed-duration", "pause-count"]) {
    byId(id).textContent = "";
    delete byId(id).dataset.value;
  }
}

function setBusy(busy) {
  input.disabled = busy || !supported;
  run.disabled = busy || !selectedFiles.length || !supported;
  cancel.hidden = !busy;
  progress.hidden = !busy;
}

function stop() {
  if (!active) return;
  const operation = active;
  active = null;
  operation.cancel();
  if (engine) engine.terminate(); // Rejects outstanding FFmpeg calls, including load.
  engine = null;
  clearResult();
  setBusy(false);
  status.textContent = CANCELLED;
}

input.addEventListener("change", () => {
  if (active) return;
  clearResult();
  clearAudio(sourceAudio);
  if (sourceURL) URL.revokeObjectURL(sourceURL);
  sourceURL = null;
  selectedFiles = [];
  byId("source").hidden = true;
  byId("file-info").replaceChildren();
  byId("selection-summary").textContent = "";
  const files = Array.from(input.files || []);
  const error = validateFiles(files);
  status.textContent = error || "Выберите файлы и нажмите «Обработать».";
  if (files.length && !error && supported) {
    selectedFiles = files;
    const size = (bytes) => new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(bytes / 1024 / 1024);
    for (const file of files) {
      const item = document.createElement("li");
      item.textContent = `${file.name} · ${size(file.size)} МБ`;
      byId("file-info").append(item);
    }
    byId("selection-summary").textContent = `Выбрано дорожек: ${files.length} · Общий размер: ${size(files.reduce((sum, file) => sum + file.size, 0))} МБ`;
    byId("source-label").textContent = files.length === 1 ? "Исходное аудио" : "Прослушать первую исходную дорожку";
    sourceURL = URL.createObjectURL(files[0]);
    sourceAudio.src = sourceURL;
    byId("source").hidden = false;
    status.textContent = files.length === 1 ? "Файл выбран. Нажмите «Обработать»." : "Дорожки выбраны. Нажмите «Обработать».";
  }
  setBusy(false);
});

function waitForMetadata(audio, operation) {
  let timer;
  let loaded;
  let failed;
  const metadata = new Promise((resolve, reject) => {
    loaded = () => Number.isFinite(audio.duration) && audio.duration > 0 ? resolve(audio.duration) : failed();
    failed = () => reject(new Error("Не удалось прочитать обработанный MP3."));
    audio.addEventListener("loadedmetadata", loaded);
    audio.addEventListener("error", failed);
    timer = setTimeout(failed, 30000);
    if (audio.readyState >= 1) loaded();
  });
  return operation.wait(metadata).finally(() => {
    clearTimeout(timer);
    audio.removeEventListener("loadedmetadata", loaded);
    audio.removeEventListener("error", failed);
  });
}

run.addEventListener("click", async () => {
  if (active || !selectedFiles.length || !supported) return;
  const files = selectedFiles;
  const multiple = files.length > 1;
  const error = validateFiles(files);
  if (error) { status.textContent = error; return; }
  const inputPaths = files.map((_, index) => `processor-input-${index}`);
  let cancelOperation;
  const cancelled = new Promise((resolve) => { cancelOperation = resolve; });
  const operation = {
    cancel: () => cancelOperation({ cancelled: true }),
    wait: async (promise) => {
      const value = await Promise.race([promise, cancelled]);
      if (active !== operation) throw new Error(CANCELLED);
      return value;
    }
  };
  active = operation;
  clearResult();
  setBusy(true);
  status.textContent = "Подготовка обработчика…";
  let currentEngine;
  let loadTimer;
  let logListener;
  try {
    if (!engine) {
      // Race the whole preparation (including the module import), not just load().
      const preparation = (async () => {
        const { FFmpeg } = await operation.wait(import("../vendor/ffmpeg/ffmpeg/index.js"));
        engine = new FFmpeg();
        currentEngine = engine;
        await operation.wait(engine.load({
          coreURL: new URL("../vendor/ffmpeg/core/ffmpeg-core.js", import.meta.url).href,
          wasmURL: new URL("../vendor/ffmpeg/core/ffmpeg-core.wasm", import.meta.url).href
        }));
      })();
      await operation.wait(Promise.race([preparation, new Promise((_, reject) => {
        loadTimer = setTimeout(() => reject(new Error("Не удалось загрузить обработчик. Попробуйте ещё раз.")), 180000);
      })]));
      clearTimeout(loadTimer);
    }
    currentEngine = engine;
    const inputArgs = (path) => ["-hide_banner", "-nostats", "-xerror", "-protocol_whitelist", "file", "-i", path,
      "-map", "0:a:0", "-vn", "-sn", "-dn"];
    const analyses = [];
    // A shorter track can contribute up to 0.5 s of implicit silent tail. Detect
    // 1.5 s tails in multi-track mode, but still require 2.0 s AFTER intersection.
    const detectionMinimum = multiple ? MIN_SILENCE_SECONDS - MAX_DURATION_DIFFERENCE_SECONDS : MIN_SILENCE_SECONDS;
    // Integer sample timestamps avoid a one-sample floating-point truncation at
    // EOF turning an exact 0.5 s duration difference into a false mismatch.
    const analysisClock = multiple ? "asettb=1/sr,asetpts=N" : "asetpts=N/SR/TB";
    for (let index = 0; index < files.length; index++) {
      const bytes = new Uint8Array(await operation.wait(files[index].arrayBuffer()));
      await operation.wait(currentEngine.writeFile(inputPaths[index], bytes));
      const logs = [];
      logListener = ({ message }) => {
        // Accept detector lines only; metadata must not impersonate silence output.
        if (/^\[silencedetect @ [^\]]+\] silence_(start|end):/.test(message)) logs.push(message);
      };
      currentEngine.on("log", logListener);
      status.textContent = "Поиск длинных пауз…";
      const analysisCode = await operation.wait(currentEngine.exec([...inputArgs(inputPaths[index]),
        "-af", `${analysisClock},silencedetect=noise=${SILENCE_THRESHOLD_DB}dB:d=${detectionMinimum}`,
        "-progress", PROGRESS_PATH, "-f", "null", "-"]));
      currentEngine.off("log", logListener);
      logListener = null;
      if (analysisCode !== 0) throw new Error("Не удалось прочитать аудио. Проверьте исходный файл.");
      const duration = analysisDuration(await operation.wait(currentEngine.readFile(PROGRESS_PATH, "utf8")));
      analyses.push({ duration, silences: parseSilences(logs, duration, detectionMinimum) });
    }
    const duration = commonTimeline(analyses); // Reject mismatches before any final encoding.
    const intervals = multiple ? commonSilences(analyses, duration) : analyses[0].silences;
    if (!multiple && !intervals.length) {
      status.textContent = "Длинные паузы не найдены. Файл не изменён.";
      return;
    }
    status.textContent = "Сокращение пауз и создание MP3…";
    const ranges = removalRanges(intervals, duration);
    const filter = multiple ? makeMixFilter(files.length, ranges, duration) : makeFilter(ranges);
    await operation.wait(currentEngine.writeFile(FILTER_PATH, new TextEncoder().encode(filter)));
    const encodeArgs = multiple ? ["-hide_banner", "-nostats", "-xerror",
      ...inputPaths.flatMap((path) => ["-protocol_whitelist", "file", "-i", path]),
      "-filter_complex_script", FILTER_PATH, "-map", "[mixed]", "-vn", "-sn", "-dn"] :
      [...inputArgs(inputPaths[0]), "-filter_script:a", FILTER_PATH];
    const encodeCode = await operation.wait(currentEngine.exec([...encodeArgs,
      "-map_metadata", "0", "-c:a", "libmp3lame", "-b:a", OUTPUT_BITRATE, OUTPUT_PATH]));
    if (encodeCode !== 0) throw new Error("Не удалось создать MP3. Попробуйте файл меньшего размера.");
    const output = await operation.wait(currentEngine.readFile(OUTPUT_PATH));
    if (!output.byteLength) throw new Error("Не удалось создать MP3.");
    resultURL = URL.createObjectURL(new Blob([output], { type: "audio/mpeg" }));
    resultAudio.src = resultURL;
    const processedDuration = await waitForMetadata(resultAudio, operation);
    for (const [id, value] of [["original-duration", duration], ["processed-duration", processedDuration],
      ["removed-duration", Math.max(0, duration - processedDuration)], ["pause-count", intervals.length]]) {
      byId(id).textContent = id === "pause-count" ? String(value) : formatDuration(value);
      byId(id).dataset.value = String(value);
    }
    byId("mixed-count").hidden = !multiple;
    byId("mixed-count").textContent = multiple ? `Дорожек сведено: ${files.length}` : "";
    byId("pause-label").textContent = multiple ? "Сокращено общих длинных пауз" : "Сокращено длинных пауз";
    download.href = resultURL;
    download.download = `${files[0].name.replace(/\.[^.]+$/, "")}${multiple ? "-mixed" : ""}-edited.mp3`;
    result.hidden = false;
    status.textContent = multiple && !intervals.length ? MIXED_WITHOUT_CUTS : "Готово.";
  } catch (failure) {
    if (active === operation) {
      clearResult();
      status.textContent = failure?.name === "NotSupportedError" || failure?.name === "SecurityError" ? UNSUPPORTED :
        failure instanceof Error && (failure.message.startsWith("Не удалось") || failure.message === DURATION_MISMATCH) ? failure.message :
          "Не удалось обработать аудио. Попробуйте ещё раз или выберите файл меньшего размера.";
      if (!currentEngine?.loaded) {
        currentEngine?.terminate();
        engine = null;
      }
    }
  } finally {
    clearTimeout(loadTimer);
    if (logListener) currentEngine?.off("log", logListener);
    if (currentEngine?.loaded && engine === currentEngine) {
      // Every path is fixed; never interpolate the user's filename into the virtual FS.
      for (const path of [...inputPaths, ...TEMP_PATHS]) {
        if (engine !== currentEngine) break;
        try { await operation.wait(currentEngine.deleteFile(path)); } catch { /* Absent or terminated. */ }
      }
    }
    if (active === operation) {
      active = null;
      setBusy(false);
    }
  }
});

cancel.addEventListener("click", stop);
window.addEventListener("pagehide", () => {
  stop();
  engine?.terminate();
  engine = null;
  clearResult();
  clearAudio(sourceAudio);
  if (sourceURL) URL.revokeObjectURL(sourceURL);
  sourceURL = null;
});
window.addEventListener("pageshow", (event) => {
  if (event.persisted && selectedFiles.length && !sourceURL) {
    sourceURL = URL.createObjectURL(selectedFiles[0]);
    sourceAudio.src = sourceURL;
  }
});
status.textContent = supported ? "Выберите файлы и нажмите «Обработать»." : UNSUPPORTED;
setBusy(false);
byId("heading").dataset.ready = "true";
