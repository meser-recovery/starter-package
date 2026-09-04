// Stage 7: local-only, single-thread processing. No engine import before valid selection.
const MIN_SILENCE_SECONDS = 2.0;
const TARGET_SILENCE_SECONDS = 0.35;
const SILENCE_THRESHOLD_DB = -45;
const OUTPUT_BITRATE = "128k";
const MAX_INPUT_BYTES = 500 * 1024 * 1024; // 500 MiB
const MAX_DURATION_DIFFERENCE_SECONDS = 0.5;
// A shared sample/frame grid prevents cumulative cut drift across different input rates.
// Only multi-track mixing uses this clock; single-track processing stays unchanged.
const MIX_SAMPLE_RATE = 48000;
const WAVEFORM_HEIGHT = 100;
// One compact FFmpeg PNG is reused for both views: fit-to-card overview and
// native-width detail. Two pixels/second exposes ~2 s gaps without unbounded images.
const WAVEFORM_PIXELS_PER_SECOND = 2;
const WAVEFORM_MIN_WIDTH = 640;
const WAVEFORM_MAX_WIDTH = 16384;
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
let tracks = [];
let activeTrackId = null;
let nextTrackId = 1;
let resultURL = null;
let engine = null;
let active = null;
let switchVersion = 0;
let playheadFrame = 0;

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
  for (const control of byId("source").querySelectorAll("button")) control.disabled = busy;
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

const fileSize = (bytes) => new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(bytes / 1024 / 1024);

export function waveformWidth(duration) {
  if (!Number.isFinite(duration) || duration <= 0) return WAVEFORM_MIN_WIDTH;
  return Math.min(WAVEFORM_MAX_WIDTH, Math.max(WAVEFORM_MIN_WIDTH, Math.ceil(duration * WAVEFORM_PIXELS_PER_SECOND)));
}

function clockDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = String(total % 60).padStart(2, "0");
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${rest}` : `${minutes}:${rest}`;
}

function selectionStatus() {
  return tracks.length === 1 ? "Файл выбран. Нажмите «Обработать»." : "Дорожки выбраны. Нажмите «Обработать».";
}

function trackById(id) {
  return tracks.find((track) => track.id === Number(id));
}

function updateSelectionSummary() {
  byId("selection-summary").textContent = tracks.length ?
    `Выбрано дорожек: ${tracks.length} · Общий размер: ${fileSize(tracks.reduce((sum, track) => sum + track.file.size, 0))} МБ` : "";
}

function updateActiveState() {
  for (const element of byId("source").querySelectorAll("[data-track-id]")) {
    const current = Number(element.dataset.trackId) === activeTrackId;
    if (element.classList.contains("processor-track")) element.setAttribute("aria-current", String(current));
    if (element.matches("button[data-track-action='listen'], .processor-track-switcher button")) {
      element.setAttribute("aria-pressed", String(current));
    }
  }
  updatePlayheads();
}

function seekFromControl(event) {
  const control = event.currentTarget;
  const track = trackById(control.dataset.trackId);
  if (!track || !Number.isFinite(track.duration)) return;
  if (event.detail === 0) {
    void activateTrack(track.id, sourceAudio.currentTime, !sourceAudio.paused && !sourceAudio.ended);
    return;
  }
  const box = control.getBoundingClientRect();
  const ratio = Math.max(0, Math.min(1, (event.clientX - box.left) / box.width));
  void activateTrack(track.id, ratio * track.duration, !sourceAudio.paused && !sourceAudio.ended);
}

function navigateWaveform(event) {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  const track = trackById(event.currentTarget.dataset.trackId);
  if (!track || !Number.isFinite(track.duration)) return;
  event.preventDefault();
  const current = Math.min(sourceAudio.currentTime || 0, track.duration);
  const step = event.shiftKey ? 30 : 5;
  const target = event.key === "Home" ? 0 : event.key === "End" ? track.duration :
    Math.max(0, Math.min(track.duration, current + (event.key === "ArrowLeft" ? -step : step)));
  void activateTrack(track.id, target, !sourceAudio.paused && !sourceAudio.ended);
}

function waveformControl(track, detail = false) {
  const control = document.createElement("button");
  control.type = "button";
  control.className = `processor-waveform${detail ? " processor-waveform--detail" : " processor-waveform--overview"}`;
  control.dataset.trackId = String(track.id);
  control.dataset.trackAction = "waveform";
  control.style.width = detail ? `${track.waveformWidth}px` : "100%";
  control.setAttribute("aria-label", `${detail ? "Подробная" : "Обзорная"} форма сигнала дорожки ${track.ordinal}: ${track.file.name}`);
  control.setAttribute("aria-describedby", "processor-source-time");
  control.addEventListener("click", seekFromControl);
  control.addEventListener("keydown", navigateWaveform);
  if (track.waveformURL) {
    const image = document.createElement("img");
    image.src = track.waveformURL;
    image.alt = "";
    image.width = track.waveformWidth;
    image.height = WAVEFORM_HEIGHT;
    control.append(image);
  } else {
    const message = document.createElement("span");
    message.className = "processor-waveform-status";
    message.textContent = track.loading ? "Подготовка формы сигнала…" :
      track.waveformFailed ? "Не удалось построить форму сигнала." : "Форма сигнала ещё не построена.";
    control.append(message);
  }
  const playhead = document.createElement("span");
  playhead.className = "processor-waveform-playhead";
  playhead.setAttribute("aria-hidden", "true");
  control.append(playhead);
  return control;
}

function renderTracks() {
  const list = byId("file-info");
  const switcher = byId("track-switcher");
  list.replaceChildren();
  switcher.replaceChildren();
  tracks.forEach((track, index) => {
    track.ordinal = index + 1;
    const item = document.createElement("li");
    item.className = "processor-track";
    item.dataset.trackId = String(track.id);
    item.setAttribute("aria-current", String(track.id === activeTrackId));
    const heading = document.createElement("div");
    heading.className = "processor-track__heading";
    const number = document.createElement("span");
    number.className = "processor-track__number";
    number.textContent = `Дорожка ${track.ordinal}`;
    const name = document.createElement("h4");
    name.className = "processor-track__name";
    name.textContent = track.file.name;
    const meta = document.createElement("span");
    meta.className = "processor-track__meta";
    meta.textContent = `${fileSize(track.file.size)} МБ · ${clockDuration(track.duration)}`;
    heading.append(number, name, meta);
    const overviewLabel = document.createElement("span");
    overviewLabel.className = "processor-waveform-label";
    overviewLabel.textContent = "Обзор формы сигнала";
    const overview = waveformControl(track);
    const detail = document.createElement("details");
    detail.className = "processor-waveform-detail";
    const summary = document.createElement("summary");
    summary.textContent = "Подробная форма сигнала";
    const scroll = document.createElement("div");
    scroll.className = "processor-waveform-scroll";
    scroll.append(waveformControl(track, true));
    detail.append(summary, scroll);
    const actions = document.createElement("div");
    actions.className = "processor-track__actions";
    const listen = document.createElement("button");
    listen.type = "button";
    listen.dataset.trackId = String(track.id);
    listen.dataset.trackAction = "listen";
    listen.setAttribute("aria-pressed", String(track.id === activeTrackId));
    listen.textContent = "Прослушать";
    listen.addEventListener("click", () => void activateTrack(track.id, sourceAudio.currentTime, !sourceAudio.paused && !sourceAudio.ended));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.dataset.trackId = String(track.id);
    remove.dataset.trackAction = "remove";
    remove.setAttribute("aria-label", `Удалить дорожку ${track.ordinal}: ${track.file.name}`);
    remove.textContent = "Удалить";
    remove.addEventListener("click", () => removeTrack(track.id));
    actions.append(listen, remove);
    item.append(heading, overviewLabel, overview, detail, actions);
    list.append(item);

    const switchButton = document.createElement("button");
    switchButton.type = "button";
    switchButton.dataset.trackId = String(track.id);
    switchButton.dataset.trackAction = "switch";
    switchButton.title = track.file.name;
    switchButton.setAttribute("aria-label", `Дорожка ${track.ordinal}: ${track.file.name}`);
    switchButton.setAttribute("aria-pressed", String(track.id === activeTrackId));
    const shortName = track.file.name.length > 24 ? `${track.file.name.slice(0, 21)}…` : track.file.name;
    switchButton.textContent = `${track.ordinal}. ${shortName}`;
    switchButton.addEventListener("click", () => void activateTrack(track.id, sourceAudio.currentTime, !sourceAudio.paused && !sourceAudio.ended));
    switcher.append(switchButton);
  });
  updateSelectionSummary();
  setBusy(Boolean(active));
  updatePlayheads();
}

function updatePlayheads() {
  const current = Number.isFinite(sourceAudio.currentTime) ? sourceAudio.currentTime : 0;
  for (const track of tracks) {
    const ratio = Number.isFinite(track.duration) && track.duration > 0 ? Math.min(1, current / track.duration) : 0;
    for (const playhead of byId("source").querySelectorAll(`.processor-waveform[data-track-id="${track.id}"] .processor-waveform-playhead`)) {
      playhead.style.left = `${ratio * 100}%`;
    }
  }
  const activeTrack = trackById(activeTrackId);
  byId("source-time").textContent = `${clockDuration(current)} / ${clockDuration(activeTrack?.duration)}`;
}

function animatePlayhead() {
  cancelAnimationFrame(playheadFrame);
  const frame = () => {
    updatePlayheads();
    if (!sourceAudio.paused && !sourceAudio.ended) playheadFrame = requestAnimationFrame(frame);
  };
  playheadFrame = requestAnimationFrame(frame);
}

sourceAudio.addEventListener("play", animatePlayhead);
for (const event of ["pause", "timeupdate", "seeked", "durationchange", "ended"]) sourceAudio.addEventListener(event, updatePlayheads);

async function activateTrack(id, position = 0, resume = false) {
  const track = trackById(id);
  if (!track) return;
  const token = ++switchVersion;
  const target = Number.isFinite(position) ? Math.max(0, position) : 0;
  activeTrackId = track.id;
  updateActiveState();
  if (sourceAudio.src === track.sourceURL) {
    sourceAudio.currentTime = Math.min(target, Number.isFinite(sourceAudio.duration) ? sourceAudio.duration : target);
    updatePlayheads();
    if (resume) await sourceAudio.play().catch(() => {});
    return;
  }
  sourceAudio.pause();
  sourceAudio.src = track.sourceURL;
  sourceAudio.load();
  await new Promise((resolve) => {
    if (sourceAudio.readyState >= 1) return resolve();
    const done = () => { sourceAudio.removeEventListener("loadedmetadata", done); sourceAudio.removeEventListener("error", done); resolve(); };
    sourceAudio.addEventListener("loadedmetadata", done, { once: true });
    sourceAudio.addEventListener("error", done, { once: true });
  });
  if (token !== switchVersion || activeTrackId !== track.id) return;
  const duration = Number.isFinite(sourceAudio.duration) ? sourceAudio.duration : track.duration;
  sourceAudio.currentTime = Number.isFinite(duration) ? Math.min(target, duration) : target;
  updatePlayheads();
  if (resume) await sourceAudio.play().catch(() => {});
}

function syncInputFiles() {
  try {
    const transfer = new DataTransfer();
    for (const track of tracks) transfer.items.add(track.file);
    input.files = transfer.files;
  } catch {
    input.value = "";
  }
}

function revokeTrackURLs(track) {
  if (track.sourceURL) URL.revokeObjectURL(track.sourceURL);
  if (track.waveformURL) URL.revokeObjectURL(track.waveformURL);
  track.sourceURL = null;
  track.waveformURL = null;
}

function clearTracks(resetInput = true) {
  switchVersion++;
  cancelAnimationFrame(playheadFrame);
  clearAudio(sourceAudio);
  for (const track of tracks) revokeTrackURLs(track);
  tracks = [];
  selectedFiles = [];
  activeTrackId = null;
  byId("file-info").replaceChildren();
  byId("track-switcher").replaceChildren();
  byId("selection-summary").textContent = "";
  byId("source-time").textContent = "0:00 / 0:00";
  byId("source").hidden = true;
  if (resetInput) input.value = "";
}

function removeTrack(id) {
  if (active) return;
  const index = tracks.findIndex((track) => track.id === Number(id));
  if (index < 0) return;
  clearResult();
  const removed = tracks[index];
  const wasActive = removed.id === activeTrackId;
  const position = sourceAudio.currentTime;
  const resume = !sourceAudio.paused && !sourceAudio.ended;
  tracks.splice(index, 1);
  revokeTrackURLs(removed);
  selectedFiles = tracks.map((track) => track.file);
  syncInputFiles();
  if (!tracks.length) {
    clearTracks();
    status.textContent = "Выберите файлы и нажмите «Обработать».";
    setBusy(false);
    return;
  }
  if (wasActive) activeTrackId = tracks[Math.min(index, tracks.length - 1)].id;
  renderTracks();
  if (wasActive) void activateTrack(activeTrackId, position, resume);
  status.textContent = selectionStatus();
  setBusy(false);
}

function createOperation(kind) {
  let cancelOperation;
  const cancelled = new Promise((resolve) => { cancelOperation = resolve; });
  const operation = {
    kind,
    cancel: () => cancelOperation({ cancelled: true }),
    wait: async (promise) => {
      const value = await Promise.race([promise, cancelled]);
      if (active !== operation) throw new Error(CANCELLED);
      return value;
    }
  };
  active = operation;
  return operation;
}

async function ensureEngine(operation) {
  if (engine?.loaded) return engine;
  let preparedEngine;
  let loadTimer;
  try {
    const preparation = (async () => {
      const { FFmpeg } = await operation.wait(import("../vendor/ffmpeg/ffmpeg/index.js"));
      engine = new FFmpeg();
      preparedEngine = engine;
      await operation.wait(preparedEngine.load({
        coreURL: new URL("../vendor/ffmpeg/core/ffmpeg-core.js", import.meta.url).href,
        wasmURL: new URL("../vendor/ffmpeg/core/ffmpeg-core.wasm", import.meta.url).href
      }));
    })();
    await operation.wait(Promise.race([preparation, new Promise((_, reject) => {
      loadTimer = setTimeout(() => reject(new Error("Не удалось загрузить обработчик. Попробуйте ещё раз.")), 180000);
    })]));
    return engine;
  } catch (failure) {
    if (engine === preparedEngine) {
      preparedEngine?.terminate();
      engine = null;
    }
    throw failure;
  } finally {
    clearTimeout(loadTimer);
  }
}

function readTrackDuration(track, operation) {
  const probe = document.createElement("audio");
  probe.preload = "metadata";
  probe.src = track.sourceURL;
  let timer;
  return operation.wait(new Promise((resolve, reject) => {
    const done = () => Number.isFinite(probe.duration) && probe.duration > 0 ? resolve(probe.duration) : reject(new Error("metadata"));
    probe.addEventListener("loadedmetadata", done, { once: true });
    probe.addEventListener("error", () => reject(new Error("metadata")), { once: true });
    timer = setTimeout(() => reject(new Error("metadata")), 30000);
  })).finally(() => {
    clearTimeout(timer);
    probe.removeAttribute("src");
    probe.load();
  });
}

async function buildWaveform(track, currentEngine, operation) {
  const inputPath = `processor-waveform-input-${track.id}`;
  const outputPath = `processor-waveform-${track.id}.png`;
  track.loading = true;
  track.waveformFailed = false;
  renderTracks();
  try {
    try { track.duration = await readTrackDuration(track, operation); } catch { /* Native playback may still be usable. */ }
    track.waveformWidth = waveformWidth(track.duration);
    renderTracks();
    const bytes = new Uint8Array(await operation.wait(track.file.arrayBuffer()));
    await operation.wait(currentEngine.writeFile(inputPath, bytes));
    const filter = `[0:a:0]aformat=channel_layouts=mono,showwavespic=s=${track.waveformWidth}x${WAVEFORM_HEIGHT}:colors=#74b2e6[v]`;
    const code = await operation.wait(currentEngine.exec(["-hide_banner", "-nostats", "-xerror", "-protocol_whitelist", "file", "-i", inputPath,
      "-filter_complex", filter, "-map", "[v]", "-frames:v", "1", "-an", outputPath]));
    if (code !== 0) throw new Error("waveform");
    const image = await operation.wait(currentEngine.readFile(outputPath));
    if (!image.byteLength) throw new Error("waveform");
    if (track.waveformURL) URL.revokeObjectURL(track.waveformURL);
    track.waveformURL = URL.createObjectURL(new Blob([image], { type: "image/png" }));
  } catch (failure) {
    if (active === operation) track.waveformFailed = true;
  } finally {
    track.loading = false;
    if (currentEngine?.loaded && engine === currentEngine) {
      for (const path of [inputPath, outputPath]) {
        try { await operation.wait(currentEngine.deleteFile(path)); } catch { /* Absent or terminated. */ }
      }
    }
    if (tracks.includes(track)) renderTracks();
  }
}

async function generateWaveforms(candidates = tracks) {
  if (active || !candidates.length || !supported) return;
  const operation = createOperation("waveform");
  setBusy(true);
  status.textContent = "Подготовка формы сигнала…";
  let currentEngine;
  try {
    currentEngine = await ensureEngine(operation);
    for (const track of candidates) await buildWaveform(track, currentEngine, operation);
    if (active === operation) status.textContent = selectionStatus();
  } catch {
    if (active === operation) {
      for (const track of candidates.filter((item) => !item.waveformURL)) {
        track.loading = false;
        track.waveformFailed = true;
      }
      renderTracks();
      status.textContent = selectionStatus();
    }
  } finally {
    if (active === operation) {
      active = null;
      setBusy(false);
      renderTracks();
    }
  }
}

input.addEventListener("change", () => {
  if (active) return;
  clearResult();
  clearTracks(false);
  const files = Array.from(input.files || []);
  const error = validateFiles(files);
  status.textContent = error || "Выберите файлы и нажмите «Обработать».";
  if (files.length && !error && supported) {
    tracks = files.map((file) => ({
      id: nextTrackId++, file, sourceURL: URL.createObjectURL(file), waveformURL: null,
      waveformWidth: WAVEFORM_MIN_WIDTH, waveformFailed: false, loading: false, duration: NaN, ordinal: 0
    }));
    selectedFiles = files;
    activeTrackId = tracks[0].id;
    byId("source").hidden = false;
    renderTracks();
    void activateTrack(activeTrackId, 0, false);
    void generateWaveforms();
  }
  if (!active) setBusy(false);
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
  const operation = createOperation("processing");
  clearResult();
  setBusy(true);
  status.textContent = "Подготовка обработчика…";
  let currentEngine;
  let logListener;
  try {
    currentEngine = await ensureEngine(operation);
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
  for (const track of tracks) revokeTrackURLs(track);
});
window.addEventListener("pageshow", (event) => {
  if (event.persisted && tracks.length) {
    for (const track of tracks) {
      track.sourceURL = URL.createObjectURL(track.file);
      track.waveformURL = null;
      track.waveformFailed = false;
    }
    renderTracks();
    void activateTrack(activeTrackId || tracks[0].id, sourceAudio.currentTime, false);
    void generateWaveforms();
  }
});
status.textContent = supported ? "Выберите файлы и нажмите «Обработать»." : UNSUPPORTED;
setBusy(false);
byId("heading").dataset.ready = "true";
