import { AudioArchiveGateway, MAX_AUDIO_SESSION_BYTES, reconstructAnnouncementOutput, reconstructSessionTracks } from "./audio-archive-client.mjs";
import { clearProcessorFiles, getProcessorFiles, getProcessorResult, loadProcessorFiles, updateProcessorProvenanceContext } from "./audio-processor.mjs";

const byId = (id) => document.getElementById(`source-session-${id}`);
const baseUrl = globalThis.__MESER_AUDIO_ARCHIVE_GATEWAY__ ||
  document.querySelector('meta[name="audio-archive-gateway"]')?.content.trim().replace(/\/$/, "") || "";
const gateway = new AudioArchiveGateway(baseUrl);
const state = {
  authenticated: false,
  sessions: [],
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
  outputUrl: null
};

const statusText = Object.freeze({ new: "Новая", in_progress: "В работе", result_ready: "Результат готов" });
const originText = Object.freeze({ manual: "Создана вручную", device: "С устройства", zoom_webhook: "Zoom" });

function formatBytes(bytes) {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(bytes / (1024 * 1024)) + " МБ";
}

function formatDate(value) {
  if (!value) return "Дата записи не указана";
  return new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function setArchiveStatus(message) {
  byId("status").textContent = message;
}

function updateSessionStatus() {
  byId("session-status").textContent = !baseUrl ? "Шлюз входящего архива ещё не настроен." :
    state.authenticated ? "Общий защищённый сеанс архива активен." : "Для архива требуется общий служебный пароль.";
  byId("authenticate").hidden = state.authenticated;
  byId("maintenance").hidden = !state.authenticated;
}

function setMode(mode) {
  state.mode = mode;
  const archive = mode === "archive";
  byId("archive-panel").hidden = !archive;
  byId("device-panel").hidden = archive;
  document.getElementById("processor-device-field").hidden = archive;
  byId("mode-archive").setAttribute("aria-pressed", String(archive));
  byId("mode-device").setAttribute("aria-pressed", String(!archive));
  document.getElementById("processor-save-incoming").disabled = archive || !getProcessorFiles().length;
  if (!archive) closeAnnouncementWorkspace();
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
  if (clearProcessor) clearProcessorFiles();
  clearOutputPlayback();
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
  const session = state.activeManifest || state.activeSession;
  byId("announcement-workspace").hidden = !session;
  if (!session) return;
  byId("announcement-identity").textContent = `${session.title} · ${session.id} · ревизия ${session.revision}`;
  const list = byId("announcement-tracks");
  list.replaceChildren();
  for (const source of state.processorProvenance) {
    const track = session.sourceTracks.find((item) => item.trackId === source.trackId);
    const item = document.createElement("li");
    item.textContent = track ? `${track.originalName} · ${formatBytes(track.sizeBytes)} · ${track.trackId}` : source.trackId;
    list.append(item);
  }
  const archived = session.lifecycle.state === "archived";
  byId("announcement-save").disabled = archived || session.sourceState !== "available" || !state.processorProvenance.length;
  const revision = state.announcementDraft?.draftRevision || 0;
  byId("announcement-status").textContent = archived ? "Архивированная запись доступна только для прослушивания и скачивания результатов. Сначала верните её во входящие." :
    revision ? `Общий черновик сохранён, ревизия ${revision}.` : "Общий черновик ещё не сохранён.";
  updatePublishState();
}

function updatePublishState() {
  const button = byId("publish-announcement");
  const reason = byId("publish-reason");
  if (!button || !reason) return;
  const session = state.activeManifest;
  const draftIds = state.announcementDraft?.payload?.trackIds || [];
  const selected = selectedTrackIds();
  let message = "";
  if (!session) message = "Публикация доступна только для активной Source Session из архива.";
  else if (session.lifecycle.state !== "incoming") message = "Верните Source Session во входящие перед публикацией.";
  else if (session.sourceState !== "available") message = "Исходники Source Session недоступны.";
  else if (!state.candidate) message = "Сначала создайте локальный результат обработки.";
  else if (!state.candidate.sources.length) message = "Локальный файл без архивного происхождения публиковать нельзя.";
  else if (state.candidate.provenance?.sessionId !== session.id) message = "Происхождение локального результата не совпадает с активной Source Session.";
  else if (state.candidate.provenance?.sourceSessionRevision !== session.revision) message = "Source Session или draft изменились после обработки; обработайте дорожки заново.";
  else if (!state.announcementDraft || JSON.stringify(draftIds) !== JSON.stringify(selected)) message = "Сохраните общий черновик с текущим порядком дорожек.";
  button.disabled = Boolean(message) || Boolean(state.publicationController);
  reason.textContent = message || "Результат готов к проверяемой публикации через защищённый шлюз.";
}

function button(label, action, className = "") {
  const element = document.createElement("button");
  element.type = "button";
  element.textContent = label;
  if (className) element.className = className;
  element.addEventListener("click", action);
  return element;
}

function onGatewayError(error, fallback) {
  if (error?.status === 401) {
    state.authenticated = false;
    updateSessionStatus();
    setArchiveStatus("Сеанс архива истёк. Подключите архив снова.");
    return;
  }
  setArchiveStatus(error instanceof Error ? error.message : fallback);
}

async function refreshSessions() {
  if (!baseUrl) {
    state.sessions = [];
    renderSessions();
    setArchiveStatus("Шлюз входящего архива ещё не настроен. Локальная обработка доступна в режиме «С устройства».");
    return;
  }
  if (!state.authenticated) {
    state.sessions = [];
    renderSessions();
    setArchiveStatus("Подключите архив общим служебным паролем.");
    return;
  }
  setArchiveStatus("Загрузка Source Sessions…");
  try {
    const result = await gateway.listSessions(byId("lifecycle").value);
    state.sessions = Array.isArray(result.sessions) ? result.sessions : [];
    renderSessions();
    setArchiveStatus(state.sessions.length ? "" : byId("lifecycle").value === "incoming" ? "Входящих записей пока нет." : "Архивированных записей пока нет.");
  } catch (error) {
    state.sessions = [];
    renderSessions();
    onGatewayError(error, "Не удалось загрузить входящий архив.");
  }
}

async function mutateSession(action) {
  try {
    setArchiveStatus("Сохранение изменений…");
    const result = await action();
    const updated = result?.session || result;
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
  setArchiveStatus(session.lifecycle.state === "archived" ? "Открытие архивированного Announcement workspace…" : "Загрузка и проверка исходных дорожек…");
  try {
    if (state.activeManifest?.id !== session.id) clearOutputPlayback();
    const complete = await gateway.getSession(session.id);
    state.activeSession = session;
    state.activeManifest = complete;
    state.announcementDraft = (await gateway.loadDraft(session.id, "announcement")).draft;
    const order = state.announcementDraft?.payload?.trackIds || complete.sourceTracks.map((track) => track.trackId);
    const tracksById = new Map(complete.sourceTracks.map((track) => [track.trackId, track]));
    if (order.some((id) => !tracksById.has(id))) throw new Error("Общий Announcement draft ссылается на отсутствующую дорожку.");
    const selectedTracks = order.map((id) => tracksById.get(id));
    state.processorProvenance = selectedTracks.map((track, index) => ({ trackId: track.trackId, blobId: track.blobId,
      ordinal: index + 1, sizeBytes: track.sizeBytes, sha256: track.sha256, mediaType: track.mediaType }));
    renderAnnouncementWorkspace();
    if (complete.lifecycle.state === "incoming" && complete.sourceState === "available") {
      const allFiles = await reconstructSessionTracks(complete, gateway.sourcePartFetch(complete));
      const filesById = new Map(complete.sourceTracks.map((track, index) => [track.trackId, allFiles[index]]));
      const files = order.map((id) => filesById.get(id));
      state.loadingArchive = true;
      loadProcessorFiles(files, state.processorProvenance, { sessionId: complete.id, sourceSessionRevision: complete.revision });
      state.loadingArchive = false;
      setArchiveStatus(`Загружено дорожек: ${files.length}. Байты и SHA-256 проверены; запись не изменена.`);
      document.getElementById("processor-heading").scrollIntoView({ behavior: "smooth", block: "start" });
    } else {
      clearProcessorFiles();
      state.processorProvenance = [];
      state.candidate = null;
      setArchiveStatus(complete.lifecycle.state === "archived" ? "Архивированная запись открыта без загрузки в обработчик." :
        "Исходники удалены; доступны сохранённые результаты и метаданные.");
      byId("announcement-workspace").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  } catch (error) {
    state.loadingArchive = false;
    onGatewayError(error, "Не удалось восстановить исходные дорожки.");
  }
}

async function openAnnouncementOutput(session, output, downloadOnly = false) {
  try {
    if (state.activeManifest?.id !== session.id) {
      state.activeSession = session;
      state.activeManifest = await gateway.getSession(session.id);
      state.announcementDraft = (await gateway.loadDraft(session.id, "announcement")).draft;
      state.processorProvenance = [];
      state.candidate = null;
      renderAnnouncementWorkspace();
    }
    byId("announcement-status").textContent = "Загрузка и проверка опубликованного результата…";
    const metadata = await gateway.getAnnouncementOutput(session.id, output.outputId);
    const file = await reconstructAnnouncementOutput(metadata, gateway.announcementPartFetch(metadata));
    if (state.outputUrl) URL.revokeObjectURL(state.outputUrl);
    state.outputUrl = URL.createObjectURL(file);
    const link = byId("announcement-download");
    link.href = state.outputUrl;
    link.download = file.name;
    byId("announcement-playback-name").textContent = `Версия ${output.version} · ${file.name} · ${formatBytes(file.size)}`;
    byId("announcement-audio").src = state.outputUrl;
    byId("announcement-playback").hidden = false;
    byId("announcement-status").textContent = "Байты частей и целого результата проверены по SHA-256.";
    if (downloadOnly) link.click();
  } catch (error) {
    byId("announcement-status").textContent = error.message;
  }
}

function workflowCard(session, name, label) {
  const workflow = session.workflows[name];
  const section = document.createElement("section");
  section.className = "source-workflow";
  const heading = document.createElement("h4");
  heading.textContent = label;
  const current = document.createElement("p");
  current.textContent = `Статус: ${statusText[workflow.status] || workflow.status}`;
  const actions = document.createElement("div");
  actions.className = "source-session-actions";
  if (name === "announcement") actions.append(button("Открыть workspace", () => loadSession(session)));
  else {
    if (workflow.status === "new") actions.append(button("Начать работу", () => mutateSession(() => gateway.updateWorkflow(session.id, name, session.revision, "in_progress"))));
    if (workflow.status === "in_progress") actions.append(button("Вернуть в новые", () => mutateSession(() => gateway.updateWorkflow(session.id, name, session.revision, "new"))));
  }
  for (const output of workflow.outputs || []) {
    const outputRow = document.createElement("p");
    outputRow.className = "source-output-version";
    outputRow.append(document.createTextNode(`Версия ${output.version} · ${formatDate(output.createdAt)} `));
    if (name === "announcement") {
      outputRow.append(button("Слушать", () => openAnnouncementOutput(session, output)));
      outputRow.append(document.createTextNode(" "));
      outputRow.append(button("Скачать", () => openAnnouncementOutput(session, output, true)));
      outputRow.append(document.createTextNode(" "));
    }
    outputRow.append(button("Удалить версию", () => openDeleteDialog(session, { kind: "output-version", workflow: name, version: output.version })));
    section.append(outputRow);
  }
  section.prepend(heading, current, actions);
  return section;
}

function renderSessions() {
  const list = byId("list");
  list.replaceChildren();
  byId("count").hidden = !state.sessions.length;
  byId("count").textContent = `Найдено: ${state.sessions.length}.`;
  for (const session of state.sessions) {
    const card = document.createElement("article");
    card.className = "source-session-item";
    const heading = document.createElement("h3");
    heading.textContent = session.title;
    const metadata = document.createElement("p");
    metadata.className = "source-session-metadata";
    metadata.textContent = `${formatDate(session.recordedAt)} · ${originText[session.origin.kind] || session.origin.kind} · ${session.sourceTracks.length} дорожек · ${session.sourceState === "available" ? "исходники доступны" : "исходники удалены"}`;
    const workflows = document.createElement("div");
    workflows.className = "source-workflows";
    workflows.append(workflowCard(session, "announcement", "Объявление"), workflowCard(session, "speaker", "Спикерская"));
    const actions = document.createElement("div");
    actions.className = "source-session-actions";
    const open = button(session.lifecycle.state === "archived" ? "Открыть результаты" : "Открыть Announcement", () => loadSession(session));
    actions.append(open);
    if (session.lifecycle.state === "incoming") actions.append(button("Архивировать", () => mutateSession(() => gateway.setLifecycle(session.id, "archive", session.revision))));
    else actions.append(button("Вернуть во входящие", () => mutateSession(() => gateway.setLifecycle(session.id, "restore", session.revision))));
    actions.append(button("Удаление…", () => openDeleteDialog(session), "source-session-danger"));
    card.append(heading, metadata, workflows, actions);
    list.append(card);
  }
}

function ensureAuthenticated(action) {
  if (state.authenticated) {
    action();
    return;
  }
  state.afterLogin = action;
  byId("login-status").textContent = baseUrl ? "" : "Шлюз входящего архива ещё не настроен.";
  byId("password").value = "";
  byId("login-dialog").showModal();
  byId("password").focus();
}

function openIngestDialog(files = []) {
  state.pendingFiles = Array.from(files);
  state.pendingOrigin = state.pendingFiles.length ? "device" : "manual";
  state.retryKey = crypto.randomUUID();
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
    await gateway.ingestFiles({
      files, title, recordedAt: recordedValue ? new Date(recordedValue).toISOString() : null,
      origin: state.pendingOrigin,
      idempotencyKey: state.retryKey, signal: state.uploadController.signal,
      onProgress: ({ uploadedBytes, totalBytes, uploadedParts, totalParts }) => {
        byId("ingest-progress").value = Math.round(uploadedBytes / totalBytes * 100);
        byId("ingest-status").textContent = `Загружено частей: ${uploadedParts} из ${totalParts}.`;
      }
    });
    byId("ingest-status").textContent = "Входящая запись создана.";
    setTimeout(() => byId("ingest-dialog").close(), 400);
    await refreshSessions();
  } catch (error) {
    byId("ingest-status").textContent = error?.name === "AbortError" ?
      "Загрузка остановлена. Незавершённая транзакция сохранена для безопасного повтора." : `${error.message} Локальные файлы сохранены; можно повторить.`;
  } finally {
    state.uploadController = null;
    byId("ingest-submit").disabled = false;
    byId("ingest-files").disabled = false;
  }
}

async function saveAnnouncementDraft() {
  if (!state.activeManifest || !state.processorProvenance.length) return;
  byId("announcement-status").textContent = "Сохранение общего Announcement draft…";
  try {
    const result = await gateway.saveDraft(state.activeManifest.id, "announcement", {
      schemaVersion: 1,
      expectedDraftRevision: state.announcementDraft?.draftRevision || 0,
      expectedSourceSessionRevision: state.activeManifest.revision,
      payloadSchema: "announcement/v1",
      payload: { trackIds: selectedTrackIds() },
      idempotencyKey: crypto.randomUUID()
    });
    state.announcementDraft = result.draft;
    state.activeManifest = result.session;
    updateProcessorProvenanceContext({ sessionId: result.session.id, sourceSessionRevision: result.session.revision });
    const index = state.sessions.findIndex((item) => item.id === result.session.id);
    if (index >= 0) state.sessions[index] = result.session;
    renderAnnouncementWorkspace();
  } catch (error) {
    byId("announcement-status").textContent = error.status === 409 ? `${error.message} Перезагрузите Source Session перед повтором.` : error.message;
  }
}

function openPublicationDialog() {
  updatePublishState();
  if (byId("publish-announcement").disabled) return;
  const nextVersion = state.activeManifest.workflows.announcement.nextVersion;
  const mode = { passthrough: "без изменения байтов", processed_single: "одна обработанная дорожка", mixed_multi: "сведение нескольких дорожек" }[state.candidate.processing.mode];
  const names = state.processorProvenance.map((source) => state.activeManifest.sourceTracks.find((track) => track.trackId === source.trackId)?.originalName || source.trackId).join(", ");
  byId("publication-summary").textContent = `${state.activeManifest.title} (${state.activeManifest.id}) · дорожки: ${names} · режим: ${mode} · результат: ${state.candidate.result.resultDurationSeconds.toFixed(2)} с, ${formatBytes(state.candidate.blob.size)}, ${state.candidate.result.mediaType}, файл ${state.candidate.result.presentationFilename} · предварительно версия ${nextVersion}.`;
  byId("publication-status").textContent = "Проверьте Source Session, порядок дорожек и локальный результат.";
  byId("publication-progress").hidden = true;
  byId("publication-submit").disabled = false;
  byId("publication-cancel").textContent = "Отмена";
  byId("publication-dialog").showModal();
}

async function submitPublication(event) {
  event.preventDefault();
  if (!state.activeManifest || !state.announcementDraft || !state.candidate) return;
  state.publicationKey ||= crypto.randomUUID();
  state.publicationController = new AbortController();
  state.publicationTransactionId = null;
  byId("publication-submit").disabled = true;
  byId("publication-cancel").textContent = "Остановить";
  byId("publication-progress").hidden = false;
  byId("publication-progress").value = 0;
  byId("publication-status").textContent = "Подготовка проверяемых частей результата…";
  updatePublishState();
  const candidate = getProcessorResult();
  let completed = false;
  try {
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
        byId("publication-progress").value = Math.round(uploadedBytes / totalBytes * 100);
        byId("publication-status").textContent = `Версия ${reservedVersion}: загружено частей ${uploadedParts} из ${totalParts}.`;
      }
    });
    byId("publication-progress").value = 100;
    byId("publication-status").textContent = `Объявление версии ${result.output.version} опубликовано.`;
    state.publicationKey = null;
    state.publicationTransactionId = null;
    state.activeManifest = await gateway.getSession(state.activeManifest.id);
    renderAnnouncementWorkspace();
    byId("announcement-status").textContent = `Объявление версии ${result.output.version} опубликовано; draft сохранён.`;
    await refreshSessions();
    completed = true;
    setTimeout(() => byId("publication-dialog").close(), 500);
  } catch (error) {
    byId("publication-status").textContent = error?.name === "AbortError" ?
      "Передача остановлена. Зарезервированная версия и job сохранены для безопасного повтора или удаления." : `${error.message} Повтор использует тот же job и ту же зарезервированную версию.`;
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
      try { await gateway.cancelPublication(transactionId); } catch (error) { byId("publication-status").textContent = error.message; }
    }
    return;
  }
  byId("publication-dialog").close();
}

async function openDeleteDialog(session, selection = null) {
  try {
    const preview = await gateway.dependencyPreview(session.id);
    state.deleteTarget = { session, selection, preview };
    byId("delete-summary").textContent = `Source Session ${session.id}: исходников ${preview.sourceTracks}; версий «Объявление» ${preview.announcementVersions}; версий «Спикерская» ${preview.speakerVersions}; черновиков ${preview.drafts}; незавершённых Announcement publications ${preview.pendingAnnouncementPublications}. Удаление не затронет другие уровни автоматически.`;
    byId("delete-confirmation").value = "";
    byId("delete-status").textContent = "";
    for (const radio of byId("delete-form").elements["delete-level"]) radio.checked = false;
    if (selection?.kind === "output-version") {
      byId("delete-status").textContent = `Выбрана только версия ${selection.version} (${selection.workflow}).`;
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
    byId("delete-status").textContent = error.message;
  } finally {
    byId("delete-submit").disabled = false;
  }
}

async function showIncomplete() {
  const container = byId("recovery-list");
  container.replaceChildren();
  try {
    const result = await gateway.listIncomplete();
    for (const transaction of result.transactions || []) {
      const row = document.createElement("div");
      row.className = "source-recovery-item";
      if (transaction.kind === "ingestion") {
        row.append(document.createTextNode(`ingestion · ${transaction.state} · ${transaction.transactionId} · загружено частей ${transaction.uploadedParts} из ${transaction.totalParts}. `));
        if (transaction.canFinalize) row.append(button("Завершить", () => recover(transaction.transactionId, "resume")));
        else row.append(document.createTextNode("Для безопасного продолжения нужны исходные файлы и исходный ключ операции. Если окно загрузки уже закрыто, удалите незавершённую операцию и создайте новую."));
        row.append(button("Удалить незавершённое", () => recover(transaction.transactionId, "discard"), "source-session-danger"));
      } else if (transaction.kind === "publication") {
        row.append(document.createTextNode(`publication · ${transaction.state} · ${transaction.transactionId} · версия ${transaction.reservedVersion} · загружено частей ${transaction.uploadedParts} из ${transaction.totalParts}. `));
        if (transaction.canFinalize) row.append(button("Завершить", () => recover(transaction.transactionId, "resume")));
        else row.append(document.createTextNode("Для продолжения нужен локальный результат и исходный ключ этой публикации. "));
        row.append(button("Удалить job", () => recover(transaction.transactionId, "discard"), "source-session-danger"));
      } else {
        row.append(document.createTextNode(`${transaction.kind} · ${transaction.state} · ${transaction.transactionId} `));
        row.append(button("Продолжить", () => recover(transaction.transactionId, "resume")));
      }
      container.append(row);
    }
    for (const orphan of result.orphans || []) {
      const row = document.createElement("p");
      row.textContent = `Кандидат на восстановление: Release ${orphan.tag} (${orphan.draft ? "draft" : "опубликован"}). Автоматически не удалён.`;
      container.append(row);
    }
    if (!container.childElementCount) container.textContent = "Незавершённых операций и orphan-кандидатов не найдено.";
  } catch (error) {
    container.textContent = error.message;
  }
}

async function recover(transactionId, action) {
  try {
    await gateway.recoverIncomplete(transactionId, action);
    await showIncomplete();
    await refreshSessions();
  } catch (error) {
    byId("recovery-list").textContent = error.message;
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
}

byId("mode-archive").addEventListener("click", () => setMode("archive"));
byId("mode-device").addEventListener("click", () => setMode("device"));
byId("refresh").addEventListener("click", refreshSessions);
byId("lifecycle").addEventListener("change", refreshSessions);
byId("authenticate").addEventListener("click", () => ensureAuthenticated(refreshSessions));
byId("create").addEventListener("click", () => ensureAuthenticated(() => openIngestDialog()));
document.getElementById("processor-save-incoming").addEventListener("click", () => ensureAuthenticated(() => openIngestDialog(getProcessorFiles())));
window.addEventListener("audio-processor-selection", (event) => {
  if (!state.loadingArchive && event.detail.files.length && !event.detail.provenance.length) setMode("device");
  if (event.detail.provenance.length) {
    state.processorProvenance = event.detail.provenance;
    renderAnnouncementWorkspace();
  }
  document.getElementById("processor-save-incoming").disabled = state.mode !== "device" || !event.detail.files.length;
  updatePublishState();
});
window.addEventListener("audio-processor-result", (event) => {
  state.candidate = event.detail.candidate;
  state.publicationKey = crypto.randomUUID();
  updatePublishState();
});
byId("announcement-save").addEventListener("click", saveAnnouncementDraft);
byId("announcement-close").addEventListener("click", () => closeAnnouncementWorkspace(true));
byId("publish-announcement").addEventListener("click", openPublicationDialog);
byId("publication-form").addEventListener("submit", submitPublication);
byId("publication-cancel").addEventListener("click", cancelPublicationDialog);

byId("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const password = byId("password").value;
  byId("login-status").textContent = "Проверка пароля…";
  try {
    await gateway.login(password);
    state.authenticated = true;
    byId("password").value = "";
    byId("login-dialog").close();
    updateSessionStatus();
    const action = state.afterLogin;
    state.afterLogin = null;
    if (action) action();
  } catch (error) {
    byId("login-status").textContent = error.message;
  } finally {
    byId("password").value = "";
  }
});
byId("login-cancel").addEventListener("click", () => { state.afterLogin = null; byId("login-dialog").close(); });
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
byId("incomplete").addEventListener("click", showIncomplete);
byId("rebuild").addEventListener("click", async () => {
  try {
    const result = await gateway.rebuildCatalog();
    byId("recovery-list").textContent = `Каталог пересобран: ${result.catalog.entries.length}. Orphan-кандидатов: ${result.orphans.length}.`;
    await refreshSessions();
  } catch (error) {
    byId("recovery-list").textContent = error.message;
  }
});
window.addEventListener("pagehide", clearOutputPlayback);

globalThis.meserAudioArchiveDrafts = Object.freeze({
  load: (sessionId, workflow) => gateway.loadDraft(sessionId, workflow),
  save: (sessionId, workflow, envelope) => gateway.saveDraft(sessionId, workflow, envelope)
});

await initialize();
