import { createHash } from "node:crypto";

export const SCHEMA_VERSION = 1;
export const DEFAULT_PART_BYTES = 16 * 1024 * 1024;
export const MAX_PART_BYTES = 64 * 1024 * 1024;
export const MAX_SESSION_BYTES = 500 * 1024 * 1024;
export const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export const SHA256_PATTERN = /^[0-9a-f]{64}$/;
export const WORKFLOWS = Object.freeze(["announcement", "speaker"]);
export const WORKFLOW_STATES = Object.freeze(["new", "in_progress", "result_ready"]);
export const MEDIA_TYPES = Object.freeze({ mp3: "audio/mpeg", m4a: "audio/mp4", wav: "audio/wav" });

export class ValidationError extends Error {
  constructor(message, details = undefined) {
    super(message);
    this.name = "ValidationError";
    this.status = 400;
    this.details = details;
  }
}

export function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function assertExactKeys(value, allowed, label) {
  if (!isPlainObject(value)) throw new ValidationError(`${label} must be an object`);
  const extras = Object.keys(value).filter((key) => !allowed.includes(key));
  if (extras.length) throw new ValidationError(`${label} contains unsupported fields`, extras);
}

export function assertUuid(value, label = "id") {
  if (typeof value !== "string" || !UUID_PATTERN.test(value)) throw new ValidationError(`${label} must be a UUID`);
  return value.toLowerCase();
}

export function assertSha256(value, label = "sha256") {
  if (typeof value !== "string" || !SHA256_PATTERN.test(value)) throw new ValidationError(`${label} must be a lowercase SHA-256 hex digest`);
  return value;
}

export function assertInteger(value, minimum, maximum, label) {
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) throw new ValidationError(`${label} is out of range`);
  return value;
}

export function assertTimestamp(value, label, optional = false) {
  if (optional && value === null) return null;
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T/.test(value) || Number.isNaN(Date.parse(value))) {
    throw new ValidationError(`${label} must be an ISO timestamp`);
  }
  return value;
}

export function normalizeFilename(value) {
  const normalized = String(value || "audio").normalize("NFC")
    .replace(/[\u0000-\u001f\u007f]/g, "").replace(/[\\/]+/g, "-").trim().slice(0, 255);
  return normalized || "audio";
}

export function normalizeMediaType(filename, supplied = "") {
  const extension = normalizeFilename(filename).split(".").pop()?.toLowerCase();
  const canonical = MEDIA_TYPES[extension];
  if (!canonical) throw new ValidationError("Only MP3, M4A and WAV sources are supported");
  const received = String(supplied || "").toLowerCase().split(";")[0].trim();
  const compatible = !received || received === canonical || (extension === "m4a" && received === "audio/x-m4a") ||
    (extension === "wav" && received === "audio/x-wav");
  if (!compatible) throw new ValidationError("Media type does not match filename extension");
  return canonical;
}

export function assetName(blobId, partNumber) {
  const id = assertUuid(blobId, "blobId");
  assertInteger(partNumber, 1, 9999, "partNumber");
  return `blob-${id}-part-${String(partNumber).padStart(4, "0")}.bin`;
}

export function hashIdempotencyKey(value) {
  if (typeof value !== "string" || value.length < 16 || value.length > 200) throw new ValidationError("Invalid idempotency key");
  return createHash("sha256").update(value, "utf8").digest("hex");
}

export function uuidFromIdempotencyKey(value) {
  const hex = hashIdempotencyKey(value).slice(0, 32).split("");
  hex[12] = "5";
  hex[16] = ["8", "9", "a", "b"][Number.parseInt(hex[16], 16) & 3];
  return `${hex.slice(0, 8).join("")}-${hex.slice(8, 12).join("")}-${hex.slice(12, 16).join("")}-${hex.slice(16, 20).join("")}-${hex.slice(20).join("")}`;
}

function validatePlannedPart(part, blobId, expectedNumber, acceptedPartBytes) {
  assertExactKeys(part, ["partNumber", "sizeBytes", "sha256", "assetName"], "part");
  if (part.partNumber !== expectedNumber || part.assetName !== assetName(blobId, expectedNumber)) throw new ValidationError("Part order or name is invalid");
  assertInteger(part.sizeBytes, 1, Math.min(MAX_PART_BYTES, acceptedPartBytes), "part.sizeBytes");
  assertSha256(part.sha256, "part.sha256");
  return part.sizeBytes;
}

export function validateIngestionPlan(plan, acceptedPartBytes = DEFAULT_PART_BYTES) {
  assertInteger(acceptedPartBytes, 1, MAX_PART_BYTES, "acceptedPartBytes");
  assertExactKeys(plan, ["totalBytes", "tracks"], "plan");
  if (!Array.isArray(plan.tracks) || !plan.tracks.length || plan.tracks.length > 32) throw new ValidationError("plan.tracks must contain 1 to 32 tracks");
  let sessionBytes = 0;
  const trackIds = new Set();
  const blobIds = new Set();
  for (const [index, track] of plan.tracks.entries()) {
    assertExactKeys(track, ["trackId", "blobId", "ordinal", "originalName", "mediaType", "sizeBytes", "sha256", "parts"], "track");
    const trackId = assertUuid(track.trackId, "trackId");
    const blobId = assertUuid(track.blobId, "blobId");
    if (trackIds.has(trackId) || blobIds.has(blobId)) throw new ValidationError("Track and blob IDs must be unique");
    trackIds.add(trackId); blobIds.add(blobId);
    if (track.ordinal !== index + 1) throw new ValidationError("Track order is invalid");
    if (track.originalName !== normalizeFilename(track.originalName)) throw new ValidationError("Filename is not normalized");
    if (track.mediaType !== normalizeMediaType(track.originalName, track.mediaType)) throw new ValidationError("Media type is not canonical");
    assertInteger(track.sizeBytes, 1, MAX_SESSION_BYTES, "track.sizeBytes");
    assertSha256(track.sha256, "track.sha256");
    if (!Array.isArray(track.parts) || !track.parts.length) throw new ValidationError("Track must contain parts");
    const partBytes = track.parts.reduce((sum, part, partIndex) => sum + validatePlannedPart(part, blobId, partIndex + 1, acceptedPartBytes), 0);
    if (partBytes !== track.sizeBytes) throw new ValidationError("Track part sizes do not match logical size");
    sessionBytes += track.sizeBytes;
  }
  if (sessionBytes !== plan.totalBytes || sessionBytes < 1 || sessionBytes > MAX_SESSION_BYTES) throw new ValidationError("Session byte total is invalid");
  return structuredClone(plan);
}

function validateStoredPart(part, blobId, expectedNumber, sessionId) {
  assertExactKeys(part, ["partNumber", "sizeBytes", "sha256", "assetName", "assetId", "downloadUrl"], "stored part");
  validatePlannedPart({ partNumber: part.partNumber, sizeBytes: part.sizeBytes, sha256: part.sha256, assetName: part.assetName }, blobId, expectedNumber, MAX_PART_BYTES);
  assertInteger(part.assetId, 1, Number.MAX_SAFE_INTEGER, "assetId");
  const expectedUrl = `https://github.com/meser-recovery/audio-archive/releases/download/audio-session-${sessionId}/${part.assetName}`;
  if (part.downloadUrl !== expectedUrl) {
    throw new ValidationError("Release asset URL is invalid");
  }
}

function validateOutput(output, sessionId) {
  assertExactKeys(output, ["outputId", "version", "sessionId", "createdAt", "blobId", "sizeBytes", "sha256", "parts", "recipeSnapshotRef", "processorVersion"], "output");
  assertUuid(output.outputId, "outputId");
  if (output.sessionId !== sessionId) throw new ValidationError("Output lineage session mismatch");
  assertInteger(output.version, 1, Number.MAX_SAFE_INTEGER, "output.version");
  assertTimestamp(output.createdAt, "output.createdAt");
  assertUuid(output.blobId, "output.blobId");
  assertInteger(output.sizeBytes, 1, Number.MAX_SAFE_INTEGER, "output.sizeBytes");
  assertSha256(output.sha256, "output.sha256");
  if (!Array.isArray(output.parts) || !output.parts.length) throw new ValidationError("Output parts are missing");
  output.parts.forEach((part, index) => validateStoredPart(part, output.blobId, index + 1, sessionId));
  if (output.parts.reduce((sum, part) => sum + part.sizeBytes, 0) !== output.sizeBytes) throw new ValidationError("Output part sizes do not match logical size");
  if (typeof output.recipeSnapshotRef !== "string" || !output.recipeSnapshotRef || typeof output.processorVersion !== "string" || !output.processorVersion) {
    throw new ValidationError("Output lineage metadata is missing");
  }
}

function validateWorkflow(value, name, sessionId) {
  assertExactKeys(value, ["workflow", "status", "currentDraft", "outputs", "deletedVersions", "nextVersion"], `workflow.${name}`);
  if (value.workflow !== name || !WORKFLOW_STATES.includes(value.status)) throw new ValidationError("Workflow state is invalid");
  if (!(value.currentDraft === null || (isPlainObject(value.currentDraft) && value.currentDraft.path === `drafts/${sessionId}/${name}.json` &&
      Number.isSafeInteger(value.currentDraft.revision) && value.currentDraft.revision > 0))) throw new ValidationError("Draft reference is invalid");
  if (!Array.isArray(value.outputs) || !Array.isArray(value.deletedVersions)) throw new ValidationError("Workflow versions are invalid");
  value.outputs.forEach((output) => validateOutput(output, sessionId));
  value.deletedVersions.forEach((version) => assertInteger(version, 1, Number.MAX_SAFE_INTEGER, "deleted version"));
  assertInteger(value.nextVersion, 1, Number.MAX_SAFE_INTEGER, "nextVersion");
  const used = [...value.outputs.map((item) => item.version), ...value.deletedVersions];
  if (new Set(used).size !== used.length || used.some((version) => version >= value.nextVersion)) throw new ValidationError("Version numbers are reused or out of order");
  if (new Set(value.outputs.map((item) => item.outputId)).size !== value.outputs.length ||
      new Set(value.outputs.map((item) => item.blobId)).size !== value.outputs.length) throw new ValidationError("Output and blob IDs must be unique");
}

function validateDeletedSources(value) {
  if (value === null) return;
  assertExactKeys(value, ["deletedAt", "tracks"], "deletedSources");
  assertTimestamp(value.deletedAt, "deletedSources.deletedAt");
  if (!Array.isArray(value.tracks) || !value.tracks.length || value.tracks.length > 32) {
    throw new ValidationError("Deleted source record must preserve one to 32 track tombstones");
  }
  const trackIds = new Set();
  const blobIds = new Set();
  for (const track of value.tracks) {
    assertExactKeys(track, ["trackId", "blobId", "sizeBytes", "sha256"], "deleted source track");
    const trackId = assertUuid(track.trackId, "deleted trackId");
    const blobId = assertUuid(track.blobId, "deleted blobId");
    if (trackIds.has(trackId) || blobIds.has(blobId)) throw new ValidationError("Deleted source track IDs must be unique");
    trackIds.add(trackId); blobIds.add(blobId);
    assertInteger(track.sizeBytes, 1, MAX_SESSION_BYTES, "deleted source sizeBytes");
    assertSha256(track.sha256, "deleted source sha256");
  }
}

export function validateSourceSession(session) {
  assertExactKeys(session, ["schemaVersion", "revision", "id", "title", "recordedAt", "createdAt", "updatedAt", "origin", "storage", "lifecycle", "sourceState", "sourceTracks", "deletedSources", "workflows", "relations", "transaction"], "source session");
  if (session.schemaVersion !== SCHEMA_VERSION) throw new ValidationError("Unsupported Source Session schema");
  assertInteger(session.revision, 1, Number.MAX_SAFE_INTEGER, "revision");
  const id = assertUuid(session.id, "session.id");
  if (typeof session.title !== "string" || !session.title.trim() || session.title.length > 200) throw new ValidationError("Session title is invalid");
  assertTimestamp(session.recordedAt, "recordedAt", true);
  assertTimestamp(session.createdAt, "createdAt"); assertTimestamp(session.updatedAt, "updatedAt");
  assertExactKeys(session.origin, ["kind", "externalId"], "origin");
  if (!["manual", "device", "zoom_webhook"].includes(session.origin.kind) || !(session.origin.externalId === null || typeof session.origin.externalId === "string")) throw new ValidationError("Origin is invalid");
  assertExactKeys(session.storage, ["releaseId", "tag"], "storage");
  assertInteger(session.storage.releaseId, 1, Number.MAX_SAFE_INTEGER, "releaseId");
  if (session.storage.tag !== `audio-session-${id}`) throw new ValidationError("Release tag is invalid");
  assertExactKeys(session.lifecycle, ["state"], "lifecycle");
  if (!["incoming", "archived"].includes(session.lifecycle.state)) throw new ValidationError("Lifecycle is invalid");
  if (!["available", "deleted"].includes(session.sourceState) || !Array.isArray(session.sourceTracks)) throw new ValidationError("Source state is invalid");
  let sourceBytes = 0;
  const sourceTrackIds = new Set();
  const sourceBlobIds = new Set();
  for (const [index, track] of session.sourceTracks.entries()) {
    assertExactKeys(track, ["trackId", "blobId", "ordinal", "originalName", "mediaType", "sizeBytes", "sha256", "parts"], "source track");
    const trackId = assertUuid(track.trackId, "trackId"); const blobId = assertUuid(track.blobId, "blobId");
    if (sourceTrackIds.has(trackId) || sourceBlobIds.has(blobId)) throw new ValidationError("Stored track and blob IDs must be unique");
    sourceTrackIds.add(trackId); sourceBlobIds.add(blobId);
    if (track.ordinal !== index + 1 || track.originalName !== normalizeFilename(track.originalName) || track.mediaType !== normalizeMediaType(track.originalName, track.mediaType)) throw new ValidationError("Stored track metadata is invalid");
    assertInteger(track.sizeBytes, 1, MAX_SESSION_BYTES, "track.sizeBytes"); assertSha256(track.sha256, "track.sha256");
    if (!Array.isArray(track.parts) || !track.parts.length) throw new ValidationError("Stored track parts are missing");
    track.parts.forEach((part, partIndex) => validateStoredPart(part, track.blobId, partIndex + 1, id));
    if (track.parts.reduce((sum, part) => sum + part.sizeBytes, 0) !== track.sizeBytes) throw new ValidationError("Stored track size mismatch");
    sourceBytes += track.sizeBytes;
  }
  if (sourceBytes > MAX_SESSION_BYTES || (session.sourceState === "available") !== (session.sourceTracks.length > 0)) throw new ValidationError("Stored source state mismatch");
  validateDeletedSources(session.deletedSources);
  if (session.sourceState === "available" && session.deletedSources !== null) throw new ValidationError("Available sources cannot also have deletion tombstones");
  if (session.sourceState === "deleted" && session.deletedSources === null) throw new ValidationError("Deleted sources require tombstones");
  assertExactKeys(session.workflows, WORKFLOWS, "workflows");
  for (const workflow of WORKFLOWS) validateWorkflow(session.workflows[workflow], workflow, id);
  const outputs = WORKFLOWS.flatMap((workflow) => session.workflows[workflow].outputs);
  if (new Set(outputs.map((output) => output.outputId)).size !== outputs.length ||
      new Set(outputs.map((output) => output.blobId)).size !== outputs.length) throw new ValidationError("Output IDs must be unique across workflows");
  if (outputs.some((output) => sourceBlobIds.has(output.blobId))) throw new ValidationError("Source and output blob IDs must be distinct");
  assertExactKeys(session.relations, ["supersedesSessionId", "supersededBySessionId"], "relations");
  for (const key of ["supersedesSessionId", "supersededBySessionId"]) if (session.relations[key] !== null) assertUuid(session.relations[key], key);
  assertExactKeys(session.transaction, ["state", "id"], "transaction");
  if (session.transaction.state !== "finalized") throw new ValidationError("Session is not finalized");
  assertUuid(session.transaction.id, "transaction.id");
  return structuredClone(session);
}

export function catalogEntry(session) {
  validateSourceSession(session);
  return {
    id: session.id, title: session.title, recordedAt: session.recordedAt, createdAt: session.createdAt, updatedAt: session.updatedAt,
    origin: session.origin.kind, lifecycle: session.lifecycle.state, sourceState: session.sourceState,
    workflows: { announcement: session.workflows.announcement.status, speaker: session.workflows.speaker.status }
  };
}

export function validateCatalog(catalog) {
  assertExactKeys(catalog, ["schemaVersion", "revision", "updatedAt", "entries"], "catalog");
  if (catalog.schemaVersion !== SCHEMA_VERSION) throw new ValidationError("Unsupported catalog schema");
  assertInteger(catalog.revision, 0, Number.MAX_SAFE_INTEGER, "catalog.revision");
  if (catalog.updatedAt !== null) assertTimestamp(catalog.updatedAt, "catalog.updatedAt");
  if (!Array.isArray(catalog.entries)) throw new ValidationError("Catalog entries must be an array");
  const ids = new Set();
  for (const entry of catalog.entries) {
    assertExactKeys(entry, ["id", "title", "recordedAt", "createdAt", "updatedAt", "origin", "lifecycle", "sourceState", "workflows"], "catalog entry");
    const id = assertUuid(entry.id, "catalog id");
    if (ids.has(id)) throw new ValidationError("Duplicate catalog entry");
    ids.add(id);
    if (typeof entry.title !== "string" || !entry.title || !["manual", "device", "zoom_webhook"].includes(entry.origin) ||
        !["incoming", "archived"].includes(entry.lifecycle) || !["available", "deleted"].includes(entry.sourceState)) throw new ValidationError("Catalog entry is invalid");
    assertTimestamp(entry.recordedAt, "catalog recordedAt", true); assertTimestamp(entry.createdAt, "catalog createdAt"); assertTimestamp(entry.updatedAt, "catalog updatedAt");
    assertExactKeys(entry.workflows, WORKFLOWS, "catalog workflows");
    for (const workflow of WORKFLOWS) if (!WORKFLOW_STATES.includes(entry.workflows[workflow])) throw new ValidationError("Catalog workflow is invalid");
  }
  return structuredClone(catalog);
}

export function validateDraft(draft) {
  assertExactKeys(draft, ["schemaVersion", "sessionId", "workflow", "draftRevision", "sourceSessionRevision", "savedAt", "payloadSchema", "payload"], "draft");
  if (draft.schemaVersion !== SCHEMA_VERSION) throw new ValidationError("Unsupported draft schema");
  assertUuid(draft.sessionId, "draft.sessionId");
  if (!WORKFLOWS.includes(draft.workflow)) throw new ValidationError("Draft workflow is invalid");
  assertInteger(draft.draftRevision, 1, Number.MAX_SAFE_INTEGER, "draftRevision");
  assertInteger(draft.sourceSessionRevision, 1, Number.MAX_SAFE_INTEGER, "sourceSessionRevision");
  assertTimestamp(draft.savedAt, "savedAt");
  if (typeof draft.payloadSchema !== "string" || !/^[-a-z0-9_.:/]{1,100}$/i.test(draft.payloadSchema)) throw new ValidationError("payloadSchema is invalid");
  JSON.stringify(draft.payload);
  return structuredClone(draft);
}

export function validateTombstone(value) {
  assertExactKeys(value, ["schemaVersion", "kind", "id", "deletedAt", "lastRevision", "releaseTag", "nextVersions"], "tombstone");
  if (value.schemaVersion !== SCHEMA_VERSION || value.kind !== "deletion_tombstone") throw new ValidationError("Unsupported tombstone schema");
  assertUuid(value.id, "tombstone.id"); assertTimestamp(value.deletedAt, "deletedAt");
  assertInteger(value.lastRevision, 1, Number.MAX_SAFE_INTEGER, "lastRevision");
  if (value.releaseTag !== `audio-session-${value.id}`) throw new ValidationError("Tombstone tag is invalid");
  assertExactKeys(value.nextVersions, WORKFLOWS, "nextVersions");
  for (const workflow of WORKFLOWS) assertInteger(value.nextVersions[workflow], 1, Number.MAX_SAFE_INTEGER, `nextVersions.${workflow}`);
  return structuredClone(value);
}

function validateTransactionBase(value, kind, states) {
  if (value.schemaVersion !== SCHEMA_VERSION || value.kind !== kind || !states.includes(value.state)) throw new ValidationError("Transaction kind or state is invalid");
  assertUuid(value.transactionId, "transactionId"); assertSha256(value.idempotencyHash, "idempotencyHash");
  assertInteger(value.revision, 1, Number.MAX_SAFE_INTEGER, "transaction.revision");
  assertUuid(value.sessionId, "transaction.sessionId");
  assertTimestamp(value.createdAt, "transaction.createdAt"); assertTimestamp(value.updatedAt, "transaction.updatedAt");
}

export function validateTransaction(value) {
  if (!isPlainObject(value)) throw new ValidationError("Transaction must be an object");
  if (value.kind === "ingestion") {
    assertExactKeys(value, ["schemaVersion", "kind", "transactionId", "idempotencyHash", "revision", "state", "sessionId", "releaseId", "releaseTag", "title", "recordedAt", "origin", "supersedesSessionId", "plan", "uploadedParts", "stagedManifest", "createdAt", "updatedAt"], "ingestion transaction");
    validateTransactionBase(value, "ingestion", ["uploading", "staged", "finalized", "discarded"]);
    if (value.sessionId !== value.transactionId || value.releaseTag !== `audio-session-${value.sessionId}`) throw new ValidationError("Ingestion identity is invalid");
    assertInteger(value.releaseId, 1, Number.MAX_SAFE_INTEGER, "transaction.releaseId");
    if (typeof value.title !== "string" || !value.title.trim() || value.title.length > 200) throw new ValidationError("Transaction title is invalid");
    assertTimestamp(value.recordedAt, "transaction.recordedAt", true);
    if (!['manual', 'device'].includes(value.origin)) throw new ValidationError("Transaction origin is invalid");
    if (value.supersedesSessionId !== null) assertUuid(value.supersedesSessionId, "transaction.supersedesSessionId");
    const plan = validateIngestionPlan(value.plan, MAX_PART_BYTES);
    if (!Array.isArray(value.uploadedParts)) throw new ValidationError("Uploaded parts must be an array");
    const uploaded = new Set();
    for (const part of value.uploadedParts) {
      assertExactKeys(part, ["blobId", "partNumber", "assetName", "sizeBytes", "sha256", "assetId", "downloadUrl"], "uploaded part");
      const blobId = assertUuid(part.blobId, "uploaded blobId");
      assertInteger(part.partNumber, 1, 9999, "uploaded partNumber");
      const planned = plan.tracks.find((track) => track.blobId === blobId)?.parts.find((item) => item.partNumber === part.partNumber);
      if (!planned || part.assetName !== planned.assetName || part.sizeBytes !== planned.sizeBytes || part.sha256 !== planned.sha256) throw new ValidationError("Uploaded part does not match plan");
      assertInteger(part.assetId, 1, Number.MAX_SAFE_INTEGER, "uploaded assetId");
      if (typeof part.downloadUrl !== "string" || !part.downloadUrl.startsWith(`https://github.com/meser-recovery/audio-archive/releases/download/${value.releaseTag}/`)) throw new ValidationError("Uploaded part URL is invalid");
      const slot = `${blobId}:${part.partNumber}`;
      if (uploaded.has(slot)) throw new ValidationError("Uploaded part slots must be unique");
      uploaded.add(slot);
    }
    if (value.stagedManifest !== null) {
      const manifest = validateSourceSession(value.stagedManifest);
      if (manifest.id !== value.sessionId || manifest.storage.releaseId !== value.releaseId) throw new ValidationError("Staged manifest does not match transaction");
    }
    if (value.state === "staged" && value.stagedManifest === null) throw new ValidationError("Staged transaction requires a manifest");
    return structuredClone(value);
  }
  if (value.kind === "pending_delete") {
    assertExactKeys(value, ["schemaVersion", "kind", "transactionId", "idempotencyHash", "revision", "state", "sessionId", "expectedRevision", "releaseId", "releaseTag", "action", "assetIds", "deletedAssetIds", "createdAt", "updatedAt"], "delete transaction");
    validateTransactionBase(value, "pending_delete", ["pending_delete", "complete"]);
    assertInteger(value.expectedRevision, 1, Number.MAX_SAFE_INTEGER, "expectedRevision");
    assertInteger(value.releaseId, 1, Number.MAX_SAFE_INTEGER, "releaseId");
    if (value.releaseTag !== `audio-session-${value.sessionId}`) throw new ValidationError("Delete release tag is invalid");
    const kind = value.action?.kind;
    const actionKeys = kind === "output-version" ? ["kind", "workflow", "version"] :
      kind === "output-series" ? ["kind", "workflow"] : ["kind"];
    assertExactKeys(value.action, actionKeys, "delete action");
    if (["output-version", "output-series"].includes(kind) && !WORKFLOWS.includes(value.action.workflow)) throw new ValidationError("Delete workflow is invalid");
    if (kind === "output-version") assertInteger(value.action.version, 1, Number.MAX_SAFE_INTEGER, "delete version");
    if (!["output-version", "output-series", "sources", "purge"].includes(kind)) throw new ValidationError("Delete action is invalid");
    if (!Array.isArray(value.assetIds) || !Array.isArray(value.deletedAssetIds)) throw new ValidationError("Delete asset lists are invalid");
    const assetIds = value.assetIds.map((id) => assertInteger(id, 1, Number.MAX_SAFE_INTEGER, "assetId"));
    const deletedIds = value.deletedAssetIds.map((id) => assertInteger(id, 1, Number.MAX_SAFE_INTEGER, "deletedAssetId"));
    if (new Set(assetIds).size !== assetIds.length || new Set(deletedIds).size !== deletedIds.length || deletedIds.some((id) => !assetIds.includes(id))) {
      throw new ValidationError("Delete asset progress is invalid");
    }
    return structuredClone(value);
  }
  throw new ValidationError("Unknown transaction kind");
}
