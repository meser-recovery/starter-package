import { createHash, randomUUID, timingSafeEqual } from "node:crypto";
import { isDeepStrictEqual } from "node:util";
import {
  SCHEMA_VERSION, MAX_PART_BYTES, WORKFLOWS, ValidationError, assertExactKeys, assertInteger, assertSha256,
  assertTimestamp, assertUuid, assetName, catalogEntry, hashIdempotencyKey, normalizeFilename, normalizeMediaType,
  uuidFromIdempotencyKey, validateCatalog, validateDraft, validateIngestionPlan, validateSourceSession, validateTombstone, validateTransaction
} from "./validation.mjs";

function conflict(message = "Canonical state changed; reload and retry") {
  const error = new Error(message);
  error.status = 409;
  return error;
}

function notFound(message = "Source Session not found") {
  const error = new Error(message);
  error.status = 404;
  return error;
}

function nowIso(clock) {
  return new Date(clock()).toISOString();
}

function safeTitle(value) {
  if (typeof value !== "string" || !value.trim() || value.trim().length > 200) throw new ValidationError("Title must contain 1 to 200 characters");
  return value.trim();
}

function emptyCatalog() {
  return { schemaVersion: SCHEMA_VERSION, revision: 0, updatedAt: null, entries: [] };
}

function workflowState(name) {
  return { workflow: name, status: "new", currentDraft: null, outputs: [], deletedVersions: [], nextVersion: 1 };
}

function transactionPath(kind, transactionId) {
  return `transactions/${kind}-${assertUuid(transactionId, "transactionId")}.json`;
}

function sessionPath(sessionId) {
  return `sessions/${assertUuid(sessionId, "sessionId")}.json`;
}

function draftPath(sessionId, workflow) {
  assertUuid(sessionId, "sessionId");
  if (!WORKFLOWS.includes(workflow)) throw new ValidationError("Unknown workflow");
  return `drafts/${sessionId}/${workflow}.json`;
}

function publicSession(session) {
  validateSourceSession(session);
  return structuredClone(session);
}

function digestBytes(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

function sameDigest(left, right) {
  if (typeof left !== "string" || typeof right !== "string") return false;
  const a = Buffer.from(left); const b = Buffer.from(right);
  return a.length === b.length && timingSafeEqual(a, b);
}

function sameAction(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function sameIngestionRequest(transaction, request) {
  return transaction.title === request.title && transaction.recordedAt === request.recordedAt &&
    transaction.origin === request.origin && transaction.supersedesSessionId === request.supersedesSessionId &&
    isDeepStrictEqual(transaction.plan, request.plan);
}

export class AudioArchiveDomain {
  constructor(repository, { acceptedPartBytes, clock = () => Date.now() }) {
    this.repository = repository;
    this.acceptedPartBytes = acceptedPartBytes;
    this.clock = clock;
  }

  async snapshot() {
    const head = await this.repository.getHead();
    const stored = await this.repository.readJson("catalog.json", head);
    return { head, catalog: stored ? validateCatalog(stored.data) : emptyCatalog() };
  }

  async sessionSnapshot(sessionId) {
    const head = await this.repository.getHead();
    const stored = await this.repository.readJson(sessionPath(sessionId), head);
    if (!stored) throw notFound();
    if (stored.data?.kind === "deletion_tombstone") throw notFound("Source Session was permanently deleted");
    return { head, session: validateSourceSession(stored.data) };
  }

  async listSessions(lifecycle) {
    if (!["incoming", "archived"].includes(lifecycle)) throw new ValidationError("Invalid lifecycle filter");
    const { head, catalog } = await this.snapshot();
    const sessions = [];
    for (const entry of catalog.entries) {
      const stored = await this.repository.readJson(sessionPath(entry.id), head);
      if (!stored || stored.data?.kind === "deletion_tombstone") continue;
      const session = validateSourceSession(stored.data);
      if (session.lifecycle.state === lifecycle) sessions.push(publicSession(session));
    }
    sessions.sort((left, right) => Date.parse(right.createdAt) - Date.parse(left.createdAt) || left.title.localeCompare(right.title, "ru"));
    return { revision: catalog.revision, sessions };
  }

  async getSession(sessionId) {
    return publicSession((await this.sessionSnapshot(sessionId)).session);
  }

  async beginIngestion(body) {
    assertExactKeys(body, ["schemaVersion", "idempotencyKey", "title", "recordedAt", "origin", "supersedesSessionId", "plan"], "begin ingestion");
    if (body.schemaVersion !== SCHEMA_VERSION) throw new ValidationError("Unsupported ingestion schema");
    const idempotencyHash = hashIdempotencyKey(body.idempotencyKey);
    const transactionId = uuidFromIdempotencyKey(body.idempotencyKey);
    const path = transactionPath("ingest", transactionId);
    const title = safeTitle(body.title);
    const recordedAt = body.recordedAt === null ? null : assertTimestamp(body.recordedAt, "recordedAt");
    if (!["manual", "device"].includes(body.origin)) throw new ValidationError("Browser ingestion origin is invalid");
    const supersedesSessionId = body.supersedesSessionId === null ? null : assertUuid(body.supersedesSessionId, "supersedesSessionId");
    const plan = validateIngestionPlan(body.plan, this.acceptedPartBytes);
    const immutableRequest = { title, recordedAt, origin: body.origin, supersedesSessionId, plan };
    let head = await this.repository.getHead();
    const existing = await this.repository.readJson(path, head);
    if (existing) {
      const transaction = validateTransaction(existing.data);
      if (transaction.idempotencyHash !== idempotencyHash || !sameIngestionRequest(transaction, immutableRequest)) {
        throw conflict("Idempotency transaction request mismatch");
      }
      return { transactionId, sessionId: transaction.sessionId, releaseId: transaction.releaseId, state: transaction.state };
    }
    const sessionId = transactionId;
    const releaseTag = `audio-session-${sessionId}`;
    const release = await this.repository.createDraftRelease(releaseTag);
    head = await this.repository.getHead();
    const raced = await this.repository.readJson(path, head);
    if (raced) {
      const transaction = validateTransaction(raced.data);
      if (transaction.idempotencyHash !== idempotencyHash || !sameIngestionRequest(transaction, immutableRequest)) {
        throw conflict("Idempotency transaction request mismatch");
      }
      return { transactionId, sessionId: transaction.sessionId, releaseId: transaction.releaseId, state: transaction.state };
    }
    const timestamp = nowIso(this.clock);
    const transaction = {
      schemaVersion: SCHEMA_VERSION, kind: "ingestion", transactionId, idempotencyHash, revision: 1, state: "uploading",
      sessionId, releaseId: release.id, releaseTag, title, recordedAt, origin: body.origin, supersedesSessionId,
      plan, uploadedParts: [], stagedManifest: null, createdAt: timestamp, updatedAt: timestamp
    };
    await this.repository.commitJson(head, { [path]: transaction }, `Begin audio ingestion ${sessionId}`);
    return { transactionId, sessionId, releaseId: release.id, state: transaction.state };
  }

  async ingestionSnapshot(transactionId) {
    const head = await this.repository.getHead();
    const path = transactionPath("ingest", transactionId);
    const stored = await this.repository.readJson(path, head);
    if (!stored || stored.data?.kind !== "ingestion") throw notFound("Ingestion transaction not found");
    return { head, path, transaction: validateTransaction(stored.data) };
  }

  async uploadPart(transactionId, blobId, partNumber, bytes, suppliedHash, idempotencyKey) {
    const id = assertUuid(blobId, "blobId");
    assertInteger(partNumber, 1, 9999, "partNumber");
    hashIdempotencyKey(idempotencyKey);
    if (!Buffer.isBuffer(bytes) || bytes.byteLength < 1 || bytes.byteLength > Math.min(this.acceptedPartBytes, MAX_PART_BYTES)) throw new ValidationError("Part body size is invalid");
    const hash = assertSha256(suppliedHash, "X-Part-SHA256");
    const actual = digestBytes(bytes);
    if (!sameDigest(hash, actual)) throw new ValidationError("Part SHA-256 does not match its bytes");
    let { head, path, transaction } = await this.ingestionSnapshot(transactionId);
    if (!["uploading", "staged"].includes(transaction.state)) {
      if (transaction.state === "finalized") return { uploaded: true, finalized: true };
      throw conflict("Ingestion is not accepting parts");
    }
    const track = transaction.plan.tracks.find((item) => item.blobId === id);
    const planned = track?.parts.find((item) => item.partNumber === partNumber);
    if (!planned || planned.sizeBytes !== bytes.byteLength || !sameDigest(planned.sha256, hash)) throw new ValidationError("Part does not match ingestion plan");
    const already = transaction.uploadedParts.find((item) => item.blobId === id && item.partNumber === partNumber);
    if (already) {
      if (already.sizeBytes !== bytes.byteLength || !sameDigest(already.sha256, hash)) throw conflict("A different part already occupies this slot");
      return { uploaded: true, assetId: already.assetId, downloadUrl: already.downloadUrl };
    }
    const name = assetName(id, partNumber);
    const assets = await this.repository.listReleaseAssets(transaction.releaseId);
    let asset = assets.find((item) => item.name === name);
    if (asset) {
      if (asset.size !== bytes.byteLength || !sameDigest(String(asset.digest || "").replace(/^sha256:/, ""), hash)) throw conflict("Existing release asset does not match the planned part");
    } else {
      asset = await this.repository.uploadReleaseAsset(transaction.releaseId, name, bytes);
    }
    if (asset.size !== bytes.byteLength || (asset.digest && !sameDigest(String(asset.digest).replace(/^sha256:/, ""), hash))) throw new Error("GitHub asset integrity response did not match upload");
    transaction = structuredClone(transaction);
    transaction.revision++;
    transaction.updatedAt = nowIso(this.clock);
    transaction.uploadedParts.push({ blobId: id, partNumber, assetName: name, sizeBytes: bytes.byteLength, sha256: hash, assetId: asset.id, downloadUrl: asset.browser_download_url });
    transaction.uploadedParts.sort((left, right) => left.blobId.localeCompare(right.blobId) || left.partNumber - right.partNumber);
    await this.repository.commitJson(head, { [path]: transaction }, `Record audio part ${transaction.sessionId} ${name}`);
    return { uploaded: true, assetId: asset.id, downloadUrl: asset.browser_download_url };
  }

  buildManifest(transaction) {
    const timestamp = nowIso(this.clock);
    const sourceTracks = transaction.plan.tracks.map((track) => ({
      ...track,
      parts: track.parts.map((part) => {
        const uploaded = transaction.uploadedParts.find((item) => item.blobId === track.blobId && item.partNumber === part.partNumber);
        if (!uploaded) throw conflict("Ingestion is incomplete");
        return { ...part, assetId: uploaded.assetId, downloadUrl: uploaded.downloadUrl };
      })
    }));
    return {
      schemaVersion: SCHEMA_VERSION, revision: 1, id: transaction.sessionId, title: transaction.title, recordedAt: transaction.recordedAt,
      createdAt: transaction.createdAt, updatedAt: timestamp, origin: { kind: transaction.origin, externalId: null },
      storage: { releaseId: transaction.releaseId, tag: transaction.releaseTag }, lifecycle: { state: "incoming" },
      sourceState: "available", sourceTracks, deletedSources: null,
      workflows: { announcement: workflowState("announcement"), speaker: workflowState("speaker") },
      relations: { supersedesSessionId: transaction.supersedesSessionId, supersededBySessionId: null },
      transaction: { state: "finalized", id: transaction.transactionId }
    };
  }

  async finalizeIngestion(transactionId) {
    let { head, path, transaction } = await this.ingestionSnapshot(transactionId);
    const existing = await this.repository.readJson(sessionPath(transaction.sessionId), head);
    if (existing && existing.data?.kind !== "deletion_tombstone") return { session: publicSession(existing.data), idempotent: true };
    const requiredCount = transaction.plan.tracks.reduce((sum, track) => sum + track.parts.length, 0);
    if (transaction.uploadedParts.length !== requiredCount) throw conflict("All planned parts must upload before finalization");
    const assets = await this.repository.listReleaseAssets(transaction.releaseId);
    for (const uploaded of transaction.uploadedParts) {
      const asset = assets.find((item) => item.id === uploaded.assetId && item.name === uploaded.assetName);
      if (!asset || asset.size !== uploaded.sizeBytes || !sameDigest(String(asset.digest || "").replace(/^sha256:/, ""), uploaded.sha256)) {
        throw conflict("Release assets failed final integrity verification");
      }
    }
    if (transaction.state === "uploading") {
      transaction = structuredClone(transaction);
      transaction.state = "staged";
      transaction.revision++;
      transaction.updatedAt = nowIso(this.clock);
      transaction.stagedManifest = this.buildManifest(transaction);
      await this.repository.commitJson(head, { [path]: transaction }, `Stage audio session ${transaction.sessionId}`);
      ({ head, transaction } = await this.ingestionSnapshot(transactionId));
    }
    await this.repository.publishRelease(transaction.releaseId);
    const catalogStored = await this.repository.readJson("catalog.json", head);
    const catalog = catalogStored ? validateCatalog(catalogStored.data) : emptyCatalog();
    const session = validateSourceSession(transaction.stagedManifest || this.buildManifest(transaction));
    const nextCatalog = this.catalogWithSession(catalog, session);
    transaction = { ...transaction, state: "finalized", revision: transaction.revision + 1, updatedAt: nowIso(this.clock), stagedManifest: null };
    await this.repository.commitJson(head, {
      [sessionPath(session.id)]: session,
      "catalog.json": nextCatalog,
      [path]: transaction
    }, `Finalize audio session ${session.id}`);
    return { session: publicSession(session), idempotent: false };
  }

  catalogWithSession(catalog, session) {
    const entries = catalog.entries.filter((entry) => entry.id !== session.id);
    entries.push(catalogEntry(session));
    entries.sort((left, right) => left.id.localeCompare(right.id));
    return { schemaVersion: SCHEMA_VERSION, revision: catalog.revision + 1, updatedAt: nowIso(this.clock), entries };
  }

  async commitSession(head, session, catalog, message, extraFiles = {}) {
    validateSourceSession(session);
    const nextCatalog = this.catalogWithSession(catalog, session);
    await this.repository.commitJson(head, { [sessionPath(session.id)]: session, "catalog.json": nextCatalog, ...extraFiles }, message);
    return publicSession(session);
  }

  async mutateSession(sessionId, expectedRevision, mutation, message, extraFiles = {}) {
    const { head, session } = await this.sessionSnapshot(sessionId);
    assertInteger(expectedRevision, 1, Number.MAX_SAFE_INTEGER, "expectedRevision");
    if (session.revision !== expectedRevision) throw conflict();
    const catalogStored = await this.repository.readJson("catalog.json", head);
    const catalog = catalogStored ? validateCatalog(catalogStored.data) : emptyCatalog();
    const next = structuredClone(session);
    mutation(next);
    next.revision++;
    next.updatedAt = nowIso(this.clock);
    return this.commitSession(head, next, catalog, message, extraFiles);
  }

  async updateMetadata(sessionId, body) {
    assertExactKeys(body, ["expectedRevision", "patch", "idempotencyKey"], "metadata update");
    hashIdempotencyKey(body.idempotencyKey);
    assertExactKeys(body.patch, ["title", "recordedAt", "supersedesSessionId", "supersededBySessionId"], "metadata patch");
    return this.mutateSession(sessionId, body.expectedRevision, (session) => {
      if (Object.hasOwn(body.patch, "title")) session.title = safeTitle(body.patch.title);
      if (Object.hasOwn(body.patch, "recordedAt")) session.recordedAt = body.patch.recordedAt === null ? null : assertTimestamp(body.patch.recordedAt, "recordedAt");
      for (const key of ["supersedesSessionId", "supersededBySessionId"]) if (Object.hasOwn(body.patch, key)) {
        session.relations[key] = body.patch[key] === null ? null : assertUuid(body.patch[key], key);
      }
    }, `Update audio session metadata ${sessionId}`);
  }

  async updateWorkflow(sessionId, workflow, body) {
    if (!WORKFLOWS.includes(workflow)) throw new ValidationError("Unknown workflow");
    assertExactKeys(body, ["expectedRevision", "status", "idempotencyKey"], "workflow update");
    hashIdempotencyKey(body.idempotencyKey);
    if (!["new", "in_progress"].includes(body.status)) throw new ValidationError("S08A cannot manually set result_ready");
    return this.mutateSession(sessionId, body.expectedRevision, (session) => { session.workflows[workflow].status = body.status; },
      `Update ${workflow} workflow ${sessionId}`);
  }

  async setLifecycle(sessionId, target, body) {
    assertExactKeys(body, ["expectedRevision", "idempotencyKey"], "lifecycle update");
    hashIdempotencyKey(body.idempotencyKey);
    if (!["incoming", "archived"].includes(target)) throw new ValidationError("Invalid lifecycle");
    return this.mutateSession(sessionId, body.expectedRevision, (session) => { session.lifecycle.state = target; }, `${target} audio session ${sessionId}`);
  }

  async loadDraft(sessionId, workflow) {
    const path = draftPath(sessionId, workflow);
    const head = await this.repository.getHead();
    const stored = await this.repository.readJson(path, head);
    return stored ? validateDraft(stored.data) : null;
  }

  async saveDraft(sessionId, workflow, body) {
    assertExactKeys(body, ["schemaVersion", "expectedDraftRevision", "expectedSourceSessionRevision", "payloadSchema", "payload", "idempotencyKey"], "draft save");
    if (body.schemaVersion !== SCHEMA_VERSION) throw new ValidationError("Unsupported draft schema");
    hashIdempotencyKey(body.idempotencyKey);
    const path = draftPath(sessionId, workflow);
    const { head, session } = await this.sessionSnapshot(sessionId);
    if (session.revision !== body.expectedSourceSessionRevision) throw conflict("Source Session changed; reload before saving draft");
    const existing = await this.repository.readJson(path, head);
    const currentRevision = existing ? validateDraft(existing.data).draftRevision : 0;
    if (body.expectedDraftRevision !== currentRevision) throw conflict("Draft changed; reload before saving");
    if (typeof body.payloadSchema !== "string" || body.payloadSchema.length > 100) throw new ValidationError("payloadSchema is invalid");
    const draft = validateDraft({
      schemaVersion: SCHEMA_VERSION, sessionId, workflow, draftRevision: currentRevision + 1,
      sourceSessionRevision: session.revision + 1, savedAt: nowIso(this.clock), payloadSchema: body.payloadSchema,
      payload: structuredClone(body.payload)
    });
    const catalogStored = await this.repository.readJson("catalog.json", head);
    const catalog = catalogStored ? validateCatalog(catalogStored.data) : emptyCatalog();
    const next = structuredClone(session);
    next.workflows[workflow].currentDraft = { path, revision: draft.draftRevision };
    next.revision++;
    next.updatedAt = nowIso(this.clock);
    const committed = await this.commitSession(head, next, catalog, `Save ${workflow} draft ${sessionId}`, { [path]: draft });
    return { draft, session: committed };
  }

  async dependencyPreview(sessionId) {
    const { head, session } = await this.sessionSnapshot(sessionId);
    const drafts = [];
    for (const workflow of WORKFLOWS) if (await this.repository.readJson(draftPath(sessionId, workflow), head)) drafts.push(workflow);
    return {
      sessionId, revision: session.revision, sourceTracks: session.sourceTracks.length,
      announcementVersions: session.workflows.announcement.outputs.length,
      speakerVersions: session.workflows.speaker.outputs.length,
      drafts: drafts.length, draftWorkflows: drafts
    };
  }

  selectDeleteAssets(session, action) {
    if (action.kind === "output-version") {
      if (!WORKFLOWS.includes(action.workflow)) throw new ValidationError("Unknown workflow");
      const output = session.workflows[action.workflow].outputs.find((item) => item.version === action.version);
      if (!output) throw notFound("Output version not found");
      return output.parts.map((part) => part.assetId);
    }
    if (action.kind === "output-series") {
      if (!WORKFLOWS.includes(action.workflow)) throw new ValidationError("Unknown workflow");
      return session.workflows[action.workflow].outputs.flatMap((output) => output.parts.map((part) => part.assetId));
    }
    if (action.kind === "sources") return session.sourceTracks.flatMap((track) => track.parts.map((part) => part.assetId));
    if (action.kind === "purge") return [];
    throw new ValidationError("Unknown deletion level");
  }

  async beginDelete(sessionId, body, action) {
    assertExactKeys(body, ["expectedRevision", "idempotencyKey", "confirmation"], "delete request");
    const idempotencyHash = hashIdempotencyKey(body.idempotencyKey);
    const transactionId = uuidFromIdempotencyKey(`delete:${sessionId}:${body.idempotencyKey}`);
    const path = transactionPath("delete", transactionId);
    let { head, session } = await this.sessionSnapshot(sessionId);
    const existing = await this.repository.readJson(path, head);
    if (existing) {
      if (existing.data?.kind !== "pending_delete" || existing.data.idempotencyHash !== idempotencyHash ||
          existing.data.sessionId !== sessionId || !sameAction(existing.data.action, action)) {
        throw conflict("Idempotency transaction mismatch");
      }
      return this.executeDelete(existing.data);
    }
    if (session.revision !== body.expectedRevision) throw conflict();
    if (action.kind === "sources" && body.confirmation !== "Удалить исходники, сохранить результаты") throw new ValidationError("Exact source deletion confirmation is required");
    if (action.kind === "purge" && body.confirmation !== sessionId) throw new ValidationError("Source Session ID confirmation is required");
    const timestamp = nowIso(this.clock);
    const transaction = {
      schemaVersion: SCHEMA_VERSION, kind: "pending_delete", transactionId, idempotencyHash, revision: 1, state: "pending_delete",
      sessionId, expectedRevision: session.revision, releaseId: session.storage.releaseId, releaseTag: session.storage.tag,
      action, assetIds: this.selectDeleteAssets(session, action), deletedAssetIds: [], createdAt: timestamp, updatedAt: timestamp
    };
    await this.repository.commitJson(head, { [path]: transaction }, `Begin deletion ${transactionId}`);
    return this.executeDelete(transaction);
  }

  async executeDelete(input) {
    let transaction = validateTransaction(input);
    const path = transactionPath("delete", transaction.transactionId);
    if (transaction.state === "complete") return { completed: true, transactionId: transaction.transactionId };
    for (const assetId of transaction.assetIds) {
      if (transaction.deletedAssetIds.includes(assetId)) continue;
      await this.repository.deleteAsset(assetId);
      const head = await this.repository.getHead();
      transaction.deletedAssetIds.push(assetId);
      transaction.revision++;
      transaction.updatedAt = nowIso(this.clock);
      await this.repository.commitJson(head, { [path]: transaction }, `Resume deletion ${transaction.transactionId}`);
    }
    const { head, session } = await this.sessionSnapshot(transaction.sessionId);
    if (session.revision !== transaction.expectedRevision) throw conflict("Session changed while deletion was pending");
    const catalogStored = await this.repository.readJson("catalog.json", head);
    const catalog = catalogStored ? validateCatalog(catalogStored.data) : emptyCatalog();
    if (transaction.action.kind === "purge") {
      await this.repository.deleteRelease(transaction.releaseId);
      await this.repository.deleteTag(transaction.releaseTag);
      const tombstone = validateTombstone({
        schemaVersion: SCHEMA_VERSION, kind: "deletion_tombstone", id: session.id, deletedAt: nowIso(this.clock),
        lastRevision: session.revision, releaseTag: session.storage.tag,
        nextVersions: { announcement: session.workflows.announcement.nextVersion, speaker: session.workflows.speaker.nextVersion }
      });
      const entries = catalog.entries.filter((entry) => entry.id !== session.id);
      const nextCatalog = { schemaVersion: SCHEMA_VERSION, revision: catalog.revision + 1, updatedAt: nowIso(this.clock), entries };
      transaction = { ...transaction, state: "complete", revision: transaction.revision + 1, updatedAt: nowIso(this.clock) };
      const files = { [sessionPath(session.id)]: tombstone, "catalog.json": nextCatalog, [path]: transaction };
      for (const workflow of WORKFLOWS) {
        const draft = draftPath(session.id, workflow);
        if (await this.repository.readJson(draft, head)) files[draft] = null;
      }
      await this.repository.commitJson(head, files, `Purge audio session ${session.id}`);
      return { completed: true, transactionId: transaction.transactionId, tombstone };
    }
    const next = structuredClone(session);
    if (transaction.action.kind === "output-version") {
      const workflow = next.workflows[transaction.action.workflow];
      workflow.outputs = workflow.outputs.filter((output) => output.version !== transaction.action.version);
      workflow.deletedVersions.push(transaction.action.version);
      workflow.deletedVersions.sort((a, b) => a - b);
      if (!workflow.outputs.length) workflow.status = "new";
    } else if (transaction.action.kind === "output-series") {
      const workflow = next.workflows[transaction.action.workflow];
      workflow.deletedVersions.push(...workflow.outputs.map((output) => output.version));
      workflow.deletedVersions = [...new Set(workflow.deletedVersions)].sort((a, b) => a - b);
      workflow.outputs = [];
      workflow.status = "new";
    } else if (transaction.action.kind === "sources") {
      next.deletedSources = {
        deletedAt: nowIso(this.clock),
        tracks: next.sourceTracks.map(({ trackId, blobId, sizeBytes, sha256 }) => ({ trackId, blobId, sizeBytes, sha256 }))
      };
      next.sourceTracks = [];
      next.sourceState = "deleted";
    }
    next.revision++;
    next.updatedAt = nowIso(this.clock);
    transaction = { ...transaction, state: "complete", revision: transaction.revision + 1, updatedAt: nowIso(this.clock) };
    const result = await this.commitSession(head, next, catalog, `Complete deletion ${transaction.transactionId}`, { [path]: transaction });
    return { completed: true, transactionId: transaction.transactionId, session: result };
  }

  deleteOutputVersion(sessionId, workflow, version, body) {
    assertInteger(version, 1, Number.MAX_SAFE_INTEGER, "version");
    return this.beginDelete(sessionId, body, { kind: "output-version", workflow, version });
  }

  deleteOutputSeries(sessionId, workflow, body) {
    return this.beginDelete(sessionId, body, { kind: "output-series", workflow });
  }

  deleteSources(sessionId, body) {
    return this.beginDelete(sessionId, body, { kind: "sources" });
  }

  purgeSession(sessionId, body) {
    return this.beginDelete(sessionId, body, { kind: "purge" });
  }

  async listIncomplete() {
    const head = await this.repository.getHead();
    const transactions = [];
    for (const item of await this.repository.listJson("transactions/", head)) {
      if (item.invalid) continue;
      try {
        const transaction = validateTransaction(item.data);
        if (!["finalized", "complete", "discarded"].includes(transaction.state)) {
          const totalParts = transaction.kind === "ingestion" ?
            transaction.plan.tracks.reduce((sum, track) => sum + track.parts.length, 0) : null;
          const uploadedParts = transaction.kind === "ingestion" ? transaction.uploadedParts.length : null;
          transactions.push({
            transactionId: transaction.transactionId, kind: transaction.kind, state: transaction.state,
            sessionId: transaction.sessionId, updatedAt: transaction.updatedAt,
            uploadedParts, totalParts,
            canFinalize: transaction.kind === "ingestion" ? uploadedParts === totalParts : null,
            requiresOriginalFiles: transaction.kind === "ingestion" ? uploadedParts !== totalParts : false
          });
        }
      } catch { /* Malformed records are not actionable. */ }
    }
    const manifests = new Set((await this.repository.listJson("sessions/", head)).filter((item) => !item.invalid && item.data.kind !== "deletion_tombstone").map((item) => item.data.storage?.tag));
    const releases = await this.repository.listReleases();
    const orphans = releases.filter((release) => release.tag_name?.startsWith("audio-session-") && !manifests.has(release.tag_name))
      .map((release) => ({ releaseId: release.id, tag: release.tag_name, draft: Boolean(release.draft) }));
    return { transactions, orphans };
  }

  async recoverIncomplete(transactionId, action) {
    if (!["resume", "retry", "discard"].includes(action)) throw new ValidationError("Unknown recovery action");
    const ingest = await this.repository.readJson(transactionPath("ingest", transactionId), await this.repository.getHead());
    if (ingest && validateTransaction(ingest.data).state !== "finalized") {
      const transaction = validateTransaction(ingest.data);
      if (action === "discard") {
        await this.repository.deleteRelease(transaction.releaseId);
        await this.repository.deleteTag(transaction.releaseTag);
        const head = await this.repository.getHead();
        const discarded = { ...transaction, state: "discarded", revision: transaction.revision + 1, updatedAt: nowIso(this.clock) };
        await this.repository.commitJson(head, { [transactionPath("ingest", transactionId)]: discarded }, `Discard ingestion ${transactionId}`);
        return { discarded: true, transactionId };
      }
      const requiredCount = transaction.plan.tracks.reduce((sum, track) => sum + track.parts.length, 0);
      if (transaction.uploadedParts.length !== requiredCount) {
        throw conflict("Original files are required to continue this incomplete ingestion safely");
      }
      return this.finalizeIngestion(transactionId);
    }
    const pending = await this.repository.readJson(transactionPath("delete", transactionId), await this.repository.getHead());
    if (pending && pending.data.kind === "pending_delete") {
      const transaction = validateTransaction(pending.data);
      if (action === "discard") throw new ValidationError("Pending permanent deletion cannot be discarded after assets may have been removed");
      return this.executeDelete(transaction);
    }
    throw notFound("Recoverable transaction not found");
  }

  async rebuildCatalog() {
    const head = await this.repository.getHead();
    const stored = await this.repository.readJson("catalog.json", head);
    const previous = stored ? validateCatalog(stored.data) : emptyCatalog();
    const manifests = await this.repository.listJson("sessions/", head);
    const sessions = [];
    const invalid = [];
    for (const item of manifests) {
      if (item.invalid) { invalid.push(item.path); continue; }
      if (item.data.kind === "deletion_tombstone") {
        try { validateTombstone(item.data); } catch { invalid.push(item.path); }
        continue;
      }
      try { sessions.push(validateSourceSession(item.data)); } catch { invalid.push(item.path); }
    }
    const catalog = {
      schemaVersion: SCHEMA_VERSION, revision: previous.revision + 1, updatedAt: nowIso(this.clock),
      entries: sessions.map(catalogEntry).sort((left, right) => left.id.localeCompare(right.id))
    };
    await this.repository.commitJson(head, { "catalog.json": catalog }, "Rebuild audio session catalog");
    const recovery = await this.listIncomplete();
    return { catalog, invalidManifests: invalid, orphans: recovery.orphans };
  }
}
