// Disposable rehearsal materials only. Never reads a production path or credential.
import { readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { randomBytes } from 'node:crypto';
import assert from 'node:assert/strict';
import { SETTINGS_PATH, defaultSettings, encryptSettings, decryptSettings, parseSettingsKey, validateSettings, connectionFingerprint } from '../../gateway/audio-archive/src/settings.mjs';
import { ZoomArchive } from '../../gateway/audio-archive/src/zoom-archive.mjs';
import { AudioArchiveDomain } from '../../gateway/audio-archive/src/domain.mjs';
import { MemoryRepository } from '../../gateway/audio-archive/test/helpers.mjs';
import { CONNECTION } from '../../gateway/audio-archive/test/s12-fixtures.mjs';
const [mode, directory, keyFile] = process.argv.slice(2);
const work = resolve(directory || '/');
assert.equal(process.env.MESER_S12_RECOVERY_SYNTHETIC_TEST, 'true');
assert.match(work, /^\/(?:private\/)?tmp\/meser-(?:recovery-rehearsal|docker-recovery)\.[^/]+$/);
assert.ok(resolve(keyFile).startsWith(`${work}/`) || /\/(?:private\/)?tmp\/meser-synthetic-restore\.[^/]+\/config\/archive-settings-key$/.test(resolve(keyFile)));
const json = async name => JSON.parse(await readFile(`${work}/${name}`, 'utf8'));
const put = (name, value) => writeFile(`${work}/${name}`, `${JSON.stringify(value)}\n`, { mode: 0o600 });
if (mode === 'create') {
  const key = randomBytes(32), settings = defaultSettings();
  const connection = { ...CONNECTION, revision: 1, verification: { fingerprint: connectionFingerprint(CONNECTION), checkedAt: '2026-10-12T00:00:00Z', tracks: 'unconfirmed' } };
  settings.connections = [connection]; settings.activeConnectionId = connection.connectionId; settings.revision = 1;
  settings.storage = { softLimitBytes: 60e9, warningPercent: 90 };
  await writeFile(keyFile, `${key.toString('hex')}\n`, { mode: 0o600 });
  await put('settings-expected.json', settings);
  await put('canonical-settings.json', encryptSettings(settings, key));
} else if (mode === 'verify') {
  const key = parseSettingsKey(await readFile(keyFile, 'utf8')), envelope = await json('canonical-settings.json');
  assert.deepEqual(validateSettings(decryptSettings(envelope, key)), await json('settings-expected.json'));
  const repository = new MemoryRepository();
  await repository.commitJson(await repository.getHead(), { [SETTINGS_PATH]: envelope }, 'Synthetic restored ciphertext');
  const service = new ZoomArchive(new AudioArchiveDomain(repository), { key });
  const dto = await service.settings(); assert.equal(dto.activeConnectionId, CONNECTION.connectionId); assert.equal(dto.storage.softLimitBytes, 60e9);
  assert.doesNotMatch(JSON.stringify(dto), /synthetic-secret|synthetic-client|synthetic-account/);
  assert.throws(() => decryptSettings(envelope, randomBytes(32)));
  assert.throws(() => decryptSettings({ ...envelope, tag: randomBytes(16).toString('base64') }, key));
  await assert.rejects(() => new ZoomArchive(service.domain).settings());
  assert.equal((await service.domain.listSessions('incoming')).sessions.length, 0);
} else if (mode === 'rotate') {
  const oldKey = parseSettingsKey(await readFile(keyFile, 'utf8')), nextKey = randomBytes(32), original = await json('canonical-settings.json');
  const settings = validateSettings(decryptSettings(original, oldKey)), next = encryptSettings(settings, nextKey);
  // Interruption before CAS: old canonical bytes/key still work; uncommitted new key cannot read them.
  assert.deepEqual(decryptSettings(original, oldKey), settings); assert.throws(() => decryptSettings(original, nextKey));
  await writeFile(`${work}/external-previous-key`, `${oldKey.toString('hex')}\n`, { mode: 0o600 });
  const repository = new MemoryRepository();
  await repository.commitJson(await repository.getHead(), { [SETTINGS_PATH]: original }, 'Synthetic pre-rotation');
  const head = await repository.getHead();
  await repository.commitJson(head, { [SETTINGS_PATH]: next }, 'Synthetic CAS re-encryption');
  await assert.rejects(() => repository.commitJson(head, { [SETTINGS_PATH]: original }, 'Stale rotation'), e => e.status === 409);
  // Interruption after CAS, before runtime mount: old runtime fails closed. Retained new key restores access.
  const committed = (await repository.readJson(SETTINGS_PATH, await repository.getHead())).data;
  assert.throws(() => decryptSettings(committed, oldKey)); assert.deepEqual(decryptSettings(committed, nextKey), settings);
  assert.deepEqual(decryptSettings(original, oldKey), settings); // Historical ciphertext requires its historical key.
  await put('canonical-settings.json', committed);
  await writeFile(keyFile, `${nextKey.toString('hex')}\n`, { mode: 0o600 });
} else throw new Error('Unknown synthetic fixture action');
console.log(`S12 synthetic recovery ${mode}: PASS`);
