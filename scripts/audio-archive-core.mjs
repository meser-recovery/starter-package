import { isUuid, validateSessionManifest } from './audio-archive-client.mjs';

export const workflows = Object.freeze({ announcement: 'Анонс-мейкер', speaker: 'Спикерская' });
export const statuses = Object.freeze({ new: 'Новая', in_progress: 'В работе', result_ready: 'Результат готов' });
export const lifecycleLabel = session => session.lifecycle.state === 'incoming' ? 'В рабочем списке' : 'Убрана из рабочего списка';
export const sourceLabel = session => session.sourceState === 'available' ? 'Исходники доступны' :
  session.sourceState === 'deleted' ? 'Исходники удалены' : 'Исходники недоступны';
export const eligible = session => session.lifecycle.state === 'incoming' && session.sourceState === 'available';
const normalized = value => String(value || '').normalize('NFKC').toLocaleLowerCase('ru');
const compareText = (a, b) => String(a).localeCompare(String(b), 'ru');
const timestamp = value => value ? Date.parse(value) : NaN;
export function dateLabel(value) {
  return Number.isFinite(timestamp(value)) ? new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'medium', timeStyle: 'medium', timeZone: 'UTC'
  }).format(new Date(value)) + ' UTC' : 'Дата не указана';
}
export const bytesLabel = value => {
  const unit = value < 1024 ? [1, 'байт'] : value < 1048576 ? [1024, 'КБ'] : [1048576, 'МБ'];
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 }).format(value / unit[0]) + ' ' + unit[1];
};
export function mergeSessions(...lists) {
  const merged = new Map();
  for (const session of lists.flat()) {
    if (!validateSessionManifest(session)) throw new Error('Данные записи повреждены.');
    if (!merged.has(session.id) || merged.get(session.id).revision < session.revision) merged.set(session.id, session);
  }
  return [...merged.values()];
}
export function validateDateRange(from = '', to = '') {
  for (const value of [from, to]) if (value && (!/^\d{4}-\d{2}-\d{2}$/.test(value) ||
    !Number.isFinite(Date.parse(value)) || new Date(value).toISOString().slice(0, 10) !== value)) throw new Error('Укажите корректные даты.');
  if (from && to && from > to) throw new Error('Дата «от» должна быть не позже даты «до».');
}
function compareDate(a, b, direction) {
  const x = timestamp(a), y = timestamp(b);
  if (!Number.isFinite(x)) return Number.isFinite(y) ? 1 : 0;
  if (!Number.isFinite(y)) return -1;
  return (x - y) * direction;
}
export function selectSessions(sessions, filters = {}, transactions = null) {
  validateDateRange(filters.from, filters.to);
  const query = normalized(filters.search).trim();
  const attention = new Set(transactions?.map(item => item.sessionId));
  return sessions.filter(session => {
    if (query && normalized(session.id) !== query && ![session.title, ...session.sourceTracks.map(t => t.originalName)].some(v => normalized(v).includes(query))) return false;
    if (filters.lifecycle && session.lifecycle.state !== filters.lifecycle) return false;
    if (filters.sources && (session.sourceState === 'available' ? 'available' : 'unavailable') !== filters.sources) return false;
    if (filters.attention && !attention.has(session.id)) return false;
    if (filters.speakerProject && !session.workflows.speaker.currentDraft) return false;
    if (filters.announcementResult && !session.workflows.announcement.outputs.length) return false;
    if (filters.speakerResult && !session.workflows.speaker.outputs.length) return false;
    for (const workflow of Object.keys(workflows)) {
      const state = filters[workflow + 'State'], result = filters[workflow + 'Result'];
      if (state && session.workflows[workflow].status !== state) return false;
      if (result && Boolean(session.workflows[workflow].outputs.length) !== (result === 'yes')) return false;
    }
    const day = Number.isFinite(timestamp(session.recordedAt)) ? new Date(session.recordedAt).toISOString().slice(0, 10) : '';
    return !((filters.from || filters.to) && (!day || (filters.from && day < filters.from) || (filters.to && day > filters.to)));
  }).sort((a, b) => {
    const sort = filters.sort || 'newest';
    const order = sort === 'title' ? compareText(a.title, b.title) : sort === 'title-desc' ? compareText(b.title, a.title) :
      sort === 'updated' ? compareDate(a.updatedAt, b.updatedAt, -1) : compareDate(a.recordedAt, b.recordedAt, sort === 'oldest' ? 1 : -1);
    return order || compareText(a.id, b.id);
  });
}
export function selectResults(sessions, workflow, sort = 'newest') {
  if (!Object.hasOwn(workflows, workflow)) throw new Error('Неизвестный вид работы.');
  return sessions.flatMap(session => session.workflows[workflow].outputs.map(output => ({ session, output, workflow })))
    .sort((a, b) => (sort === 'version' ? a.output.version - b.output.version : sort === 'version-desc' ? b.output.version - a.output.version :
      sort === 'title' ? compareText(a.session.title, b.session.title) : compareDate(a.output.createdAt, b.output.createdAt, sort === 'oldest' ? 1 : -1)) ||
      compareText(a.session.id, b.session.id) || a.output.version - b.output.version || compareText(a.output.outputId, b.output.outputId));
}
export function overview(sessions, maintenance) {
  return {
    incoming: sessions ? sessions.filter(s => s.lifecycle.state === 'incoming').length : null,
    archived: sessions ? sessions.filter(s => s.lifecycle.state === 'archived').length : null,
    announcement: sessions ? selectResults(sessions, 'announcement').length : null,
    speaker: sessions ? selectResults(sessions, 'speaker').length : null,
    attention: maintenance ? maintenance.transactions.length : null,
    orphans: maintenance ? maintenance.orphans.length : null
  };
}
export function recoveryPolicy(operation) {
  const readOnly = { actions: [], local: 'Состояние не распознано. Доступен только просмотр.' };
  if (!operation || !isUuid(operation.transactionId)) return readOnly;
  if (operation.kind === 'pending_delete') return operation.state === 'pending_delete' ? {
    actions: [['retry', 'Продолжить удаление']], local: 'Удаление уже начато. Отмена и восстановление удалённых байтов недоступны.'
  } : readOnly;
  if (!['ingestion', 'publication'].includes(operation.kind)) return readOnly;
  if (operation.kind === 'publication' && !Object.hasOwn(workflows, operation.workflow)) return readOnly;
  const states = operation.kind === 'ingestion' ? ['uploading', 'staged'] : ['uploading', 'cancelled', 'finalizing', 'discarding'];
  if (!states.includes(operation.state)) return readOnly;
  if (operation.state === 'discarding') return { actions: [['discard', 'Завершить удаление незавершённого сохранения']], local: 'Возобновление сохранения недоступно: удаление уже начато.' };
  if (!Number.isSafeInteger(operation.totalParts) || operation.totalParts < 1 || !Number.isSafeInteger(operation.uploadedParts) ||
      operation.uploadedParts < 0 || operation.uploadedParts > operation.totalParts || typeof operation.canFinalize !== 'boolean' ||
      operation.canFinalize !== (operation.totalParts === operation.uploadedParts)) return readOnly;
  if (operation.canFinalize) return { actions: [['resume', 'Завершить сохранение']], local: 'Все части переданы. Локальные файлы не нужны.' };
  if (operation.state === 'finalizing') return readOnly;
  return { actions: [['discard', 'Удалить незавершённое сохранение']], local: operation.kind === 'ingestion' ?
    'Нужны исходные файлы и прежний контекст загрузки. Вернитесь в уже открытую вкладку редактора. Если контекст потерян, удалите незавершённую операцию и создайте новую запись в редакторе.' :
    'Нужен точно тот же локальный результат и прежний контекст сохранения. Вернитесь в уже открытую вкладку редактора и продолжите сохранение там. Повторная сборка не заменяет потерянный результат; если он утрачен, продолжение недоступно.' };
}
export function parseEditorIntent(search) {
  const params = new URLSearchParams(search);
  if (!params.has('session') && !params.has('workflow')) return null;
  if (params.getAll('session').length !== 1 || params.getAll('workflow').length !== 1 ||
      !isUuid(params.get('session')) || !Object.hasOwn(workflows, params.get('workflow'))) throw new Error('Некорректная ссылка на обработку. Откройте запись из аудиоархива.');
  return { sessionId: params.get('session'), workflow: params.get('workflow') };
}
export function parseArchiveIntent(search) {
  const params = new URLSearchParams(search);
  if (!params.has('session')) return null;
  if (params.getAll('session').length !== 1 || [...params.keys()].some(key => key !== 'session') || !isUuid(params.get('session'))) {
    throw new Error('Некорректная ссылка на запись. Откройте запись из списка аудиоархива.');
  }
  return { sessionId: params.get('session') };
}
export function editorUrl(session, workflow) {
  if (!eligible(session) || !Object.hasOwn(workflows, workflow)) throw new Error('Для обработки нужны запись в рабочем списке и доступные исходники.');
  return `Audio-Editor.html?session=${encodeURIComponent(session.id)}&workflow=${workflow}`;
}
export function deletionImpact(preview, target) {
  const counts = { announcement: preview.announcementVersions, speaker: preview.speakerVersions };
  const all = `Исходники: ${preview.sourceTracks}; версии «Анонс-мейкер»: ${counts.announcement}; версии «Спикерская»: ${counts.speaker}; сохранённые настройки обработки: ${preview.drafts}.`;
  if (target.kind === 'purge') return { removed: `Запись целиком. ${all}`, retained: 'Только служебная отметка об удалении; запись и её данные восстановить нельзя.' };
  if (target.kind === 'sources') return { removed: `Исходные дорожки будут удалены: ${preview.sourceTracks}. Продолжение обработки проекта после удаления исходников может стать невозможным.`, retained: `Сохранённые готовые версии останутся доступны. Метаданные записи, сохранённые настройки обработки (${preview.drafts}), все сохранённые результаты: «Анонс-мейкер» ${counts.announcement}, «Спикерская» ${counts.speaker}.` };
  const label = workflows[target.workflow];
  if (!label || !['output-version', 'output-series'].includes(target.kind)) throw new Error('Неизвестная цель удаления.');
  const removed = target.kind === 'output-version' ? 1 : counts[target.workflow];
  return { removed: target.kind === 'output-version' ? `«${label}», версия ${target.version}.` : `Все результаты «${label}»: ${removed}.`,
    retained: `Исходники (${preview.sourceTracks}), сохранённые настройки обработки (${preview.drafts}), метаданные и результаты другого вида работы (${counts[target.workflow === 'speaker' ? 'announcement' : 'speaker']}); остальные версии «${label}»: ${counts[target.workflow] - removed}. Номера версий не переиспользуются.` };
}
// Independent generations fence authentication, listing, detail and playback completions.
export class RequestGeneration {
  constructor() { this.value = 0; }
  next() { return ++this.value; }
  current(value) { return value === this.value; }
}
