import { contextActions } from "./audio-actions.mjs";
import { defaultSpeakerPayload } from "./speaker-editor-core.mjs";
import { RECONNECT_MESSAGE, localSourceContext, bindLocalPayload, projectProjection, ingestSpeakerRecoverySources, ProjectSave } from "./audio-project.mjs";
import { eligible, parseEditorIntent, mergeSessions, recoveryPolicy, deletionImpact, pageItems, speakerRecoveryBinding,
  createSpeakerRecoveryAttempt, recoveryContinuationRequest } from './audio-archive-core.mjs';
import { AudioArchiveGateway, MAX_AUDIO_SESSION_BYTES, validateSessionManifest, validateSpeakerOutput, verifyLocalSourceAttachment, reconstructAnnouncementOutput, reconstructSpeakerOutput, prepareRemoteSourceBatch, remoteSourceFingerprint } from "./audio-archive-client.mjs";
import { ServiceSessionController } from "./service-session.mjs";
import { bindProcessorSources, setProcessorSelectionGuard, clearProcessorFiles, getProcessorFiles, getProcessorResult, loadProcessorFiles, updateProcessorProvenanceContext } from "./audio-processor.mjs";
import { confirmLocalProjectSave, protectSpeakerTransition, closeSpeakerEditor, getSpeakerSaveState, openSpeakerEditor, setSpeakerSaveLocked, speakerEditorSessionId, updateSpeakerSession } from "./speaker-editor.mjs";

const byId = (id) => document.getElementById(`source-session-${id}`);
const speakerId = (id) => document.getElementById(`speaker-editor-${id}`);
const baseUrl = globalThis.__MESER_AUDIO_ARCHIVE_GATEWAY__ || "";
const gateway = new AudioArchiveGateway(baseUrl);
const state = {
  localContext: null, localProject: null, editorMode: null,
  authenticated: false, authSequence: 0, retryAction: null, reconnectNeeded: false,
  listsLoaded: false, projects: new Map(), deleteSequence: 0, deleteBusy: false,
  sessions: [],
  allSessions: [],
  picker: { requested: false, page: 0, pageSize: 10 },
  resultArchive: "announcement",
  refreshSequence: 0,
  sessionSequence: 0,
  outputSequence: 0,
  incompleteSequence: 0,
  mode: "archive",
  pendingFiles: [],
  pendingOrigin: "manual",
  retryKey: null,
  uploadController: null,
  afterLogin: null,
  deleteTarget: null,
  loadingArchive: false,
  preparedBatch: null,
  preparationController: null,
  activeSession: null,
  activeManifest: null,
  announcementDraft: null,
  processorProvenance: [],
  candidate: null,
  publicationKey: null,
  publicationController: null,
  publicationTransactionId: null,
  speakerSaveKey: null,
  speakerSaveController: null,
  speakerSaveTransactionId: null,
  speakerSaveSnapshot: null,
  speakerResumeController: null,
  speakerResumeTransactionId: null,
  speakerResumeSnapshot: null,
  speakerResumeStatus: null,
  speakerResumeCancellable: false,
  speakerRecovery: null,
  outputUrl: null
};

const statusText = Object.freeze({ new: "Новая", in_progress: "В работе", result_ready: "Результат готов" });
const originText = Object.freeze({ manual: "Создана вручную", device: "С устройства", zoom_webhook: "Zoom" });

function formatBytes(bytes) {
  const format = (value) => new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(value);
  if (bytes < 1024) return `${bytes} байт`;
  if (bytes < 1024 * 1024) return `${format(bytes / 1024)} КБ`;
  return `${format(bytes / (1024 * 1024))} МБ`;
}

function formatDate(value) {
  if (!value) return "Дата записи не указана";
  return new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }).format(new Date(value)) + " UTC";
}

function formatMediaType(value) {
  return ({ "audio/mpeg": "MP3", "audio/mp4": "M4A", "audio/wav": "WAV" })[value] || "аудиофайл";
}

function workflowLabel(value) {
  return ({ announcement: "Анонс-мейкер", speaker: "Спикерская" })[value] || "Неизвестный тип работы";
}

function userError(error, fallback) {
  if (error?.name === "AbortError") return "Операция остановлена.";
  if (error?.status === 401) return RECONNECT_MESSAGE;
  if (error?.status === 403) return "Действие отклонено проверкой Origin, CSRF или прав операции. Обновите состояние и повторите безопасно.";
  if (error?.status === 409) return "Данные записи изменились в другом окне. Обновите архив и повторите действие.";
  if (error?.status === 413) return "Объём данных превышает допустимый предел.";
  if (error?.status === 422) return "Проверка целостности данных не пройдена. Операция остановлена без изменений.";
  if (error?.status >= 500) return "Архив временно недоступен. Повторите действие позже.";
  if (error?.userMessage) return error.userMessage;
  if (error instanceof TypeError) return "Не удалось связаться со служебным сервером. Проверьте подключение к сети и повторите действие.";
  return fallback;
}

function setArchiveStatus(message) {
  byId("status").textContent = message;
}

function updateSessionStatus() {
  byId("session-status").textContent = state.authenticated ? "Служебная сессия активна." : RECONNECT_MESSAGE;
  byId("authenticate").hidden = state.authenticated;
  document.getElementById("archive-reconnect").hidden = !state.reconnectNeeded || (state.authenticated && !state.retryAction);
  document.getElementById("archive-reconnect-message").textContent = state.authenticated ? "Подключение восстановлено. Повторите действие." : RECONNECT_MESSAGE;
  document.getElementById("archive-reconnect-login").hidden = state.authenticated;
  document.getElementById("archive-reconnect-retry").hidden = !state.authenticated || !state.retryAction;

}

const authController = new ServiceSessionController({
  gateway,
  onState: ({ state: authState, detail }) => {
    const labels = {
      "checking-password": "Проверка пароля…",
      "verifying-session": "Подтверждаем служебную сессию…",
      connected: "Служебная сессия подтверждена.",
      denied: "Неверный пароль.",
      throttled: "Слишком много попыток. Подождите и повторите вход.",
      "network-error": "Не удалось связаться с сервером. Проверьте подключение.",
      "server-error": detail?.status >= 500 ? "Служебный сервер временно недоступен." : "Не удалось подтвердить вход."
    };
    if (labels[authState]) byId("login-status").textContent = labels[authState];
    if (authState === "connected" && !state.authenticated && (byId("login-dialog").open || state.afterLogin)) void finishAuthentication();
  }
});

async function finishAuthentication() {
  if (state.authenticated) return;
  state.authenticated = true;
  state.reconnectNeeded = Boolean(state.retryAction);
  byId("password").value = "";
  if (byId("login-dialog").open) byId("login-dialog").close();
  updateSessionStatus();
  const action = state.afterLogin;
  state.afterLogin = null;
  await refreshSessions();
  if (!state.authenticated) { action?.(false); return; }
  action?.(true);
  await consumeEditorIntent();
}

function renderCurrentRecording() {
  const manifest = state.activeManifest;
  const local = !manifest && (state.localContext || workingFiles().length ? state.localContext || localSourceContext(workingFiles()) : null);
  const heading = document.getElementById("current-recording-heading");
  const summary = document.getElementById("current-recording-state");
  const link = document.getElementById("current-recording-archive-link");
  const picker = byId("mode-archive");
  const workflowChoice = document.getElementById("workflow-choice");
  const card = document.getElementById("current-recording");
  const badge = document.getElementById("current-recording-badge");
  const facts = document.getElementById("current-recording-facts");
  const source = document.getElementById("current-recording-source");
  const tracks = document.getElementById("current-recording-tracks");
  const next = document.getElementById("current-recording-next");
  const pickerLabel = picker.querySelector(":scope > span:not(.source-choice__icon):not(.source-choice__action):not(.visually-hidden)");
  if (manifest) {
    heading.textContent = manifest.title;
    summary.textContent = `${formatDate(manifest.recordedAt)} · ${manifest.sourceTracks.length} дорожек · Сохранена в аудиоархиве`;
    link.href = `Audio-Archive.html?session=${encodeURIComponent(manifest.id)}`; link.hidden = false;
    pickerLabel.textContent = "Сменить запись";
    card.dataset.recordingState = "archive"; badge.textContent = "В аудиоархиве";
    source.textContent = manifest.sourceState === "available" ? "Аудиоархив · исходники доступны" : "Аудиоархив · исходники недоступны";
    tracks.textContent = `${manifest.sourceTracks.length}`;
    next.textContent = state.editorMode ? workflowLabel(state.editorMode) : "Выберите задачу";
    facts.hidden = false; workflowChoice.hidden = false;
  } else if (local) {
    heading.textContent = "Новая запись Zoom";
    summary.textContent = `${local.sourceTracks.length} дорожек · Только на этом устройстве`;
    link.removeAttribute("href"); link.hidden = true;
    pickerLabel.textContent = "Из аудиоархива";
    card.dataset.recordingState = "device"; badge.textContent = "На устройстве";
    source.textContent = "Локальные файлы · без сохранения в архив";
    tracks.textContent = `${local.sourceTracks.length}`;
    next.textContent = state.editorMode ? workflowLabel(state.editorMode) : "Выберите задачу";
    facts.hidden = false; workflowChoice.hidden = false;
  } else {
    heading.textContent = "Откуда взять запись?";
    summary.textContent = "Выберите сохранённую запись из аудиоархива или несколько синхронизированных дорожек с этого устройства.";
    link.removeAttribute("href"); link.hidden = true;
    pickerLabel.textContent = "Из аудиоархива";
    card.dataset.recordingState = "empty"; badge.textContent = "Не выбрана";
    facts.hidden = true; workflowChoice.hidden = true;
  }
}

function setMode(mode) {
  state.mode = mode;
  const archive = mode === "archive";
  byId("heading").textContent = archive ? "Выберите запись" : "Выберите аудиодорожки";
  byId("archive-panel").hidden = !archive;
  byId("device-panel").hidden = archive;
  document.getElementById("processor-device-field").hidden = archive;
  document.getElementById("processor-device-ingest-actions").hidden = archive;
  byId("mode-archive").setAttribute("aria-pressed", String(archive));
  byId("mode-device").setAttribute("aria-pressed", String(!archive));
  byId("mode-device").setAttribute("aria-expanded", String(!archive && document.getElementById("import-zone").open));
  updateSourceSaveState();
  renderCurrentRecording(); updatePublishState(); renderResultArchive(); void showIncomplete();
}

function setSourceLoading(visible, { title = "Открываем запись…", record = "Подготавливаем дорожки и проект.", progress = 0, step = "record" } = {}) {
  const overlay = document.getElementById("source-session-loading");
  if (!overlay) return;
  overlay.hidden = !visible;
  document.body.toggleAttribute("data-source-loading", visible);
  document.getElementById("source-session-loading-title").textContent = title;
  document.getElementById("source-session-loading-record").textContent = record;
  document.getElementById("source-session-loading-progress").value = progress;
  for (const item of overlay.querySelectorAll("[data-loading-step]")) {
    const order = ["record", "tracks", "files", "editor"];
    const itemIndex = order.indexOf(item.dataset.loadingStep);
    const activeIndex = order.indexOf(step);
    item.classList.toggle("is-complete", itemIndex < activeIndex);
    item.classList.toggle("is-active", itemIndex === activeIndex);
  }
}

function clearOutputPlayback() {
  const audio = byId("announcement-audio");
  audio.pause();
  audio.removeAttribute("src");
  audio.load();
  byId("announcement-download").removeAttribute("href");
  byId("announcement-download").removeAttribute("download");
  byId("announcement-playback").hidden = true;
  if (state.outputUrl) URL.revokeObjectURL(state.outputUrl);
  state.outputUrl = null;
}

function closeAnnouncementWorkspace(clearProcessor = false, { advanceGeneration = true } = {}) {
  if (advanceGeneration) state.sessionSequence++;
  if (clearProcessor) clearProcessorFiles();
  state.activeSession = null;
  state.activeManifest = null;
  state.announcementDraft = null;
  state.processorProvenance = [];
  state.candidate = null;
  byId("announcement-workspace").hidden = true;
  updatePublishState(); renderCurrentRecording(); renderResultArchive(); void showIncomplete();
}

function selectedTrackIds() {
  return state.processorProvenance.map((source) => source.trackId);
}

function renderAnnouncementWorkspace() {
  const session = state.activeManifest;
  byId("announcement-workspace").hidden = state.editorMode !== "announcement";
  byId("announcement-identity").textContent = session ? `${session.title} · ${formatDate(session.recordedAt)}` : "Дорожки на этом устройстве";
  byId("announcement-status").textContent = "Исходники → Обработать запись → Прослушать → Сохранить / Скачать";
  updatePublishState(); renderCurrentRecording(); renderResultArchive();
}
function scrollToElement(element) {
  element.scrollIntoView({
    block: "start",
    behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth",
  });
}
function leaveAnnouncementWorkspace() {
  state.editorMode = null;
  delete document.body.dataset.editing;
  document.getElementById("announcement-processor-card").hidden = true;
  byId("announcement-workspace").hidden = true;
  document.getElementById("active-editor-mode").textContent = "Запись готова. Выберите одну задачу.";
  renderCurrentRecording(); renderResultArchive(); void showIncomplete();
  document.getElementById("workflow-choice").focus({ preventScroll: true });
  scrollToElement(document.getElementById("workflow-choice"));
}
function activateMode(mode) {
  state.editorMode = mode;
  document.getElementById("import-zone").open = false;
  document.body.dataset.editing = mode;
  document.getElementById("announcement-processor-card").hidden = mode !== "announcement";
  byId("announcement-workspace").hidden = mode !== "announcement";
  document.getElementById("active-editor-mode").textContent = `Открыта задача: ${workflowLabel(mode)}`;
  const inactiveEditor = document.getElementById(mode === "speaker" ? "announcement-processor-card" : "speaker-editor");
  for (const audio of inactiveEditor.querySelectorAll("audio")) audio.pause();
  state.resultArchive = mode; renderAnnouncementWorkspace(); renderImportFiles(); void showIncomplete();
  const workspace = document.getElementById(mode === "speaker" ? "speaker-editor" : "announcement-processor-card");
  requestAnimationFrame(() => requestAnimationFrame(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
    workspace.focus?.({ preventScroll: true });
  }));
}

function updatePublishState() {
  const button = byId("publish-announcement");
  const reason = byId("publish-reason");
  if (!button || !reason) return;
  const session = state.activeManifest;
  let message = "";
  if (!session) message = "Сначала сохраните запись Zoom в аудиоархив, затем создайте результат для сохранённой записи.";
  else if (session.lifecycle.state !== "incoming") message = "Верните запись для обработки перед сохранением нового результата.";
  else if (session.sourceState !== "available") message = "Исходники этой записи недоступны.";
  else if (!state.candidate) message = "Сначала создайте локальный результат обработки.";
  else if (!state.candidate.sources.length) message = "Локальный файл без связи с архивной записью сохранить в этот архив нельзя.";
  else if (state.candidate.provenance?.sessionId !== session.id) message = "Локальный результат относится к другой записи.";
  else if (state.candidate.provenance?.sourceSessionRevision !== session.revision) message = "Запись или проект изменились после обработки; обработайте дорожки заново.";

  button.disabled = Boolean(message) || Boolean(state.publicationController);
  reason.textContent = message || "Результат готов к сохранению в архив «Анонс-мейкер».";
}

function button(label, action, className = "") {
  const element = document.createElement("button");
  element.type = "button";
  element.textContent = label;
  if (className) element.className = className;
  element.addEventListener("click", action);
  return element;
}

function onGatewayError(error, fallback, retry = null) {
  if (error?.status === 401) {
    state.authenticated = false; ++state.authSequence; state.reconnectNeeded = true; state.retryAction = retry;
    state.listsLoaded = false; state.projects.clear(); state.sessions = []; state.allSessions = []; renderSessions(); renderResultArchive();
    updateSessionStatus();
    setArchiveStatus(RECONNECT_MESSAGE);
    return;
  }
  setArchiveStatus(userError(error, fallback));
}

async function refreshSessions() {
  const sequence = ++state.refreshSequence, auth = state.authSequence;
  state.listsLoaded = false; state.projects.clear(); state.sessions = []; state.allSessions = []; renderSessions(); renderResultArchive();
  if (!state.authenticated) {
    state.sessions = [];
    state.allSessions = [];
    renderSessions();
    renderResultArchive();
    setArchiveStatus(RECONNECT_MESSAGE);
    return;
  }
  setArchiveStatus("Загрузка записей и сохранённых результатов…");
  try {
    const [incoming, archived] = await Promise.all([gateway.listSessions("incoming"), gateway.listSessions("archived")]);
    if (sequence !== state.refreshSequence || auth !== state.authSequence) return;
    state.allSessions = mergeSessions(incoming.sessions, archived.sessions);
    const projects = await Promise.allSettled(state.allSessions.filter(session => session.workflows.speaker.currentDraft).map(async session => {
      const result = await gateway.loadDraft(session.id, "speaker");
      return [session.id, projectProjection(session, result.draft)];
    }));
    if (sequence !== state.refreshSequence || auth !== state.authSequence) return;
    const failure = projects.find(result => result.status === 'rejected' && result.reason?.status === 401);
    if (failure) throw failure.reason;
    for (const result of projects) if (result.status === 'fulfilled') state.projects.set(...result.value);
    state.sessions = state.allSessions.filter(eligible); state.listsLoaded = true;
    renderSessions();
    renderResultArchive();
    await showIncomplete();
    if (sequence !== state.refreshSequence || auth !== state.authSequence) return;
    setArchiveStatus(state.sessions.length ? "" : "Нет записей, доступных для новой обработки. Все записи и управление ими доступны в Аудиоархиве.");
  } catch (error) {
    if (sequence !== state.refreshSequence || auth !== state.authSequence) return;
    state.sessions = [];
    state.allSessions = [];
    renderSessions();
    renderResultArchive();
    onGatewayError(error, "Не удалось загрузить исходные записи.");
  }
}

async function mutateSession(action) {
  try {
    setArchiveStatus("Сохранение изменений…");
    const result = await action();
    const updated = result?.session || result;
    if (updated?.id === speakerEditorSessionId() && (updated.lifecycle.state !== "incoming" || updated.sourceState !== "available")) {
      closeSpeakerEditor(true);
    }
    if (updated?.id && state.activeManifest?.id === updated.id) {
      state.activeSession = updated;
      state.activeManifest = updated;
      if (updated.lifecycle.state === "archived") {
        clearProcessorFiles();
        state.processorProvenance = [];
        state.candidate = null;
      }
      renderAnnouncementWorkspace();
    }
    await refreshSessions();
  } catch (error) {
    onGatewayError(error, "Не удалось сохранить изменения.");
  }
}

function newerSpeakerSession(prepared) {
  const active = getSpeakerSaveState().session;
  return active?.id === prepared.id && active.revision > prepared.revision ? active : null;
}
function adoptCurrentCanonicalBatch(session) {
  const files = getProcessorFiles();
  if (files.length !== session.sourceTracks.length || state.processorProvenance.length !== files.length) return null;
  const byTrack = new Map();
  for (const [index, source] of state.processorProvenance.entries()) {
    const track = session.sourceTracks.find(item => item.trackId === source.trackId);
    const file = files[index];
    if (!track || source.blobId !== track.blobId || source.sizeBytes !== track.sizeBytes || source.sha256 !== track.sha256 ||
        source.mediaType !== track.mediaType || file.size !== track.sizeBytes || file.type !== track.mediaType) return null;
    byTrack.set(track.trackId, file);
  }
  const ordered = session.sourceTracks.map(track => byTrack.get(track.trackId));
  if (ordered.some(file => !file)) return null;
  const fingerprint = remoteSourceFingerprint(session);
  return Object.freeze({ session, files: Object.freeze(ordered), fingerprint, readinessIdentity: `${session.id}:${fingerprint}` });
}
function beginContextSwitch(sessionId) {
  document.getElementById("speaker-project-recovery").hidden = true;
  state.speakerRecovery = null;
  const current = state.activeManifest?.id || speakerEditorSessionId();
  if (current === sessionId) return;
  ++state.incompleteSequence; byId("recovery-list").replaceChildren(); byId("recovery-list").hidden = true;
}

async function loadSession(session) {
  if (state.publicationController || state.uploadController) return;
  beginContextSwitch(session.id);
  const sequence = ++state.sessionSequence, auth = state.authSequence;
  const current = () => sequence === state.sessionSequence && auth === state.authSequence;
  setArchiveStatus(session.lifecycle.state === "archived" ? "Открытие записи, убранной из рабочего списка…" : "Загрузка и проверка исходных дорожек…");
  try {
    // Prepare in local variables. A failed/expired load must not clear the active editor or its Blob URLs.
    const complete = await gateway.getSession(session.id);
    if (!current()) return;
    const draft = (await gateway.loadDraft(session.id, "announcement")).draft;
    if (!current()) return;
    if (draft && draft.payloadSchema !== "announcement/v1") throw new Error("Неподдерживаемые сохранённые настройки; они не будут перезаписаны.");
    const order = draft?.payload?.trackIds || complete.sourceTracks.map((track) => track.trackId);
    const tracksById = new Map(complete.sourceTracks.map((track) => [track.trackId, track]));
    if (order.some((id) => !tracksById.has(id))) throw new Error("Проект обработки ссылается на отсутствующую дорожку.");
    const selectedTracks = order.map((id) => tracksById.get(id));
    const provenance = selectedTracks.map((track, index) => ({ trackId: track.trackId, blobId: track.blobId,
      ordinal: index + 1, sizeBytes: track.sizeBytes, sha256: track.sha256, mediaType: track.mediaType }));
    const available = complete.lifecycle.state === "incoming" && complete.sourceState === "available";
    let files = [];
    if (available) {
      const batch = state.preparedBatch?.session.id === complete.id ? state.preparedBatch : adoptCurrentCanonicalBatch(complete);
      if (!batch || batch.session.id !== complete.id || remoteSourceFingerprint(complete) !== batch.fingerprint) {
        throw new Error("Исходники записи изменились. Выберите запись заново для полной проверки.");
      }
      const filesById = new Map(batch.session.sourceTracks.map((track, index) => [track.trackId, batch.files[index]]));
      files = order.map((id) => filesById.get(id));
      state.preparedBatch = Object.freeze({ ...batch, session: complete });
    }
    // Check the latest montage only when the replacement is ready, and fence the dialog/save completion too.
    if (!current()) return;
    if (!await closeSpeakerEditor(false, () => current() && !newerSpeakerSession(complete))) {
      // Save-and-continue can advance this very source while the confirmation is open.
      // Fetch its new lineage before replacing the current editor.
      const newer = newerSpeakerSession(complete);
      if (current() && newer) return loadSession(newer);
      return;
    }
    if (!current()) return;
    ++state.outputSequence; clearOutputPlayback();
    const previousProvenance = state.processorProvenance;
    state.activeSession = complete;
    state.activeManifest = complete;
    state.announcementDraft = draft;
    state.processorProvenance = provenance;
    state.candidate = null;
    activateMode("announcement");
    if (available) {
      state.loadingArchive = true;
      const currentFiles = getProcessorFiles();
      const sameFiles = currentFiles.length === files.length && currentFiles.every((file, index) => file === files[index]);
      if (sameFiles) {
        await bindProcessorSources(files, provenance, { sessionId: complete.id, sourceSessionRevision: complete.revision });
      } else {
        if (currentFiles.length && previousProvenance.length === currentFiles.length) {
          await bindProcessorSources(currentFiles, previousProvenance, { sessionId: complete.id, sourceSessionRevision: complete.revision });
        }
        loadProcessorFiles(files, provenance, { sessionId: complete.id, sourceSessionRevision: complete.revision });
      }
      state.loadingArchive = false;
      setArchiveStatus(`Загружено дорожек: ${files.length}. Целостность исходников проверена; запись не изменена.`);
      scrollToElement(document.getElementById("processor-heading"));
    } else {
      state.loadingArchive = true;
      clearProcessorFiles();
      state.loadingArchive = false;
      state.processorProvenance = [];
      state.candidate = null;
      setArchiveStatus(complete.lifecycle.state === "archived" ? "Запись убрана из рабочего списка. Верните её для обработки." :
        "Исходники удалены; доступны сохранённые результаты и метаданные.");
      scrollToElement(byId("announcement-workspace"));
    }
  } catch (error) {
    if (!current()) return;
    state.loadingArchive = false;
    onGatewayError(error, `Не удалось восстановить исходные дорожки. ${error?.message || ""}`, () => { if (sequence === state.sessionSequence) return loadSession(session); });
  }
}

function projectSourcesMatchSession(sources, session) {
  return Array.isArray(sources) && sources.length === session.sourceTracks.length && sources.every((source) => {
    const track = session.sourceTracks.find((item) => item.trackId === source.trackId);
    return track && source.trackId === track.trackId && source.blobId === track.blobId && source.ordinal === track.ordinal &&
      source.originalName === track.originalName && source.mediaType === track.mediaType && source.sizeBytes === track.sizeBytes && source.sha256 === track.sha256;
  });
}

async function resolveSpeakerWork(session, intent = {}) {
  const loaded = await gateway.loadDraft(session.id, "speaker");
  const draft = loaded.draft;
  if (intent.projectRevision) {
    const selected = await gateway.speakerProjectState(session.id, intent.projectRevision);
    return { draft, initialPayload: selected.payload, sources: selected.sources, continuation: { sourceDraftRevision: selected.draftRevision, sourceOutputId: null } };
  }
  if (intent.speakerOutput) {
    const metadata = await gateway.getSpeakerOutput(session.id, intent.speakerOutput);
    if (!validateSpeakerOutput(metadata.output, metadata.recipe, session.id)) throw new Error("Происхождение финальной версии не подтверждено.");
    if (metadata.recipe.schemaVersion === 2) {
      const selected = await gateway.speakerProjectState(session.id, metadata.recipe.projectState.draftRevision);
      if (selected.stateFingerprint !== metadata.recipe.projectState.stateFingerprint) throw new Error("Final не совпадает с состоянием проекта.");
      return { draft, initialPayload: selected.payload, sources: selected.sources, continuation: { sourceDraftRevision: null, sourceOutputId: intent.speakerOutput } };
    }
    const sources = metadata.recipe.sources.map(({ trackId, blobId, ordinal, originalFilename: originalName, mediaType, sizeBytes, sha256 }) =>
      ({ trackId, blobId, ordinal, originalName, mediaType, sizeBytes, sha256 }));
    return { draft, initialPayload: metadata.recipe.draft.payload, sources, continuation: { sourceDraftRevision: null, sourceOutputId: intent.speakerOutput } };
  }
  let projectState = null;
  if (draft?.draftRevision && gateway.speakerProjectHistoryVersion === 1) {
    try { projectState = await gateway.speakerProjectState(session.id, draft.draftRevision); }
    catch (error) { if (error?.status !== 404) throw error; }
  }
  return { draft, initialPayload: null, projectState, sources: projectState?.sources || null,
    continuation: draft?.draftRevision ? { sourceDraftRevision: draft.draftRevision, sourceOutputId: null } : null };
}

function showSpeakerRecovery(session, work) {
  state.speakerRecovery = createSpeakerRecoveryAttempt(session, work);
  const panel = document.getElementById("speaker-project-recovery"); panel.hidden = false;
  document.getElementById("speaker-project-recovery-status").textContent = session.lifecycle.state !== "incoming" ?
    "Запись убрана из рабочего списка. Сначала верните её в обработку." : "Проект сохранён, но исходные дорожки недоступны.";
  for (const id of ["speaker-project-recovery-ingest", "speaker-project-recovery-continue"]) document.getElementById(id).hidden = true;
  panel.scrollIntoView({ block: "nearest" });
}

async function renderSpeakerProjectHistory(session, sequence, auth) {
  const disclosure = speakerId("project-history"), list = speakerId("project-history-list");
  disclosure.hidden = false;
  if (gateway.speakerProjectHistoryVersion !== 1) {
    list.replaceChildren(document.createTextNode("Версия шлюза несовместима с историей проекта. Локальная работа и скачивание результата доступны; архивные изменения «Спикерская» заблокированы."));
    return;
  }
  list.replaceChildren(document.createTextNode("Загрузка истории…"));
  try {
    const history = await gateway.speakerProjectHistory(session.id);
    if (sequence !== state.sessionSequence || auth !== state.authSequence || speakerEditorSessionId() !== session.id) return;
    list.replaceChildren();
    if (!history.states?.length) { list.append(document.createTextNode("Явных сохранений в истории пока нет.")); return; }
    for (const saved of history.states) {
      const row = document.createElement("article"); row.className = "archive-card project-state-row";
      const heading = document.createElement("h3"); heading.textContent = `Состояние ${saved.draftRevision}${saved.current ? " · текущее" : ""}`;
      const meta = document.createElement("p"); meta.textContent = `${formatDate(saved.savedAt)} · ${saved.canonicalSourcesAvailable ? "исходники доступны" : "исходники недоступны"}`;
      const finals = document.createElement("p"); finals.textContent = saved.finalVersions?.length ?
        `Связанные финальные версии: ${saved.finalVersions.map(item => item.version).join(", ")}` : "Связанных финальных версий нет.";
      const resume = button("Продолжить с этого состояния", () => loadSpeakerSession(session, { projectRevision: saved.draftRevision }));
      row.append(heading, meta, finals, resume); list.append(row);
    }
  } catch (error) {
    if (sequence === state.sessionSequence && auth === state.authSequence) list.replaceChildren(document.createTextNode("История проекта не прошла проверку и недоступна."));
  }
}

async function loadSpeakerSession(session, intent = {}) {
  if (state.publicationController || state.uploadController) return;
  beginContextSwitch(session.id);
  const sequence = ++state.sessionSequence, auth = state.authSequence;
  setArchiveStatus("Загрузка состояния проекта и проверка исходников для «Спикерская»…");
  try {
    const complete = await gateway.getSession(session.id);
    if (sequence !== state.sessionSequence || auth !== state.authSequence) return;
    const work = await resolveSpeakerWork(complete, intent);
    if (sequence !== state.sessionSequence || auth !== state.authSequence) return;
    if (complete.lifecycle.state !== "incoming" || complete.sourceState !== "available") {
      if (work.sources?.length && work.continuation) showSpeakerRecovery(complete, work);
      else setArchiveStatus("Проект сохранён, но исходные дорожки недоступны.");
      return;
    }
    if (work.sources && !projectSourcesMatchSession(work.sources, complete)) throw new Error("Происхождение состояния не совпадает с каноническими исходниками.");
    const batch = state.preparedBatch?.session.id === complete.id ? state.preparedBatch : adoptCurrentCanonicalBatch(complete);
    if (!batch || batch.session.id !== complete.id || remoteSourceFingerprint(complete) !== batch.fingerprint) {
      throw new Error("Исходники записи изменились. Выберите запись заново для полной проверки.");
    }
    const files = batch.files;
    state.preparedBatch = Object.freeze({ ...batch, session: complete });
    if (sequence !== state.sessionSequence || auth !== state.authSequence) return;
    const project = new ProjectSave(gateway);
    // A revision refresh of this exact loaded batch is not a competing source intent.
    const ownsSources = () => {
      const work = getSpeakerSaveState();
      return work.session?.id === complete.id && work.files.length === files.length &&
        work.files.every((file, index) => file === files[index]);
    };
    const opened = await openSpeakerEditor({
      session: complete,
      files,
      draft: work.draft,
      projectState: work.projectState,
      initialPayload: work.initialPayload,
      isCurrent: () => sequence === state.sessionSequence && auth === state.authSequence && (!newerSpeakerSession(complete) || ownsSources()),
      saveDraft: ({ session, draft, payload, signal, forceLatest }) => withReconnect(() => forceLatest ? project.saveAsLatest(session, draft, payload, signal) : project.save(session, draft, payload, signal)),
      loadProjectState: async ({ session: latest, draft: latestDraft, signal }) => {
        return gateway.speakerProjectState(latest.id, latestDraft.draftRevision, signal);
      },
      onSaved: ({ session: updated }) => {
        state.activeSession = updated; state.activeManifest = updated;
        const index = state.sessions.findIndex((item) => item.id === updated.id);
        if (index >= 0) state.sessions[index] = updated;
        const allIndex = state.allSessions.findIndex((item) => item.id === updated.id);
        if (allIndex >= 0) state.allSessions[allIndex] = updated;
        renderSessions();
      }
    });
    if (sequence !== state.sessionSequence || auth !== state.authSequence) return;
    const newer = newerSpeakerSession(complete);
    if (!opened && newer && !ownsSources()) return loadSpeakerSession(newer, intent);
    if (opened) {
      ++state.outputSequence; clearOutputPlayback();
      closeAnnouncementWorkspace(false);
      state.activeManifest = getSpeakerSaveState().session;
      activateMode("speaker");
      await renderSpeakerProjectHistory(getSpeakerSaveState().session, sequence, auth);
    }
    setArchiveStatus(opened ? `${work.initialPayload ? "Предыдущее состояние открыто как локальные несохранённые изменения" : "Открыта работа «Спикерская»"}: ${complete.title}. Все исходники проверены.` : "Не удалось подготовить исходники для «Спикерская».");
  } catch (error) {
    if (sequence !== state.sessionSequence || auth !== state.authSequence) return;
    onGatewayError(error, "Не удалось открыть запись в «Спикерская».", () => { if (sequence === state.sessionSequence) return loadSpeakerSession(session, intent); });
  }
}

function speakerSaveReason(snapshot = getSpeakerSaveState()) {
  const { session, draft, projectState, payload, candidate, saving } = snapshot;
  if (!session) return "Откройте финальную обработку спикерской.";
  if (session.kind === "local") return "Сохраните проект вместе с исходниками, затем создайте финальную версию заново.";
  if (gateway.speakerProjectHistoryVersion !== 1) return "Версия шлюза несовместима с сохранением «Спикерская». Локальный монтаж и скачивание MP3 доступны; файлы и результат сохранены в этой вкладке.";
  if (candidate?.candidateType === "local-speaker") return "Создайте финальную версию заново для сохранения в аудиоархив.";
  if (session.lifecycle.state !== "incoming") return "Верните запись для обработки перед сохранением новой версии.";
  if (session.sourceState !== "available") return "Исходники этой записи недоступны.";
  if (saving) return "Идёт сохранение текущего локального результата.";
  if (!candidate) return "Сначала соберите и проверьте локальный MP3.";
  if (!draft || draft.draftRevision < 1) return "Сохраните текущий проект обработки перед сохранением результата.";
  if (!projectState || projectState.sessionId !== session.id ||
      projectState.draftRevision !== draft.draftRevision || projectState.sourceSessionRevision !== session.revision) return "Сохраните текущий проект, чтобы создать точное неизменяемое состояние перед финальной версией.";
  if (candidate.sessionId !== session.id) return "Локальный результат относится к другой записи.";
  if (candidate.sourceSessionRevision !== session.revision || candidate.draftRevision !== draft.draftRevision) return "Запись или проект изменились после локальной сборки. Соберите результат заново.";
  if (JSON.stringify(candidate.payload) !== JSON.stringify(payload) || JSON.stringify(draft.payload) !== JSON.stringify(payload)) return "Текущий проект не совпадает с локальным результатом. Сохраните проект и соберите MP3 заново.";
  if (candidate.mediaType !== "audio/mpeg" || !(candidate.blob instanceof Blob) || candidate.blob.size !== candidate.sizeBytes || !candidate.sizeBytes) return "Локальный MP3 повреждён. Соберите результат заново.";
  const sourcesMatch = candidate.sources.length === session.sourceTracks.length && candidate.sources.every((source) => {
    const track = session.sourceTracks.find((item) => item.trackId === source.trackId);
    return track && source.blobId === track.blobId && source.ordinal === track.ordinal &&
      source.originalFilename === track.originalName && source.mediaType === track.mediaType && source.sizeBytes === track.sizeBytes && source.sha256 === track.sha256;
  });
  return sourcesMatch ? "" : "Состав или целостность исходников изменились. Откройте запись заново.";
}

function updateSpeakerSaveState(snapshot = getSpeakerSaveState()) {
  updateSourceSaveState(); renderCurrentRecording(); renderResultArchive();
  const save = speakerId("archive-save");
  const reason = speakerId("archive-unavailable");
  if (!save || !reason) return;
  const message = speakerSaveReason(snapshot);
  save.disabled = Boolean(message);
  reason.textContent = message || "Результат готов к сохранению в архив «Спикерская».";
}

function speakerRecipe(candidate, draft, projectState = null) {
  const payload = structuredClone(candidate.payload);
  return {
    schemaVersion: 2, projectState: {
      sessionId: projectState.sessionId, draftRevision: projectState.draftRevision, stateFingerprint: projectState.stateFingerprint
    },
    renderedAt: candidate.renderedAt,
    sourceSessionRevision: candidate.sourceSessionRevision,
    draft: { revision: draft.draftRevision, payloadSchema: "speaker/v1", payload },
    sources: structuredClone(candidate.sources),
    editState: {
      orderedTrackIds: [...payload.trackIds],
      includedTrackIds: [...candidate.includedTrackIds],
      excludedTrackIds: [...payload.excludedTrackIds],
      globalCuts: structuredClone(payload.globalCuts),
      trackSilenceRegions: structuredClone(payload.trackSilenceRegions),
      trackProcessing: structuredClone(payload.trackProcessing)
    },
    renderer: structuredClone(candidate.renderer),
    candidateFingerprint: candidate.candidateFingerprint,
    result: {
      mediaType: candidate.mediaType,
      presentationFilename: candidate.presentationFilename,
      sizeBytes: candidate.sizeBytes,
      sha256: candidate.sha256,
      originalDurationSeconds: candidate.originalDurationSeconds,
      resultDurationSeconds: candidate.resultDurationSeconds,
      globallyRemovedDurationSeconds: candidate.globallyRemovedDurationSeconds
    }
  };
}

function openSpeakerSaveDialog() {
  const snapshot = getSpeakerSaveState();
  updateSpeakerSaveState(snapshot);
  if (speakerId("archive-save").disabled) return;
  state.speakerSaveSnapshot = { session: snapshot.session, draft: snapshot.draft, projectState: snapshot.projectState, candidate: snapshot.candidate };
  state.speakerSaveKey = crypto.randomUUID();
  speakerId("save-source").textContent = `${snapshot.session.title} · ${formatDate(snapshot.session.recordedAt)}`;
  speakerId("save-result").textContent = `${snapshot.candidate.presentationFilename} · MP3 · ${formatBytes(snapshot.candidate.sizeBytes)}`;
  speakerId("save-version").textContent = `Следующая версия будет зарезервирована сервером (сейчас ожидается Версия ${snapshot.session.workflows.speaker.nextVersion})`;
  speakerId("save-status").textContent = "Проверьте запись и локальный результат.";
  speakerId("save-progress").hidden = true;
  speakerId("save-submit").disabled = false;
  speakerId("save-cancel").textContent = "Отмена";
  speakerId("save-dialog").showModal();
}

async function submitSpeakerSave(event) {
  event.preventDefault();
  const snapshot = state.speakerSaveSnapshot;
  if (!snapshot || speakerSaveReason({ ...getSpeakerSaveState(), ...snapshot })) {
    speakerId("save-status").textContent = "Состояние результата изменилось. Закройте подтверждение и проверьте причину рядом с кнопкой сохранения.";
    return;
  }
  const immutable = { session: structuredClone(snapshot.session), draft: structuredClone(snapshot.draft),
    candidate: { ...structuredClone({ ...snapshot.candidate, blob: null }), blob: snapshot.candidate.blob } };
  state.speakerSaveController = new AbortController();
  state.speakerSaveTransactionId = null;
  setSpeakerSaveLocked(true);
  speakerId("save-submit").disabled = true;
  speakerId("save-cancel").textContent = "Отменить передачу";
  speakerId("save-progress").hidden = false;
  speakerId("save-progress").value = 0;
  let completed = false;
  try {
    const phaseText = { preparing: "Подготовка точных частей результата…", reserving: "Резервирование версии…",
      uploading: "Передача частей…", verifying: "Проверка целостности и финализация…", saved: "Сохранено." };
    const result = await gateway.saveSpeaker({
      sessionId: immutable.session.id,
      expectedRevision: immutable.session.revision,
      expectedDraftRevision: immutable.draft.draftRevision,
      blob: immutable.candidate.blob,
      recipe: speakerRecipe(immutable.candidate, immutable.draft, snapshot.projectState),
      idempotencyKey: state.speakerSaveKey,
      signal: state.speakerSaveController.signal,
      onPhase: (phase) => { speakerId("save-status").textContent = phaseText[phase]; },
      onStarted: (job) => {
        state.speakerSaveTransactionId = job.transactionId;
        speakerId("save-version").textContent = `Версия ${job.reservedVersion}`;
      },
      onProgress: ({ uploadedBytes, totalBytes, uploadedParts, totalParts, reservedVersion }) => {
        speakerId("save-progress").value = Math.min(95, Math.round(uploadedBytes / totalBytes * 100));
        speakerId("save-status").textContent = `Версия ${reservedVersion}: передано частей ${uploadedParts} из ${totalParts}.`;
      }
    });
    speakerId("save-progress").value = 100;
    speakerId("save-status").textContent = `Версия ${result.output.version} сохранена в архиве «Спикерская».`;
    const updated = await gateway.getSession(immutable.session.id);
    updateSpeakerSession(updated);
    state.speakerSaveKey = null;
    state.speakerSaveTransactionId = null;
    completed = true;
    await refreshSessions();
    setTimeout(() => speakerId("save-dialog").close(), 600);
  } catch (error) {
    const transactionId = state.speakerSaveTransactionId;
    if (error?.name === "AbortError" && transactionId) {
      try { await gateway.cancelSpeakerSave(transactionId); } catch { /* authoritative read below */ }
    }
    const authoritative = transactionId ? await reconcileSpeakerSave(transactionId, immutable.session.id) : { known: false };
    if (authoritative.finalized) {
      speakerId("save-progress").value = 100;
      speakerId("save-status").textContent = `Версия ${authoritative.job.reservedVersion} сохранена в архиве «Спикерская».`;
      state.speakerSaveKey = null;
      state.speakerSaveTransactionId = null;
      completed = true;
      setTimeout(() => speakerId("save-dialog").close(), 600);
    } else if (!transactionId) {
      speakerId("save-status").textContent = error?.name === "AbortError" ?
        "Передача остановлена до подтверждённого резервирования версии." :
        `${userError(error, "Не удалось начать сохранение.")} Сервер не подтвердил резервирование версии.`;
    } else if (authoritative.known) {
      speakerId("save-status").textContent = error?.name === "AbortError" ?
        `Передача Версии ${authoritative.job.reservedVersion} остановлена. Она доступна для продолжения или явного удаления.` :
        `${userError(error, "Не удалось завершить сохранение.")} Версия ${authoritative.job.reservedVersion} доступна для безопасного восстановления.`;
    } else {
      speakerId("save-status").textContent = "Состояние сохранения пока неизвестно. Проверьте незавершённые сохранения перед повтором.";
    }
  } finally {
    state.speakerSaveController = null;
    state.speakerSaveSnapshot = completed ? null : immutable;
    setSpeakerSaveLocked(false);
    speakerId("save-submit").disabled = completed;
    speakerId("save-cancel").disabled = false;
    speakerId("save-cancel").textContent = "Закрыть";
    updateSpeakerSaveState();
  }
}

async function cancelSpeakerSaveDialog() {
  if (state.speakerSaveController) {
    state.speakerSaveController.abort();
    speakerId("save-cancel").disabled = true;
    speakerId("save-status").textContent = "Останавливаем передачу и проверяем состояние на сервере…";
    return;
  }
  speakerId("save-dialog").close();
}

async function reconcileSpeakerSave(transactionId, sessionId) {
  try {
    const job = await gateway.speakerSaveJob(transactionId);
    if (job.state === "finalized") {
      const updated = await gateway.getSession(sessionId);
      updateSpeakerSession(updated);
      await refreshSessions();
      return { known: true, finalized: true, job };
    }
    await showIncomplete();
    return { known: true, finalized: false, job };
  } catch {
    await showIncomplete();
    return { known: false, finalized: false, job: null };
  }
}

async function openArchivedOutput(session, output, workflow = "announcement", downloadOnly = false) {
  const sequence = ++state.outputSequence, auth = state.authSequence, currentSessionId = state.activeManifest?.id;
  try {
    byId("results-status").textContent = "Загрузка и проверка сохранённого результата…";
    const metadata = workflow === "speaker" ? await gateway.getSpeakerOutput(session.id, output.outputId) : await gateway.getAnnouncementOutput(session.id, output.outputId);
    const file = workflow === "speaker" ? await reconstructSpeakerOutput(metadata, gateway.speakerPartFetch(metadata)) :
      await reconstructAnnouncementOutput(metadata, gateway.announcementPartFetch(metadata));
    if (sequence !== state.outputSequence || auth !== state.authSequence || state.resultArchive !== workflow || state.activeManifest?.id !== currentSessionId || currentSessionId !== session.id) return;
    if (state.outputUrl) URL.revokeObjectURL(state.outputUrl);
    state.outputUrl = URL.createObjectURL(file);
    const link = byId("announcement-download");
    link.href = state.outputUrl;
    link.download = file.name;
    byId("announcement-playback-label").textContent = `Прослушивание · ${workflowLabel(workflow)}`;
    byId("announcement-playback-name").textContent = `${session.title} · Версия ${output.version} · ${file.name} · ${formatBytes(file.size)}`;
    byId("announcement-audio").src = state.outputUrl;
    byId("announcement-playback").hidden = false;
    byId("results-status").textContent = "Файл проверен и готов к воспроизведению.";
    if (downloadOnly) link.click();
  } catch (error) {
    if (sequence === state.outputSequence && auth === state.authSequence) {
      if (error.status === 401) onGatewayError(error, RECONNECT_MESSAGE, async () => {
        if (sequence !== state.outputSequence || state.resultArchive !== workflow || state.activeManifest?.id !== currentSessionId) return;
        const fresh = await gateway.getSession(session.id);
        const target = fresh.workflows[workflow].outputs.find(item => item.outputId === output.outputId && item.sha256 === output.sha256 && item.version === output.version);
        if (!target) throw Object.assign(new Error("Результат больше не доступен"), { status: 404 });
        return openArchivedOutput(fresh, target, workflow, downloadOnly);
      });
      clearOutputPlayback();
      byId("results-status").textContent = userError(error, "Не удалось проверить и открыть сохранённый результат.");
    }
  }
}

function setResultArchive(name) {
  if (!new Set(["announcement", "speaker"]).has(name)) return;
  state.resultArchive = name;
  state.outputSequence++;
  clearOutputPlayback();
  byId("results-announcement").setAttribute("aria-pressed", String(name === "announcement"));
  byId("results-speaker").setAttribute("aria-pressed", String(name === "speaker"));
  byId("results-announcement-panel").hidden = name !== "announcement";
  byId("results-speaker-panel").hidden = name !== "speaker";
  renderResultArchive();
}

function resultArchiveItem(session, workflowName, output) {
  const item = document.createElement("article");
  item.className = "result-archive-item";
  const details = document.createElement("div");
  details.className = "result-archive-item__details";
  const heading = document.createElement("h4");
  heading.textContent = `Версия ${output.version}`;
  const metadata = document.createElement("p");
  metadata.className = "result-archive-item__metadata";
  metadata.textContent = `${formatDate(output.createdAt)} · ${formatBytes(output.sizeBytes)}`;
  details.append(heading, metadata);
  const actions = document.createElement("div");
  actions.className = "result-archive-item__actions";
  actions.append(button("Прослушать", () => openArchivedOutput(session, output, workflowName)));
  actions.append(button("Скачать", () => openArchivedOutput(session, output, workflowName, true)));
  item.append(details, actions);
  return item;
}

function renderResultArchive() {
  const membership = { announcement: [], speaker: [] };
  const current = state.activeManifest && state.allSessions.find(session => session.id === state.activeManifest.id);
  for (const session of current ? [current] : []) {
    for (const name of Object.keys(membership)) {
      const workflow = session.workflows?.[name];
      if (!workflow || workflow.workflow !== name || !Array.isArray(workflow.outputs)) continue;
      for (const output of workflow.outputs) {
        if (!output || output.sessionId !== session.id || typeof output.outputId !== "string") continue;
        membership[name].push({ session, output });
      }
    }
  }
  byId("results").hidden = !current || !state.editorMode;
  if (state.editorMode && state.resultArchive !== state.editorMode) state.resultArchive = state.editorMode;
  byId("results-announcement-panel").hidden = state.resultArchive !== "announcement";
  byId("results-speaker-panel").hidden = state.resultArchive !== "speaker";
  for (const name of Object.keys(membership)) {
    const unique = new Map(membership[name].map((entry) => [`${entry.session.id}:${entry.output.outputId}`, entry]));
    membership[name] = [...unique.values()].sort((left, right) => String(right.output.createdAt).localeCompare(String(left.output.createdAt)));
    byId(`results-${name}-count`).textContent = state.listsLoaded ? String(membership[name].length) : "—";
    const list = byId(`results-${name}-list`);
    list.replaceChildren();
    if (!membership[name].length) {
      const empty = document.createElement("p");
      empty.textContent = state.listsLoaded ? "Сохранённых результатов пока нет." : "Результаты не загружены.";
      list.append(empty);
    } else {
      for (const { session, output } of membership[name]) list.append(resultArchiveItem(session, name, output));
    }
  }
  if (!baseUrl) byId("results-status").textContent = "Архив результатов ещё не настроен.";
  else if (!state.authenticated) byId("results-status").textContent = "Подключите архив, чтобы увидеть сохранённые результаты.";
  else if (!current) byId("results-status").textContent = "Для локальной записи сохранённых версий нет.";
  else byId("results-status").textContent = `${current.title} · ${workflowLabel(state.resultArchive)}.`;
}

function renderSessions() {
  const list = byId("list");
  list.replaceChildren();
  byId("pagination").hidden = true;
  if (!state.picker.requested) {
    byId("count").hidden = false; byId("count").textContent = "Список появится после поиска."; return;
  }
  const form = byId("filters").elements, query = form.search.value.trim().toLocaleLowerCase("ru");
  const month = form.month.value;
  const matches = state.sessions.filter(session => (!query || session.title.toLocaleLowerCase("ru").includes(query) ||
    session.sourceTracks.some(track => track.originalName.toLocaleLowerCase("ru").includes(query))) &&
    (!month || String(session.recordedAt || "").slice(0, 7) === month));
  const pages = Math.max(1, Math.ceil(matches.length / state.picker.pageSize));
  state.picker.page = Math.min(state.picker.page, pages - 1);
  const start = state.picker.page * state.picker.pageSize, visible = pageItems(matches, state.picker.page, state.picker.pageSize);
  byId("count").hidden = false;
  byId("count").textContent = matches.length ? `Найдено: ${matches.length} · ${start + 1}–${start + visible.length}` : "Ничего не найдено. Измените запрос.";
  for (const session of visible) {
    const card = document.createElement("article");
    card.className = "source-session-item"; card.dataset.sessionId = session.id;
    const heading = document.createElement("h3");
    heading.textContent = session.title;
    const metadata = document.createElement("p");
    metadata.className = "source-session-metadata";
    metadata.textContent = `${formatDate(session.recordedAt)} · ${session.sourceTracks.length} дорожек · Исходники доступны`;
    const body = document.createElement("div");
    body.className = "source-session-item__body";
    const summary = document.createElement("div");
    summary.className = "source-session-item__summary";
    const actions = document.createElement("div");
    actions.className = "source-session-actions";
    const open = button("Выбрать", () => selectSessionContext(session), "action-primary");
    open.disabled = !eligible(session); actions.append(open);
    summary.append(heading, metadata);
    body.append(summary, actions);
    card.append(body);
    list.append(card);
  }
  if (matches.length > state.picker.pageSize) {
    byId("pagination").hidden = false; byId("page").textContent = `${state.picker.page + 1} из ${pages}`;
    byId("prev").disabled = state.picker.page === 0; byId("next").disabled = state.picker.page + 1 >= pages;
  }
}

async function selectSessionContext(session, { workflow = null, intent = {} } = {}) {
  if (state.publicationController || state.uploadController || state.speakerSaveController || state.speakerResumeController) return;
  state.preparationController?.abort();
  const controller = new AbortController();
  state.preparationController = controller;
  const sequence = ++state.sessionSequence, auth = state.authSequence;
  const current = () => state.preparationController === controller && sequence === state.sessionSequence && auth === state.authSequence && !controller.signal.aborted;
  setSourceLoading(true, { record: session.title, progress: 0, step: "record" });
  setArchiveStatus("Загрузка и проверка выбранной записи…");
  try {
    const batch = await prepareRemoteSourceBatch({ gateway, sessionId: session.id, signal: controller.signal, onProgress: progress => {
      if (!current()) return;
      const percent = progress.totalBytes ? Math.floor(progress.verifiedBytes / progress.totalBytes * 100) : 0;
      setSourceLoading(true, { record: `${session.title} · дорожка ${progress.trackIndex}/${progress.trackCount}, часть ${progress.partNumber}/${progress.trackPartCount}`, progress: percent, step: percent === 100 ? "files" : "tracks" });
      setArchiveStatus(`Проверено ${formatBytes(progress.verifiedBytes)} из ${formatBytes(progress.totalBytes)} · частей ${progress.verifiedParts}/${progress.totalParts}.`);
    } });
    if (!current()) return;
    setSourceLoading(true, { record: batch.session.title, progress: 100, step: "editor" });
    const replacingCurrent = !getSpeakerSaveState().session && workingFiles().length && state.activeManifest?.id !== batch.session.id;
    if (replacingCurrent && !globalThis.confirm("Заменить текущие исходники проверенной записью из аудиоархива? Несохранённый локальный результат будет потерян.")) return;
    if (!current()) return;
    if (!await closeSpeakerEditor(false, current)) return;
    if (!current()) return;
    state.loadingArchive = true;
    closeAnnouncementWorkspace(true, { advanceGeneration: false });
    state.loadingArchive = false;
    if (!current()) return;
    const provenance = batch.session.sourceTracks.map(track => ({ trackId: track.trackId, blobId: track.blobId,
      ordinal: track.ordinal, sizeBytes: track.sizeBytes, sha256: track.sha256, mediaType: track.mediaType }));
    state.preparedBatch = batch;
    state.activeSession = batch.session; state.activeManifest = batch.session; state.editorMode = null; delete document.body.dataset.editing;
    document.getElementById("import-zone").open = false; document.getElementById("import-zone").hidden = true;
    state.processorProvenance = provenance; state.candidate = null;
    renderCurrentRecording(); renderResultArchive(); renderSessions();
    setArchiveStatus(`Запись готова: ${batch.session.title}. Все исходники скачаны и проверены.`);
    state.preparationController = null;
    setSourceLoading(false);
    await showIncomplete();
    if (sequence !== state.sessionSequence || auth !== state.authSequence) return;
    if (workflow === "speaker") await loadSpeakerSession(batch.session, intent);
    else if (workflow === "announcement") await loadSession(batch.session);
  } catch (error) {
    if (current() || (!controller.signal.aborted && sequence === state.sessionSequence && auth === state.authSequence)) {
      onGatewayError(error, "Не удалось загрузить и проверить выбранную запись.", () => selectSessionContext(session, { workflow, intent }));
    }
  } finally {
    if (state.preparationController === controller) {
      state.preparationController = null;
      setSourceLoading(false);
    }
  }
}

async function ensureAuthenticated(action = async () => {}) {
  if (state.authenticated) return action();
  const connected = await new Promise(resolve => {
    if (state.afterLogin) { resolve(false); return; }
    state.afterLogin = resolve;
    byId("login-status").textContent = RECONNECT_MESSAGE;
    byId("password").value = "";
    byId("login-dialog").showModal(); byId("password").focus();
  });
  if (!connected) throw new DOMException("cancelled", "AbortError");
  return action();
}
async function withReconnect(action) {
  await ensureAuthenticated();
  try { return await action(); }
  catch (error) {
    if (error.status !== 401) throw error;
    state.authenticated = false; updateSessionStatus();
    await ensureAuthenticated();
    return action(); // One retry only; the action revalidates revisions and its retained transaction.
  }
}
async function saveLocalProject({ session: context, files, draft, payload, duration, signal, onProgress }) {
  const project = state.localProject;
  if (context.kind !== "local") return withReconnect(() => project.save(context, draft, payload, signal));
  if (!project.finalized && !await confirmLocalProjectSave()) return null;
  return withReconnect(async () => {
    const session = await project.sources(context, files, { signal, onProgress });
    state.activeManifest = session;
    renderCurrentRecording();
    renderResultArchive();
    const bound = bindLocalPayload(context, payload, project.plan, session, duration);
    const result = await project.save(session, null, bound.payload, signal);
    return { ...result, mapping: bound.mapping };
  });
}
async function openLocalSpeaker() {
  if (state.publicationController || state.uploadController) return;
  if (state.editorMode === "speaker" && getSpeakerSaveState().ready) return;
  if (state.activeManifest) return loadSpeakerSession(state.activeManifest);
  if (!getProcessorFiles().length) { setArchiveStatus("Выберите исходные дорожки в разделе Импорт."); return; }
  const files = getProcessorFiles();
  state.localContext ||= localSourceContext(files); state.localProject ||= new ProjectSave(gateway);
  const opened = await openSpeakerEditor({ session: state.localContext, files, saveDraft: saveLocalProject, onSaved: ({ session }) => { state.activeManifest = session; updateSourceSaveState(); renderCurrentRecording(); renderResultArchive(); } });
  if (opened) activateMode("speaker");
}
async function openLocalAnnouncement() {
  if (state.publicationController || state.uploadController) return;
  if (state.activeManifest) return loadSession(state.activeManifest);
  ++state.sessionSequence;
  if (!await protectSpeakerTransition()) return;
  // Save-and-continue may just have made local sources canonical; load them before closing Speaker.
  if (state.activeManifest) return loadSession(state.activeManifest);
  if (!await closeSpeakerEditor(true)) return;
  if (!getProcessorFiles().length) { setArchiveStatus("Выберите исходные дорожки в разделе Импорт."); return; }
  activateMode("announcement");
}
function workingFiles() { return state.editorMode === "speaker" && getSpeakerSaveState().session ? getSpeakerSaveState().files : getProcessorFiles(); }
function updateSourceSaveState() {
  const speaker = getSpeakerSaveState();
  document.getElementById("processor-save-incoming").disabled = !workingFiles().length || Boolean(state.activeManifest || state.localProject?.finalized) || Boolean(speaker.session && !speaker.ready);
}
function renderImportFiles() {
  updateSourceSaveState();
  const list = document.getElementById("import-files"); list.replaceChildren();
  const useLocal = document.getElementById("source-session-use-local");
  useLocal.hidden = !workingFiles().length;
  useLocal.disabled = !workingFiles().length;
  document.getElementById("import-summary").textContent = workingFiles().length ? `Выбрано дорожек: ${workingFiles().length}` : "Запись не выбрана";
  for (const [index, file] of workingFiles().entries()) {
    const row = document.createElement("li"); row.append(document.createTextNode(`${file.name} · ${file.name.split('.').at(-1).toUpperCase()} · ${formatBytes(file.size)} `));
    row.append(button("Удалить", async () => {
      const files = workingFiles().filter((_, i) => i !== index);
      if (!await closeSpeakerEditor(false)) return;
      state.activeManifest = null; state.localContext = null; state.localProject = null;
      if (files.length) loadProcessorFiles(files); else clearProcessorFiles();
    })); list.append(row);
  }
  renderCurrentRecording(); renderResultArchive();
}

function openIngestDialog(files = []) {
  const speaker = getSpeakerSaveState();
  if (speaker.session && !speaker.ready) { updateSourceSaveState(); return; }
  if (state.localProject?.finalized || state.activeManifest) { updateSourceSaveState(); return; }
  const sameFiles = state.pendingFiles.length === files.length && state.pendingFiles.every((file, i) => file === files[i]);
  state.pendingFiles = Array.from(files);
  state.pendingOrigin = state.pendingFiles.length ? "device" : "manual";
  if (!sameFiles || !state.retryKey) state.retryKey = crypto.randomUUID();
  const local = state.pendingFiles.length > 0;
  byId("ingest-files-field").hidden = local;
  byId("ingest-files").required = !local;
  if (!local) byId("ingest-files").value = "";
  byId("ingest-selection").textContent = local ? `Будут сохранены текущие дорожки: ${localSelectionText(state.pendingFiles)}` : "";
  byId("ingest-name").value = local ? state.pendingFiles[0].name.replace(/\.[^.]+$/, "") : "";
  byId("ingest-recorded").value = "";
  byId("ingest-status").textContent = "";
  byId("ingest-progress").hidden = true;
  byId("ingest-submit").disabled = false;
  byId("ingest-dialog").showModal();
}

function localSelectionText(files) {
  const bytes = files.reduce((sum, file) => sum + file.size, 0);
  return `${files.length} · ${formatBytes(bytes)}`;
}

async function submitIngestion(event) {
  event.preventDefault();
  const files = state.pendingFiles.length ? state.pendingFiles : Array.from(byId("ingest-files").files || []);
  if (!files.length || files.some((file) => !file.size) || files.reduce((sum, file) => sum + file.size, 0) > MAX_AUDIO_SESSION_BYTES) {
    byId("ingest-status").textContent = "Выберите непустые MP3, M4A или WAV общим размером не более 500 МБ.";
    return;
  }
  const title = byId("ingest-name").value.trim();
  if (!title) return;
  state.pendingFiles = files;
  state.uploadController = new AbortController();
  byId("ingest-submit").disabled = true;
  byId("ingest-files").disabled = true;
  byId("ingest-progress").hidden = false;
  byId("ingest-progress").value = 0;
  byId("ingest-status").textContent = "Хеширование и подготовка частей…";
  try {
    const recordedValue = byId("ingest-recorded").value;
    const saved = await gateway.ingestFiles({
      files, title, recordedAt: recordedValue ? new Date(recordedValue).toISOString() : null,
      origin: state.pendingOrigin,
      idempotencyKey: state.retryKey, signal: state.uploadController.signal,
      onPlan: plan => { state.ingestionPlan = plan; },
      onProgress: ({ uploadedBytes, totalBytes, uploadedParts, totalParts }) => {
        byId("ingest-progress").value = Math.round(uploadedBytes / totalBytes * 100);
        byId("ingest-status").textContent = `Загружено частей: ${uploadedParts} из ${totalParts}.`;
      }
    });
    const session = saved.session || saved;
    const context = localSourceContext(files);
    bindLocalPayload(context, defaultSpeakerPayload(context.sourceTracks.map(t => t.trackId)), state.ingestionPlan, session);
    if (!validateSessionManifest(session)) throw new Error("Не удалось подтвердить исходники.");
    state.activeManifest = session;
    if (state.pendingOrigin === "device") {
      state.localProject ||= new ProjectSave(gateway); state.localProject.finalized = session; state.localProject.plan = state.ingestionPlan;
      if (state.editorMode !== "speaker") {
        state.processorProvenance = state.ingestionPlan.tracks.map(t => ({ trackId: t.trackId, blobId: t.blobId, ordinal: t.ordinal, sizeBytes: t.sizeBytes, sha256: t.sha256, mediaType: t.mediaType }));
        state.loadingArchive = true; await bindProcessorSources(files, state.processorProvenance, { sessionId: session.id, sourceSessionRevision: session.revision }); state.loadingArchive = false;
        renderAnnouncementWorkspace();
      }
    }
    updateSourceSaveState();
    renderCurrentRecording(); renderResultArchive();
    byId("ingest-status").textContent = "Запись Zoom сохранена в аудиоархиве.";
    setTimeout(() => byId("ingest-dialog").close(), 400);
    await refreshSessions();
    setArchiveStatus("Запись Zoom сохранена в аудиоархиве.");
  } catch (error) {
    byId("ingest-status").textContent = error?.name === "AbortError" ?
      "Передача остановлена. Незавершённая операция сохранена для безопасного повтора." : `${userError(error, "Не удалось сохранить исходники.")} Локальные файлы сохранены; можно повторить.`;
  } finally {
    state.uploadController = null;
    byId("ingest-submit").disabled = false;
    byId("ingest-files").disabled = false;
  }
}


function openPublicationDialog() {
  updatePublishState();
  if (byId("publish-announcement").disabled) return;
  const nextVersion = state.activeManifest.workflows.announcement.nextVersion;
  const mode = { passthrough: "без изменения байтов", processed_single: "одна обработанная дорожка", mixed_multi: "сведение нескольких дорожек" }[state.candidate.processing.mode];
  const tracks = byId("publication-tracks");
  tracks.replaceChildren();
  for (const source of state.processorProvenance) {
    const item = document.createElement("li");
    item.textContent = state.activeManifest.sourceTracks.find((track) => track.trackId === source.trackId)?.originalName || "Дорожка недоступна";
    tracks.append(item);
  }
  byId("publication-source").textContent = `${state.activeManifest.title} · ${formatDate(state.activeManifest.recordedAt)}`;
  byId("publication-mode").textContent = mode;
  byId("publication-result").textContent = `${state.candidate.result.resultDurationSeconds.toFixed(2)} с · ${formatBytes(state.candidate.blob.size)} · ${formatMediaType(state.candidate.result.mediaType)} · ${state.candidate.result.presentationFilename}`;
  byId("publication-version").textContent = `Версия ${nextVersion} (предварительно)`;
  byId("publication-technical").textContent = `Идентификатор записи: ${state.activeManifest.id}. Ревизия: ${state.activeManifest.revision}.`;
  byId("publication-status").textContent = "Проверьте запись, порядок дорожек и локальный результат.";
  byId("publication-progress").hidden = true;
  byId("publication-submit").disabled = false;
  byId("publication-cancel").textContent = "Отмена";
  byId("publication-dialog").showModal();
}

async function submitPublication(event) {
  event.preventDefault();
  if (!state.activeManifest || !state.candidate) return;
  state.publicationKey ||= crypto.randomUUID();
  state.publicationController = new AbortController();
  byId("publication-submit").disabled = true;
  byId("publication-cancel").textContent = "Остановить";
  byId("publication-progress").hidden = false;
  byId("publication-progress").value = 0;
  byId("publication-status").textContent = "Подготовка проверяемых частей результата…";
  updatePublishState();
  const candidate = getProcessorResult();
  const epoch = state.sessionSequence;
  let completed = false;
  try {
    const session = state.activeManifest;
    state.publicationBinding ||= { session: structuredClone(session), candidate, payload: { trackIds: selectedTrackIds() }, saver: new ProjectSave(gateway, "announcement"), saved: null };
    const binding = state.publicationBinding;
    if (binding.session.id !== session.id || candidate.blob !== binding.candidate.blob || JSON.stringify(binding.payload.trackIds) !== JSON.stringify(selectedTrackIds())) throw Object.assign(new Error("Результат изменился"), { status: 409 });
    if (!binding.saved) {
      const current = (await gateway.loadDraft(session.id, "announcement")).draft;
      if (current && current.payloadSchema !== "announcement/v1") throw new Error("Неподдерживаемые сохранённые данные не будут перезаписаны.");
      if (!binding.saver.attempt && current && JSON.stringify(current.payload) === JSON.stringify(binding.payload)) {
        const fresh = await gateway.getSession(session.id);
        if (fresh.revision !== binding.session.revision || candidate.provenance?.sourceSessionRevision !== fresh.revision) throw Object.assign(new Error("Запись изменилась"), { status: 409 });
        binding.saved = { session: fresh, draft: current };
      } else binding.saved = await binding.saver.save(binding.session, current, binding.payload);
    }
    const fresh = await gateway.getSession(session.id);
    if (fresh.revision !== binding.saved.session.revision) {
      const job = state.publicationTransactionId ? await gateway.publicationJob(state.publicationTransactionId) : null;
      if (job?.state !== "finalized" || job.sessionId !== session.id) throw Object.assign(new Error("Запись изменилась"), { status: 409 });
    }
    if (epoch !== state.sessionSequence) return;
    state.activeManifest = binding.saved.session; state.announcementDraft = binding.saved.draft;
    const result = await gateway.publishAnnouncement({
      sessionId: state.activeManifest.id,
      expectedRevision: state.activeManifest.revision,
      expectedDraftRevision: state.announcementDraft.draftRevision,
      blob: candidate.blob,
      recipe: {
        sourceSessionRevision: state.activeManifest.revision,
        sources: candidate.sources,
        draft: { revision: state.announcementDraft.draftRevision, payloadSchema: "announcement/v1",
          payload: { trackIds: selectedTrackIds() } },
        processing: candidate.processing,
        result: candidate.result
      },
      idempotencyKey: state.publicationKey,
      signal: state.publicationController.signal,
      onStarted: (job) => { state.publicationTransactionId = job.transactionId; },
      onProgress: ({ uploadedBytes, totalBytes, uploadedParts, totalParts, reservedVersion }) => {
        byId("publication-progress").value = Math.min(95, Math.round(uploadedBytes / totalBytes * 100));
        byId("publication-status").textContent = `Версия ${reservedVersion}: передано частей ${uploadedParts} из ${totalParts}. Завершаем сохранение…`;
      }
    });
    byId("publication-progress").value = 100;
    byId("publication-status").textContent = `Версия ${result.output.version} сохранена в архиве «Анонс-мейкер».`;
    state.publicationBinding = null;
    state.announcementDraftKey = null;
    state.publicationKey = null;
    state.publicationTransactionId = null;
    state.activeManifest = await gateway.getSession(state.activeManifest.id);
    renderAnnouncementWorkspace();
    byId("announcement-status").textContent = `Версия ${result.output.version} сохранена; проект обработки не изменён.`;
    await refreshSessions();
    completed = true;
    setTimeout(() => byId("publication-dialog").close(), 500);
  } catch (error) {
    byId("publication-status").textContent = error?.name === "AbortError" ?
      "Передача остановлена. Зарезервированная версия сохранена для безопасного повтора или удаления незавершённой операции." : `${userError(error, "Не удалось завершить сохранение результата.")} Безопасный повтор продолжит ту же операцию и сохранит номер версии.`;
  } finally {
    state.publicationController = null;
    byId("publication-submit").disabled = completed;
    byId("publication-cancel").textContent = "Закрыть";
    updatePublishState();
  }
}

async function cancelPublicationDialog() {
  if (state.publicationController) {
    state.publicationController.abort();
    const transactionId = state.publicationTransactionId;
    if (transactionId) {
      try { await gateway.cancelPublication(transactionId); } catch (error) { byId("publication-status").textContent = userError(error, "Не удалось подтвердить остановку. Проверьте незавершённые операции."); }
    }
    return;
  }
  byId("publication-dialog").close();
}

function destructiveSourceTarget(selection) { return ["sources", "purge"].includes(selection.kind); }
function speakerIdentity() {
  const work = getSpeakerSaveState();
  return { id: work.session?.id, epoch: work.sourceEpoch, payload: JSON.stringify(work.payload) };
}
function sameSpeaker(work) {
  const now = speakerIdentity(); return now.id === work.id && now.epoch === work.epoch && now.payload === work.payload;
}
async function freshDeletion(id, selection, expectedRevision = null) {
  const [session, preview, incomplete] = await Promise.all([gateway.getSession(id), gateway.dependencyPreview(id), gateway.listIncomplete()]);
  if (!validateSessionManifest(session) || session.id !== id || preview.sessionId !== id || preview.revision !== session.revision ||
      (expectedRevision !== null && session.revision !== expectedRevision) || !Array.isArray(incomplete.transactions)) throw Object.assign(new Error("Данные изменились"), { status: 409 });
  if (incomplete.transactions.some(t => t.sessionId === id && (t.kind === "pending_delete" || ["finalizing", "discarding"].includes(t.state))) ||
      preview.pendingAnnouncementPublications + preview.pendingSpeakerSaves > 0) throw Object.assign(new Error("Требуется завершить незавершённые операции"), { status: 409 });
  if (selection.kind === "output-version" && !session.workflows[selection.workflow].outputs.some(output => output.version === selection.version)) throw Object.assign(new Error("Версия недоступна"), { status: 404 });
  return { session, preview };
}
async function openDeleteDialog(session, selection) {
  if (state.deleteBusy || byId("delete-dialog").open) return;
  const sequence = ++state.deleteSequence, auth = state.authSequence, focus = document.activeElement;
  const current = () => sequence === state.deleteSequence && auth === state.authSequence;
  try {
    if (session.id === speakerEditorSessionId()) {
      if (getSpeakerSaveState().saving) throw new Error("Сохранение ещё выполняется");
      if (destructiveSourceTarget(selection) && !await protectSpeakerTransition()) return;
    }
    if (!current()) return;
    const work = speakerIdentity();
    const fresh = await freshDeletion(session.id, selection);
    if (!current() || (destructiveSourceTarget(selection) && !sameSpeaker(work))) return;
    state.deleteTarget = { ...fresh, selection, work, focus, sequence, auth, idempotencyKey: crypto.randomUUID() };
    const impact = deletionImpact(fresh.preview, selection);
    byId("delete-summary").textContent = `${fresh.session.title}. ${impact.removed} Останется: ${impact.retained}`;
    byId("delete-technical").textContent = `Точный идентификатор записи: ${session.id}`;
    byId("delete-confirmation").value = "";
    byId("delete-confirmation-field").hidden = !destructiveSourceTarget(selection);
    byId("delete-confirmation-label").textContent = selection.kind === "purge" ? `Введите точный ID записи: ${session.id}` : "Введите «Удалить исходники, сохранить результаты»";
    byId("delete-status").textContent = "Подтверждение относится только к этой цели и её текущему состоянию.";
    byId("delete-submit").disabled = false; byId("delete-dialog").showModal();
  } catch (error) { if (current()) onGatewayError(error, "Не удалось подготовить удаление. Обновите запись и проверьте незавершённые операции."); }
}
async function submitDeletion(event) {
  event.preventDefault();
  const target = state.deleteTarget;
  if (!target || state.deleteBusy) return;
  const { selection } = target;
  const current = () => state.deleteTarget === target && state.deleteSequence === target.sequence && state.authSequence === target.auth;
  const confirmation = byId("delete-confirmation").value;
  if ((selection.kind === "purge" && confirmation !== target.session.id) || (selection.kind === "sources" && confirmation !== "Удалить исходники, сохранить результаты")) {
    byId("delete-status").textContent = "Введите подтверждение точно, без изменений."; return;
  }
  state.deleteBusy = true; byId("delete-submit").disabled = true;
  try {
    const fresh = await freshDeletion(target.session.id, selection, target.session.revision);
    if (!current()) return;
    if (JSON.stringify(fresh.preview) !== JSON.stringify(target.preview) || (destructiveSourceTarget(selection) && !sameSpeaker(target.work))) throw Object.assign(new Error("Цель или работа изменились"), { status: 409 });
    if (target.session.id === speakerEditorSessionId() && getSpeakerSaveState().saving) throw new Error("Сохранение ещё выполняется");
    const body = { expectedRevision: fresh.session.revision, idempotencyKey: target.idempotencyKey, confirmation };
    const result = selection.kind === "output-version" ? await gateway.deleteOutputVersion(target.session.id, selection.workflow, selection.version, body) :
      selection.kind === "output-series" ? await gateway.deleteOutputSeries(target.session.id, selection.workflow, body) :
      selection.kind === "sources" ? await gateway.deleteSources(target.session.id, body) : await gateway.purgeSession(target.session.id, body);
    if (!current()) return;
    // Output deletion never tears down an editor. A late destructive response
    // cannot close newer work, even if the same source has since been reopened.
    const matchingWork = sameSpeaker(target.work);
    if (!destructiveSourceTarget(selection) && result?.session && matchingWork) updateSpeakerSession(result.session);
    if (destructiveSourceTarget(selection) && target.session.id === speakerEditorSessionId() && matchingWork) await closeSpeakerEditor(true);
    clearOutputPlayback();
    if (state.activeManifest?.id === target.session.id && matchingWork) {
      if (result?.session) {
        state.activeManifest = result.session; state.activeSession = result.session;
        if (result.session.sourceState === "available") updateProcessorProvenanceContext({ sessionId: result.session.id, sourceSessionRevision: result.session.revision });
        else if (destructiveSourceTarget(selection)) { clearProcessorFiles(); state.processorProvenance = []; }
        renderAnnouncementWorkspace();
      } else if (result?.tombstone && destructiveSourceTarget(selection)) closeAnnouncementWorkspace(true);
    }
    byId("delete-dialog").close(); await refreshSessions();
  } catch (error) {
    if (!current()) return;
    state.deleteTarget = null;
    byId("delete-status").textContent = userError(error, "Удаление не подтверждено. Обновите данные и получите новый предварительный просмотр.");
    if (error.status === 401) onGatewayError(error, "", null);
  } finally { state.deleteBusy = false; }
}

async function showIncomplete() {
  const sequence = ++state.incompleteSequence, auth = state.authSequence;
  const container = byId("recovery-list");
  const currentSessionId = state.activeManifest?.id || speakerEditorSessionId();
  const contextual = Boolean(currentSessionId && state.mode === "archive" && state.editorMode === "speaker" && getSpeakerSaveState().ready);
  if (!contextual && !state.speakerResumeController) {
    container.replaceChildren(); container.hidden = true; return;
  }
  try {
    const result = await gateway.listIncomplete();
    if (sequence !== state.incompleteSequence || auth !== state.authSequence) return;
    if (state.speakerResumeController) {
      container.hidden = false;
      renderSpeakerResumeStatus(state.speakerResumeStatus || "Продолжение передачи выполняется…", state.speakerResumeCancellable);
      return;
    }
    container.replaceChildren();
    let associated = 0;
    for (const transaction of result.transactions || []) {
      const binding = speakerRecoveryBinding(transaction, { sessionId: currentSessionId, workflow: state.editorMode,
        archiveMode: state.mode === "archive", candidate: getSpeakerSaveState().candidate });
      if (!binding.belongs) continue;
      associated++;
      const row = document.createElement("div"); row.className = "source-recovery-item";
      const title = document.createElement("strong"); title.textContent = "Требуется внимание"; row.append(title);
      const policy = recoveryPolicy(transaction);
      row.append(document.createTextNode(transaction.kind === "pending_delete" ? " Удаление не завершено. " :
        transaction.kind === "publication" ? ` Есть незавершённое сохранение Версии ${transaction.reservedVersion} в «${workflowLabel(transaction.workflow)}». ` : " Сохранение записи Zoom не завершено. "));
      row.append(document.createTextNode(policy.local));
      if (!transaction.canFinalize && ["uploading", "cancelled"].includes(transaction.state) && policy.actions.length && binding.exactCandidate) {
        row.append(button("Продолжить передачу", () => resumeSpeakerIncomplete(transaction)));
      }
      for (const [action, label] of policy.actions) row.append(button(label, () => recover(transaction, action), action === "discard" ? "source-session-danger" : ""));
      container.append(row);
    }
    container.hidden = !associated;

  } catch (error) {
    if (sequence !== state.incompleteSequence || auth !== state.authSequence) return;
    if (state.speakerResumeController) {
      renderSpeakerResumeStatus(state.speakerResumeStatus || "Продолжение передачи выполняется…", state.speakerResumeCancellable);
      return;
    }
    container.hidden = false; container.textContent = userError(error, "Не удалось проверить незавершённые операции.");
  }
}

async function recover(operation, action) {
  const context = {
    auth: state.authSequence,
    generation: state.sessionSequence,
    sessionId: state.activeManifest?.id || speakerEditorSessionId(),
    workflow: state.editorMode
  };
  const currentContext = () => context.auth === state.authSequence && context.generation === state.sessionSequence &&
    context.sessionId === (state.activeManifest?.id || speakerEditorSessionId()) && context.workflow === state.editorMode;
  try {
    const latest = await gateway.listIncomplete();
    if (!currentContext()) return;
    const current = latest.transactions.find(t => t.transactionId === operation.transactionId);
    const same = value => value && value.kind === operation.kind && value.sessionId === operation.sessionId && value.workflow === operation.workflow &&
      value.state === operation.state && recoveryPolicy(value).actions.some(([allowed]) => allowed === action);
    if (!same(current)) throw Object.assign(new Error("Состояние операции изменилось"), { status: 409 });
    if ((action === "discard" || current.kind === "pending_delete") && !globalThis.confirm(action === "discard" ? "Удалить только это незавершённое сохранение? Зарезервированный номер версии останется использованным." : "Продолжить уже начатое необратимое удаление этой записи?")) return;
    const rechecked = await gateway.listIncomplete();
    if (!currentContext()) return;
    if (!same(rechecked.transactions.find(t => t.transactionId === operation.transactionId))) throw Object.assign(new Error("Состояние операции изменилось"), { status: 409 });
    if (!currentContext()) return;
    await gateway.recoverIncomplete(operation.transactionId, action);
    if (!currentContext()) return;
    await refreshSessions();
    if (!currentContext()) return;
  } catch (error) {
    if (!currentContext()) return;
    byId("recovery-list").textContent = userError(error, "Не удалось восстановить незавершённую операцию.");
    if (error.status === 401) onGatewayError(error, "", null);
  }
}

async function resumeSpeakerIncomplete(transaction) {
  if (state.speakerResumeController) {
    renderSpeakerResumeStatus(state.speakerResumeStatus || "Продолжение передачи уже выполняется.", state.speakerResumeCancellable);
    return;
  }
  const candidate = getSpeakerSaveState().candidate;
  if (!candidate) {
    byId("recovery-list").textContent = "Локальный результат незавершённого сохранения отсутствует в этой вкладке. Его нельзя заменить новой обработкой. Проверьте доступные действия у этой записи в аудиоархиве.";
    return;
  }
  if (candidate.sessionId !== transaction.sessionId) {
    byId("recovery-list").textContent = "Открытый локальный результат относится к другой записи. Откройте точную запись незавершённого сохранения.";
    return;
  }
  const immutable = {
    transaction: structuredClone(transaction),
    candidate: { ...structuredClone({ ...candidate, blob: null }), blob: candidate.blob }
  };
  state.speakerResumeController = new AbortController();
  state.speakerResumeTransactionId = immutable.transaction.transactionId;
  state.speakerResumeSnapshot = immutable;
  let refreshRecovery = false;
  try {
    setSpeakerSaveLocked(true);
    renderSpeakerResumeStatus(`Версия ${immutable.transaction.reservedVersion}: проверка локального результата…`, true);
    await gateway.resumeSpeakerSave(immutable.transaction.transactionId, {
      blob: immutable.candidate.blob,
      candidateFingerprint: immutable.candidate.candidateFingerprint,
      signal: state.speakerResumeController.signal,
      onProgress: ({ uploadedParts, totalParts, reservedVersion }) => {
        renderSpeakerResumeStatus(`Версия ${reservedVersion}: продолжение передачи, частей ${uploadedParts} из ${totalParts}.`, true);
      }
    });
    const updated = await gateway.getSession(immutable.candidate.sessionId);
    updateSpeakerSession(updated);
    await refreshSessions();
    refreshRecovery = true;
  } catch (error) {
    if (error?.name === "AbortError") {
      try { await gateway.cancelSpeakerSave(immutable.transaction.transactionId); } catch { /* authoritative read below */ }
    }
    const authoritative = await reconcileSpeakerSave(immutable.transaction.transactionId, immutable.candidate.sessionId);
    if (authoritative.finalized) {
      renderSpeakerResumeStatus(`Версия ${authoritative.job.reservedVersion} уже сохранена в архиве «Спикерская».`);
    } else if (authoritative.known) {
      const exactMismatch = /точно тот же локальный результат|не совпадает с планом/.test(error?.message || "");
      renderSpeakerResumeStatus(error?.name === "AbortError" ?
        `Продолжение Версии ${authoritative.job.reservedVersion} остановлено. Незавершённое сохранение не удалено.` :
        exactMismatch ? `${error.message} Незавершённое сохранение не удалено.` :
          userError(error, "Не удалось продолжить передачу. Незавершённое сохранение не удалено."));
    } else {
      renderSpeakerResumeStatus("Состояние продолжения пока неизвестно. Проверьте незавершённые сохранения перед повтором.");
    }
  } finally {
    state.speakerResumeController = null;
    state.speakerResumeTransactionId = null;
    state.speakerResumeSnapshot = null;
    state.speakerResumeStatus = null;
    state.speakerResumeCancellable = false;
    setSpeakerSaveLocked(false);
  }
  if (refreshRecovery) await showIncomplete();
}

function renderSpeakerResumeStatus(message, cancellable = false) {
  state.speakerResumeStatus = message;
  state.speakerResumeCancellable = Boolean(cancellable);
  const container = byId("recovery-list");
  container.hidden = false;
  container.replaceChildren(document.createTextNode(message));
  if (cancellable) container.append(document.createTextNode(" "), button("Отменить продолжение", cancelSpeakerResume));
}

function cancelSpeakerResume() {
  if (!state.speakerResumeController || state.speakerResumeController.signal.aborted) return;
  state.speakerResumeController.abort();
  renderSpeakerResumeStatus("Останавливаем продолжение и проверяем состояние на сервере…");
}

let editorIntentConsumed = false;
async function consumeEditorIntent() {
  if (editorIntentConsumed) return;
  let intent;
  try { intent = parseEditorIntent(location.search); }
  catch (error) { editorIntentConsumed = true; setArchiveStatus(error.message); return; }
  if (!intent) return;
  if (!state.authenticated) {
    setArchiveStatus("Для открытия записи по ссылке подключите архив. Обработка автоматически не запускается.");
    return;
  }
  if (state.publicationController || state.speakerSaveController || state.speakerResumeController || state.uploadController || getSpeakerSaveState().saving) {
    setArchiveStatus("Сначала завершите текущую передачу, затем откройте ссылку из аудиоархива снова.");
    return;
  }
  const sequence = ++state.sessionSequence, auth = state.authSequence;
  try {
    const session = await gateway.getSession(intent.sessionId);
    if (sequence !== state.sessionSequence || !state.authenticated) return;
    if (!validateSessionManifest(session) || session.id !== intent.sessionId) throw new Error("Некорректные сведения о записи.");
    const recoverableSpeaker = intent.workflow === "speaker" &&
      Boolean(session.workflows?.speaker?.currentDraft || intent.projectRevision || intent.speakerOutput);
    if (!eligible(session) && !recoverableSpeaker) {
      setArchiveStatus("Новая обработка недоступна: верните запись для обработки; исходники должны быть доступны. Откройте аудиоархив для просмотра результатов.");
      return;
    }
    if (recoverableSpeaker && !eligible(session)) await loadSpeakerSession(session, intent);
    else await selectSessionContext(session, { workflow: intent.workflow, intent });
    if ((state.activeManifest?.id === session.id && state.editorMode === intent.workflow) ||
        (recoverableSpeaker && state.speakerRecovery?.session?.id === session.id)) {
      editorIntentConsumed = true;
      const url = new URL(location.href);
      for (const key of ["session", "workflow", "projectRevision", "speakerOutput"]) url.searchParams.delete(key);
      history.replaceState(history.state, "", url);
    }
  } catch (error) {
    if (sequence === state.sessionSequence) onGatewayError(error, "Запись по ссылке недоступна или удалена. Откройте аудиоархив.");
  }
}

async function initialize() {
  setMode("archive");
  updateSessionStatus();
  try {
    state.authenticated = await authController.restore();
    if (state.authenticated) await gateway.configuration();
  } catch { state.authenticated = false; }
  updateSessionStatus();
  await refreshSessions();

  await consumeEditorIntent();
}

document.getElementById("speaker-project-recovery-attach").addEventListener("click", async () => {
  const recovery = state.speakerRecovery;
  if (!recovery || !recovery.work.sources?.length) return;
  const status = document.getElementById("speaker-project-recovery-status");
  const input = document.getElementById("speaker-project-recovery-files");
  try {
    status.textContent = "Проверка SHA-256 и размера полного набора дорожек…";
    const files = await verifyLocalSourceAttachment(input.files, recovery.work.sources);
    if (state.speakerRecovery !== recovery) return;
    recovery.files = files;
    status.textContent = "Точные локальные исходники подключены в каноническом порядке. Старые удалённые bytes и tombstone не изменены.";
    document.getElementById("speaker-project-recovery-ingest").hidden = false;
  } catch (error) {
    if (state.speakerRecovery !== recovery) return;
    recovery.files = null; document.getElementById("speaker-project-recovery-ingest").hidden = true;
    status.textContent = error.message || "Набор дорожек не прошёл проверку.";
  }
});

document.getElementById("speaker-project-recovery-ingest").addEventListener("click", async () => {
  const recovery = state.speakerRecovery;
  if (!recovery?.files) return;
  const status = document.getElementById("speaker-project-recovery-status");
  try {
    const target = await ingestSpeakerRecoverySources(gateway, recovery, () => {
      status.textContent = "Сохранение точных исходников как новой записи Zoom…";
    });
    if (state.speakerRecovery !== recovery) return;
    recovery.target = target;
    status.textContent = "Новая запись Zoom сохранена. Теперь проект можно атомарно продолжить в ней.";
    document.getElementById("speaker-project-recovery-ingest").hidden = true;
    document.getElementById("speaker-project-recovery-continue").hidden = false;
  } catch (error) { if (state.speakerRecovery === recovery) status.textContent = userError(error, "Не удалось сохранить восстановленные исходники."); }
});

document.getElementById("speaker-project-recovery-continue").addEventListener("click", async () => {
  const recovery = state.speakerRecovery;
  if (!recovery?.target || !recovery.work.continuation) return;
  const status = document.getElementById("speaker-project-recovery-status");
  try {
    status.textContent = "Проверка исходников, переназначение дорожек и подтверждение связей…";
    if (!recovery.continuationRequest) {
      const [source, target] = await Promise.all([gateway.getSession(recovery.session.id), gateway.getSession(recovery.target.id)]);
      if (state.speakerRecovery !== recovery) return;
      recoveryContinuationRequest(recovery, source, target);
    }
    const result = await gateway.continueSpeakerProject(recovery.session.id, recoveryContinuationRequest(recovery, recovery.session, recovery.target));
    if (state.speakerRecovery !== recovery) return;
    if (result.sourceSession.relations.supersededBySessionId !== result.targetSession.id ||
        result.targetSession.relations.supersedesSessionId !== result.sourceSession.id || !result.state) throw new Error("Связи продолжения не подтверждены.");
    status.textContent = "Проект продолжен в новой записи Zoom.";
    document.getElementById("speaker-project-recovery").hidden = true; state.speakerRecovery = null;
    await refreshSessions(); await loadSpeakerSession(result.targetSession);
  } catch (error) { if (state.speakerRecovery === recovery) status.textContent = userError(error, "Не удалось подтвердить продолжение проекта. Повтор безопасен."); }
});

byId("mode-archive").addEventListener("click", () => {
  setMode("archive"); document.getElementById("import-zone").hidden = false; document.getElementById("import-zone").open = true;
  state.picker.requested = true; state.picker.page = 0; renderSessions();
  byId("mode-archive").setAttribute("aria-expanded", "true"); byId("filters").elements.search.focus();
});
byId("mode-device").addEventListener("click", () => {
  setMode("device"); document.getElementById("import-zone").hidden = false; document.getElementById("import-zone").open = true;
  byId("mode-device").setAttribute("aria-expanded", "true"); byId("mode-device").focus();
});
byId("picker-close").addEventListener("click", () => {
  const zone = document.getElementById("import-zone"); zone.open = false;
  if (!state.activeManifest && !state.localContext && !workingFiles().length) zone.hidden = true;
  byId("mode-archive").setAttribute("aria-expanded", "false"); byId("mode-device").setAttribute("aria-expanded", "false"); byId(`mode-${state.mode}`).focus();
});
document.getElementById("source-session-use-local").addEventListener("click", () => {
  if (!workingFiles().length) return;
  const zone = document.getElementById("import-zone");
  zone.open = false;
  byId("mode-device").setAttribute("aria-expanded", "false");
  document.getElementById("workflow-choice").focus({ preventScroll: true });
  scrollToElement(document.getElementById("workflow-choice"));
});
document.getElementById("import-zone").addEventListener("toggle", event => {
  byId("mode-archive").setAttribute("aria-expanded", String(event.currentTarget.open && state.mode === "archive"));
  byId("mode-device").setAttribute("aria-expanded", String(event.currentTarget.open && state.mode === "device"));
});
document.getElementById("import-zone").addEventListener("keydown", event => {
  if (event.key !== "Escape" || !event.currentTarget.open) return;
  event.preventDefault(); byId("picker-close").click();
});
byId("filters").addEventListener("submit", event => { event.preventDefault(); state.picker.requested = true; state.picker.page = 0; renderSessions(); });
byId("recent").addEventListener("click", () => { byId("filters").elements.search.value = ""; byId("filters").elements.month.value = ""; state.picker.requested = true; state.picker.page = 0; renderSessions(); });
byId("prev").addEventListener("click", () => { state.picker.page--; renderSessions(); });
byId("next").addEventListener("click", () => { state.picker.page++; renderSessions(); });
byId("results-announcement").addEventListener("click", () => setResultArchive("announcement"));
byId("results-speaker").addEventListener("click", () => setResultArchive("speaker"));
byId("refresh").addEventListener("click", refreshSessions);
document.getElementById("source-session-loading-cancel").addEventListener("click", () => {
  if (!state.preparationController || state.preparationController.signal.aborted) return;
  state.preparationController.abort(new DOMException("Загрузка отменена пользователем.", "AbortError"));
  setArchiveStatus("Загрузка отменена. Предыдущая запись и локальная работа сохранены.");
});

byId("authenticate").addEventListener("click", () => ensureAuthenticated(refreshSessions).catch(() => {}));

document.getElementById("processor-save-incoming").addEventListener("click", () => ensureAuthenticated(() => openIngestDialog(workingFiles())).catch(() => {}));
window.addEventListener("audio-processor-selection", (event) => {
  if (!state.loadingArchive) { state.preparationController?.abort(); ++state.sessionSequence; }
  if (!state.loadingArchive && state.editorMode !== "speaker" && event.detail.files.length && !event.detail.provenance.length) {
    setMode("device"); state.activeManifest = null; state.preparedBatch = null; state.processorProvenance = [];
    state.localContext = localSourceContext(event.detail.files); state.localProject = new ProjectSave(gateway);
  }
  renderImportFiles();
  if (event.detail.provenance.length) {
    state.processorProvenance = event.detail.provenance;
    renderAnnouncementWorkspace();
  }
  updateSourceSaveState();
  updatePublishState();
});
window.addEventListener("audio-processor-result", (event) => {
  state.candidate = event.detail.candidate;
  state.publicationBinding = null; state.publicationTransactionId = null;
  state.publicationKey = crypto.randomUUID();
  updatePublishState();
});
window.addEventListener("speaker-editor-state", (event) => updateSpeakerSaveState(event.detail));
window.addEventListener("speaker-editor-opened", () => activateMode("speaker"));
speakerId("archive-save").addEventListener("click", openSpeakerSaveDialog);
speakerId("save-form").addEventListener("submit", submitSpeakerSave);
speakerId("save-cancel").addEventListener("click", cancelSpeakerSaveDialog);
speakerId("save-dialog").addEventListener("cancel", (event) => {
  if (!state.speakerSaveController) return;
  event.preventDefault();
  cancelSpeakerSaveDialog();
});

byId("announcement-close").addEventListener("click", leaveAnnouncementWorkspace);
byId("publish-announcement").addEventListener("click", openPublicationDialog);
byId("publication-form").addEventListener("submit", submitPublication);
byId("publication-cancel").addEventListener("click", cancelPublicationDialog);
byId("publication-dialog").addEventListener("cancel", (event) => {
  if (!state.publicationController) return;
  event.preventDefault();
  cancelPublicationDialog();
});

byId("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (event.submitter.disabled) return;
  const submit = event.submitter; submit.disabled = true;
  const auth = ++state.authSequence;
  const password = byId("password").value;
  try {
    await authController.login(password);
    if (auth !== state.authSequence) return;
  } catch (error) {
    if (error?.code !== 'invalid_password') byId("login-status").textContent = userError(error, "Не удалось восстановить служебную сессию.");
  } finally {
    submit.disabled = false;
    byId("password").value = "";
  }
});
byId("login-cancel").addEventListener("click", () => { ++state.authSequence; authController.cancel(); state.afterLogin?.(false); state.afterLogin = null; byId("login-dialog").close(); });
byId("ingest-files").addEventListener("change", () => {
  const files = Array.from(byId("ingest-files").files || []);
  byId("ingest-selection").textContent = files.length ? localSelectionText(files) : "";
});
byId("ingest-form").addEventListener("submit", submitIngestion);
byId("ingest-cancel").addEventListener("click", () => {
  if (state.uploadController) state.uploadController.abort();
  else byId("ingest-dialog").close();
});
byId("delete-form").addEventListener("submit", submitDeletion);
byId("delete-cancel").addEventListener("click", () => { if (!state.deleteBusy) byId("delete-dialog").close(); });
byId("delete-dialog").addEventListener("cancel", event => { if (state.deleteBusy) event.preventDefault(); });
byId("delete-dialog").addEventListener("close", () => {
  const focus = state.deleteTarget?.focus; state.deleteTarget = null; ++state.deleteSequence;
  if (focus?.isConnected) focus.focus(); else byId("refresh").focus();
});
window.addEventListener("pagehide", () => { state.preparationController?.abort(); clearOutputPlayback(); });

await initialize();

document.getElementById("open-local-speaker").addEventListener("click", openLocalSpeaker);
document.getElementById("open-local-announcement").addEventListener("click", openLocalAnnouncement);
setProcessorSelectionGuard(async () => { if (state.publicationController || state.uploadController) return false; if (!await closeSpeakerEditor(false)) return false; state.preparationController?.abort(); ++state.sessionSequence; return true; });
document.getElementById("import-replace").addEventListener("click", () => document.getElementById("processor-file").click());
document.getElementById("import-add").addEventListener("click", () => document.getElementById("import-add-files").click());
document.getElementById("import-add-files").addEventListener("change", async event => {
  const files = [...workingFiles(), ...event.target.files];
  if (await closeSpeakerEditor(false)) loadProcessorFiles(files);
  event.target.value = "";
});
byId("login-dialog").addEventListener("cancel", () => { ++state.authSequence; state.afterLogin?.(false); state.afterLogin = null; });
// Every archive response, including byte downloads, retains auth status. Login itself never recursively reconnects.
const archiveFetch = gateway.fetchImpl;
gateway.fetchImpl = async (url, options) => {
  const auth = state.authSequence;
  const response = await archiveFetch(url, options);
  if (auth === state.authSequence && response.status === 401 && !String(url).endsWith("/session/login")) {
    state.authenticated = false; state.reconnectNeeded = true; updateSessionStatus(); setArchiveStatus(RECONNECT_MESSAGE);
  }
  return response;
};
for (const dialog of [byId("ingest-dialog"), byId("publication-dialog"), speakerId("save-dialog")]) {
  const reconnect = button("Войти снова", () => ensureAuthenticated().catch(() => {}));
  dialog.append(reconnect);
}

speakerId("close").addEventListener("click", () => {
  ++state.sessionSequence; state.retryAction = null; updateSessionStatus();
});

window.addEventListener("speaker-editor-closed", () => {
  if (state.editorMode === "speaker") {
    state.editorMode = null; delete document.body.dataset.editing;
    document.getElementById("active-editor-mode").textContent = "Запись готова. Выберите одну задачу.";
    renderCurrentRecording(); renderResultArchive();
  }
});

document.getElementById("archive-reconnect-login").addEventListener("click", () => ensureAuthenticated().catch(() => {}));
document.getElementById("archive-reconnect-retry").addEventListener("click", async () => {
  const action = state.retryAction; state.retryAction = null; updateSessionStatus();
  try { await action?.(); } catch (error) { onGatewayError(error, "Данные изменились. Выберите запись и повторите действие."); }
});
