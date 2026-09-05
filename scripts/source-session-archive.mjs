import { AudioArchiveGateway, MAX_AUDIO_SESSION_BYTES, reconstructSessionTracks } from "./audio-archive-client.mjs";
import { getProcessorFiles, loadProcessorFiles } from "./audio-processor.mjs";

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
  loadingArchive: false
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
    await action();
    await refreshSessions();
  } catch (error) {
    onGatewayError(error, "Не удалось сохранить изменения.");
  }
}

async function loadSession(session) {
  if (session.sourceState !== "available") {
    setArchiveStatus("Исходники этой записи были удалены; сохранённые результаты и метаданные остаются в архиве.");
    return;
  }
  setArchiveStatus("Загрузка и проверка исходных дорожек…");
  try {
    const complete = await gateway.getSession(session.id);
    const files = await reconstructSessionTracks(complete, (url, options) => fetch(url, options));
    state.loadingArchive = true;
    loadProcessorFiles(files);
    state.loadingArchive = false;
    setArchiveStatus(`Загружено дорожек: ${files.length}. Байты и SHA-256 проверены; запись ${session.lifecycle.state === "archived" ? "осталась архивированной" : "не изменена"}.`);
    document.getElementById("processor-heading").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    state.loadingArchive = false;
    onGatewayError(error, "Не удалось восстановить исходные дорожки.");
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
  if (workflow.status === "new") actions.append(button("Начать работу", () => mutateSession(() => gateway.updateWorkflow(session.id, name, session.revision, "in_progress"))));
  if (workflow.status === "in_progress") actions.append(button("Вернуть в новые", () => mutateSession(() => gateway.updateWorkflow(session.id, name, session.revision, "new"))));
  for (const output of workflow.outputs || []) {
    const outputRow = document.createElement("p");
    outputRow.className = "source-output-version";
    outputRow.append(document.createTextNode(`Версия ${output.version} · ${formatDate(output.createdAt)} `));
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
    const open = button("Открыть исходники", () => loadSession(session));
    open.disabled = session.sourceState !== "available";
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

async function openDeleteDialog(session, selection = null) {
  try {
    const preview = await gateway.dependencyPreview(session.id);
    state.deleteTarget = { session, selection, preview };
    byId("delete-summary").textContent = `Source Session ${session.id}: исходников ${preview.sourceTracks}; версий «Объявление» ${preview.announcementVersions}; версий «Спикерская» ${preview.speakerVersions}; черновиков ${preview.drafts}. Удаление не затронет другие уровни автоматически.`;
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
    if (selected.kind === "output-version") await gateway.deleteOutputVersion(target.session.id, selected.workflow, selected.version, body);
    else if (selected.kind === "announcement-series") await gateway.deleteOutputSeries(target.session.id, "announcement", body);
    else if (selected.kind === "speaker-series") await gateway.deleteOutputSeries(target.session.id, "speaker", body);
    else if (selected.kind === "sources") await gateway.deleteSources(target.session.id, body);
    else if (selected.kind === "purge") await gateway.purgeSession(target.session.id, body);
    else throw new Error("Неизвестный уровень удаления.");
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
      row.append(document.createTextNode(`${transaction.kind} · ${transaction.state} · ${transaction.transactionId} `));
      row.append(button("Продолжить", () => recover(transaction.transactionId, "resume")));
      if (transaction.kind === "ingestion") row.append(button("Удалить незавершённое", () => recover(transaction.transactionId, "discard"), "source-session-danger"));
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
  if (!state.loadingArchive && event.detail.files.length) setMode("device");
  document.getElementById("processor-save-incoming").disabled = state.mode !== "device" || !event.detail.files.length;
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

globalThis.meserAudioArchiveDrafts = Object.freeze({
  load: (sessionId, workflow) => gateway.loadDraft(sessionId, workflow),
  save: (sessionId, workflow, envelope) => gateway.saveDraft(sessionId, workflow, envelope)
});

await initialize();
