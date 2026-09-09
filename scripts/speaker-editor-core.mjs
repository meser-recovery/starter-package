export const SPEAKER_PROCESSOR_VERSION = "speaker-editor-v1";
export const SPEAKER_PAYLOAD_SCHEMA = "speaker/v1";
export const SPEAKER_SAMPLE_RATE = 48000;
export const SPEAKER_PAYLOAD_MAX_BYTES = 900 * 1024;
export const SPEAKER_MAX_REGIONS = 10000;
export const SPEAKER_FRAME_TOLERANCE_SECONDS = 1152 / SPEAKER_SAMPLE_RATE;

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const ENHANCEMENT = new Set(["off", "gentle"]);
const LEVELING = new Set(["off", "on"]);
const COMPRESSION = new Set(["off", "light", "medium", "strong"]);
const COMPRESSION_FILTERS = Object.freeze({
  light: "acompressor=threshold=0.177828:ratio=2:attack=20:release=250:knee=2:makeup=1.25",
  medium: "acompressor=threshold=0.125893:ratio=3:attack=15:release=300:knee=2.5:makeup=1.5",
  strong: "acompressor=threshold=0.089125:ratio=4:attack=10:release=350:knee=3:makeup=1.75"
});

export function speakerRendererMetadata(payload, measurements = {}) {
  const included = payload.trackIds.filter((id) => !payload.excludedTrackIds.includes(id));
  const leveled = included.filter((id) => payload.trackProcessing.find((item) => item.trackId === id)?.leveling === "on");
  return {
    sampleRate: SPEAKER_SAMPLE_RATE,
    enhancement: "highpass=f=80,lowpass=f=16000",
    loudnorm: {
      integratedLufs: -19,
      truePeakDb: -3,
      loudnessRangeLufs: 11,
      measurements: leveled.map((trackId) => ({ trackId, ...structuredClone(measurements[trackId]) }))
    },
    compression: structuredClone(COMPRESSION_FILTERS),
    mix: "amix=duration=longest:normalize=0",
    limiter: "alimiter=limit=0.95:level=0:latency=1",
    codec: { name: "libmp3lame", bitrate: "128k" }
  };
}

function fail(message) {
  throw new Error(message);
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function exactKeys(value, keys, label) {
  if (!isPlainObject(value) || Object.keys(value).length !== keys.length || keys.some((key) => !Object.hasOwn(value, key))) {
    fail(`${label}: неподдерживаемая структура.`);
  }
}

function uuid(value, label) {
  if (typeof value !== "string" || !UUID_PATTERN.test(value)) fail(`${label}: требуется UUID.`);
  return value.toLowerCase();
}

export function microseconds(value, label = "Время") {
  if (!Number.isFinite(value)) fail(`${label}: укажите конечное число.`);
  return Math.round(value * 1e6) / 1e6;
}

function validateBounds(startValue, endValue, duration, label) {
  const startSeconds = microseconds(startValue, `${label}, начало`);
  const endSeconds = microseconds(endValue, `${label}, конец`);
  const maximum = Number.isFinite(duration) ? microseconds(duration, "Длительность") : 7 * 24 * 60 * 60;
  if (startSeconds < 0 || endSeconds <= startSeconds || endSeconds > maximum) {
    fail(`${label}: интервал должен находиться внутри исходной шкалы времени.`);
  }
  return { startSeconds, endSeconds };
}

function normalizeGroup(regions) {
  const ordered = [...regions].sort((left, right) => left.startSeconds - right.startSeconds ||
    left.endSeconds - right.endSeconds || left.regionId.localeCompare(right.regionId));
  const result = [];
  for (const region of ordered) {
    const previous = result.at(-1);
    if (previous && region.startSeconds <= previous.endSeconds) {
      previous.endSeconds = Math.max(previous.endSeconds, region.endSeconds);
      previous.regionId = [previous.regionId, region.regionId].sort()[0];
    } else result.push({ ...region });
  }
  return result;
}

function normalizedGlobalCuts(value, duration) {
  if (!Array.isArray(value) || value.length > SPEAKER_MAX_REGIONS) fail("Глобальные вырезы: превышен предел регионов.");
  const ids = new Set();
  const regions = value.map((region, index) => {
    exactKeys(region, ["regionId", "startSeconds", "endSeconds"], `Глобальный вырез ${index + 1}`);
    const regionId = uuid(region.regionId, `Глобальный вырез ${index + 1}`);
    if (ids.has(regionId)) fail("Идентификаторы регионов не должны повторяться.");
    ids.add(regionId);
    return { regionId, ...validateBounds(region.startSeconds, region.endSeconds, duration, `Глобальный вырез ${index + 1}`) };
  });
  return normalizeGroup(regions);
}

function normalizedTrackSilences(value, trackIds, duration, occupiedIds = new Set()) {
  if (!Array.isArray(value) || value.length > SPEAKER_MAX_REGIONS) fail("Тишина на дорожках: превышен предел регионов.");
  const tracks = new Set(trackIds);
  const ids = new Set(occupiedIds);
  const groups = new Map(trackIds.map((trackId) => [trackId, []]));
  value.forEach((region, index) => {
    exactKeys(region, ["regionId", "trackId", "startSeconds", "endSeconds"], `Регион тишины ${index + 1}`);
    const regionId = uuid(region.regionId, `Регион тишины ${index + 1}`);
    const trackId = uuid(region.trackId, `Дорожка региона ${index + 1}`);
    if (!tracks.has(trackId)) fail("Регион тишины ссылается на неизвестную дорожку.");
    if (ids.has(regionId)) fail("Идентификаторы регионов не должны повторяться.");
    ids.add(regionId);
    groups.get(trackId).push({ regionId, trackId,
      ...validateBounds(region.startSeconds, region.endSeconds, duration, `Регион тишины ${index + 1}`) });
  });
  return trackIds.flatMap((trackId) => normalizeGroup(groups.get(trackId)));
}

export function defaultSpeakerPayload(trackIds) {
  const ids = trackIds.map((id) => uuid(id, "Дорожка"));
  if (!ids.length || new Set(ids).size !== ids.length) fail("Нужна хотя бы одна уникальная дорожка.");
  return {
    trackIds: ids,
    excludedTrackIds: [],
    globalCuts: [],
    trackSilenceRegions: [],
    trackProcessing: ids.map((trackId) => ({ trackId, enhancement: "off", leveling: "off", compression: "off" }))
  };
}

export function normalizeSpeakerPayload(value, availableTrackIds, originalTimelineDuration) {
  exactKeys(value, ["trackIds", "excludedTrackIds", "globalCuts", "trackSilenceRegions", "trackProcessing"], "Черновик Спикерской");
  if (new TextEncoder().encode(JSON.stringify(value)).byteLength > SPEAKER_PAYLOAD_MAX_BYTES) fail("Черновик слишком большой для безопасного сохранения.");
  if (!Array.isArray(availableTrackIds) || !availableTrackIds.length || availableTrackIds.length > 32) fail("Состав исходных дорожек недоступен.");
  const available = availableTrackIds.map((id) => uuid(id, "Исходная дорожка"));
  if (new Set(available).size !== available.length) fail("Исходные дорожки повторяются.");
  if (!Array.isArray(value.trackIds) || value.trackIds.length !== available.length) fail("Черновик должен содержать все исходные дорожки.");
  const trackIds = value.trackIds.map((id) => uuid(id, "Дорожка черновика"));
  if (new Set(trackIds).size !== trackIds.length || trackIds.some((id) => !available.includes(id)) || available.some((id) => !trackIds.includes(id))) {
    fail("Состав дорожек черновика не совпадает с исходной записью.");
  }
  if (!Array.isArray(value.excludedTrackIds)) fail("Исключённые дорожки должны быть списком.");
  const excludedTrackIds = value.excludedTrackIds.map((id) => uuid(id, "Исключённая дорожка"));
  if (new Set(excludedTrackIds).size !== excludedTrackIds.length || excludedTrackIds.some((id) => !trackIds.includes(id))) {
    fail("Исключённые дорожки должны быть уникальным подмножеством исходных.");
  }
  const globalCuts = normalizedGlobalCuts(value.globalCuts, originalTimelineDuration);
  const trackSilenceRegions = normalizedTrackSilences(value.trackSilenceRegions, trackIds, originalTimelineDuration,
    new Set(value.globalCuts.map((region) => uuid(region.regionId, "Глобальный вырез"))));
  if (!Array.isArray(value.trackProcessing) || value.trackProcessing.length !== trackIds.length) {
    fail("Для каждой дорожки требуются настройки обработки.");
  }
  const processingByTrack = new Map();
  for (const [index, setting] of value.trackProcessing.entries()) {
    exactKeys(setting, ["trackId", "enhancement", "leveling", "compression"], `Обработка дорожки ${index + 1}`);
    const trackId = uuid(setting.trackId, `Обработка дорожки ${index + 1}`);
    if (!trackIds.includes(trackId) || processingByTrack.has(trackId)) fail("Настройки обработки должны точно покрывать все дорожки.");
    if (!ENHANCEMENT.has(setting.enhancement) || !LEVELING.has(setting.leveling) || !COMPRESSION.has(setting.compression)) {
      fail("Выбрано неподдерживаемое значение обработки.");
    }
    processingByTrack.set(trackId, { trackId, enhancement: setting.enhancement, leveling: setting.leveling, compression: setting.compression });
  }
  const normalized = {
    trackIds,
    excludedTrackIds: trackIds.filter((id) => excludedTrackIds.includes(id)),
    globalCuts,
    trackSilenceRegions,
    trackProcessing: trackIds.map((id) => processingByTrack.get(id))
  };
  if (new TextEncoder().encode(JSON.stringify(normalized)).byteLength > SPEAKER_PAYLOAD_MAX_BYTES) fail("Черновик слишком большой для безопасного сохранения.");
  return normalized;
}

export function removedDuration(globalCuts) {
  return microseconds(globalCuts.reduce((sum, region) => sum + region.endSeconds - region.startSeconds, 0));
}

export function resultDuration(originalDuration, globalCuts) {
  return microseconds(originalDuration - removedDuration(globalCuts));
}

export function originalToResultTime(originalSeconds, globalCuts) {
  const time = microseconds(originalSeconds);
  let removed = 0;
  for (const cut of globalCuts) {
    if (time >= cut.endSeconds) removed += cut.endSeconds - cut.startSeconds;
    else if (time > cut.startSeconds) return microseconds(cut.startSeconds - removed);
  }
  return microseconds(time - removed);
}

export function mapSilenceToResult(region, globalCuts) {
  let pieces = [[region.startSeconds, region.endSeconds]];
  for (const cut of globalCuts) {
    pieces = pieces.flatMap(([start, end]) => {
      if (end <= cut.startSeconds || start >= cut.endSeconds) return [[start, end]];
      const kept = [];
      if (start < cut.startSeconds) kept.push([start, cut.startSeconds]);
      if (end > cut.endSeconds) kept.push([cut.endSeconds, end]);
      return kept;
    });
  }
  return pieces.map(([start, end]) => [originalToResultTime(start, globalCuts), originalToResultTime(end, globalCuts)])
    .filter(([start, end]) => end > start);
}

function timeExpression(regions) {
  return regions.map((region) => `gte(t,${region.startSeconds.toFixed(6)})*lt(t,${region.endSeconds.toFixed(6)})`).join("+");
}

export function parseLoudnormMeasurements(lines) {
  const text = Array.isArray(lines) ? lines.join("\n") : String(lines || "");
  const matches = [...text.matchAll(/\{[\s\S]*?"input_i"[\s\S]*?\}/g)];
  if (!matches.length) fail("Не удалось получить надёжные измерения громкости.");
  let data;
  try { data = JSON.parse(matches.at(-1)[0]); } catch { fail("Не удалось прочитать измерения громкости."); }
  const fields = { input_i: "measured_I", input_tp: "measured_TP", input_lra: "measured_LRA", input_thresh: "measured_thresh", target_offset: "offset" };
  const bounded = {};
  for (const [source, target] of Object.entries(fields)) {
    const value = Number(data[source]);
    if (!Number.isFinite(value) || value < -120 || value > 120) fail("Измерения громкости вышли за безопасный диапазон.");
    bounded[target] = value;
  }
  return bounded;
}

function loudnormFilter(measured) {
  if (!measured) fail("Для выравнивания нужны измерения первого прохода.");
  const values = [measured.measured_I, measured.measured_TP, measured.measured_LRA, measured.measured_thresh, measured.offset];
  if (values.some((value) => !Number.isFinite(value) || value < -120 || value > 120)) fail("Измерения громкости недопустимы.");
  return `loudnorm=I=-19:TP=-3:LRA=11:measured_I=${values[0]}:measured_TP=${values[1]}:measured_LRA=${values[2]}:measured_thresh=${values[3]}:offset=${values[4]}:linear=true:print_format=summary`;
}

export function buildTrackFilter({ inputIndex, trackId, duration, payload, measurement = null, outputLabel = "track" }) {
  if (!Number.isInteger(inputIndex) || inputIndex < 0 || !/^[a-z][a-z0-9_-]*$/i.test(outputLabel)) fail("Небезопасная метка FFmpeg.");
  const normalized = normalizeSpeakerPayload(payload, payload.trackIds, duration);
  if (!normalized.trackIds.includes(trackId)) fail("Неизвестная дорожка.");
  const processing = normalized.trackProcessing.find((item) => item.trackId === trackId);
  const silences = normalized.trackSilenceRegions.filter((item) => item.trackId === trackId);
  const filters = [`asetpts=N/SR/TB`, `aresample=${SPEAKER_SAMPLE_RATE}`,
    `apad=whole_len=${Math.ceil(duration * SPEAKER_SAMPLE_RATE)}`, `atrim=end=${duration.toFixed(6)}`];
  if (silences.length) filters.push(`volume=volume=0:enable='${timeExpression(silences)}'`);
  if (normalized.globalCuts.length) filters.push("asetnsamples=n=256:p=0",
    `aselect='not(${timeExpression(normalized.globalCuts)})'`, "asetpts=N/SR/TB");
  else filters.push("asetpts=N/SR/TB");
  if (processing.enhancement === "gentle") filters.push("highpass=f=80", "lowpass=f=16000");
  if (processing.leveling === "on") filters.push(loudnormFilter(measurement));
  if (processing.compression !== "off") filters.push(COMPRESSION_FILTERS[processing.compression]);
  const resultSilences = silences.flatMap((region) => mapSilenceToResult(region, normalized.globalCuts))
    .map(([startSeconds, endSeconds], index) => ({ regionId: String(index), startSeconds, endSeconds }));
  if (resultSilences.length) filters.push(`volume=volume=0:enable='${timeExpression(resultSilences)}'`);
  return `[${inputIndex}:a:0]${filters.join(",")}[${outputLabel}]`;
}

export function buildLevelingAnalysisFilter(options) {
  const payload = structuredClone(options.payload);
  const setting = payload.trackProcessing.find((item) => item.trackId === options.trackId);
  if (!setting || setting.leveling !== "on") fail("Первый проход громкости запрошен для дорожки без выравнивания.");
  setting.leveling = "off";
  setting.compression = "off";
  const graph = buildTrackFilter({ ...options, payload, measurement: null, outputLabel: "analysis" });
  return graph.replace("[analysis]", ",loudnorm=I=-19:TP=-3:LRA=11:print_format=json[analysis]");
}

export function buildSpeakerFilterGraph(payload, duration, measurements = {}) {
  const normalized = normalizeSpeakerPayload(payload, payload.trackIds, duration);
  const included = normalized.trackIds.filter((id) => !normalized.excludedTrackIds.includes(id));
  if (!included.length) fail("Верните хотя бы одну дорожку в микс.");
  const inputByTrack = new Map(normalized.trackIds.map((id, index) => [id, index]));
  const tracks = included.map((trackId, index) => buildTrackFilter({ inputIndex: inputByTrack.get(trackId), trackId, duration,
    payload: normalized, measurement: measurements[trackId] || null, outputLabel: `speaker_track_${index}` }));
  const labels = included.map((_, index) => `[speaker_track_${index}]`).join("");
  return `${tracks.join(";")};${labels}amix=inputs=${included.length}:duration=longest:normalize=0,` +
    "alimiter=limit=0.95:level=0:latency=1[speaker_mix]";
}

export class SpeakerHistory {
  constructor(initial) { this.reset(initial); }
  reset(value) { this.past = []; this.present = structuredClone(value); this.future = []; return this.value(); }
  value() { return structuredClone(this.present); }
  commit(value) {
    if (JSON.stringify(value) === JSON.stringify(this.present)) return this.value();
    this.past.push(this.present); this.present = structuredClone(value); this.future = []; return this.value();
  }
  undo() { if (!this.past.length) return this.value(); this.future.push(this.present); this.present = this.past.pop(); return this.value(); }
  redo() { if (!this.future.length) return this.value(); this.past.push(this.present); this.present = this.future.pop(); return this.value(); }
  get canUndo() { return this.past.length > 0; }
  get canRedo() { return this.future.length > 0; }
}

export function payloadFingerprint(payload) {
  return JSON.stringify(payload);
}

function deepFreeze(value) {
  if (!value || typeof value !== "object" || value instanceof Blob || Object.isFrozen(value)) return value;
  for (const item of Object.values(value)) deepFreeze(item);
  return Object.freeze(value);
}

export function createSpeakerRenderSnapshot({ session, draftRevision = 0, payload, originalDurationSeconds, tracks }) {
  if (!session || !Array.isArray(session.sourceTracks)) fail("Состав исходной записи недоступен.");
  const availableTrackIds = session.sourceTracks.map((track) => track.trackId);
  const normalized = normalizeSpeakerPayload(payload, availableTrackIds, originalDurationSeconds);
  if (!Array.isArray(tracks) || tracks.length !== normalized.trackIds.length) fail("Состав подготовленных исходников не совпадает с записью.");
  const tracksById = new Map();
  for (const track of tracks) {
    const trackId = uuid(track?.trackId, "Подготовленная дорожка");
    if (tracksById.has(trackId) || !(track.file instanceof Blob)) fail("Подготовленные исходники неполны или повторяются.");
    tracksById.set(trackId, track);
  }
  const sources = normalized.trackIds.map((trackId) => {
    const prepared = tracksById.get(trackId);
    const identity = session.sourceTracks.find((track) => track.trackId.toLowerCase() === trackId);
    if (!prepared || !identity || prepared.file.size !== identity.sizeBytes) fail("Подготовленный исходник не совпадает с записью.");
    return Object.freeze({ trackId, file: prepared.file, identity: deepFreeze(structuredClone(identity)) });
  });
  const snapshot = {
    payload: deepFreeze(structuredClone(normalized)),
    payloadFingerprint: payloadFingerprint(normalized),
    session: deepFreeze(structuredClone(session)),
    sessionId: session.id,
    sourceSessionRevision: session.revision,
    draftRevision: Number.isInteger(draftRevision) && draftRevision >= 0 ? draftRevision : 0,
    originalDurationSeconds: microseconds(originalDurationSeconds, "Исходная длительность"),
    sources: Object.freeze(sources)
  };
  return Object.freeze(snapshot);
}

export function candidateAffectedBy(action) {
  return new Set(["globalCuts", "trackSilenceRegions", "excludedTrackIds", "trackIds", "enhancement", "leveling", "compression",
    "sourceReplacement", "sourceProvenance"]).has(action);
}

export function rebindSpeakerCandidate(candidate, payload, sessionRevision, draftRevision) {
  if (!candidate || candidate.payloadFingerprint !== payloadFingerprint(payload)) return null;
  return Object.freeze({ ...candidate, sourceSessionRevision: sessionRevision, draftRevision });
}

export async function buildSpeakerCandidate({ blob, snapshot, measurements = {}, resultDurationSeconds, renderedAt = new Date().toISOString(), sha256 }) {
  if (!snapshot || snapshot.payloadFingerprint !== payloadFingerprint(snapshot.payload)) fail("Снимок локальной сборки повреждён.");
  const normalized = snapshot.payload;
  const originalDurationSeconds = snapshot.originalDurationSeconds;
  const expected = resultDuration(originalDurationSeconds, normalized.globalCuts);
  if (!Number.isFinite(resultDurationSeconds) || Math.abs(resultDurationSeconds - expected) > SPEAKER_FRAME_TOLERANCE_SECONDS) {
    fail("Длительность результата не совпадает с выбранными глобальными вырезами.");
  }
  const hash = await sha256(new Uint8Array(await blob.arrayBuffer()));
  const excluded = new Set(normalized.excludedTrackIds);
  const renderer = speakerRendererMetadata(normalized, measurements);
  const resultIdentity = { sessionId: snapshot.sessionId, payload: normalized,
    sources: snapshot.sources.map(({ trackId, identity }) => ({ trackId, blobId: identity.blobId, ordinal: identity.ordinal,
      originalFilename: identity.originalName, mediaType: identity.mediaType, sizeBytes: identity.sizeBytes, sha256: identity.sha256 })),
    renderer, sizeBytes: blob.size, sha256: hash, renderedAt };
  const candidateFingerprint = await sha256(new TextEncoder().encode(JSON.stringify(resultIdentity)));
  return Object.freeze({
    candidateType: "speaker", processorVersion: SPEAKER_PROCESSOR_VERSION, payloadSchema: SPEAKER_PAYLOAD_SCHEMA,
    sessionId: snapshot.sessionId, sourceSessionRevision: snapshot.sourceSessionRevision, draftRevision: snapshot.draftRevision,
    sources: snapshot.sources.map(({ trackId, identity }) => {
      return { trackId, blobId: identity.blobId, ordinal: identity.ordinal, originalFilename: identity.originalName,
        mediaType: identity.mediaType, sizeBytes: identity.sizeBytes, sha256: identity.sha256 };
    }),
    globalCuts: structuredClone(normalized.globalCuts), trackSilenceRegions: structuredClone(normalized.trackSilenceRegions),
    includedTrackIds: normalized.trackIds.filter((id) => !excluded.has(id)), excludedTrackIds: [...normalized.excludedTrackIds],
    trackProcessing: structuredClone(normalized.trackProcessing), blob, mediaType: "audio/mpeg",
    presentationFilename: `${String(snapshot.session.title || "speaker").replace(/[\\/\u0000-\u001f]/g, "-").slice(0, 220)}-speaker.mp3`,
    sizeBytes: blob.size, sha256: hash, originalDurationSeconds, resultDurationSeconds,
    globallyRemovedDurationSeconds: removedDuration(normalized.globalCuts), renderedAt,
    payload: structuredClone(normalized), renderer, candidateFingerprint,
    payloadFingerprint: payloadFingerprint(normalized)
  });
}
