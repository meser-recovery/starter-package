import { AudioArchiveGateway, MAX_AUDIO_SESSION_BYTES, reconstructAnnouncementOutput, reconstructSessionTracks } from "./audio-archive-client.mjs";
import { clearProcessorFiles, getProcessorFiles, getProcessorResult, loadProcessorFiles, updateProcessorProvenanceContext } from "./audio-processor.mjs";
import { closeSpeakerEditor, openSpeakerEditor, speakerEditorSessionId } from "./speaker-editor.mjs";

const byId = (id) => document.getElementById(`source-session-${id}`);
const baseUrl = globalThis.__MESER_AUDIO_ARCHIVE_GATEWAY__ ||
  document.querySelector('meta[name="audio-archive-gateway"]')?.content.trim().replace(/\/$/, "") || "";
const gateway = new AudioArchiveGateway(baseUrl);
const state = {
  authenticated: false,
  sessions: [],
  allSessions: [],
  resultArchive: "announcement",
  refreshSequence: 0,
  sessionSequence: 0,
  outputSequence: 0,
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
  if (error?.status === 401 || error?.status === 403) return "Подключение к архиву истекло или недостаточно прав. Подключите архив снова.";
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
  byId("session-status").textContent = !baseUrl ? "Шлюз входящего архива ещё не настроен." :
    state.authenticated ? "Общий защищённый сеанс архива активен." : "Для архива требуется общий служебный пароль.";
  byId("authenticate").hidden = state.authenticated;
  byId("maintenance").hidden = !state.authenticated;
}

function setMode(mode) {
  if (mode === "device" && !closeSpeakerEditor(false)) return;
  state.mode = mode;
  const archive = mode === "archive";
  byId("archive-panel").hidden = !archive;
  byId("device-panel").hidden = archive;
  document.getElementById("processor-device-field").hidden = archive;
  document.getElementById("processor-device-ingest-actions").hidden = archive;
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
  const session = state.activeManifest || state.activeSession;
  byId("announcement-workspace").hidden = !session;
  if (!session) return;
  byId("announcement-identity").textContent = `${session.title} · ${formatDate(session.recordedAt)} · активная работа «Анонс-мейкер»`;
  byId("announcement-technical").textContent = `Идентификатор записи: ${session.id}. Ревизия: ${session.revision}.`;
  const list = byId("announcement-tracks");
  list.replaceChildren();
  for (const source of state.processorProvenance) {
    const track = session.sourceTracks.find((item) => item.trackId === source.trackId);
    const item = document.createElement("li");
    item.textContent = track ? `${track.originalName} · ${formatBytes(track.sizeBytes)}` : "Дорожка недоступна";
    list.append(item);
  }
  const archived = session.lifecycle.state === "archived";
  byId("announcement-save").disabled = archived || session.sourceState !== "available" || !state.processorProvenance.length;
  const revision = state.announcementDraft?.draftRevision || 0;
  byId("announcement-status").textContent = archived ? "Архивированная запись доступна только для прослушивания и скачивания результатов. Сначала верните её во входящие." :
    revision ? `Черновик обработки сохранён, ревизия ${revision}.` : "Черновик обработки ещё не сохранён.";
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
  if (!session) message = "Сохранение доступно только для активной входящей записи из архива исходников.";
  else if (session.lifecycle.state !== "incoming") message = "Верните запись во входящие перед сохранением нового результата.";
  else if (session.sourceState !== "available") message = "Исходники этой записи недоступны.";
  else if (!state.candidate) message = "Сначала создайте локальный результат обработки.";
  else if (!state.candidate.sources.length) message = "Локальный файл без связи с архивной записью сохранить в этот архив нельзя.";
  else if (state.candidate.provenance?.sessionId !== session.id) message = "Локальный результат относится к другой записи.";
  else if (state.candidate.provenance?.sourceSessionRevision !== session.revision) message = "Запись или черновик изменились после обработки; обработайте дорожки заново.";
  else if (!state.announcementDraft || JSON.stringify(draftIds) !== JSON.stringify(selected)) message = "Сохраните черновик обработки с текущим порядком дорожек.";
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

function onGatewayError(error, fallback) {
  if (error?.status === 401) {
    state.authenticated = false;
    updateSessionStatus();
    setArchiveStatus("Сеанс архива истёк. Подключите архив снова.");
    return;
  }
  setArchiveStatus(userError(error, fallback));
}

async function refreshSessions() {
  const sequence = ++state.refreshSequence;
  if (!baseUrl) {
    state.sessions = [];
    state.allSessions = [];
    renderSessions();
    renderResultArchive();
    setArchiveStatus("Шлюз входящего архива ещё не настроен. Локальная обработка доступна в режиме «С устройства».");
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
    if (sequence !== state.refreshSequence) return;
    const byIdentity = new Map();
    for (const session of [...(incoming.sessions || []), ...(archived.sessions || [])]) {
      const known = byIdentity.get(session.id);
      if (!known || session.revision > known.revision) byIdentity.set(session.id, session);
    }
    state.allSessions = [...byIdentity.values()];
    const lifecycle = byId("lifecycle").value;
    state.sessions = state.allSessions.filter((session) => session.lifecycle.state === lifecycle);
    renderSessions();
    renderResultArchive();
    setArchiveStatus(state.sessions.length ? "" : lifecycle === "incoming" ? "Входящих записей пока нет." : "Архив исходников пока пуст.");
  } catch (error) {
    if (sequence !== state.refreshSequence) return;
    state.sessions = [];
    state.allSessions = [];
    renderSessions();
    renderResultArchive();
    onGatewayError(error, "Не удалось загрузить входящий архив.");
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
  if (!closeSpeakerEditor(false)) return;
  const sequence = ++state.sessionSequence;
  state.candidate = null;
  updatePublishState();
  setArchiveStatus(session.lifecycle.state === "archived" ? "Открытие архивированной записи…" : "Загрузка и проверка исходных дорожек…");
  try {
    const complete = await gateway.getSession(session.id);
    if (sequence !== state.sessionSequence) return;
    const draft = (await gateway.loadDraft(session.id, "announcement")).draft;
    if (sequence !== state.sessionSequence) return;
    state.activeSession = session;
    state.activeManifest = complete;
    state.announcementDraft = draft;
    const order = state.announcementDraft?.payload?.trackIds || complete.sourceTracks.map((track) => track.trackId);
    const tracksById = new Map(complete.sourceTracks.map((track) => [track.trackId, track]));
    if (order.some((id) => !tracksById.has(id))) throw new Error("Черновик обработки ссылается на отсутствующую дорожку.");
    const selectedTracks = order.map((id) => tracksById.get(id));
    state.processorProvenance = selectedTracks.map((track, index) => ({ trackId: track.trackId, blobId: track.blobId,
      ordinal: index + 1, sizeBytes: track.sizeBytes, sha256: track.sha256, mediaType: track.mediaType }));
    renderAnnouncementWorkspace();
    if (complete.lifecycle.state === "incoming" && complete.sourceState === "available") {
      const allFiles = await reconstructSessionTracks(complete, gateway.sourcePartFetch(complete));
      if (sequence !== state.sessionSequence) return;
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
      setArchiveStatus(complete.lifecycle.state === "archived" ? "Архивированная запись открыта без загрузки в обработчик." :
        "Исходники удалены; доступны сохранённые результаты и метаданные.");
      byId("announcement-workspace").scrollIntoView({ behavior: "smooth", block: "start" });
    }
  } catch (error) {
    if (sequence !== state.sessionSequence) return;
    state.loadingArchive = false;
    onGatewayError(error, "Не удалось восстановить исходные дорожки.");
  }
}

async function loadSpeakerSession(session) {
  if (session.lifecycle.state !== "incoming" || session.sourceState !== "available") {
    setArchiveStatus("Спикерская доступна только для входящей записи с доступными исходниками. Сначала верните запись во входящие.");
    return;
  }
  const sequence = ++state.sessionSequence;
  setArchiveStatus("Загрузка и проверка исходников для «Спикерская»…");
  try {
    const complete = await gateway.getSession(session.id);
    if (sequence !== state.sessionSequence) return;
    const draft = (await gateway.loadDraft(session.id, "speaker")).draft;
    if (sequence !== state.sessionSequence) return;
    if (complete.lifecycle.state !== "incoming" || complete.sourceState !== "available") throw new Error("Запись больше не доступна для редактирования.");
    const files = await reconstructSessionTracks(complete, gateway.sourcePartFetch(complete));
    if (sequence !== state.sessionSequence) return;
    clearProcessorFiles();
    closeAnnouncementWorkspace(false);
    const opened = await openSpeakerEditor({
      session: complete,
      files,
      draft,
      saveDraft: (envelope) => gateway.saveDraft(complete.id, "speaker", envelope),
      onSaved: ({ session: updated }) => {
        state.activeSession = updated;
        const index = state.sessions.findIndex((item) => item.id === updated.id);
        if (index >= 0) state.sessions[index] = updated;
        const allIndex = state.allSessions.findIndex((item) => item.id === updated.id);
        if (allIndex >= 0) state.allSessions[allIndex] = updated;
        renderSessions();
      }
    });
    setArchiveStatus(opened ? `Открыта работа «Спикерская»: ${complete.title}. Исходники проверены и не изменены.` : "Не удалось подготовить исходники для «Спикерская».");
  } catch (error) {
    if (sequence !== state.sessionSequence) return;
    onGatewayError(error, "Не удалось открыть запись в «Спикерская».");
  }
}

async function openAnnouncementOutput(session, output, downloadOnly = false) {
  const sequence = ++state.outputSequence;
  try {
    byId("results-status").textContent = "Загрузка и проверка сохранённого результата…";
    const metadata = await gateway.getAnnouncementOutput(session.id, output.outputId);
    const file = await reconstructAnnouncementOutput(metadata, gateway.announcementPartFetch(metadata));
    if (sequence !== state.outputSequence || state.resultArchive !== "announcement") return;
    if (state.outputUrl) URL.revokeObjectURL(state.outputUrl);
    state.outputUrl = URL.createObjectURL(file);
    const link = byId("announcement-download");
    link.href = state.outputUrl;
    link.download = file.name;
    byId("announcement-playback-name").textContent = `${session.title} · Версия ${output.version} · ${file.name} · ${formatBytes(file.size)}`;
    byId("announcement-audio").src = state.outputUrl;
    byId("announcement-playback").hidden = false;
    byId("results-status").textContent = "Целостность сохранённого результата проверена. Он готов к прослушиванию и скачиванию.";
    if (downloadOnly) link.click();
  } catch (error) {
    if (sequence === state.outputSequence) byId("results-status").textContent = userError(error, "Не удалось проверить и открыть сохранённый результат.");
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
  metadata.textContent = `${formatDate(output.createdAt)} · ${formatBytes(output.sizeBytes)} · ${session.sourceState === "deleted" ? "исходники удалены" : session.lifecycle.state === "archived" ? "исходники в архиве" : "исходники во входящих"}`;
  details.append(heading, metadata);
  const actions = document.createElement("div");
  actions.className = "result-archive-item__actions";
  if (workflowName === "announcement") {
    actions.append(button("Слушать", () => openAnnouncementOutput(session, output)));
    actions.append(button("Скачать", () => openAnnouncementOutput(session, output, true)));
  }
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
      empty.textContent = name === "speaker" ? "Сохранённых результатов пока нет. Локально собранный результат нельзя сохранить сюда до следующего этапа." : "Сохранённых результатов пока нет.";
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
    card.className = "source-session-item";
    const heading = document.createElement("h3");
    heading.textContent = session.title;
    const metadata = document.createElement("p");
    metadata.className = "source-session-metadata";
    metadata.textContent = `${formatDate(session.recordedAt)} · ${originText[session.origin.kind] || "Источник не указан"} · ${session.sourceTracks.length} дорожек · ${session.sourceState === "available" ? "исходники доступны" : "исходники удалены"}`;
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
      badge.textContent = validWorkflow ? `${workflowLabel(name)}: ${statusText[workflow.status] || "состояние недоступно"} · результатов ${workflow.outputs.length}` : `${workflowLabel(name)}: данные недоступны`;
      workflows.append(badge);
    }
    const actions = document.createElement("div");
    actions.className = "source-session-actions";
    const open = button(session.lifecycle.state === "archived" ? "Открыть запись" : "Открыть в «Анонс-мейкер»", () => loadSession(session), "action-primary");
    actions.append(open);
    if (session.lifecycle.state === "incoming" && session.sourceState === "available") {
      actions.append(button("Открыть в «Спикерская»", () => loadSpeakerSession(session), "speaker-open-action"));
    }
    if (session.lifecycle.state === "incoming") actions.append(button("Архивировать", () => {
      if (session.id === speakerEditorSessionId() && !closeSpeakerEditor(false)) return;
      mutateSession(() => gateway.setLifecycle(session.id, "archive", session.revision));
    }));
    else actions.append(button("Вернуть во входящие", () => mutateSession(() => gateway.setLifecycle(session.id, "restore", session.revision))));
    actions.append(button("Удаление…", () => openDeleteDialog(session), "source-session-danger"));
    summary.append(heading, metadata, workflows);
    body.append(summary, actions);
    card.append(body);
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
      "Передача остановлена. Незавершённая операция сохранена для безопасного повтора." : `${userError(error, "Не удалось сохранить исходники.")} Локальные файлы сохранены; можно повторить.`;
  } finally {
    state.uploadController = null;
    byId("ingest-submit").disabled = false;
    byId("ingest-files").disabled = false;
  }
}

async function saveAnnouncementDraft() {
  if (!state.activeManifest || !state.processorProvenance.length) return;
  byId("announcement-status").textContent = "Сохранение черновика обработки…";
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
    byId("announcement-status").textContent = userError(error, "Не удалось сохранить черновик обработки. Обновите запись и повторите действие.");
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
        byId("publication-progress").value = Math.min(95, Math.round(uploadedBytes / totalBytes * 100));
        byId("publication-status").textContent = `Версия ${reservedVersion}: передано частей ${uploadedParts} из ${totalParts}. Завершаем сохранение…`;
      }
    });
    byId("publication-progress").value = 100;
    byId("publication-status").textContent = `Версия ${result.output.version} сохранена в архиве «Анонс-мейкер».`;
    state.publicationKey = null;
    state.publicationTransactionId = null;
    state.activeManifest = await gateway.getSession(state.activeManifest.id);
    renderAnnouncementWorkspace();
    byId("announcement-status").textContent = `Версия ${result.output.version} сохранена; черновик обработки не изменён.`;
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
  try {
    const preview = await gateway.dependencyPreview(session.id);
    state.deleteTarget = { session, selection, preview };
    byId("delete-summary").textContent = `${session.title}: исходников ${preview.sourceTracks}; версий «Анонс-мейкер» ${preview.announcementVersions}; версий «Спикерская» ${preview.speakerVersions}; черновиков ${preview.drafts}; незавершённых сохранений ${preview.pendingAnnouncementPublications}. Другие уровни автоматически удалены не будут.`;
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
  const container = byId("recovery-list");
  container.replaceChildren();
  try {
    const result = await gateway.listIncomplete();
    for (const transaction of result.transactions || []) {
      const row = document.createElement("div");
      row.className = "source-recovery-item";
      if (transaction.kind === "ingestion") {
        row.append(document.createTextNode(`Незавершённое сохранение исходников · передано частей ${transaction.uploadedParts} из ${transaction.totalParts}. `));
        if (transaction.canFinalize) row.append(button("Завершить", () => recover(transaction.transactionId, "resume")));
        else row.append(document.createTextNode("Для безопасного продолжения нужны исходные файлы и исходный ключ операции. Если окно загрузки уже закрыто, удалите незавершённую операцию и создайте новую."));
        row.append(button("Удалить незавершённое", () => recover(transaction.transactionId, "discard"), "source-session-danger"));
      } else if (transaction.kind === "publication") {
        row.append(document.createTextNode(`Незавершённое сохранение в «Анонс-мейкер» · версия ${transaction.reservedVersion} · передано частей ${transaction.uploadedParts} из ${transaction.totalParts}. `));
        if (transaction.canFinalize) row.append(button("Завершить", () => recover(transaction.transactionId, "resume")));
        else row.append(document.createTextNode("Для продолжения нужен локальный результат и исходный ключ сохранения. "));
        row.append(button("Удалить незавершённое", () => recover(transaction.transactionId, "discard"), "source-session-danger"));
      } else {
        row.append(document.createTextNode("Незнакомая незавершённая операция. Автоматическое продолжение отключено."));
        row.append(button("Удалить незавершённое", () => recover(transaction.transactionId, "discard"), "source-session-danger"));
      }
      container.append(row);
    }
    for (const orphan of result.orphans || []) {
      const row = document.createElement("p");
      row.textContent = `Найдены данные для ручной проверки (${orphan.draft ? "черновик" : "сохранённый результат"}). Они не удалены автоматически.`;
      container.append(row);
    }
    if (!container.childElementCount) container.textContent = "Незавершённых операций и данных для ручной проверки не найдено.";
  } catch (error) {
    container.textContent = userError(error, "Не удалось проверить незавершённые операции.");
  }
}

async function recover(transactionId, action) {
  try {
    await gateway.recoverIncomplete(transactionId, action);
    await showIncomplete();
    await refreshSessions();
  } catch (error) {
    byId("recovery-list").textContent = userError(error, "Не удалось восстановить незавершённую операцию.");
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
byId("results-announcement").addEventListener("click", () => setResultArchive("announcement"));
byId("results-speaker").addEventListener("click", () => setResultArchive("speaker"));
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
byId("publication-dialog").addEventListener("cancel", (event) => {
  if (!state.publicationController) return;
  event.preventDefault();
  cancelPublicationDialog();
});

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
    byId("login-status").textContent = userError(error, "Не удалось подключить архив. Проверьте пароль и повторите действие.");
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
    byId("recovery-list").textContent = `Каталог пересобран: записей ${result.catalog.entries.length}. Данных для ручной проверки: ${result.orphans.length}.`;
    await refreshSessions();
  } catch (error) {
    byId("recovery-list").textContent = userError(error, "Не удалось пересобрать каталог.");
  }
});
window.addEventListener("pagehide", clearOutputPlayback);

globalThis.meserAudioArchiveDrafts = Object.freeze({
  load: (sessionId, workflow) => gateway.loadDraft(sessionId, workflow),
  save: (sessionId, workflow, envelope) => gateway.saveDraft(sessionId, workflow, envelope)
});

await initialize();
