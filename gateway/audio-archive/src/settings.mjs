import { createCipheriv, createDecipheriv, createHash, randomBytes } from 'node:crypto';
import { ValidationError, assertExactKeys, assertInteger, assertUuid, assertTimestamp, normalizeFilename, uuidFromIdempotencyKey, validateIngestionPlan, MAX_PART_BYTES } from './validation.mjs';

export const SETTINGS_PATH = 'settings/audio-archive.encrypted.json';
export const IMPORT_PREFIX = 'zoom-imports/';
export const importPath = id => {
  if (!/^[a-f0-9]{64}$/.test(id)) throw new ValidationError('Invalid Zoom import identity');
  return `${IMPORT_PREFIX}${id}.json`;
};
const AAD = Buffer.from('meser/audio-archive/settings/v1/AES-256-GCM');
export function settingsError(message, status = 503) { return Object.assign(new Error(message), { status, name: 'SettingsError' }); }
export function parseSettingsKey(text) {
  if (typeof text !== 'string' || !/^[a-f0-9]{64}$/i.test(text.trim())) throw settingsError('Ключ настроек недоступен.');
  return Buffer.from(text.trim(), 'hex');
}
export function encryptSettings(value, key) {
  if (!Buffer.isBuffer(key) || key.length !== 32) throw settingsError('Ключ настроек недоступен.');
  const nonce = randomBytes(12), cipher = createCipheriv('aes-256-gcm', key, nonce);
  cipher.setAAD(AAD);
  const ciphertext = Buffer.concat([cipher.update(JSON.stringify(value), 'utf8'), cipher.final()]);
  return { version: 1, algorithm: 'AES-256-GCM', nonce: nonce.toString('base64'), tag: cipher.getAuthTag().toString('base64'), ciphertext: ciphertext.toString('base64') };
}
export function decryptSettings(envelope, key) {
  try {
    assertExactKeys(envelope, ['version', 'algorithm', 'nonce', 'tag', 'ciphertext'], 'encrypted settings');
    if (envelope.version !== 1 || envelope.algorithm !== 'AES-256-GCM' || !Buffer.isBuffer(key) || key.length !== 32) throw new Error();
    const decode = (value, length) => {
      if (typeof value !== 'string' || value.length > 1024 * 1024) throw new Error();
      const bytes = Buffer.from(value, 'base64');
      if (bytes.toString('base64') !== value || !bytes.length || (length && bytes.length !== length)) throw new Error();
      return bytes;
    };
    const cipher = createDecipheriv('aes-256-gcm', key, decode(envelope.nonce, 12));
    cipher.setAAD(AAD); cipher.setAuthTag(decode(envelope.tag, 16));
    return JSON.parse(Buffer.concat([cipher.update(decode(envelope.ciphertext)), cipher.final()]).toString('utf8'));
  } catch { throw settingsError('Не удалось проверить зашифрованные настройки.'); }
}
export function opaqueIdentity(accountId, meetingId, uuid) {
  return createHash('sha256').update(JSON.stringify(['zoom-cloud-v1', accountId, meetingId, uuid])).digest('hex');
}
export function connectionFingerprint(c) {
  return createHash('sha256').update(JSON.stringify([c.accountId, c.clientId, c.clientSecret, c.meetingId])).digest('hex');
}
export function validateStorage(s) {
  assertExactKeys(s, ['softLimitBytes', 'warningPercent'], 'storage settings');
  assertInteger(s.softLimitBytes, 1, Number.MAX_SAFE_INTEGER, 'softLimitBytes');
  assertInteger(s.warningPercent, 1, 100, 'warningPercent');
  return s;
}
export function validateConnection(c) {
  assertExactKeys(c, ['connectionId', 'name', 'accountId', 'clientId', 'clientSecret', 'meetingId', 'revision', 'verification'], 'Zoom connection');
  assertUuid(c.connectionId, 'connectionId'); assertInteger(c.revision, 1, Number.MAX_SAFE_INTEGER, 'connection revision');
  for (const field of ['name', 'accountId', 'clientId', 'clientSecret', 'meetingId']) {
    if (typeof c[field] !== 'string' || !c[field].trim() || c[field].length > (field === 'name' ? 100 : 512) || /[\x00-\x1f]/.test(c[field])) throw new ValidationError('Заполните поля подключения Zoom.');
  }
  if (!/^\d{9,11}$/.test(c.meetingId)) throw new ValidationError('Meeting ID должен содержать 9–11 цифр.');
  if (c.verification !== null) {
    assertExactKeys(c.verification, ['fingerprint', 'checkedAt', 'tracks'], 'connection verification');
    assertTimestamp(c.verification.checkedAt, 'checkedAt');
    if (c.verification.fingerprint !== connectionFingerprint(c) || !Number.isFinite(Date.parse(c.verification.checkedAt)) || !['confirmed', 'unconfirmed'].includes(c.verification.tracks)) throw new ValidationError('Invalid connection verification');
  }
  return c;
}
export function validateSettings(s) {
  assertExactKeys(s, ['version', 'revision', 'lastMutationId', 'activeConnectionId', 'connections', 'storage'], 'settings');
  if (s.version !== 1) throw new ValidationError('Unsupported settings version');
  assertInteger(s.revision, 0, Number.MAX_SAFE_INTEGER, 'settings revision');
  if (s.lastMutationId !== null) assertUuid(s.lastMutationId, 'lastMutationId');
  validateStorage(s.storage);
  if (!Array.isArray(s.connections) || s.connections.length > 32) throw new ValidationError('Invalid connections');
  const ids = new Set();
  for (const c of s.connections) { validateConnection(c); if (ids.has(c.connectionId)) throw new ValidationError('Duplicate connection'); ids.add(c.connectionId); }
  if (s.activeConnectionId !== null && !s.connections.some(c => c.connectionId === s.activeConnectionId && c.verification)) throw new ValidationError('Invalid active connection');
  return s;
}
export const defaultSettings = () => ({ version: 1, revision: 0, lastMutationId: null, activeConnectionId: null, connections: [], storage: { softLimitBytes: 50_000_000_000, warningPercent: 80 } });
export function settingsDto(s) {
  return { version: 1, revision: s.revision, lastMutationId: s.lastMutationId, activeConnectionId: s.activeConnectionId, storage: s.storage,
    connections: s.connections.map(c => ({ connectionId: c.connectionId, name: c.name, meetingId: c.meetingId, revision: c.revision,
      hasCredentials: true, verification: c.verification ? { checkedAt: c.verification.checkedAt, tracks: c.verification.tracks } : null })) };
}
export function validateImport(r) {
  assertExactKeys(r, ['version', 'id', 'revision', 'connectionId', 'connectionRevision', 'occurrenceUuid', 'recordedAt', 'title', 'files', 'idempotencyKey', 'transactionId', 'state', 'plan'], 'Zoom import');
  importPath(r.id); assertUuid(r.connectionId, 'connectionId'); assertUuid(r.transactionId, 'transactionId');
  if (r.version !== 1 || !['reserved', 'bound', 'completed', 'discarded'].includes(r.state) || r.idempotencyKey !== `zoom:${r.id}` || r.transactionId !== uuidFromIdempotencyKey(r.idempotencyKey)) throw new ValidationError('Invalid Zoom import state');
  assertInteger(r.revision, 1, Number.MAX_SAFE_INTEGER, 'import revision'); assertInteger(r.connectionRevision, 1, Number.MAX_SAFE_INTEGER, 'connection revision');
  assertTimestamp(r.recordedAt, 'recordedAt');
  if (typeof r.occurrenceUuid !== 'string' || !r.occurrenceUuid || r.occurrenceUuid.length > 512 || typeof r.title !== 'string' || !r.title || r.title.length > 200) throw new ValidationError('Invalid occurrence metadata');
  if (!Array.isArray(r.files) || !r.files.length || r.files.length > 32) throw new ValidationError('Invalid participant file count');
  const ids = new Set(); let size = 0;
  for (const f of r.files) {
    assertExactKeys(f, ['id', 'name', 'sizeBytes', 'startTime', 'endTime'], 'Zoom file');
    if (typeof f.id !== 'string' || !f.id || f.id.length > 512 || ids.has(f.id) || typeof f.name !== 'string' || !f.name.endsWith('.m4a') || f.name !== normalizeFilename(f.name)) throw new ValidationError('Invalid participant identity');
    for (const time of [f.startTime, f.endTime]) assertTimestamp(time, 'file timestamp', true);
    assertInteger(f.sizeBytes, 1, 500 * 1024 * 1024, 'file size'); size += f.sizeBytes; ids.add(f.id);
  }
  if (size > 500 * 1024 * 1024) throw new ValidationError('Запись превышает 500 MiB.');
  if (r.plan !== null) {
    const plan = validateIngestionPlan(r.plan, MAX_PART_BYTES);
    if (plan.tracks.length !== r.files.length || plan.tracks.some((t, i) => t.originalName !== r.files[i].name || t.sizeBytes !== r.files[i].sizeBytes || t.mediaType !== 'audio/mp4')) throw new ValidationError('Invalid frozen Zoom plan');
  }
  if ((r.state === 'reserved' && r.plan !== null) || (['bound', 'completed'].includes(r.state) && r.plan === null)) throw new ValidationError('Zoom plan state mismatch');
  return r;
}
