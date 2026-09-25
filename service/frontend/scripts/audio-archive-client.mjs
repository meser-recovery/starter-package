export const AUDIO_ARCHIVE_SCHEMA_VERSION = 1;
export const MAX_AUDIO_SESSION_BYTES = 500 * 1024 * 1024;
export const DEFAULT_AUDIO_PART_BYTES = 16 * 1024 * 1024;
export const MAX_AUDIO_PART_BYTES = 64 * 1024 * 1024;

const MEDIA_TYPES = Object.freeze({
  mp3: "audio/mpeg",
  m4a: "audio/mp4",
  wav: "audio/wav"
});

const encoder = new TextEncoder();
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA256_PATTERN = /^[0-9a-f]{64}$/;
const WORKFLOWS = new Set(["announcement", "speaker"]);
const WORKFLOW_STATES = new Set(["new", "in_progress", "result_ready"]);

function hasExactKeys(value, keys) {
  return value && typeof value === "object" && !Array.isArray(value) &&
    Object.keys(value).length === keys.length && keys.every((key) => Object.prototype.hasOwnProperty.call(value, key));
}

export function isUuid(value) {
  return typeof value === "string" && UUID_PATTERN.test(value);
}

function rotateRight(value, amount) {
  return (value >>> amount) | (value << (32 - amount));
}

// Small incremental implementation avoids buffering a complete 500 MiB logical file.
export class Sha256 {
  constructor() {
    this.state = new Uint32Array([
      0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
      0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19
    ]);
    this.buffer = new Uint8Array(64);
    this.bufferLength = 0;
    this.bytesHashed = 0;
    this.finished = false;
  }

  update(input) {
    if (this.finished) throw new Error("SHA-256 уже завершён.");
    const data = input instanceof Uint8Array ? input : new Uint8Array(input);
    this.bytesHashed += data.byteLength;
    let position = 0;
    if (this.bufferLength) {
      const needed = 64 - this.bufferLength;
      const take = Math.min(needed, data.byteLength);
      this.buffer.set(data.subarray(0, take), this.bufferLength);
      this.bufferLength += take;
      position += take;
      if (this.bufferLength === 64) {
        this.process(this.buffer);
        this.bufferLength = 0;
      }
    }
    while (position + 64 <= data.byteLength) {
      this.process(data.subarray(position, position + 64));
      position += 64;
    }
    if (position < data.byteLength) {
      this.buffer.set(data.subarray(position), 0);
      this.bufferLength = data.byteLength - position;
    }
    return this;
  }

  process(chunk) {
    const words = new Uint32Array(64);
    const view = new DataView(chunk.buffer, chunk.byteOffset, chunk.byteLength);
    for (let index = 0; index < 16; index++) words[index] = view.getUint32(index * 4);
    for (let index = 16; index < 64; index++) {
      const a = words[index - 15];
      const b = words[index - 2];
      const s0 = rotateRight(a, 7) ^ rotateRight(a, 18) ^ (a >>> 3);
      const s1 = rotateRight(b, 17) ^ rotateRight(b, 19) ^ (b >>> 10);
      words[index] = (words[index - 16] + s0 + words[index - 7] + s1) >>> 0;
    }
    const constants = Sha256.constants;
    let [a, b, c, d, e, f, g, h] = this.state;
    for (let index = 0; index < 64; index++) {
      const s1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
      const choice = (e & f) ^ (~e & g);
      const first = (h + s1 + choice + constants[index] + words[index]) >>> 0;
      const s0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const second = (s0 + majority) >>> 0;
      h = g; g = f; f = e; e = (d + first) >>> 0;
      d = c; c = b; b = a; a = (first + second) >>> 0;
    }
    this.state[0] = (this.state[0] + a) >>> 0;
    this.state[1] = (this.state[1] + b) >>> 0;
    this.state[2] = (this.state[2] + c) >>> 0;
    this.state[3] = (this.state[3] + d) >>> 0;
    this.state[4] = (this.state[4] + e) >>> 0;
    this.state[5] = (this.state[5] + f) >>> 0;
    this.state[6] = (this.state[6] + g) >>> 0;
    this.state[7] = (this.state[7] + h) >>> 0;
  }

  digestHex() {
    if (!this.finished) {
      const bitLength = BigInt(this.bytesHashed) * 8n;
      this.buffer[this.bufferLength++] = 0x80;
      if (this.bufferLength > 56) {
        this.buffer.fill(0, this.bufferLength);
        this.process(this.buffer);
        this.bufferLength = 0;
      }
      this.buffer.fill(0, this.bufferLength, 56);
      const view = new DataView(this.buffer.buffer);
      view.setUint32(56, Number((bitLength >> 32n) & 0xffffffffn));
      view.setUint32(60, Number(bitLength & 0xffffffffn));
      this.process(this.buffer);
      this.finished = true;
    }
    return Array.from(this.state, (value) => value.toString(16).padStart(8, "0")).join("");
  }
}

Sha256.constants = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
]);

export function normalizeAudioFilename(value) {
  const cleaned = String(value || "audio")
    .normalize("NFC")
    .replace(/[\u0000-\u001f\u007f]/g, "")
    .replace(/[\\/]+/g, "-")
    .trim()
    .slice(0, 255);
  return cleaned || "audio";
}

export function normalizedMediaType(filename, suppliedType = "") {
  const extension = normalizeAudioFilename(filename).split(".").pop()?.toLowerCase();
  const canonical = MEDIA_TYPES[extension];
  if (!canonical) throw new Error("Поддерживаются файлы MP3, M4A и WAV.");
  const supplied = String(suppliedType || "").toLowerCase().split(";")[0].trim();
  const compatible = !supplied || supplied === canonical ||
    (extension === "m4a" && supplied === "audio/x-m4a") ||
    (extension === "wav" && supplied === "audio/x-wav");
  if (!compatible) throw new Error("Тип аудиофайла не соответствует его расширению.");
  return canonical;
}

function throwIfAborted(signal) {
  if (!signal?.aborted) return;
  if (signal.reason instanceof Error) throw signal.reason;
  throw new DOMException("Операция отменена.", "AbortError");
}

export async function sha256Hex(value, signal) {
  throwIfAborted(signal);
  const bytes = value instanceof Uint8Array ? value : value instanceof ArrayBuffer ? new Uint8Array(value) : encoder.encode(String(value));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  throwIfAborted(signal);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function canonicalValue(value) {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (value && typeof value === "object") return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonicalValue(value[key])]));
  return value;
}

function projectStateIdentity(value) {
  return canonicalValue({ sessionId: value.sessionId, workflow: value.workflow, draftRevision: value.draftRevision,
    sourceSessionRevision: value.sourceSessionRevision, payloadSchema: value.payloadSchema, payload: value.payload, sources: value.sources });
}

function validateSpeakerStatePayload(payload, sourceIds) {
  if (!hasExactKeys(payload, ["trackIds", "excludedTrackIds", "globalCuts", "trackSilenceRegions", "trackProcessing"]) ||
      !Array.isArray(payload.trackIds) || payload.trackIds.length !== sourceIds.length || payload.trackIds.some((id, index) => id !== sourceIds[index] || !isUuid(id)) ||
      new Set(payload.trackIds).size !== payload.trackIds.length || !Array.isArray(payload.excludedTrackIds) ||
      payload.excludedTrackIds.some(id => !payload.trackIds.includes(id)) || new Set(payload.excludedTrackIds).size !== payload.excludedTrackIds.length ||
      JSON.stringify(payload.excludedTrackIds) !== JSON.stringify(payload.trackIds.filter(id => payload.excludedTrackIds.includes(id))) ||
      !Array.isArray(payload.trackProcessing) || payload.trackProcessing.length !== payload.trackIds.length) return false;
  if (payload.trackProcessing.some((item, index) => !hasExactKeys(item, ["trackId", "enhancement", "leveling", "compression"]) ||
      item.trackId !== payload.trackIds[index] || !["off", "gentle"].includes(item.enhancement) ||
      !["off", "on"].includes(item.leveling) || !["off", "light", "medium", "strong"].includes(item.compression))) return false;
  const ids = new Set(), exactTime = value => Number.isFinite(value) && value >= 0 && value <= 604800 && Math.round(value * 1e6) / 1e6 === value;
  if (!Array.isArray(payload.globalCuts) || payload.globalCuts.length > 10000 || !Array.isArray(payload.trackSilenceRegions) || payload.trackSilenceRegions.length > 10000) return false;
  let previousEnd = -1;
  for (const region of payload.globalCuts) {
    if (!hasExactKeys(region, ["regionId", "startSeconds", "endSeconds"]) || !isUuid(region.regionId) || ids.has(region.regionId) ||
        !exactTime(region.startSeconds) || !exactTime(region.endSeconds) || region.endSeconds <= region.startSeconds || region.startSeconds <= previousEnd) return false;
    ids.add(region.regionId); previousEnd = region.endSeconds;
  }
  let previousTrack = -1;
  const ends = new Map();
  for (const region of payload.trackSilenceRegions) {
    const trackIndex = payload.trackIds.indexOf(region?.trackId);
    if (!hasExactKeys(region, ["regionId", "trackId", "startSeconds", "endSeconds"]) || !isUuid(region.regionId) || ids.has(region.regionId) ||
        trackIndex < 0 || trackIndex < previousTrack || !exactTime(region.startSeconds) || !exactTime(region.endSeconds) ||
        region.endSeconds <= region.startSeconds || region.startSeconds <= (ends.get(region.trackId) ?? -1)) return false;
    ids.add(region.regionId); previousTrack = trackIndex; ends.set(region.trackId, region.endSeconds);
  }
  return true;
}

export async function verifySpeakerProjectState(value, signal) {
  const keys = ["schemaVersion", "sessionId", "workflow", "draftRevision", "sourceSessionRevision", "savedAt", "payloadSchema", "payload", "sources", "stateFingerprint"];
  if (!hasExactKeys(value, keys) || value.schemaVersion !== 1 || !isUuid(value.sessionId) || value.workflow !== "speaker" ||
      !Number.isSafeInteger(value.draftRevision) || value.draftRevision < 1 || !Number.isSafeInteger(value.sourceSessionRevision) ||
      value.sourceSessionRevision < 1 || !isIsoTimestamp(value.savedAt) || value.payloadSchema !== "speaker/v1" ||
      !SHA256_PATTERN.test(value.stateFingerprint) || !Array.isArray(value.sources) || !value.sources.length || value.sources.length > 32) {
    throw new Error("Состояние проекта «Спикерская» повреждено или имеет неизвестную версию.");
  }
  const payload = value.payload;
  const seenOrdinals = new Set(), seenBlobs = new Set();
  for (const [index, source] of value.sources.entries()) {
    if (!hasExactKeys(source, ["trackId", "blobId", "ordinal", "originalName", "mediaType", "sizeBytes", "sha256"]) ||
        !isUuid(source.trackId) || !isUuid(source.blobId) || source.trackId !== payload.trackIds[index] ||
        !Number.isSafeInteger(source.ordinal) || source.ordinal < 1 || source.ordinal > value.sources.length || seenOrdinals.has(source.ordinal) || seenBlobs.has(source.blobId) ||
        source.originalName !== normalizeAudioFilename(source.originalName) || !Object.values(MEDIA_TYPES).includes(source.mediaType) ||
        !Number.isSafeInteger(source.sizeBytes) || source.sizeBytes < 1 || !SHA256_PATTERN.test(source.sha256)) {
      throw new Error("Происхождение исходников состояния проекта не подтверждено.");
    }
    try { if (normalizedMediaType(source.originalName, source.mediaType) !== source.mediaType) throw new Error(); }
    catch { throw new Error("Происхождение исходников состояния проекта не подтверждено."); }
    seenOrdinals.add(source.ordinal); seenBlobs.add(source.blobId);
  }
  if (!validateSpeakerStatePayload(payload, value.sources.map(source => source.trackId))) throw new Error("Состояние проекта «Спикерская» повреждено.");
  const expected = await sha256Hex(JSON.stringify(projectStateIdentity(value)), signal);
  if (expected !== value.stateFingerprint) throw new Error("Fingerprint состояния проекта не совпадает.");
  return structuredClone(value);
}

export function validateSpeakerProjectHistory(value, sessionId) {
  if (!hasExactKeys(value, ["schemaVersion", "sessionId", "workflow", "currentDraftRevision", "lifecycle", "sourceState", "states"]) ||
      value.schemaVersion !== 1 || value.sessionId !== sessionId || !isUuid(sessionId) || value.workflow !== "speaker" ||
      !(value.currentDraftRevision === null || (Number.isSafeInteger(value.currentDraftRevision) && value.currentDraftRevision > 0)) ||
      !["incoming", "archived"].includes(value.lifecycle) || !["available", "deleted"].includes(value.sourceState) || !Array.isArray(value.states)) {
    throw new Error("История проекта «Спикерская» повреждена.");
  }
  let previous = Number.MAX_SAFE_INTEGER, currentCount = 0;
  for (const item of value.states) {
    if (!hasExactKeys(item, ["draftRevision", "savedAt", "current", "canonicalSourcesAvailable", "canonicalEditingAvailable", "stateFingerprint", "finalVersions"]) ||
        !Number.isSafeInteger(item.draftRevision) || item.draftRevision < 1 || item.draftRevision >= previous || !isIsoTimestamp(item.savedAt) ||
        typeof item.current !== "boolean" || typeof item.canonicalSourcesAvailable !== "boolean" || typeof item.canonicalEditingAvailable !== "boolean" ||
        item.canonicalSourcesAvailable !== (value.sourceState === "available") || item.canonicalEditingAvailable !== (value.sourceState === "available" && value.lifecycle === "incoming") ||
        !SHA256_PATTERN.test(item.stateFingerprint) || !Array.isArray(item.finalVersions)) throw new Error("История проекта «Спикерская» повреждена.");
    if (item.current) { currentCount++; if (item.draftRevision !== value.currentDraftRevision) throw new Error("Текущее состояние проекта не подтверждено."); }
    let priorVersion = Number.MAX_SAFE_INTEGER;
    for (const linked of item.finalVersions) {
      if (!hasExactKeys(linked, ["outputId", "version", "createdAt"]) || !isUuid(linked.outputId) || !Number.isSafeInteger(linked.version) ||
          linked.version < 1 || linked.version >= priorVersion || !isIsoTimestamp(linked.createdAt)) throw new Error("Связь финальной версии с проектом повреждена.");
      priorVersion = linked.version;
    }
    previous = item.draftRevision;
  }
  if (currentCount > 1 || (value.states.some(item => item.draftRevision === value.currentDraftRevision) && currentCount !== 1)) {
    throw new Error("Текущее состояние проекта неоднозначно.");
  }
  return structuredClone(value);
}

async function hashLocalFile(file, signal) {
  const hasher = new Sha256();
  for (let offset = 0; offset < file.size; offset += DEFAULT_AUDIO_PART_BYTES) {
    throwIfAborted(signal);
    hasher.update(new Uint8Array(await file.slice(offset, Math.min(file.size, offset + DEFAULT_AUDIO_PART_BYTES)).arrayBuffer()));
  }
  return hasher.digestHex();
}

// Filename is presentation only. A complete set is matched exclusively by byte size and SHA-256.
export async function verifyLocalSourceAttachment(files, sources, signal) {
  const selected = Array.from(files || []);
  if (!Array.isArray(sources) || !sources.length || selected.length !== sources.length) {
    throw new Error("Подключите полный набор исходных дорожек.");
  }
  const expected = new Map();
  for (const source of sources) {
    const identity = `${source.sizeBytes}:${source.sha256}`;
    if (expected.has(identity)) throw new Error("Набор содержит неоднозначные одинаковые дорожки; соответствие нельзя доказать.");
    expected.set(identity, source);
  }
  const matched = new Map();
  for (const file of selected) {
    if (!file || !Number.isSafeInteger(file.size) || file.size < 1) throw new Error("Подключённый файл повреждён.");
    const identity = `${file.size}:${await hashLocalFile(file, signal)}`;
    if (!expected.has(identity) || matched.has(identity)) throw new Error("Подключённые дорожки не совпадают с сохранённым происхождением.");
    matched.set(identity, file);
  }
  if (matched.size !== expected.size) throw new Error("Подключите полный точный набор исходных дорожек.");
  return [...sources].sort((a, b) => a.ordinal - b.ordinal).map((source) => matched.get(`${source.sizeBytes}:${source.sha256}`));
}

async function stableUuid(idempotencyKey, label, signal) {
  const hex = (await sha256Hex(`audio-archive\u0000${idempotencyKey}\u0000${label}`, signal)).slice(0, 32).split("");
  hex[12] = "8";
  hex[16] = ["8", "9", "a", "b"][Number.parseInt(hex[16], 16) & 3];
  return `${hex.slice(0, 8).join("")}-${hex.slice(8, 12).join("")}-${hex.slice(12, 16).join("")}-${hex.slice(16, 20).join("")}-${hex.slice(20).join("")}`;
}

export function assetName(blobId, partNumber) {
  if (!isUuid(blobId) || !Number.isSafeInteger(partNumber) || partNumber < 1 || partNumber > 9999) {
    throw new Error("Некорректный идентификатор части.");
  }
  return `blob-${blobId.toLowerCase()}-part-${String(partNumber).padStart(4, "0")}.bin`;
}

export async function createIngestionPlan(files, partSize = DEFAULT_AUDIO_PART_BYTES, { idempotencyKey = crypto.randomUUID(), signal } = {}) {
  throwIfAborted(signal);
  const selected = Array.from(files || []);
  if (!selected.length) throw new Error("Выберите хотя бы одну аудиодорожку.");
  if (!Number.isSafeInteger(partSize) || partSize < 1 || partSize > MAX_AUDIO_PART_BYTES) {
    throw new Error("Некорректный размер части аудиофайла.");
  }
  if (selected.some((file) => !file || !Number.isSafeInteger(file.size) || file.size <= 0)) {
    throw new Error("Пустые аудиофайлы загружать нельзя.");
  }
  const totalBytes = selected.reduce((sum, file) => sum + file.size, 0);
  if (totalBytes <= 0 || totalBytes > MAX_AUDIO_SESSION_BYTES) throw new Error("Общий размер файлов превышает 500 МБ.");
  const tracks = [];
  for (const [trackIndex, file] of selected.entries()) {
    throwIfAborted(signal);
    const blobId = await stableUuid(idempotencyKey, `blob:${trackIndex + 1}`, signal);
    const trackId = await stableUuid(idempotencyKey, `track:${trackIndex + 1}`, signal);
    const logicalHasher = new Sha256();
    const parts = [];
    for (let offset = 0, partNumber = 1; offset < file.size; offset += partSize, partNumber++) {
      throwIfAborted(signal);
      const blob = file.slice(offset, Math.min(file.size, offset + partSize));
      throwIfAborted(signal);
      const bytes = new Uint8Array(await blob.arrayBuffer());
      throwIfAborted(signal);
      logicalHasher.update(bytes);
      parts.push({
        partNumber,
        sizeBytes: bytes.byteLength,
        sha256: await sha256Hex(bytes, signal),
        assetName: assetName(blobId, partNumber),
        blob
      });
      throwIfAborted(signal);
    }
    tracks.push({
      trackId,
      blobId,
      ordinal: trackIndex + 1,
      originalName: normalizeAudioFilename(file.name),
      mediaType: normalizedMediaType(file.name, file.type),
      sizeBytes: file.size,
      sha256: logicalHasher.digestHex(),
      parts
    });
  }
  return { totalBytes, tracks };
}

export function serializeIngestionPlan(plan) {
  return {
    totalBytes: plan.totalBytes,
    tracks: plan.tracks.map((track) => ({
      ...track,
      parts: track.parts.map(({ blob: _blob, ...part }) => part)
    }))
  };
}

export async function createAnnouncementPublicationPlan(blob, recipe, partSize = DEFAULT_AUDIO_PART_BYTES,
  { idempotencyKey = crypto.randomUUID(), processorVersion = "s07-v1", signal } = {}) {
  throwIfAborted(signal);
  if (!(blob instanceof Blob) || !Number.isSafeInteger(blob.size) || blob.size < 1 || blob.size > MAX_AUDIO_SESSION_BYTES) {
    throw new Error("Результат обработки пуст или превышает 500 МБ.");
  }
  if (!Number.isSafeInteger(partSize) || partSize < 1 || partSize > MAX_AUDIO_PART_BYTES) throw new Error("Некорректный размер части результата.");
  const outputId = await stableUuid(idempotencyKey, "announcement-output", signal);
  const blobId = await stableUuid(idempotencyKey, "announcement-blob", signal);
  const logicalHasher = new Sha256();
  const parts = [];
  for (let offset = 0, partNumber = 1; offset < blob.size; offset += partSize, partNumber++) {
    const partBlob = blob.slice(offset, Math.min(blob.size, offset + partSize));
    const bytes = new Uint8Array(await partBlob.arrayBuffer());
    throwIfAborted(signal);
    logicalHasher.update(bytes);
    parts.push({ partNumber, sizeBytes: bytes.byteLength, sha256: await sha256Hex(bytes, signal),
      assetName: assetName(blobId, partNumber), blob: partBlob });
  }
  const sha256 = logicalHasher.digestHex();
  return {
    outputId, blobId, processorVersion, sizeBytes: blob.size, sha256, parts,
    recipe: { ...structuredClone(recipe), result: { ...structuredClone(recipe.result), sizeBytes: blob.size, sha256 } }
  };
}

export async function createSpeakerSavePlan(blob, recipe, partSize = DEFAULT_AUDIO_PART_BYTES,
  { idempotencyKey = crypto.randomUUID(), signal } = {}) {
  throwIfAborted(signal);
  if (!(blob instanceof Blob) || blob.type !== "audio/mpeg" || !Number.isSafeInteger(blob.size) || blob.size < 1 || blob.size > MAX_AUDIO_SESSION_BYTES) {
    throw new Error("Локальный результат Спикерской пуст, повреждён или превышает 500 МБ.");
  }
  if (!Number.isSafeInteger(partSize) || partSize < 1 || partSize > MAX_AUDIO_PART_BYTES) throw new Error("Некорректный размер части результата.");
  const outputId = await stableUuid(idempotencyKey, "speaker-output", signal);
  const blobId = await stableUuid(idempotencyKey, "speaker-blob", signal);
  const logicalHasher = new Sha256();
  const parts = [];
  for (let offset = 0, partNumber = 1; offset < blob.size; offset += partSize, partNumber++) {
    const partBlob = blob.slice(offset, Math.min(blob.size, offset + partSize), "application/octet-stream");
    const bytes = new Uint8Array(await partBlob.arrayBuffer());
    throwIfAborted(signal);
    logicalHasher.update(bytes);
    parts.push({ partNumber, sizeBytes: bytes.byteLength, sha256: await sha256Hex(bytes, signal),
      assetName: assetName(blobId, partNumber), blob: partBlob });
  }
  const sha256 = logicalHasher.digestHex();
  if (recipe?.result?.sizeBytes !== blob.size || recipe?.result?.sha256 !== sha256) {
    throw new Error("Локальные байты не совпадают с зафиксированным результатом Спикерской.");
  }
  return { outputId, blobId, processorVersion: "speaker-editor-v1", sizeBytes: blob.size, sha256, parts, recipe: structuredClone(recipe) };
}

export function serializeAnnouncementPublicationPlan(plan) {
  return { ...plan, parts: plan.parts.map(({ blob: _blob, ...part }) => part) };
}

export const serializeSpeakerSavePlan = serializeAnnouncementPublicationPlan;

function isIsoTimestamp(value) {
  return typeof value === "string" && !Number.isNaN(Date.parse(value)) && /^\d{4}-\d{2}-\d{2}T/.test(value);
}

export function isReleaseAssetUrl(value, sessionId, expectedAssetName) {
  if (typeof value !== "string" || !isUuid(sessionId)) return false;
  try {
    const parsed = new URL(value);
    const expectedPath = `/meser-recovery/audio-archive/releases/download/audio-session-${sessionId}/${expectedAssetName}`;
    return parsed.protocol === "https:" && parsed.hostname === "github.com" && !parsed.username && !parsed.password &&
      parsed.pathname === expectedPath && !parsed.search && !parsed.hash;
  } catch {
    return false;
  }
}

export function validateTrackManifest(track, sessionId) {
  if (!hasExactKeys(track, ["trackId", "blobId", "ordinal", "originalName", "mediaType", "sizeBytes", "sha256", "parts"]) ||
      !isUuid(track.trackId) || !isUuid(track.blobId) || !Number.isSafeInteger(track.ordinal) || track.ordinal < 1 ||
      track.originalName !== normalizeAudioFilename(track.originalName) ||
      !Object.values(MEDIA_TYPES).includes(track.mediaType) || !Number.isSafeInteger(track.sizeBytes) || track.sizeBytes <= 0 ||
      !SHA256_PATTERN.test(track.sha256) || !Array.isArray(track.parts) || !track.parts.length) return false;
  try {
    if (normalizedMediaType(track.originalName, track.mediaType) !== track.mediaType) return false;
  } catch { return false; }
  let total = 0;
  for (const [index, part] of track.parts.entries()) {
    const expectedName = assetName(track.blobId, index + 1);
    if (!hasExactKeys(part, ["partNumber", "sizeBytes", "sha256", "assetName", "assetId", "downloadUrl"]) ||
        part.partNumber !== index + 1 || part.assetName !== expectedName ||
        !Number.isSafeInteger(part.assetId) || part.assetId <= 0 || !Number.isSafeInteger(part.sizeBytes) || part.sizeBytes <= 0 ||
        part.sizeBytes > MAX_AUDIO_PART_BYTES || !SHA256_PATTERN.test(part.sha256) ||
        !isReleaseAssetUrl(part.downloadUrl, sessionId, expectedName)) return false;
    total += part.sizeBytes;
  }
  return total === track.sizeBytes;
}

function validateWorkflow(value, sessionId) {
  if (!hasExactKeys(value, ["workflow", "status", "currentDraft", "outputs", "deletedVersions", "nextVersion"]) ||
      !WORKFLOWS.has(value.workflow) || !WORKFLOW_STATES.has(value.status) ||
      !Number.isSafeInteger(value.nextVersion) || value.nextVersion < 1 || !Array.isArray(value.outputs) || !Array.isArray(value.deletedVersions)) return false;
  if (!(value.currentDraft === null || (hasExactKeys(value.currentDraft, ["path", "revision"]) &&
      value.currentDraft.path === `drafts/${sessionId}/${value.workflow}.json` && Number.isSafeInteger(value.currentDraft.revision) && value.currentDraft.revision > 0))) return false;
  const versions = [...value.outputs.map((output) => output.version), ...value.deletedVersions];
  if (versions.some((version) => !Number.isSafeInteger(version) || version < 1 || version >= value.nextVersion) || new Set(versions).size !== versions.length) return false;
  return value.outputs.every((output) => hasExactKeys(output, ["outputId", "version", "sessionId", "createdAt", "blobId", "sizeBytes", "sha256", "parts", "recipeSnapshotRef", "processorVersion"]) &&
    isUuid(output.outputId) && isUuid(output.blobId) &&
    Number.isSafeInteger(output.version) && output.version > 0 && output.sessionId === sessionId && isIsoTimestamp(output.createdAt) &&
    Number.isSafeInteger(output.sizeBytes) && output.sizeBytes > 0 && SHA256_PATTERN.test(output.sha256) && Array.isArray(output.parts) && output.parts.length > 0 &&
    output.parts.every((part, index) => hasExactKeys(part, ["partNumber", "sizeBytes", "sha256", "assetName", "assetId", "downloadUrl"]) &&
      part.partNumber === index + 1 && part.assetName === assetName(output.blobId, index + 1) &&
      Number.isSafeInteger(part.assetId) && part.assetId > 0 && Number.isSafeInteger(part.sizeBytes) && part.sizeBytes > 0 &&
      part.sizeBytes <= MAX_AUDIO_PART_BYTES && SHA256_PATTERN.test(part.sha256) && isReleaseAssetUrl(part.downloadUrl, sessionId, part.assetName)) &&
    output.parts.reduce((sum, part) => sum + part.sizeBytes, 0) === output.sizeBytes &&
    typeof output.recipeSnapshotRef === "string" && output.recipeSnapshotRef.length > 0 &&
    typeof output.processorVersion === "string" && output.processorVersion.length > 0);
}

export function validateAnnouncementOutput(output, recipe, sessionId) {
  const workflow = { workflow: "announcement", status: "result_ready", currentDraft: null,
    outputs: [output], deletedVersions: [], nextVersion: output?.version + 1 };
  if (!isUuid(sessionId) || !validateWorkflow(workflow, sessionId) ||
      output.recipeSnapshotRef !== `recipes/${sessionId}/announcement/${output.outputId}.json` ||
      !hasExactKeys(recipe, ["schemaVersion", "workflow", "sessionId", "outputId", "version", "processorVersion", "createdAt", "sourceSessionRevision", "sources", "draft", "processing", "result"]) ||
      recipe.schemaVersion !== 1 || recipe.workflow !== "announcement" || recipe.sessionId !== sessionId ||
      recipe.outputId !== output.outputId || recipe.version !== output.version || recipe.processorVersion !== output.processorVersion ||
      !hasExactKeys(recipe.result, ["mediaType", "presentationFilename", "sizeBytes", "sha256", "originalDurationSeconds", "resultDurationSeconds", "removedDurationSeconds", "pauseCount"]) ||
      recipe.result.sizeBytes !== output.sizeBytes || recipe.result.sha256 !== output.sha256 ||
      !Object.values(MEDIA_TYPES).includes(recipe.result.mediaType) || recipe.result.presentationFilename !== normalizeAudioFilename(recipe.result.presentationFilename) ||
      !Number.isSafeInteger(recipe.sourceSessionRevision) || recipe.sourceSessionRevision < 1 || !isIsoTimestamp(recipe.createdAt) ||
      !/^s07(?:[-.][a-z0-9]+)*$/i.test(recipe.processorVersion) ||
      !Array.isArray(recipe.sources) || !recipe.sources.length || recipe.sources.length > 32 ||
      !hasExactKeys(recipe.draft, ["revision", "payloadSchema", "payload"]) || !Number.isSafeInteger(recipe.draft.revision) || recipe.draft.revision < 0 ||
      recipe.draft.payloadSchema !== "announcement/v1" || !hasExactKeys(recipe.draft.payload, ["trackIds"]) ||
      !Array.isArray(recipe.draft.payload.trackIds) || !recipe.draft.payload.trackIds.length ||
      !hasExactKeys(recipe.processing, ["mode", "silenceThresholdDb", "minimumSilenceSeconds", "retainedSilenceSeconds", "detectedIntervals", "removalRanges", "mix", "limiter", "codec"])) return false;
  const sourceIds = [];
  for (const [index, source] of recipe.sources.entries()) {
    if (!hasExactKeys(source, ["trackId", "blobId", "ordinal", "sizeBytes", "sha256", "mediaType"]) ||
        !isUuid(source.trackId) || !isUuid(source.blobId) || source.ordinal !== index + 1 ||
        !Number.isSafeInteger(source.sizeBytes) || source.sizeBytes < 1 || !SHA256_PATTERN.test(source.sha256) ||
        !Object.values(MEDIA_TYPES).includes(source.mediaType)) return false;
    sourceIds.push(source.trackId);
  }
  if (new Set(sourceIds).size !== sourceIds.length || new Set(recipe.sources.map((source) => source.blobId)).size !== recipe.sources.length ||
      JSON.stringify(sourceIds) !== JSON.stringify(recipe.draft.payload.trackIds)) return false;
  const processing = recipe.processing;
  const intervalsValid = (intervals) => Array.isArray(intervals) && intervals.length <= 10000 && intervals.every((interval, index) =>
    Array.isArray(interval) && interval.length === 2 && Number.isFinite(interval[0]) && Number.isFinite(interval[1]) &&
    interval[0] >= 0 && interval[1] > interval[0] && (!index || interval[0] >= intervals[index - 1][1]));
  if (![-45].includes(processing.silenceThresholdDb) || processing.minimumSilenceSeconds !== 2 || processing.retainedSilenceSeconds !== 0.35 ||
      !intervalsValid(processing.detectedIntervals) || !intervalsValid(processing.removalRanges) ||
      !["passthrough", "processed_single", "mixed_multi"].includes(processing.mode) ||
      (processing.mode === "mixed_multi") !== (recipe.sources.length > 1)) return false;
  if (processing.mode === "passthrough") {
    if (processing.removalRanges.length || processing.mix !== null || processing.limiter !== null || processing.codec !== null ||
        output.sizeBytes !== recipe.sources[0].sizeBytes || output.sha256 !== recipe.sources[0].sha256 || recipe.result.mediaType !== recipe.sources[0].mediaType) return false;
  } else if (!hasExactKeys(processing.codec, ["name", "bitrate"]) || processing.codec.name !== "libmp3lame" || processing.codec.bitrate !== "128k" ||
      recipe.result.mediaType !== "audio/mpeg" || (processing.mode === "processed_single" && (processing.mix !== null || processing.limiter !== null)) ||
      (processing.mode === "mixed_multi" && (processing.mix !== "amix=normalize=0" || processing.limiter !== "alimiter=limit=0.95:level=0:latency=1"))) return false;
  return true;
}

export async function reconstructAnnouncementOutput(metadata, fetchImpl = fetch) {
  const { output, recipe } = metadata || {};
  if (!validateAnnouncementOutput(output, recipe, output?.sessionId)) throw new Error("Данные сохранённого результата «Анонс-мейкер» повреждены.");
  const chunks = [];
  const logicalHasher = new Sha256();
  let totalBytes = 0;
  for (const [index, part] of output.parts.entries()) {
    if (part.partNumber !== index + 1) throw new Error("Нарушен порядок частей результата.");
    const response = await fetchImpl(part.downloadUrl, { cache: "no-store" });
    if (!response.ok) throw Object.assign(new Error("Не удалось загрузить часть результата."), { status: response.status });
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.byteLength !== part.sizeBytes || await sha256Hex(bytes) !== part.sha256) throw new Error("Проверка целостности части результата не пройдена.");
    chunks.push(bytes); totalBytes += bytes.byteLength; logicalHasher.update(bytes);
  }
  if (totalBytes !== output.sizeBytes || logicalHasher.digestHex() !== output.sha256) throw new Error("Проверка целостности результата не пройдена.");
  return new File(chunks, recipe.result.presentationFilename, { type: recipe.result.mediaType, lastModified: 0 });
}

export function validateSpeakerOutput(output, recipe, sessionId) {
  const workflow = { workflow: "speaker", status: "result_ready", currentDraft: null,
    outputs: [output], deletedVersions: [], nextVersion: (output?.version || 0) + 1 };
  const recipeKeys = recipe?.schemaVersion === 2 ?
    ["schemaVersion", "workflow", "sessionId", "outputId", "version", "processorVersion", "createdAt", "renderedAt", "sourceSessionRevision", "draft", "sources", "editState", "renderer", "candidateFingerprint", "result", "projectState"] :
    ["schemaVersion", "workflow", "sessionId", "outputId", "version", "processorVersion", "createdAt", "renderedAt", "sourceSessionRevision", "draft", "sources", "editState", "renderer", "candidateFingerprint", "result"];
  if (!isUuid(sessionId) || !validateWorkflow(workflow, sessionId) ||
      output.recipeSnapshotRef !== `recipes/${sessionId}/speaker/${output.outputId}.json` ||
      !hasExactKeys(recipe, recipeKeys) || ![1, 2].includes(recipe.schemaVersion) || recipe.workflow !== "speaker" || recipe.sessionId !== sessionId || recipe.outputId !== output.outputId ||
      recipe.version !== output.version || recipe.processorVersion !== "speaker-editor-v1" || output.processorVersion !== "speaker-editor-v1" ||
      !isIsoTimestamp(recipe.createdAt) || !isIsoTimestamp(recipe.renderedAt) || !Number.isSafeInteger(recipe.sourceSessionRevision) || recipe.sourceSessionRevision < 1 ||
      !SHA256_PATTERN.test(recipe.candidateFingerprint) || !hasExactKeys(recipe.draft, ["revision", "payloadSchema", "payload"]) ||
      !Number.isSafeInteger(recipe.draft.revision) || recipe.draft.revision < 1 || recipe.draft.payloadSchema !== "speaker/v1" ||
      !Array.isArray(recipe.sources) || !recipe.sources.length || !hasExactKeys(recipe.editState, ["orderedTrackIds", "includedTrackIds", "excludedTrackIds", "globalCuts", "trackSilenceRegions", "trackProcessing"]) ||
      !hasExactKeys(recipe.renderer, ["sampleRate", "enhancement", "loudnorm", "compression", "mix", "limiter", "codec"]) || recipe.renderer.sampleRate !== 48000 ||
      !hasExactKeys(recipe.result, ["mediaType", "presentationFilename", "sizeBytes", "sha256", "originalDurationSeconds", "resultDurationSeconds", "globallyRemovedDurationSeconds"]) ||
      recipe.result.mediaType !== "audio/mpeg" || recipe.result.presentationFilename !== normalizeAudioFilename(recipe.result.presentationFilename) ||
      recipe.result.sizeBytes !== output.sizeBytes || recipe.result.sha256 !== output.sha256) return false;
  if (recipe.schemaVersion === 2 && (!hasExactKeys(recipe.projectState, ["sessionId", "draftRevision", "stateFingerprint"]) ||
      recipe.projectState.sessionId !== sessionId || recipe.projectState.draftRevision !== recipe.draft.revision ||
      !SHA256_PATTERN.test(recipe.projectState.stateFingerprint))) return false;
  const payload = recipe.draft.payload;
  if (!hasExactKeys(payload, ["trackIds", "excludedTrackIds", "globalCuts", "trackSilenceRegions", "trackProcessing"]) ||
      JSON.stringify(recipe.editState.orderedTrackIds) !== JSON.stringify(payload.trackIds) ||
      JSON.stringify(recipe.editState.excludedTrackIds) !== JSON.stringify(payload.excludedTrackIds) ||
      JSON.stringify(recipe.editState.globalCuts) !== JSON.stringify(payload.globalCuts) ||
      JSON.stringify(recipe.editState.trackSilenceRegions) !== JSON.stringify(payload.trackSilenceRegions) ||
      JSON.stringify(recipe.editState.trackProcessing) !== JSON.stringify(payload.trackProcessing) ||
      JSON.stringify(recipe.editState.includedTrackIds) !== JSON.stringify(payload.trackIds.filter((id) => !payload.excludedTrackIds.includes(id)))) return false;
  const ordinals = recipe.sources.map((source) => source?.ordinal);
  return new Set(ordinals).size === recipe.sources.length && recipe.sources.every((source, index) =>
    hasExactKeys(source, ["trackId", "blobId", "ordinal", "originalFilename", "mediaType", "sizeBytes", "sha256"]) &&
    source.trackId === payload.trackIds[index] && isUuid(source.trackId) && isUuid(source.blobId) &&
    Number.isSafeInteger(source.ordinal) && source.ordinal >= 1 && source.ordinal <= recipe.sources.length &&
    source.originalFilename === normalizeAudioFilename(source.originalFilename) && Object.values(MEDIA_TYPES).includes(source.mediaType) &&
    Number.isSafeInteger(source.sizeBytes) && source.sizeBytes > 0 && SHA256_PATTERN.test(source.sha256));
}

export async function reconstructSpeakerOutput(metadata, fetchImpl = fetch) {
  const { output, recipe } = metadata || {};
  if (!validateSpeakerOutput(output, recipe, output?.sessionId)) throw new Error("Данные сохранённого результата «Спикерская» повреждены.");
  const chunks = [];
  const logicalHasher = new Sha256();
  let totalBytes = 0;
  for (const [index, part] of output.parts.entries()) {
    if (part.partNumber !== index + 1) throw new Error("Нарушен порядок частей результата Спикерской.");
    const response = await fetchImpl(part.downloadUrl, { cache: "no-store" });
    if (!response.ok) throw Object.assign(new Error("Не удалось загрузить часть результата Спикерской."), { status: response.status });
    const bytes = new Uint8Array(await response.arrayBuffer());
    if (bytes.byteLength !== part.sizeBytes || await sha256Hex(bytes) !== part.sha256) throw new Error("Проверка целостности части результата Спикерской не пройдена.");
    chunks.push(bytes); totalBytes += bytes.byteLength; logicalHasher.update(bytes);
  }
  if (totalBytes !== output.sizeBytes || logicalHasher.digestHex() !== output.sha256) throw new Error("Проверка целостности результата Спикерской не пройдена.");
  return new File(chunks, recipe.result.presentationFilename, { type: "audio/mpeg", lastModified: 0 });
}

export function validateSessionManifest(session) {
  if (!hasExactKeys(session, ["schemaVersion", "revision", "id", "title", "recordedAt", "createdAt", "updatedAt", "origin", "storage", "lifecycle", "sourceState", "sourceTracks", "deletedSources", "workflows", "relations", "transaction"]) ||
      session.schemaVersion !== AUDIO_ARCHIVE_SCHEMA_VERSION ||
      !Number.isSafeInteger(session.revision) || session.revision < 1 || !isUuid(session.id) ||
      typeof session.title !== "string" || !session.title.trim() || session.title.length > 200 ||
      !(session.recordedAt === null || isIsoTimestamp(session.recordedAt)) || !isIsoTimestamp(session.createdAt) || !isIsoTimestamp(session.updatedAt) ||
      !hasExactKeys(session.origin, ["kind", "externalId"]) || !["manual", "device", "zoom_webhook"].includes(session.origin.kind) ||
      !(session.origin.externalId === null || typeof session.origin.externalId === "string") ||
      !hasExactKeys(session.storage, ["releaseId", "tag"]) || !Number.isSafeInteger(session.storage.releaseId) || session.storage.releaseId <= 0 ||
      session.storage.tag !== `audio-session-${session.id}` || !hasExactKeys(session.lifecycle, ["state"]) || !["incoming", "archived"].includes(session.lifecycle.state) ||
      !["available", "deleted"].includes(session.sourceState) || !Array.isArray(session.sourceTracks) || !hasExactKeys(session.workflows, ["announcement", "speaker"]) ||
      !hasExactKeys(session.relations, ["supersedesSessionId", "supersededBySessionId"]) ||
      !hasExactKeys(session.transaction, ["state", "id"]) || session.transaction.state !== "finalized" || !isUuid(session.transaction.id)) return false;
  if ((session.sourceState === "available") !== (session.sourceTracks.length > 0)) return false;
  if (session.sourceState === "available" && session.deletedSources !== null) return false;
  if (session.sourceState === "deleted") {
    if (!hasExactKeys(session.deletedSources, ["deletedAt", "tracks"]) || !isIsoTimestamp(session.deletedSources.deletedAt) ||
        !Array.isArray(session.deletedSources.tracks) || !session.deletedSources.tracks.length ||
        !session.deletedSources.tracks.every((track) => hasExactKeys(track, ["trackId", "blobId", "sizeBytes", "sha256"]) &&
          isUuid(track.trackId) && isUuid(track.blobId) && Number.isSafeInteger(track.sizeBytes) && track.sizeBytes > 0 && SHA256_PATTERN.test(track.sha256))) return false;
    const deletedTrackIds = session.deletedSources.tracks.map((track) => track.trackId);
    const deletedBlobIds = session.deletedSources.tracks.map((track) => track.blobId);
    if (new Set(deletedTrackIds).size !== deletedTrackIds.length || new Set(deletedBlobIds).size !== deletedBlobIds.length ||
        session.deletedSources.tracks.reduce((sum, track) => sum + track.sizeBytes, 0) > MAX_AUDIO_SESSION_BYTES) return false;
  }
  if (session.sourceTracks.reduce((sum, track) => sum + (track?.sizeBytes || 0), 0) > MAX_AUDIO_SESSION_BYTES) return false;
  if (!session.sourceTracks.every((track, index) => track.ordinal === index + 1 && validateTrackManifest(track, session.id))) return false;
  const trackIds = new Set();
  const blobIds = new Set();
  const partKeys = new Set();
  const partAssetIds = new Set();
  const partAssetNames = new Set();
  const partUrls = new Set();
  for (const track of session.sourceTracks) {
    if (trackIds.has(track.trackId) || blobIds.has(track.blobId)) return false;
    trackIds.add(track.trackId);
    blobIds.add(track.blobId);
    for (const part of track.parts) {
      const partKey = `${track.blobId}:${part.partNumber}`;
      if (partKeys.has(partKey) || partAssetIds.has(part.assetId) || partAssetNames.has(part.assetName) || partUrls.has(part.downloadUrl)) return false;
      partKeys.add(partKey);
      partAssetIds.add(part.assetId);
      partAssetNames.add(part.assetName);
      partUrls.add(part.downloadUrl);
    }
  }
  for (const workflow of WORKFLOWS) {
    if (!session.workflows[workflow] || session.workflows[workflow].workflow !== workflow ||
        !validateWorkflow(session.workflows[workflow], session.id)) return false;
  }
  return ["supersedesSessionId", "supersededBySessionId"].every((key) =>
    session.relations[key] === null || isUuid(session.relations[key]));
}

export async function reconstructTrack(track, sessionId, fetchImpl = fetch, { signal, onProgress } = {}) {
  throwIfAborted(signal);
  if (!validateTrackManifest(track, sessionId)) throw new Error("Манифест дорожки повреждён.");
  const ordered = [...track.parts].sort((left, right) => left.partNumber - right.partNumber);
  const chunks = [];
  const logicalHasher = new Sha256();
  let totalBytes = 0;
  for (const [index, part] of ordered.entries()) {
    throwIfAborted(signal);
    if (part.partNumber !== index + 1) throw new Error("Нарушен порядок частей аудиофайла.");
    const response = await fetchImpl(part.downloadUrl, { cache: "no-store", signal });
    if (!response.ok) throw Object.assign(new Error("Не удалось загрузить часть аудиофайла."), { status: response.status });
    const bytes = new Uint8Array(await response.arrayBuffer());
    throwIfAborted(signal);
    if (bytes.byteLength !== part.sizeBytes || await sha256Hex(bytes, signal) !== part.sha256) {
      throw new Error("Проверка целостности части аудиофайла не пройдена.");
    }
    totalBytes += bytes.byteLength;
    logicalHasher.update(bytes);
    chunks.push(bytes);
    onProgress?.({ verifiedBytes: bytes.byteLength, partNumber: part.partNumber, partCount: ordered.length, track });
  }
  throwIfAborted(signal);
  if (totalBytes !== track.sizeBytes || logicalHasher.digestHex() !== track.sha256) {
    throw new Error("Проверка целостности аудиодорожки не пройдена.");
  }
  return new File(chunks, track.originalName, { type: track.mediaType, lastModified: 0 });
}

export async function reconstructSessionTracks(session, fetchImpl = fetch, { signal, onProgress } = {}) {
  throwIfAborted(signal);
  if (!validateSessionManifest(session)) throw new Error("Данные архивной записи повреждены.");
  if (session.sourceState !== "available") throw new Error("Исходники этой записи были удалены.");
  const ordered = [...(session.sourceTracks || [])].sort((left, right) => left.ordinal - right.ordinal);
  const files = [];
  const totalBytes = ordered.reduce((sum, track) => sum + track.sizeBytes, 0);
  const totalParts = ordered.reduce((sum, track) => sum + track.parts.length, 0);
  let verifiedBytes = 0; let verifiedParts = 0;
  for (const [trackIndex, track] of ordered.entries()) {
    files.push(await reconstructTrack(track, session.id, fetchImpl, { signal, onProgress: (progress) => {
      verifiedBytes += progress.verifiedBytes; verifiedParts++;
      onProgress?.({ verifiedBytes, totalBytes, verifiedParts, totalParts, trackIndex: trackIndex + 1,
        trackCount: ordered.length, partNumber: progress.partNumber, trackPartCount: progress.partCount });
    } }));
  }
  throwIfAborted(signal);
  if (files.reduce((sum, file) => sum + file.size, 0) > MAX_AUDIO_SESSION_BYTES) {
    throw new Error("Исходная сессия превышает лимит 500 МБ.");
  }
  return files;
}

function sourceDescriptor(session) {
  return (session.sourceTracks || []).map((track) => ({
    trackId: track.trackId, blobId: track.blobId, ordinal: track.ordinal, originalName: track.originalName,
    mediaType: track.mediaType, sizeBytes: track.sizeBytes, sha256: track.sha256,
    parts: track.parts.map((part) => ({ partNumber: part.partNumber, sizeBytes: part.sizeBytes,
      sha256: part.sha256, assetName: part.assetName, assetId: part.assetId, downloadUrl: part.downloadUrl }))
  }));
}

export function remoteSourceFingerprint(session) {
  if (!validateSessionManifest(session)) throw new Error("Данные архивной записи повреждены.");
  return JSON.stringify(sourceDescriptor(session));
}

export async function prepareRemoteSourceBatch({ gateway, sessionId, signal, onProgress } = {}) {
  if (!gateway || !isUuid(sessionId)) throw new Error("Некорректная архивная запись.");
  throwIfAborted(signal);
  const initial = await gateway.getSession(sessionId, signal);
  throwIfAborted(signal);
  if (!validateSessionManifest(initial) || initial.id !== sessionId || initial.lifecycle.state !== "incoming" || initial.sourceState !== "available") {
    throw new Error("Запись больше не доступна для редактирования.");
  }
  const fingerprint = remoteSourceFingerprint(initial);
  const files = await reconstructSessionTracks(initial, gateway.sourcePartFetch(initial), { signal, onProgress });
  throwIfAborted(signal);
  const fresh = await gateway.getSession(sessionId, signal);
  throwIfAborted(signal);
  if (!validateSessionManifest(fresh) || fresh.id !== sessionId || fresh.lifecycle.state !== "incoming" || fresh.sourceState !== "available" ||
      remoteSourceFingerprint(fresh) !== fingerprint) {
    const error = new Error("Состав или доступность исходников изменились во время загрузки.");
    error.code = "remote_source_changed";
    throw error;
  }
  return Object.freeze({ session: fresh, files: Object.freeze(files), fingerprint,
    readinessIdentity: `${fresh.id}:${fingerprint}` });
}

export class AudioArchiveGateway {
  constructor(baseUrl, fetchImpl = fetch) {
    this.baseUrl = String(baseUrl || "").replace(/\/+$/, "");
    this.fetchImpl = fetchImpl.bind(globalThis);
    this.csrfToken = null;
    this.authGeneration = 0;
    this.acceptedPartSize = DEFAULT_AUDIO_PART_BYTES;
    this.speakerProjectHistoryVersion = 0;
  }

  async request(path, options = {}) {
    const { captureCsrf = true, ...fetchOptions } = options;
    throwIfAborted(fetchOptions.signal);
    const headers = new Headers(fetchOptions.headers || {});
    if (fetchOptions.body && !(fetchOptions.body instanceof Blob) && typeof fetchOptions.body !== "string") {
      headers.set("Content-Type", "application/json");
      fetchOptions.body = JSON.stringify(fetchOptions.body);
    }
    if (!/^(GET|HEAD|OPTIONS)$/i.test(fetchOptions.method || "GET") && this.csrfToken) headers.set("X-CSRF-Token", this.csrfToken);
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, { credentials: "include", ...fetchOptions, headers });
    const contentType = response.headers.get("Content-Type") || "";
    if (response.status !== 204 && !contentType.toLowerCase().startsWith("application/json")) {
      throw Object.assign(new Error("Шлюз вернул ответ в неожиданном формате."), { status: response.status });
    }
    const payload = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) {
      const error = new Error(payload?.error || "Операция аудиоархива не выполнена.");
      error.status = response.status;
      error.details = payload?.details;
      throw error;
    }
    if (captureCsrf && payload?.csrfToken) this.csrfToken = payload.csrfToken;
    return payload;
  }

  async requestBinary(path, { signal } = {}) {
    throwIfAborted(signal);
    const response = await this.fetchImpl(`${this.baseUrl}${path}`, { method: "GET", credentials: "include", signal });
    if (!response.ok) {
      const payload = (response.headers.get("Content-Type") || "").toLowerCase().startsWith("application/json")
        ? await response.json().catch(() => null) : null;
      throw Object.assign(new Error(payload?.error || "Операция аудиоархива не выполнена."), {
        status: response.status,
        waveformDiagnostic: payload?.waveformDiagnostic && typeof payload.waveformDiagnostic.stage === "string"
          ? Object.freeze({ stage: payload.waveformDiagnostic.stage, exitStatus: Number.isInteger(payload.waveformDiagnostic.exitStatus) ? payload.waveformDiagnostic.exitStatus : null }) : null
      });
    }
    if ((response.headers.get("Content-Type") || "").toLowerCase() !== "application/vnd.meser.waveform-f32le") {
      throw Object.assign(new Error("Шлюз вернул waveform в неожиданном формате."), { waveformDiagnostic: Object.freeze({ stage: "parse" }) });
    }
    try {
      return { response, bytes: new Uint8Array(await response.arrayBuffer()) };
    } catch (error) {
      throw Object.assign(new Error("Не удалось прочитать binary waveform ответ."), {
        cause: error, waveformDiagnostic: Object.freeze({ stage: "parse" })
      });
    }
  }

  async configuration() {
    const result = await this.request("/v1/config");
    if (Number.isSafeInteger(result?.acceptedPartSize) && result.acceptedPartSize > 0 && result.acceptedPartSize <= MAX_AUDIO_PART_BYTES) {
      this.acceptedPartSize = Math.min(DEFAULT_AUDIO_PART_BYTES, result.acceptedPartSize);
    }
    this.speakerProjectHistoryVersion = result?.speakerProjectHistory === 1 ? 1 : 0;
    return result;
  }
  assertCanonicalSpeakerWrites() {
    if (this.speakerProjectHistoryVersion === 1) return;
    const error = new Error("Версия шлюза несовместима с текущим сохранением «Спикерская». Локальные файлы, монтаж и готовый MP3 сохранены; можно продолжить локальную работу и скачать результат.");
    error.code = "incompatible_speaker_gateway";
    error.userMessage = error.message;
    throw error;
  }
  sessionStatus({ captureCsrf = true } = {}) { return this.request("/v1/session", { captureCsrf }); }
  invalidateAuthentication() { this.authGeneration += 1; this.csrfToken = null; }
  async login(password, { onState } = {}) {
    const generation = ++this.authGeneration;
    this.csrfToken = null;
    onState?.("checking-password");
    try {
      await this.request("/v1/session/login", { method: "POST", body: { password }, captureCsrf: false });
    } catch (error) {
      if (error?.status === 401) error.code = "invalid_password";
      throw error;
    }
    try {
      onState?.("verifying-session");
      const proof = await this.sessionStatus({ captureCsrf: false });
      if (proof?.authenticated !== true || typeof proof.csrfToken !== "string" || !proof.csrfToken) throw new Error("Шлюз не подтвердил защищённый сеанс.");
      if (generation !== this.authGeneration) return Object.freeze({ authenticated: false, stale: true });
      this.csrfToken = proof.csrfToken;
      return proof;
    } catch (error) {
      if (generation === this.authGeneration) this.csrfToken = null;
      if (error?.status === 401) error.code = "session_replay_failed";
      throw error;
    }
  }
  async logout() {
    this.authGeneration += 1;
    try { return await this.request("/v1/session/logout", { method: "POST" }); }
    finally { this.csrfToken = null; }
  }
  listSessions(lifecycle = "incoming") { return this.request(`/v1/source-sessions?lifecycle=${encodeURIComponent(lifecycle)}`); }
  getSession(id, signal) { return this.request(`/v1/source-sessions/${encodeURIComponent(id)}`, { signal }); }
  async sourceWaveform(sessionId, blobId, expectedSource, signal) {
    if (!isUuid(sessionId) || !isUuid(blobId) || !expectedSource || !/^[0-9a-f]{64}$/.test(expectedSource.sha256)) {
      throw new Error("Некорректная waveform identity.");
    }
    const { response, bytes } = await this.requestBinary(`/v1/source-sessions/${encodeURIComponent(sessionId)}/blobs/${encodeURIComponent(blobId)}/waveform`, { signal });
    const peakCount = Number(response.headers.get("X-Meser-Waveform-Peaks"));
    const duration = Number(response.headers.get("X-Meser-Waveform-Duration"));
    const sourceSha256 = response.headers.get("X-Meser-Source-SHA256") || "";
    const resultSha256 = response.headers.get("X-Meser-Waveform-SHA256") || "";
    if (response.headers.get("X-Meser-Waveform-Algorithm") !== "meser-peaks-f32le-v1" || peakCount !== 65536 ||
        bytes.byteLength !== peakCount * 4 || sourceSha256 !== expectedSource.sha256 || !/^[0-9a-f]{64}$/.test(resultSha256) ||
        await sha256Hex(bytes, signal) !== resultSha256 || !(duration > 0)) {
      throw Object.assign(new Error("Проверка server waveform не пройдена."), { waveformDiagnostic: Object.freeze({ stage: "validate" }) });
    }
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const samples = new Float32Array(peakCount);
    for (let index = 0; index < samples.length; index++) {
      const value = view.getFloat32(index * 4, true);
      if (!Number.isFinite(value) || value < 0 || value > 1) throw Object.assign(new Error("Server waveform содержит недопустимые peaks."), { waveformDiagnostic: Object.freeze({ stage: "validate" }) });
      samples[index] = value;
    }
    samples.sampleRate = samples.length / duration;
    return Object.freeze({ samples, duration, sourceSha256, resultSha256,
      cache: response.headers.get("X-Meser-Waveform-Cache") === "hit" ? "hit" : "miss" });
  }
  sourcePartFetch(session) {
    if (!validateSessionManifest(session) || session.sourceState !== "available") throw new Error("Данные архивной записи повреждены.");
    const parts = new Map();
    for (const track of session.sourceTracks) {
      for (const part of track.parts) parts.set(part.downloadUrl, { blobId: track.blobId, partNumber: part.partNumber });
    }
    return async (url, options = {}) => {
      const part = parts.get(String(url));
      if (!part) throw new Error("Запрошенная часть не принадлежит этой архивной записи.");
      const path = `/v1/source-sessions/${encodeURIComponent(session.id)}/blobs/${encodeURIComponent(part.blobId)}/parts/${part.partNumber}/content`;
      return this.fetchImpl(`${this.baseUrl}${path}`, { ...options, credentials: "include" });
    };
  }
  getAnnouncementOutput(sessionId, outputId) {
    return this.request(`/v1/source-sessions/${encodeURIComponent(sessionId)}/outputs/announcement/${encodeURIComponent(outputId)}`);
  }
  getSpeakerOutput(sessionId, outputId) {
    return this.request(`/v1/source-sessions/${encodeURIComponent(sessionId)}/outputs/speaker/${encodeURIComponent(outputId)}`);
  }
  async speakerProjectHistory(sessionId, signal) {
    this.assertCanonicalSpeakerWrites();
    return validateSpeakerProjectHistory(await this.request(`/v1/source-sessions/${encodeURIComponent(sessionId)}/projects/speaker`, { signal }), sessionId);
  }
  async speakerProjectState(sessionId, draftRevision, signal) {
    this.assertCanonicalSpeakerWrites();
    if (!Number.isSafeInteger(draftRevision) || draftRevision < 1) {
      throw new Error("Некорректная версия состояния проекта.");
    }
    const state = await this.request(`/v1/source-sessions/${encodeURIComponent(sessionId)}/projects/speaker/states/${draftRevision}`, { signal });
    return verifySpeakerProjectState(state, signal);
  }
  continueSpeakerProject(sessionId, envelope, signal) {
    this.assertCanonicalSpeakerWrites();
    return this.request(`/v1/source-sessions/${encodeURIComponent(sessionId)}/projects/speaker/continuations`, { method: "POST", body: envelope, signal });
  }
  announcementPartFetch(metadata) {
    const { output, recipe } = metadata || {};
    if (!validateAnnouncementOutput(output, recipe, output?.sessionId)) throw new Error("Данные сохранённого результата «Анонс-мейкер» повреждены.");
    const parts = new Map(output.parts.map((part) => [part.downloadUrl, part]));
    return async (url, options = {}) => {
      const part = parts.get(String(url));
      if (!part) throw new Error("URL части не принадлежит этому результату.");
      const path = `/v1/source-sessions/${encodeURIComponent(output.sessionId)}/outputs/announcement/${encodeURIComponent(output.outputId)}/blobs/${encodeURIComponent(output.blobId)}/parts/${part.partNumber}/content`;
      return this.fetchImpl(`${this.baseUrl}${path}`, { ...options, credentials: "include" });
    };
  }
  speakerPartFetch(metadata) {
    const { output, recipe } = metadata || {};
    if (!validateSpeakerOutput(output, recipe, output?.sessionId)) throw new Error("Данные сохранённого результата «Спикерская» повреждены.");
    const parts = new Map(output.parts.map((part) => [part.downloadUrl, part]));
    return async (url, options = {}) => {
      const part = parts.get(String(url));
      if (!part) throw new Error("URL части не принадлежит результату Спикерской.");
      const path = `/v1/source-sessions/${encodeURIComponent(output.sessionId)}/outputs/speaker/${encodeURIComponent(output.outputId)}/blobs/${encodeURIComponent(output.blobId)}/parts/${part.partNumber}/content`;
      return this.fetchImpl(`${this.baseUrl}${path}`, { ...options, credentials: "include" });
    };
  }
  updateSession(id, expectedRevision, patch, idempotencyKey = crypto.randomUUID()) {
    return this.request(`/v1/source-sessions/${encodeURIComponent(id)}`, { method: "PATCH", body: { expectedRevision, patch, idempotencyKey } });
  }
  updateWorkflow(id, workflow, expectedRevision, status, idempotencyKey = crypto.randomUUID()) {
    return this.request(`/v1/source-sessions/${encodeURIComponent(id)}/workflows/${workflow}/status`, {
      method: "PUT", body: { expectedRevision, status, idempotencyKey }
    });
  }
  loadDraft(id, workflow) { return this.request(`/v1/source-sessions/${encodeURIComponent(id)}/drafts/${workflow}`); }
  saveDraft(id, workflow, envelope, signal) {
    if (workflow === "speaker") this.assertCanonicalSpeakerWrites();
    return this.request(`/v1/source-sessions/${encodeURIComponent(id)}/drafts/${workflow}`, { method: "PUT", body: envelope, signal });
  }
  dependencyPreview(id) { return this.request(`/v1/source-sessions/${encodeURIComponent(id)}/deletion-preview`); }
  setLifecycle(id, action, expectedRevision, idempotencyKey = crypto.randomUUID()) {
    return this.request(`/v1/source-sessions/${encodeURIComponent(id)}/${action}`, { method: "POST", body: { expectedRevision, idempotencyKey } });
  }
  deleteOutputVersion(id, workflow, version, body) {
    return this.request(`/v1/source-sessions/${encodeURIComponent(id)}/outputs/${workflow}/versions/${version}/delete`, { method: "POST", body });
  }
  deleteOutputSeries(id, workflow, body) {
    return this.request(`/v1/source-sessions/${encodeURIComponent(id)}/outputs/${workflow}/delete`, { method: "POST", body });
  }
  deleteSources(id, body) { return this.request(`/v1/source-sessions/${encodeURIComponent(id)}/sources/delete`, { method: "POST", body }); }
  purgeSession(id, body) { return this.request(`/v1/source-sessions/${encodeURIComponent(id)}/purge`, { method: "POST", body }); }
  listIncomplete() { return this.request("/v1/maintenance/incomplete"); }
  recoverIncomplete(transactionId, action) { return this.request(`/v1/maintenance/incomplete/${encodeURIComponent(transactionId)}/${action}`, { method: "POST", body: { idempotencyKey: crypto.randomUUID() } }); }
  rebuildCatalog() { return this.request("/v1/maintenance/catalog/rebuild", { method: "POST", body: { idempotencyKey: crypto.randomUUID() } }); }

  async publishAnnouncement({ sessionId, expectedRevision, expectedDraftRevision, blob, recipe,
    idempotencyKey = crypto.randomUUID(), signal, onProgress = () => {}, onStarted = () => {} }) {
    const plan = await createAnnouncementPublicationPlan(blob, recipe, this.acceptedPartSize, { idempotencyKey, signal });
    const started = await this.request(`/v1/source-sessions/${encodeURIComponent(sessionId)}/outputs/announcement/publications`, {
      method: "POST", signal, body: { schemaVersion: 1, expectedRevision, expectedDraftRevision,
        idempotencyKey, plan: serializeAnnouncementPublicationPlan(plan) }
    });
    onStarted(started);
    let uploadedBytes = 0;
    for (const part of plan.parts) {
      await this.request(`/v1/announcement-publications/${encodeURIComponent(started.transactionId)}/blobs/${encodeURIComponent(plan.blobId)}/parts/${part.partNumber}`, {
        method: "PUT", signal, body: part.blob, headers: { "Content-Type": "application/octet-stream",
          "X-Part-SHA256": part.sha256, "Idempotency-Key": `${idempotencyKey}:${part.partNumber}` }
      });
      uploadedBytes += part.sizeBytes;
      onProgress({ uploadedBytes, totalBytes: plan.sizeBytes, uploadedParts: part.partNumber, totalParts: plan.parts.length,
        reservedVersion: started.reservedVersion });
    }
    return this.request(`/v1/announcement-publications/${encodeURIComponent(started.transactionId)}/finalize`, {
      method: "POST", signal, body: { idempotencyKey: `${idempotencyKey}:finalize` }
    });
  }

  async saveSpeaker({ sessionId, expectedRevision, expectedDraftRevision, blob, recipe,
    idempotencyKey = crypto.randomUUID(), signal, onPhase = () => {}, onProgress = () => {}, onStarted = () => {} }) {
    this.assertCanonicalSpeakerWrites();
    if (recipe?.schemaVersion !== 2) throw new Error("Новая финальная версия «Спикерская» должна ссылаться на точное неизменяемое состояние проекта.");
    onPhase("preparing");
    const plan = await createSpeakerSavePlan(blob, recipe, this.acceptedPartSize, { idempotencyKey, signal });
    onPhase("reserving");
    const started = await this.request(`/v1/source-sessions/${encodeURIComponent(sessionId)}/outputs/speaker/saves`, {
      method: "POST", signal, body: { schemaVersion: 1, expectedRevision, expectedDraftRevision,
        idempotencyKey, plan: serializeSpeakerSavePlan(plan) }
    });
    onStarted(started);
    const accepted = new Set(started.uploadedPartNumbers || []);
    let uploadedBytes = plan.parts.filter((part) => accepted.has(part.partNumber)).reduce((sum, part) => sum + part.sizeBytes, 0);
    onPhase("uploading");
    for (const part of plan.parts) {
      if (accepted.has(part.partNumber)) continue;
      await this.request(`/v1/speaker-saves/${encodeURIComponent(started.transactionId)}/blobs/${encodeURIComponent(plan.blobId)}/parts/${part.partNumber}`, {
        method: "PUT", signal, body: part.blob, headers: { "Content-Type": "application/octet-stream",
          "X-Part-SHA256": part.sha256, "Idempotency-Key": `${idempotencyKey}:${part.partNumber}` }
      });
      uploadedBytes += part.sizeBytes;
      onProgress({ uploadedBytes, totalBytes: plan.sizeBytes, uploadedParts: accepted.size + 1, totalParts: plan.parts.length,
        reservedVersion: started.reservedVersion });
      accepted.add(part.partNumber);
    }
    onPhase("verifying");
    const result = await this.request(`/v1/speaker-saves/${encodeURIComponent(started.transactionId)}/finalize`, {
      method: "POST", signal, body: { idempotencyKey: `${idempotencyKey}:finalize` }
    });
    onPhase("saved");
    return result;
  }

  speakerSaveJob(transactionId, signal) { return this.request(`/v1/speaker-saves/${encodeURIComponent(transactionId)}`, { signal }); }
  cancelSpeakerSave(transactionId, discard = false, idempotencyKey = crypto.randomUUID()) {
    return this.request(`/v1/speaker-saves/${encodeURIComponent(transactionId)}/${discard ? "discard" : "cancel"}`, {
      method: "POST", body: { idempotencyKey }
    });
  }

  finalizeSpeakerSave(transactionId, idempotencyKey = crypto.randomUUID(), signal) {
    this.assertCanonicalSpeakerWrites();
    return this.request(`/v1/speaker-saves/${encodeURIComponent(transactionId)}/finalize`, { method: "POST", signal, body: { idempotencyKey } });
  }

  async resumeSpeakerSave(transactionId, { blob, candidateFingerprint, signal, onProgress = () => {} } = {}) {
    this.assertCanonicalSpeakerWrites();
    signal?.throwIfAborted();
    const job = await this.speakerSaveJob(transactionId, signal);
    signal?.throwIfAborted();
    if (job.canFinalize) return this.finalizeSpeakerSave(transactionId, crypto.randomUUID(), signal);
    if (!(blob instanceof Blob) || blob.size !== job.sizeBytes || candidateFingerprint !== job.candidateFingerprint ||
        await sha256Hex(new Uint8Array(await blob.arrayBuffer()), signal) !== job.sha256) {
      throw new Error("Для продолжения нужен точно тот же локальный результат Спикерской.");
    }
    const accepted = new Set(job.uploadedPartNumbers || []);
    let offset = 0;
    let uploadedBytes = job.parts.filter((part) => accepted.has(part.partNumber)).reduce((sum, part) => sum + part.sizeBytes, 0);
    for (const part of job.parts) {
      const partBlob = blob.slice(offset, offset + part.sizeBytes, "application/octet-stream");
      offset += part.sizeBytes;
      if (accepted.has(part.partNumber)) continue;
      const bytes = new Uint8Array(await partBlob.arrayBuffer());
      if (bytes.byteLength !== part.sizeBytes || await sha256Hex(bytes, signal) !== part.sha256) throw new Error("Локальный результат не совпадает с планом незавершённого сохранения.");
      await this.request(`/v1/speaker-saves/${encodeURIComponent(transactionId)}/blobs/${encodeURIComponent(job.blobId)}/parts/${part.partNumber}`, {
        method: "PUT", signal, body: partBlob, headers: { "Content-Type": "application/octet-stream", "X-Part-SHA256": part.sha256,
          "Idempotency-Key": `speaker-resume:${transactionId}:${part.partNumber}` }
      });
      accepted.add(part.partNumber); uploadedBytes += part.sizeBytes;
      onProgress({ uploadedBytes, totalBytes: job.sizeBytes, uploadedParts: accepted.size, totalParts: job.parts.length, reservedVersion: job.reservedVersion });
    }
    signal?.throwIfAborted();
    return this.finalizeSpeakerSave(transactionId, crypto.randomUUID(), signal);
  }

  publicationJob(transactionId) { return this.request(`/v1/announcement-publications/${encodeURIComponent(transactionId)}`); }
  cancelPublication(transactionId, discard = false, idempotencyKey = crypto.randomUUID()) {
    return this.request(`/v1/announcement-publications/${encodeURIComponent(transactionId)}/${discard ? "discard" : "cancel"}`, {
      method: "POST", body: { idempotencyKey }
    });
  }

  async ingestFiles({ files, title, recordedAt = null, origin = "device", supersedesSessionId = null, idempotencyKey = crypto.randomUUID(), signal, onProgress = () => {}, onPlan = () => {}, onStarted = () => {}, onFinalizing = () => {} }) {
    const plan = await createIngestionPlan(files, this.acceptedPartSize, { idempotencyKey, signal });
    onPlan(plan);
    const started = await this.request("/v1/source-sessions/ingestions", {
      method: "POST", signal,
      body: { schemaVersion: AUDIO_ARCHIVE_SCHEMA_VERSION, idempotencyKey, title, recordedAt, origin, supersedesSessionId, plan: serializeIngestionPlan(plan) }
    });
    onStarted(started);
    if (started.state === "finalized") return { session: await this.getSession(started.sessionId, signal), idempotent: true };
    const totalParts = plan.tracks.reduce((sum, track) => sum + track.parts.length, 0);
    let uploadedParts = 0;
    let uploadedBytes = 0;
    for (const track of plan.tracks) {
      for (const part of track.parts) {
        await this.request(`/v1/source-sessions/ingestions/${encodeURIComponent(started.transactionId)}/blobs/${encodeURIComponent(track.blobId)}/parts/${part.partNumber}`, {
          method: "PUT", signal, body: part.blob,
          headers: {
            "Content-Type": "application/octet-stream",
            "X-Part-SHA256": part.sha256,
            "Idempotency-Key": `${idempotencyKey}:${track.blobId}:${part.partNumber}`
          }
        });
        uploadedParts++;
        uploadedBytes += part.sizeBytes;
        onProgress({ uploadedParts, totalParts, uploadedBytes, totalBytes: plan.totalBytes });
      }
    }
    onFinalizing();
    return this.request(`/v1/source-sessions/ingestions/${encodeURIComponent(started.transactionId)}/finalize`, {
      method: "POST", signal, body: { idempotencyKey: `${idempotencyKey}:finalize` }
    });
  }
}
