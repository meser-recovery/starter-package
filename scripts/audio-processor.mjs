import { createWaveformDetail } from "./audio-waveform-detail.mjs";
import { createWaveformReader } from "./speaker-waveform.mjs";
import { drawWaveformViewport } from "./audio-waveform-view.mjs";
import { renderSourceTimeline } from "./audio-timeline.mjs";
import { createAudioMeters } from "./audio-meters.mjs";
import { createAudioTransport } from "./audio-transport.mjs";
import { defaultTrackColor, installEditorExpansion, installSpaceTransport, installTimelineZoomGestures } from "./audio-timeline-ux.mjs";
import { sha256Hex } from "./audio-archive-client.mjs";
const sourceDetail = createWaveformDetail();

// Stage 7 DSP contract: S08B adds provenance/publication only and does not alter these values.
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
// Bounded high-resolution envelopes for detailed zoom, including Retina screens.
const WAVEFORM_PIXELS_PER_SECOND = 64;
const WAVEFORM_MIN_WIDTH = 4096;
const WAVEFORM_MAX_WIDTH = 65536;
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
let selectedProvenance = [];
let provenanceContext = null;
let resultCandidate = null;
let tracks = [];
let sourceSelection = null, sourceSelectionEpoch = 0;
let nextTrackId = 1;
let resultURL = null;
let resultWaveformSamples = null;
let resultWaveformFile = null;
let engine = null;
let active = null;
let playheadFrame = 0;
let resultPlayheadFrame = 0;
let previewSyncTimer = 0;
const sourceSynchronizedScroll = new WeakMap();
let sourcePixelsPerSecond = 2;
let sourceTimelineDuration = NaN;
let sourceLeftVisibleTime = 0;
let sourceViewportDuration = 0;
let sourceFollowEnabled = false;
let sourceZoomMinimum = 2;
let sourceZoomMaximum = 2;
let sourceZoomInitialized = false;
let sourceScaleMode = "time";
let sourceTimeZoomValue = 50;
let sourceTrackHeight = 196;
let sourceLoopEnabled = false;
let sourceLoopRange = null;
let resultPixelsPerSecond = 2;
let resultDuration = NaN;
let resultWaveformWidth = WAVEFORM_MIN_WIDTH;
let resultZoomMinimum = 2;
let resultZoomMaximum = 2;
const sourceTransport = createAudioTransport({
  audio: sourceAudio, resultAudio, canPlay: () => !active && tracks.length > 0 && tracks.every(track => Number.isFinite(track.duration)),
  getSelection: () => sourceSelection,
  seek: seekSources, reportError: message => { status.textContent = message; },
  onLoopChange: ({ enabled, range }) => { sourceLoopEnabled = enabled; sourceLoopRange = range; renderProcessorGlobalRegions(); }
});

const meters = createAudioMeters({ root: sourceAudio.closest(".processor-card"), resultAudio });
function syncMeters() {
  meters.sync(tracks.map(track => ({ id: String(track.id), audio: track.previewAudio, container: [...byId("file-info").children].find(row => row.dataset.trackId === String(track.id))?.querySelector(".processor-track__top") })));
}

function notifyProcessorSelection() {
  window.dispatchEvent(new CustomEvent("audio-processor-selection", {
    detail: { files: [...selectedFiles], provenance: structuredClone(selectedProvenance), provenanceContext: structuredClone(provenanceContext) }
  }));
}

function syncSelectedProvenance() {
  selectedProvenance = tracks.every((track) => track.provenance)
    ? tracks.map((track, index) => ({ ...structuredClone(track.provenance), ordinal: index + 1 }))
    : [];
}

function notifyProcessorResult() {
  window.dispatchEvent(new CustomEvent("audio-processor-result", { detail: { candidate: getProcessorResult() } }));
}

const idleWaiters = new Set();
export async function bindProcessorSources(files, provenance, context) {
  if (active) await new Promise(resolve => idleWaiters.add(resolve));
  if (files.length !== selectedFiles.length || files.some((file, i) => file !== selectedFiles[i]) || provenance.length !== files.length) throw new Error("Состав выбранных дорожек изменился.");
  tracks.forEach((track, index) => { track.provenance = structuredClone(provenance[index]); });
  syncSelectedProvenance(); provenanceContext = structuredClone(context);
  // An existing local result keeps its original provenance and remains downloadable.
  notifyProcessorSelection();
}
export function getProcessorFiles() {
  return [...selectedFiles];
}

export function getProcessorResult() {
  return resultCandidate ? { ...structuredClone({ ...resultCandidate, blob: null }), blob: resultCandidate.blob } : null;
}

export function updateProcessorProvenanceContext(context) {
  if (active) throw new Error("Дождитесь завершения текущей операции.");
  if (!selectedProvenance.length) return;
  clearResult();
  provenanceContext = structuredClone(context);
  notifyProcessorSelection();
}

export function clearProcessorFiles() {
  if (active) throw new Error("Дождитесь завершения текущей операции.");
  clearResult();
  clearTracks();
  status.textContent = "Выберите файлы и нажмите «Обработать».";
  setBusy(false);
}

export function loadProcessorFiles(files, provenance = [], context = null) {
  if (active) throw new Error("Дождитесь завершения текущей операции.");
  const selected = Array.from(files || []);
  const error = validateFiles(selected);
  if (!selected.length || error) throw new Error(error || "Выберите хотя бы одну аудиодорожку.");
  if (provenance.length && provenance.length !== selected.length) throw new Error("Происхождение дорожек не соответствует выбранным файлам.");
  selectProcessorFiles(selected, provenance, context);
}

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
  cancelAnimationFrame(resultPlayheadFrame);
  clearAudio(resultAudio);
  if (resultURL) URL.revokeObjectURL(resultURL);
  resultURL = null;
  resultWaveformSamples = null; resultWaveformFile = null;
  resultDuration = NaN;
  resultWaveformWidth = WAVEFORM_MIN_WIDTH;
  const resultControl = byId("result-waveform-control");
  resultControl.replaceChildren();
  resultControl.style.width = "100%";
  byId("result-waveform-scroll").hidden = true;
  byId("result-waveform-status").hidden = true;
  byId("result-waveform-status").textContent = "";
  byId("result-time").textContent = "0:00 / 0:00";
  download.removeAttribute("href");
  download.removeAttribute("download");
  resultCandidate = null;
  notifyProcessorResult();
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
  for (const control of result.querySelectorAll("button, input")) {
    if (control.id !== "source-session-publish-announcement") control.disabled = busy;
  }
  if (!busy) {
    for (const resolve of idleWaiters) resolve(); idleWaiters.clear();
    updateSourceZoomRange();
    if (resultWaveformSamples) updateResultZoomRange();
  }
  sourceTransport.refresh();
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

function sourceDisplayWidth(track) {
  if (!sourceZoomInitialized || !Number.isFinite(sourceTimelineDuration) || sourceTimelineDuration <= 0) return track.waveformWidth;
  return Math.max(1, Math.ceil(sourceTimelineDuration * sourcePixelsPerSecond));
}

function maximumSourceLeftTime() {
  return Math.max(0, (Number.isFinite(sourceTimelineDuration) ? sourceTimelineDuration : 0) - sourceViewportDuration);
}

function sourceScrollbarGeometry() {
  const rail = byId("source-scrollbar");
  const railStyle = getComputedStyle(rail);
  const railWidth = Math.max(0, rail.getBoundingClientRect().width -
    parseFloat(railStyle.borderLeftWidth) - parseFloat(railStyle.borderRightWidth));
  const duration = Number.isFinite(sourceTimelineDuration) ? sourceTimelineDuration : 0;
  const fraction = duration > 0 ? Math.min(1, Math.max(0, sourceViewportDuration / duration)) : 1;
  const thumbWidth = railWidth ? Math.min(railWidth, Math.max(36, railWidth * fraction)) : 0;
  const maxLeft = maximumSourceLeftTime();
  const travel = Math.max(0, railWidth - thumbWidth);
  return { railWidth, thumbWidth, maxLeft, travel };
}

function updateSourceScrollbar() {
  const rail = byId("source-scrollbar");
  const thumb = byId("source-scrollbar-thumb");
  const { thumbWidth, maxLeft, travel } = sourceScrollbarGeometry();
  const position = maxLeft > 0 ? sourceLeftVisibleTime / maxLeft * travel : 0;
  thumb.style.width = `${thumbWidth}px`;
  thumb.style.transform = `translateX(${Math.max(0, Math.min(travel, position))}px)`;
  rail.setAttribute("aria-valuemin", "0");
  rail.setAttribute("aria-valuemax", String(Math.round(maxLeft * 1000) / 1000));
  rail.setAttribute("aria-valuenow", String(Math.round(sourceLeftVisibleTime * 1000) / 1000));
  renderSourceTimeline("announcement-source-timeline", sourceTimelineDuration, sourcePixelsPerSecond, sourceLeftVisibleTime * sourcePixelsPerSecond);
  renderProcessorGlobalRegions();
  rail.setAttribute("aria-valuetext", `${clockDuration(sourceLeftVisibleTime)} из ${clockDuration(Number.isFinite(sourceTimelineDuration) ? sourceTimelineDuration : 0)}`);
}

function setSourceLeftVisibleTime(value) {
  sourceLeftVisibleTime = Math.max(0, Math.min(maximumSourceLeftTime(), Number.isFinite(value) ? value : 0));
  const target = sourceLeftVisibleTime * sourcePixelsPerSecond;
  for (const scroll of byId("file-info").querySelectorAll(".processor-waveform-scroll")) {
    if (Math.abs(scroll.scrollLeft - target) > .5) scroll.scrollLeft = target;
    // Retain the browser-rounded/clamped position, not an ideal float target.
    sourceSynchronizedScroll.set(scroll, scroll.scrollLeft);
  }
  updateSourceScrollbar();
  redrawSourceDetails();
}

function setSourceFollow(enabled) {
  sourceFollowEnabled = Boolean(enabled);
  byId("source-follow").setAttribute("aria-pressed", String(sourceFollowEnabled));
  if (sourceFollowEnabled) followSourcePlayhead(sourceAudio.currentTime || 0);
}

function disengageSourceFollow() {
  if (sourceFollowEnabled) setSourceFollow(false);
}

function followSourcePlayhead(time = sourceAudio.currentTime || 0) {
  if (!sourceFollowEnabled) return;
  setSourceLeftVisibleTime(time - sourceViewportDuration / 2);
}

function updateSourceNavigation() {
  const viewport = byId("file-info").querySelector(".processor-waveform-scroll");
  const navigation = byId("source-navigation");
  if (!tracks.length) {
    navigation.hidden = true;
    sourceViewportDuration = 0;
    sourceLeftVisibleTime = 0;
    updateSourceScrollbar();
    return;
  }
  navigation.hidden = false;
  if (!viewport || !sourceZoomInitialized || !Number.isFinite(sourceTimelineDuration) || sourcePixelsPerSecond <= 0) {
    sourceViewportDuration = 0;
    sourceLeftVisibleTime = 0;
    updateSourceScrollbar();
    return;
  }
  sourceViewportDuration = viewport.clientWidth / sourcePixelsPerSecond;
  setSourceLeftVisibleTime(sourceLeftVisibleTime);
}

function seekSources(seconds) {
  const target = Math.max(0, Math.min(Number.isFinite(sourceTimelineDuration) ? sourceTimelineDuration : seconds, seconds));
  for (const track of tracks) {
    const audio = track.previewAudio;
    if (!audio) continue;
    const duration = Number.isFinite(audio.duration) ? audio.duration : track.duration;
    try { audio.currentTime = Number.isFinite(duration) ? Math.min(target, duration) : target; } catch { /* Metadata is pending. */ }
  }
  if (sourceFollowEnabled) followSourcePlayhead(target);
  updatePlayheads();
}

function seekFromControl(event) {
  const scroll = event.currentTarget.closest(".processor-waveform-scroll");
  if (!scroll || Date.now() - Number(scroll.dataset.dragEnded || 0) < 150) return;
  const box = scroll.getBoundingClientRect();
  seekSources((scroll.scrollLeft + event.clientX - box.left) / sourcePixelsPerSecond);
}

function updateSourceSelection(range) {
  sourceSelection = range;
  for (const wave of byId("file-info").querySelectorAll(".processor-waveform")) {
    wave.querySelector(".processor-selection-overlay")?.remove();
    if (!range || !(sourceTimelineDuration > 0)) continue;
    const overlay = document.createElement("span"); overlay.className = "processor-selection-overlay";
    overlay.style.left = `${range.startSeconds / sourceTimelineDuration * 100}%`;
    overlay.style.width = `${(range.endSeconds - range.startSeconds) / sourceTimelineDuration * 100}%`;
    wave.append(overlay);
  }
  let summary = byId("loop-selection-summary");
  if (!summary) { summary = document.createElement("span"); summary.id = "processor-loop-selection-summary"; sourceAudio.before(summary); }
  summary.textContent = range ? `Выделение: ${range.startSeconds.toFixed(3)}–${range.endSeconds.toFixed(3)} с` : "Клик — позиция; протянуть — выделить для повтора; Alt + протянуть — прокрутка.";
  sourceTransport.refresh();
}

let processorLoopDrag = null;
function paintProcessorLoopStrip(strip) {
  if (!strip || !sourceLoopRange || !(sourceTimelineDuration > 0)) return;
  strip.style.left = `${sourceLoopRange.startSeconds / sourceTimelineDuration * 100}%`;
  strip.style.width = `${(sourceLoopRange.endSeconds - sourceLoopRange.startSeconds) / sourceTimelineDuration * 100}%`;
  strip.title = `Loop · ${sourceLoopRange.startSeconds.toFixed(3)}–${sourceLoopRange.endSeconds.toFixed(3)} с`;
  for (const handle of strip.querySelectorAll("[data-loop-edge]")) {
    const value = sourceLoopRange[handle.dataset.loopEdge === "start" ? "startSeconds" : "endSeconds"];
    handle.setAttribute("aria-valuenow", String(value)); handle.setAttribute("aria-valuetext", `${value.toFixed(3)} с`);
  }
}

function bindProcessorLoopHandle(handle, edge) {
  let drag = null;
  const cancelDrag = () => {
    if (!drag) return;
    const old = drag; drag = null; processorLoopDrag = null;
    if (handle.hasPointerCapture(old.id)) handle.releasePointerCapture(old.id);
    updateSourceSelection(old.range);
  };
  const update = event => {
    if (!drag || drag.id !== event.pointerId) return;
    const delta = (event.clientX - drag.x) / sourcePixelsPerSecond;
    let start = drag.range.startSeconds, end = drag.range.endSeconds;
    if (edge === "start") start = Math.max(0, Math.min(end - .000001, start + delta));
    else end = Math.min(sourceTimelineDuration, Math.max(start + .000001, end + delta));
    updateSourceSelection({ startSeconds: start, endSeconds: end });
  };
  handle.addEventListener("pointerdown", event => {
    if (event.button !== 0 || !sourceLoopEnabled || active || !sourceLoopRange) return;
    event.preventDefault(); event.stopPropagation(); drag = { id: event.pointerId, x: event.clientX, range: { ...sourceLoopRange } };
    processorLoopDrag = drag; handle.setPointerCapture(event.pointerId);
  });
  handle.addEventListener("pointermove", update);
  handle.addEventListener("pointerup", event => {
    if (!drag || drag.id !== event.pointerId) return;
    update(event); drag = null; processorLoopDrag = null;
    if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId);
    renderProcessorGlobalRegions();
  });
  handle.addEventListener("pointercancel", cancelDrag); handle.addEventListener("lostpointercapture", cancelDrag);
  handle.addEventListener("keydown", event => {
    if (event.key === "Escape") { event.stopPropagation(); cancelDrag(); return; }
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key) || !sourceLoopRange) return;
    event.preventDefault(); event.stopPropagation(); const step = event.shiftKey ? 1 : .01;
    let start = sourceLoopRange.startSeconds, end = sourceLoopRange.endSeconds;
    const value = event.key === "Home" ? 0 : event.key === "End" ? sourceTimelineDuration : (edge === "start" ? start : end) + (event.key === "ArrowLeft" ? -step : step);
    if (edge === "start") start = Math.max(0, Math.min(end - .000001, value)); else end = Math.min(sourceTimelineDuration, Math.max(start + .000001, value));
    updateSourceSelection({ startSeconds: start, endSeconds: end });
  });
}

function renderProcessorGlobalRegions() {
  const layer = byId("global-regions"); const first = byId("file-info")?.querySelector(".processor-waveform-scroll");
  for (const wave of byId("file-info")?.querySelectorAll(".processor-waveform") || []) {
    wave.querySelector(".timeline-loop-region")?.remove();
    if (sourceLoopEnabled && sourceLoopRange && sourceTimelineDuration > 0) {
      const loop = document.createElement("span"); loop.className = "timeline-loop-region";
      loop.style.left = `${sourceLoopRange.startSeconds / sourceTimelineDuration * 100}%`;
      loop.style.width = `${(sourceLoopRange.endSeconds - sourceLoopRange.startSeconds) / sourceTimelineDuration * 100}%`;
      loop.title = `Loop · ${sourceLoopRange.startSeconds.toFixed(3)}–${sourceLoopRange.endSeconds.toFixed(3)} с`; wave.append(loop);
    }
  }
  if (!layer || !first || !(sourceTimelineDuration > 0)) { layer?.replaceChildren(); return; }
  layer.style.width = `${Math.max(first.clientWidth, Math.ceil(sourceTimelineDuration * sourcePixelsPerSecond))}px`;
  layer.style.transform = `translateX(${-first.scrollLeft}px)`;
  if (processorLoopDrag) { paintProcessorLoopStrip(layer.querySelector(".timeline-loop-strip")); return; }
  layer.replaceChildren();
  if (!sourceLoopEnabled || !sourceLoopRange) return;
  const strip = document.createElement("span"); strip.className = "timeline-loop-strip";
  const label = document.createElement("span"); label.className = "timeline-region-label"; label.textContent = "Loop"; strip.append(label);
  for (const edge of ["start", "end"]) {
    const handle = document.createElement("span"); handle.className = `timeline-loop-handle timeline-loop-handle--${edge}`; handle.dataset.loopEdge = edge;
    handle.tabIndex = 0; handle.setAttribute("role", "slider"); handle.setAttribute("aria-valuemin", "0"); handle.setAttribute("aria-valuemax", String(sourceTimelineDuration));
    handle.setAttribute("aria-label", `Loop: ${edge === "start" ? "левая" : "правая"} граница`); bindProcessorLoopHandle(handle, edge); strip.append(handle);
  }
  paintProcessorLoopStrip(strip); layer.append(strip);
}

function installSourceSelection(scroll) {
  let drag = null;
  const time = event => Math.max(0, Math.min(sourceTimelineDuration,
    (scroll.scrollLeft + event.clientX - scroll.getBoundingClientRect().left) / sourcePixelsPerSecond));
  scroll.addEventListener("pointerdown", event => {
    if (drag || event.button !== 0 || event.altKey || active || !Number.isFinite(sourceTimelineDuration)) return;
    drag = { id: event.pointerId, x: event.clientX, start: time(event), previous: sourceSelection, epoch: sourceSelectionEpoch };
    scroll.setPointerCapture(event.pointerId);
  });
  scroll.addEventListener("pointermove", event => {
    if (!drag || drag.id !== event.pointerId || drag.epoch !== sourceSelectionEpoch || active || Math.abs(event.clientX - drag.x) <= 4) return;
    const end = time(event);
    updateSourceSelection({ startSeconds: Math.min(drag.start, end), endSeconds: Math.max(drag.start, end) });
  });
  scroll.addEventListener("pointerup", event => {
    if (!drag || drag.id !== event.pointerId) return;
    const current = drag; drag = null; scroll.releasePointerCapture(event.pointerId);
    if (current.epoch !== sourceSelectionEpoch) return;
    if (active) { updateSourceSelection(current.previous); return; }
    if (Math.abs(event.clientX - current.x) <= 4) { updateSourceSelection(null); seekSources(time(event)); }
    else { const end = time(event); updateSourceSelection({ startSeconds: Math.min(current.start, end), endSeconds: Math.max(current.start, end) }); }
    scroll.dataset.dragEnded = String(Date.now());
  });
  const cancel = () => { if (drag) { const previous = drag; drag = null; if (previous.epoch === sourceSelectionEpoch) updateSourceSelection(previous.previous); } };
  scroll.addEventListener("pointercancel", cancel); scroll.addEventListener("lostpointercapture", cancel);
}

function navigateWaveform(event) {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const current = sourceAudio.currentTime || 0;
  if (event.shiftKey) {
    const start = sourceSelection?.startSeconds ?? current, end = sourceSelection?.endSeconds ?? current;
    const next = event.key === "Home" ? start : event.key === "End" ? sourceTimelineDuration : end + (event.key === "ArrowLeft" ? -.1 : .1);
    updateSourceSelection({ startSeconds: start, endSeconds: Math.max(start, Math.min(sourceTimelineDuration, next)) });
    return;
  }
  updateSourceSelection(null);
  const step = 5;
  const target = event.key === "Home" ? 0 : event.key === "End" ? sourceTimelineDuration :
    current + (event.key === "ArrowLeft" ? -step : step);
  seekSources(target);
}

function installPan(scroll, onManualPan, altOnly = false) {
  let startX = 0;
  let startScroll = 0;
  let dragging = false, panPointer = null;
  scroll.addEventListener("pointerdown", (event) => {
    if (panPointer !== null || event.button !== 0 || (altOnly && !event.altKey)) return;
    panPointer = event.pointerId;
    startX = event.clientX;
    startScroll = scroll.scrollLeft;
    dragging = false;
    scroll.setPointerCapture(event.pointerId);
  });
  scroll.addEventListener("pointermove", (event) => {
    if (panPointer !== event.pointerId || !scroll.hasPointerCapture(event.pointerId)) return;
    if (Math.abs(event.clientX - startX) > 6 && !dragging) {
      dragging = true;
      onManualPan?.();
    }
    if (!dragging) return;
    event.preventDefault();
    scroll.classList.add("is-dragging");
    scroll.scrollLeft = startScroll - (event.clientX - startX);
  });
  const finish = (event) => {
    if (panPointer !== event.pointerId || !scroll.hasPointerCapture(event.pointerId)) return;
    panPointer = null; scroll.releasePointerCapture(event.pointerId);
    scroll.classList.remove("is-dragging");
    if (dragging) scroll.dataset.dragEnded = String(Date.now());
  };
  scroll.addEventListener("pointerup", finish);
  scroll.addEventListener("pointercancel", finish);
}

function syncSourceScroll(event) {
  if (sourcePixelsPerSecond <= 0) return;
  const origin = event.currentTarget;
  // Our scroll event may arrive after rendering/decoding has finished. Ignore
  // an unchanged synchronized position regardless of elapsed frames, while a
  // new user position must still apply immediately after zoom.
  if (origin.scrollLeft === sourceSynchronizedScroll.get(origin)) return;
  disengageSourceFollow();
  setSourceLeftVisibleTime(origin.scrollLeft / sourcePixelsPerSecond);
}

function redrawSourceDetails() {
  for (const track of tracks) {
    const wave = byId("file-info").querySelector(`.processor-waveform[data-track-id="${track.id}"]`);
    const scroll = wave?.parentElement, canvas = wave?.querySelector("canvas");
    if (!canvas || !scroll || !track.samples) continue;
    canvas.hidden = false;
    if (!sourceDetail.draw(canvas, track.file, track.duration, sourcePixelsPerSecond, scroll.scrollLeft,
      scroll.clientWidth, wave.clientHeight || WAVEFORM_HEIGHT, track.samples.sampleRate)) {
      drawWaveformViewport(canvas, track.samples, track.duration, sourcePixelsPerSecond, scroll.scrollLeft,
        scroll.clientWidth, wave.clientHeight || WAVEFORM_HEIGHT);
    }
  }
}

function waveformControl(track) {
  const control = document.createElement("button");
  control.type = "button";
  control.className = "processor-waveform";
  control.dataset.trackId = String(track.id);
  control.dataset.trackAction = "waveform";
  control.style.width = `${sourceDisplayWidth(track)}px`;
  control.setAttribute("aria-label", `Форма сигнала дорожки ${track.ordinal}: ${track.file.name}`);
  control.setAttribute("aria-describedby", "processor-source-time");
  control.addEventListener("keydown", navigateWaveform);
  if (!track.samples) {
    const message = document.createElement("span");
    message.className = "processor-waveform-status";
    message.textContent = track.loading ? "Подготовка формы сигнала…" :
      track.waveformFailed ? "Не удалось построить форму сигнала." : "Форма сигнала ещё не построена.";
    control.append(message);
  }
  const detailCanvas = document.createElement("canvas"); detailCanvas.hidden = true;
  detailCanvas.className = "processor-waveform-detail"; control.append(detailCanvas);
  if (sourceTimelineDuration > 0 && Number.isFinite(track.duration) && track.duration < sourceTimelineDuration) {
    const outside = document.createElement("span"); outside.className = "timeline-outside-region";
    outside.style.left = `${track.duration / sourceTimelineDuration * 100}%`; outside.style.width = `${(sourceTimelineDuration - track.duration) / sourceTimelineDuration * 100}%`;
    outside.title = `Вне записи · ${track.duration.toFixed(3)}–${sourceTimelineDuration.toFixed(3)} с`;
    const label = document.createElement("span"); label.className = "timeline-region-label"; label.textContent = "Вне записи"; outside.append(label); control.append(outside);
  }
  if (sourceLoopEnabled && sourceLoopRange && sourceTimelineDuration > 0) {
    const loop = document.createElement("span"); loop.className = "timeline-loop-region";
    loop.style.left = `${sourceLoopRange.startSeconds / sourceTimelineDuration * 100}%`; loop.style.width = `${(sourceLoopRange.endSeconds - sourceLoopRange.startSeconds) / sourceTimelineDuration * 100}%`;
    loop.title = `Loop · ${sourceLoopRange.startSeconds.toFixed(3)}–${sourceLoopRange.endSeconds.toFixed(3)} с`; control.append(loop);
  }
  const playhead = document.createElement("span");
  playhead.className = "processor-waveform-playhead";
  playhead.setAttribute("aria-hidden", "true");
  control.append(playhead);
  return control;
}

function renderTracks() {
  const list = byId("file-info");
  list.replaceChildren();
  tracks.forEach((track, index) => {
    track.ordinal = index + 1;
    const item = document.createElement("li");
    item.className = "processor-track";
    item.dataset.trackId = String(track.id);
    item.style.setProperty("--track-wave", track.color || defaultTrackColor(index));
    const top = document.createElement("div");
    top.className = "processor-track__top";
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
    const colorLabel = document.createElement("label"); colorLabel.className = "track-color-control";
    const color = document.createElement("input"); color.type = "color"; color.value = track.color || defaultTrackColor(index);
    color.setAttribute("aria-label", `Цвет дорожки ${track.ordinal}: ${track.file.name}`); color.title = color.getAttribute("aria-label");
    color.addEventListener("input", () => { track.color = color.value; item.style.setProperty("--track-wave", track.color); redrawSourceDetails(); });
    colorLabel.append(color); heading.append(colorLabel, number, name, meta);
    const scroll = document.createElement("div");
    scroll.className = "processor-waveform-scroll";
    scroll.dataset.trackId = String(track.id);
    scroll.append(waveformControl(track));
    scroll.addEventListener("click", seekFromControl);
    scroll.addEventListener("scroll", syncSourceScroll, { passive: true });
    scroll.addEventListener("wheel", (event) => {
      if (Math.abs(event.deltaX) > Math.abs(event.deltaY) || event.shiftKey) disengageSourceFollow();
    }, { passive: true });
    installTimelineZoomGestures(scroll, { getZoom: () => sourcePixelsPerSecond, setZoomAt: setProcessorZoomAt });
    installSourceSelection(scroll);
    installPan(scroll, disengageSourceFollow, true);
    const actions = document.createElement("div");
    actions.className = "processor-track__actions";
    const solo = document.createElement("button");
    solo.type = "button";
    solo.dataset.trackId = String(track.id);
    solo.dataset.trackAction = "solo";
    solo.setAttribute("aria-pressed", String(track.solo));
    solo.textContent = "S · Solo";
    solo.addEventListener("click", () => toggleMonitoring(track.id, "solo"));
    const mute = document.createElement("button");
    mute.type = "button";
    mute.dataset.trackId = String(track.id);
    mute.dataset.trackAction = "mute";
    mute.setAttribute("aria-pressed", String(track.muted));
    mute.textContent = "M · Mute";
    mute.addEventListener("click", () => toggleMonitoring(track.id, "mute"));
    for (const [button, action] of [[solo, "Solo"], [mute, "Mute"]]) {
      button.title = `${action} · Дорожка ${index + 1} · ${track.file.name} · только прослушивание`;
      button.setAttribute("aria-label", button.textContent);
      button.setAttribute("aria-description", button.title);
      button.textContent = action === "Solo" ? "S" : "M";
    }
    const moveUp = document.createElement("button");
    moveUp.type = "button";
    moveUp.dataset.trackId = String(track.id);
    moveUp.dataset.trackAction = "move-up";
    moveUp.disabled = index === 0;
    moveUp.setAttribute("aria-label", `Переместить дорожку ${track.ordinal} вверх: ${track.file.name}`);
    moveUp.textContent = "Вверх";
    moveUp.addEventListener("click", () => moveTrack(track.id, -1));
    const moveDown = document.createElement("button");
    moveDown.type = "button";
    moveDown.dataset.trackId = String(track.id);
    moveDown.dataset.trackAction = "move-down";
    moveDown.disabled = index === tracks.length - 1;
    moveDown.setAttribute("aria-label", `Переместить дорожку ${track.ordinal} вниз: ${track.file.name}`);
    moveDown.textContent = "Вниз";
    moveDown.addEventListener("click", () => moveTrack(track.id, 1));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.dataset.trackId = String(track.id);
    remove.dataset.trackAction = "remove";
    remove.setAttribute("aria-label", `Удалить дорожку ${track.ordinal}: ${track.file.name}`);
    remove.textContent = "Удалить";
    remove.addEventListener("click", () => removeTrack(track.id));
    actions.append(solo, mute, moveUp, moveDown, remove);
    const monitorStatus = document.createElement("span"); monitorStatus.className = "track-monitor-status";
    actions.append(monitorStatus);
    top.append(heading, actions);
    item.append(top, scroll);
    list.append(item);
    scroll.scrollLeft = sourceLeftVisibleTime * sourcePixelsPerSecond;
  });
  syncMeters();
  applyProcessorTrackHeight();
  updateSelectionSummary();
  setBusy(Boolean(active));
  applyMonitoring();
  if (sourceZoomInitialized) updateSourceNavigation();
  updatePlayheads();
  updateSourceSelection(sourceSelection);
}

function updatePlayheads() {
  const current = Number.isFinite(sourceAudio.currentTime) ? sourceAudio.currentTime : 0;
  for (const track of tracks) {
    const control = byId("source").querySelector(`.processor-waveform[data-track-id="${track.id}"]`);
    const playhead = control?.querySelector(".processor-waveform-playhead");
    if (playhead) playhead.style.left = `${Math.min(control.offsetWidth, current * sourcePixelsPerSecond)}px`;
  }
  byId("source-time").textContent = `${clockDuration(current)} / ${clockDuration(sourceTimelineDuration)}`;
}

function animatePlayhead() {
  cancelAnimationFrame(playheadFrame);
  const frame = () => {
    // A frame queued before pause must not move the zoomed viewport afterward.
    if (sourceAudio.paused || sourceAudio.ended) return;
    if (sourceFollowEnabled) followSourcePlayhead(sourceAudio.currentTime || 0);
    updatePlayheads();
    if (!sourceAudio.paused && !sourceAudio.ended) playheadFrame = requestAnimationFrame(frame);
  };
  playheadFrame = requestAnimationFrame(frame);
}

function correctPreviewDrift(force = false) {
  const masterTime = sourceAudio.currentTime || 0;
  for (const track of tracks.filter((item) => item.previewAudio !== sourceAudio)) {
    const audio = track.previewAudio;
    if (!audio) continue;
    if (force || Math.abs((audio.currentTime || 0) - masterTime) > .25) {
      try { audio.currentTime = Math.min(masterTime, Number.isFinite(audio.duration) ? audio.duration : masterTime); } catch { /* Metadata is pending. */ }
    }
    audio.playbackRate = sourceAudio.playbackRate;
    audio.volume = sourceAudio.volume;
  }
}

function applyMonitoring() {
  const hasSolo = tracks.some((track) => track.solo);
  for (const track of tracks) {
    const audible = hasSolo ? track.solo : !track.muted;
    if (track.previewAudio) track.previewAudio.muted = !audible;
    const row = byId("source").querySelector(`.processor-track[data-track-id="${track.id}"]`);
    row?.classList.toggle("is-muted", track.muted); row?.classList.toggle("is-solo", track.solo);
    row?.classList.toggle("is-solo-suppressed", !track.muted && !audible);
    const status = row?.querySelector(".track-monitor-status");
    if (status) status.textContent = track.muted ? "Mute · эта дорожка выключена" : track.solo ? "Solo · в прослушивании" : !audible ? "Не слышна: Solo другой дорожки" : "В прослушивании";
    const solo = byId("source").querySelector(`button[data-track-id="${track.id}"][data-track-action="solo"]`);
    const mute = byId("source").querySelector(`button[data-track-id="${track.id}"][data-track-action="mute"]`);
    solo?.setAttribute("aria-pressed", String(track.solo));
    mute?.setAttribute("aria-pressed", String(track.muted));
  }
}

function toggleMonitoring(id, action) {
  const track = trackById(id);
  if (!track || active) return;
  if (action === "solo") {
    track.solo = !track.solo;
    if (track.solo) track.muted = false;
  } else {
    track.muted = !track.muted;
    if (track.muted) track.solo = false;
  }
  applyMonitoring();
}

function clearPreviewAudios(clearMaster = true) {
  meters.clear();
  clearInterval(previewSyncTimer);
  previewSyncTimer = 0;
  for (const track of tracks) {
    if (track.previewAudio && track.previewAudio !== sourceAudio) clearAudio(track.previewAudio);
    track.previewAudio = null;
  }
  byId("preview-audios").replaceChildren();
  if (clearMaster) clearAudio(sourceAudio);
  delete sourceAudio.dataset.trackId;
}

function setupPreviewAudios(position = 0, resume = false) {
  clearPreviewAudios(true);
  if (!tracks.length) return;
  const master = tracks.reduce((longest, track) =>
    Number.isFinite(track.duration) && (!Number.isFinite(longest.duration) || track.duration > longest.duration) ? track : longest, tracks[0]);
  tracks.forEach((track) => {
    const audio = track === master ? sourceAudio : document.createElement("audio");
    audio.preload = "auto";
    audio.src = track.sourceURL;
    audio.dataset.trackId = String(track.id);
    if (track !== master) {
      audio.className = "processor-preview-audio";
      byId("preview-audios").append(audio);
    }
    track.previewAudio = audio;
    audio.load();
  });
  syncMeters();
  const restore = () => {
    seekSources(position);
    applyMonitoring();
    if (resume) void sourceAudio.play().catch(() => {});
  };
  if (sourceAudio.readyState >= 1) restore();
  else sourceAudio.addEventListener("loadedmetadata", restore, { once: true });
}

sourceAudio.addEventListener("play", () => {
  if (sourceFollowEnabled) followSourcePlayhead(sourceAudio.currentTime || 0);
  animatePlayhead();
  correctPreviewDrift(true);
  for (const track of tracks.filter((item) => item.previewAudio !== sourceAudio)) void track.previewAudio?.play().catch(() => {});
  clearInterval(previewSyncTimer);
  previewSyncTimer = window.setInterval(() => correctPreviewDrift(false), 500);
});
sourceAudio.addEventListener("pause", () => {
  cancelAnimationFrame(playheadFrame);
  clearInterval(previewSyncTimer);
  previewSyncTimer = 0;
  for (const track of tracks.filter((item) => item.previewAudio !== sourceAudio)) track.previewAudio?.pause();
  updatePlayheads();
});
sourceAudio.addEventListener("seeking", () => {
  correctPreviewDrift(true);
  if (sourceFollowEnabled) followSourcePlayhead(sourceAudio.currentTime || 0);
});
sourceAudio.addEventListener("volumechange", () => correctPreviewDrift(false));
for (const event of ["timeupdate", "seeked", "durationchange", "ended"]) sourceAudio.addEventListener(event, updatePlayheads);

function sourceZoomBounds() {
  const viewport = byId("file-info").querySelector(".processor-waveform-scroll");
  const durations = tracks.map((track) => track.duration).filter((duration) => Number.isFinite(duration) && duration > 0);
  sourceTimelineDuration = durations.length ? Math.max(...durations) : NaN;
  sourceZoomMaximum = durations.length ? 1000 : 2;
  sourceZoomMinimum = Number.isFinite(sourceTimelineDuration) && viewport ?
    Math.max(.01, Math.min(sourceZoomMaximum, viewport.clientWidth / sourceTimelineDuration)) : sourceZoomMaximum;
}

function updateSourceZoomRange() {
  const range = byId("source-zoom-range");
  const span = Math.log(sourceZoomMaximum / sourceZoomMinimum);
  sourceTimeZoomValue = span > 0 ? Math.round(Math.log(sourcePixelsPerSecond / sourceZoomMinimum) / span * 100) : 0;
  if (sourceScaleMode === "time") range.value = String(sourceTimeZoomValue);
  byId("source-scale-value").textContent = sourceScaleMode === "height" ? `${sourceTrackHeight} px` : `${sourcePixelsPerSecond.toFixed(sourcePixelsPerSecond < 10 ? 1 : 0)} px/s`;
  byId("source-zoom-out").disabled = Boolean(active) || sourcePixelsPerSecond <= sourceZoomMinimum + .001;
  byId("source-zoom-in").disabled = Boolean(active) || sourcePixelsPerSecond >= sourceZoomMaximum - .001;
}

function setSourceZoom(value, anchorTime, anchorOffset) {
  sourceZoomBounds();
  const centerTime = Number.isFinite(anchorTime) ? anchorTime : sourceFollowEnabled ?
    (sourceAudio.currentTime || 0) : sourceLeftVisibleTime + sourceViewportDuration / 2;
  sourcePixelsPerSecond = Math.max(sourceZoomMinimum, Math.min(sourceZoomMaximum, value));
  sourceZoomInitialized = true;
  for (const track of tracks) {
    const control = byId("source").querySelector(`.processor-waveform[data-track-id="${track.id}"]`);
    if (control) {
      control.style.width = `${sourceDisplayWidth(track)}px`;
    }
  }
  updateSourceNavigation();
  if (Number.isFinite(anchorOffset)) setSourceLeftVisibleTime(centerTime - anchorOffset / sourcePixelsPerSecond);
  else if (sourceFollowEnabled) followSourcePlayhead(sourceAudio.currentTime || 0);
  else setSourceLeftVisibleTime(centerTime - sourceViewportDuration / 2);
  updateSourceZoomRange();
  updatePlayheads();
}

function setProcessorZoomAt(value, anchorTime, anchorOffset) {
  disengageSourceFollow();
  setSourceZoom(value, anchorTime, anchorOffset);
}

function applyProcessorTrackHeight() {
  const workspace = document.getElementById("announcement-processor-card");
  workspace.style.setProperty("--track-height", `${sourceTrackHeight}px`);
  workspace.classList.toggle("has-compact-tracks", sourceTrackHeight < 200);
  byId("source-scale-value").textContent = sourceScaleMode === "height" ? `${sourceTrackHeight} px` : `${sourcePixelsPerSecond.toFixed(sourcePixelsPerSecond < 10 ? 1 : 0)} px/s`;
  redrawSourceDetails();
}

function setProcessorScaleMode(mode) {
  const range = byId("source-zoom-range");
  if (mode === sourceScaleMode) return;
  if (sourceScaleMode === "time") sourceTimeZoomValue = Number(range.value); else sourceTrackHeight = Number(range.value);
  sourceScaleMode = mode; const height = mode === "height";
  byId("source-scale-mode").setAttribute("aria-pressed", String(height));
  byId("source-scale-mode").setAttribute("aria-label", height ? "Переключить на масштаб времени" : "Переключить на высоту дорожек");
  byId("source-scale-mode").querySelector("span").textContent = height ? "Высота" : "Время";
  if (height) { range.min = "148"; range.max = "300"; range.step = "4"; range.value = String(sourceTrackHeight); applyProcessorTrackHeight(); }
  else { range.min = "0"; range.max = "100"; range.step = "1"; range.value = String(sourceTimeZoomValue); const ratio = sourceTimeZoomValue / 100; sourceZoomBounds(); setSourceZoom(sourceZoomMinimum * (sourceZoomMaximum / sourceZoomMinimum) ** ratio); }
}

function initializeSourceZoom() {
  sourceZoomBounds();
  setSourceZoom(Math.max(sourceZoomMinimum, Math.min(sourceZoomMaximum, 2)), 0);
}

byId("source-zoom-range").addEventListener("input", (event) => {
  if (sourceScaleMode === "height") { sourceTrackHeight = Number(event.currentTarget.value); applyProcessorTrackHeight(); return; }
  sourceZoomBounds();
  const ratio = Number(event.currentTarget.value) / 100;
  setSourceZoom(sourceZoomMinimum * (sourceZoomMaximum / sourceZoomMinimum) ** ratio);
});
byId("source-scale-mode").addEventListener("click", () => setProcessorScaleMode(sourceScaleMode === "time" ? "height" : "time"));
byId("source-zoom-out").addEventListener("click", () => setSourceZoom(sourcePixelsPerSecond / 1.5));
byId("source-zoom-in").addEventListener("click", () => setSourceZoom(sourcePixelsPerSecond * 1.5));
byId("source-zoom-fit").addEventListener("click", () => {
  sourceZoomBounds();
  setSourceZoom(sourceZoomMinimum, 0);
});
byId("source-follow").addEventListener("click", () => setSourceFollow(!sourceFollowEnabled));

const sourceScrollbar = byId("source-scrollbar");
const sourceScrollbarThumb = byId("source-scrollbar-thumb");
let sourceScrollbarDrag = null;

function setSourceFromScrollbarPosition(position) {
  const { thumbWidth, maxLeft, travel } = sourceScrollbarGeometry();
  const fraction = travel > 0 ? Math.max(0, Math.min(1, position / travel)) : 0;
  setSourceLeftVisibleTime(fraction * maxLeft);
}

sourceScrollbar.addEventListener("pointerdown", (event) => {
  if (event.button !== 0) return;
  const rect = sourceScrollbar.getBoundingClientRect();
  disengageSourceFollow();
  if (event.target === sourceScrollbarThumb) {
    const { thumbWidth, travel } = sourceScrollbarGeometry();
    const currentPosition = maximumSourceLeftTime() > 0 ? sourceLeftVisibleTime / maximumSourceLeftTime() * travel : 0;
    sourceScrollbarDrag = { pointerId: event.pointerId, grabOffset: Math.max(0, Math.min(thumbWidth, event.clientX - rect.left - currentPosition)) };
    sourceScrollbar.setPointerCapture(event.pointerId);
    sourceScrollbarThumb.classList.add("is-dragging");
    event.preventDefault();
    return;
  }
  const { thumbWidth } = sourceScrollbarGeometry();
  setSourceFromScrollbarPosition(event.clientX - rect.left - thumbWidth / 2);
});

sourceScrollbar.addEventListener("pointermove", (event) => {
  if (!sourceScrollbarDrag || sourceScrollbarDrag.pointerId !== event.pointerId) return;
  const rect = sourceScrollbar.getBoundingClientRect();
  setSourceFromScrollbarPosition(event.clientX - rect.left - sourceScrollbarDrag.grabOffset);
  event.preventDefault();
});

function finishSourceScrollbarDrag(event) {
  if (!sourceScrollbarDrag || sourceScrollbarDrag.pointerId !== event.pointerId) return;
  if (sourceScrollbar.hasPointerCapture(event.pointerId)) sourceScrollbar.releasePointerCapture(event.pointerId);
  sourceScrollbarDrag = null;
  sourceScrollbarThumb.classList.remove("is-dragging");
}

sourceScrollbar.addEventListener("pointerup", finishSourceScrollbarDrag);
sourceScrollbar.addEventListener("pointercancel", finishSourceScrollbarDrag);
sourceScrollbar.addEventListener("keydown", (event) => {
  if (!["ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"].includes(event.key)) return;
  event.preventDefault();
  disengageSourceFollow();
  const smallStep = Math.max(1, sourceViewportDuration / 10);
  const pageStep = Math.max(smallStep, sourceViewportDuration * .9);
  const target = event.key === "Home" ? 0 : event.key === "End" ? maximumSourceLeftTime() :
    sourceLeftVisibleTime + (event.key === "ArrowLeft" ? -smallStep : event.key === "ArrowRight" ? smallStep : event.key === "PageUp" ? -pageStep : pageStep);
  setSourceLeftVisibleTime(target);
});

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
  sourceDetail.clear();
  if (track.sourceURL) URL.revokeObjectURL(track.sourceURL);
  track.sourceURL = null;
  track.samples = null;
}

function clearTracks(resetInput = true) {
  sourceSelection = null; sourceSelectionEpoch++;
  cancelAnimationFrame(playheadFrame);
  clearPreviewAudios(true);
  for (const track of tracks) revokeTrackURLs(track);
  tracks = [];
  selectedFiles = [];
  selectedProvenance = [];
  provenanceContext = null;
  sourceTimelineDuration = NaN;
  sourceLeftVisibleTime = 0;
  sourceViewportDuration = 0;
  sourceZoomInitialized = false;
  setSourceFollow(false);
  byId("file-info").replaceChildren();
  byId("source-navigation").hidden = true;
  updateSourceScrollbar();
  byId("selection-summary").textContent = "";
  byId("source-time").textContent = "0:00 / 0:00";
  byId("source").hidden = true;
  if (resetInput) input.value = "";
  notifyProcessorSelection();
}

function removeTrack(id) {
  if (active) return;
  const index = tracks.findIndex((track) => track.id === Number(id));
  if (index < 0) return;
  clearResult();
  const removed = tracks[index];
  const position = sourceAudio.currentTime;
  const resume = !sourceAudio.paused && !sourceAudio.ended;
  clearPreviewAudios(true);
  tracks.splice(index, 1);
  revokeTrackURLs(removed);
  selectedFiles = tracks.map((track) => track.file);
  syncSelectedProvenance();
  syncInputFiles();
  notifyProcessorSelection();
  if (!tracks.length) {
    clearTracks();
    status.textContent = "Выберите файлы и нажмите «Обработать».";
    setBusy(false);
    return;
  }
  renderTracks();
  setupPreviewAudios(position, resume);
  initializeSourceZoom();
  status.textContent = selectionStatus();
  setBusy(false);
}

function moveTrack(id, offset) {
  if (active) return;
  const index = tracks.findIndex((track) => track.id === Number(id));
  const destination = index + offset;
  if (index < 0 || destination < 0 || destination >= tracks.length) return;
  clearResult();
  const position = sourceAudio.currentTime;
  const resume = !sourceAudio.paused && !sourceAudio.ended;
  clearPreviewAudios(true);
  const [track] = tracks.splice(index, 1);
  tracks.splice(destination, 0, track);
  selectedFiles = tracks.map((item) => item.file);
  syncSelectedProvenance();
  syncInputFiles();
  notifyProcessorSelection();
  renderTracks();
  setupPreviewAudios(position, resume);
  initializeSourceZoom();
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
  track.loading = true;
  track.waveformFailed = false;
  renderTracks();
  try {
    try { track.duration = await readTrackDuration(track, operation); } catch { /* Native playback may still be usable. */ }
    track.waveformWidth = waveformWidth(track.duration);
    renderTracks();
    const reader = createWaveformReader(undefined, currentEngine);
    try { track.samples = await operation.wait(reader.read(track.file, track.duration)); }
    finally { reader.dispose(); }
    track.waveformWidth = track.samples.length;
  } catch (failure) {
    if (active !== operation) throw failure;
    track.waveformFailed = true;
  } finally {
    track.loading = false;
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
      for (const track of candidates.filter((item) => !item.samples)) {
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
      const longest = tracks.reduce((candidate, track) =>
        Number.isFinite(track.duration) && (!Number.isFinite(candidate.duration) || track.duration > candidate.duration) ? track : candidate, tracks[0]);
      if (longest && Number(sourceAudio.dataset.trackId) !== longest.id) {
        setupPreviewAudios(sourceAudio.currentTime, !sourceAudio.paused && !sourceAudio.ended);
      }
      initializeSourceZoom();
      if (!sourceSelection && sourceTimelineDuration > 0) updateSourceSelection({ startSeconds: 0, endSeconds: sourceTimelineDuration });
    }
  }
}

function selectProcessorFiles(candidates, provenance = [], context = null) {
  if (active) return;
  clearResult();
  clearTracks(false);
  const files = Array.from(candidates || []);
  const error = validateFiles(files);
  status.textContent = error || "Выберите файлы и нажмите «Обработать».";
  if (files.length && !error && supported) {
    tracks = files.map((file, index) => ({
      id: nextTrackId++, file, sourceURL: URL.createObjectURL(file), samples: null,
      waveformWidth: WAVEFORM_MIN_WIDTH, waveformFailed: false, loading: false, duration: NaN, ordinal: 0,
      solo: false, muted: false, previewAudio: null, color: defaultTrackColor(index), provenance: provenance[index] ? structuredClone(provenance[index]) : null
    }));
    selectedFiles = files;
    syncSelectedProvenance();
    provenanceContext = context ? structuredClone(context) : null;
    byId("source").hidden = false;
    renderTracks();
    setupPreviewAudios(0, false);
    void generateWaveforms();
  }
  notifyProcessorSelection();
  if (!active) setBusy(false);
}

let selectionGuard = async () => true;
export function setProcessorSelectionGuard(guard) { selectionGuard = guard; }
input.addEventListener("change", async () => {
  const files = [...input.files];
  if (await selectionGuard()) selectProcessorFiles(files); else syncInputFiles();
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

function resultDisplayWidth() {
  if (!Number.isFinite(resultDuration) || resultDuration <= 0) return resultWaveformWidth;
  return Math.max(1, Math.min(resultWaveformWidth, Math.ceil(resultDuration * resultPixelsPerSecond)));
}

function resultZoomBounds() {
  const viewport = byId("result-waveform-scroll");
  resultZoomMaximum = Number.isFinite(resultDuration) && resultDuration > 0 ? resultWaveformWidth / resultDuration : 2;
  resultZoomMinimum = Number.isFinite(resultDuration) && resultDuration > 0 ?
    Math.min(resultZoomMaximum, viewport.clientWidth / resultDuration) : resultZoomMaximum;
}

function updateResultZoomRange() {
  const span = resultZoomMaximum - resultZoomMinimum;
  byId("result-zoom-range").value = String(span > 0 ?
    Math.round((resultPixelsPerSecond - resultZoomMinimum) / span * 100) : 0);
  byId("result-zoom-out").disabled = Boolean(active) || resultPixelsPerSecond <= resultZoomMinimum + .001;
  byId("result-zoom-in").disabled = Boolean(active) || resultPixelsPerSecond >= resultZoomMaximum - .001;
}

function setResultZoom(value, anchorTime) {
  if (!resultWaveformSamples) return;
  const viewport = byId("result-waveform-scroll");
  resultZoomBounds();
  const centerTime = Number.isFinite(anchorTime) ? anchorTime :
    (viewport.scrollLeft + viewport.clientWidth / 2) / resultPixelsPerSecond;
  resultPixelsPerSecond = Math.max(resultZoomMinimum, Math.min(resultZoomMaximum, value));
  byId("result-waveform-control").style.width = `${resultDisplayWidth()}px`;
  viewport.scrollLeft = Math.max(0, centerTime * resultPixelsPerSecond - viewport.clientWidth / 2);
  updateResultZoomRange();
  updateResultPlayhead();
  redrawResultWave();
}

function redrawResultWave() {
  const scroll = byId("result-waveform-scroll"), canvas = byId("result-waveform-control").querySelector("canvas");
  if (canvas && resultWaveformSamples) drawWaveformViewport(canvas, resultWaveformSamples, resultDuration,
    resultPixelsPerSecond, scroll.scrollLeft, scroll.clientWidth, scroll.clientHeight || WAVEFORM_HEIGHT);
}

function updateResultPlayhead() {
  const current = Number.isFinite(resultAudio.currentTime) ? resultAudio.currentTime : 0;
  const control = byId("result-waveform-control");
  const playhead = control.querySelector(".processor-waveform-playhead");
  if (playhead) playhead.style.left = `${Math.min(control.offsetWidth, current * resultPixelsPerSecond)}px`;
  byId("result-time").textContent = `${clockDuration(current)} / ${clockDuration(resultDuration)}`;
}

function animateResultPlayhead() {
  cancelAnimationFrame(resultPlayheadFrame);
  const frame = () => {
    updateResultPlayhead();
    if (!resultAudio.paused && !resultAudio.ended) resultPlayheadFrame = requestAnimationFrame(frame);
  };
  resultPlayheadFrame = requestAnimationFrame(frame);
}

function seekResult(seconds) {
  if (!Number.isFinite(resultDuration)) return;
  resultAudio.currentTime = Math.max(0, Math.min(resultDuration, seconds));
  updateResultPlayhead();
}

const resultScroll = byId("result-waveform-scroll");
const resultControl = byId("result-waveform-control");
installPan(resultScroll);
resultScroll.addEventListener("scroll", redrawResultWave);
resultScroll.addEventListener("click", (event) => {
  if (Date.now() - Number(resultScroll.dataset.dragEnded || 0) < 150) return;
  const box = resultScroll.getBoundingClientRect();
  seekResult((resultScroll.scrollLeft + event.clientX - box.left) / resultPixelsPerSecond);
});
resultControl.addEventListener("keydown", (event) => {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const step = event.shiftKey ? 30 : 5;
  seekResult(event.key === "Home" ? 0 : event.key === "End" ? resultDuration :
    (resultAudio.currentTime || 0) + (event.key === "ArrowLeft" ? -step : step));
});
resultAudio.addEventListener("play", animateResultPlayhead);
for (const event of ["pause", "timeupdate", "seeked", "durationchange", "ended"]) resultAudio.addEventListener(event, updateResultPlayhead);
byId("result-zoom-range").addEventListener("input", (event) => {
  const ratio = Number(event.currentTarget.value) / 100;
  setResultZoom(resultZoomMinimum + (resultZoomMaximum - resultZoomMinimum) * ratio);
});
byId("result-zoom-out").addEventListener("click", () => setResultZoom(resultPixelsPerSecond / 1.5));
byId("result-zoom-in").addEventListener("click", () => setResultZoom(resultPixelsPerSecond * 1.5));
byId("result-zoom-fit").addEventListener("click", () => setResultZoom(resultZoomMinimum, 0));

async function buildResultWaveform(currentEngine, operation, duration) {
  const waveformStatus = byId("result-waveform-status");
  try {
    resultDuration = duration;
    resultWaveformWidth = waveformWidth(duration);
    const reader = createWaveformReader(undefined, currentEngine);
    try { resultWaveformSamples = await operation.wait(reader.read(resultWaveformFile, duration)); }
    finally { reader.dispose(); }
    const element = document.createElement("canvas");
    element.className = "processor-waveform-detail";
    const playhead = document.createElement("span");
    playhead.className = "processor-waveform-playhead";
    playhead.setAttribute("aria-hidden", "true");
    resultControl.replaceChildren(element, playhead);
    resultScroll.hidden = false;
    waveformStatus.hidden = true;
    resultZoomBounds();
    setResultZoom(Math.max(resultZoomMinimum, Math.min(resultZoomMaximum, 2)), 0);
  } catch (failure) {
    if (active !== operation) throw failure;
    resultScroll.hidden = true;
    waveformStatus.textContent = "Не удалось построить форму сигнала.";
    waveformStatus.hidden = false;
  }
}

async function presentResult({ blob, mediaType, filename, originalDuration, intervals, ranges, multiple, mode }, currentEngine, operation) {
  resultURL = URL.createObjectURL(blob);
  resultWaveformFile = new File([blob], "result.mp3", { type: "audio/mpeg" });
  resultAudio.src = resultURL;
  const processedDuration = await waitForMetadata(resultAudio, operation);
  result.hidden = false;
  await buildResultWaveform(currentEngine, operation, processedDuration);
  const removedDuration = Math.max(0, originalDuration - processedDuration);
  for (const [id, value] of [["original-duration", originalDuration], ["processed-duration", processedDuration],
    ["removed-duration", removedDuration], ["pause-count", intervals.length]]) {
    byId(id).textContent = id === "pause-count" ? String(value) : formatDuration(value);
    byId(id).dataset.value = String(value);
  }
  byId("mixed-count").hidden = !multiple;
  byId("mixed-count").textContent = multiple ? `Дорожек сведено: ${selectedFiles.length}` : "";
  byId("pause-label").textContent = multiple ? "Сокращено общих длинных пауз" : "Сокращено длинных пауз";
  download.href = resultURL;
  download.download = filename;
  download.textContent = mode === "passthrough" ? "Скачать исходный файл без изменений" : "Скачать MP3";
  resultCandidate = {
    blob, processorVersion: "s07-v1", sources: structuredClone(selectedProvenance),
    provenance: provenanceContext ? { ...structuredClone(provenanceContext), sources: structuredClone(selectedProvenance) } : null,
    processing: {
      mode, silenceThresholdDb: SILENCE_THRESHOLD_DB, minimumSilenceSeconds: MIN_SILENCE_SECONDS,
      retainedSilenceSeconds: TARGET_SILENCE_SECONDS, detectedIntervals: intervals.map((item) => [...item]),
      removalRanges: ranges.map((item) => [...item]), mix: multiple ? "amix=normalize=0" : null,
      limiter: multiple ? "alimiter=limit=0.95:level=0:latency=1" : null,
      codec: mode === "passthrough" ? null : { name: "libmp3lame", bitrate: OUTPUT_BITRATE }
    },
    result: {
      mediaType, presentationFilename: filename, sizeBytes: blob.size, sha256: await sha256Hex(new Uint8Array(await blob.arrayBuffer())),
      originalDurationSeconds: originalDuration, resultDurationSeconds: processedDuration,
      removedDurationSeconds: removedDuration, pauseCount: intervals.length
    }
  };
  notifyProcessorResult();
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
      const filename = files[0].name;
      await presentResult({ blob: files[0], mediaType: files[0].type || "audio/mpeg", filename,
        originalDuration: duration, intervals: [], ranges: [], multiple: false, mode: "passthrough" }, currentEngine, operation);
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
    const filename = `${files[0].name.replace(/\.[^.]+$/, "")}${multiple ? "-mixed" : ""}-edited.mp3`;
    await presentResult({ blob: new Blob([output], { type: "audio/mpeg" }), mediaType: "audio/mpeg", filename,
      originalDuration: duration, intervals, ranges, multiple, mode: multiple ? "mixed_multi" : "processed_single" }, currentEngine, operation);
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
  clearPreviewAudios(true);
  for (const track of tracks) revokeTrackURLs(track);
});
window.addEventListener("pageshow", (event) => {
  if (event.persisted && tracks.length) {
    for (const track of tracks) {
      track.sourceURL = URL.createObjectURL(track.file);
      track.samples = null;
      track.waveformFailed = false;
      track.previewAudio = null;
    }
    renderTracks();
    setupPreviewAudios(0, false);
    void generateWaveforms();
  }
});
window.addEventListener("resize", () => {
  if (tracks.length && sourceZoomInitialized) setSourceZoom(sourcePixelsPerSecond);
  if (resultWaveformSamples) setResultZoom(resultPixelsPerSecond);
});
const processorWorkspace = document.getElementById("announcement-processor-card");
installSpaceTransport({ workspace: processorWorkspace, sourceAudio, resultAudio, sourceButton: byId("source-audio-play"), canHandle: () => !active && tracks.length > 0 && tracks.every(track => Number.isFinite(track.duration)) });
installEditorExpansion({ workspace: processorWorkspace, button: byId("expand"),
  captureAnchor: () => sourceLeftVisibleTime + sourceViewportDuration / 2,
  onGeometryChange: anchor => { if (tracks.length && sourceZoomInitialized) setSourceZoom(sourcePixelsPerSecond, anchor); if (resultWaveformSamples) setResultZoom(resultPixelsPerSecond); },
  isGestureActive: () => Boolean(processorLoopDrag || sourceScrollbarDrag) });
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (tracks.length && sourceZoomInitialized) setSourceZoom(sourcePixelsPerSecond);
  if (resultWaveformSamples) setResultZoom(resultPixelsPerSecond);
});
status.textContent = supported ? "Выберите файлы и нажмите «Обработать»." : UNSUPPORTED;
setBusy(false);
byId("heading").dataset.ready = "true";
