import { renderSourceTimeline } from "./audio-timeline.mjs";
import { createAudioTransport } from "./audio-transport.mjs";
import { drawWaveformViewport } from "./audio-waveform-view.mjs";
import { createWaveformReader } from "./speaker-waveform.mjs";
import { RECONNECT_MESSAGE, recordingBoundaries, setRecordingBoundary } from "./audio-project.mjs";
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
  preparation: null, preparationError: "", operation: null, projectSaving: false, projectController: null, saveLocked: false, ready: false, sourceEpoch: 0, presentationEpoch: 0, monitorTimer: null,
  pixelsPerSecond: 2, follow: false, scrollLock: false, resultDuration: NaN, resultPixelsPerSecond: 2
};

const fingerprint = (value) => JSON.stringify(value);
const editorBusy = () => Boolean(state.operation) || state.saveLocked || state.projectSaving;
const sourceTransport = createAudioTransport({
  audio: byId("source-audio"), resultAudio: byId("result-audio"), canPlay: () => state.ready && !editorBusy(), seek: seekSource,
  getSelection: () => { if (!state.ready) return null; try { return readSelection(); } catch { return null; } },
  reportError: message => { byId("status").textContent = message; }
});
const clock = (seconds) => {
  if (!Number.isFinite(seconds)) return "—";
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600); const minutes = Math.floor(total % 3600 / 60); const rest = String(total % 60).padStart(2, "0");
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${rest}` : `${minutes}:${rest}`;
};
const durationText = (seconds) => !Number.isFinite(seconds) ? "Длительность ещё не определена" : `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 3 }).format(seconds)} с`;
const bytesText = (bytes) => bytes < 1024 * 1024 ? `${Math.round(bytes / 1024)} КБ` : `${(bytes / 1024 / 1024).toFixed(1)} МБ`;

function userMessage(error, fallback) {
  if (error?.name === "AbortError" || error?.message === "cancelled") return "Создание финальной версии отменено. Проект и исходники сохранены в памяти.";
  if ([401, 403].includes(error?.status)) return RECONNECT_MESSAGE;
  if (error?.status === 409) return "Проект или запись изменились в другом окне. Закройте работу, откройте её снова и повторите изменения.";
  if (error?.status === 413) return "Проект превышает безопасный предел размера.";
  return error instanceof Error && /^(Не удалось|Длительность|Верните|Проект|Состав|Регион)/.test(error.message) ? error.message : fallback;
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
    sourceEpoch: state.sourceEpoch,
    originalDuration: state.originalDuration,
    files: state.session?.sourceTracks.map(t => state.filesById.get(t.trackId)) || [],
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
  if (session.revision < state.session.revision) return;
  // This API refreshes canonical metadata/results, never the prepared sources.
  if (session.sourceState !== state.session.sourceState || fingerprint(session.sourceTracks) !== fingerprint(state.session.sourceTracks)) {
    throw Object.assign(new Error("Состав исходников изменился. Откройте запись заново."), { status: 409 });
  }
  const updated = structuredClone(session);
  // Keep the preparation's identity token, but retain the newest canonical revision.
  for (const key of Object.keys(state.session)) if (!(key in updated)) delete state.session[key];
  Object.assign(state.session, updated);
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
  if (!byId("selection-start").value || !byId("selection-end").value || !Number.isFinite(state.originalDuration) || !Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start || end > state.originalDuration) {
    throw new Error("Выделение должно иметь положительную длительность и находиться внутри исходной шкалы.");
  }
  return { startSeconds: microseconds(start), endSeconds: microseconds(end) };
}

function updateSelectionDuration() {
  const start = Number(byId("selection-start").value), end = Number(byId("selection-end").value);
  let valid = false;
  try { readSelection(); valid = true; } catch { /* Empty/out-of-range selection is not an editing target. */ }
  byId("selection-duration").textContent = valid ? (end - start).toFixed(6) : "—";
  byId("selection-error").textContent = "";
  const trackId = byId("selection-track").value;
  const index = state.payload?.trackIds.indexOf(trackId) ?? -1;
  const name = state.tracks.find(track => track.trackId === trackId)?.file.name;
  document.getElementById("speaker-selection-summary").textContent = valid
    ? `Дорожка ${index + 1} · ${name}: ${start.toFixed(3)} — ${end.toFixed(3)} · ${(end-start).toFixed(3)} с`
    : "Выделите фрагмент на форме сигнала.";
  const target = `Дорожка ${index + 1} · ${name || "не выбрана"}`;
  byId("selection-scope").textContent = valid
    ? `Ножницы и границы записи: все дорожки. Тишина: ${target}.`
    : "Клик — позиция; протянуть — выделение. Нажмите отмеченный сегмент, чтобы снять вырез или тишину.";
  for (const [id, label] of [["set-start", "Начало записи от левой границы выделения — все дорожки"], ["set-end", "Конец записи по правой границе выделения — все дорожки"], ["add-cut", "Вырезать выделение на всех дорожках"], ["add-silence", `Заменить выделение тишиной: ${target}`]]) {
    byId(id).title = valid ? `${label}: ${start.toFixed(3)}–${end.toFixed(3)} с` : `${label}. Сначала выделите фрагмент.`;
    byId(id).setAttribute("aria-label", byId(id).title);
  }
  for (const id of ["add-cut", "add-silence"]) byId(id).disabled = !state.ready || editorBusy() || !valid;
  for (const kind of ["start", "end"]) {
    const input = byId(`selection-${kind}`), value = Number(input.value);
    byId(`set-${kind}`).disabled = !state.ready || editorBusy() || !valid || !input.value || !Number.isFinite(value) || value < 0 || value > state.originalDuration;
  }
  sourceTransport.refresh();
  updateRestoreTools();
  for (const wave of workspace.querySelectorAll(".speaker-waveform[data-track-id]")) {
    wave.querySelector(".speaker-selection-overlay")?.remove();
    const selected = wave.dataset.trackId === trackId;
    const row = wave.closest(".speaker-track"); row?.classList.toggle("is-selected", selected);
    if (row) { const label = row.querySelector(".speaker-track-selection"); if (label) label.textContent = selected ? "Выбрана" : ""; }
    if (selected && valid) { const overlay = element("span", "speaker-region-overlay speaker-selection-overlay"); overlay.style.left = `${start/state.originalDuration*100}%`; overlay.style.width = `${(end-start)/state.originalDuration*100}%`; wave.append(overlay); }
  }
}

function clearCandidate() {
  state.presentationEpoch += 1;
  state.candidate = null; state.resultSamples = null;
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
    byId("status").textContent = `Изменение применено: ${action}. Проект не сохранён.`;
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
  byId("undo").disabled = !state.ready || !state.history?.canUndo || editorBusy();
  byId("redo").disabled = !state.ready || !state.history?.canRedo || editorBusy();
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
    const row = workspace.querySelector(`.speaker-track[data-track-id="${track.trackId}"]`);
    if (row) { row.classList.toggle("is-muted", track.mute); row.classList.toggle("is-solo", track.solo);
      row.classList.toggle("is-solo-suppressed", !track.mute && !monitorAudible(track));
      row.classList.toggle("is-excluded", state.payload.excludedTrackIds.includes(track.trackId));
      row.querySelector(".track-monitor-status").textContent = !state.ready ? (state.preparationError ? "Прослушивание недоступно" : "Подготовка прослушивания") : track.mute ? "Mute · эта дорожка выключена" : track.solo ? "Solo · в прослушивании" : !monitorAudible(track) ? "Не слышна: Solo другой дорожки" : "В прослушивании";
    }
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
  const scroll = canvas.closest(".speaker-waveform-scroll, .speaker-result-waveform-scroll");
  const width = scroll?.clientWidth || 800;
  const pps = scroll?.id === "speaker-editor-result-waveform-scroll" ? state.resultPixelsPerSecond : state.pixelsPerSecond;
  drawWaveformViewport(canvas, track.samples, track.duration, pps || width / timelineDuration,
    scroll?.scrollLeft || 0, width, canvas.parentElement?.clientHeight || 112);
  canvas.dataset.timelineDuration = String(timelineDuration);
  canvas.dataset.usedWidth = String(track.duration * (pps || width / timelineDuration));
}

function redrawSourceWaves() {
  for (const track of state.tracks) {
    const canvas = [...byId("tracks").querySelectorAll(".speaker-waveform")].find(w => w.dataset.trackId === track.trackId)?.querySelector("canvas");
    if (canvas) drawCanvas(canvas, track);
  }
}

function selectedEdits(key) {
  let range; try { range = readSelection(); } catch { return []; }
  return (state.payload?.[key] || []).filter(r =>
    Math.abs(r.startSeconds - range.startSeconds) < .000001 && Math.abs(r.endSeconds - range.endSeconds) < .000001 &&
    (key === "globalCuts" || r.trackId === byId("selection-track").value));
}

function updateRestoreTools() {
  for (const [key, id] of [["globalCuts", "restore-cut"], ["trackSilenceRegions", "restore-silence"]]) {
    const tool = byId(id); if (!tool) continue;
    tool.disabled = !state.ready || editorBusy() || !selectedEdits(key).length;
    tool.title = tool.disabled ? "Выберите соответствующий отмеченный сегмент на волне" :
      `Снять ${key === "globalCuts" ? "вырез на всех дорожках" : "тишину на выбранной дорожке"}: ${byId("selection-start").value}–${byId("selection-end").value} с`;
  }
}

function restoreSelected(key) {
  const ids = new Set(selectedEdits(key).map(r => r.regionId));
  if (!ids.size) return;
  const next = structuredClone(state.payload);
  next[key] = next[key].filter(r => !ids.has(r.regionId));
  commitPayload(next, key === "globalCuts" ? "снят выбранный вырез" : "снята выбранная тишина");
}

function markEditableRegion(overlay, region, trackId) {
  overlay.dataset.regionId = region.regionId;
  overlay.setAttribute("role", "button"); overlay.tabIndex = 0;
  overlay.setAttribute("aria-label", `${overlay.title}. Выбрать для снятия правки.`);
  overlay.addEventListener("keydown", event => {
    if (!["Enter", " "].includes(event.key) || !state.ready || editorBusy()) return;
    event.preventDefault(); event.stopPropagation();
    setSelection(region.startSeconds, region.endSeconds, trackId);
  });
}

function boundaryMarker(kind, time, scroll) {
  const marker = element("span", `speaker-boundary speaker-boundary--${kind}`);
  const label = kind === "start" ? "Начало" : "Конец";
  marker.setAttribute("role", "slider"); marker.tabIndex = 0;
  marker.setAttribute("aria-label", `${label} всей записи`);
  marker.setAttribute("aria-valuemin", "0"); marker.setAttribute("aria-valuemax", String(state.originalDuration));
  const paint = value => {
    for (const flag of workspace.querySelectorAll(`.speaker-boundary--${kind}`)) {
      flag.style.left = `${value / state.originalDuration * 100}%`;
      flag.textContent = `${label} ${value.toFixed(3)}`;
      flag.setAttribute("aria-valuenow", String(value));
    }
  };
  marker.style.left = `${time / state.originalDuration * 100}%`;
  marker.textContent = `${label} ${time.toFixed(3)}`; marker.setAttribute("aria-valuenow", String(time));
  let drag = null;
  marker.addEventListener("pointerdown", event => {
    if (event.button !== 0 || !state.ready || editorBusy()) return;
    event.preventDefault(); event.stopPropagation();
    drag = { id: event.pointerId, x: event.clientX, left: scroll.scrollLeft, value: time, epoch: state.sourceEpoch };
    marker.setPointerCapture(event.pointerId);
  });
  marker.addEventListener("pointermove", event => {
    if (!drag || drag.id !== event.pointerId || drag.epoch !== state.sourceEpoch || editorBusy()) return;
    const value = microseconds(Math.max(0, Math.min(state.originalDuration,
      time + (event.clientX - drag.x + scroll.scrollLeft - drag.left) / state.pixelsPerSecond)));
    try { setRecordingBoundary(state.payload, state.originalDuration, kind, value); drag.value = value; paint(value); byId("selection-error").textContent = ""; }
    catch (error) { byId("selection-error").textContent = error.message; }
  });
  marker.addEventListener("pointerup", event => {
    if (!drag || drag.id !== event.pointerId) return;
    event.stopPropagation(); const current = drag; drag = null; marker.releasePointerCapture(event.pointerId);
    if (current.epoch !== state.sourceEpoch || editorBusy() || current.value === time) { paint(time); return; }
    commitPayload(setRecordingBoundary(state.payload, state.originalDuration, kind, current.value), "граница записи");
  });
  const cancel = () => { if (drag) { drag = null; paint(time); } };
  marker.addEventListener("pointercancel", cancel); marker.addEventListener("lostpointercapture", cancel);
  marker.addEventListener("keydown", event => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key) || !state.ready || editorBusy()) return;
    event.preventDefault(); event.stopPropagation();
    const value = event.key === "Home" ? 0 : event.key === "End" ? state.originalDuration : time + (event.key === "ArrowLeft" ? -1 : 1) * (event.shiftKey ? 1 : .1);
    try { commitPayload(setRecordingBoundary(state.payload, state.originalDuration, kind, microseconds(value)), "граница записи"); }
    catch (error) { byId("selection-error").textContent = error.message; }
  });
  return marker;
}

function waveform(track) {
  const scroll = element("div", "speaker-waveform-scroll"); scroll.dataset.trackId = track.trackId;
  const control = element("div", "speaker-waveform"); control.setAttribute("role", "group"); control.tabIndex = 0; control.dataset.trackId = track.trackId;
  control.setAttribute("aria-label", `Форма сигнала ${track.file.name}. Клик ставит позицию; протягивание выделяет фрагмент; клик по правке выбирает её для снятия. Стрелки перемещают позицию; Shift со стрелками изменяет конец выделения.`);
  const canvas = document.createElement("canvas"); canvas.height = 100; drawCanvas(canvas, track); control.append(canvas);
  for (const cut of state.payload.globalCuts) {
    const overlay = element("span", "speaker-region-overlay speaker-region-overlay--cut");
    overlay.style.left = `${cut.startSeconds / state.originalDuration * 100}%`; overlay.style.width = `${(cut.endSeconds - cut.startSeconds) / state.originalDuration * 100}%`;
    overlay.title = `Глобальный вырез ${cut.startSeconds.toFixed(6)}–${cut.endSeconds.toFixed(6)} с`; markEditableRegion(overlay, cut, track.trackId); control.append(overlay);
  }
  for (const region of state.payload.trackSilenceRegions.filter((item) => item.trackId === track.trackId)) {
    const overlay = element("span", "speaker-region-overlay speaker-region-overlay--silence");
    overlay.style.left = `${region.startSeconds / state.originalDuration * 100}%`; overlay.style.width = `${(region.endSeconds - region.startSeconds) / state.originalDuration * 100}%`;
    overlay.title = `Тишина ${region.startSeconds.toFixed(6)}–${region.endSeconds.toFixed(6)} с`; markEditableRegion(overlay, region, track.trackId); control.append(overlay);
  }
  const bounds = recordingBoundaries(state.payload, state.originalDuration);
  for (const [kind, time] of Object.entries(bounds)) control.append(boundaryMarker(kind, time, scroll));
  const playhead = element("span", "speaker-playhead"); playhead.setAttribute("aria-hidden", "true"); control.append(playhead);
  let pointerStart = null;
  let pointerId = null, previousSelection = null, pointerX = 0, clickedRegion = null, pointerEpoch = null;
  control.addEventListener("pointerdown", (event) => {
    if (!state.ready || editorBusy() || event.button !== 0 || pointerStart !== null) return;
    previousSelection = ["selection-start", "selection-end"].map(id => byId(id).value === "" ? NaN : Number(byId(id).value));
    previousSelection.push(byId("selection-track").value);
    pointerEpoch = state.sourceEpoch; pointerX = event.clientX; clickedRegion = event.target.closest("[data-region-id]")?.dataset.regionId;
    pointerId = event.pointerId; pointerStart = pointerTime(event, scroll); control.setPointerCapture(event.pointerId);
    setSelection(pointerStart, pointerStart, track.trackId);
  });
  control.addEventListener("pointermove", (event) => {
    if (pointerStart === null || event.pointerId !== pointerId || pointerEpoch !== state.sourceEpoch || !state.ready || editorBusy()) return;
    const end = pointerTime(event, scroll);
    setSelection(Math.min(pointerStart, end), Math.max(pointerStart, end), track.trackId);
  });
  control.addEventListener("pointerup", (event) => {
    if (pointerStart === null || event.pointerId !== pointerId || pointerEpoch !== state.sourceEpoch || !state.ready || editorBusy()) return;
    const end = pointerTime(event, scroll);
    if (Math.abs(event.clientX - pointerX) <= 4) {
      const region = [...state.payload.globalCuts, ...state.payload.trackSilenceRegions].find(r => r.regionId === clickedRegion);
      if (region) setSelection(region.startSeconds, region.endSeconds, track.trackId);
      else { setSelection(end, end, track.trackId); seekSource(end); }
    } else setSelection(Math.min(pointerStart, end), Math.max(pointerStart, end), track.trackId);
    pointerStart = null; pointerId = null; previousSelection = null; control.releasePointerCapture(event.pointerId);
  });
  const cancelSelection = () => {
    if (previousSelection && pointerEpoch === state.sourceEpoch) setSelection(...previousSelection);
    pointerStart = null; pointerId = null; previousSelection = null;
  };
  control.addEventListener("pointercancel", cancelSelection);
  control.addEventListener("lostpointercapture", cancelSelection);
  control.addEventListener("keydown", (event) => {
    if (!state.ready || editorBusy() || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return; event.preventDefault();
    if (event.shiftKey) { const start = Number(byId("selection-start").value) || 0; const end = Number(byId("selection-end").value) || start;
      setSelection(start, Math.max(start, Math.min(state.originalDuration, event.key === "Home" ? start : event.key === "End" ? state.originalDuration : end + (event.key === "ArrowLeft" ? -.1 : .1))), track.trackId); return; }
    const current = byId("source-audio").currentTime || 0; const step = 5;
    seekSource(event.key === "Home" ? 0 : event.key === "End" ? state.originalDuration : current + (event.key === "ArrowLeft" ? -step : step));
  });
  scroll.addEventListener("scroll", () => syncScroll(scroll), { passive: true }); scroll.append(control); return scroll;
}

function pointerTime(event, scroll) {
  const box = scroll.getBoundingClientRect(); return microseconds(Math.max(0, Math.min(state.originalDuration,
    (scroll.scrollLeft + event.clientX - box.left) / state.pixelsPerSecond)));
}

function selectControl(label, value, values, change) {
  const wrapper = element("label", "speaker-dsp-field", label);
  const input = document.createElement("input"); input.setAttribute("aria-label", label);
  input.disabled = editorBusy() || !state.ready;
  const output = element("span", "speaker-dsp-value");
  if (values.length === 2) {
    input.type = "checkbox"; input.setAttribute("role", "switch"); input.checked = value === values[1][0];
    output.textContent = values[input.checked ? 1 : 0][1];
    input.addEventListener("change", () => change(values[input.checked ? 1 : 0][0]));
  } else {
    input.type = "range"; input.min = "0"; input.max = "3"; input.step = "1";
    input.value = String(values.findIndex(item => item[0] === value));
    const refresh = () => { output.textContent = values[Number(input.value)][1]; input.setAttribute("aria-valuetext", output.textContent); };
    refresh(); input.addEventListener("input", refresh);
    input.addEventListener("change", () => change(values[Number(input.value)][0]));
    input.title = "Выкл. · Лёгкая · Средняя · Сильная";
    const ticks = element("span", "speaker-compression-ticks"); ticks.setAttribute("aria-hidden", "true");
    for (const [, text] of values) ticks.append(element("span", "", text));
    wrapper.append(input, ticks, output); return wrapper;
  }
  wrapper.append(input, output); return wrapper;
}

function renderTracks() {
  const list = byId("tracks");
  const focused = list.contains(document.activeElement) ? document.activeElement : null;
  const focusedBoundary = focused?.classList.contains("speaker-boundary--start") ? "start" : focused?.classList.contains("speaker-boundary--end") ? "end" : null;
  const focusedRow = focused?.closest(".speaker-track"), focusIndex = focusedRow ? [...focusedRow.querySelectorAll("button, select, input")].indexOf(focused) : -1;
  const scrollLeft = list.querySelector(".speaker-waveform-scroll")?.scrollLeft || 0;
  list.replaceChildren();
  const excluded = new Set(state.payload.excludedTrackIds);
  state.payload.trackIds.forEach((trackId, index) => {
    const track = state.tracks.find((item) => item.trackId === trackId); const setting = state.payload.trackProcessing.find((item) => item.trackId === trackId);
    const item = element("li", `speaker-track${excluded.has(trackId) ? " is-excluded" : ""}`); item.dataset.trackId = trackId;
    const header = element("div", "speaker-track__header"); const heading = element("div", "speaker-track__identity");
    heading.append(element("span", "speaker-track__number", `Дорожка ${index + 1}`), element("h4", "", track.file.name),
      element("span", "", `${durationText(track.duration)} · ${excluded.has(trackId) ? "Не в финальном миксе" : "в финальном миксе"}`));
    const monitor = element("div", "speaker-track__buttons");
    const solo = makeButton("S · Solo", () => toggleMonitoring(trackId, "solo"), trackId, !state.ready); solo.dataset.action = "solo"; solo.setAttribute("aria-pressed", String(track.solo));
    const mute = makeButton("M · Mute", () => toggleMonitoring(trackId, "mute"), trackId, !state.ready); mute.dataset.action = "mute"; mute.setAttribute("aria-pressed", String(track.mute));
    for (const [button, action] of [[solo, "Solo"], [mute, "Mute"]]) {
      button.title = `${action} · Дорожка ${index + 1} · ${track.file.name} · только прослушивание`;
      button.setAttribute("aria-label", button.textContent);
      button.setAttribute("aria-description", button.title);
      button.textContent = action === "Solo" ? "S" : "M";
    }
    const editsDisabled = editorBusy() || !state.ready;
    const include = makeButton(excluded.has(trackId) ? "Вернуть в микс" : "Исключить из микса", () => changeTrack(trackId, "excluded", !excluded.has(trackId)), trackId, editsDisabled);
    const up = makeButton("Вверх", () => moveTrack(trackId, -1), trackId, editsDisabled || index === 0);
    const down = makeButton("Вниз", () => moveTrack(trackId, 1), trackId, editsDisabled || index === state.payload.trackIds.length - 1);
    for (const [button, icon] of [[up, "↑"], [down, "↓"]]) {
      button.setAttribute("aria-label", button.textContent); button.title = `${button.textContent} · ${track.file.name}`; button.textContent = icon;
    }
    monitor.append(solo, mute, include, up, down); header.append(heading, monitor, element("span", "track-monitor-status"));
    const dsp = element("div", "speaker-dsp");
    dsp.append(selectControl("Улучшение", setting.enhancement, [["off", "Выкл."], ["gentle", "Мягкое"]], (value) => changeTrack(trackId, "enhancement", value)),
      selectControl("Выравнивание громкости", setting.leveling, [["off", "Выкл."], ["on", "Вкл."]], (value) => changeTrack(trackId, "leveling", value)),
      selectControl("Компрессия", setting.compression, [["off", "Выкл."], ["light", "Лёгкая"], ["medium", "Средняя"], ["strong", "Сильная"]], (value) => changeTrack(trackId, "compression", value)));
    const summary = element("p", "speaker-track__summary", processingLabel(setting));
    header.append(element("span", "speaker-track-selection"));
    const preview = state.ready ? waveform(track) : element("div", "speaker-source-pending", track.preparationError || (state.preparationError ? "Ожидает повторной подготовки." : "Подготовка формы сигнала…"));
    const processing = element("details", "speaker-dsp-disclosure");
    processing.open = track.controlsOpen ?? window.innerWidth >= 768;
    const processingToggle = element("summary", "", "Обработка дорожки");
    processingToggle.addEventListener("click", event => {
      event.preventDefault(); track.controlsOpen = !processing.open; processing.open = track.controlsOpen;
    });
    processing.append(processingToggle, dsp);
    const controls = element("div", "speaker-track-controls"); controls.append(header, processing, summary);
    item.append(controls, preview); list.append(item);
  });
  updateWaveWidths();
  for (const scroll of list.querySelectorAll(".speaker-waveform-scroll")) scroll.scrollLeft = scrollLeft;
  redrawSourceWaves(); updateScrollbar(); applyMonitoring(); updateSelectionDuration();
  if (focusedRow && focusedBoundary) {
    [...list.children].find(row => row.dataset.trackId === focusedRow.dataset.trackId)?.querySelector(`.speaker-boundary--${focusedBoundary}`)?.focus({ preventScroll: true });
  } else if (focusedRow && focusIndex >= 0) {
    const row = [...list.children].find(row => row.dataset.trackId === focusedRow.dataset.trackId);
    row?.querySelectorAll("button, select, input")[focusIndex]?.focus({ preventScroll: true });
  }
}

function renderRegions() {
  const container = byId("regions");
  const focused = container.contains(document.activeElement) ? document.activeElement : null;
  const focusedRow = focused?.closest(".speaker-region-row"), focusIndex = focusedRow ? [...focusedRow.querySelectorAll("input, button")].indexOf(focused) : -1;
  container.replaceChildren();
  const regions = [...state.payload.globalCuts.map((region) => ({ ...region, kind: "cut" })),
    ...state.payload.trackSilenceRegions.map((region) => ({ ...region, kind: "silence" }))];
  document.getElementById("speaker-regions-heading").textContent = `Правки · ${regions.length}`;
  if (!regions.length) { container.append(element("p", "", "Регионов пока нет.")); if (focusedRow) document.getElementById("speaker-regions-heading").focus(); return; }
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
    const select = makeButton("Выбрать", () => { setSelection(region.startSeconds, region.endSeconds, region.trackId); row.scrollIntoView({ block: "nearest" }); }, null, editsDisabled);
    const remove = makeButton("Удалить", () => {
      const next = structuredClone(state.payload); const key = region.kind === "cut" ? "globalCuts" : "trackSilenceRegions";
      next[key] = next[key].filter((item) => item.regionId !== region.regionId); commitPayload(next, "удаление региона");
    }, null, editsDisabled);
    fields.append(start, end, apply, select, remove); row.append(title, fields); container.append(row);
  }
  if (focusedRow && focusIndex >= 0) {
    const row = [...container.children].find(row => row.dataset.regionId === focusedRow.dataset.regionId);
    (row?.querySelectorAll("input, button")[focusIndex] || document.getElementById("speaker-regions-heading")).focus({ preventScroll: true });
  }
}

function updateRenderState() {
  const allExcluded = Boolean(state.payload && state.payload.excludedTrackIds.length === state.payload.trackIds.length);
  const disabled = !state.ready || !state.session || !Number.isFinite(state.originalDuration) || allExcluded || editorBusy();
  byId("render").disabled = disabled;
  byId("source-audio").hidden = !state.ready;
  sourceTransport.refresh();
  byId("render-reason").textContent = allExcluded ? "Все дорожки исключены. Верните хотя бы одну дорожку в микс." :
    state.saveLocked ? "Идёт сохранение в архив «Спикерская»." : state.operation ? "Идёт локальная сборка." : !state.ready ? "Сборка недоступна, пока исходники не прошли полную проверку." :
      "В результат войдут только дорожки, оставленные в финальном миксе.";
  byId("save").disabled = !state.ready || !state.session || editorBusy();
  byId("close").disabled = state.saveLocked;
  for (const id of ["selection-start", "selection-end", "selection-track"]) byId(id).disabled = !state.ready || editorBusy();
  updateSelectionDuration();
}

function render() {
  if (!state.session) return;
  if (state.payload) { renderTracks(); renderRegions(); }
  else { byId("tracks").replaceChildren(); byId("regions").replaceChildren(); }
  updateHistoryControls(); updateRenderState(); updatePlayheads();
  if (!state.ready) renderSourceTimeline("speaker-source-timeline", NaN, 0);
  byId("status").dataset.dirty = String(currentDirty());
  byId("status").textContent = state.preparationError || (!state.ready ? "Подготовка исходников…" : currentDirty() ? "Есть несохранённые изменения" : "Все изменения сохранены");
  byId("identity").textContent = `${state.session.title} · ${state.tracks.length} дорожек · ${clock(state.originalDuration)}`;
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
  if (!first) return; renderSourceTimeline("speaker-source-timeline", state.originalDuration, state.pixelsPerSecond, first.scrollLeft); const fraction = Math.min(1, first.clientWidth / first.scrollWidth); const width = Math.max(36, rail.clientWidth * fraction);
  const max = maximumScroll(); const travel = Math.max(0, rail.clientWidth - width); thumb.style.width = `${width}px`; thumb.style.transform = `translateX(${max ? first.scrollLeft / max * travel : 0}px)`;
  rail.setAttribute("aria-valuemax", String(max)); rail.setAttribute("aria-valuenow", String(Math.round(first.scrollLeft)));
}

function syncScroll(origin) {
  if (state.scrollLock) return; state.scrollLock = true;
  for (const scroll of byId("tracks").querySelectorAll(".speaker-waveform-scroll")) if (scroll !== origin) scroll.scrollLeft = origin.scrollLeft;
  redrawSourceWaves(); updateScrollbar(); requestAnimationFrame(() => { state.scrollLock = false; });
}

function updateWaveWidths() {
  const first = byId("tracks").querySelector(".speaker-waveform-scroll"); if (!first || !state.originalDuration) return;
  const base = first.clientWidth / state.originalDuration; state.pixelsPerSecond = Math.max(.01, base * Number(byId("zoom").value));
  const width = Math.max(first.clientWidth, Math.ceil(state.originalDuration * state.pixelsPerSecond));
  for (const control of byId("tracks").querySelectorAll(".speaker-waveform")) control.style.width = `${width}px`;
  redrawSourceWaves(); updatePlayheads(); updateScrollbar();
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
  byId("source-time").textContent = `${clock(time)} / ${clock(state.originalDuration)}`;
  if (state.follow && !byId("source-audio").paused) {
    const first = byId("tracks").querySelector(".speaker-waveform-scroll"); if (first) { first.scrollLeft = Math.max(0, time * state.pixelsPerSecond - first.clientWidth / 2); syncScroll(first); }
  }
}

function setupPlayback() {
  stopMonitoringSynchronization();
  const masterTrack = state.tracks.reduce((best, track) => track.duration > best.duration ? track : best, state.tracks[0]);
  const master = byId("source-audio"); const hidden = byId("preview-audios"); hidden.replaceChildren();
  for (const track of state.tracks) {
    const audio = track === masterTrack ? master : document.createElement("audio"); audio.src = track.url; audio.preload = "auto"; audio.dataset.trackId = track.trackId; track.audio = audio;
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

async function metadataFor(url, signal) {
  const audio = document.createElement("audio"); audio.preload = "metadata";
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      clearTimeout(timer); signal?.removeEventListener("abort", aborted);
      audio.removeEventListener("loadedmetadata", loaded); audio.removeEventListener("error", failed);
      audio.removeAttribute("src"); audio.load();
    };
    const finish = (error, duration) => { cleanup(); error ? reject(error) : resolve(duration); };
    const loaded = () => Number.isFinite(audio.duration) && audio.duration > 0
      ? finish(null, audio.duration) : finish(new Error("Не удалось определить длительность исходной дорожки."));
    const failed = () => finish(new Error("Не удалось прочитать исходную дорожку в этом браузере."));
    const aborted = () => finish(new DOMException("cancelled", "AbortError"));
    const timer = setTimeout(() => finish(new Error("Не удалось определить длительность исходной дорожки.")), 30000);
    audio.addEventListener("loadedmetadata", loaded); audio.addEventListener("error", failed);
    signal?.addEventListener("abort", aborted, { once: true });
    if (signal?.aborted) aborted(); else audio.src = url;
  });
}

async function prepareSources(epoch) {
  const controller = new AbortController(); state.preparation = controller;
  const reader = createWaveformReader(controller.signal);
  state.preparationError = ""; byId("source-retry").hidden = true;
  const tracks = [...state.tracks]; const session = state.session; const payload = state.payload; const draft = state.draft;
  const current = () => state.sourceEpoch === epoch && state.session === session && !controller.signal.aborted;
  let activeTrack;
  try {
    const durations = [];
    for (const [index, track] of tracks.entries()) {
      activeTrack = track; track.preparationError = "";
      byId("status").textContent = `Подготовка дорожки ${index + 1} из ${tracks.length}: ${track.file.name}`;
      const duration = await metadataFor(track.url, controller.signal);
      if (!current()) throw new DOMException("cancelled", "AbortError");
      track.duration = duration; durations.push(duration);
      track.samples = await reader.read(track.file, duration);
      if (!current()) throw new DOMException("cancelled", "AbortError");
    }
    activeTrack = null;
    const originalDuration = Math.max(...durations);
    if (originalDuration - Math.min(...durations) > .5) throw new Error("Длительность дорожек различается больше чем на 0,5 секунды. Выберите дорожки одной и той же записи Zoom.");
    const normalized = normalizeSpeakerPayload(payload, session.sourceTracks.map((track) => track.trackId), originalDuration);
    state.originalDuration = originalDuration; state.payload = normalized; state.history.reset(normalized);
    state.savedFingerprint = draft ? fingerprint(normalized) : "";
    setupPlayback(); state.ready = true; render();
  } catch (error) {
    if (!current()) throw new DOMException("cancelled", "AbortError");
    const detail = userMessage(error, "Не удалось декодировать аудио для формы сигнала.");
    if (activeTrack) activeTrack.preparationError = detail;
    const message = activeTrack ? `Не удалось подготовить «${activeTrack.file.name}». ${detail}` : detail;
    // Keep exact File references and the project so retry needs no re-selection.
    state.preparationError = message; state.ready = false; render();
    byId("source-retry").hidden = false;
    byId("render-status").textContent = "Исходники остались в редакторе. Повторите подготовку или измените выбор файлов в разделе «Импорт».";
    throw new Error(message, { cause: error });
  } finally {
    reader.dispose();
    if (state.preparation === controller) state.preparation = null;
  }
}

export async function saveSpeakerProject() {
  if (!state.ready || editorBusy() || !state.session || !state.saveDraft) return false;
  const epoch = state.sourceEpoch;
  const submitted = structuredClone(state.payload);
  state.projectSaving = true; state.projectController = new AbortController(); byId("project-cancel").hidden = false;
  byId("status").textContent = "Сохранение проекта…"; updateRenderState();
  try {
    const result = await state.saveDraft({ session: structuredClone(state.session), draft: state.draft,
      payload: submitted, files: state.session.sourceTracks.map(t => state.filesById.get(t.trackId)), duration: state.originalDuration, signal: state.projectController.signal,
      onProgress: ({ uploadedBytes, totalBytes }) => { if (epoch === state.sourceEpoch) byId("status").textContent = `Сохранение исходных дорожек: ${Math.round(uploadedBytes / totalBytes * 100)}%`; } });
    if (epoch !== state.sourceEpoch || !result) return false;
    if (result.mapping) {
      const remap = id => result.mapping.get(id);
      state.tracks.forEach(t => { t.trackId = remap(t.trackId); t.manifest = result.session.sourceTracks.find(s => s.trackId === t.trackId); });
      state.filesById = new Map(state.tracks.map(t => [t.trackId, t.file]));
      const remapPayload = payload => {
        const next = structuredClone(payload); next.trackIds = next.trackIds.map(remap); next.excludedTrackIds = next.excludedTrackIds.map(remap);
        for (const value of [...next.trackProcessing, ...next.trackSilenceRegions]) value.trackId = remap(value.trackId);
        return normalizeSpeakerPayload(next, result.session.sourceTracks.map(t => t.trackId), state.originalDuration);
      };
      state.history.past = state.history.past.map(remapPayload); state.history.future = state.history.future.map(remapPayload);
      state.payload = structuredClone(result.draft.payload); state.history.present = structuredClone(state.payload);
      // Keep the local MP3 downloadable, but never relabel its source provenance.
      if (state.candidate) byId("render-status").textContent = "Проект сохранён. Создайте финальную версию заново, чтобы сохранить её в аудиоархив.";
    } else state.candidate = rebindSpeakerCandidate(state.candidate, submitted, result.session.revision, result.draft.draftRevision);
    state.draft = result.draft; state.session = result.session;
    state.savedFingerprint = fingerprint(result.draft.payload);
    const select = byId("selection-track"); select.replaceChildren();
    for (const t of state.tracks) { const option = element("option", "", t.file.name); option.value = t.trackId; select.append(option); }
    state.onSaved?.(result); render();
    return !currentDirty();
  } catch (error) {
    if (epoch === state.sourceEpoch) byId("status").textContent = userMessage(error, "Не удалось сохранить проект. Изменения и исходники остались в памяти.");
    return false;
  } finally {
    if (epoch === state.sourceEpoch) { state.projectSaving = false; state.projectController = null; byId("project-cancel").hidden = true; updateRenderState(); notifyState(); }
  }
}

function dialogChoice(id, choices) {
  const dialog = document.getElementById(id), focus = document.activeElement;
  return new Promise(resolve => {
    let resolved = false;
    const finish = value => { if (resolved) return; resolved = true; dialog.close();
      for (const [button, handler] of handlers) button.removeEventListener("click", handler);
      dialog.removeEventListener("cancel", cancel); if (focus?.isConnected) focus.focus(); resolve(value); };
    const handlers = Object.entries(choices).map(([button, value]) => {
      const node = document.getElementById(button), handler = () => finish(value); node.addEventListener("click", handler); return [node, handler];
    });
    const cancel = event => { event.preventDefault(); finish("cancel"); }; dialog.addEventListener("cancel", cancel); dialog.showModal();
  });
}
export async function confirmLocalProjectSave() {
  return await dialogChoice("speaker-local-save-dialog", { "speaker-local-save-confirm": "save", "speaker-local-save-cancel": "cancel" }) === "save";
}
export async function protectSpeakerTransition() {
  if (editorBusy()) return false;
  if (!currentDirty()) return true;
  const choice = await dialogChoice("speaker-unsaved-dialog", { "speaker-unsaved-save": "save", "speaker-unsaved-discard": "discard", "speaker-unsaved-cancel": "cancel" });
  return choice === "discard" || (choice === "save" && await saveSpeakerProject());
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
  const epoch = state.sourceEpoch;
  let snapshot;
  try {
    snapshot = state.session.kind === "local" ? { local: true, title: state.session.title, payload: structuredClone(state.payload), originalDurationSeconds: state.originalDuration, sources: state.payload.trackIds.map(id => ({ trackId: id, file: state.filesById.get(id) })) } : createSpeakerRenderSnapshot({ session: state.session, draftRevision: state.draft?.draftRevision || 0,
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
    if (Math.abs(actualDuration - resultDuration(snapshot.originalDurationSeconds, snapshot.payload.globalCuts)) > 1152 / 48000) throw new Error("Длительность результата не совпадает с монтажом.");
    const candidate = snapshot.local ? { candidateType: "local-speaker", blob, payload: snapshot.payload,
      presentationFilename: `${snapshot.title}-speaker.mp3`, originalDurationSeconds: snapshot.originalDurationSeconds,
      resultDurationSeconds: actualDuration, globallyRemovedDurationSeconds: removedDuration(snapshot.payload.globalCuts), sizeBytes: blob.size } :
      await buildSpeakerCandidate({ blob, snapshot, measurements, resultDurationSeconds: actualDuration, sha256: sha256Hex }); abortCheck(controller);
    await presentCandidate(candidate, controller); abortCheck(controller);
    byId("progress").value = 100; byId("render-status").textContent = "Финальная версия готова. В архив ничего не передавалось.";
  } catch (error) {
    if (epoch !== state.sourceEpoch) return;
    clearCandidate(); byId("render-status").textContent = userMessage(error, "Не удалось собрать результат. Проект и исходники остались в памяти.");
  } finally {
    if (epoch !== state.sourceEpoch) return;
    if (logListener) state.engine?.off("log", logListener);
    if (state.engine?.loaded) for (const path of [...inputPaths, filterPath, outputPath]) { try { await state.engine.deleteFile(path); } catch { /* fixed temporary path may be absent */ } }
    if (state.operation === controller) state.operation = null;
    byId("cancel").hidden = true; byId("progress").hidden = true; render();
  }
}

function cancelRender() {
  if (!state.operation) return; state.operation.abort(); state.engine?.terminate(); state.engine = null; clearCandidate();
  byId("render-status").textContent = "Создание финальной версии отменено. Проект и исходники сохранены в памяти."; byId("cancel").hidden = true; byId("progress").hidden = true; render();
}

async function resultSamples(blob, duration, signal) {
  const reader = createWaveformReader(signal);
  try { return await reader.read(new File([blob], "result.mp3", { type: "audio/mpeg" }), duration); }
  finally { reader.dispose(); }
}

async function presentCandidate(candidate, controller) {
  const epoch = state.presentationEpoch;
  const samples = await resultSamples(candidate.blob, candidate.resultDurationSeconds, controller.signal); abortCheck(controller);
  if (epoch !== state.presentationEpoch) throw new DOMException("cancelled", "AbortError");
  state.candidate = candidate;
  state.candidateUrl = URL.createObjectURL(candidate.blob); byId("result-audio").src = state.candidateUrl;
  byId("download").href = state.candidateUrl; byId("download").download = candidate.presentationFilename;
  byId("original-duration").textContent = durationText(candidate.originalDurationSeconds); byId("result-duration").textContent = durationText(candidate.resultDurationSeconds);
  byId("removed-duration").textContent = durationText(candidate.globallyRemovedDurationSeconds); byId("result-format").textContent = `MP3 · 128 кбит/с · ${bytesText(candidate.sizeBytes)}`;
  state.resultDuration = candidate.resultDurationSeconds; const canvas = byId("result-waveform").querySelector("canvas");
  state.resultSamples = samples;
  drawCanvas(canvas, { samples, duration: state.resultDuration }, state.resultDuration);
  byId("result").hidden = false; updateResultWidth(); updateResultPlayhead();
}

function updateResultWidth() {
  if (!Number.isFinite(state.resultDuration)) return; const scroll = byId("result-waveform-scroll");
  state.resultPixelsPerSecond = scroll.clientWidth / state.resultDuration * Number(byId("result-zoom").value);
  byId("result-waveform").style.width = `${Math.max(scroll.clientWidth, state.resultDuration * state.resultPixelsPerSecond)}px`;
  drawCanvas(byId("result-waveform").querySelector("canvas"), { samples: state.resultSamples, duration: state.resultDuration }, state.resultDuration);
}

function updateResultPlayhead() {
  const current = byId("result-audio").currentTime || 0; byId("result-waveform").querySelector(".speaker-playhead").style.left = `${current * state.resultPixelsPerSecond}px`;
  byId("result-time").textContent = `${clock(current)} / ${clock(state.resultDuration)}`;
}

function teardown() {
  state.sourceEpoch += 1; state.preparation?.abort(); state.preparation = null; state.preparationError = ""; byId("source-retry").hidden = true;
  cancelRender(); state.operation = null; stopMonitoringSynchronization(true); clearCandidate(); byId("source-audio").pause(); byId("source-audio").removeAttribute("src"); byId("source-audio").load();
  for (const track of state.tracks) { track.audio?.pause(); URL.revokeObjectURL(track.url); }
  byId("preview-audios").replaceChildren(); state.session = null; state.filesById = new Map(); state.tracks = []; state.payload = null; state.history = null;
  state.draft = null; state.savedFingerprint = ""; state.originalDuration = NaN; state.saveDraft = null; state.onSaved = null; state.saveLocked = false; state.ready = false; workspace.hidden = true;
  document.getElementById("announcement-processor-card").hidden = true;
  document.getElementById("active-editor-mode").textContent = "Выберите исходники и режим редактирования.";
  notifyState();
  window.dispatchEvent(new Event("speaker-editor-closed"));
}

export async function closeSpeakerEditor(force = false, isCurrent = () => true) {
  if (!isCurrent()) return false;
  if (!state.session) return true;
  if (state.saveLocked || state.projectSaving) {
    byId("status").textContent = "Сохранение в архив ещё выполняется. Сначала отмените или завершите передачу.";
    return false;
  }
  if (!force && !await protectSpeakerTransition()) return false;
  if (!isCurrent()) return false;
  teardown(); return true;
}

export async function openSpeakerEditor({ session, files, draft = null, saveDraft: save, onSaved, isCurrent = () => true }) {
  if (session.kind !== "local" && (session.lifecycle.state !== "incoming" || session.sourceState !== "available")) throw new Error("Для обработки спикерской нужны доступные исходники. Верните запись для обработки.");
  if (draft && draft.payloadSchema !== SPEAKER_PAYLOAD_SCHEMA) throw new Error("Сохранённый проект имеет неподдерживаемую схему и не будет перезаписан.");
  const orderedManifest = [...session.sourceTracks].sort((left, right) => left.ordinal - right.ordinal);
  if (files.length !== orderedManifest.length) throw new Error("Состав загруженных исходников не совпадает с записью.");
  if (!await closeSpeakerEditor(false, isCurrent) || !isCurrent()) return false;
  const epoch = ++state.sourceEpoch;
  state.ready = false; state.saveLocked = false; state.session = structuredClone(session); state.filesById = new Map(orderedManifest.map((track, index) => [track.trackId, files[index]]));
  state.tracks = orderedManifest.map((track, index) => ({ trackId: track.trackId, manifest: track, file: files[index], url: URL.createObjectURL(files[index]), duration: NaN, samples: null, solo: false, mute: false, audio: null }));
  state.payload = draft ? structuredClone(draft.payload) : defaultSpeakerPayload(orderedManifest.map((track) => track.trackId));
  state.history = new SpeakerHistory(state.payload); state.savedFingerprint = draft ? fingerprint(state.payload) : ""; state.draft = draft; state.saveDraft = save; state.onSaved = onSaved;
  document.getElementById("announcement-processor-card").hidden = true;
  workspace.hidden = false; document.getElementById("active-editor-mode").textContent = "Сейчас открыто: Финальная обработка спикерской"; byId("identity").textContent = `${session.title} · активная работа «Спикерская» · исходная шкала неизменна`;
  byId("technical").textContent = `Идентификатор записи: ${session.id}. Ревизия записи: ${session.revision}. Версия процессора: speaker-editor-v1.`;
  const select = byId("selection-track"); select.replaceChildren(); for (const track of orderedManifest) { const option = document.createElement("option"); option.value = track.trackId; option.textContent = track.originalName; select.append(option); }
  setSelection(0, ""); clearCandidate();
  state.originalDuration = NaN; render();
  window.dispatchEvent(new Event("speaker-editor-opened"));
  try { await prepareSources(epoch); if (!isCurrent() || state.sourceEpoch !== epoch) return false; workspace.scrollIntoView({ behavior: "smooth", block: "start" }); return true; }
  catch (error) {
    if (state.sourceEpoch !== epoch) return false;
    byId("status").textContent = userMessage(error, "Не удалось подготовить Спикерскую. Исходники остались в редакторе.");
    return false;
  }
}

byId("selection-track").addEventListener("change", updateSelectionDuration);
byId("selection-start").addEventListener("input", updateSelectionDuration); byId("selection-end").addEventListener("input", updateSelectionDuration);
byId("add-cut").addEventListener("click", () => addRegion("cut")); byId("add-silence").addEventListener("click", () => addRegion("silence"));
byId("undo").addEventListener("click", undo); byId("redo").addEventListener("click", redo); byId("save").addEventListener("click", saveSpeakerProject);
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
window.addEventListener("resize", () => {
  if (!state.session) return;
  for (const row of byId("tracks").querySelectorAll(".speaker-track")) {
    const track = state.tracks.find(item => item.trackId === row.dataset.trackId);
    row.querySelector(".speaker-dsp-disclosure").open = track.controlsOpen ?? window.innerWidth >= 768;
  }
  updateWaveWidths(); updateResultWidth();
});
window.addEventListener("pagehide", () => teardown());

for (const kind of ["start", "end"]) byId(`set-${kind}`).addEventListener("click", () => {
  try { const value = Number(byId(`selection-${kind}`).value); commitPayload(setRecordingBoundary(state.payload, state.originalDuration, kind, value), "граница записи"); }
  catch (error) { byId("selection-error").textContent = error.message; }
});
window.addEventListener("beforeunload", event => { if (currentDirty()) { event.preventDefault(); event.returnValue = ""; } });

byId("project-cancel").addEventListener("click", () => state.projectController?.abort());

byId("source-retry").addEventListener("click", async () => {
  if (!state.session || state.preparation || state.ready) return;
  byId("render-status").textContent = "";
  try { await prepareSources(state.sourceEpoch); }
  catch { /* prepareSources displays a named error and retains the inputs. */ }
});

byId("result-waveform-scroll").addEventListener("scroll", () => {
  if (state.resultSamples) drawCanvas(byId("result-waveform").querySelector("canvas"), { samples: state.resultSamples, duration: state.resultDuration }, state.resultDuration);
}, { passive: true });
for (const [id, key] of [["restore-cut", "globalCuts"], ["restore-silence", "trackSilenceRegions"]]) byId(id).addEventListener("click", () => restoreSelected(key));
