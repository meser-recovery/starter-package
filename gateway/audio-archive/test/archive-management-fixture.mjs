import { readFile } from 'node:fs/promises';
import { AudioArchiveGateway, sha256Hex } from '../../../scripts/audio-archive-client.mjs';
import { createApp } from '../src/app.mjs';
import { createPasswordVerifier } from '../src/auth.mjs';
import { AudioArchiveDomain } from '../src/domain.mjs';
import { MemoryRepository } from './helpers.mjs';

export function wav() {
  const bytes = Buffer.alloc(44 + 8000); bytes.write('RIFF'); bytes.writeUInt32LE(bytes.length - 8, 4); bytes.write('WAVEfmt ', 8);
  bytes.writeUInt32LE(16, 16); bytes.writeUInt16LE(1, 20); bytes.writeUInt16LE(1, 22); bytes.writeUInt32LE(8000, 24); bytes.writeUInt32LE(16000, 28);
  bytes.writeUInt16LE(2, 32); bytes.writeUInt16LE(16, 34); bytes.write('data', 36); bytes.writeUInt32LE(8000, 40);
  for (let i = 0; i < 4000; i++) bytes.writeInt16LE(Math.round(Math.sin(i * Math.PI * 440 / 4000) * 2000), 44 + i * 2);
  return bytes;
}
export async function managementHarness() {
  const repository = new MemoryRepository(), trace = [], clock = () => Date.parse('2026-09-10T12:00:00Z');
  const domain = new AudioArchiveDomain(repository, { acceptedPartBytes: 4096, clock });
  const verifier = await createPasswordVerifier('local-test-password', Buffer.alloc(16, 8), { N: 16384, r: 8, p: 1 });
  const app = createApp({ config: { allowedOrigin: 'https://site.test', acceptedPartBytes: 4096, sessionSigningSecret: '0123456789abcdef0123456789abcdef', sessionLifetimeSeconds: 3600, sharedPasswordVerifier: verifier }, domain, clock });
  let cookie = '';
  const gateway = new AudioArchiveGateway('https://gateway.test', async (input, init = {}) => {
    const url = new URL(input);
    if (url.origin !== 'https://gateway.test') throw new Error('Outbound access blocked');
    trace.push({ path: url.pathname + url.search, method: init.method || 'GET' });
    const headers = new Headers(init.headers); headers.set('Origin', 'https://site.test'); if (cookie) headers.set('Cookie', cookie);
    const response = await app(new Request(input, { ...init, headers }));
    if (response.headers.get('set-cookie')) cookie = response.headers.get('set-cookie').split(';')[0];
    return response;
  });
  await gateway.login('local-test-password'); await gateway.configuration();
  async function ingest(title, key, recordedAt = null) {
    return (await gateway.ingestFiles({ files: [new File([wav()], 'Исходник Й.wav', { type: 'audio/wav' })], title, recordedAt, origin: 'manual', idempotencyKey: `s09-management:${key}` })).session;
  }
  async function save(session, workflow, key) {
    session = await gateway.getSession(session.id);
    const track = session.sourceTracks[0], trackIds = [track.trackId];
    const payload = workflow === 'announcement' ? { trackIds } : { trackIds, excludedTrackIds: [], globalCuts: [], trackSilenceRegions: [], trackProcessing: [{ trackId: track.trackId, enhancement: 'off', leveling: 'off', compression: 'off' }] };
    const previous = await gateway.loadDraft(session.id, workflow);
    const saved = await gateway.saveDraft(session.id, workflow, { schemaVersion: 1, expectedDraftRevision: previous.draft?.draftRevision || 0, expectedSourceSessionRevision: session.revision, payloadSchema: `${workflow}/v1`, payload, idempotencyKey: `s09-management:${key}:draft` });
    session = saved.session;
    const bytes = workflow === 'announcement' ? wav() : await readFile(new URL('./fixtures/s09/tone.mp3', import.meta.url));
    const recipe = { sourceSessionRevision: session.revision, draft: { revision: saved.draft.draftRevision, payloadSchema: `${workflow}/v1`, payload },
      sources: [{ trackId: track.trackId, blobId: track.blobId, ordinal: 1, sizeBytes: track.sizeBytes, sha256: track.sha256, mediaType: track.mediaType }],
      result: { mediaType: workflow === 'announcement' ? 'audio/wav' : 'audio/mpeg', presentationFilename: workflow === 'announcement' ? 'Анонс.wav' : 'Спикерская.mp3', sizeBytes: bytes.length, sha256: await sha256Hex(bytes), originalDurationSeconds: .5, resultDurationSeconds: .5 } };
    if (workflow === 'announcement') {
      recipe.processing = { mode: 'passthrough', silenceThresholdDb: -45, minimumSilenceSeconds: 2, retainedSilenceSeconds: .35, detectedIntervals: [], removalRanges: [], mix: null, limiter: null, codec: null };
      Object.assign(recipe.result, { removedDurationSeconds: 0, pauseCount: 0 });
    } else {
      recipe.renderedAt = '2026-09-10T11:00:00Z'; recipe.sources[0].originalFilename = track.originalName;
      recipe.editState = { orderedTrackIds: trackIds, includedTrackIds: trackIds, excludedTrackIds: [], globalCuts: [], trackSilenceRegions: [], trackProcessing: payload.trackProcessing };
      recipe.renderer = { sampleRate: 48000, enhancement: 'highpass=f=80,lowpass=f=16000', loudnorm: { integratedLufs: -19, truePeakDb: -3, loudnessRangeLufs: 11, measurements: [] },
        compression: { light: 'acompressor=threshold=0.177828:ratio=2:attack=20:release=250:knee=2:makeup=1.25', medium: 'acompressor=threshold=0.125893:ratio=3:attack=15:release=300:knee=2.5:makeup=1.5', strong: 'acompressor=threshold=0.089125:ratio=4:attack=10:release=350:knee=3:makeup=1.75' }, mix: 'amix=duration=longest:normalize=0', limiter: 'alimiter=limit=0.95:level=0:latency=1', codec: { name: 'libmp3lame', bitrate: '128k' } };
      recipe.candidateFingerprint = await sha256Hex(key); recipe.result.globallyRemovedDurationSeconds = 0;
    }
    const options = { sessionId: session.id, expectedRevision: session.revision, expectedDraftRevision: saved.draft.draftRevision, blob: new Blob([bytes], { type: recipe.result.mediaType }), recipe, idempotencyKey: `s09-management:${key}:save` };
    return workflow === 'announcement' ? gateway.publishAnnouncement(options) : gateway.saveSpeaker(options);
  }
  return { gateway, domain, repository, trace, ingest, save };
}
export async function managementFixture() {
  const h = await managementHarness();
  let primary = await h.ingest('Встреча Й · длинное название записи для проверки переноса на узком экране', 'primary', '2026-09-09T22:30:00+03:00');
  for (let index = 1; index <= 3; index++) await h.save(primary, 'announcement', `announcement-${index}`);
  await h.save(primary, 'speaker', 'speaker-1'); primary = await h.gateway.getSession(primary.id);
  await h.gateway.deleteOutputVersion(primary.id, 'announcement', 2, { expectedRevision: primary.revision, confirmation: '', idempotencyKey: 's09-management:delete-version-2' });
  let archived = await h.ingest('Архивная беседа', 'archived'); await h.save(archived, 'announcement', 'archived-output'); archived = await h.gateway.getSession(archived.id);
  await h.gateway.setLifecycle(archived.id, 'archive', archived.revision);
  const empty = await h.ingest('Новая запись', 'empty', '2026-08-10T00:00:00Z');
  primary = await h.gateway.getSession(primary.id);
  return { ...h, primary, archived: await h.gateway.getSession(archived.id), empty };
}
