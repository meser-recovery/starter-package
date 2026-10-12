import { createHmac, randomUUID, timingSafeEqual } from 'node:crypto';
import { isDeepStrictEqual } from 'node:util';
import { ValidationError, assertExactKeys, assertInteger, assertUuid, uuidFromIdempotencyKey, validateIngestionPlan, validateSourceSession, validateTransaction, validateTombstone } from './validation.mjs';
import { SETTINGS_PATH, IMPORT_PREFIX, importPath, encryptSettings, decryptSettings, defaultSettings, settingsDto,
  validateSettings, validateConnection, validateStorage, validateImport, connectionFingerprint, opaqueIdentity, settingsError } from './settings.mjs';
import { ZoomClient, monthRange, participantFiles } from './zoom.mjs';

export class ZoomArchive {
  constructor(domain, { key = null, zoom = new ZoomClient(), clock = () => Date.now() } = {}) {
    this.domain = domain; this.repository = domain.repository; this.key = key; this.zoom = zoom; this.clock = clock;
    this.calendarCache = new Map(); this.usageCache = null;
  }
  async settingsSnapshot() {
    if (!this.key) throw settingsError('Настройки Zoom недоступны: серверный ключ не настроен.');
    const head = await this.repository.getHead(), stored = await this.repository.readJson(SETTINGS_PATH, head);
    return { head, settings: stored ? validateSettings(decryptSettings(stored.data, this.key)) : defaultSettings() };
  }
  async settings() { return settingsDto((await this.settingsSnapshot()).settings); }
  draft(body, settings) {
    assertExactKeys(body, ['connectionId', 'name', 'accountId', 'clientId', 'clientSecret', 'meetingId'], 'connection form');
    const old = settings.connections.find(c => c.connectionId === body.connectionId);
    return validateConnection({ connectionId: assertUuid(body.connectionId, 'connectionId'), name: typeof body.name === 'string' ? body.name.trim() : body.name,
      accountId: body.accountId || old?.accountId, clientId: body.clientId || old?.clientId, clientSecret: body.clientSecret || old?.clientSecret,
      meetingId: body.meetingId, revision: old ? old.revision : 1, verification: null });
  }
  sign(value) { return createHmac('sha256', this.key).update(value).digest('base64url'); }
  async check(body) {
    assertExactKeys(body, ['revision', 'connection'], 'check connection');
    const { settings } = await this.settingsSnapshot();
    if (body.revision !== settings.revision) throw settingsError('Настройки изменились. Перечитайте их.', 409);
    const c = this.draft(body.connection, settings), result = await this.zoom.check(c);
    const value = Buffer.from(JSON.stringify({ connectionId: c.connectionId, fingerprint: connectionFingerprint(c), revision: settings.revision, ...result, expires: this.clock() + 10 * 60_000 })).toString('base64url');
    return { ...result, receipt: `${value}.${this.sign(value)}` };
  }
  receipt(value, c, revision) {
    try {
      const [payload, signature, extra] = String(value).split('.'), expected = this.sign(payload);
      if (extra || !signature || signature.length !== expected.length || !timingSafeEqual(Buffer.from(signature), Buffer.from(expected))) throw new Error();
      const r = JSON.parse(Buffer.from(payload, 'base64url'));
      if (r.connectionId !== c.connectionId || r.fingerprint !== connectionFingerprint(c) || r.revision !== revision || r.expires < this.clock()) throw new Error();
      return { fingerprint: r.fingerprint, checkedAt: r.checkedAt, tracks: r.tracks };
    } catch { throw settingsError('Проверка устарела. Проверьте точные настройки снова.', 409); }
  }
  async pendingConnection(id, head) {
    const records = await this.repository.listJson(IMPORT_PREFIX, head);
    for (const entry of records) {
      const r = validateImport(entry.data);
      if (r.connectionId !== id || ['completed', 'discarded'].includes(r.state)) continue;
      const transaction = await this.repository.readJson(`transactions/ingest-${r.transactionId}.json`, head);
      if (!transaction || !['finalized', 'discarded'].includes(transaction.data.state)) return true;
    }
    return false;
  }
  async mutate(body) {
    assertExactKeys(body, ['revision', 'mutationId', 'action', 'connection', 'connectionId', 'receipt', 'storage', 'confirmed'], 'settings mutation');
    assertInteger(body.revision, 0, Number.MAX_SAFE_INTEGER, 'settings revision'); assertUuid(body.mutationId, 'mutationId');
    for (let attempt = 0; attempt < 3; attempt++) {
      const { head, settings } = await this.settingsSnapshot();
      if (settings.lastMutationId === body.mutationId) return settingsDto(settings);
      if (body.revision !== settings.revision) throw settingsError('Настройки изменились. Перечитайте их; форма не сохранена.', 409);
      const next = structuredClone(settings), old = settings.connections.find(c => c.connectionId === body.connectionId);
      if (body.action === 'save') {
        const c = this.draft(body.connection, settings), previous = settings.connections.find(p => p.connectionId === c.connectionId);
        const changed = previous && connectionFingerprint(c) !== connectionFingerprint(previous);
        if (changed && await this.pendingConnection(c.connectionId, head)) throw settingsError('Сначала завершите или отмените незавершённый импорт этого подключения.', 409);
        c.revision = previous ? previous.revision + (changed ? 1 : 0) : 1;
        c.verification = body.receipt ? this.receipt(body.receipt, c, settings.revision) : !changed ? previous?.verification || null : null;
        if (!c.verification && next.activeConnectionId === c.connectionId) next.activeConnectionId = null;
        next.connections = next.connections.filter(p => p.connectionId !== c.connectionId).concat(c);
      } else if (['activate', 'disable', 'delete'].includes(body.action)) {
        if (!old || body.confirmed !== true) throw new ValidationError('Подтвердите изменение подключения.');
        if (body.action === 'activate') {
          if (!old.verification || old.verification.fingerprint !== connectionFingerprint(old)) throw settingsError('Сначала проверьте и сохраните подключение.', 409);
          next.activeConnectionId = old.connectionId;
        } else {
          if (await this.pendingConnection(old.connectionId, head)) throw settingsError('Сначала завершите или отмените незавершённый импорт этого подключения.', 409);
          if (next.activeConnectionId === old.connectionId) next.activeConnectionId = null;
          if (body.action === 'delete') next.connections = next.connections.filter(c => c.connectionId !== old.connectionId);
        }
      } else if (body.action === 'storage') next.storage = validateStorage(body.storage);
      else throw new ValidationError('Unknown settings action');
      next.revision++; next.lastMutationId = body.mutationId; validateSettings(next);
      try { await this.repository.commitJson(head, { [SETTINGS_PATH]: encryptSettings(next, this.key) }, 'Update encrypted Audio Archive settings'); }
      catch (error) {
        // Includes lost response after a successful write; always resolve authoritative state first.
        const readback = await this.settingsSnapshot();
        if (readback.settings.lastMutationId === body.mutationId) { this.calendarCache.clear(); return settingsDto(readback.settings); }
        if (error.status === 409 && readback.settings.revision === settings.revision) continue;
        throw error;
      }
      this.calendarCache.clear();
      const readback = await this.settingsSnapshot();
      if (readback.settings.lastMutationId !== body.mutationId || readback.settings.revision !== next.revision) throw settingsError('Результат сохранения изменился. Перечитайте настройки.', 409);
      return settingsDto(readback.settings);
    }
    throw settingsError('Архив изменился. Перечитайте настройки.', 409);
  }
  async record(id, head = null) {
    const stored = await this.repository.readJson(importPath(id), head || await this.repository.getHead());
    if (!stored) throw settingsError('Импорт не найден.', 404);
    const record = validateImport(stored.data);
    if (record.id !== id) throw settingsError('Идентификатор импорта не совпал.', 409);
    return record;
  }
  async operation(id) {
    const head = await this.repository.getHead(), r = await this.record(id, head);
    const source = await this.repository.readJson(`sessions/${r.transactionId}.json`, head);
    const t = await this.repository.readJson(`transactions/ingest-${r.transactionId}.json`, head);
    if (t) {
      t.data = validateTransaction(t.data);
      if (t.data.origin !== 'zoom_cloud' || t.data.zoomImportId !== id || !isDeepStrictEqual(t.data.plan, r.plan)) throw settingsError('Связь плана импорта не подтверждена.', 409);
    }
    if (source) {
      const value = source.data.kind === 'deletion_tombstone' ? validateTombstone(source.data) : validateSourceSession(source.data);
      if (value.id !== r.transactionId || (value.kind !== 'deletion_tombstone' && (value.origin.kind !== 'zoom_cloud' || value.origin.externalId !== id))) throw settingsError('Связь исходной записи не подтверждена.', 409);
    }
    let state = r.state;
    if (source) state = source.data.kind === 'deletion_tombstone' || source.data.sourceState !== 'available' ? 'deleted' : 'completed';
    else if (r.state === 'completed' || t?.data.state === 'finalized') state = 'deleted';
    else if (['discarded', 'discarding'].includes(t?.data.state)) state = t.data.state;
    const accepted = t?.data.uploadedParts || [];
    return { version: 1, id: r.id, revision: r.revision, connectionId: r.connectionId, connectionRevision: r.connectionRevision,
      recordedAt: r.recordedAt, title: r.title, files: r.files, idempotencyKey: r.idempotencyKey, transactionId: r.transactionId, state,
      plan: r.plan, uploadedParts: accepted.map(p => ({ blobId: p.blobId, partNumber: p.partNumber })),
      canFinalize: Boolean(state !== 'deleted' && t && ['uploading', 'staged'].includes(t.data.state) && accepted.length === t.data.plan.tracks.reduce((s, f) => s + f.parts.length, 0)) };
  }
  async calendar(month, refresh = false) {
    const range = monthRange(month), { settings } = await this.settingsSnapshot(), c = settings.connections.find(c => c.connectionId === settings.activeConnectionId);
    const durable = (await this.repository.listJson(IMPORT_PREFIX, await this.repository.getHead())).map(entry => validateImport(entry.data))
      .filter(r => Date.parse(r.recordedAt) >= range.start && Date.parse(r.recordedAt) < range.end);
    const key = `${c?.connectionId}:${c?.revision}:${month}`;
    let cached = this.calendarCache.get(key);
    let warning = null;
    if (c && (!cached || refresh || cached.expires < this.clock())) {
      const recordings = [];
      try {
      const records = await this.zoom.list(c, range);
      for (const row of records) {
        const recording = await this.zoom.recording(c, row.uuid);
        if (recording.uuid !== row.uuid || String(recording.id) !== c.meetingId) throw settingsError('Zoom: occurrence не совпал.', 502);
        const id = opaqueIdentity(c.accountId, c.meetingId, row.uuid);
        let files = [], state = 'available', reason = null;
        try { files = participantFiles(recording); } catch (error) { state = 'unavailable'; reason = error.message; }
        recordings.push({ id, occurrenceUuid: row.uuid, startTime: recording.start_time, files, state, reason });
      }
      } catch (error) {
        if (!durable.length) throw error;
        warning = 'Zoom сейчас недоступен. Показаны только сохранённые операции; список новых записей неполный.';
      }
      cached = { expires: this.clock() + 30_000, recordings };
      if (this.calendarCache.size >= 64) this.calendarCache.delete(this.calendarCache.keys().next().value);
      if (!warning) this.calendarCache.set(key, cached);
    }
    const rows = new Map((cached?.recordings || []).map(row => [row.id, row]));
    for (const r of durable) rows.set(r.id, { id: r.id, startTime: r.recordedAt, files: r.files, state: r.state, reason: null });
    const recordings = [];
    for (const row of rows.values()) {
      const { occurrenceUuid, ...safe } = row;
      let operation = null; try { operation = await this.operation(row.id); } catch (e) { if (e.status !== 404) throw e; }
      recordings.push({ ...safe, state: operation?.state || row.state, trackCount: row.files.length, sizeBytes: row.files.reduce((n, f) => n + f.sizeBytes, 0), sessionId: operation?.transactionId || null });
    }
    if ((await this.settingsSnapshot()).settings.revision !== settings.revision) throw settingsError('Подключение изменилось. Обновите календарь.', 409);
    return { month, settingsRevision: settings.revision, state: c ? 'ready' : 'unconfigured', warning, recordings };
  }
  async reserve(body) {
    assertExactKeys(body, ['id', 'month', 'settingsRevision'], 'reserve Zoom import'); importPath(body.id);
    // An existing durable identity wins even after active profile changes / upstream expiry.
    try { return await this.operation(body.id); } catch (e) { if (e.status !== 404) throw e; }
    await this.calendar(body.month);
    const { head, settings } = await this.settingsSnapshot();
    if (settings.revision !== body.settingsRevision) throw settingsError('Подключение изменилось. Обновите календарь.', 409);
    const c = settings.connections.find(c => c.connectionId === settings.activeConnectionId);
    const candidate = this.calendarCache.get(`${c?.connectionId}:${c?.revision}:${body.month}`)?.recordings.find(r => r.id === body.id);
    if (!c || !candidate || candidate.state !== 'available') throw settingsError('Запись недоступна. Обновите календарь.', 409);
    const fresh = await this.zoom.recording(c, candidate.occurrenceUuid), files = participantFiles(fresh);
    if (fresh.uuid !== candidate.occurrenceUuid || String(fresh.id) !== c.meetingId || !isDeepStrictEqual(files, candidate.files)) throw settingsError('Состав записи изменился. Обновите календарь.', 409);
    const record = validateImport({ version: 1, id: candidate.id, revision: 1, connectionId: c.connectionId, connectionRevision: c.revision,
      occurrenceUuid: candidate.occurrenceUuid, recordedAt: fresh.start_time,
      title: `Zoom · ${new Date(fresh.start_time).toLocaleString('ru-RU', { timeZone: 'Europe/Moscow', dateStyle: 'short', timeStyle: 'short' })} МСК`,
      files, idempotencyKey: `zoom:${candidate.id}`, transactionId: uuidFromIdempotencyKey(`zoom:${candidate.id}`), state: 'reserved', plan: null });
    try { await this.repository.commitJson(head, { [importPath(record.id)]: record }, 'Reserve Zoom occurrence'); }
    catch (e) { try { return await this.operation(record.id); } catch { throw e; } }
    return this.operation(record.id);
  }
  async bind(id, body) {
    assertExactKeys(body, ['plan'], 'Zoom plan');
    const plan = validateIngestionPlan(body.plan, this.domain.acceptedPartBytes);
    for (let attempt = 0; attempt < 3; attempt++) {
      const head = await this.repository.getHead(), r = await this.record(id, head);
      if (r.plan && !isDeepStrictEqual(r.plan, plan)) throw settingsError('Дорожки отличаются от неизменяемого плана импорта.', 409);
      if (['completed', 'discarded'].includes(r.state)) throw settingsError('Импорт уже завершён или отменён.', 409);
      if (plan.tracks.length !== r.files.length || plan.tracks.some((t, i) => t.originalName !== r.files[i].name || t.sizeBytes !== r.files[i].sizeBytes || t.mediaType !== 'audio/mp4')) throw new ValidationError('План не совпадает с полным составом Zoom.');
      if (!r.plan) {
        try { await this.repository.commitJson(head, { [importPath(id)]: { ...r, revision: r.revision + 1, plan, state: 'bound' } }, 'Bind exact Zoom ingestion plan'); }
        catch (e) { if (e.status === 409) continue; const readback = await this.record(id); if (!isDeepStrictEqual(readback.plan, plan)) throw e; }
      }
      return this.domain.beginIngestion({ schemaVersion: 1, idempotencyKey: r.idempotencyKey, title: r.title, recordedAt: r.recordedAt, origin: 'zoom_cloud', supersedesSessionId: null, plan }, id);
    }
    throw settingsError('Импорт изменился. Проверьте его состояние.', 409);
  }
  async download(id, fileId, signal) {
    const r = await this.record(id), op = await this.operation(id);
    if (!['reserved', 'bound'].includes(op.state) || !r.files.some(f => f.id === fileId)) throw settingsError('Импорт не принимает дорожки.', 409);
    const { settings } = await this.settingsSnapshot(), c = settings.connections.find(c => c.connectionId === r.connectionId && c.revision === r.connectionRevision);
    if (!c) throw settingsError('Исходное подключение больше недоступно.', 409);
    const fresh = await this.zoom.recording(c, r.occurrenceUuid), files = participantFiles(fresh);
    if (fresh.uuid !== r.occurrenceUuid || opaqueIdentity(c.accountId, c.meetingId, fresh.uuid) !== r.id || files.length !== r.files.length || r.files.some(f => !files.some(x => isDeepStrictEqual(f, x)))) throw settingsError('Состав дорожек изменился. Продолжение заблокировано.', 409);
    return this.zoom.download(c, fresh, fileId, signal);
  }
  async discard(id) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const head = await this.repository.getHead(), r = await this.record(id, head), op = await this.operation(id);
      if (['completed', 'deleted'].includes(op.state)) throw settingsError('Завершённую запись нельзя отменить.', 409);
      if (op.state === 'discarded') return op;
      const t = await this.repository.readJson(`transactions/ingest-${r.transactionId}.json`, head);
      if (t) await this.domain.recoverIncomplete(r.transactionId, 'discard');
      else {
        try { await this.repository.commitJson(head, { [importPath(id)]: { ...r, state: 'discarded', revision: r.revision + 1 } }, 'Discard reserved Zoom occurrence'); }
        catch (e) { if (e.status === 409) continue; throw e; }
      }
      return this.operation(id);
    }
    throw settingsError('Импорт изменился. Перечитайте состояние.', 409);
  }
  async usage(refresh = false) {
    const { settings } = await this.settingsSnapshot(), head = await this.repository.getHead();
    const mutationVersion = this.repository.storageMutationVersion || 0;
    let stale = false;
    if (refresh || !this.usageCache || this.usageCache.head !== head || this.usageCache.mutationVersion !== mutationVersion || this.repository.activeStorageMutations || this.usageCache.expires < this.clock()) {
      try {
        if (this.repository.activeStorageMutations) throw new Error();
        const scan = async () => {
          const assets = new Map();
          for (const release of await this.repository.listReleases()) for (const asset of await this.repository.listReleaseAssets(release.id)) {
            if (!Number.isSafeInteger(asset.id) || asset.id < 1 || !Number.isSafeInteger(asset.size) || asset.size < 0) throw new Error();
            if (assets.has(asset.id) && assets.get(asset.id) !== asset.size) throw new Error(); assets.set(asset.id, asset.size);
          }
          return assets;
        };
        // GitHub listings have no atomic snapshot. Two stable complete traversals plus
        // canonical/mutation checks refuse a moving total, including orphan assets.
        const assets = await scan();
        if (!isDeepStrictEqual(assets, await scan())) throw new Error();
        const usedBytes = [...assets.values()].reduce((a, b) => a + b, 0);
        if (!Number.isSafeInteger(usedBytes) || head !== await this.repository.getHead() || this.repository.activeStorageMutations || mutationVersion !== (this.repository.storageMutationVersion || 0)) throw new Error();
        this.usageCache = { usedBytes, assetCount: assets.size, countedAt: new Date(this.clock()).toISOString(), head, mutationVersion, expires: this.clock() + 30_000 };
      } catch { stale = true; }
    }
    const c = this.usageCache;
    return { usedBytes: c?.usedBytes ?? null, assetCount: c?.assetCount ?? null, countedAt: c?.countedAt ?? null, stale,
      ...settings.storage, warning: c ? c.usedBytes >= settings.storage.softLimitBytes * settings.storage.warningPercent / 100 : null };
  }
}
