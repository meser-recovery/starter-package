// Test-only JSON-lines bridge: real client + authenticated app + in-memory domain. No network transport.
import { createInterface } from 'node:readline';
import { managementFixture, wav } from '../../gateway/audio-archive/test/archive-management-fixture.mjs';
let h = await managementFixture();
let authenticated = true;
function previewWav(trackIndex = 0) {
  const rate = 8000, seconds = 8, samples = rate * seconds;
  const bytes = Buffer.alloc(44 + samples * 2);
  bytes.write('RIFF'); bytes.writeUInt32LE(bytes.length - 8, 4); bytes.write('WAVEfmt ', 8);
  bytes.writeUInt32LE(16, 16); bytes.writeUInt16LE(1, 20); bytes.writeUInt16LE(1, 22); bytes.writeUInt32LE(rate, 24); bytes.writeUInt32LE(rate * 2, 28);
  bytes.writeUInt16LE(2, 32); bytes.writeUInt16LE(16, 34); bytes.write('data', 36); bytes.writeUInt32LE(samples * 2, 40);
  for (let index = 0; index < samples; index++) {
    const time = index / rate;
    const phrase = .2 + .58 * Math.abs(Math.sin(time * Math.PI * (.72 + trackIndex * .11) + trackIndex));
    const syllables = .35 + .65 * Math.abs(Math.sin(time * Math.PI * (3.1 + trackIndex * .37)));
    const pause = (time > 2.15 + trackIndex * .12 && time < 2.72 + trackIndex * .1) || (time > 5.35 && time < 5.72 + trackIndex * .08) ? .025 : 1;
    const carrier = Math.sin(2 * Math.PI * (155 + trackIndex * 73) * time) + .34 * Math.sin(2 * Math.PI * (311 + trackIndex * 41) * time);
    bytes.writeInt16LE(Math.round(8800 * phrase * syllables * pause * carrier), 44 + index * 2);
  }
  return bytes;
}
async function snapshot() {
  return { primary: await h.gateway.getSession(h.primary.id), archived: await h.gateway.getSession(h.archived.id), empty: h.empty,
    sessions: [...(await h.gateway.listSessions('incoming')).sessions, ...(await h.gateway.listSessions('archived')).sessions], maintenance: await h.gateway.listIncomplete() };
}
async function interruptSave(kind, allParts, discarding = false) {
  const session = await h.ingest(`Незавершённое сохранение ${kind === 'speaker' ? 'спикерской' : 'анонса'}`, `${kind}-${allParts}-${discarding}`);
  const original = h.gateway.fetchImpl;
  let parts = 0;
  h.gateway.fetchImpl = async (input, options = {}) => {
    if (input.includes('/finalize') || (!allParts && options.method === 'PUT' && input.includes('/parts/') && parts++ > 0)) throw new Error('Test interrupted save');
    return original(input, options);
  };
  try { await h.save(session, kind, `partial-${kind}-${allParts}-${discarding}`); } catch { /* Deliberate interruption. */ }
  finally { h.gateway.fetchImpl = original; }
  if (discarding) {
    const operation = (await h.gateway.listIncomplete()).transactions.find(t => t.sessionId === session.id);
    const remove = h.repository.deleteAsset.bind(h.repository);
    h.repository.deleteAsset = async id => { await remove(id); throw new Error('Test interrupted discard'); };
    try { await h.gateway.recoverIncomplete(operation.transactionId, 'discard'); } catch { /* Retain discarding. */ }
    finally { h.repository.deleteAsset = remove; }
  }
}
async function seedRecovery() {
  for (const kind of ['announcement', 'speaker']) for (const complete of [false, true]) await interruptSave(kind, complete);
  await interruptSave('speaker', true, true);
  const original = h.gateway.fetchImpl; let parts = 0;
  h.gateway.fetchImpl = async (input, options = {}) => {
    if (options.method === 'PUT' && input.includes('/parts/') && parts++ > 0) throw new Error('Test interrupted ingestion');
    return original(input, options);
  };
  try { await h.ingest('Незавершённая загрузка', 'incomplete-ingestion'); } catch { /* Retain ingestion. */ }
  finally { h.gateway.fetchImpl = original; }
  const pending = await h.ingest('Незавершённое удаление', 'pending-delete');
  const remove = h.repository.deleteAsset.bind(h.repository);
  h.repository.deleteAsset = async id => { await remove(id); throw new Error('Test interrupted deletion'); };
  try { await h.gateway.deleteSources(pending.id, { expectedRevision: pending.revision, confirmation: 'Удалить исходники, сохранить результаты', idempotencyKey: 's09-management-pending-delete' }); } catch { /* Retain pending delete. */ }
  finally { h.repository.deleteAsset = remove; }
}
console.log(JSON.stringify(await snapshot()));
for await (const line of createInterface({ input: process.stdin })) {
  try {
    const command = JSON.parse(line);
    let result;
    if (command.action === 'reset') { h = await managementFixture(); authenticated = true; result = await snapshot(); }
    else if (command.action === 'snapshot') result = await snapshot();
    else if (command.action === 'recovery') { await seedRecovery(); result = await snapshot(); }
    else if (command.action === 'multi-track-preview') {
      const files = ['Ведущий.wav', 'Спикер 1.wav', 'Спикер 2.wav'].map((name, index) => new File([previewWav(index)], name, { type: 'audio/wav' }));
      result = await h.gateway.ingestFiles({
        files, title: 'Спикерская · три синхронизированные дорожки', recordedAt: '2026-09-08T18:00:00Z',
        origin: 'manual', idempotencyKey: 's09c-preview-multi-track'
      });
    }
    else if (command.action === 'purge-empty') {
      const session = await h.gateway.getSession(h.empty.id);
      await h.gateway.purgeSession(session.id, { expectedRevision: session.revision, idempotencyKey: 's09-navigation-purge', confirmation: session.id }); result = {};
    }
    else if (command.action === 'auth') { authenticated = command.value; result = {}; }
    else if (command.action === 'conflict') {
      const session = await h.gateway.getSession(command.id);
      await h.gateway.updateSession(session.id, session.revision, { title: 'Изменено в другом окне' }); result = {};
    } else if (command.action === 'request') {
      if (!authenticated && command.path !== '/v1/session/login') result = { status: 401, body: JSON.stringify({ error: 'Подключите архив' }), type: 'application/json' };
      else {
        const response = await h.gateway.fetchImpl(`https://gateway.test${command.path}`, { method: command.method, headers: command.headers, ...(command.bodyBase64 ? { body: Buffer.from(command.bodyBase64, "base64") } : command.body ? { body: command.body } : {}) });
        const bytes = Buffer.from(await response.arrayBuffer());
        if (response.headers.get('content-type')?.startsWith('application/json')) {
          const payload = JSON.parse(bytes.toString());
          if (payload.csrfToken) h.gateway.csrfToken = payload.csrfToken;
        }
        result = { status: response.status, body: bytes.toString('base64'), base64: true, type: response.headers.get('content-type') };
        if (command.path === '/v1/session/logout' && response.ok) authenticated = false;
        if (command.path === '/v1/session/login' && response.ok) authenticated = true;
      }
    } else throw new Error('Unknown test command');
    console.log(JSON.stringify(result));
  } catch (error) { console.log(JSON.stringify({ bridgeError: error.message })); }
}
