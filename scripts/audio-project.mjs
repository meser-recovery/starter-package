import { normalizeAudioFilename, normalizedMediaType, validateSessionManifest } from './audio-archive-client.mjs';
import { normalizeSpeakerPayload, resultDuration } from './speaker-editor-core.mjs';

export const RECONNECT_MESSAGE = 'Подключение к аудиоархиву истекло. Подключитесь снова, чтобы продолжить.';
const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);
const conflict = () => Object.assign(new Error('Запись изменилась. Сохранение остановлено; текущий монтаж остаётся в памяти.'), { status: 409 });
const localIds = new WeakMap();
export function localSourceContext(files) {
  return { kind: 'local', title: files[0]?.name.replace(/\.[^.]+$/, '') || 'Новая запись', sourceTracks: files.map((file, index) => {
    if (!localIds.has(file)) localIds.set(file, crypto.randomUUID());
    return { trackId: localIds.get(file), ordinal: index + 1, originalName: normalizeAudioFilename(file.name),
      mediaType: normalizedMediaType(file.name), sizeBytes: file.size };
  }) };
}
// Local IDs never assert persistence. Binding uses the exact hashed ingestion plan, including ordinal and blob identity.
export function bindLocalPayload(context, payload, plan, session, duration) {
  if (context.kind !== 'local' || !validateSessionManifest(session) || session.sourceState !== 'available' ||
      plan.tracks.length !== context.sourceTracks.length || session.sourceTracks.length !== plan.tracks.length) throw new Error('Состав сохранённых исходников не подтверждён.');
  const mapping = new Map();
  context.sourceTracks.forEach((local, index) => {
    const planned = plan.tracks[index], canonical = session.sourceTracks.find(t => t.trackId === planned.trackId);
    if (!canonical || ['trackId', 'blobId', 'ordinal', 'originalName', 'mediaType', 'sizeBytes', 'sha256'].some(k => canonical[k] !== planned[k]) ||
        local.sizeBytes !== planned.sizeBytes || local.mediaType !== planned.mediaType || local.originalName !== planned.originalName ||
        canonical.parts.length !== planned.parts.length || canonical.parts.some((p, i) => ['partNumber', 'sizeBytes', 'sha256', 'assetName'].some(k => p[k] !== planned.parts[i][k]))) {
      throw new Error('Целостность или принадлежность сохранённых дорожек не подтверждена.');
    }
    mapping.set(local.trackId, canonical.trackId);
  });
  const next = structuredClone(payload);
  next.trackIds = next.trackIds.map(id => mapping.get(id));
  next.excludedTrackIds = next.excludedTrackIds.map(id => mapping.get(id));
  for (const item of [...next.trackSilenceRegions, ...next.trackProcessing]) item.trackId = mapping.get(item.trackId);
  return { payload: normalizeSpeakerPayload(next, session.sourceTracks.map(t => t.trackId), duration), mapping };
}
export function recordingBoundaries(payload, duration) {
  return { start: payload.globalCuts.find(c => c.startSeconds === 0)?.endSeconds || 0,
    end: payload.globalCuts.find(c => c.endSeconds === duration)?.startSeconds ?? duration };
}
export function setRecordingBoundary(payload, duration, kind, value) {
  const bounds = recordingBoundaries(payload, duration), next = structuredClone(payload);
  if (!['start', 'end'].includes(kind) || !Number.isFinite(value)) throw new Error('Некорректная граница записи.');
  const interior = payload.globalCuts.filter(c => c.startSeconds !== 0 && c.endSeconds !== duration);
  if (interior.some(c => kind === 'start' ? value >= c.startSeconds : value <= c.endSeconds)) throw new Error('Граница пересекает существующий вырез. Сначала измените этот вырез в разделе «Правки».');
  bounds[kind] = value;
  if (bounds.start < 0 || bounds.end > duration || bounds.end <= bounds.start) throw new Error('Начало должно быть раньше конца записи.');
  next.globalCuts = next.globalCuts.filter(c => kind === 'start' ? c.startSeconds !== 0 : c.endSeconds !== duration);
  if (kind === 'start' && value > 0) next.globalCuts.push({ regionId: payload.globalCuts.find(c => c.startSeconds === 0)?.regionId || crypto.randomUUID(), startSeconds: 0, endSeconds: value });
  if (kind === 'end' && value < duration) next.globalCuts.push({ regionId: payload.globalCuts.find(c => c.endSeconds === duration)?.regionId || crypto.randomUUID(), startSeconds: value, endSeconds: duration });
  const normalized = normalizeSpeakerPayload(next, next.trackIds, duration);
  if (resultDuration(duration, normalized.globalCuts) <= 0) throw new Error('В записи должен остаться звук.');
  return normalized;
}
// One in-memory attempt; no second project store. Preserve keys and finalized sources on every error/cancellation.
export class ProjectSave {
  constructor(gateway, workflow = "speaker") { this.workflow = workflow; this.gateway = gateway; this.ingestionKey = crypto.randomUUID(); this.finalized = null; this.plan = null; this.attempt = null; }
  async sources(context, files, options = {}) {
    if (!this.finalized) {
      const result = await this.gateway.ingestFiles({ files, title: context.title, origin: 'device', ...options,
        idempotencyKey: this.ingestionKey, onPlan: plan => { this.plan = plan; } });
      this.finalized = result.session || result;
    }
    return this.finalized;
  }
  async save(session, draft, payload, signal) {
    signal?.throwIfAborted();
    const id = session.id;
    if (!this.attempt) this.attempt = { id, envelope: { schemaVersion: 1, payloadSchema: `${this.workflow}/v1`, payload: structuredClone(payload),
      expectedSourceSessionRevision: session.revision, expectedDraftRevision: draft?.draftRevision || 0, idempotencyKey: crypto.randomUUID() } };
    const attempt = this.attempt;
    if (attempt.id !== id) throw conflict();
    const [fresh, saved] = await Promise.all([this.gateway.getSession(id), this.gateway.loadDraft(id, this.workflow)]);
    if (!validateSessionManifest(fresh) || fresh.id !== id || fresh.lifecycle.state !== 'incoming' || fresh.sourceState !== 'available') throw conflict();
    const current = saved.draft, envelope = attempt.envelope;
    if (current?.payloadSchema === `${this.workflow}/v1` && current.draftRevision === envelope.expectedDraftRevision + 1 && equal(current.payload, envelope.payload) &&
        fresh.revision === envelope.expectedSourceSessionRevision + 1) {
      this.attempt = null;
      return equal(envelope.payload, payload) ? { session: fresh, draft: current } : this.save(fresh, current, payload, signal);
    }
    if (fresh.revision !== envelope.expectedSourceSessionRevision || (current?.draftRevision || 0) !== envelope.expectedDraftRevision) throw conflict();
    if (!equal(envelope.payload, payload)) {
      this.attempt = null;
      return this.save(fresh, current, payload, signal);
    }
    signal?.throwIfAborted();
    const result = await this.gateway.saveDraft(id, this.workflow, envelope, signal);
    if (!validateSessionManifest(result.session) || result.session.id !== id || !equal(result.draft?.payload, payload) || result.draft?.payloadSchema !== `${this.workflow}/v1`) throw conflict();
    this.attempt = null; return result;
  }
}
export function projectProjection(session, draft) {
  if (!draft || draft.sessionId !== session.id || draft.workflow !== 'speaker' || draft.payloadSchema !== 'speaker/v1' ||
      draft.draftRevision !== session.workflows.speaker.currentDraft?.revision || !Number.isFinite(Date.parse(draft.savedAt))) return null;
  try { normalizeSpeakerPayload(draft.payload, session.sourceTracks.map(t => t.trackId)); } catch { return null; }
  return { sessionId: session.id, title: session.title, trackCount: draft.payload.trackIds.length, savedAt: draft.savedAt };
}
