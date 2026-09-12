import { contextActions } from "./audio-actions.mjs";
import { RECONNECT_MESSAGE, projectProjection } from "./audio-project.mjs";
import { AudioArchiveGateway, validateSessionManifest, validateAnnouncementOutput, validateSpeakerOutput,
  reconstructAnnouncementOutput, reconstructSpeakerOutput } from './audio-archive-client.mjs';
import { workflows, statuses, lifecycleLabel, sourceLabel, eligible, dateLabel, bytesLabel, mergeSessions,
  selectSessions, selectResults, overview, recoveryPolicy, editorUrl, deletionImpact, RequestGeneration } from './audio-archive-core.mjs';

const $ = id => document.getElementById(id);
const gateway = new AudioArchiveGateway(globalThis.__MESER_AUDIO_ARCHIVE_GATEWAY__ || document.querySelector('meta[name="audio-archive-gateway"]')?.content || '');
const generations = Object.fromEntries(['auth', 'list', 'detail', 'play', 'delete'].map(key => [key, new RequestGeneration()]));
const state = { authenticated: false, projects: new Map(), sessions: null, maintenance: null, detail: null, url: null, target: null, busy: false, resultSort: { announcement: 'newest', speaker: 'newest' } };
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function button(label, action, className) {
  const node = element('button', label, className); node.type = 'button';
  node.addEventListener('click', action); return node;
}
function message(error) {
  if ([401, 403].includes(error.status)) return RECONNECT_MESSAGE;
  if (error.status === 409) return 'Данные изменились или операция сейчас недоступна. Загрузите актуальное состояние и подтвердите действие заново.';
  if (error.status === 404) return 'Запись или результат больше не доступны.';
  return 'Не удалось получить подтверждение от архива. Проверьте состояние перед повторным действием.';
}
function report(error) {
  if ([401, 403].includes(error.status)) clearSession();
  $('status').textContent = message(error);
}
function clearPlayback() {
  generations.play.next();
  $('audio').pause(); $('audio').removeAttribute('src'); $('audio').load();
  $('download').removeAttribute('href'); $('download').removeAttribute('download');
  if (state.url) URL.revokeObjectURL(state.url);
  state.url = null; $('player').hidden = true; $('playback-status').textContent = '';
}
function clearSession() {
  for (const generation of Object.values(generations)) generation.next();
  clearPlayback(); state.authenticated = false; state.sessions = null; state.maintenance = null; state.detail = null; state.target = null; state.projects.clear();
  $('detail').hidden = true; $('detail-body').replaceChildren(); $('delete-dialog').close();
  updateControls(); render();
}
function updateControls() {
  $('login').hidden = state.authenticated;
  $('logout').hidden = !state.authenticated;
  $('refresh').disabled = !state.authenticated || state.busy;
  $('rebuild').disabled = !state.authenticated || state.busy;
}
function technical(data) {
  const details = element('details'); details.append(element('summary', 'Технические сведения'), element('pre', JSON.stringify(data, null, 2))); return details;
}
function renderOverview() { /* Navigation is based on objects, never storage partitions. */ }
function filters() {
  const form = $('filters').elements;
  return { search: form.search.value, sort: form.sort.value, lifecycle: form.showRemoved.checked ? '' : 'incoming',
    sources: form.availableOnly.checked ? 'available' : '', attention: form.attention.checked };
}
function projectLink(session, label = 'Продолжить обработку') {
  if (!eligible(session)) return element('p', session.sourceState === 'available' ? 'Верните запись для обработки.' : 'Исходные дорожки недоступны.');
  const link = element('a', label); link.href = editorUrl(session, 'speaker'); link.target = '_blank'; link.rel = 'noopener'; return link;
}
function renderProjects() {
  const list = $('project-list'); list.replaceChildren();
  if (!state.sessions) { list.append(element('p', 'Проекты не загружены.')); return; }
  for (const session of state.sessions.filter(s => s.workflows.speaker.currentDraft)) {
    const data = state.projects.get(session.id), card = element('article', undefined, 'archive-card project-row');
    card.append(element('h3', 'Проект обработки спикерской'), element('p', session.title));
    if (data?.projection) card.append(element('p', `${data.projection.trackCount} дорожек · Последнее сохранение ${dateLabel(data.projection.savedAt)}`), projectLink(session));
    else card.append(element('p', data ? 'Сохранённые данные недоступны или имеют неподдерживаемый формат.' : 'Проверка сохранённого проекта…'));
    card.append(contextActions(session.title, button('Открыть исходную запись', () => openDetail(session.id)))); list.append(card);
  }
  if (!list.childElementCount) list.append(element('p', 'Сохранённых проектов пока нет.'));
}
function contextualRecovery(session, container) {
  for (const operation of state.maintenance?.transactions || []) {
    if (operation.sessionId !== session.id) continue;
    const policy = recoveryPolicy(operation), row = element('div', undefined, 'attention');
    row.append(element('strong', 'Требуется внимание'), element('p', operation.kind === 'pending_delete' ? 'Удаление не завершено.' : operation.kind === 'ingestion' ? 'Сохранение исходных записей не завершено.' : 'Сохранение финальной версии не завершено.'), element('p', policy.local));
    for (const [action, label] of policy.actions) row.append(button(label, () => recover(operation, action), action === 'discard' ? 'danger' : ''));
    container.append(row);
  }
}
function renderRecords() {
  $('session-list').replaceChildren();
  if (!state.sessions) { $('matching').textContent = 'Список записей не загружен.'; return; }
  if (filters().attention && !state.maintenance) { $('matching').textContent = 'Сведения о незавершённых операциях не загружены. Фильтр внимания пока недоступен.'; return; }
  let sessions;
  try { sessions = selectSessions(state.sessions, filters(), state.maintenance?.transactions); }
  catch (error) { $('matching').textContent = error.message; return; }
  $('matching').textContent = !state.sessions.length ? 'Архив пока пуст.' : `Найдено: ${sessions.length}.` + (!sessions.length ? ' Нет записей с такими условиями.' : '');
  for (const session of sessions) {
    const card = element('article', undefined, 'archive-card');
    card.classList.add('source-row');
    const info = element('div', undefined, 'record-info'), badges = element('div', undefined, 'status-badges');
    const project = state.projects.get(session.id);
    const projectState = project?.projection ? 'Сохранён проект спикерской' : session.workflows.speaker.currentDraft ? 'Проект не проверен' : 'Проект спикерской отсутствует';
    info.append(element('h3', session.title), element('p', `Записано: ${dateLabel(session.recordedAt)} · дорожек: ${session.sourceTracks.length} · готовых версий: ${session.workflows.announcement.outputs.length + session.workflows.speaker.outputs.length}`));
    badges.append(element('span', lifecycleLabel(session), `status-badge ${eligible(session) ? 'is-ready' : ''}`), element('span', sourceLabel(session), 'status-badge'), element('span', projectState, `status-badge ${project?.projection ? 'is-ready' : session.workflows.speaker.currentDraft ? 'is-warning' : ''}`));
    info.append(badges); card.append(info);
    const actions = [button('Сведения о записи', () => openDetail(session.id))];
    if (eligible(session)) {
      const link = element('a', 'Редактировать для анонс-мейкера'); link.href = editorUrl(session, 'announcement'); link.target = '_blank'; link.rel = 'noopener'; actions.push(link, projectLink(session, 'Открыть финальную обработку спикерской'));
    } else if (session.lifecycle.state === 'archived') actions.push(button('Вернуть для обработки', () => mutate(() => writeSession(session, () => gateway.setLifecycle(session.id, 'restore', session.revision)))));
    card.append(contextActions(session.title, ...actions));
    contextualRecovery(session, card);
    $('session-list').append(card);
  }
}
function resultCard(session, output, workflow) {
  const card = element('article', undefined, 'archive-card result-row');
  card.append(element('h3', `Версия ${output.version} · ${session.title}`), element('p', `Сохранено: ${dateLabel(output.createdAt)} · ${bytesLabel(output.sizeBytes)}`));
  const actions = element('div', undefined, 'toolbar');
  actions.append(button('Прослушать', () => loadOutput(session, output, workflow)),
    button('Скачать', () => loadOutput(session, output, workflow, true)),
    contextActions(`${session.title}, версия ${output.version}`, button('Удалить версию', () => openDeletion(session.id, { kind: 'output-version', workflow, version: output.version }), 'danger')));
  card.append(actions); return card;
}
function renderResults() {
  $('result-sections').replaceChildren();
  for (const workflow of Object.keys(workflows)) {
    const section = element('section'); section.id = `results-${workflow}`; section.append(element('h3', workflows[workflow]));
    section.append(element('p', workflow === 'announcement' ? 'Сохранённые версии записей, обработанных для анонс-мейкера.' : 'Сохранённые финальные версии спикерских записей.'));
    const label = element('label', `Сортировка · ${workflows[workflow]}`), select = element('select');
    for (const [value, text] of Object.entries({ newest: 'Сначала новые', oldest: 'Сначала старые', version: 'Версия по возрастанию', 'version-desc': 'Версия по убыванию', title: 'Название записи' })) { const option = element('option', text); option.value = value; select.append(option); }
    select.value = state.resultSort[workflow]; label.append(select); section.append(label);
    const cards = element('div', undefined, 'cards');
    const draw = () => {
      cards.replaceChildren();
      const results = state.sessions ? selectResults(state.sessions, workflow, state.resultSort[workflow]) : null;
      if (!results?.length) cards.append(element('p', results ? 'Сохранённых результатов пока нет.' : 'Результаты не загружены.'));
      for (const { session, output } of results || []) cards.append(resultCard(session, output, workflow));
    };
    select.addEventListener('change', () => { state.resultSort[workflow] = select.value; draw(); });
    draw(); section.append(cards); $('result-sections').append(section);
  }
}
function renderMaintenance() {
  $('operations').replaceChildren(); $('observations').replaceChildren();
  if (!state.maintenance) { $('operations').append(element('p', 'Сведения об операциях не загружены.')); return; }
  if (!state.maintenance.transactions.length) $('operations').append(element('p', 'Незавершённых операций не обнаружено.'));
  const phases = { uploading: 'Передача частей', staged: 'Части подготовлены', cancelled: 'Передача остановлена', finalizing: 'Завершение сохранения', discarding: 'Удаление незавершённого сохранения', pending_delete: 'Незавершённое удаление' };
  for (const operation of state.maintenance.transactions) {
    const policy = recoveryPolicy(operation), session = state.sessions?.find(s => s.id === operation.sessionId);
    const card = element('article', undefined, 'archive-card');
    card.append(element('h3', session?.title || 'Запись ещё не определена'), element('p', operation.kind === 'ingestion' ? 'Сохранение исходников' : operation.kind === 'pending_delete' ? 'Удаление данных' : operation.kind === 'publication' ? `Сохранение · ${workflows[operation.workflow] || 'Вид работы неизвестен'}` : 'Неизвестная операция'),
      element('p', phases[operation.state] || 'Состояние не распознано'));
    if (operation.reservedVersion) card.append(element('p', `Зарезервирована версия ${operation.reservedVersion}. Номер не переиспользуется.`));
    card.append(element('p', Number.isSafeInteger(operation.totalParts) ? `Передано частей: ${operation.uploadedParts} из ${operation.totalParts}.` : 'Детальный прогресс не предоставлен.'), element('p', policy.local));
    for (const [action, label] of policy.actions) card.append(button(label, () => recover(operation, action), action === 'discard' || operation.kind === 'pending_delete' ? 'danger' : ''));
    card.append(technical(operation)); $('operations').append(card);
  }
  $('observations').append(element('h3', `Наблюдения для ручной проверки: ${state.maintenance.orphans.length}`), element('p', 'Эти наблюдения не считаются восстанавливаемыми операциями. Автоматическая очистка недоступна.'));
  for (const observation of state.maintenance.orphans) $('observations').append(technical(observation));
}
function render() { renderProjects(); renderOverview(); renderRecords(); renderResults(); renderMaintenance(); }
async function refresh() {
  if (!state.authenticated) return;
  const sequence = generations.list.next(), auth = generations.auth.value;
  clearPlayback(); $('status').textContent = 'Загрузка записей и незавершённых операций…';
  state.sessions = null; state.maintenance = null; state.projects.clear(); render();
  const results = await Promise.allSettled([gateway.listSessions('incoming'), gateway.listSessions('archived'), gateway.listIncomplete()]);
  if (!generations.list.current(sequence) || !generations.auth.current(auth)) return;
  const authFailure = results.find(r => r.status === 'rejected' && [401, 403].includes(r.reason.status));
  if (authFailure) { report(authFailure.reason); return; }
  const errors = [];
  try {
    if (results.slice(0, 2).every(r => r.status === 'fulfilled')) state.sessions = mergeSessions(results[0].value.sessions, results[1].value.sessions);
    else errors.push('Не удалось загрузить оба списка записей.');
    if (results[2].status === 'fulfilled' && Array.isArray(results[2].value.transactions) && Array.isArray(results[2].value.orphans)) state.maintenance = results[2].value;
    else errors.push('Не удалось загрузить незавершённые операции.');
  } catch { errors.push('Данные записей повреждены.'); }
  if (state.sessions) {
    const projects = await Promise.allSettled(state.sessions.filter(s => s.workflows.speaker.currentDraft).map(async session => {
      const result = await gateway.loadDraft(session.id, 'speaker'); return [session.id, { draft: result.draft, projection: projectProjection(session, result.draft) }];
    }));
    if (!generations.list.current(sequence) || !generations.auth.current(auth)) return;
    const projectAuthFailure = projects.find(r => r.status === 'rejected' && [401, 403].includes(r.reason.status));
    if (projectAuthFailure) { report(projectAuthFailure.reason); return; }
    for (const result of projects) if (result.status === 'fulfilled') state.projects.set(...result.value);
    for (const session of state.sessions.filter(s => s.workflows.speaker.currentDraft)) if (!state.projects.has(session.id)) state.projects.set(session.id, { error: true });
  }
  render(); $('status').textContent = errors.length ? errors.join(' ') + ' Обновите данные.' : 'Данные загружены. Просмотр не изменяет архив.';
}
async function openDetail(id) {
  if (state.busy) return;
  const sequence = generations.detail.next(), auth = generations.auth.value;
  state.detail = null; state.projects.delete(id); $('detail').hidden = false; $('detail-body').replaceChildren(element('p', 'Загрузка актуальных сведений…'));
  try {
    const session = await gateway.getSession(id);
    if (!generations.detail.current(sequence) || !generations.auth.current(auth)) return;
    if (!validateSessionManifest(session) || session.id !== id) throw new Error('Invalid session');
    let project = null;
    if (session.workflows.speaker.currentDraft) {
      try { const result = await gateway.loadDraft(id, 'speaker'); project = { draft: result.draft, projection: projectProjection(session, result.draft) }; }
      catch (error) { if ([401, 403].includes(error.status)) throw error; project = { error: true }; }
    }
    if (!generations.detail.current(sequence) || !generations.auth.current(auth)) return;
    if (project) state.projects.set(id, project); else state.projects.delete(id);
    state.detail = session; renderDetail(); renderRecords(); renderProjects(); $('detail-title').focus();
  } catch (error) { if (generations.detail.current(sequence) && generations.auth.current(auth)) { $('detail-body').replaceChildren(element('p', message(error))); report(error); } }
}
function renderDetail() {
  const session = state.detail, container = $('detail-body'); container.replaceChildren();
  container.append(element('h3', session.title), element('p', `${lifecycleLabel(session)} · ${sourceLabel(session)}`), element('p', `Записано: ${dateLabel(session.recordedAt)} · Обновлено: ${dateLabel(session.updatedAt)}`),
    element('p', `Источник: ${{ manual: 'Создана вручную', device: 'С устройства', zoom_webhook: 'Zoom' }[session.origin.kind] || 'Не указан'}`));
  const form = element('form'), titleLabel = element('label', 'Название записи'), title = element('input');
  title.value = session.title; title.required = true; title.maxLength = 200; title.id = 'metadata-title'; titleLabel.append(title);
  const dateInputLabel = element('label', 'Дата и время записи (UTC; пусто — дата не указана)'), date = element('input');
  date.type = 'datetime-local'; date.step = '0.001'; date.id = 'metadata-date';
  const initialDate = session.recordedAt ? new Date(session.recordedAt).toISOString().slice(0, -1) : ''; date.value = initialDate; const initialControlValue = date.value;
  dateInputLabel.append(date); const save = element('button', 'Сохранить название и дату'); save.type = 'submit';
  const feedback = element('p'); feedback.id = 'metadata-status'; feedback.setAttribute('role', 'status');
  const reload = button('Загрузить актуальные сведения', () => openDetail(session.id));
  form.append(titleLabel, dateInputLabel, save, feedback, reload);
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (state.busy || save.disabled) return;
    const patch = { title: title.value.trim(), recordedAt: date.value === initialControlValue ? session.recordedAt : date.value ? new Date(date.value + 'Z').toISOString() : null };
    save.disabled = true;
    await mutate(() => writeSession(session, () => gateway.updateSession(session.id, session.revision, patch, crypto.randomUUID())), async () => {
      await openDetail(session.id);
    }, error => { feedback.textContent = message(error) + ' Введённые значения сохранены в форме. Для нового действия загрузите актуальные сведения.'; });
  });
  container.append(form, element('h3', 'Исходные дорожки'));
  for (const track of session.sourceTracks) container.append(element('p', `${track.ordinal}. ${track.originalName} · ${{ 'audio/mpeg': 'MP3', 'audio/wav': 'WAV', 'audio/mp4': 'M4A' }[track.mediaType] || track.mediaType} · ${bytesLabel(track.sizeBytes)}`));
  if (!session.sourceTracks.length) container.append(element('p', 'Доступных исходных дорожек нет.'));
  for (const [key, label] of Object.entries({ supersedesSessionId: 'Заменяет предыдущую запись', supersededBySessionId: 'Есть более новая связанная запись' })) {
    if (session.relations[key]) container.append(button(label, () => openDetail(session.relations[key])));
  }
  const project = state.projects.get(session.id);
  container.append(element('h3', 'Проект обработки спикерской'));
  if (project?.projection) container.append(element('p', `Последнее сохранение ${dateLabel(project.projection.savedAt)}`), projectLink(session));
  else container.append(element('p', session.workflows.speaker.currentDraft ? 'Сохранённые данные недоступны или имеют неподдерживаемый формат.' : 'Проект отсутствует.'));
  if (project?.draft && !project.projection) container.append(technical(project.draft));
  contextualRecovery(session, container);
  const actions = element('div', undefined, 'toolbar');
  actions.append(button(session.lifecycle.state === 'incoming' ? 'Убрать из рабочего списка' : 'Вернуть для обработки', () => mutate(() => writeSession(session, () => gateway.setLifecycle(session.id, session.lifecycle.state === 'incoming' ? 'archive' : 'restore', session.revision)), () => openDetail(session.id))),
    button('Удалить исходники', () => openDeletion(session.id, { kind: 'sources' }), 'danger'), button('Удалить запись полностью', () => openDeletion(session.id, { kind: 'purge' }), 'danger'));
  actions.children[1].disabled = session.sourceState !== 'available'; const danger = element('details'); danger.append(element('summary', 'Опасная зона'), actions.children[2]); container.append(actions, danger);
  for (const workflow of Object.keys(workflows)) {
    const data = session.workflows[workflow], block = element('section'); block.append(element('h3', workflows[workflow]));
    if (eligible(session)) { const link = element('a', workflow === 'speaker' ? 'Открыть финальную обработку спикерской' : 'Редактировать для анонс-мейкера'); link.href = editorUrl(session, workflow); link.target = '_blank'; link.rel = 'noopener'; block.append(link); }
    else block.append(element('p', 'Новая обработка недоступна: нужны запись в рабочем списке и доступные исходники.'));
    const versions = [...data.outputs].sort((a, b) => a.version - b.version);
    for (const output of versions) block.append(resultCard(session, output, workflow));
    if (!versions.length) block.append(element('p', 'Сохранённых версий нет.'));
    block.append(technical({ deletedVersions: data.deletedVersions, nextVersion: data.nextVersion }));
    for (const transaction of state.maintenance?.transactions || []) if (transaction.sessionId === session.id && transaction.workflow === workflow && transaction.reservedVersion) block.append(element('p', `Незавершённое сохранение: зарезервирована версия ${transaction.reservedVersion}.`));
    const remove = button(`Удалить всю серию «${workflows[workflow]}»`, () => openDeletion(session.id, { kind: 'output-series', workflow }), 'danger'); remove.disabled = !versions.length; block.append(remove); container.append(block);
  }
  container.append(technical({ id: session.id, revision: session.revision, storage: session.storage, relations: session.relations, origin: session.origin }));
}
async function loadOutput(session, output, workflow, downloadOnly = false) {
  clearPlayback(); const sequence = generations.play.value, auth = generations.auth.value;
  $('playback-status').textContent = 'Загрузка и проверка целостности результата…';
  try {
    const metadata = await (workflow === 'speaker' ? gateway.getSpeakerOutput(session.id, output.outputId) : gateway.getAnnouncementOutput(session.id, output.outputId));
    if (!generations.play.current(sequence) || !generations.auth.current(auth)) return;
    const validate = workflow === 'speaker' ? validateSpeakerOutput : validateAnnouncementOutput;
    if (!validate(metadata.output, metadata.recipe, session.id) || metadata.output.outputId !== output.outputId || metadata.output.version !== output.version || metadata.output.blobId !== output.blobId ||
        metadata.output.sha256 !== output.sha256 || metadata.output.sizeBytes !== output.sizeBytes || metadata.output.recipeSnapshotRef !== output.recipeSnapshotRef) throw new Error('Invalid output identity');
    const file = await (workflow === 'speaker' ? reconstructSpeakerOutput(metadata, gateway.speakerPartFetch(metadata)) : reconstructAnnouncementOutput(metadata, gateway.announcementPartFetch(metadata)));
    if (!generations.play.current(sequence) || !generations.auth.current(auth)) return;
    state.url = URL.createObjectURL(file); $('audio').src = state.url; $('download').href = state.url; $('download').download = file.name;
    $('player-title').textContent = `${workflows[workflow]} · ${session.title} · версия ${output.version}`;
    $('player-meta').textContent = `${file.name} · ${file.type} · ${bytesLabel(file.size)}`;
    $('player').hidden = false; $('playback-status').textContent = 'Файл проверен и готов к воспроизведению.'; $('player').scrollIntoView({ block: 'nearest' });
    if (downloadOnly) $('download').click();
  } catch (error) {
    if (!generations.play.current(sequence) || !generations.auth.current(auth)) return;
    clearPlayback(); $('playback-status').textContent = 'Не удалось загрузить и проверить результат. Воспроизведение и скачивание недоступны.';
    if ([401, 403].includes(error.status)) report(error);
  }
}
async function writeSession(session, action) {
  const auth = generations.auth.value;
  const [fresh, maintenance] = await Promise.all([gateway.getSession(session.id), gateway.listIncomplete()]);
  if (!generations.auth.current(auth)) throw new Error('Session ended');
  if (fresh.id !== session.id || fresh.revision !== session.revision || maintenance.transactions.some(t =>
      t.sessionId === session.id && (t.kind === 'pending_delete' || ['finalizing', 'discarding'].includes(t.state)))) {
    throw Object.assign(new Error('Session changed or maintenance is required'), { status: 409 });
  }
  return action();
}
// A failed write is never treated as success or retried automatically. Reconcile both manifests and maintenance first.
async function mutate(action, success = () => {}, failure = null) {
  if (state.busy || !state.authenticated) return;
  state.busy = true; updateControls(); const auth = generations.auth.value;
  clearPlayback();
  try {
    await action();
    if (!generations.auth.current(auth)) return;
    await refresh();
    if (!generations.auth.current(auth)) return;
    state.busy = false; await success();
  } catch (error) {
    if (!generations.auth.current(auth)) return;
    if ([401, 403].includes(error.status)) { report(error); return; }
    await refresh();
    if (!generations.auth.current(auth)) return;
    if (state.detail) {
      try { await gateway.getSession(state.detail.id); } catch { /* Listing/maintenance and explicit reload remain authoritative. */ }
    }
    if (!generations.auth.current(auth)) return;
    if (failure) failure(error); else report(error);
  } finally { state.busy = false; updateControls(); }
}
async function openDeletion(id, selection) {
  if (state.busy || $('delete-dialog').open) return;
  const sequence = generations.delete.next(), auth = generations.auth.value;
  try {
    const session = await gateway.getSession(id), preview = await gateway.dependencyPreview(id), maintenance = await gateway.listIncomplete();
    if (!generations.delete.current(sequence) || !generations.auth.current(auth)) return;
    if (!validateSessionManifest(session) || session.id !== id || preview.sessionId !== id || preview.revision !== session.revision) throw Object.assign(new Error('Stale preview'), { status: 409 });
    if (selection.kind === 'output-version' && !session.workflows[selection.workflow].outputs.some(o => o.version === selection.version)) throw Object.assign(new Error('Missing version'), { status: 404 });
    state.target = Object.freeze({ ...selection, session, preview, idempotencyKey: crypto.randomUUID() });
    state.returnFocus = document.activeElement;
    const impact = deletionImpact(preview, selection);
    $('delete-name').textContent = session.title; $('delete-removed').textContent = impact.removed; $('delete-retained').textContent = impact.retained;
    const pendingDeletion = maintenance.transactions.some(t => t.sessionId === id && (t.kind === 'pending_delete' || ['finalizing', 'discarding'].includes(t.state)));
    const pending = preview.pendingAnnouncementPublications + preview.pendingSpeakerSaves;
    $('delete-pending').textContent = pendingDeletion ? 'Удаление уже начато. Продолжите его в разделе восстановления; новая цель недоступна.' : pending ? `Незавершённых сохранений: ${pending}. Сначала завершите их или удалите в разделе восстановления.` : 'Подтверждение относится только к выбранной записи и её текущему состоянию.';
    $('purge-label').hidden = selection.kind !== 'purge'; $('purge-id').textContent = selection.kind === 'purge' ? id : '';
    $('purge-confirmation').value = ''; $('delete-status').textContent = ''; $('delete-submit').disabled = Boolean(pending) || pendingDeletion; $('delete-dialog').showModal();
  } catch (error) { if (generations.delete.current(sequence) && generations.auth.current(auth)) report(error); }
}
$('delete-form').addEventListener('submit', async event => {
  event.preventDefault(); const target = state.target;
  if (!target || state.busy || $('delete-submit').disabled) return;
  if (target.kind === 'purge' && $('purge-confirmation').value !== target.session.id) { $('delete-status').textContent = 'Введите точный ID записи без изменений.'; return; }
  const body = { expectedRevision: target.preview.revision, idempotencyKey: target.idempotencyKey,
    confirmation: target.kind === 'purge' ? $('purge-confirmation').value : target.kind === 'sources' ? 'Удалить исходники, сохранить результаты' : '' };
  $('delete-submit').disabled = true;
  await mutate(() => writeSession(target.session, async () => {
    const preview = await gateway.dependencyPreview(target.session.id);
    if (state.target !== target || preview.sessionId !== target.session.id || preview.revision !== target.preview.revision ||
        JSON.stringify(preview) !== JSON.stringify(target.preview)) throw Object.assign(new Error('Dependencies changed'), { status: 409 });
    return target.kind === 'purge' ? gateway.purgeSession(target.session.id, body) : target.kind === 'sources' ? gateway.deleteSources(target.session.id, body) :
    target.kind === 'output-series' ? gateway.deleteOutputSeries(target.session.id, target.workflow, body) : gateway.deleteOutputVersion(target.session.id, target.workflow, target.version, body); }),
  async () => { $('delete-dialog').close(); state.target = null; if (target.kind === 'purge') { $('detail').hidden = true; state.detail = null; } else if (state.detail?.id === target.session.id) await openDetail(target.session.id); },
  error => { $('delete-status').textContent = message(error) + ' Результат не подтверждён этим запросом. Состояние списков и операций повторно запрошено. Дождитесь успешного обновления, затем закройте окно и получите новый предварительный просмотр. При незавершённом удалении используйте раздел восстановления.'; state.target = null; });
});
async function recover(operation, action) {
  if (state.busy) return;
  if ((action === 'discard' || operation.kind === 'pending_delete') && !globalThis.confirm(action === 'discard' ? 'Удалить только эту незавершённую операцию? Зарезервированный номер версии останется использованным.' : 'Продолжить уже начатое необратимое удаление?')) return;
  await mutate(async () => {
    const auth = generations.auth.value;
    const latest = await gateway.listIncomplete();
    if (!generations.auth.current(auth)) throw new Error('Session ended');
    const fresh = latest.transactions.find(t => t.transactionId === operation.transactionId);
    if (!fresh || fresh.kind !== operation.kind || fresh.sessionId !== operation.sessionId || fresh.workflow !== operation.workflow ||
        !recoveryPolicy(fresh).actions.some(([allowed]) => allowed === action)) throw Object.assign(new Error('Recovery changed'), { status: 409 });
    return gateway.recoverIncomplete(fresh.transactionId, action);
  }, async () => { if (state.detail) await openDetail(state.detail.id); });
}
$('filters').addEventListener('submit', event => event.preventDefault());
$('filters').addEventListener('input', renderRecords);
$('filters').addEventListener('reset', () => requestAnimationFrame(renderRecords));
$('refresh').addEventListener('click', refresh);
$('player-close').addEventListener('click', clearPlayback);
$('rebuild').addEventListener('click', () => mutate(() => gateway.rebuildCatalog()));
$('login').addEventListener('click', () => { $('login-status').textContent = ''; $('login-dialog').showModal(); });
$('login-cancel').addEventListener('click', () => $('login-dialog').close());
$('delete-cancel').addEventListener('click', () => { if (!state.busy) $('delete-dialog').close(); });
$('delete-dialog').addEventListener('cancel', event => { if (state.busy) event.preventDefault(); });
$('delete-dialog').addEventListener('close', () => {
  state.target = null; generations.delete.next();
  const focus = state.returnFocus?.isConnected ? state.returnFocus : $('records-title');
  focus.focus(); state.returnFocus = null;
});
$('login-form').addEventListener('submit', async event => {
  event.preventDefault(); const submit = event.submitter; if (submit.disabled) return; submit.disabled = true;
  const sequence = generations.auth.next();
  try {
    await gateway.login($('password').value);
    if (!generations.auth.current(sequence)) return;
    state.authenticated = true; $('login-dialog').close(); updateControls(); await refresh();
  } catch (error) { if (generations.auth.current(sequence)) $('login-status').textContent = message(error); }
  finally { $('password').value = ''; submit.disabled = false; }
});
$('logout').addEventListener('click', async () => {
  clearSession(); $('status').textContent = 'Отключение архива…';
  const sequence = generations.auth.value; $('login').disabled = true;
  try { await gateway.logout(); if (generations.auth.current(sequence)) $('status').textContent = 'Архив отключён.'; }
  catch { if (generations.auth.current(sequence)) $('status').textContent = 'Локальные данные очищены, но сервер не подтвердил выход. Повторите отключение.'; $('logout').hidden = false; }
  finally { gateway.csrfToken = null; $('login').disabled = false; }
});
window.addEventListener('pagehide', () => { clearSession(); });
window.addEventListener('pageshow', event => { if (event.persisted) initialize(); });
async function initialize() {
  render(); const sequence = generations.auth.next();
  try {
    await gateway.sessionStatus();
    if (!generations.auth.current(sequence)) return;
    state.authenticated = true; updateControls(); await refresh();
  } catch (error) { if (generations.auth.current(sequence)) report(error); }
}
await initialize();
