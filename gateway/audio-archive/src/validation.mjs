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
export const PUBLICATION_STATES = Object.freeze(["uploading", "cancelled", "finalized", "discarded"]);

export function canonicalReleaseAssetUrl(releaseTag, assetName) {
  return `https://github.com/meser-recovery/audio-archive/releases/download/${releaseTag}/${assetName}`;
}

function escapeRegularExpression(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function normalizeUploadedPartUrl(value, part) {
  const canonical = canonicalReleaseAssetUrl(value.releaseTag, part.assetName);
  if (part.downloadUrl === canonical) return canonical;
  if (!["uploading", "staged"].includes(value.state) || typeof part.downloadUrl !== "string") {
    throw new ValidationError("Uploaded part URL is invalid");
  }
  let parsed;
  try { parsed = new URL(part.downloadUrl); } catch { throw new ValidationError("Uploaded part URL is invalid"); }
  const legacy = new RegExp(`^https://github\\.com/meser-recovery/audio-archive/releases/download/untagged-[0-9a-f]{20}/${escapeRegularExpression(part.assetName)}$`);
  if (!legacy.test(part.downloadUrl) || parsed.protocol !== "https:" || parsed.hostname !== "github.com" || parsed.host !== "github.com" ||
      parsed.username || parsed.password || parsed.port || parsed.search || parsed.hash) {
    throw new ValidationError("Uploaded part URL is invalid");
  }
  return canonical;
}

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

export function recipePath(sessionId, outputId) {
  const session = assertUuid(sessionId, "sessionId");
  const output = assertUuid(outputId, "outputId");
  return `recipes/${session}/announcement/${output}.json`;
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

function assertFinite(value, minimum, maximum, label) {
  if (!Number.isFinite(value) || value < minimum || value > maximum) throw new ValidationError(`${label} is out of range`);
  return value;
}

function validateIntervals(value, label) {
  if (!Array.isArray(value) || value.length > 10000) throw new ValidationError(`${label} must be a bounded array`);
  let previousEnd = 0;
  for (const [index, interval] of value.entries()) {
    if (!Array.isArray(interval) || interval.length !== 2) throw new ValidationError(`${label}[${index}] is invalid`);
    const start = assertFinite(interval[0], 0, 7 * 24 * 60 * 60, `${label}[${index}].start`);
    const end = assertFinite(interval[1], 0, 7 * 24 * 60 * 60, `${label}[${index}].end`);
    if (end <= start || (index && start < previousEnd)) throw new ValidationError(`${label} order is invalid`);
    previousEnd = end;
  }
}

export function validateAnnouncementDraftPayload(value) {
  assertExactKeys(value, ["trackIds"], "announcement draft payload");
  if (!Array.isArray(value.trackIds) || !value.trackIds.length || value.trackIds.length > 32) {
    throw new ValidationError("Announcement draft must contain one to 32 track IDs");
  }
  const ids = value.trackIds.map((id) => assertUuid(id, "announcement draft trackId"));
  if (new Set(ids).size !== ids.length) throw new ValidationError("Announcement draft track IDs must be unique");
  return { trackIds: ids };
}

function validateRecipeSources(sources) {
  if (!Array.isArray(sources) || !sources.length || sources.length > 32) throw new ValidationError("Recipe sources are invalid");
  const trackIds = new Set();
  const blobIds = new Set();
  for (const [index, source] of sources.entries()) {
    assertExactKeys(source, ["trackId", "blobId", "ordinal", "sizeBytes", "sha256", "mediaType"], "recipe source");
    const trackId = assertUuid(source.trackId, "recipe trackId");
    const blobId = assertUuid(source.blobId, "recipe blobId");
    if (trackIds.has(trackId) || blobIds.has(blobId)) throw new ValidationError("Recipe source identities must be unique");
    trackIds.add(trackId); blobIds.add(blobId);
    if (source.ordinal !== index + 1) throw new ValidationError("Recipe source order is invalid");
    assertInteger(source.sizeBytes, 1, MAX_SESSION_BYTES, "recipe source sizeBytes");
    assertSha256(source.sha256, "recipe source sha256");
    if (!Object.values(MEDIA_TYPES).includes(source.mediaType)) throw new ValidationError("Recipe source media type is invalid");
  }
}

function validateProcessing(value) {
  assertExactKeys(value, ["mode", "silenceThresholdDb", "minimumSilenceSeconds", "retainedSilenceSeconds", "detectedIntervals", "removalRanges", "mix", "limiter", "codec"], "recipe processing");
  if (!["passthrough", "processed_single", "mixed_multi"].includes(value.mode)) throw new ValidationError("Processing mode is invalid");
  if (value.silenceThresholdDb !== -45 || value.minimumSilenceSeconds !== 2 || value.retainedSilenceSeconds !== 0.35) {
    throw new ValidationError("Processing settings do not match the accepted S07 contract");
  }
  validateIntervals(value.detectedIntervals, "detectedIntervals");
  validateIntervals(value.removalRanges, "removalRanges");
  if (value.mode === "passthrough") {
    if (value.removalRanges.length || value.mix !== null || value.limiter !== null || value.codec !== null) {
      throw new ValidationError("Passthrough recipe cannot claim processing that did not occur");
    }
  } else {
    if (value.mode === "processed_single" && value.mix !== null) throw new ValidationError("Single-track recipe cannot contain mix settings");
    if (value.mode === "mixed_multi" && (value.mix !== "amix=normalize=0" || value.limiter !== "alimiter=limit=0.95:level=0:latency=1")) {
      throw new ValidationError("Multi-track mix settings are invalid");
    }
    if (value.mode === "processed_single" && value.limiter !== null) throw new ValidationError("Single-track recipe cannot contain limiter settings");
    assertExactKeys(value.codec, ["name", "bitrate"], "recipe codec");
    if (value.codec.name !== "libmp3lame" || value.codec.bitrate !== "128k") throw new ValidationError("Recipe codec settings are invalid");
  }
}

function validateRecipeResult(value) {
  assertExactKeys(value, ["mediaType", "presentationFilename", "sizeBytes", "sha256", "originalDurationSeconds", "resultDurationSeconds", "removedDurationSeconds", "pauseCount"], "recipe result");
  if (!Object.values(MEDIA_TYPES).includes(value.mediaType)) throw new ValidationError("Recipe result media type is invalid");
  if (value.presentationFilename !== normalizeFilename(value.presentationFilename)) throw new ValidationError("Recipe presentation filename is invalid");
  assertInteger(value.sizeBytes, 1, MAX_SESSION_BYTES, "recipe result sizeBytes");
  assertSha256(value.sha256, "recipe result sha256");
  assertFinite(value.originalDurationSeconds, 0, 7 * 24 * 60 * 60, "originalDurationSeconds");
  assertFinite(value.resultDurationSeconds, 0, 7 * 24 * 60 * 60, "resultDurationSeconds");
  assertFinite(value.removedDurationSeconds, 0, 7 * 24 * 60 * 60, "removedDurationSeconds");
  assertInteger(value.pauseCount, 0, 10000, "pauseCount");
}

export function validateAnnouncementRecipe(recipe) {
  assertExactKeys(recipe, ["schemaVersion", "workflow", "sessionId", "outputId", "version", "processorVersion", "createdAt", "sourceSessionRevision", "sources", "draft", "processing", "result"], "announcement recipe");
  if (recipe.schemaVersion !== SCHEMA_VERSION || recipe.workflow !== "announcement") throw new ValidationError("Announcement recipe identity is invalid");
  assertUuid(recipe.sessionId, "recipe sessionId");
  assertUuid(recipe.outputId, "recipe outputId");
  assertInteger(recipe.version, 1, Number.MAX_SAFE_INTEGER, "recipe version");
  if (typeof recipe.processorVersion !== "string" || !/^s07(?:[-.][a-z0-9]+)*$/i.test(recipe.processorVersion)) throw new ValidationError("processorVersion is invalid");
  assertTimestamp(recipe.createdAt, "recipe createdAt");
  assertInteger(recipe.sourceSessionRevision, 1, Number.MAX_SAFE_INTEGER, "recipe sourceSessionRevision");
  validateRecipeSources(recipe.sources);
  assertExactKeys(recipe.draft, ["revision", "payloadSchema", "payload"], "recipe draft");
  assertInteger(recipe.draft.revision, 0, Number.MAX_SAFE_INTEGER, "recipe draft revision");
  if (recipe.draft.payloadSchema !== "announcement/v1") throw new ValidationError("Announcement draft schema is invalid");
  validateAnnouncementDraftPayload(recipe.draft.payload);
  validateProcessing(recipe.processing);
  validateRecipeResult(recipe.result);
  if ((recipe.processing.mode === "mixed_multi") !== (recipe.sources.length > 1)) throw new ValidationError("Processing mode does not match source count");
  if (recipe.processing.mode !== "passthrough" && recipe.result.mediaType !== MEDIA_TYPES.mp3) throw new ValidationError("Processed Announcement output must be MP3");
  return structuredClone(recipe);
}

export function validatePublicationPlan(plan, acceptedPartBytes = DEFAULT_PART_BYTES) {
  assertInteger(acceptedPartBytes, 1, MAX_PART_BYTES, "acceptedPartBytes");
  assertExactKeys(plan, ["outputId", "blobId", "processorVersion", "sizeBytes", "sha256", "parts", "recipe"], "publication plan");
  const outputId = assertUuid(plan.outputId, "outputId");
  const blobId = assertUuid(plan.blobId, "blobId");
  if (typeof plan.processorVersion !== "string" || !/^s07(?:[-.][a-z0-9]+)*$/i.test(plan.processorVersion)) throw new ValidationError("processorVersion is invalid");
  assertInteger(plan.sizeBytes, 1, MAX_SESSION_BYTES, "publication sizeBytes");
  assertSha256(plan.sha256, "publication sha256");
  if (!Array.isArray(plan.parts) || !plan.parts.length || plan.parts.length > 9999) throw new ValidationError("Publication parts are invalid");
  const partBytes = plan.parts.reduce((sum, part, index) => sum + validatePlannedPart(part, blobId, index + 1, acceptedPartBytes), 0);
  if (partBytes !== plan.sizeBytes) throw new ValidationError("Publication part sizes do not match logical size");
  assertExactKeys(plan.recipe, ["sourceSessionRevision", "sources", "draft", "processing", "result"], "publication recipe template");
  assertInteger(plan.recipe.sourceSessionRevision, 1, Number.MAX_SAFE_INTEGER, "recipe sourceSessionRevision");
  validateRecipeSources(plan.recipe.sources);
  assertExactKeys(plan.recipe.draft, ["revision", "payloadSchema", "payload"], "recipe draft");
  assertInteger(plan.recipe.draft.revision, 0, Number.MAX_SAFE_INTEGER, "recipe draft revision");
  if (plan.recipe.draft.payloadSchema !== "announcement/v1") throw new ValidationError("Announcement draft schema is invalid");
  validateAnnouncementDraftPayload(plan.recipe.draft.payload);
  validateProcessing(plan.recipe.processing);
  validateRecipeResult(plan.recipe.result);
  if ((plan.recipe.processing.mode === "mixed_multi") !== (plan.recipe.sources.length > 1)) throw new ValidationError("Processing mode does not match source count");
  if (plan.recipe.result.sizeBytes !== plan.sizeBytes || plan.recipe.result.sha256 !== plan.sha256) throw new ValidationError("Publication result does not match its plan");
  if (plan.recipe.processing.mode !== "passthrough" && plan.recipe.result.mediaType !== MEDIA_TYPES.mp3) throw new ValidationError("Processed Announcement output must be MP3");
  if (outputId === blobId) throw new ValidationError("Output and blob identities must be distinct");
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
    const normalized = structuredClone(value);
    const uploaded = new Set();
    for (const part of normalized.uploadedParts) {
      assertExactKeys(part, ["blobId", "partNumber", "assetName", "sizeBytes", "sha256", "assetId", "downloadUrl"], "uploaded part");
      const blobId = assertUuid(part.blobId, "uploaded blobId");
      assertInteger(part.partNumber, 1, 9999, "uploaded partNumber");
      const planned = plan.tracks.find((track) => track.blobId === blobId)?.parts.find((item) => item.partNumber === part.partNumber);
      if (!planned || part.assetName !== planned.assetName || part.sizeBytes !== planned.sizeBytes || part.sha256 !== planned.sha256) throw new ValidationError("Uploaded part does not match plan");
      assertInteger(part.assetId, 1, Number.MAX_SAFE_INTEGER, "uploaded assetId");
      part.downloadUrl = normalizeUploadedPartUrl(normalized, part);
      const slot = `${blobId}:${part.partNumber}`;
      if (uploaded.has(slot)) throw new ValidationError("Uploaded part slots must be unique");
      uploaded.add(slot);
    }
    if (value.stagedManifest !== null) {
      const manifest = validateSourceSession(value.stagedManifest);
      if (manifest.id !== value.sessionId || manifest.storage.releaseId !== value.releaseId) throw new ValidationError("Staged manifest does not match transaction");
    }
    if (value.state === "staged" && value.stagedManifest === null) throw new ValidationError("Staged transaction requires a manifest");
    return normalized;
  }
  if (value.kind === "publication") {
    assertExactKeys(value, ["schemaVersion", "kind", "transactionId", "idempotencyHash", "requestFingerprint", "revision", "state", "sessionId", "workflow", "outputId", "blobId", "expectedRevision", "reservedSessionRevision", "reservedVersion", "releaseId", "releaseTag", "plan", "uploadedParts", "recipeSnapshot", "outputDescriptor", "failure", "createdAt", "updatedAt"], "publication transaction");
    validateTransactionBase(value, "publication", PUBLICATION_STATES);
    assertSha256(value.requestFingerprint, "requestFingerprint");
    if (value.workflow !== "announcement") throw new ValidationError("Publication workflow is invalid");
    if (assertUuid(value.outputId, "publication outputId") !== value.plan?.outputId ||
        assertUuid(value.blobId, "publication blobId") !== value.plan?.blobId) throw new ValidationError("Publication identities do not match plan");
    assertInteger(value.expectedRevision, 1, Number.MAX_SAFE_INTEGER, "publication expectedRevision");
    assertInteger(value.reservedSessionRevision, value.expectedRevision + 1, Number.MAX_SAFE_INTEGER, "publication reservedSessionRevision");
    assertInteger(value.reservedVersion, 1, Number.MAX_SAFE_INTEGER, "publication reservedVersion");
    assertInteger(value.releaseId, 1, Number.MAX_SAFE_INTEGER, "publication releaseId");
    if (value.releaseTag !== `audio-session-${value.sessionId}`) throw new ValidationError("Publication release tag is invalid");
    const plan = validatePublicationPlan(value.plan, MAX_PART_BYTES);
    const recipe = validateAnnouncementRecipe(value.recipeSnapshot);
    if (recipe.sessionId !== value.sessionId || recipe.outputId !== value.outputId || recipe.version !== value.reservedVersion ||
        recipe.processorVersion !== plan.processorVersion || recipe.sourceSessionRevision !== value.expectedRevision) {
      throw new ValidationError("Publication recipe identity is invalid");
    }
    if (!Array.isArray(value.uploadedParts)) throw new ValidationError("Publication uploaded parts are invalid");
    const slots = new Set();
    for (const part of value.uploadedParts) {
      assertExactKeys(part, ["blobId", "partNumber", "assetName", "sizeBytes", "sha256", "assetId", "downloadUrl"], "publication uploaded part");
      if (part.blobId !== value.blobId) throw new ValidationError("Publication uploaded blob is invalid");
      assertInteger(part.partNumber, 1, 9999, "publication partNumber");
      const planned = plan.parts.find((item) => item.partNumber === part.partNumber);
      if (!planned || part.assetName !== planned.assetName || part.sizeBytes !== planned.sizeBytes || part.sha256 !== planned.sha256) {
        throw new ValidationError("Publication uploaded part does not match plan");
      }
      assertInteger(part.assetId, 1, Number.MAX_SAFE_INTEGER, "publication assetId");
      if (part.downloadUrl !== canonicalReleaseAssetUrl(value.releaseTag, part.assetName)) throw new ValidationError("Publication asset URL is invalid");
      if (slots.has(part.partNumber)) throw new ValidationError("Publication part slots must be unique");
      slots.add(part.partNumber);
    }
    if (value.outputDescriptor !== null) {
      validateOutput(value.outputDescriptor, value.sessionId);
      if (value.outputDescriptor.outputId !== value.outputId || value.outputDescriptor.version !== value.reservedVersion ||
          value.outputDescriptor.blobId !== value.blobId || value.outputDescriptor.recipeSnapshotRef !== recipePath(value.sessionId, value.outputId)) {
        throw new ValidationError("Publication output descriptor is invalid");
      }
    }
    if (value.state === "finalized" && (value.outputDescriptor === null || value.uploadedParts.length !== plan.parts.length)) {
      throw new ValidationError("Finalized publication requires a complete output descriptor");
    }
    if (value.state !== "finalized" && value.outputDescriptor !== null) throw new ValidationError("Incomplete publication cannot expose an output descriptor");
    if (value.failure !== null) {
      assertExactKeys(value.failure, ["code", "message", "at"], "publication failure");
      if (typeof value.failure.code !== "string" || typeof value.failure.message !== "string") throw new ValidationError("Publication failure metadata is invalid");
      assertTimestamp(value.failure.at, "publication failure.at");
    }
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
