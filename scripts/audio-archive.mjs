import { contextActions } from './audio-actions.mjs';
import { RECONNECT_MESSAGE, projectProjection } from './audio-project.mjs';
import {
  AudioArchiveGateway, validateSessionManifest, validateAnnouncementOutput, validateSpeakerOutput,
  reconstructAnnouncementOutput, reconstructSpeakerOutput
} from './audio-archive-client.mjs';
import {
  workflows, lifecycleLabel, sourceLabel, eligible, dateLabel, bytesLabel, mergeSessions,
  selectSessions, selectResults, recoveryPolicy, editorUrl, deletionImpact, parseArchiveIntent, RequestGeneration,
  processingAvailabilityMessage, pageItems, latestOutput
} from './audio-archive-core.mjs';
import { ArchiveAuthController } from './audio-archive-auth.mjs';

const $ = id => document.getElementById(id);
const gateway = new AudioArchiveGateway(globalThis.__MESER_AUDIO_ARCHIVE_GATEWAY__ || document.querySelector('meta[name="audio-archive-gateway"]')?.content || '');
const generations = Object.fromEntries(['auth', 'list', 'detail', 'play', 'delete'].map(key => [key, new RequestGeneration()]));
const state = {
  authenticated: false, sessions: null, maintenance: null, detail: null, projects: new Map(), outputMeta: new Map(),
  projectHistories: new Map(),
  url: null, target: null, returnFocus: null, busy: false, intentConsumed: false, detailInput: null, detailOpen: new Set(),
  resultSort: { announcement: 'newest', speaker: 'newest' },
  picker: { open: false, requested: false, page: 0, pageSize: 10 }
};

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function button(label, action, className) {
  const node = element('button', label, className); node.type = 'button'; node.addEventListener('click', action); return node;
}
function message(error) {
  if ([401, 403].includes(error?.status)) return RECONNECT_MESSAGE;
  if (error?.status === 409) return 'Данные изменились или операция сейчас недоступна. Загрузите актуальное состояние и подтвердите действие заново.';
  if (error?.status === 404) return 'Запись или результат больше не доступны.';
  return error?.userMessage || 'Не удалось получить подтверждение от архива. Проверьте состояние перед повторным действием.';
}
function setArchiveStatus(text, tone = 'neutral') {
  $('status').textContent = text;
  $('status').dataset.tone = tone;
}
function report(error) {
  if ([401, 403].includes(error?.status)) clearSession();
  setArchiveStatus(message(error), 'error');
}
function technical(data) {
  const details = element('details', undefined, 'technical-details');
  details.append(element('summary', 'Технические сведения'), element('pre', JSON.stringify(data, null, 2)));
  return details;
}
function workflowTitle(workflow) {
  return workflow === 'announcement' ? 'Анонс-мейкер' : 'Финальные версии спикерской';
}
function mediaTypeLabel(value) {
  return ({ 'audio/mpeg': 'MP3', 'audio/wav': 'WAV', 'audio/mp4': 'M4A' })[value] || value || 'Формат не указан';
}
function trackCount(session) {
  if (session.sourceState === 'available') return session.sourceTracks.length;
  return Array.isArray(session.deletedSources?.tracks) ? session.deletedSources.tracks.length : null;
}
function trackCountLabel(count) {
  if (count === null) return 'Количество дорожек неизвестно';
  const lastTwo = count % 100, last = count % 10;
  const noun = lastTwo >= 11 && lastTwo <= 14 ? 'дорожек' : last === 1 ? 'дорожка' : last >= 2 && last <= 4 ? 'дорожки' : 'дорожек';
  return `${count} ${noun}`;
}
function attentionFor(session) {
  return (state.maintenance?.transactions || []).filter(operation => operation.sessionId === session.id);
}

function clearPlayback() {
  generations.play.next();
  $('audio').pause(); $('audio').removeAttribute('src'); $('audio').load();
  $('download').removeAttribute('href'); $('download').removeAttribute('download');
  if (state.url) URL.revokeObjectURL(state.url);
  state.url = null; $('player').hidden = true; $('playback-status').textContent = '';
}
function closeDetail({ updateUrl = true } = {}) {
  generations.detail.next(); clearPlayback(); state.detail = null; state.detailInput = null; state.detailOpen.clear(); state.outputMeta.clear();
  $('detail').hidden = true; $('detail-heading').replaceChildren(); $('detail-body').replaceChildren(); $('archive-index').hidden = false;
  if (updateUrl) {
    const url = new URL(location.href); url.searchParams.delete('session'); history.replaceState(history.state, '', url);
  }
  openRecordPicker();
}
function clearSession() {
  for (const generation of Object.values(generations)) generation.next();
  clearPlayback(); state.authenticated = false; state.sessions = null; state.maintenance = null; state.detail = null; state.detailInput = null; state.target = null;
  state.projects.clear(); state.projectHistories.clear(); state.outputMeta.clear(); $('detail').hidden = true; $('detail-heading').replaceChildren(); $('detail-body').replaceChildren(); $('archive-index').hidden = false;
  if ($('delete-dialog').open) $('delete-dialog').close(); updateControls(); render();
}
function updateControls() {
  $('login').hidden = state.authenticated; $('logout').hidden = !state.authenticated;
  $('refresh').disabled = !state.authenticated || state.busy; $('rebuild').disabled = !state.authenticated || state.busy;
}

const authController = new ArchiveAuthController({
  gateway,
  mount: $('storage-frame'),
  onState: ({ state: authState, detail }) => {
    const help = $('storage-help');
    help.hidden = !['storage-access-required', 'opening-first-party-bootstrap', 'awaiting-storage-grant', 'unsupported'].includes(authState) &&
      !(authState === 'denied' && detail?.code !== 'invalid_password');
    const labels = {
      'checking-password': 'Проверка пароля…',
      'verifying-session': 'Подтверждаем защищённый сеанс…',
      'storage-access-required': 'Пароль принят, но Safari пока не разрешил странице использовать защищённый сеанс.',
      'opening-first-party-bootstrap': 'Открываем защищённую вкладку архива…',
      'awaiting-storage-grant': 'Вернитесь после подтверждения пароля и разрешите доступ в блоке ниже.',
      'connected': 'Подключение подтверждено.',
      'unsupported': 'Безопасный запрос доступа не поддерживается этим браузером.',
      'denied': detail?.code === 'invalid_password' ? 'Неверный пароль.' : 'Доступ Safari не разрешён. Можно повторить.',
      'error': detail?.message || 'Не удалось подтвердить подключение. Повторите действие.'
    };
    if (labels[authState]) $('login-status').textContent = labels[authState];
    if (authState === 'connected' && !state.authenticated && $('login-dialog').open) {
      state.authenticated = true;
      if ($('login-dialog').open) $('login-dialog').close();
      updateControls();
      void refresh();
    }
  }
});
function openRecordPicker() {
  state.picker.open = true; $('records').hidden = false; $('record-picker-open').setAttribute('aria-expanded', 'true');
  $('records-title').focus();
}
function closeRecordPicker() {
  state.picker.open = false; $('records').hidden = true; $('record-picker-open').setAttribute('aria-expanded', 'false');
  $('record-picker-open').focus();
}

function currentFilters() {
  const form = $('filters').elements, quick = form.quick.value;
  return {
    search: form.search.value, sort: form.sort.value,
    lifecycle: ['incoming', 'archived'].includes(quick) ? quick : '', attention: quick === 'attention',
    sources: form.availableOnly.checked ? 'available' : '', speakerProject: form.speakerProject.checked,
    announcementResult: form.announcementResult.checked, speakerResult: form.speakerResult.checked
  };
}
function projectState(session) {
  if (!session.workflows.speaker.currentDraft) return { label: 'Проект ещё не сохранён', kind: '' };
  const history = state.projectHistories.get(session.id);
  if (history?.states?.length) return { label: session.sourceState === 'available' ? 'Проект спикерской сохранён' : 'Проект сохранён, исходники недоступны', kind: session.sourceState === 'available' ? 'is-ready' : 'is-warning' };
  const project = state.projects.get(session.id);
  if (!project) return { label: 'Проект проверяется…', kind: 'is-warning' };
  if (project.projection) return { label: 'Проект спикерской сохранён', kind: 'is-ready' };
  return { label: 'Сохранённый проект недоступен', kind: 'is-warning' };
}
function processingUnavailable(session) {
  return processingAvailabilityMessage(session);
}
function editorLink(session, workflow, label) {
  if (!eligible(session)) return null;
  const link = element('a', label, 'action-primary');
  link.href = editorUrl(session, workflow); link.target = '_blank'; link.rel = 'noopener'; return link;
}
function attentionSummary(session) {
  const operations = attentionFor(session);
  if (!operations.length) return null;
  const kinds = new Set(operations.map(operation => operation.kind));
  const descriptions = [];
  if (kinds.has('ingestion')) descriptions.push('сохранение исходников');
  if (operations.some(operation => operation.kind === 'publication' && operation.workflow === 'announcement')) descriptions.push('версия для анонс-мейкера');
  if (operations.some(operation => operation.kind === 'publication' && operation.workflow === 'speaker')) descriptions.push('финальная версия спикерской');
  if (kinds.has('pending_delete')) descriptions.push('удаление');
  return `Требует внимания · ${descriptions.join(', ') || 'состояние операции'}`;
}
function renderRecords() {
  $('session-list').replaceChildren();
  $('record-pagination').hidden = true;
  if (!state.picker.requested) { $('matching').textContent = 'Список появится после поиска.'; return; }
  if (!state.sessions) { $('matching').textContent = 'Список записей не загружен.'; return; }
  const chosen = currentFilters();
  if (chosen.attention && !state.maintenance) { $('matching').textContent = 'Сведения о незавершённых операциях не загружены. Фильтр внимания пока недоступен.'; return; }
  let sessions;
  try { sessions = selectSessions(state.sessions, chosen, state.maintenance?.transactions); }
  catch (error) { $('matching').textContent = error.message; return; }
  const month = $('filters').elements.month.value;
  if (month) sessions = sessions.filter(session => String(session.recordedAt || '').slice(0, 7) === month);
  const pageCount = Math.max(1, Math.ceil(sessions.length / state.picker.pageSize));
  state.picker.page = Math.min(state.picker.page, pageCount - 1);
  const start = state.picker.page * state.picker.pageSize;
  const visible = pageItems(sessions, state.picker.page, state.picker.pageSize);
  $('matching').textContent = !state.sessions.length ? 'Аудиоархив пока пуст.' : sessions.length ? `Найдено: ${sessions.length} · ${start + 1}–${start + visible.length}` : 'Ничего не найдено. Измените запрос или фильтры.';
  for (const session of visible) {
    const card = element('article', undefined, 'archive-card source-row'); card.dataset.sessionId = session.id;
    const info = element('div', undefined, 'record-info'), badges = element('div', undefined, 'status-badges');
    const count = trackCount(session), project = projectState(session), attention = attentionSummary(session);
    info.append(element('h3', session.title), element('p', `${dateLabel(session.recordedAt)} · ${trackCountLabel(count)}`));
    badges.append(element('span', lifecycleLabel(session), 'status-badge'), element('span', sourceLabel(session), `status-badge ${session.sourceState === 'available' ? 'is-ready' : 'is-warning'}`));
    info.append(badges, element('p', `Анонс-мейкер: ${session.workflows.announcement.outputs.length} · Финальные версии спикерской: ${session.workflows.speaker.outputs.length}`), element('p', project.label, project.kind ? `record-project ${project.kind}` : 'record-project'));
    if (attention) info.append(element('p', attention, 'attention-summary'));
    card.append(info, button('Открыть запись', () => openDetail(session.id, { updateUrl: true }), 'action-primary'));
    $('session-list').append(card);
  }
  if (sessions.length > state.picker.pageSize) {
    $('record-pagination').hidden = false; $('record-page').textContent = `${state.picker.page + 1} из ${pageCount}`;
    $('record-prev').disabled = state.picker.page === 0; $('record-next').disabled = state.picker.page + 1 >= pageCount;
  }
}

function contextualRecovery(session, container) {
  const operations = attentionFor(session);
  if (state.maintenance && !operations.length) return;
  const section = element('section', undefined, 'detail-section attention-section');
  section.append(element('h3', 'Требует внимания'));
  if (!state.maintenance) section.append(element('p', 'Сведения о незавершённых операциях не загружены.'));
  else if (!operations.length) section.append(element('p', 'Незавершённых операций для этой записи нет.'));
  for (const operation of operations) {
    const policy = recoveryPolicy(operation), row = element('article', undefined, 'attention');
    const label = operation.kind === 'pending_delete' ? 'Незавершённое удаление' : 'Незавершённое сохранение';
    const object = operation.kind === 'ingestion' ? 'исходных дорожек' : operation.kind === 'publication' ?
      (operation.workflow === 'announcement' ? 'версии для анонс-мейкера' : 'финальной версии спикерской') : 'данных записи';
    row.append(element('h4', label), element('p', `${label} ${object}.`));
    if (operation.reservedVersion) row.append(element('p', `Зарезервирована версия ${operation.reservedVersion}. Номер не переиспользуется.`));
    row.append(element('p', policy.local));
    for (const [action, text] of policy.actions) row.append(button(text, () => recover(operation, action), action === 'discard' || operation.kind === 'pending_delete' ? 'danger' : ''));
    row.append(technical(operation)); section.append(row);
  }
  container.append(section);
}

function validatedMetadata(session, workflow, output) {
  const metadata = state.outputMeta.get(`${workflow}:${output.outputId}`);
  if (!metadata) return { label: 'Имя файла и формат проверяются…', valid: false };
  if (metadata.error) return { label: 'Имя файла и формат недоступны: сведения не прошли проверку.', valid: false };
  return { label: `${metadata.recipe.result.presentationFilename} · ${mediaTypeLabel(metadata.recipe.result.mediaType)}`, valid: true };
}
function resultCard(session, output, workflow) {
  const card = element('article', undefined, 'archive-card result-row');
  const meta = validatedMetadata(session, workflow, output);
  card.append(element('div', undefined, 'result-info'));
  card.firstElementChild.append(element('h4', `Версия ${output.version}`), element('p', `${dateLabel(output.createdAt)} · ${bytesLabel(output.sizeBytes)}`), element('p', meta.label));
  const actions = element('div', undefined, 'toolbar');
  const play = button('Прослушать', () => loadOutput(session, output, workflow));
  const download = button('Скачать', () => loadOutput(session, output, workflow, true));
  play.disabled = !meta.valid; download.disabled = !meta.valid;
  if (workflow === 'speaker' && meta.valid) {
    const resume = element('a', 'Продолжить редактирование с этой финальной версии');
    resume.href = `Audio-Editor.html?session=${encodeURIComponent(session.id)}&workflow=speaker&speakerOutput=${encodeURIComponent(output.outputId)}`;
    actions.append(resume);
  }
  actions.append(play, download, contextActions(`Версия ${output.version}`, button('Удалить версию', () => openDeletion(session.id, { kind: 'output-version', workflow, version: output.version }), 'danger')));
  card.append(actions); return card;
}
function latestResults(session) {
  const section = element('details', undefined, 'detail-section ready-results'); section.open = true;
  section.append(element('summary', 'Готовые записи'));
  const body = element('div', undefined, 'ready-results__body');
  for (const workflow of ['speaker', 'announcement']) {
    const output = latestOutput(session, workflow);
    const group = element('section', undefined, 'ready-result');
    group.append(element('h3', workflow === 'speaker' ? 'Спикерская' : 'Анонс-мейкер'));
    if (output) {
      const card = resultCard(session, output, workflow);
      card.querySelector('.audio-actions')?.remove();
      group.append(card);
    } else group.append(element('p', 'Готовых версий пока нет.'));
    body.append(group);
  }
  section.append(body); return section;
}
function workflowSection(session, workflow) {
  const data = session.workflows[workflow], section = element('section', undefined, `detail-section workflow-section workflow-${workflow}`);
  section.append(element('h3', workflow === 'announcement' ? 'Версии для анонс-мейкера' : 'Финальные версии спикерской'));
  const sortLabel = element('label', `Сортировка · ${workflowTitle(workflow)}`), sort = element('select');
  sort.id = `version-sort-${workflow}`;
  for (const [value, text] of Object.entries({ newest: 'Сначала новые', oldest: 'Сначала старые', version: 'Версия по возрастанию', 'version-desc': 'Версия по убыванию', title: 'Название записи' })) {
    const option = element('option', text); option.value = value; sort.append(option);
  }
  sort.value = state.resultSort[workflow]; sortLabel.append(sort); section.append(sortLabel);
  const list = element('div', undefined, 'version-list');
  const draw = () => {
    list.replaceChildren();
    const versions = selectResults([session], workflow, state.resultSort[workflow]).map(result => result.output);
    for (const output of versions) list.append(resultCard(session, output, workflow));
    if (!versions.length) list.append(element('p', 'Сохранённых версий пока нет.'));
  };
  sort.addEventListener('change', () => { state.resultSort[workflow] = sort.value; draw(); });
  draw(); section.append(list);
  for (const version of data.deletedVersions || []) section.append(element('p', `Версия ${version} удалена. Номера версий не переиспользуются.`, 'deleted-version'));
  for (const transaction of attentionFor(session)) if (transaction.workflow === workflow && transaction.reservedVersion && !(data.deletedVersions || []).includes(transaction.reservedVersion)) {
    section.append(element('p', `Версия ${transaction.reservedVersion} занята незавершённым сохранением.`, 'reserved-version'));
  }
  const remove = button(workflow === 'announcement' ? 'Удалить все версии для анонс-мейкера' : 'Удалить все финальные версии спикерской', () => openDeletion(session.id, { kind: 'output-series', workflow }), 'danger');
  remove.disabled = !data.outputs.length; const disclosure = element('details', undefined, 'destructive-disclosure'); disclosure.append(element('summary', 'Управление версиями'), remove); section.append(disclosure);
  return section;
}
function workflowChoice(session, workflow) {
  const isAnnouncement = workflow === 'announcement';
  const project = isAnnouncement ? null : state.projects.get(session.id);
  const card = element('article', undefined, `workflow-choice ${isAnnouncement ? 'workflow-choice-announcement' : 'project-section'}`);
  card.append(element('p', isAnnouncement ? 'КОРОТКАЯ ВЕРСИЯ' : 'ПОЛНАЯ ЗАПИСЬ', 'choice-kicker'));
  card.append(element('h3', isAnnouncement ? 'Подготовить для анонса' : 'Обработать спикерскую'));
  card.append(element('p', isAnnouncement ? 'Обрезать запись и сохранить готовую версию для анонс-мейкера.' : 'Продолжить поканальный проект и сохранить финальную спикерскую запись.', 'choice-description'));
  if (isAnnouncement) {
    const count = session.workflows.announcement.outputs.length;
    card.append(element('p', count ? `Готовых версий: ${count}` : 'Готовых версий пока нет', count ? 'choice-state is-ready' : 'choice-state'));
  } else {
    const history = state.projectHistories.get(session.id);
    if (!session.workflows.speaker.currentDraft) card.append(element('p', 'Проект ещё не начат', 'choice-state'));
    else if (project?.projection || history?.states?.length) card.append(element('p', session.sourceState === 'available' ? `Проект сохранён ${dateLabel(project?.projection?.savedAt || history.states[0].savedAt)}` : 'Проект сохранён, но исходные дорожки недоступны.', `choice-state ${session.sourceState === 'available' ? 'is-ready' : 'is-warning'}`));
    else card.append(element('p', 'Сохранённый проект сейчас недоступен', 'choice-state is-warning'));
  }
  const projectSafe = isAnnouncement || !session.workflows.speaker.currentDraft || Boolean(project?.projection);
  const link = projectSafe ? editorLink(session, workflow, isAnnouncement ? 'Открыть анонс-мейкер' : session.workflows.speaker.currentDraft ? 'Продолжить обработку' : 'Начать обработку') : null;
  if (link) card.append(link);
  else card.append(element('p', projectSafe ? processingUnavailable(session) : 'Продолжение недоступно: сохранённый проект не прошёл проверку и не будет перезаписан.', 'unavailable-note'));
  return card;
}
function renderDetail() {
  const session = state.detail, heading = $('detail-heading'), container = $('detail-body');
  const disclosureState = Object.fromEntries(['version-history', 'project-disclosure', 'source-section', 'record-management', 'danger-zone']
    .map(name => [name, Boolean(container.querySelector(`.${name}`)?.open || state.detailOpen.has(name))]));
  heading.replaceChildren(); container.replaceChildren();
  const identity = element('div', undefined, 'record-identity');
  identity.append(element('p', 'Запись Zoom', 'eyebrow'));
  const heroTitle = element('h2', session.title); heroTitle.id = 'detail-title'; heroTitle.tabIndex = -1; identity.append(heroTitle);
  const count = trackCount(session), origin = ({ manual: 'Создана вручную', device: 'С устройства', zoom_webhook: 'Zoom' })[session.origin.kind] || 'Источник не указан';
  identity.append(element('p', `${dateLabel(session.recordedAt)} · ${trackCountLabel(count)} · ${origin}`, 'record-meta'));
  const badges = element('div', undefined, 'status-badges'); badges.append(element('span', lifecycleLabel(session), 'status-badge'), element('span', sourceLabel(session), `status-badge ${session.sourceState === 'available' ? 'is-ready' : 'is-warning'}`)); identity.append(badges); heading.append(identity);

  const primary = element('section', undefined, 'detail-section primary-workflows');
  primary.append(element('h3', 'Что сделать с этой записью?'));
  const choices = element('div', undefined, 'workflow-choices');
  choices.append(workflowChoice(session, 'announcement'), workflowChoice(session, 'speaker'));
  primary.append(choices); container.append(primary, latestResults(session));
  const history = element('details', undefined, 'detail-section version-history'); history.open = disclosureState['version-history']; history.append(element('summary', 'Все версии и управление'));
  const historyBody = element('div'); historyBody.append(workflowSection(session, 'announcement'), workflowSection(session, 'speaker')); history.append(historyBody); container.append(history);
  const project = element('details', undefined, 'detail-section project-disclosure'); project.open = disclosureState['project-disclosure']; project.append(element('summary', 'Проект обработки спикерской'));
  const speakerProject = state.projects.get(session.id);
  const savedHistory = state.projectHistories.get(session.id);
  if (!session.workflows.speaker.currentDraft) project.append(element('p', 'Сохранённого проекта пока нет. Начать обработку можно в верхней части страницы.'));
  else if (speakerProject?.projection || savedHistory?.states?.length) project.append(element('p', session.sourceState === 'available' ? `Проект сохранён ${dateLabel(speakerProject?.projection?.savedAt || savedHistory.states[0].savedAt)}. Продолжить его можно в верхней части страницы.` : 'Проект сохранён, но исходные дорожки недоступны. История и финальные версии остаются доступны.'));
  else project.append(element('p', 'Сохранённый проект не прошёл проверку и не будет перезаписан. Продолжение обработки недоступно.'));
  if (gateway.speakerProjectHistoryVersion === 1) {
    const history = state.projectHistories.get(session.id);
    project.append(element('h3', 'История проекта'));
    if (history?.error) project.append(element('p', 'История проекта не прошла строгую проверку. Восстановление недоступно.'));
    else if (!history?.states?.length) project.append(element('p', 'Явных сохранений с неизменяемой историей пока нет.'));
    else for (const saved of history.states) {
      const valid = Number.isSafeInteger(saved.draftRevision) && saved.draftRevision > 0 && typeof saved.savedAt === 'string' &&
        typeof saved.current === 'boolean' && typeof saved.canonicalSourcesAvailable === 'boolean' && Array.isArray(saved.finalVersions);
      if (!valid) { project.replaceChildren(element('summary', 'Проект обработки спикерской'), element('p', 'История проекта повреждена. Восстановление недоступно.')); break; }
      const row = element('article', undefined, 'archive-card project-state-row');
      row.append(element('h4', `Состояние ${saved.draftRevision}${saved.current ? ' · текущее' : ''}`),
        element('p', dateLabel(saved.savedAt)),
        element('p', saved.canonicalSourcesAvailable ? 'Исходники доступны' : 'Проект сохранён, но исходные дорожки недоступны.'),
        element('p', saved.finalVersions.length ? `Связанные финальные версии: ${saved.finalVersions.map(item => item.version).join(', ')}` : 'Связанных финальных версий нет.'));
      const resume = element('a', 'Продолжить с этого состояния');
      resume.href = `Audio-Editor.html?session=${encodeURIComponent(session.id)}&workflow=speaker&projectRevision=${saved.draftRevision}`;
      row.append(resume); project.append(row);
    }
  } else project.append(element('p', 'Версия шлюза несовместима с историей проекта. Просмотр и скачивание совместимых записей доступны; изменения «Спикерская» заблокированы.'));
  container.append(project);
  const sources = element('details', undefined, 'detail-section source-section'); sources.open = true; sources.append(element('summary', `Исходные дорожки${count === null ? '' : ` · ${count}`}`));
  if (session.sourceState === 'available') for (const track of [...session.sourceTracks].sort((a, b) => a.ordinal - b.ordinal)) {
    const row = element('div', undefined, 'source-track'); row.append(element('span', String(track.ordinal), 'track-number'), element('span', track.originalName, 'track-name'), element('span', `${mediaTypeLabel(track.mediaType)} · ${bytesLabel(track.sizeBytes)}`, 'track-meta')); sources.append(row);
  }
  else if (session.sourceState === 'deleted') sources.append(element('p', `Исходники удалены${trackCount(session) === null ? '' : ` · дорожек было: ${trackCount(session)}`}. Имена и форматы удалённых дорожек не сохранены.`));
  else sources.append(element('p', 'Исходники недоступны. Сведения о дорожках нельзя подтвердить.'));
  container.append(sources);
  contextualRecovery(session, container);

  const management = element('details', undefined, 'detail-section record-management'); management.open = disclosureState['record-management']; management.append(element('summary', 'Управление записью'));
  const form = element('form'), titleLabel = element('label', 'Название записи'), title = element('input');
  const serverDate = session.recordedAt ? new Date(session.recordedAt).toISOString().slice(0, -1) : '';
  const draft = state.detailInput?.sessionId === session.id ? state.detailInput : null;
  title.value = draft?.titleDirty ? draft.title : session.title; title.required = true; title.maxLength = 200; title.id = 'metadata-title'; titleLabel.append(title);
  const dateLabelNode = element('label', 'Дата и время записи (UTC; пусто — дата не указана)'), date = element('input'); date.type = 'datetime-local'; date.step = '0.001'; date.id = 'metadata-date';
  date.value = draft?.dateDirty ? draft.date : serverDate; dateLabelNode.append(date);
  const save = element('button', 'Сохранить название и дату'); save.type = 'submit'; const feedback = element('p'); feedback.id = 'metadata-status'; feedback.setAttribute('role', 'status');
  feedback.textContent = draft?.notice || '';
  const rememberInput = changed => {
    const current = state.detailInput?.sessionId === session.id ? state.detailInput : null;
    state.detailInput = {
      sessionId: session.id, title: title.value, date: date.value,
      titleDirty: Boolean(current?.titleDirty || changed === 'title' || title.value !== session.title),
      dateDirty: Boolean(current?.dateDirty || changed === 'date' || date.value !== serverDate),
      notice: current?.notice || ''
    };
    return state.detailInput;
  };
  title.addEventListener('input', () => rememberInput('title')); date.addEventListener('input', () => rememberInput('date'));
  const reload = button('Загрузить актуальные сведения', () => {
    const input = rememberInput();
    if (input.titleDirty || input.dateDirty) input.notice = 'Актуальные сведения загружены. Введённые значения сохранены в форме.';
    openDetail(session.id).then(() => { const disclosure = document.querySelector('.record-management'); if (disclosure) disclosure.open = true; });
  });
  form.append(titleLabel, dateLabelNode, save, feedback, reload);
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (state.busy || save.disabled) return;
    const input = rememberInput();
    const patch = { title: title.value.trim(), recordedAt: date.value === serverDate ? session.recordedAt : date.value ? new Date(date.value + 'Z').toISOString() : null };
    save.disabled = true;
    await mutate(() => writeSession(session, () => gateway.updateSession(session.id, session.revision, patch, crypto.randomUUID())), () => {
      state.detailInput = null; openDetail(session.id);
    }, error => {
      input.notice = message(error) + ' Введённые значения сохранены в форме. Загрузите актуальные сведения и решите, повторять ли изменение.';
      feedback.textContent = input.notice;
    });
  });
  const lifecycle = button(session.lifecycle.state === 'incoming' ? 'Убрать из рабочего списка' : 'Вернуть в рабочий список', () => mutate(() => writeSession(session, () => gateway.setLifecycle(session.id, session.lifecycle.state === 'incoming' ? 'archive' : 'restore', session.revision)), () => openDetail(session.id)));
  management.append(form, lifecycle); container.append(management);

  const danger = element('details', undefined, 'danger-zone'); danger.open = disclosureState['danger-zone']; danger.append(element('summary', 'Опасная зона'));
  const dangerBody = element('div'); dangerBody.append(element('p', 'Необратимые действия требуют свежей проверки состава записи и отдельного подтверждения.'));
  const deleteSources = button('Удалить исходные дорожки', () => openDeletion(session.id, { kind: 'sources' }), 'danger'); deleteSources.disabled = session.sourceState !== 'available';
  dangerBody.append(deleteSources, button('Удалить запись полностью', () => openDeletion(session.id, { kind: 'purge' }), 'danger')); danger.append(dangerBody); container.append(danger);
  container.append(technical({ id: session.id, revision: session.revision, storage: session.storage, relations: session.relations, origin: session.origin }));
}

async function loadOutputMetadata(session, sequence, auth) {
  const work = [];
  for (const workflow of Object.keys(workflows)) for (const output of session.workflows[workflow].outputs) work.push((async () => {
    const key = `${workflow}:${output.outputId}`;
    try {
      const metadata = await (workflow === 'speaker' ? gateway.getSpeakerOutput(session.id, output.outputId) : gateway.getAnnouncementOutput(session.id, output.outputId));
      if (!generations.detail.current(sequence) || !generations.auth.current(auth)) return;
      const validate = workflow === 'speaker' ? validateSpeakerOutput : validateAnnouncementOutput;
      if (!validate(metadata.output, metadata.recipe, session.id) || metadata.output.outputId !== output.outputId || metadata.output.version !== output.version || metadata.output.blobId !== output.blobId || metadata.output.sha256 !== output.sha256 || metadata.output.sizeBytes !== output.sizeBytes || metadata.output.recipeSnapshotRef !== output.recipeSnapshotRef) throw new Error('Invalid output metadata');
      state.outputMeta.set(key, metadata);
    } catch (error) {
      if ([401, 403].includes(error?.status)) throw error;
      if (generations.detail.current(sequence) && generations.auth.current(auth)) state.outputMeta.set(key, { error: true });
    }
  })());
  const results = await Promise.allSettled(work), failure = results.find(result => result.status === 'rejected'); if (failure) throw failure.reason;
}
async function openDetail(id, { updateUrl = false } = {}) {
  if (state.busy) return;
  if (state.detailInput?.sessionId !== id) state.detailInput = null;
  if (state.detail?.id === id) state.detailOpen = new Set([...$('detail-body').querySelectorAll(':scope > details[open]')]
    .flatMap(details => [...details.classList].filter(name => ['version-history', 'project-disclosure', 'source-section', 'record-management', 'danger-zone'].includes(name))));
  else state.detailOpen.clear();
  const sequence = generations.detail.next(), auth = generations.auth.value; clearPlayback(); state.detail = null; state.outputMeta.clear();
  $('archive-index').hidden = true; $('detail').hidden = false; $('detail-heading').replaceChildren(); $('detail-body').replaceChildren(element('p', 'Загрузка актуальных сведений…'));
  try {
    const session = await gateway.getSession(id);
    if (!generations.detail.current(sequence) || !generations.auth.current(auth)) return;
    if (!validateSessionManifest(session) || session.id !== id) throw new Error('Invalid session');
    let project = null, projectHistory = null;
    if (session.workflows.speaker.currentDraft) {
      try { const result = await gateway.loadDraft(id, 'speaker'); project = { draft: result.draft, projection: projectProjection(session, result.draft) }; }
      catch (error) { if ([401, 403].includes(error?.status)) throw error; project = { error: true }; }
    }
    if (gateway.speakerProjectHistoryVersion === 1) {
      try { projectHistory = await gateway.speakerProjectHistory(id); }
      catch (error) { if ([401, 403].includes(error?.status)) throw error; projectHistory = { error: true }; }
    }
    if (!generations.detail.current(sequence) || !generations.auth.current(auth)) return;
    if (project) state.projects.set(id, project); else state.projects.delete(id);
    if (projectHistory) state.projectHistories.set(id, projectHistory); else state.projectHistories.delete(id);
    state.detail = session; renderDetail(); renderRecords();
    await loadOutputMetadata(session, sequence, auth);
    if (!generations.detail.current(sequence) || !generations.auth.current(auth)) return;
    renderDetail();
    if (updateUrl) { const url = new URL(location.href); url.searchParams.set('session', id); history.replaceState(history.state, '', url); }
    $('detail-title').focus(); $('detail').scrollIntoView({ block: 'start' });
  } catch (error) {
    if (!generations.detail.current(sequence) || !generations.auth.current(auth)) return;
    const title = element('h2', 'Запись недоступна'); title.id = 'detail-title'; title.tabIndex = -1; $('detail-heading').replaceChildren(title);
    $('detail-body').replaceChildren(element('p', error?.status === 404 ? 'Запись по ссылке не найдена или уже удалена.' : message(error)));
    if ([401, 403].includes(error?.status)) report(error);
  }
}

function renderMaintenance() {
  $('operations').replaceChildren(); $('observations').replaceChildren();
  if (!state.maintenance) { $('operations').append(element('p', 'Сведения об операциях не загружены.')); return; }
  const known = new Set((state.sessions || []).map(session => session.id));
  const operations = state.maintenance.transactions.filter(operation => !known.has(operation.sessionId));
  if (!operations.length) $('operations').append(element('p', 'Операций без подтверждённой записи нет.'));
  const phases = { uploading: 'Передача частей', staged: 'Части подготовлены', cancelled: 'Передача остановлена', finalizing: 'Завершение сохранения', discarding: 'Удаление незавершённого сохранения', pending_delete: 'Незавершённое удаление' };
  for (const operation of operations) {
    const policy = recoveryPolicy(operation), card = element('article', undefined, 'archive-card');
    card.append(element('h3', 'Запись ещё не определена'), element('p', operation.kind === 'ingestion' ? 'Незавершённое сохранение исходников' : operation.kind === 'pending_delete' ? 'Незавершённое удаление' : 'Незавершённое сохранение результата'), element('p', phases[operation.state] || 'Состояние не распознано'), element('p', policy.local));
    for (const [action, label] of policy.actions) card.append(button(label, () => recover(operation, action), action === 'discard' || operation.kind === 'pending_delete' ? 'danger' : ''));
    card.append(technical(operation)); $('operations').append(card);
  }
  $('observations').append(element('h3', `Наблюдения для ручной проверки: ${state.maintenance.orphans.length}`), element('p', 'Наблюдения доступны только для диагностики. Автоматическая очистка недоступна.'));
  for (const observation of state.maintenance.orphans) $('observations').append(technical(observation));
}
function render() { renderRecords(); renderMaintenance(); }

async function refresh() {
  if (!state.authenticated) return;
  const sequence = generations.list.next(), auth = generations.auth.value; clearPlayback(); setArchiveStatus('Загрузка записей и незавершённых операций…', 'busy');
  state.sessions = null; state.maintenance = null; state.projects.clear(); render();
  const results = await Promise.allSettled([gateway.listSessions('incoming'), gateway.listSessions('archived'), gateway.listIncomplete()]);
  if (!generations.list.current(sequence) || !generations.auth.current(auth)) return;
  const authFailure = results.find(result => result.status === 'rejected' && [401, 403].includes(result.reason?.status)); if (authFailure) { report(authFailure.reason); return; }
  const errors = [];
  try {
    if (results.slice(0, 2).every(result => result.status === 'fulfilled')) state.sessions = mergeSessions(results[0].value.sessions, results[1].value.sessions);
    else errors.push('Не удалось загрузить оба списка записей.');
    if (results[2].status === 'fulfilled' && Array.isArray(results[2].value.transactions) && Array.isArray(results[2].value.orphans)) state.maintenance = results[2].value;
    else errors.push('Не удалось загрузить незавершённые операции.');
  } catch { errors.push('Данные записей повреждены.'); }
  if (state.sessions) {
    const projects = await Promise.allSettled(state.sessions.filter(session => session.workflows.speaker.currentDraft).map(async session => {
      const result = await gateway.loadDraft(session.id, 'speaker'); return [session.id, { draft: result.draft, projection: projectProjection(session, result.draft) }];
    }));
    if (!generations.list.current(sequence) || !generations.auth.current(auth)) return;
    const projectAuthFailure = projects.find(result => result.status === 'rejected' && [401, 403].includes(result.reason?.status)); if (projectAuthFailure) { report(projectAuthFailure.reason); return; }
    for (const result of projects) if (result.status === 'fulfilled') state.projects.set(...result.value);
    for (const session of state.sessions.filter(session => session.workflows.speaker.currentDraft)) if (!state.projects.has(session.id)) state.projects.set(session.id, { error: true });
  }
  render(); setArchiveStatus(errors.length ? `${errors.join(' ')} Обновите данные.` : 'Данные загружены. Просмотр не изменяет аудиоархив.', errors.length ? 'error' : 'ready');
  await consumeArchiveIntent();
}

async function loadOutput(session, output, workflow, downloadOnly = false) {
  clearPlayback(); const sequence = generations.play.value, auth = generations.auth.value, detail = generations.detail.value;
  $('playback-status').textContent = 'Загрузка и проверка целостности результата…';
  try {
    const metadata = state.outputMeta.get(`${workflow}:${output.outputId}`) || await (workflow === 'speaker' ? gateway.getSpeakerOutput(session.id, output.outputId) : gateway.getAnnouncementOutput(session.id, output.outputId));
    if (!generations.play.current(sequence) || !generations.auth.current(auth) || !generations.detail.current(detail) || state.detail?.id !== session.id) return;
    const validate = workflow === 'speaker' ? validateSpeakerOutput : validateAnnouncementOutput;
    if (!validate(metadata.output, metadata.recipe, session.id) || metadata.output.outputId !== output.outputId || metadata.output.version !== output.version || metadata.output.blobId !== output.blobId || metadata.output.sha256 !== output.sha256 || metadata.output.sizeBytes !== output.sizeBytes || metadata.output.recipeSnapshotRef !== output.recipeSnapshotRef) throw new Error('Invalid output identity');
    const file = await (workflow === 'speaker' ? reconstructSpeakerOutput(metadata, gateway.speakerPartFetch(metadata)) : reconstructAnnouncementOutput(metadata, gateway.announcementPartFetch(metadata)));
    if (!generations.play.current(sequence) || !generations.auth.current(auth) || !generations.detail.current(detail) || state.detail?.id !== session.id) return;
    state.url = URL.createObjectURL(file); $('audio').src = state.url; $('download').href = state.url; $('download').download = file.name;
    $('player-title').textContent = `${workflowTitle(workflow)} · ${session.title} · версия ${output.version}`; $('player-meta').textContent = `${file.name} · ${mediaTypeLabel(file.type)} · ${bytesLabel(file.size)}`;
    $('player').hidden = false; $('playback-status').textContent = 'Файл проверен и готов к воспроизведению.'; $('player').scrollIntoView({ block: 'nearest' }); if (downloadOnly) $('download').click();
  } catch (error) {
    if (!generations.play.current(sequence) || !generations.auth.current(auth)) return;
    clearPlayback(); $('playback-status').textContent = 'Не удалось загрузить и проверить результат. Воспроизведение и скачивание недоступны.'; if ([401, 403].includes(error?.status)) report(error);
  }
}
async function writeSession(session, action) {
  const auth = generations.auth.value, [fresh, maintenance] = await Promise.all([gateway.getSession(session.id), gateway.listIncomplete()]);
  if (!generations.auth.current(auth)) throw new Error('Session ended');
  if (fresh.id !== session.id || fresh.revision !== session.revision || maintenance.transactions.some(operation => operation.sessionId === session.id && (operation.kind === 'pending_delete' || ['finalizing', 'discarding'].includes(operation.state)))) throw Object.assign(new Error('Session changed'), { status: 409 });
  return action();
}
async function mutate(action, success = () => {}, failure = null) {
  if (state.busy || !state.authenticated) return; state.busy = true; updateControls(); const auth = generations.auth.value; clearPlayback();
  try { await action(); if (!generations.auth.current(auth)) return; await refresh(); if (!generations.auth.current(auth)) return; state.busy = false; await success(); }
  catch (error) {
    if (!generations.auth.current(auth)) return; if ([401, 403].includes(error?.status)) { report(error); return; }
    await refresh(); if (!generations.auth.current(auth)) return; if (failure) failure(error); else report(error);
  } finally { state.busy = false; updateControls(); }
}
async function openDeletion(id, selection) {
  if (state.busy || $('delete-dialog').open) return; const sequence = generations.delete.next(), auth = generations.auth.value;
  try {
    const [session, preview, maintenance] = await Promise.all([gateway.getSession(id), gateway.dependencyPreview(id), gateway.listIncomplete()]);
    if (!generations.delete.current(sequence) || !generations.auth.current(auth)) return;
    if (!validateSessionManifest(session) || session.id !== id || preview.sessionId !== id || preview.revision !== session.revision) throw Object.assign(new Error('Stale preview'), { status: 409 });
    if (selection.kind === 'output-version' && !session.workflows[selection.workflow].outputs.some(output => output.version === selection.version)) throw Object.assign(new Error('Missing version'), { status: 404 });
    state.target = Object.freeze({ ...selection, session, preview, idempotencyKey: crypto.randomUUID() }); state.returnFocus = document.activeElement;
    const impact = deletionImpact(preview, selection); $('delete-name').textContent = session.title; $('delete-removed').textContent = impact.removed; $('delete-retained').textContent = impact.retained;
    const pendingDeletion = maintenance.transactions.some(operation => operation.sessionId === id && (operation.kind === 'pending_delete' || ['finalizing', 'discarding'].includes(operation.state)));
    const pending = preview.pendingAnnouncementPublications + preview.pendingSpeakerSaves;
    $('delete-pending').textContent = pendingDeletion ? 'Удаление уже начато. Продолжите его в сведениях записи.' : pending ? `Незавершённых сохранений: ${pending}. Сначала завершите или удалите их.` : 'Подтверждение относится только к выбранной записи и её текущему состоянию.';
    $('purge-label').hidden = selection.kind !== 'purge'; $('purge-id').textContent = selection.kind === 'purge' ? id : ''; $('purge-confirmation').value = ''; $('delete-status').textContent = ''; $('delete-submit').disabled = Boolean(pending) || pendingDeletion; $('delete-dialog').showModal();
  } catch (error) { if (generations.delete.current(sequence) && generations.auth.current(auth)) report(error); }
}
$('delete-form').addEventListener('submit', async event => {
  event.preventDefault(); const target = state.target; if (!target || state.busy || $('delete-submit').disabled) return;
  if (target.kind === 'purge' && $('purge-confirmation').value !== target.session.id) { $('delete-status').textContent = 'Введите точный ID записи без изменений.'; return; }
  const body = { expectedRevision: target.preview.revision, idempotencyKey: target.idempotencyKey, confirmation: target.kind === 'purge' ? $('purge-confirmation').value : target.kind === 'sources' ? 'Удалить исходники, сохранить результаты' : '' }; $('delete-submit').disabled = true;
  await mutate(() => writeSession(target.session, async () => {
    const preview = await gateway.dependencyPreview(target.session.id);
    if (state.target !== target || preview.sessionId !== target.session.id || preview.revision !== target.preview.revision || JSON.stringify(preview) !== JSON.stringify(target.preview)) throw Object.assign(new Error('Dependencies changed'), { status: 409 });
    return target.kind === 'purge' ? gateway.purgeSession(target.session.id, body) : target.kind === 'sources' ? gateway.deleteSources(target.session.id, body) : target.kind === 'output-series' ? gateway.deleteOutputSeries(target.session.id, target.workflow, body) : gateway.deleteOutputVersion(target.session.id, target.workflow, target.version, body);
  }), async () => { $('delete-dialog').close(); state.target = null; if (target.kind === 'purge') closeDetail(); else if (state.detail?.id === target.session.id) await openDetail(target.session.id); }, error => {
    $('delete-status').textContent = `${message(error)} Результат не подтверждён этим запросом. Получите новый предварительный просмотр перед повтором.`; state.target = null;
  });
});
async function recover(operation, action) {
  if (state.busy) return;
  if ((action === 'discard' || operation.kind === 'pending_delete') && !globalThis.confirm(action === 'discard' ? 'Удалить только эту незавершённую операцию? Зарезервированный номер версии останется использованным.' : 'Продолжить уже начатое необратимое удаление?')) return;
  await mutate(async () => {
    const auth = generations.auth.value, latest = await gateway.listIncomplete(); if (!generations.auth.current(auth)) throw new Error('Session ended');
    const fresh = latest.transactions.find(item => item.transactionId === operation.transactionId);
    if (!fresh || fresh.kind !== operation.kind || fresh.sessionId !== operation.sessionId || fresh.workflow !== operation.workflow || !recoveryPolicy(fresh).actions.some(([allowed]) => allowed === action)) throw Object.assign(new Error('Recovery changed'), { status: 409 });
    return gateway.recoverIncomplete(fresh.transactionId, action);
  }, async () => { if (state.detail) await openDetail(state.detail.id); });
}

async function consumeArchiveIntent() {
  if (state.intentConsumed) return; let intent;
  try { intent = parseArchiveIntent(location.search); }
  catch (error) { state.intentConsumed = true; setArchiveStatus(error.message, 'error'); return; }
  if (!intent || !state.authenticated || !state.sessions) return;
  state.intentConsumed = true;
  if (!state.sessions.some(session => session.id === intent.sessionId)) { $('archive-index').hidden = true; $('detail').hidden = false; const title = element('h2', 'Запись недоступна'); title.id = 'detail-title'; $('detail-heading').replaceChildren(title); $('detail-body').replaceChildren(element('p', 'Запись по ссылке не найдена или уже удалена.')); return; }
  await openDetail(intent.sessionId, { updateUrl: false });
}
function applyLegacyAnchor() {
  if (!['#projects', '#results'].includes(location.hash)) return;
  const field = location.hash === '#projects' ? $('filters').elements.speakerProject : $('filters').elements.announcementResult;
  field.checked = true; state.picker.requested = true; openRecordPicker(); history.replaceState(history.state, '', `${location.pathname}${location.search}#records`);
}

$('record-picker-open').addEventListener('click', openRecordPicker); $('record-picker-close').addEventListener('click', closeRecordPicker);
$('filters').addEventListener('submit', event => { event.preventDefault(); state.picker.requested = true; state.picker.page = 0; renderRecords(); });
$('record-picker-recent').addEventListener('click', () => { $('filters').elements.search.value = ''; $('filters').elements.month.value = ''; $('filters').elements.sort.value = 'newest'; state.picker.requested = true; state.picker.page = 0; renderRecords(); });
$('filters').addEventListener('reset', () => requestAnimationFrame(() => { state.picker.requested = false; state.picker.page = 0; renderRecords(); }));
$('record-prev').addEventListener('click', () => { state.picker.page--; renderRecords(); }); $('record-next').addEventListener('click', () => { state.picker.page++; renderRecords(); });
$('refresh').addEventListener('click', refresh); $('detail-close').addEventListener('click', () => closeDetail()); $('player-close').addEventListener('click', clearPlayback); $('rebuild').addEventListener('click', () => mutate(() => gateway.rebuildCatalog()));
$('login').addEventListener('click', () => { $('login-status').textContent = ''; $('storage-help').hidden = true; $('login-dialog').showModal(); });
$('login-cancel').addEventListener('click', () => { authController.cancel(); $('login-dialog').close(); });
$('storage-bootstrap').addEventListener('click', () => authController.openBootstrap());
$('storage-retry').addEventListener('click', () => authController.showBridge());
$('delete-cancel').addEventListener('click', () => { if (!state.busy) $('delete-dialog').close(); }); $('delete-dialog').addEventListener('cancel', event => { if (state.busy) event.preventDefault(); });
$('delete-dialog').addEventListener('close', () => { state.target = null; generations.delete.next(); const focus = state.returnFocus?.isConnected ? state.returnFocus : $('records-title'); focus.focus(); state.returnFocus = null; });
$('login-form').addEventListener('submit', async event => {
  event.preventDefault(); const submit = event.submitter; if (submit.disabled) return; submit.disabled = true; const sequence = generations.auth.next();
  try { await authController.login($('password').value); if (!generations.auth.current(sequence)) return; }
  catch (error) { if (generations.auth.current(sequence) && !['storage_access_required', 'invalid_password'].includes(error?.code)) $('login-status').textContent = message(error); }
  finally { $('password').value = ''; submit.disabled = false; }
});
$('logout').addEventListener('click', async () => {
  clearSession(); setArchiveStatus('Отключение архива…', 'busy'); const sequence = generations.auth.value; $('login').disabled = true;
  try { await gateway.logout(); if (generations.auth.current(sequence)) setArchiveStatus('Аудиоархив отключён.'); }
  catch { if (generations.auth.current(sequence)) setArchiveStatus('Локальные данные очищены, но сервер не подтвердил выход. Повторите отключение.', 'error'); $('logout').hidden = false; }
  finally { gateway.csrfToken = null; $('login').disabled = false; }
});
window.addEventListener('pagehide', clearPlayback); window.addEventListener('pageshow', event => { if (event.persisted) initialize(); });
async function initialize() {
  applyLegacyAnchor(); render(); const sequence = generations.auth.next();
  try { await gateway.configuration(); const restored = await authController.restore(); if (!restored || !generations.auth.current(sequence)) return; state.authenticated = true; updateControls(); await refresh(); if (!state.intentConsumed) { state.picker.requested = true; openRecordPicker(); renderRecords(); } }
  catch (error) { if (generations.auth.current(sequence)) report(error); }
}
await initialize();
