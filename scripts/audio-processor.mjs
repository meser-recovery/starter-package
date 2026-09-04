// Stage 7: local-only, single-thread processing. No engine import before Run.
const MIN_SILENCE_SECONDS = 2.0;
const TARGET_SILENCE_SECONDS = 0.35;
const SILENCE_THRESHOLD_DB = -45;
const OUTPUT_BITRATE = "128k";
const MAX_INPUT_BYTES = 500 * 1024 * 1024; // 500 MiB
const INPUT_PATH = "processor-input";
const OUTPUT_PATH = "processor-output.mp3";
const PROGRESS_PATH = "processor-analysis.txt";
const FILTER_PATH = "processor-filter.txt";
const TEMP_PATHS = [INPUT_PATH, OUTPUT_PATH, PROGRESS_PATH, FILTER_PATH];
const UNSUPPORTED = "Обработка аудио не поддерживается в этом браузере.";
const CANCELLED = "Обработка отменена.";

export function validateFile(file) {
  if (!/\.(mp3|m4a|wav)$/i.test(file.name)) return "Поддерживаются файлы MP3, M4A и WAV.";
  if (file.size > MAX_INPUT_BYTES) return "Файл слишком большой для обработки в браузере. Максимальный размер — 500 МБ.";
  return "";
}

export function parseSilences(logs, duration) {
  if (!Number.isFinite(duration) || duration <= 0) return [];
  const intervals = [];
  let start = null;
  const close = (end) => {
    if (start !== null && Number.isFinite(end)) {
      const left = Math.max(0, Math.min(start, duration));
      const right = Math.max(0, Math.min(end, duration));
      if (right - left >= MIN_SILENCE_SECONDS) intervals.push([left, right]);
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

export function removalRanges(intervals, duration) {
  return intervals.map(([start, end]) => {
    // An entirely silent recording retains its first 0.35 seconds.
    if (end === duration) return [start + TARGET_SILENCE_SECONDS, end];
    if (start === 0) return [start, end - TARGET_SILENCE_SECONDS];
    return [start + TARGET_SILENCE_SECONDS / 2, end - TARGET_SILENCE_SECONDS / 2];
  });
}

export function makeFilter(ranges) {
  const excluded = ranges.map(([start, end]) => `gte(t,${start.toFixed(6)})*lt(t,${end.toFixed(6)})`).join("+");
  // Small frames bound cut rounding without resampling or changing channel layout.
  // All analysis/cut timestamps use the same decoded, zero-based audio timeline.
  return `asetpts=N/SR/TB,asetnsamples=n=256:p=0,aselect='not(${excluded})',asetpts=N/SR/TB`;
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
let selectedFile = null;
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
  for (const id of ["original-duration", "processed-duration", "removed-duration", "pause-count"]) {
    byId(id).textContent = "";
    delete byId(id).dataset.value;
  }
}

function setBusy(busy) {
  input.disabled = busy || !supported;
  run.disabled = busy || !selectedFile || !supported;
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
  selectedFile = null;
  byId("source").hidden = true;
  const file = input.files?.[0];
  const error = file ? validateFile(file) : "";
  status.textContent = error || "Выберите файл и нажмите «Обработать».";
  if (file && !error && supported) {
    selectedFile = file;
    const size = new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(file.size / 1024 / 1024);
    byId("file-info").textContent = `${file.name} · ${size} МБ`;
    sourceURL = URL.createObjectURL(file);
    sourceAudio.src = sourceURL;
    byId("source").hidden = false;
    status.textContent = "Файл выбран. Нажмите «Обработать».";
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
  if (active || !selectedFile || !supported) return;
  const file = selectedFile;
  const error = validateFile(file);
  if (error) { status.textContent = error; return; }
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
    const bytes = new Uint8Array(await operation.wait(file.arrayBuffer()));
    await operation.wait(currentEngine.writeFile(INPUT_PATH, bytes));
    const logs = [];
    logListener = ({ message }) => {
      // Keep only detector output, not an unbounded copy of all decoder logs.
      if (/\bsilence_(start|end):/.test(message)) logs.push(message);
    };
    currentEngine.on("log", logListener);
    const inputArgs = ["-hide_banner", "-nostats", "-xerror", "-protocol_whitelist", "file", "-i", INPUT_PATH,
      "-map", "0:a:0", "-vn", "-sn", "-dn"];
    status.textContent = "Поиск длинных пауз…";
    const analysisCode = await operation.wait(currentEngine.exec([...inputArgs,
      "-af", `asetpts=N/SR/TB,silencedetect=noise=${SILENCE_THRESHOLD_DB}dB:d=${MIN_SILENCE_SECONDS}`,
      "-progress", PROGRESS_PATH, "-f", "null", "-"]));
    currentEngine.off("log", logListener);
    logListener = null;
    if (analysisCode !== 0) throw new Error("Не удалось прочитать аудио. Проверьте исходный файл.");
    const duration = analysisDuration(await operation.wait(currentEngine.readFile(PROGRESS_PATH, "utf8")));
    const intervals = parseSilences(logs, duration);
    if (!intervals.length) {
      status.textContent = "Длинные паузы не найдены. Файл не изменён.";
      return;
    }
    status.textContent = "Сокращение пауз и создание MP3…";
    await operation.wait(currentEngine.writeFile(FILTER_PATH, new TextEncoder().encode(makeFilter(removalRanges(intervals, duration)))));
    const encodeCode = await operation.wait(currentEngine.exec([...inputArgs,
      "-filter_script:a", FILTER_PATH, "-map_metadata", "0", "-c:a", "libmp3lame", "-b:a", OUTPUT_BITRATE, OUTPUT_PATH]));
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
    download.href = resultURL;
    download.download = `${file.name.replace(/\.[^.]+$/, "")}-edited.mp3`;
    result.hidden = false;
    status.textContent = "Готово.";
  } catch (failure) {
    if (active === operation) {
      clearResult();
      status.textContent = failure?.name === "NotSupportedError" || failure?.name === "SecurityError" ? UNSUPPORTED :
        failure instanceof Error && failure.message.startsWith("Не удалось") ? failure.message :
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
      for (const path of TEMP_PATHS) {
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
  if (event.persisted && selectedFile && !sourceURL) {
    sourceURL = URL.createObjectURL(selectedFile);
    sourceAudio.src = sourceURL;
  }
});
status.textContent = supported ? "Выберите файл и нажмите «Обработать»." : UNSUPPORTED;
setBusy(false);
byId("heading").dataset.ready = "true";
