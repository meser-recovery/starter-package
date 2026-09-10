import { defaultSpeakerPayload } from "./speaker-editor-core.mjs";
import { RECONNECT_MESSAGE, localSourceContext, bindLocalPayload, ProjectSave } from "./audio-project.mjs";
import { eligible, parseEditorIntent, mergeSessions, recoveryPolicy } from './audio-archive-core.mjs';
import { AudioArchiveGateway, MAX_AUDIO_SESSION_BYTES, validateSessionManifest, reconstructAnnouncementOutput, reconstructSessionTracks, reconstructSpeakerOutput } from "./audio-archive-client.mjs";
import { bindProcessorSources, setProcessorSelectionGuard, clearProcessorFiles, getProcessorFiles, getProcessorResult, loadProcessorFiles, updateProcessorProvenanceContext } from "./audio-processor.mjs";
import { confirmLocalProjectSave, protectSpeakerTransition, closeSpeakerEditor, getSpeakerSaveState, openSpeakerEditor, setSpeakerSaveLocked, speakerEditorSessionId, updateSpeakerSession } from "./speaker-editor.mjs";

const byId = (id) => document.getElementById(`source-session-${id}`);
const speakerId = (id) => document.getElementById(`speaker-editor-${id}`);
const baseUrl = globalThis.__MESER_AUDIO_ARCHIVE_GATEWAY__ ||
  document.querySelector('meta[name="audio-archive-gateway"]')?.content.trim().replace(/\/$/, "") || "";
const gateway = new AudioArchiveGateway(baseUrl);
const state = {
  localContext: null, localProject: null, editorMode: null,
  authenticated: false, authSequence: 0, retryAction: null, reconnectNeeded: false,
  sessions: [],
  allSessions: [],
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
  return new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function formatMediaType(value) {
  return ({ "audio/mpeg": "MP3", "audio/mp4": "M4A", "audio/wav": "WAV" })[value] || "аудиофайл";
}

function workflowLabel(value) {
  return ({ announcement: "Анонс-мейкер", speaker: "Спикерская" })[value] || "Неизвестный тип работы";
}

function userError(error, fallback) {
  if (error?.name === "AbortError") return "Операция остановлена.";
  if (error?.status === 401 || error?.status === 403) return "Подключение к аудиоархиву истекло. Подключитесь снова, чтобы продолжить.";
  if (error?.status === 409) return "Данные записи изменились в другом окне. Обновите архив и повторите действие.";
  if (error?.status === 413) return "Объём данных превышает допустимый предел.";
  if (error?.status === 422) return "Проверка целостности данных не пройдена. Операция остановлена без изменений.";
  if (error?.status >= 500) return "Архив временно недоступен. Повторите действие позже.";
  if (error instanceof TypeError) return "Не удалось связаться с архивом. Проверьте подключение к сети и повторите действие.";
  return fallback;
}

function setArchiveStatus(message) {
  byId("status").textContent = message;
}

function updateSessionStatus() {
  byId("session-status").textContent = !baseUrl ? "Шлюз аудиоархива ещё не настроен." :
    state.authenticated ? "Общий защищённый сеанс архива активен." : "Для архива требуется общий служебный пароль.";
  byId("authenticate").hidden = state.authenticated;
  document.getElementById("archive-reconnect").hidden = !state.reconnectNeeded || (state.authenticated && !state.retryAction);
  document.getElementById("archive-reconnect-message").textContent = state.authenticated ? "Подключение восстановлено. Повторите действие." : RECONNECT_MESSAGE;
  document.getElementById("archive-reconnect-login").hidden = state.authenticated;
  document.getElementById("archive-reconnect-retry").hidden = !state.authenticated || !state.retryAction;

}

function setMode(mode) {
  state.mode = mode;
  if (mode === "device" && !state.editorMode) { activateMode("announcement"); document.getElementById("import-zone").open = true; }
  const archive = mode === "archive";
  byId("archive-panel").hidden = !archive;
  byId("device-panel").hidden = archive;
  document.getElementById("processor-device-field").hidden = archive;
  document.getElementById("processor-device-ingest-actions").hidden = archive;
  byId("mode-archive").setAttribute("aria-pressed", String(archive));
  byId("mode-device").setAttribute("aria-pressed", String(!archive));
  document.getElementById("processor-save-incoming").disabled = archive || !getProcessorFiles().length;

  updatePublishState();
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

function closeAnnouncementWorkspace(clearProcessor = false) {
  state.sessionSequence++;
  if (clearProcessor) clearProcessorFiles();
  state.activeSession = null;
  state.activeManifest = null;
  state.announcementDraft = null;
  state.processorProvenance = [];
  state.candidate = null;
  byId("announcement-workspace").hidden = true;
  updatePublishState();
}

function selectedTrackIds() {
  return state.processorProvenance.map((source) => source.trackId);
}

function renderAnnouncementWorkspace() {
  const session = state.activeManifest;
  byId("announcement-workspace").hidden = state.editorMode !== "announcement";
  byId("announcement-identity").textContent = session ? `${session.title} · ${formatDate(session.recordedAt)}` : "Дорожки на этом устройстве";
  byId("announcement-status").textContent = "Исходники → Обработать запись → Прослушать → Сохранить / Скачать";
  updatePublishState();
}
function activateMode(mode) {
  state.editorMode = mode;
  document.getElementById("import-zone").open = false;
  document.body.dataset.editing = mode;
  document.getElementById("announcement-processor-card").hidden = mode !== "announcement";
  byId("announcement-workspace").hidden = mode !== "announcement";
  document.getElementById("active-editor-mode").textContent = `Сейчас открыто: ${mode === "speaker" ? "Финальная обработка спикерской" : "Редактирование для анонс-мейкера"}`;
  if (mode === "speaker") document.getElementById("processor-source-audio").pause();
  renderAnnouncementWorkspace(); renderImportFiles();
}

function updatePublishState() {
  const button = byId("publish-announcement");
  const reason = byId("publish-reason");
  if (!button || !reason) return;
  const session = state.activeManifest;
  let message = "";
  if (!session) message = "Сначала сохраните исходные записи в аудиоархив, затем обработайте запись заново.";
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
  if ([401, 403].includes(error?.status)) {
    state.authenticated = false; state.reconnectNeeded = true; state.retryAction = retry;
    updateSessionStatus();
    setArchiveStatus("Подключение к аудиоархиву истекло. Подключитесь снова, чтобы продолжить.");
    return;
  }
  setArchiveStatus(userError(error, fallback));
}

async function refreshSessions() {
  const sequence = ++state.refreshSequence, auth = state.authSequence;
  if (!baseUrl) {
    state.sessions = [];
    state.allSessions = [];
    renderSessions();
    renderResultArchive();
    setArchiveStatus("Шлюз аудиоархива ещё не настроен. Локальная обработка доступна в режиме «С устройства».");
    return;
  }
  if (!state.authenticated) {
    state.sessions = [];
    state.allSessions = [];
    renderSessions();
    renderResultArchive();
    setArchiveStatus("Подключите архив общим служебным паролем.");
    return;
  }
  setArchiveStatus("Загрузка записей и сохранённых результатов…");
  try {
    const [incoming, archived] = await Promise.all([gateway.listSessions("incoming"), gateway.listSessions("archived")]);
    if (sequence !== state.refreshSequence || auth !== state.authSequence) return;
    state.allSessions = mergeSessions(incoming.sessions, archived.sessions);
    state.sessions = state.allSessions;
    renderSessions();
    renderResultArchive();
    await showIncomplete();
    if (sequence !== state.refreshSequence || auth !== state.authSequence) return;
    setArchiveStatus(state.sessions.length ? "" : "Исходных записей пока нет.");
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

async function loadSession(session) {
  if (state.publicationController || state.uploadController) return;
  if (!await closeSpeakerEditor(false)) return;
  const sequence = ++state.sessionSequence, auth = state.authSequence;
  state.candidate = null;
  updatePublishState();
  setArchiveStatus(session.lifecycle.state === "archived" ? "Открытие записи, убранной из рабочего списка…" : "Загрузка и проверка исходных дорожек…");
  try {
    const complete = await gateway.getSession(session.id);
    if (sequence !== state.sessionSequence || auth !== state.authSequence) return;
    const draft = (await gateway.loadDraft(session.id, "announcement")).draft;
    if (sequence !== state.sessionSequence || auth !== state.authSequence) return;
    state.activeSession = session;
    state.activeManifest = complete;
    state.announcementDraft = draft;
    if (draft && draft.payloadSchema !== "announcement/v1") throw new Error("Неподдерживаемые сохранённые настройки; они не будут перезаписаны.");
    const order = state.announcementDraft?.payload?.trackIds || complete.sourceTracks.map((track) => track.trackId);
    const tracksById = new Map(complete.sourceTracks.map((track) => [track.trackId, track]));
    if (order.some((id) => !tracksById.has(id))) throw new Error("Проект обработки ссылается на отсутствующую дорожку.");
    const selectedTracks = order.map((id) => tracksById.get(id));
    state.processorProvenance = selectedTracks.map((track, index) => ({ trackId: track.trackId, blobId: track.blobId,
      ordinal: index + 1, sizeBytes: track.sizeBytes, sha256: track.sha256, mediaType: track.mediaType }));
    activateMode("announcement");
    renderAnnouncementWorkspace();
    if (complete.lifecycle.state === "incoming" && complete.sourceState === "available") {
      const allFiles = await reconstructSessionTracks(complete, gateway.sourcePartFetch(complete));
      if (sequence !== state.sessionSequence || auth !== state.authSequence) return;
      const filesById = new Map(complete.sourceTracks.map((track, index) => [track.trackId, allFiles[index]]));
      const files = order.map((id) => filesById.get(id));
      state.loadingArchive = true;
      loadProcessorFiles(files, state.processorProvenance, { sessionId: complete.id, sourceSessionRevision: complete.revision });
      state.loadingArchive = false;
      setArchiveStatus(`Загружено дорожек: ${files.length}. Целостность исходников проверена; запись не изменена.`);
      document.getElementById("processor-heading").scrollIntoView({ behavior: "smooth", block: "start" });
    } else {
      clearProcessorFiles();
      state.processorProvenance = [];
      state.candidate = null;
      setArchiveStatus(complete.lifecycle.state === "archived" ? "Запись убрана из рабочего списка. Верните её для обработки." :
        "Исходники удалены; доступны сохранённые результаты и метаданные.");
      byId("announcement-workspace").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  } catch (error) {
    if (sequence !== state.sessionSequence || auth !== state.authSequence) return;
    state.loadingArchive = false;
    onGatewayError(error, "Не удалось восстановить исходные дорожки.", () => { if (sequence === state.sessionSequence) return loadSession(session); });
  }
}

async function loadSpeakerSession(session) {
  if (state.publicationController || state.uploadController) return;
  if (!await protectSpeakerTransition()) return;
  if (session.lifecycle.state !== "incoming" || session.sourceState !== "available") {
    setArchiveStatus("Спикерская доступна только для исходной записи с доступными исходниками. Сначала верните запись для обработки.");
    return;
  }
  const sequence = ++state.sessionSequence, auth = state.authSequence;
  setArchiveStatus("Загрузка и проверка исходников для «Спикерская»…");
  try {
    const complete = await gateway.getSession(session.id);
    if (sequence !== state.sessionSequence || auth !== state.authSequence) return;
    const draft = (await gateway.loadDraft(session.id, "speaker")).draft;
    if (sequence !== state.sessionSequence || auth !== state.authSequence) return;
    if (complete.lifecycle.state !== "incoming" || complete.sourceState !== "available") throw new Error("Запись больше не доступна для редактирования.");
    const files = await reconstructSessionTracks(complete, gateway.sourcePartFetch(complete));
    if (sequence !== state.sessionSequence || auth !== state.authSequence) return;
    closeAnnouncementWorkspace(false);
    await closeSpeakerEditor(true);
    const project = new ProjectSave(gateway);
    state.activeManifest = complete;
    const opened = await openSpeakerEditor({
      session: complete,
      files,
      draft,
      saveDraft: ({ session, draft, payload, signal }) => withReconnect(() => project.save(session, draft, payload, signal)),
      onSaved: ({ session: updated }) => {
        state.activeSession = updated; state.activeManifest = updated;
        const index = state.sessions.findIndex((item) => item.id === updated.id);
        if (index >= 0) state.sessions[index] = updated;
        const allIndex = state.allSessions.findIndex((item) => item.id === updated.id);
        if (allIndex >= 0) state.allSessions[allIndex] = updated;
        renderSessions();
      }
    });
    if (opened) activateMode("speaker");
    setArchiveStatus(opened ? `Открыта работа «Спикерская»: ${complete.title}. Исходники проверены и не изменены.` : "Не удалось подготовить исходники для «Спикерская».");
  } catch (error) {
    if (sequence !== state.sessionSequence || auth !== state.authSequence) return;
    onGatewayError(error, "Не удалось открыть запись в «Спикерская».", () => { if (sequence === state.sessionSequence) return loadSpeakerSession(session); });
  }
}

function speakerSaveReason(snapshot = getSpeakerSaveState()) {
  const { session, draft, payload, candidate, saving } = snapshot;
  if (!session) return "Откройте финальную обработку спикерской.";
  if (session.kind === "local") return "Сохраните проект вместе с исходниками, затем создайте финальную версию заново.";
  if (candidate?.candidateType === "local-speaker") return "Создайте финальную версию заново для сохранения в аудиоархив.";
  if (session.lifecycle.state !== "incoming") return "Верните запись для обработки перед сохранением новой версии.";
  if (session.sourceState !== "available") return "Исходники этой записи недоступны.";
  if (saving) return "Идёт сохранение текущего локального результата.";
  if (!candidate) return "Сначала соберите и проверьте локальный MP3.";
  if (!draft || draft.draftRevision < 1) return "Сохраните текущий проект обработки перед сохранением результата.";
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
  const save = speakerId("archive-save");
  const reason = speakerId("archive-unavailable");
  if (!save || !reason) return;
  const message = speakerSaveReason(snapshot);
  save.disabled = Boolean(message);
  reason.textContent = message || "Результат готов к сохранению в архив «Спикерская».";
}

function speakerRecipe(candidate, draft) {
  const payload = structuredClone(candidate.payload);
  return {
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
  state.speakerSaveSnapshot = { session: snapshot.session, draft: snapshot.draft, candidate: snapshot.candidate };
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
      recipe: speakerRecipe(immutable.candidate, immutable.draft),
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
  const sequence = ++state.outputSequence, auth = state.authSequence;
  try {
    byId("results-status").textContent = "Загрузка и проверка сохранённого результата…";
    const metadata = workflow === "speaker" ? await gateway.getSpeakerOutput(session.id, output.outputId) : await gateway.getAnnouncementOutput(session.id, output.outputId);
    const file = workflow === "speaker" ? await reconstructSpeakerOutput(metadata, gateway.speakerPartFetch(metadata)) :
      await reconstructAnnouncementOutput(metadata, gateway.announcementPartFetch(metadata));
    if (sequence !== state.outputSequence || auth !== state.authSequence || state.resultArchive !== workflow) return;
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
      if ([401, 403].includes(error.status)) onGatewayError(error, RECONNECT_MESSAGE, async () => {
        if (sequence !== state.outputSequence || state.resultArchive !== workflow) return;
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
  heading.textContent = `${session.title} · Версия ${output.version}`;
  const metadata = document.createElement("p");
  metadata.className = "result-archive-item__metadata";
  metadata.textContent = `${formatDate(output.createdAt)} · ${formatBytes(output.sizeBytes)} · ${session.sourceState === "deleted" ? "исходники удалены" : session.lifecycle.state === "archived" ? "Убрана из рабочего списка" : "Готова к обработке"}`;
  details.append(heading, metadata);
  const actions = document.createElement("div");
  actions.className = "result-archive-item__actions";
  actions.append(button("Прослушать", () => openArchivedOutput(session, output, workflowName)));
  actions.append(button("Скачать", () => openArchivedOutput(session, output, workflowName, true)));
  actions.append(button("Удалить версию", () => openDeleteDialog(session, { kind: "output-version", workflow: workflowName, version: output.version }), "source-session-danger"));
  item.append(details, actions);
  return item;
}

function renderResultArchive() {
  const membership = { announcement: [], speaker: [] };
  for (const session of state.allSessions) {
    for (const name of Object.keys(membership)) {
      const workflow = session.workflows?.[name];
      if (!workflow || workflow.workflow !== name || !Array.isArray(workflow.outputs)) continue;
      for (const output of workflow.outputs) {
        if (!output || output.sessionId !== session.id || typeof output.outputId !== "string") continue;
        membership[name].push({ session, output });
      }
    }
  }
  for (const name of Object.keys(membership)) {
    const unique = new Map(membership[name].map((entry) => [`${entry.session.id}:${entry.output.outputId}`, entry]));
    membership[name] = [...unique.values()].sort((left, right) => String(right.output.createdAt).localeCompare(String(left.output.createdAt)));
    byId(`results-${name}-count`).textContent = String(membership[name].length);
    const list = byId(`results-${name}-list`);
    list.replaceChildren();
    if (!membership[name].length) {
      const empty = document.createElement("p");
      empty.textContent = "Сохранённых результатов пока нет.";
      list.append(empty);
    } else {
      for (const { session, output } of membership[name]) list.append(resultArchiveItem(session, name, output));
    }
  }
  if (!baseUrl) byId("results-status").textContent = "Архив результатов ещё не настроен.";
  else if (!state.authenticated) byId("results-status").textContent = "Подключите архив, чтобы увидеть сохранённые результаты.";
  else byId("results-status").textContent = `Открыт раздел «${workflowLabel(state.resultArchive)}».`;
}

function renderSessions() {
  const list = byId("list");
  list.replaceChildren();
  byId("count").hidden = !state.sessions.length;
  byId("count").textContent = `Найдено: ${state.sessions.length}.`;
  for (const session of state.sessions) {
    const card = document.createElement("article");
    card.className = "source-session-item"; card.dataset.sessionId = session.id;
    const heading = document.createElement("h3");
    heading.textContent = session.title;
    const metadata = document.createElement("p");
    metadata.className = "source-session-metadata";
    metadata.textContent = `${session.lifecycle.state === "incoming" ? "Готова к обработке" : "Убрана из рабочего списка"} · ${formatDate(session.recordedAt)} · ${originText[session.origin.kind] || "Источник не указан"} · ${session.sourceTracks.length} дорожек · ${session.sourceState === "available" ? "исходники доступны" : "исходники удалены"}`;
    const body = document.createElement("div");
    body.className = "source-session-item__body";
    const summary = document.createElement("div");
    summary.className = "source-session-item__summary";
    const workflows = document.createElement("p");
    workflows.className = "source-workflow-summary";
    for (const name of ["announcement", "speaker"]) {
      const badge = document.createElement("span");
      const workflow = session.workflows?.[name];
      const validWorkflow = workflow?.workflow === name && Array.isArray(workflow.outputs);
      badge.textContent = validWorkflow ? `${workflowLabel(name)} · готовых версий: ${workflow.outputs.length}${name === "speaker" && workflow.currentDraft ? " · сохранён проект" : ""}` : `${workflowLabel(name)}: данные недоступны`;
      workflows.append(badge);
    }
    const actions = document.createElement("div");
    actions.className = "source-session-actions";
    const open = button("Редактировать для анонс-мейкера", () => loadSession(session), "action-primary");
    open.disabled = !eligible(session); actions.append(open);
    if (session.lifecycle.state === "incoming" && session.sourceState === "available") {
      actions.append(button("Открыть финальную обработку спикерской", () => loadSpeakerSession(session), "speaker-open-action"));
    }
    if (session.lifecycle.state === "incoming") actions.append(button("Убрать из рабочего списка", async () => {
      if (session.id === speakerEditorSessionId() && !await closeSpeakerEditor(false)) return;
      mutateSession(() => gateway.setLifecycle(session.id, "archive", session.revision));
    }));
    else actions.append(button("Вернуть для обработки", () => mutateSession(() => gateway.setLifecycle(session.id, "restore", session.revision))));
    actions.append(button("Удаление…", () => openDeleteDialog(session), "source-session-danger"));
    summary.append(heading, metadata, workflows);
    body.append(summary, actions);
    card.append(body);
    list.append(card);
  }
}

async function ensureAuthenticated(action = async () => {}) {
  if (state.authenticated) return action();
  const connected = await new Promise(resolve => {
    if (state.afterLogin) { resolve(false); return; }
    state.afterLogin = resolve;
    byId("login-status").textContent = baseUrl ? RECONNECT_MESSAGE : "Шлюз аудиоархива ещё не настроен.";
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
    if (![401, 403].includes(error.status)) throw error;
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
  const opened = await openSpeakerEditor({ session: state.localContext, files, saveDraft: saveLocalProject, onSaved: ({ session }) => { state.activeManifest = session; updateSourceSaveState(); } });
  if (opened) activateMode("speaker");
}
async function openLocalAnnouncement() {
  if (state.publicationController || state.uploadController) return;
  if (!await closeSpeakerEditor(false)) return;
  ++state.sessionSequence;
  if (state.activeManifest) return loadSession(state.activeManifest);
  if (!getProcessorFiles().length) { setArchiveStatus("Выберите исходные дорожки в разделе Импорт."); return; }
  activateMode("announcement");
}
function workingFiles() { return state.editorMode === "speaker" && getSpeakerSaveState().ready ? getSpeakerSaveState().files : getProcessorFiles(); }
function updateSourceSaveState() {
  document.getElementById("processor-save-incoming").disabled = !workingFiles().length || Boolean(state.activeManifest || state.localProject?.finalized);
}
function renderImportFiles() {
  updateSourceSaveState();
  const list = document.getElementById("import-files"); list.replaceChildren();
  document.getElementById("import-summary").textContent = `Выбрано дорожек: ${workingFiles().length}`;
  for (const [index, file] of workingFiles().entries()) {
    const row = document.createElement("li"); row.append(document.createTextNode(`${file.name} · ${file.name.split('.').at(-1).toUpperCase()} · ${formatBytes(file.size)} `));
    row.append(button("Удалить", async () => {
      const files = workingFiles().filter((_, i) => i !== index);
      if (!await closeSpeakerEditor(false)) return;
      state.activeManifest = null; state.localContext = null; state.localProject = null;
      if (files.length) loadProcessorFiles(files); else clearProcessorFiles();
    })); list.append(row);
  }
}

function openIngestDialog(files = []) {
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
    if (state.pendingOrigin === "device") {
      state.localProject ||= new ProjectSave(gateway); state.localProject.finalized = session; state.localProject.plan = state.ingestionPlan;
      if (state.editorMode !== "speaker") {
        state.activeManifest = session;
        state.processorProvenance = state.ingestionPlan.tracks.map(t => ({ trackId: t.trackId, blobId: t.blobId, ordinal: t.ordinal, sizeBytes: t.sizeBytes, sha256: t.sha256, mediaType: t.mediaType }));
        state.loadingArchive = true; await bindProcessorSources(files, state.processorProvenance, { sessionId: session.id, sourceSessionRevision: session.revision }); state.loadingArchive = false;
        renderAnnouncementWorkspace();
      }
    }
    updateSourceSaveState();
    byId("ingest-status").textContent = "Исходные записи сохранены в аудиоархиве.";
    setTimeout(() => byId("ingest-dialog").close(), 400);
    await refreshSessions();
    setArchiveStatus("Исходные записи сохранены в аудиоархиве.");
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

async function openDeleteDialog(session, selection = null) {
  if (getSpeakerSaveState().saving && session.id === speakerEditorSessionId()) {
    setArchiveStatus("Сначала отмените или завершите передачу результата Спикерской.");
    return;
  }
  try {
    const preview = await gateway.dependencyPreview(session.id);
    state.deleteTarget = { session, selection, preview };
    byId("delete-summary").textContent = `${session.title}: исходников ${preview.sourceTracks}; версий «Анонс-мейкер» ${preview.announcementVersions}; версий «Спикерская» ${preview.speakerVersions}; сохранённых настроек обработки ${preview.drafts}; незавершённых сохранений ${preview.pendingAnnouncementPublications + (preview.pendingSpeakerSaves || 0)}. Другие уровни автоматически удалены не будут.`;
    byId("delete-technical").textContent = `Точный идентификатор записи: ${session.id}`;
    byId("delete-confirmation").value = "";
    byId("delete-status").textContent = "";
    for (const radio of byId("delete-form").elements["delete-level"]) radio.checked = false;
    if (selection?.kind === "output-version") {
      byId("delete-status").textContent = `Выбрана только версия ${selection.version} из раздела «${workflowLabel(selection.workflow)}».`;
    }
    byId("delete-dialog").showModal();
  } catch (error) {
    onGatewayError(error, "Не удалось получить зависимости.");
  }
}

async function submitDeletion(event) {
  event.preventDefault();
  const target = state.deleteTarget;
  if (!target) return;
  if (getSpeakerSaveState().saving && target.session.id === speakerEditorSessionId()) {
    byId("delete-status").textContent = "Сначала отмените или завершите передачу результата Спикерской.";
    return;
  }
  const selected = target.selection?.kind === "output-version" ? target.selection :
    { kind: byId("delete-form").elements["delete-level"].value };
  if (!selected.kind) {
    byId("delete-status").textContent = "Выберите уровень удаления.";
    return;
  }
  const body = { expectedRevision: target.session.revision, idempotencyKey: crypto.randomUUID(), confirmation: byId("delete-confirmation").value };
  try {
    byId("delete-submit").disabled = true;
    let result;
    if (selected.kind === "output-version") result = await gateway.deleteOutputVersion(target.session.id, selected.workflow, selected.version, body);
    else if (selected.kind === "announcement-series") result = await gateway.deleteOutputSeries(target.session.id, "announcement", body);
    else if (selected.kind === "speaker-series") result = await gateway.deleteOutputSeries(target.session.id, "speaker", body);
    else if (selected.kind === "sources") result = await gateway.deleteSources(target.session.id, body);
    else if (selected.kind === "purge") result = await gateway.purgeSession(target.session.id, body);
    else throw new Error("Неизвестный уровень удаления.");
    if (target.session.id === speakerEditorSessionId()) closeSpeakerEditor(true);
    clearOutputPlayback();
    if (state.activeManifest?.id === target.session.id) {
      if (result?.session) {
        state.activeManifest = result.session;
        state.activeSession = result.session;
        if (result.session.sourceState === "available") {
          updateProcessorProvenanceContext({ sessionId: result.session.id, sourceSessionRevision: result.session.revision });
        } else {
          clearProcessorFiles();
          state.processorProvenance = [];
        }
        renderAnnouncementWorkspace();
      } else if (result?.tombstone) closeAnnouncementWorkspace(true);
    }
    byId("delete-dialog").close();
    await refreshSessions();
  } catch (error) {
    byId("delete-status").textContent = userError(error, "Не удалось выполнить удаление. Обновите архив и повторите действие.");
  } finally {
    byId("delete-submit").disabled = false;
  }
}

async function showIncomplete() {
  const sequence = ++state.incompleteSequence;
  const container = byId("recovery-list");
  try {
    const result = await gateway.listIncomplete();
    if (sequence !== state.incompleteSequence) return;
    if (state.speakerResumeController) {
      renderSpeakerResumeStatus(state.speakerResumeStatus || "Продолжение передачи выполняется…", state.speakerResumeCancellable);
      return;
    }
    container.replaceChildren();
    for (const row of byId("list").querySelectorAll(".source-recovery-item")) row.remove();
    let associated = 0;
    for (const transaction of result.transactions || []) {
      const target = [...byId("list").querySelectorAll(".source-session-item")].find(row => row.dataset.sessionId === transaction.sessionId);
      if (!target) continue; // Unassociated operations and orphan diagnostics remain in Archive maintenance.
      associated++;
      const row = document.createElement("div"); row.className = "source-recovery-item";
      const title = document.createElement("strong"); title.textContent = "Требуется внимание"; row.append(title);
      const policy = recoveryPolicy(transaction);
      row.append(document.createTextNode(transaction.kind === "pending_delete" ? " Удаление не завершено. " :
        transaction.kind === "publication" ? ` Есть незавершённое сохранение Версии ${transaction.reservedVersion} в «${workflowLabel(transaction.workflow)}». ` : " Сохранение исходных записей не завершено. "));
      row.append(document.createTextNode(policy.local));
      if (transaction.kind === "publication" && transaction.workflow === "speaker" && !transaction.canFinalize &&
          ["uploading", "cancelled"].includes(transaction.state) && policy.actions.length) {
        row.append(button("Продолжить передачу", () => resumeSpeakerIncomplete(transaction)));
      }
      for (const [action, label] of policy.actions) row.append(button(label, () => recover(transaction.transactionId, action), action === "discard" ? "source-session-danger" : ""));
      target.append(row);
    }
    if (!associated) container.textContent = "Незавершённых сохранений для этих записей не найдено.";

  } catch (error) {
    if (sequence !== state.incompleteSequence) return;
    if (state.speakerResumeController) {
      renderSpeakerResumeStatus(state.speakerResumeStatus || "Продолжение передачи выполняется…", state.speakerResumeCancellable);
      return;
    }
    container.textContent = userError(error, "Не удалось проверить незавершённые операции.");
  }
}

async function recover(transactionId, action) {
  if (action === "discard" && !globalThis.confirm("Удалить только это незавершённое сохранение? Зарезервированный номер версии останется использованным.")) return;
  try {
    const latest = await gateway.listIncomplete(); const current = latest.transactions.find(t => t.transactionId === transactionId);
    if (!current || !recoveryPolicy(current).actions.some(([allowed]) => allowed === action)) throw Object.assign(new Error("Состояние операции изменилось"), { status: 409 });
    await gateway.recoverIncomplete(transactionId, action);
    await showIncomplete();
    await refreshSessions();
  } catch (error) {
    byId("recovery-list").textContent = userError(error, "Не удалось восстановить незавершённую операцию.");
  }
}

async function resumeSpeakerIncomplete(transaction) {
  if (state.speakerResumeController) {
    renderSpeakerResumeStatus(state.speakerResumeStatus || "Продолжение передачи уже выполняется.", state.speakerResumeCancellable);
    return;
  }
  const candidate = getSpeakerSaveState().candidate;
  if (!candidate) {
    byId("recovery-list").textContent = "Для продолжения передачи откройте эту запись в Спикерской и соберите точно тот же локальный результат.";
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
  editorIntentConsumed = true;
  const url = new URL(location.href);
  url.searchParams.delete("session"); url.searchParams.delete("workflow");
  history.replaceState(history.state, "", url);
  if (state.publicationController || state.speakerSaveController || state.speakerResumeController || state.uploadController || getSpeakerSaveState().saving) {
    setArchiveStatus("Сначала завершите текущую передачу, затем откройте ссылку из аудиоархива снова.");
    return;
  }
  if (getProcessorFiles().length && !globalThis.confirm("Заменить текущие локальные исходники записью из аудиоархива? Несохранённый результат будет потерян.")) return;
  const sequence = ++state.sessionSequence, auth = state.authSequence;
  try {
    const session = await gateway.getSession(intent.sessionId);
    if (sequence !== state.sessionSequence || !state.authenticated) return;
    if (!validateSessionManifest(session) || session.id !== intent.sessionId) throw new Error("Некорректные сведения о записи.");
    if (!eligible(session)) {
      setArchiveStatus("Новая обработка недоступна: верните запись для обработки; исходники должны быть доступны. Откройте аудиоархив для просмотра результатов.");
      return;
    }
    if (intent.workflow === "speaker") await loadSpeakerSession(session);
    else await loadSession(session);
  } catch (error) {
    if (sequence === state.sessionSequence) onGatewayError(error, "Запись по ссылке недоступна или удалена. Откройте аудиоархив.");
  }
}

async function initialize() {
  setMode("archive");
  updateSessionStatus();
  if (baseUrl) {
    try {
      await gateway.configuration();
      await gateway.sessionStatus();
      state.authenticated = true;
    } catch {
      state.authenticated = false;
    }
  }
  updateSessionStatus();
  await refreshSessions();

  await consumeEditorIntent();
}

byId("mode-archive").addEventListener("click", () => setMode("archive"));
byId("mode-device").addEventListener("click", () => setMode("device"));
byId("results-announcement").addEventListener("click", () => setResultArchive("announcement"));
byId("results-speaker").addEventListener("click", () => setResultArchive("speaker"));
byId("refresh").addEventListener("click", refreshSessions);

byId("authenticate").addEventListener("click", () => ensureAuthenticated(refreshSessions).catch(() => {}));

document.getElementById("processor-save-incoming").addEventListener("click", () => ensureAuthenticated(() => openIngestDialog(workingFiles())).catch(() => {}));
window.addEventListener("audio-processor-selection", (event) => {
  if (!state.loadingArchive && state.editorMode !== "speaker" && event.detail.files.length && !event.detail.provenance.length) {
    setMode("device"); state.activeManifest = null; state.processorProvenance = [];
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
speakerId("archive-save").addEventListener("click", openSpeakerSaveDialog);
speakerId("save-form").addEventListener("submit", submitSpeakerSave);
speakerId("save-cancel").addEventListener("click", cancelSpeakerSaveDialog);
speakerId("save-dialog").addEventListener("cancel", (event) => {
  if (!state.speakerSaveController) return;
  event.preventDefault();
  cancelSpeakerSaveDialog();
});

byId("announcement-close").addEventListener("click", () => closeAnnouncementWorkspace(true));
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
  byId("login-status").textContent = "Проверка пароля…";
  try {
    await gateway.login(password);
    if (auth !== state.authSequence) return;
    state.authenticated = true;
    byId("password").value = "";
    byId("login-dialog").close();
    updateSessionStatus();
    const action = state.afterLogin;
    state.afterLogin = null;
    if (action) action(true);
    await consumeEditorIntent();
  } catch (error) {
    byId("login-status").textContent = userError(error, "Не удалось подключить архив. Проверьте пароль и повторите действие.");
  } finally {
    submit.disabled = false;
    byId("password").value = "";
  }
});
byId("login-cancel").addEventListener("click", () => { ++state.authSequence; state.afterLogin?.(false); state.afterLogin = null; byId("login-dialog").close(); });
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
byId("delete-cancel").addEventListener("click", () => byId("delete-dialog").close());
window.addEventListener("pagehide", clearOutputPlayback);

globalThis.meserAudioArchiveDrafts = Object.freeze({
  load: (sessionId, workflow) => gateway.loadDraft(sessionId, workflow),
  save: (sessionId, workflow, envelope) => gateway.saveDraft(sessionId, workflow, envelope)
});

await initialize();

document.getElementById("open-local-speaker").addEventListener("click", openLocalSpeaker);
document.getElementById("open-local-announcement").addEventListener("click", openLocalAnnouncement);
setProcessorSelectionGuard(async () => { if (state.publicationController || state.uploadController) return false; if (!await closeSpeakerEditor(false)) return false; ++state.sessionSequence; return true; });
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
  if (auth === state.authSequence && [401, 403].includes(response.status) && !String(url).endsWith("/session/login")) {
    state.authenticated = false; state.reconnectNeeded = true; updateSessionStatus(); setArchiveStatus(RECONNECT_MESSAGE);
  }
  return response;
};
for (const dialog of [byId("ingest-dialog"), byId("publication-dialog"), speakerId("save-dialog")]) {
  const reconnect = button("Подключиться снова", () => ensureAuthenticated().catch(() => {}));
  dialog.append(reconnect);
}

window.addEventListener("speaker-editor-closed", () => { if (state.editorMode === "speaker") { state.editorMode = null; delete document.body.dataset.editing; } });

document.getElementById("archive-reconnect-login").addEventListener("click", () => ensureAuthenticated().catch(() => {}));
document.getElementById("archive-reconnect-retry").addEventListener("click", async () => {
  const action = state.retryAction; state.retryAction = null; updateSessionStatus();
  try { await action?.(); } catch (error) { onGatewayError(error, "Данные изменились. Выберите запись и повторите действие."); }
});
