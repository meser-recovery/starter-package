import { sha256Hex } from "./audio-archive-client.mjs";
import {
  SpeakerHistory, buildLevelingAnalysisFilter, buildSpeakerCandidate, buildSpeakerFilterGraph,
  createSpeakerRenderSnapshot, defaultSpeakerPayload, microseconds, normalizeSpeakerPayload, parseLoudnormMeasurements,
  rebindSpeakerCandidate, removedDuration, resultDuration, SPEAKER_PAYLOAD_SCHEMA
} from "./speaker-editor-core.mjs";

const byId = (id) => document.getElementById(`speaker-editor-${id}`);
const workspace = document.getElementById("speaker-editor");
const encoder = new TextEncoder();
const state = {
  session: null, filesById: new Map(), tracks: [], payload: null, history: null, draft: null, savedFingerprint: "",
  originalDuration: NaN, saveDraft: null, onSaved: null, candidate: null, candidateUrl: null, engine: null,
  operation: null, saveLocked: false, ready: false, sourceEpoch: 0, presentationEpoch: 0, monitorTimer: null,
  pixelsPerSecond: 2, follow: false, scrollLock: false, resultDuration: NaN, resultPixelsPerSecond: 2
};

const fingerprint = (value) => JSON.stringify(value);
const editorBusy = () => Boolean(state.operation) || state.saveLocked;
const clock = (seconds) => {
  if (!Number.isFinite(seconds)) return "—";
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600); const minutes = Math.floor(total % 3600 / 60); const rest = String(total % 60).padStart(2, "0");
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${rest}` : `${minutes}:${rest}`;
};
const durationText = (seconds) => `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 3 }).format(seconds)} с`;
const bytesText = (bytes) => bytes < 1024 * 1024 ? `${Math.round(bytes / 1024)} КБ` : `${(bytes / 1024 / 1024).toFixed(1)} МБ`;

function userMessage(error, fallback) {
  if (error?.name === "AbortError" || error?.message === "cancelled") return "Сборка отменена. Черновик и исходники сохранены в памяти.";
  if (error?.status === 409) return "Черновик или запись изменились в другом окне. Закройте работу, откройте её снова и повторите изменения.";
  if (error?.status === 413) return "Черновик превышает безопасный предел размера.";
  return error instanceof Error && /^(Не удалось|Длительность|Верните|Черновик|Состав|Регион)/.test(error.message) ? error.message : fallback;
}

function currentDirty() {
  return Boolean(state.payload && fingerprint(state.payload) !== state.savedFingerprint);
}

export function speakerEditorHasUnsavedChanges() { return currentDirty(); }
export function speakerEditorSessionId() { return state.session?.id || null; }
export function getSpeakerCandidate() {
  return state.candidate ? { ...structuredClone({ ...state.candidate, blob: null }), blob: state.candidate.blob } : null;
}
export function getSpeakerSaveState() {
  return {
    session: state.session ? structuredClone(state.session) : null,
    draft: state.draft ? structuredClone(state.draft) : null,
    payload: state.payload ? structuredClone(state.payload) : null,
    candidate: getSpeakerCandidate(),
    ready: state.ready,
    saving: state.saveLocked
  };
}
export function setSpeakerSaveLocked(locked) {
  state.saveLocked = Boolean(locked);
  render();
}
export function updateSpeakerSession(session) {
  if (state.session?.id !== session?.id) return;
  state.session = structuredClone(session);
  render();
}

function notifyState() {
  window.dispatchEvent(new CustomEvent("speaker-editor-state", { detail: getSpeakerSaveState() }));
}

function setSelection(start, end, trackId = null) {
  byId("selection-start").value = Number.isFinite(start) ? String(microseconds(start)) : "";
  byId("selection-end").value = Number.isFinite(end) ? String(microseconds(end)) : "";
  if (trackId) byId("selection-track").value = trackId;
  updateSelectionDuration();
}

function readSelection() {
  const start = Number(byId("selection-start").value); const end = Number(byId("selection-end").value);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start || end > state.originalDuration) {
    throw new Error("Выделение должно иметь положительную длительность и находиться внутри исходной шкалы.");
  }
  return { startSeconds: microseconds(start), endSeconds: microseconds(end) };
}

function updateSelectionDuration() {
  const start = Number(byId("selection-start").value); const end = Number(byId("selection-end").value);
  byId("selection-duration").textContent = Number.isFinite(start) && Number.isFinite(end) && end > start ? (end - start).toFixed(6) : "0.000000";
  byId("selection-error").textContent = "";
}

function clearCandidate() {
  state.presentationEpoch += 1;
  state.candidate = null;
  byId("result").hidden = true;
  byId("result-audio").pause(); byId("result-audio").removeAttribute("src"); byId("result-audio").load();
  byId("download").removeAttribute("href"); byId("download").removeAttribute("download");
  if (state.candidateUrl) URL.revokeObjectURL(state.candidateUrl);
  state.candidateUrl = null;
}

function commitPayload(next, action) {
  if (!state.ready || editorBusy()) {
    byId("selection-error").textContent = editorBusy() ? "Дождитесь окончания текущей операции или отмените её." : "Исходники ещё не готовы для редактирования.";
    return;
  }
  try {
    const normalized = normalizeSpeakerPayload(next, state.session.sourceTracks.map((track) => track.trackId), state.originalDuration);
    if (fingerprint(normalized) === fingerprint(state.payload)) return;
    state.payload = state.history.commit(normalized);
    clearCandidate();
    byId("status").textContent = `Изменение применено: ${action}. Черновик не сохранён.`;
    render();
  } catch (error) { byId("selection-error").textContent = userMessage(error, "Изменение не применено."); }
}

function undo() {
  if (!state.ready || editorBusy() || !state.history?.canUndo) return;
  state.payload = state.history.undo(); clearCandidate(); byId("status").textContent = "Последнее изменение отменено."; render();
}

function redo() {
  if (!state.ready || editorBusy() || !state.history?.canRedo) return;
  state.payload = state.history.redo(); clearCandidate(); byId("status").textContent = "Изменение повторено."; render();
}

function updateHistoryControls() {
  byId("undo").disabled = !state.history?.canUndo || editorBusy();
  byId("redo").disabled = !state.history?.canRedo || editorBusy();
}

function processingLabel(setting) {
  const enhancement = setting.enhancement === "gentle" ? "улучшение: мягкое" : "улучшение: выкл.";
  const leveling = setting.leveling === "on" ? "выравнивание: вкл." : "выравнивание: выкл.";
  const compression = ({ off: "выкл.", light: "лёгкая", medium: "средняя", strong: "сильная" })[setting.compression];
  return `${enhancement}; ${leveling}; компрессия: ${compression}`;
}

function monitorAudible(track) {
  const solo = state.tracks.some((item) => item.solo);
  return solo ? track.solo : !track.mute;
}

function applyMonitoring() {
  for (const track of state.tracks) {
    if (track.audio) track.audio.muted = !monitorAudible(track);
    workspace.querySelector(`[data-track-id="${track.trackId}"][data-action="solo"]`)?.setAttribute("aria-pressed", String(track.solo));
    workspace.querySelector(`[data-track-id="${track.trackId}"][data-action="mute"]`)?.setAttribute("aria-pressed", String(track.mute));
  }
}

function toggleMonitoring(trackId, kind) {
  const track = state.tracks.find((item) => item.trackId === trackId); if (!track) return;
  track[kind] = !track[kind];
  if (kind === "solo" && track.solo) track.mute = false;
  if (kind === "mute" && track.mute) track.solo = false;
  applyMonitoring();
}

function moveTrack(trackId, offset) {
  const index = state.payload.trackIds.indexOf(trackId); const target = index + offset;
  if (index < 0 || target < 0 || target >= state.payload.trackIds.length) return;
  const next = structuredClone(state.payload); const [id] = next.trackIds.splice(index, 1); next.trackIds.splice(target, 0, id);
  next.excludedTrackIds = next.trackIds.filter((item) => next.excludedTrackIds.includes(item));
  next.trackProcessing.sort((left, right) => next.trackIds.indexOf(left.trackId) - next.trackIds.indexOf(right.trackId));
  commitPayload(next, "порядок дорожек");
}

function changeTrack(trackId, field, value) {
  const next = structuredClone(state.payload);
  if (field === "excluded") {
    next.excludedTrackIds = value ? [...next.excludedTrackIds, trackId] : next.excludedTrackIds.filter((id) => id !== trackId);
  } else next.trackProcessing.find((item) => item.trackId === trackId)[field] = value;
  commitPayload(next, field === "excluded" ? "состав микса" : "обработка дорожки");
}

function element(tag, className = "", text = "") {
  const node = document.createElement(tag); if (className) node.className = className; if (text) node.textContent = text; return node;
}

function makeButton(text, action, trackId, disabled = false) {
  const button = element("button", "", text); button.type = "button"; button.disabled = disabled;
  if (trackId) button.dataset.trackId = trackId; button.addEventListener("click", action); return button;
}

function drawCanvas(canvas, track, timelineDuration = state.originalDuration) {
  const width = 1400; const height = 100; canvas.width = width; canvas.height = height;
  const context = canvas.getContext("2d"); context.fillStyle = "#13293d"; context.fillRect(0, 0, width, height);
  context.strokeStyle = "#74b2e6"; context.lineWidth = 1; context.beginPath();
  const samples = track.samples || new Float32Array(width);
  const usedWidth = Math.max(1, Math.round(width * Math.min(1, track.duration / timelineDuration)));
  canvas.dataset.usedWidth = String(usedWidth); canvas.dataset.timelineDuration = String(timelineDuration);
  for (let x = 0; x < usedWidth; x++) {
    const sample = samples[Math.min(samples.length - 1, Math.floor(x / usedWidth * samples.length))] || 0;
    context.moveTo(x, height / 2 - sample * height * .46); context.lineTo(x, height / 2 + sample * height * .46);
  }
  context.stroke();
}

function waveform(track) {
  const scroll = element("div", "speaker-waveform-scroll"); scroll.dataset.trackId = track.trackId;
  const control = element("button", "speaker-waveform"); control.type = "button"; control.dataset.trackId = track.trackId;
  control.setAttribute("aria-label", `Форма сигнала ${track.file.name}. Стрелки перемещают позицию; выделение можно точно задать выше.`);
  const canvas = document.createElement("canvas"); canvas.height = 100; drawCanvas(canvas, track); control.append(canvas);
  for (const cut of state.payload.globalCuts) {
    const overlay = element("span", "speaker-region-overlay speaker-region-overlay--cut");
    overlay.style.left = `${cut.startSeconds / state.originalDuration * 100}%`; overlay.style.width = `${(cut.endSeconds - cut.startSeconds) / state.originalDuration * 100}%`;
    overlay.title = `Глобальный вырез ${cut.startSeconds.toFixed(6)}–${cut.endSeconds.toFixed(6)} с`; control.append(overlay);
  }
  for (const region of state.payload.trackSilenceRegions.filter((item) => item.trackId === track.trackId)) {
    const overlay = element("span", "speaker-region-overlay speaker-region-overlay--silence");
    overlay.style.left = `${region.startSeconds / state.originalDuration * 100}%`; overlay.style.width = `${(region.endSeconds - region.startSeconds) / state.originalDuration * 100}%`;
    overlay.title = `Тишина ${region.startSeconds.toFixed(6)}–${region.endSeconds.toFixed(6)} с`; control.append(overlay);
  }
  const playhead = element("span", "speaker-playhead"); playhead.setAttribute("aria-hidden", "true"); control.append(playhead);
  let pointerStart = null;
  control.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return; pointerStart = pointerTime(event, scroll); control.setPointerCapture(event.pointerId);
  });
  control.addEventListener("pointerup", (event) => {
    if (pointerStart === null) return; const end = pointerTime(event, scroll); setSelection(Math.min(pointerStart, end), Math.max(pointerStart, end), track.trackId);
    pointerStart = null; control.releasePointerCapture(event.pointerId);
  });
  control.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return; event.preventDefault();
    const current = byId("source-audio").currentTime || 0; const step = event.shiftKey ? 30 : 5;
    seekSource(event.key === "Home" ? 0 : event.key === "End" ? state.originalDuration : current + (event.key === "ArrowLeft" ? -step : step));
  });
  scroll.addEventListener("scroll", () => syncScroll(scroll), { passive: true }); scroll.append(control); return scroll;
}

function pointerTime(event, scroll) {
  const box = scroll.getBoundingClientRect(); return microseconds(Math.max(0, Math.min(state.originalDuration,
    (scroll.scrollLeft + event.clientX - box.left) / state.pixelsPerSecond)));
}

function selectControl(label, value, values, change) {
  const wrapper = element("label", "speaker-dsp-field", label); const select = document.createElement("select");
  for (const [key, text] of values) { const option = document.createElement("option"); option.value = key; option.textContent = text; select.append(option); }
  select.value = value; select.disabled = editorBusy() || !state.ready;
  select.addEventListener("change", () => change(select.value)); wrapper.append(select); return wrapper;
}

function renderTracks() {
  const list = byId("tracks"); list.replaceChildren();
  const excluded = new Set(state.payload.excludedTrackIds);
  state.payload.trackIds.forEach((trackId, index) => {
    const track = state.tracks.find((item) => item.trackId === trackId); const setting = state.payload.trackProcessing.find((item) => item.trackId === trackId);
    const item = element("li", `speaker-track${excluded.has(trackId) ? " is-excluded" : ""}`); item.dataset.trackId = trackId;
    const header = element("div", "speaker-track__header"); const heading = element("div", "speaker-track__identity");
    heading.append(element("span", "speaker-track__number", `Дорожка ${index + 1}`), element("h4", "", track.file.name),
      element("span", "", `${durationText(track.duration)} · ${excluded.has(trackId) ? "исключена из финального микса" : "в финальном миксе"}`));
    const monitor = element("div", "speaker-track__buttons");
    const solo = makeButton("Соло", () => toggleMonitoring(trackId, "solo"), trackId); solo.dataset.action = "solo"; solo.setAttribute("aria-pressed", String(track.solo));
    const mute = makeButton("Заглушить", () => toggleMonitoring(trackId, "mute"), trackId); mute.dataset.action = "mute"; mute.setAttribute("aria-pressed", String(track.mute));
    const editsDisabled = editorBusy() || !state.ready;
    const include = makeButton(excluded.has(trackId) ? "Вернуть в микс" : "Исключить из микса", () => changeTrack(trackId, "excluded", !excluded.has(trackId)), trackId, editsDisabled);
    const up = makeButton("Вверх", () => moveTrack(trackId, -1), trackId, editsDisabled || index === 0);
    const down = makeButton("Вниз", () => moveTrack(trackId, 1), trackId, editsDisabled || index === state.payload.trackIds.length - 1);
    monitor.append(solo, mute, include, up, down); header.append(heading, monitor);
    const dsp = element("div", "speaker-dsp");
    dsp.append(selectControl("Улучшение", setting.enhancement, [["off", "Выкл."], ["gentle", "Мягкое"]], (value) => changeTrack(trackId, "enhancement", value)),
      selectControl("Выравнивание", setting.leveling, [["off", "Выкл."], ["on", "Вкл."]], (value) => changeTrack(trackId, "leveling", value)),
      selectControl("Компрессия", setting.compression, [["off", "Выкл."], ["light", "Лёгкая"], ["medium", "Средняя"], ["strong", "Сильная"]], (value) => changeTrack(trackId, "compression", value)));
    const summary = element("p", "speaker-track__summary", processingLabel(setting));
    item.append(header, waveform(track), dsp, summary); list.append(item);
  });
  updateWaveWidths(); applyMonitoring();
}

function renderRegions() {
  const container = byId("regions"); container.replaceChildren();
  const regions = [...state.payload.globalCuts.map((region) => ({ ...region, kind: "cut" })),
    ...state.payload.trackSilenceRegions.map((region) => ({ ...region, kind: "silence" }))];
  if (!regions.length) { container.append(element("p", "", "Регионов пока нет.")); return; }
  for (const region of regions) {
    const row = element("article", `speaker-region-row speaker-region-row--${region.kind}`); row.dataset.regionId = region.regionId;
    const title = element("h4", "", region.kind === "cut" ? "Глобальный вырез" : `Тишина · ${state.tracks.find((track) => track.trackId === region.trackId)?.file.name}`);
    const fields = element("div", "speaker-region-row__fields");
    const editsDisabled = editorBusy() || !state.ready;
    const start = document.createElement("input"); start.type = "number"; start.step = "0.000001"; start.min = "0"; start.value = region.startSeconds; start.disabled = editsDisabled; start.setAttribute("aria-label", `${title.textContent}, начало в секундах`);
    const end = document.createElement("input"); end.type = "number"; end.step = "0.000001"; end.min = "0"; end.value = region.endSeconds; end.disabled = editsDisabled; end.setAttribute("aria-label", `${title.textContent}, конец в секундах`);
    const apply = makeButton("Применить границы", () => {
      const next = structuredClone(state.payload); const collection = region.kind === "cut" ? next.globalCuts : next.trackSilenceRegions;
      const target = collection.find((item) => item.regionId === region.regionId); target.startSeconds = Number(start.value); target.endSeconds = Number(end.value);
      commitPayload(next, "границы региона");
    }, null, editsDisabled);
    const select = makeButton("Выбрать", () => { setSelection(region.startSeconds, region.endSeconds, region.trackId); row.scrollIntoView({ block: "nearest" }); });
    const remove = makeButton("Удалить", () => {
      const next = structuredClone(state.payload); const key = region.kind === "cut" ? "globalCuts" : "trackSilenceRegions";
      next[key] = next[key].filter((item) => item.regionId !== region.regionId); commitPayload(next, "удаление региона");
    }, null, editsDisabled);
    fields.append(start, end, apply, select, remove); row.append(title, fields); container.append(row);
  }
}

function updateRenderState() {
  const allExcluded = Boolean(state.payload && state.payload.excludedTrackIds.length === state.payload.trackIds.length);
  const disabled = !state.ready || !state.session || !Number.isFinite(state.originalDuration) || allExcluded || editorBusy();
  byId("render").disabled = disabled;
  byId("render-reason").textContent = allExcluded ? "Все дорожки исключены. Верните хотя бы одну дорожку в микс." :
    state.saveLocked ? "Идёт сохранение в архив «Спикерская»." : state.operation ? "Идёт локальная сборка." : !state.ready ? "Сборка недоступна, пока исходники не прошли полную проверку." :
      "В результат войдут только дорожки, оставленные в финальном миксе.";
  byId("save").disabled = !state.ready || !state.session || editorBusy();
  byId("close").disabled = state.saveLocked;
  for (const id of ["selection-start", "selection-end", "selection-track", "add-cut", "add-silence"]) byId(id).disabled = !state.ready || editorBusy();
}

function render() {
  if (!state.session) return;
  if (state.payload) { renderTracks(); renderRegions(); }
  else { byId("tracks").replaceChildren(); byId("regions").replaceChildren(); }
  updateHistoryControls(); updateRenderState();
  byId("status").dataset.dirty = String(currentDirty());
  notifyState();
}

function addRegion(kind) {
  if (!state.ready || editorBusy()) return;
  try {
    const selection = readSelection(); const next = structuredClone(state.payload);
    if (kind === "cut") next.globalCuts.push({ regionId: crypto.randomUUID(), ...selection });
    else next.trackSilenceRegions.push({ regionId: crypto.randomUUID(), trackId: byId("selection-track").value, ...selection });
    commitPayload(next, kind === "cut" ? "глобальный вырез" : "тишина на одной дорожке");
  } catch (error) { byId("selection-error").textContent = userMessage(error, "Проверьте выделение."); }
}

function maximumScroll() {
  const first = byId("tracks").querySelector(".speaker-waveform-scroll"); return first ? Math.max(0, first.scrollWidth - first.clientWidth) : 0;
}

function updateScrollbar() {
  const rail = byId("source-scrollbar"); const thumb = rail.firstElementChild; const first = byId("tracks").querySelector(".speaker-waveform-scroll");
  if (!first) return; const fraction = Math.min(1, first.clientWidth / first.scrollWidth); const width = Math.max(36, rail.clientWidth * fraction);
  const max = maximumScroll(); const travel = Math.max(0, rail.clientWidth - width); thumb.style.width = `${width}px`; thumb.style.transform = `translateX(${max ? first.scrollLeft / max * travel : 0}px)`;
  rail.setAttribute("aria-valuemax", String(max)); rail.setAttribute("aria-valuenow", String(Math.round(first.scrollLeft)));
}

function syncScroll(origin) {
  if (state.scrollLock) return; state.scrollLock = true;
  for (const scroll of byId("tracks").querySelectorAll(".speaker-waveform-scroll")) if (scroll !== origin) scroll.scrollLeft = origin.scrollLeft;
  updateScrollbar(); requestAnimationFrame(() => { state.scrollLock = false; });
}

function updateWaveWidths() {
  const first = byId("tracks").querySelector(".speaker-waveform-scroll"); if (!first || !state.originalDuration) return;
  const base = first.clientWidth / state.originalDuration; state.pixelsPerSecond = Math.max(.01, base * Number(byId("zoom").value));
  const width = Math.max(first.clientWidth, Math.ceil(state.originalDuration * state.pixelsPerSecond));
  for (const control of byId("tracks").querySelectorAll(".speaker-waveform")) control.style.width = `${width}px`;
  updatePlayheads(); updateScrollbar();
}

function seekSource(seconds) {
  const target = Math.max(0, Math.min(state.originalDuration, seconds));
  for (const track of state.tracks) if (track.audio) { try { track.audio.currentTime = Math.min(target, track.duration); } catch { /* metadata settled asynchronously */ } }
  synchronizePlayback();
  updatePlayheads();
}

function updatePlayheads() {
  const time = byId("source-audio").currentTime || 0;
  for (const playhead of byId("tracks").querySelectorAll(".speaker-playhead")) playhead.style.left = `${time * state.pixelsPerSecond}px`;
  byId("source-time").textContent = `${clock(time)} / ${clock(state.originalDuration)} · исходная шкала`;
  if (state.follow && !byId("source-audio").paused) {
    const first = byId("tracks").querySelector(".speaker-waveform-scroll"); if (first) { first.scrollLeft = Math.max(0, time * state.pixelsPerSecond - first.clientWidth / 2); syncScroll(first); }
  }
}

function setupPlayback() {
  stopMonitoringSynchronization();
  const masterTrack = state.tracks.reduce((best, track) => track.duration > best.duration ? track : best, state.tracks[0]);
  const master = byId("source-audio"); const hidden = byId("preview-audios"); hidden.replaceChildren();
  for (const track of state.tracks) {
    const audio = track === masterTrack ? master : document.createElement("audio"); audio.src = track.url; audio.preload = "auto"; track.audio = audio;
    if (audio !== master) hidden.append(audio);
  }
  master.onplay = () => { synchronizePlayback(); scheduleMonitoringSynchronization(); };
  applyMonitoring();
}

function synchronizePlayback() {
  const master = byId("source-audio");
  for (const track of state.tracks) if (track.audio !== master) {
    const preview = track.audio; const target = Math.min(master.currentTime, track.duration);
    preview.playbackRate = master.playbackRate; preview.volume = master.volume;
    if (Math.abs(preview.currentTime - target) > .04) preview.currentTime = target;
    if (!master.paused && master.currentTime < track.duration) void preview.play().catch(() => {}); else preview.pause();
  }
}

function scheduleMonitoringSynchronization() {
  stopMonitoringSynchronization(false);
  if (byId("source-audio").paused || !state.ready) return;
  state.monitorTimer = setTimeout(() => {
    state.monitorTimer = null; synchronizePlayback(); scheduleMonitoringSynchronization();
  }, 200);
}

function stopMonitoringSynchronization(pausePreviews = false) {
  if (state.monitorTimer !== null) clearTimeout(state.monitorTimer);
  state.monitorTimer = null;
  if (pausePreviews) {
    const master = byId("source-audio");
    for (const track of state.tracks) if (track.audio !== master) track.audio?.pause();
  }
}

function stopOtherPlayback() { stopMonitoringSynchronization(true); }

async function metadataFor(url) {
  const audio = document.createElement("audio"); audio.preload = "metadata"; audio.src = url;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("Не удалось определить длительность исходной дорожки.")), 30000);
    audio.addEventListener("loadedmetadata", () => { clearTimeout(timer); Number.isFinite(audio.duration) && audio.duration > 0 ? resolve(audio.duration) : reject(new Error("Не удалось определить длительность исходной дорожки.")); }, { once: true });
    audio.addEventListener("error", () => { clearTimeout(timer); reject(new Error("Не удалось прочитать исходную дорожку.")); }, { once: true });
  });
}

async function waveformSamples(file) {
  const AudioContextClass = globalThis.AudioContext || globalThis.webkitAudioContext; if (!AudioContextClass) return null;
  const context = new AudioContextClass();
  try {
    const buffer = await context.decodeAudioData(await file.arrayBuffer()); const data = buffer.getChannelData(0); const result = new Float32Array(1400);
    const block = Math.max(1, Math.floor(data.length / result.length));
    for (let index = 0; index < result.length; index++) { let peak = 0; const end = Math.min(data.length, (index + 1) * block); for (let cursor = index * block; cursor < end; cursor++) peak = Math.max(peak, Math.abs(data[cursor])); result[index] = peak; }
    return result;
  } finally { await context.close(); }
}

async function prepareSources(epoch) {
  byId("status").textContent = "Проверка длительности и подготовка форм сигнала…";
  const tracks = [...state.tracks]; const session = state.session; const payload = state.payload; const draft = state.draft;
  const current = () => state.sourceEpoch === epoch && state.session === session;
  const durations = await Promise.all(tracks.map((track) => metadataFor(track.url)));
  if (!current()) throw new DOMException("cancelled", "AbortError");
  const originalDuration = Math.max(...durations);
  if (originalDuration - Math.min(...durations) > .5) throw new Error("Длительность дорожек различается больше чем на 0,5 секунды.");
  const normalized = normalizeSpeakerPayload(payload, session.sourceTracks.map((track) => track.trackId), originalDuration);
  const samples = await Promise.all(tracks.map((track) => waveformSamples(track.file)));
  if (!current()) throw new DOMException("cancelled", "AbortError");
  if (samples.some((item) => !item)) throw new Error("Не удалось подготовить формы сигнала исходных дорожек.");
  tracks.forEach((track, index) => { track.duration = durations[index]; track.samples = samples[index]; });
  state.originalDuration = originalDuration; state.payload = normalized; state.history.reset(normalized);
  state.savedFingerprint = draft ? fingerprint(normalized) : fingerprint(defaultSpeakerPayload(normalized.trackIds));
  setupPlayback(); state.ready = true; render();
  byId("status").textContent = draft ? `Черновик открыт, ревизия ${draft.draftRevision}.` : "Новый черновик готов. Все настройки выключены.";
}

function failSourcePreparation() {
  stopMonitoringSynchronization(true); clearCandidate();
  const master = byId("source-audio"); master.pause(); master.removeAttribute("src"); master.load();
  for (const track of state.tracks) { track.audio?.pause(); URL.revokeObjectURL(track.url); }
  byId("preview-audios").replaceChildren(); state.filesById = new Map(); state.tracks = []; state.payload = null; state.history = null;
  state.draft = null; state.savedFingerprint = ""; state.originalDuration = NaN; state.saveDraft = null; state.onSaved = null; state.ready = false;
  render();
}

async function saveDraft() {
  if (!state.ready || editorBusy() || !state.session || !state.saveDraft) return;
  byId("status").textContent = "Сохранение черновика обработки…"; byId("save").disabled = true;
  const before = fingerprint(state.payload);
  try {
    const result = await state.saveDraft({ schemaVersion: 1, expectedDraftRevision: state.draft?.draftRevision || 0,
      expectedSourceSessionRevision: state.session.revision, payloadSchema: SPEAKER_PAYLOAD_SCHEMA, payload: structuredClone(state.payload), idempotencyKey: crypto.randomUUID() });
    if (fingerprint(state.payload) !== before) throw new Error("Черновик изменился во время сохранения; повторите сохранение.");
    state.draft = result.draft; state.session = result.session; state.savedFingerprint = before;
    state.candidate = rebindSpeakerCandidate(state.candidate, state.payload, result.session.revision, result.draft.draftRevision);
    state.onSaved?.(result); byId("status").textContent = `Черновик сохранён, ревизия ${result.draft.draftRevision}.`;
  } catch (error) { byId("status").textContent = userMessage(error, "Не удалось сохранить черновик. Изменения и исходники остались в памяти."); }
  finally { updateRenderState(); notifyState(); }
}

function operation() {
  const controller = new AbortController(); state.operation = controller; return controller;
}

async function ensureEngine(controller) {
  if (state.engine?.loaded) return state.engine;
  const { FFmpeg } = await import("../vendor/ffmpeg/ffmpeg/index.js"); if (controller.signal.aborted) throw new DOMException("cancelled", "AbortError");
  const engine = new FFmpeg(); state.engine = engine;
  await engine.load({ coreURL: new URL("../vendor/ffmpeg/core/ffmpeg-core.js", import.meta.url).href,
    wasmURL: new URL("../vendor/ffmpeg/core/ffmpeg-core.wasm", import.meta.url).href });
  if (controller.signal.aborted) throw new DOMException("cancelled", "AbortError"); return engine;
}

function abortCheck(controller) { if (controller.signal.aborted || state.operation !== controller) throw new DOMException("cancelled", "AbortError"); }

async function resultMetadata(blob) {
  const url = URL.createObjectURL(blob); try { return await metadataFor(url); } finally { URL.revokeObjectURL(url); }
}

async function renderSpeaker() {
  if (!state.ready || editorBusy() || byId("render").disabled) return;
  let snapshot;
  try {
    snapshot = createSpeakerRenderSnapshot({ session: state.session, draftRevision: state.draft?.draftRevision || 0,
      payload: state.payload, originalDurationSeconds: state.originalDuration, tracks: state.tracks });
  } catch (error) {
    byId("render-status").textContent = userMessage(error, "Не удалось зафиксировать безопасное состояние для сборки."); return;
  }
  clearCandidate(); const controller = operation(); const inputPaths = snapshot.sources.map((_, index) => `speaker-input-${index}`);
  const outputPath = "speaker-output.mp3"; const filterPath = "speaker-filter.txt"; const measurements = {}; let logListener = null;
  byId("cancel").hidden = false; byId("progress").hidden = false; byId("progress").value = 2; byId("render-status").textContent = "Подготовка локального обработчика…"; render();
  try {
    const engine = await ensureEngine(controller); abortCheck(controller);
    for (let index = 0; index < snapshot.sources.length; index++) {
      const file = snapshot.sources[index].file; await engine.writeFile(inputPaths[index], new Uint8Array(await file.arrayBuffer())); abortCheck(controller);
      byId("progress").value = 10 + Math.round((index + 1) / snapshot.sources.length * 20);
    }
    const included = snapshot.payload.trackIds.filter((id) => !snapshot.payload.excludedTrackIds.includes(id));
    for (const trackId of included.filter((id) => snapshot.payload.trackProcessing.find((item) => item.trackId === id).leveling === "on")) {
      const logs = []; logListener = ({ message }) => logs.push(message); engine.on("log", logListener);
      byId("render-status").textContent = `Измерение громкости: дорожка ${snapshot.payload.trackIds.indexOf(trackId) + 1}…`;
      const graph = buildLevelingAnalysisFilter({ inputIndex: snapshot.payload.trackIds.indexOf(trackId), trackId,
        duration: snapshot.originalDurationSeconds, payload: snapshot.payload });
      const code = await engine.exec(["-hide_banner", "-nostats", "-xerror", ...inputPaths.flatMap((path) => ["-protocol_whitelist", "file", "-i", path]),
        "-filter_complex", graph, "-map", "[analysis]", "-f", "null", "-"]);
      engine.off("log", logListener); logListener = null; abortCheck(controller); if (code !== 0) throw new Error("Не удалось измерить громкость дорожки.");
      measurements[trackId] = parseLoudnormMeasurements(logs);
    }
    byId("progress").value = 55; byId("render-status").textContent = "Применение монтажа, обработки и финального лимитера…";
    const graph = buildSpeakerFilterGraph(snapshot.payload, snapshot.originalDurationSeconds, measurements); await engine.writeFile(filterPath, encoder.encode(graph));
    const code = await engine.exec(["-hide_banner", "-nostats", "-xerror", ...inputPaths.flatMap((path) => ["-protocol_whitelist", "file", "-i", path]),
      "-filter_complex_script", filterPath, "-map", "[speaker_mix]", "-vn", "-sn", "-dn", "-c:a", "libmp3lame", "-b:a", "128k", outputPath]);
    abortCheck(controller); if (code !== 0) throw new Error("Не удалось создать MP3. Проверьте исходники и повторите.");
    const bytes = await engine.readFile(outputPath); if (!bytes.byteLength) throw new Error("Не удалось создать MP3.");
    const blob = new Blob([bytes], { type: "audio/mpeg" }); const actualDuration = await resultMetadata(blob); abortCheck(controller);
    const candidate = await buildSpeakerCandidate({ blob, snapshot, measurements, resultDurationSeconds: actualDuration, sha256: sha256Hex }); abortCheck(controller);
    await presentCandidate(candidate, controller); abortCheck(controller);
    byId("progress").value = 100; byId("render-status").textContent = "Локальный MP3 готов. В архив ничего не передавалось.";
  } catch (error) {
    clearCandidate(); byId("render-status").textContent = userMessage(error, "Не удалось собрать результат. Черновик и исходники остались в памяти.");
  } finally {
    if (logListener) state.engine?.off("log", logListener);
    if (state.engine?.loaded) for (const path of [...inputPaths, filterPath, outputPath]) { try { await state.engine.deleteFile(path); } catch { /* fixed temporary path may be absent */ } }
    if (state.operation === controller) state.operation = null;
    byId("cancel").hidden = true; byId("progress").hidden = true; render();
  }
}

function cancelRender() {
  if (!state.operation) return; state.operation.abort(); state.engine?.terminate(); state.engine = null; clearCandidate();
  byId("render-status").textContent = "Сборка отменена. Черновик и исходники сохранены в памяти."; byId("cancel").hidden = true; byId("progress").hidden = true; render();
}

async function resultSamples(blob) { return waveformSamples(new File([blob], "result.mp3", { type: "audio/mpeg" })); }

async function presentCandidate(candidate, controller) {
  const epoch = state.presentationEpoch;
  const samples = await resultSamples(candidate.blob); abortCheck(controller);
  if (epoch !== state.presentationEpoch) throw new DOMException("cancelled", "AbortError");
  state.candidate = candidate;
  state.candidateUrl = URL.createObjectURL(candidate.blob); byId("result-audio").src = state.candidateUrl;
  byId("download").href = state.candidateUrl; byId("download").download = candidate.presentationFilename;
  byId("original-duration").textContent = durationText(candidate.originalDurationSeconds); byId("result-duration").textContent = durationText(candidate.resultDurationSeconds);
  byId("removed-duration").textContent = durationText(candidate.globallyRemovedDurationSeconds); byId("result-format").textContent = `MP3 · 128 кбит/с · ${bytesText(candidate.sizeBytes)}`;
  state.resultDuration = candidate.resultDurationSeconds; const canvas = byId("result-waveform").querySelector("canvas");
  drawCanvas(canvas, { samples, duration: state.resultDuration }, state.resultDuration);
  byId("result").hidden = false; updateResultWidth(); updateResultPlayhead();
}

function updateResultWidth() {
  if (!Number.isFinite(state.resultDuration)) return; const scroll = byId("result-waveform-scroll");
  state.resultPixelsPerSecond = scroll.clientWidth / state.resultDuration * Number(byId("result-zoom").value);
  byId("result-waveform").style.width = `${Math.max(scroll.clientWidth, state.resultDuration * state.resultPixelsPerSecond)}px`;
}

function updateResultPlayhead() {
  const current = byId("result-audio").currentTime || 0; byId("result-waveform").querySelector(".speaker-playhead").style.left = `${current * state.resultPixelsPerSecond}px`;
  byId("result-time").textContent = `${clock(current)} / ${clock(state.resultDuration)}`;
}

function teardown() {
  state.sourceEpoch += 1;
  cancelRender(); stopMonitoringSynchronization(true); clearCandidate(); byId("source-audio").pause(); byId("source-audio").removeAttribute("src"); byId("source-audio").load();
  for (const track of state.tracks) { track.audio?.pause(); URL.revokeObjectURL(track.url); }
  byId("preview-audios").replaceChildren(); state.session = null; state.filesById = new Map(); state.tracks = []; state.payload = null; state.history = null;
  state.draft = null; state.savedFingerprint = ""; state.originalDuration = NaN; state.saveDraft = null; state.onSaved = null; state.saveLocked = false; state.ready = false; workspace.hidden = true;
  document.getElementById("announcement-processor-card").hidden = false;
  notifyState();
}

export function closeSpeakerEditor(force = false) {
  if (!state.session) return true;
  if (state.saveLocked) {
    byId("status").textContent = "Сохранение в архив ещё выполняется. Сначала отмените или завершите передачу.";
    return false;
  }
  if (!force && currentDirty() && !globalThis.confirm("Закрыть работу и отбросить несохранённые изменения Спикерской?")) return false;
  teardown(); return true;
}

export async function openSpeakerEditor({ session, files, draft = null, saveDraft: save, onSaved }) {
  if (!closeSpeakerEditor(false)) return false;
  if (session.lifecycle.state !== "incoming" || session.sourceState !== "available") throw new Error("Спикерская доступна только для входящей записи с целыми исходниками.");
  if (draft && draft.payloadSchema !== SPEAKER_PAYLOAD_SCHEMA) throw new Error("Сохранённый черновик имеет неподдерживаемую схему и не будет перезаписан.");
  const orderedManifest = [...session.sourceTracks].sort((left, right) => left.ordinal - right.ordinal);
  if (files.length !== orderedManifest.length) throw new Error("Состав загруженных исходников не совпадает с записью.");
  const epoch = ++state.sourceEpoch;
  state.ready = false; state.saveLocked = false; state.session = structuredClone(session); state.filesById = new Map(orderedManifest.map((track, index) => [track.trackId, files[index]]));
  state.tracks = orderedManifest.map((track, index) => ({ trackId: track.trackId, manifest: track, file: files[index], url: URL.createObjectURL(files[index]), duration: NaN, samples: null, solo: false, mute: false, audio: null }));
  state.payload = draft ? structuredClone(draft.payload) : defaultSpeakerPayload(orderedManifest.map((track) => track.trackId));
  state.history = new SpeakerHistory(state.payload); state.draft = draft; state.saveDraft = save; state.onSaved = onSaved;
  document.getElementById("announcement-processor-card").hidden = true;
  workspace.hidden = false; byId("identity").textContent = `${session.title} · активная работа «Спикерская» · исходная шкала неизменна`;
  byId("technical").textContent = `Идентификатор записи: ${session.id}. Ревизия записи: ${session.revision}. Версия процессора: speaker-editor-v1.`;
  const select = byId("selection-track"); select.replaceChildren(); for (const track of orderedManifest) { const option = document.createElement("option"); option.value = track.trackId; option.textContent = track.originalName; select.append(option); }
  setSelection(0, ""); clearCandidate();
  updateRenderState();
  try { await prepareSources(epoch); workspace.scrollIntoView({ behavior: "smooth", block: "start" }); return true; }
  catch (error) {
    if (state.sourceEpoch !== epoch) return false;
    const message = userMessage(error, "Не удалось подготовить Спикерскую."); failSourcePreparation();
    byId("status").textContent = message; byId("render-status").textContent = "Сохранение и локальная сборка отключены до повторного открытия исправных исходников.";
    return false;
  }
}

byId("selection-start").addEventListener("input", updateSelectionDuration); byId("selection-end").addEventListener("input", updateSelectionDuration);
byId("add-cut").addEventListener("click", () => addRegion("cut")); byId("add-silence").addEventListener("click", () => addRegion("silence"));
byId("undo").addEventListener("click", undo); byId("redo").addEventListener("click", redo); byId("save").addEventListener("click", saveDraft);
byId("close").addEventListener("click", () => closeSpeakerEditor(false)); byId("render").addEventListener("click", renderSpeaker); byId("cancel").addEventListener("click", cancelRender);
byId("zoom").addEventListener("input", updateWaveWidths); byId("zoom-out").addEventListener("click", () => { byId("zoom").value = Math.max(1, Number(byId("zoom").value) - .5); updateWaveWidths(); });
byId("zoom-in").addEventListener("click", () => { byId("zoom").value = Math.min(8, Number(byId("zoom").value) + .5); updateWaveWidths(); }); byId("zoom-fit").addEventListener("click", () => { byId("zoom").value = 1; updateWaveWidths(); });
byId("follow").addEventListener("click", () => { state.follow = !state.follow; byId("follow").setAttribute("aria-pressed", String(state.follow)); });
byId("source-audio").addEventListener("pause", stopOtherPlayback);
byId("source-audio").addEventListener("ended", stopOtherPlayback);
for (const name of ["seeking", "seeked"]) byId("source-audio").addEventListener(name, synchronizePlayback);
for (const name of ["ratechange", "volumechange"]) byId("source-audio").addEventListener(name, synchronizePlayback);
for (const name of ["timeupdate", "seeked", "play", "ended"]) byId("source-audio").addEventListener(name, updatePlayheads);
byId("source-scrollbar").addEventListener("click", (event) => { const rail = byId("source-scrollbar"); const first = byId("tracks").querySelector(".speaker-waveform-scroll"); if (!first) return; first.scrollLeft = (event.clientX - rail.getBoundingClientRect().left) / rail.clientWidth * maximumScroll(); syncScroll(first); });
byId("source-scrollbar").addEventListener("keydown", (event) => { if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return; event.preventDefault(); const first = byId("tracks").querySelector(".speaker-waveform-scroll"); if (!first) return; first.scrollLeft = event.key === "Home" ? 0 : event.key === "End" ? maximumScroll() : first.scrollLeft + (event.key === "ArrowLeft" ? -60 : 60); syncScroll(first); });
byId("result-zoom").addEventListener("input", updateResultWidth); byId("result-audio").addEventListener("timeupdate", updateResultPlayhead);
byId("result-waveform").addEventListener("click", (event) => { if (!Number.isFinite(state.resultDuration)) return; const scroll = byId("result-waveform-scroll"); const box = scroll.getBoundingClientRect(); byId("result-audio").currentTime = Math.max(0, Math.min(state.resultDuration, (scroll.scrollLeft + event.clientX - box.left) / state.resultPixelsPerSecond)); });
document.addEventListener("keydown", (event) => {
  if (!state.session || !(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== "z") {
    if (state.session && event.ctrlKey && event.key.toLowerCase() === "y") { event.preventDefault(); redo(); } return;
  }
  event.preventDefault(); event.shiftKey ? redo() : undo();
});
window.addEventListener("resize", () => { if (state.session) { updateWaveWidths(); updateResultWidth(); } });
window.addEventListener("pagehide", () => teardown());
