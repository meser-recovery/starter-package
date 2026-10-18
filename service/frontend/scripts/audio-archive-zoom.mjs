const $ = id => document.getElementById(id);
export const moscowMonth = (date = new Date()) => new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Moscow', year: 'numeric', month: '2-digit' }).format(date);
export const moscowDay = date => new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Moscow', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(date));
const timeLabel = date => new Intl.DateTimeFormat('ru-RU', { timeZone: 'Europe/Moscow', hour: '2-digit', minute: '2-digit' }).format(new Date(date));
const sizeLabel = size => size < 1_000_000_000 ? `${(size / 1_000_000).toLocaleString('ru-RU', { maximumFractionDigits: 3 })} MB` : `${(size / 1_000_000_000).toLocaleString('ru-RU', { maximumFractionDigits: 3 })} GB`;
function node(tag, text) { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; return n; }
function action(label, callback) { const b = node('button', label); b.type = 'button'; b.addEventListener('click', callback); return b; }
const labels = { available: 'Доступно', reserved: 'Импорт не завершён', bound: 'Импорт не завершён', completed: 'В Аудиоархиве', deleted: 'Исходники удалены', discarded: 'Импорт отменён', discarding: 'Отмена не завершена', unavailable: 'Файлы недоступны' };

export function mountZoomArchive(gateway, openSession) {
  let settings = null, receipt = null, calendar = null, generation = 0, usageGeneration = 0, month = moscowMonth(), selectedDay = null, controller = null, busy = false;
  let usageRefreshPending = null;
  const dialog = $('archive-settings-dialog'), zoomDialog = $('archive-zoom-dialog');
  const status = text => { $('archive-settings-status').textContent = text; };
  const zoomStatus = text => { $('archive-zoom-status').textContent = text; };
  const available = async () => {
    await gateway.configuration();
    if (gateway.zoomCloudVersion !== 1) throw new Error('Версия шлюза не поддерживает настройки и импорт Zoom.');
  };
  const run = async fn => { try { await fn(); } catch (error) { status(error.message); } };
  const runZoom = async fn => { try { await fn(); } catch (error) { zoomStatus(error.name === 'AbortError' ? 'Передача остановлена. Операция сохранена; продолжите её из календаря.' : error.message); } };
  const resetForm = c => {
    $('zoom-connection-form').reset(); receipt = null;
    $('zoom-connection-id').value = c?.connectionId || crypto.randomUUID();
    $('zoom-name').value = c?.name || ''; $('zoom-meeting-id').value = c?.meetingId || '';
    $('zoom-credential-note').textContent = c ? 'Сохранённые credentials скрыты. Пустые поля сохраняют прежние значения.' : 'Введите credentials приложения Zoom в защищённой форме.';
  };
  const form = () => ({ connectionId: $('zoom-connection-id').value, name: $('zoom-name').value, accountId: $('zoom-account-id').value.trim(),
    clientId: $('zoom-client-id').value.trim(), clientSecret: $('zoom-client-secret').value, meetingId: $('zoom-meeting-id').value.trim() });
  async function mutate(actionName, extra = {}) {
    if (busy || !settings) return;
    busy = true;
    const body = { revision: settings.revision, mutationId: crypto.randomUUID(), action: actionName, connection: null, connectionId: null, receipt: null, storage: null, confirmed: false, ...extra };
    try {
      try { settings = await gateway.request('/v1/archive-settings', { method: 'POST', body }); }
      catch (error) {
        const latest = await gateway.request('/v1/archive-settings');
        if (latest.lastMutationId !== body.mutationId) throw error;
        settings = latest;
      }
      renderSettings(); resetForm(); status('Сохранение подтверждено архивом.'); await updateWarning();
    } finally { busy = false; }
  }
  function renderSettings() {
    const list = $('zoom-connections'); list.replaceChildren();
    for (const c of settings.connections) {
      const card = node('article'); card.className = 'archive-card';
      card.append(node('h4', c.name), node('p', `${c.connectionId === settings.activeConnectionId ? 'Активно · ' : ''}${c.verification ? c.verification.tracks === 'confirmed' ? 'Проверено' : 'Проверено; тестовые дорожки не подтверждены' : 'Не проверено'}`));
      card.append(action('Изменить', () => { resetForm(c); $('zoom-name').focus(); }), action('Активировать', () => run(async () => {
        if (confirm(`Активировать «${c.name}» для новых запросов календаря?`)) { generation++; calendar = null; await mutate('activate', { connectionId: c.connectionId, confirmed: true }); }
      })), action('Отключить', () => run(async () => { if (confirm(`Отключить «${c.name}»?`)) await mutate('disable', { connectionId: c.connectionId, confirmed: true }); })),
      action('Удалить подключение', () => run(async () => { if (confirm(`Удалить подключение «${c.name}»? Записи останутся в Архиве.`)) await mutate('delete', { connectionId: c.connectionId, confirmed: true }); })));
      list.append(card);
    }
    $('archive-soft-limit').value = settings.storage.softLimitBytes / 1_000_000_000;
    $('archive-warning-percent').value = settings.storage.warningPercent;
  }
  async function loadSettings() {
    await available(); settings = await gateway.request('/v1/archive-settings'); renderSettings(); resetForm(); status('Настройки загружены.'); await updateWarning();
  }
  async function updateWarning(refresh = false) {
    if (!refresh && usageRefreshPending) { await usageRefreshPending; return updateWarning(false); }
    const pending = renderWarning(refresh);
    if (!refresh) return pending;
    usageRefreshPending = pending;
    try { return await pending; }
    finally { if (usageRefreshPending === pending) usageRefreshPending = null; }
  }
  async function renderWarning(refresh) {
    const sequence = ++usageGeneration;
    try {
      await available(); const result = await gateway.request(`/v1/storage-usage${refresh ? '?refresh=1' : ''}`);
      if (sequence !== usageGeneration) return;
      // Both views describe the same authoritative response, including stale/unknown.
      $('archive-storage-usage').textContent = result.usedBytes === null ? 'Объём пока неизвестен.' : `${sizeLabel(result.usedBytes)} · ${result.assetCount} физических частей · ${result.stale ? 'последний полный подсчёт' : 'подсчитано'} ${new Date(result.countedAt).toLocaleString('ru-RU', { timeZone: 'Europe/Moscow' })} МСК`;
      $('archive-storage-warning').hidden = result.warning !== true;
      $('archive-storage-warning-text').textContent = result.usedBytes === null ? '' : `${result.stale ? 'Последний полный подсчёт: ' : ''}занято ${sizeLabel(result.usedBytes)}. Рекомендуемый предел — ${sizeLabel(result.softLimitBytes)}. Импорт и сохранение доступны.`;
    } catch {
      if (sequence !== usageGeneration) return;
      $('archive-storage-usage').textContent = 'Объём пока неизвестен. Повторите подсчёт.';
      // A network error does not erase the last confirmed soft-limit warning.
      if (!$('archive-storage-warning').hidden) $('archive-storage-warning-text').textContent = 'Последний подтверждённый подсчёт: ' + $('archive-storage-warning-text').textContent.replace(/^Последний подтверждённый подсчёт: /, '');
    }
  }
  function renderCalendar() {
    const grid = $('zoom-days'); grid.replaceChildren(); $('zoom-occurrences').replaceChildren();
    $('zoom-month').value = month;
    if (!calendar) return;
    if (calendar.state === 'unconfigured' && !calendar.recordings.length) { zoomStatus('Активное подключение не настроено. Откройте настройки Аудиоархива.'); return; }
    const days = new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5)), 0)).getUTCDate();
    const offset = (new Date(`${month}-01T12:00:00Z`).getUTCDay() + 6) % 7;
    for (const day of ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']) grid.append(node('span', day));
    for (let i = 0; i < offset; i++) grid.append(node('span'));
    for (let d = 1; d <= days; d++) {
      const key = `${month}-${String(d).padStart(2, '0')}`, records = calendar.recordings.filter(r => moscowDay(r.startTime) === key);
      const b = action(String(d), () => { selectedDay = key; renderCalendar(); $('zoom-day-title').focus(); });
      b.classList.toggle('has-recordings', Boolean(records.length)); b.setAttribute('aria-label', `${d}: ${records.length} записей`); b.setAttribute('aria-pressed', String(selectedDay === key)); grid.append(b);
    }
    $('zoom-day-title').textContent = selectedDay ? `Записи ${selectedDay} · МСК` : 'Выберите день';
    for (const r of calendar.recordings.filter(r => moscowDay(r.startTime) === selectedDay)) {
      const row = node('article'); row.className = 'archive-card';
      row.append(node('h4', `${timeLabel(r.startTime)} МСК · ${labels[r.state] || r.state}`), node('p', `${r.trackCount} отдельных дорожек · приблизительно ${sizeLabel(r.sizeBytes)}`));
      if (r.reason) row.append(node('p', r.reason));
      if (r.files.length) {
        const details = node('details'); details.append(node('summary', 'Состав и время дорожек'));
        for (const f of r.files) details.append(node('p', `${f.name} · ${f.sizeBytes} bytes · ${f.startTime ? timeLabel(f.startTime) : 'начало неизвестно'} — ${f.endTime ? timeLabel(f.endTime) : 'конец неизвестен'} МСК`)); row.append(details);
      }
      if (r.state === 'completed') row.append(action('Открыть в Аудиоархиве', () => { zoomDialog.close(); openSession(r.sessionId); }));
      if (['available', 'reserved', 'bound'].includes(r.state)) row.append(action(r.state === 'available' ? 'Импортировать запись' : 'Проверить и продолжить', () => runZoom(() => importRecording(r))));
      if (['reserved', 'bound', 'discarding'].includes(r.state)) row.append(action('Отказаться от импорта', () => runZoom(async () => {
        if (controller) return;
        if (confirm('Отказаться от этого незавершённого импорта?')) {
          try { await gateway.request(`/v1/zoom/imports/${r.id}/discard`, { method: 'POST', body: { confirmed: true } }); }
          finally { await updateWarning(true); }
          await loadCalendar(true);
        }
      })));
      $('zoom-occurrences').append(row);
    }
    zoomStatus(calendar.warning || (calendar.state === 'unconfigured' ? 'Активное подключение не настроено. Показаны сохранённые операции.' : calendar.recordings.length ? 'Показано фактическое время Zoom по Москве.' : 'В этом месяце записей нет.'));
  }
  async function loadCalendar(refresh = false) {
    const sequence = ++generation, requestedMonth = month; zoomStatus('Загрузка календаря…');
    let value;
    try {
      await available();
      value = await gateway.request(`/v1/zoom/calendar?month=${encodeURIComponent(requestedMonth)}${refresh ? '&refresh=1' : ''}`);
    } catch (error) { if (sequence !== generation || month !== requestedMonth) return; throw error; }
    if (sequence !== generation || month !== requestedMonth) return;
    calendar = value;
    if (!selectedDay?.startsWith(month)) selectedDay = calendar.recordings[0] ? moscowDay(calendar.recordings[0].startTime) : null;
    renderCalendar();
  }
  async function importRecording(row) {
    if (controller) return;
    if (!confirm(`Импортировать все ${row.trackCount} отдельных M4A-дорожек записи ${timeLabel(row.startTime)} МСК?`)) return;
    const abort = new AbortController(); controller = abort; $('zoom-stop').hidden = false;
    try {
      await available();
      let op = await gateway.request('/v1/zoom/imports', { method: 'POST', signal: abort.signal, body: { id: row.id, month, settingsRevision: calendar.settingsRevision } });
      if (op.state === 'completed') { zoomDialog.close(); openSession(op.transactionId); return; }
      if (['discarded', 'discarding', 'deleted'].includes(op.state)) throw new Error('Импорт отменён или исходники удалены. Новая запись автоматически не создаётся.');
      let result;
      if (op.canFinalize) {
        zoomStatus('Все части в Архиве. Подтверждаем завершение…');
        result = await gateway.request(`/v1/zoom/imports/${row.id}/finalize`, { method: 'POST', signal: abort.signal, body: { confirmed: true } });
      } else {
        const files = [];
        for (const [index, f] of op.files.entries()) {
          zoomStatus(`Получение дорожки ${index + 1} из ${op.files.length}…`);
          const response = await gateway.fetchImpl(`${gateway.baseUrl}/v1/zoom/imports/${row.id}/files/${encodeURIComponent(f.id)}`, { credentials: 'include', signal: abort.signal });
          if (!response.ok) { const payload = await response.json().catch(() => null); throw new Error(payload?.error || 'Не удалось получить дорожку Zoom.'); }
          const blob = await response.blob();
          const header = new Uint8Array(await blob.slice(0, 12).arrayBuffer());
          if (blob.size !== f.sizeBytes || String.fromCharCode(...header.slice(4, 8)) !== 'ftyp') throw new Error('Размер или формат M4A не подтверждён. Импорт остановлен.');
          files.push(new File([blob], f.name, { type: 'audio/mp4' }));
        }
        zoomStatus('Подготовка и проверка неизменяемого плана…');
        result = await gateway.ingestFiles({ files, title: op.title, recordedAt: op.recordedAt, origin: 'zoom_cloud', idempotencyKey: op.idempotencyKey, zoomImportId: op.id,
          signal: abort.signal, onStarted: () => zoomStatus('Передача частей в Архив…'),
          onProgress: p => zoomStatus(`Передано частей ${p.uploadedParts} из ${p.totalParts}.`), onFinalizing: () => zoomStatus('Проверка и каноническое подтверждение…') });
      }
      op = await gateway.request(`/v1/zoom/imports/${row.id}`, { signal: abort.signal });
      if (op.state !== 'completed' || result.session?.origin.externalId !== row.id) throw new Error('Сохранение не подтверждено. Проверьте состояние операции.');
      zoomStatus('Запись сохранена в Аудиоархиве.'); await loadCalendar(true);
    } finally { controller = null; $('zoom-stop').hidden = true; await updateWarning(true); }
  }
  $('archive-settings-open').addEventListener('click', () => { dialog.showModal(); void run(loadSettings); });
  $('archive-warning-settings').addEventListener('click', () => { dialog.showModal(); void run(loadSettings); });
  $('archive-settings-close').addEventListener('click', () => { dialog.close(); });
  dialog.addEventListener('close', () => { $('zoom-connection-form').reset(); receipt = null; $('archive-settings-open').focus(); });
  $('archive-settings-reload').addEventListener('click', () => void run(loadSettings));
  $('zoom-add').addEventListener('click', () => { resetForm(); $('zoom-name').focus(); });
  $('zoom-connection-form').addEventListener('input', () => { receipt = null; });
  $('zoom-check').addEventListener('click', () => void run(async () => {
    if (!settings || busy) return; busy = true; status('Проверка подключения…');
    try { const result = await gateway.request('/v1/archive-settings/check', { method: 'POST', body: { revision: settings.revision, connection: form() } }); receipt = result.receipt; status(result.tracks === 'confirmed' ? 'Проверено. Сохраните подключение явно.' : 'Основные проверки пройдены. Тестовых дорожек нет; активация разрешена после сохранения.'); }
    finally { busy = false; }
  }));
  $('zoom-connection-form').addEventListener('submit', e => { e.preventDefault(); void run(() => mutate('save', { connection: form(), receipt })); });
  $('archive-storage-form').addEventListener('submit', e => { e.preventDefault(); void run(() => mutate('storage', { storage: { softLimitBytes: Math.round(Number($('archive-soft-limit').value) * 1_000_000_000), warningPercent: Number($('archive-warning-percent').value) } })); });
  $('archive-usage-refresh').addEventListener('click', () => void updateWarning(true));
  $('archive-zoom-open').addEventListener('click', () => { zoomDialog.showModal(); void runZoom(() => loadCalendar()); });
  $('archive-zoom-close').addEventListener('click', () => zoomDialog.close());
  zoomDialog.addEventListener('close', () => { generation++; controller?.abort(); $('archive-zoom-open').focus(); });
  $('zoom-stop').addEventListener('click', () => controller?.abort());
  $('zoom-month').addEventListener('change', () => { month = $('zoom-month').value; void runZoom(() => loadCalendar()); });
  for (const [id, delta] of [['zoom-month-prev', -1], ['zoom-month-next', 1]]) $(id).addEventListener('click', () => {
    const date = new Date(`${month}-15T12:00:00Z`); date.setUTCMonth(date.getUTCMonth() + delta); month = date.toISOString().slice(0, 7); void runZoom(() => loadCalendar());
  });
  $('zoom-refresh').addEventListener('click', () => void runZoom(() => loadCalendar(true)));
  window.addEventListener('pagehide', () => controller?.abort());
  return { updateWarning };
}
