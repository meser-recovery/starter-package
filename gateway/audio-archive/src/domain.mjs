import { createHash, randomUUID, timingSafeEqual } from "node:crypto";
import { isDeepStrictEqual } from "node:util";
import {
  SCHEMA_VERSION, MAX_PART_BYTES, WORKFLOWS, ValidationError, assertExactKeys, assertInteger, assertSha256,
  assertTimestamp, assertUuid, assetName, catalogEntry, hashIdempotencyKey, normalizeFilename, normalizeMediaType,
  uuidFromIdempotencyKey, canonicalReleaseAssetUrl, recipePath, validateAnnouncementDraftPayload, validateSpeakerDraftPayload, validateAnnouncementRecipe,
  validateCatalog, validateDraft, validateIngestionPlan, validatePublicationPlan, validateSourceSession, validateTombstone, validateTransaction
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

function publicationFailure(phase, clock) {
  const failures = {
    upload: { code: "upload_failed", message: "Announcement part upload failed; retry is safe." },
    finalize: { code: "finalize_failed", message: "Announcement finalization failed; retry or discard is required." }
  };
  return { ...failures[phase], at: nowIso(clock) };
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

function publicationPath(transactionId) {
  return transactionPath("publish", transactionId);
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

function requestFingerprint(value) {
  const canonical = (input) => Array.isArray(input) ? input.map(canonical) : input && typeof input === "object" ?
    Object.fromEntries(Object.keys(input).sort().map((key) => [key, canonical(input[key])])) : input;
  return createHash("sha256").update(JSON.stringify(canonical(value)), "utf8").digest("hex");
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

  async downloadSourcePart(sessionId, blobId, partNumber) {
    const id = assertUuid(blobId, "blobId");
    assertInteger(partNumber, 1, 9999, "partNumber");
    const session = (await this.sessionSnapshot(sessionId)).session;
    if (session.sourceState !== "available") throw notFound("Source Session audio is unavailable");
    const track = session.sourceTracks.find((item) => item.blobId === id);
    const part = track?.parts.find((item) => item.partNumber === partNumber);
    if (!part) throw notFound("Source Session part not found");
    const bytes = await this.repository.downloadReleaseAsset(part.assetId);
    if (bytes.byteLength !== part.sizeBytes || !sameDigest(digestBytes(bytes), part.sha256)) {
      throw conflict("Release asset failed integrity verification");
    }
    return { bytes, assetName: part.assetName };
  }

  async getAnnouncementOutput(sessionId, outputId) {
    const id = assertUuid(outputId, "outputId");
    const { head, session } = await this.sessionSnapshot(sessionId);
    const output = session.workflows.announcement.outputs.find((item) => item.outputId === id);
    if (!output) throw notFound("Announcement output not found");
    const stored = await this.repository.readJson(recipePath(session.id, id), head);
    if (!stored) throw conflict("Announcement recipe is missing");
    const recipe = validateAnnouncementRecipe(stored.data);
    if (recipe.sessionId !== session.id || recipe.outputId !== output.outputId || recipe.version !== output.version ||
        recipe.processorVersion !== output.processorVersion || recipe.result.sizeBytes !== output.sizeBytes || recipe.result.sha256 !== output.sha256) {
      throw conflict("Announcement recipe does not match its output");
    }
    return { output: structuredClone(output), recipe };
  }

  async downloadAnnouncementPart(sessionId, outputId, blobId, partNumber) {
    const metadata = await this.getAnnouncementOutput(sessionId, outputId);
    const id = assertUuid(blobId, "blobId");
    assertInteger(partNumber, 1, 9999, "partNumber");
    if (metadata.output.blobId !== id) throw notFound("Announcement output blob not found");
    const part = metadata.output.parts.find((item) => item.partNumber === partNumber);
    if (!part) throw notFound("Announcement output part not found");
    const bytes = await this.repository.downloadReleaseAsset(part.assetId);
    if (bytes.byteLength !== part.sizeBytes || !sameDigest(digestBytes(bytes), part.sha256)) {
      throw conflict("Announcement asset failed integrity verification");
    }
    return { bytes, assetName: part.assetName };
  }

  async publicationSnapshot(transactionId) {
    const head = await this.repository.getHead();
    const path = publicationPath(transactionId);
    const stored = await this.repository.readJson(path, head);
    if (!stored || stored.data?.kind !== "publication") throw notFound("Publication job not found");
    return { head, path, transaction: validateTransaction(stored.data) };
  }

  publicPublicationJob(transaction) {
    const requiredParts = transaction.plan.parts.length;
    return {
      transactionId: transaction.transactionId,
      sessionId: transaction.sessionId,
      workflow: transaction.workflow,
      outputId: transaction.outputId,
      blobId: transaction.blobId,
      state: transaction.state,
      reservedVersion: transaction.reservedVersion,
      reservedSessionRevision: transaction.reservedSessionRevision,
      uploadedParts: transaction.uploadedParts.length,
      totalParts: requiredParts,
      canFinalize: transaction.uploadedParts.length === requiredParts,
      requiresLocalResult: transaction.uploadedParts.length !== requiredParts,
      failure: structuredClone(transaction.failure),
      updatedAt: transaction.updatedAt
    };
  }

  async persistPublicationFailure(transactionId, phase, observedRevision) {
    try {
      const { head, path, transaction } = await this.publicationSnapshot(transactionId);
      if (transaction.revision !== observedRevision || ["finalized", "discarded"].includes(transaction.state)) return;
      const failed = validateTransaction({ ...transaction, revision: transaction.revision + 1,
        failure: publicationFailure(phase, this.clock), updatedAt: nowIso(this.clock) });
      await this.repository.commitJson(head, { [path]: failed }, `Record Announcement ${phase} failure ${transactionId}`);
    } catch { /* Failure reporting is best effort and must not replace the attributable error. */ }
  }

  async activePublications(sessionId, head = null, excluding = null) {
    const ref = head || await this.repository.getHead();
    const jobs = [];
    for (const item of await this.repository.listJson("transactions/", ref)) {
      if (item.invalid || item.data?.kind !== "publication") continue;
      try {
        const job = validateTransaction(item.data);
        if (job.sessionId === sessionId && job.transactionId !== excluding && ["uploading", "cancelled"].includes(job.state)) jobs.push(job);
      } catch { /* Invalid jobs fail closed elsewhere and are not resumable. */ }
    }
    return jobs;
  }

  async beginAnnouncementPublication(sessionId, body) {
    assertExactKeys(body, ["schemaVersion", "expectedRevision", "expectedDraftRevision", "idempotencyKey", "plan"], "begin publication");
    if (body.schemaVersion !== SCHEMA_VERSION) throw new ValidationError("Unsupported publication schema");
    assertInteger(body.expectedRevision, 1, Number.MAX_SAFE_INTEGER, "expectedRevision");
    assertInteger(body.expectedDraftRevision, 0, Number.MAX_SAFE_INTEGER, "expectedDraftRevision");
    const idempotencyHash = hashIdempotencyKey(body.idempotencyKey);
    const transactionId = uuidFromIdempotencyKey(`publication:${sessionId}:${body.idempotencyKey}`);
    const path = publicationPath(transactionId);
    const plan = validatePublicationPlan(body.plan, this.acceptedPartBytes);
    const immutableRequest = { sessionId, workflow: "announcement", expectedRevision: body.expectedRevision,
      expectedDraftRevision: body.expectedDraftRevision, plan };
    const fingerprint = requestFingerprint(immutableRequest);
    let head = await this.repository.getHead();
    const existing = await this.repository.readJson(path, head);
    if (existing) {
      const job = validateTransaction(existing.data);
      if (job.idempotencyHash !== idempotencyHash || job.requestFingerprint !== fingerprint) {
        throw conflict("Idempotency publication request mismatch");
      }
      return this.publicPublicationJob(job);
    }
    const snapshot = await this.sessionSnapshot(sessionId);
    head = snapshot.head;
    const session = snapshot.session;
    if (session.revision !== body.expectedRevision) throw conflict();
    if (session.lifecycle.state !== "incoming") throw conflict("Archived Source Session must be restored before publication");
    if (session.sourceState !== "available") throw conflict("Source Session audio is unavailable for publication");
    if ((await this.activePublications(session.id, head)).length) throw conflict("Finish or discard the existing Announcement publication before starting another");
    const workflow = session.workflows.announcement;
    const currentDraftRevision = workflow.currentDraft?.revision || 0;
    if (currentDraftRevision !== body.expectedDraftRevision || plan.recipe.draft.revision !== body.expectedDraftRevision) {
      throw conflict("Announcement draft changed; reload before publication");
    }
    if (plan.recipe.sourceSessionRevision !== session.revision) throw conflict("Processor provenance is stale");
    const recipeTrackIds = plan.recipe.sources.map((source) => source.trackId);
    const draftTrackIds = validateAnnouncementDraftPayload(plan.recipe.draft.payload).trackIds;
    if (!isDeepStrictEqual(recipeTrackIds, draftTrackIds)) throw new ValidationError("Announcement draft and recipe track order differ");
    for (const source of plan.recipe.sources) {
      const track = session.sourceTracks.find((item) => item.trackId === source.trackId);
      if (!track || track.blobId !== source.blobId || track.sizeBytes !== source.sizeBytes || track.sha256 !== source.sha256 || track.mediaType !== source.mediaType) {
        throw conflict("Processor source provenance does not match Source Session");
      }
    }
    if (plan.recipe.processing.mode === "passthrough") {
      const source = session.sourceTracks.find((track) => track.trackId === recipeTrackIds[0]);
      if (!source || plan.sizeBytes !== source.sizeBytes || plan.sha256 !== source.sha256 ||
          plan.recipe.result.mediaType !== source.mediaType) {
        throw conflict("Passthrough result must be byte-identical to its single source track");
      }
    }
    if (workflow.currentDraft) {
      const storedDraft = await this.repository.readJson(workflow.currentDraft.path, head);
      const draft = storedDraft ? validateDraft(storedDraft.data) : null;
      if (!draft || draft.draftRevision !== body.expectedDraftRevision || draft.payloadSchema !== "announcement/v1" ||
          !isDeepStrictEqual(validateAnnouncementDraftPayload(draft.payload), plan.recipe.draft.payload)) {
        throw conflict("Announcement draft does not match the processed candidate");
      }
    }
    const allOutputs = WORKFLOWS.flatMap((name) => session.workflows[name].outputs);
    if (session.sourceTracks.some((track) => track.blobId === plan.blobId) ||
        allOutputs.some((output) => output.outputId === plan.outputId || output.blobId === plan.blobId)) {
      throw conflict("Publication output identity is already in use");
    }
    const timestamp = nowIso(this.clock);
    const reservedVersion = workflow.nextVersion;
    const recipeSnapshot = validateAnnouncementRecipe({
      schemaVersion: SCHEMA_VERSION, workflow: "announcement", sessionId: session.id, outputId: plan.outputId,
      version: reservedVersion, processorVersion: plan.processorVersion, createdAt: timestamp, ...plan.recipe
    });
    const next = structuredClone(session);
    next.workflows.announcement.nextVersion++;
    if (!next.workflows.announcement.outputs.length) next.workflows.announcement.status = "in_progress";
    next.revision++;
    next.updatedAt = timestamp;
    const job = validateTransaction({
      schemaVersion: SCHEMA_VERSION, kind: "publication", transactionId, idempotencyHash, requestFingerprint: fingerprint,
      revision: 1, state: "uploading", sessionId: session.id, workflow: "announcement", outputId: plan.outputId,
      blobId: plan.blobId, expectedRevision: session.revision, reservedSessionRevision: next.revision,
      reservedVersion, releaseId: session.storage.releaseId, releaseTag: session.storage.tag, plan,
      uploadedParts: [], recipeSnapshot, outputDescriptor: null, failure: null, createdAt: timestamp, updatedAt: timestamp
    });
    const catalogStored = await this.repository.readJson("catalog.json", head);
    const catalog = catalogStored ? validateCatalog(catalogStored.data) : emptyCatalog();
    await this.commitSession(head, next, catalog, `Reserve Announcement version ${reservedVersion} for ${session.id}`, { [path]: job });
    return this.publicPublicationJob(job);
  }

  async uploadAnnouncementPart(transactionId, blobId, partNumber, bytes, suppliedHash, idempotencyKey) {
    const id = assertUuid(blobId, "blobId");
    assertInteger(partNumber, 1, 9999, "partNumber");
    hashIdempotencyKey(idempotencyKey);
    if (!Buffer.isBuffer(bytes) || bytes.byteLength < 1 || bytes.byteLength > Math.min(this.acceptedPartBytes, MAX_PART_BYTES)) throw new ValidationError("Part body size is invalid");
    const hash = assertSha256(suppliedHash, "X-Part-SHA256");
    if (!sameDigest(digestBytes(bytes), hash)) throw new ValidationError("Part SHA-256 does not match its bytes");
    let { head, path, transaction } = await this.publicationSnapshot(transactionId);
    const observedRevision = transaction.revision;
    try {
      if (transaction.state === "finalized") return { uploaded: true, finalized: true };
      if (transaction.state === "discarded") throw conflict("Publication job was discarded");
      if (transaction.blobId !== id) throw new ValidationError("Blob does not belong to publication job");
      const planned = transaction.plan.parts.find((item) => item.partNumber === partNumber);
      if (!planned || planned.sizeBytes !== bytes.byteLength || !sameDigest(planned.sha256, hash)) throw new ValidationError("Part does not match publication plan");
      const already = transaction.uploadedParts.find((item) => item.partNumber === partNumber);
      if (already) {
        if (already.sizeBytes !== bytes.byteLength || !sameDigest(already.sha256, hash)) throw conflict("A different part already occupies this slot");
        if (transaction.failure !== null) {
          transaction = validateTransaction({ ...transaction, revision: transaction.revision + 1, failure: null, updatedAt: nowIso(this.clock) });
          await this.repository.commitJson(head, { [path]: transaction }, `Clear Announcement upload failure ${transactionId}`);
        }
        return { uploaded: true, assetId: already.assetId, downloadUrl: already.downloadUrl };
      }
      const name = assetName(id, partNumber);
      const assets = await this.repository.listReleaseAssets(transaction.releaseId);
      const matches = assets.filter((asset) => asset.name === name);
      if (matches.length > 1) throw conflict("Duplicate release assets occupy the planned slot");
      let asset = matches[0];
      if (asset) {
        if (!Number.isSafeInteger(asset.id) || asset.id < 1 || asset.size !== bytes.byteLength ||
            (asset.digest && !sameDigest(String(asset.digest).replace(/^sha256:/, ""), hash))) throw conflict("Existing release asset does not match planned part");
      } else {
        asset = await this.repository.uploadReleaseAsset(transaction.releaseId, name, bytes);
      }
      if (!Number.isSafeInteger(asset.id) || asset.id < 1 || asset.name !== name || asset.size !== bytes.byteLength ||
          (asset.digest && !sameDigest(String(asset.digest).replace(/^sha256:/, ""), hash))) throw new Error("GitHub asset integrity response did not match upload");
      transaction = structuredClone(transaction);
      transaction.state = "uploading";
      transaction.revision++;
      transaction.failure = null;
      transaction.updatedAt = nowIso(this.clock);
      transaction.uploadedParts.push({ blobId: id, partNumber, assetName: name, sizeBytes: bytes.byteLength, sha256: hash,
        assetId: asset.id, downloadUrl: canonicalReleaseAssetUrl(transaction.releaseTag, name) });
      transaction.uploadedParts.sort((left, right) => left.partNumber - right.partNumber);
      transaction = validateTransaction(transaction);
      await this.repository.commitJson(head, { [path]: transaction }, `Record Announcement part ${transaction.sessionId} ${name}`);
      return { uploaded: true, assetId: asset.id, downloadUrl: canonicalReleaseAssetUrl(transaction.releaseTag, name) };
    } catch (error) {
      await this.persistPublicationFailure(transactionId, "upload", observedRevision);
      throw error;
    }
  }

  async finalizeAnnouncementPublication(transactionId) {
    let { head, path, transaction } = await this.publicationSnapshot(transactionId);
    const observedRevision = transaction.revision;
    try {
    if (transaction.state === "finalized") return { job: this.publicPublicationJob(transaction), output: structuredClone(transaction.outputDescriptor), idempotent: true };
    if (transaction.state === "discarded") throw conflict("Publication job was discarded");
    if (transaction.uploadedParts.length !== transaction.plan.parts.length) throw conflict("All planned parts must upload before finalization");
    const assets = await this.repository.listReleaseAssets(transaction.releaseId);
    const logicalHasher = createHash("sha256");
    let logicalBytes = 0;
    for (const uploaded of transaction.uploadedParts) {
      const asset = assets.find((item) => item.id === uploaded.assetId && item.name === uploaded.assetName);
      if (!asset || asset.size !== uploaded.sizeBytes ||
          (asset.digest && !sameDigest(String(asset.digest).replace(/^sha256:/, ""), uploaded.sha256))) {
        throw conflict("Announcement assets failed final integrity verification");
      }
      const bytes = await this.repository.downloadReleaseAsset(uploaded.assetId);
      if (bytes.byteLength !== uploaded.sizeBytes || !sameDigest(digestBytes(bytes), uploaded.sha256)) {
        throw conflict("Announcement asset bytes failed final integrity verification");
      }
      logicalHasher.update(bytes);
      logicalBytes += bytes.byteLength;
    }
    if (logicalBytes !== transaction.plan.sizeBytes || logicalHasher.digest("hex") !== transaction.plan.sha256) {
      throw conflict("Announcement logical result failed final integrity verification");
    }
    const snapshot = await this.sessionSnapshot(transaction.sessionId);
    head = snapshot.head;
    const session = snapshot.session;
    if (session.revision !== transaction.reservedSessionRevision) throw conflict("Source Session changed after version reservation");
    if (session.lifecycle.state !== "incoming") throw conflict("Archived Source Session cannot finalize a new Announcement");
    const recipeRef = recipePath(session.id, transaction.outputId);
    const existingRecipe = await this.repository.readJson(recipeRef, head);
    if (existingRecipe && !isDeepStrictEqual(validateAnnouncementRecipe(existingRecipe.data), transaction.recipeSnapshot)) {
      throw conflict("Immutable Announcement recipe already exists with different content");
    }
    const parts = transaction.plan.parts.map((part) => {
      const uploaded = transaction.uploadedParts.find((item) => item.partNumber === part.partNumber);
      if (!uploaded) throw conflict("Publication is incomplete");
      return { partNumber: part.partNumber, sizeBytes: part.sizeBytes, sha256: part.sha256, assetName: part.assetName,
        assetId: uploaded.assetId, downloadUrl: uploaded.downloadUrl };
    });
    const output = {
      outputId: transaction.outputId, version: transaction.reservedVersion, sessionId: session.id,
      createdAt: transaction.recipeSnapshot.createdAt, blobId: transaction.blobId, sizeBytes: transaction.plan.sizeBytes,
      sha256: transaction.plan.sha256, parts, recipeSnapshotRef: recipeRef, processorVersion: transaction.plan.processorVersion
    };
    const next = structuredClone(session);
    if (!next.workflows.announcement.outputs.some((item) => item.outputId === output.outputId)) next.workflows.announcement.outputs.push(output);
    next.workflows.announcement.outputs.sort((left, right) => left.version - right.version);
    next.workflows.announcement.status = "result_ready";
    next.revision++;
    next.updatedAt = nowIso(this.clock);
    transaction = validateTransaction({ ...transaction, state: "finalized", revision: transaction.revision + 1,
      outputDescriptor: output, failure: null, updatedAt: nowIso(this.clock) });
    const catalogStored = await this.repository.readJson("catalog.json", head);
    const catalog = catalogStored ? validateCatalog(catalogStored.data) : emptyCatalog();
    await this.commitSession(head, next, catalog, `Finalize Announcement version ${output.version} for ${session.id}`, {
      [recipeRef]: transaction.recipeSnapshot,
      [path]: transaction
    });
    return { job: this.publicPublicationJob(transaction), output: structuredClone(output), idempotent: false };
    } catch (error) {
      await this.persistPublicationFailure(transactionId, "finalize", observedRevision);
      throw error;
    }
  }

  async cancelAnnouncementPublication(transactionId, body, discard = false) {
    assertExactKeys(body, ["idempotencyKey"], discard ? "discard publication" : "cancel publication");
    hashIdempotencyKey(body.idempotencyKey);
    let { head, path, transaction } = await this.publicationSnapshot(transactionId);
    if (transaction.state === "finalized") throw conflict("Finalized publication cannot be cancelled");
    if (transaction.state === "discarded") return { job: this.publicPublicationJob(transaction), idempotent: true };
    const nextState = discard ? "discarded" : "cancelled";
    if (transaction.state !== nextState) {
      transaction = validateTransaction({ ...transaction, state: nextState, revision: transaction.revision + 1, updatedAt: nowIso(this.clock) });
      if (discard) {
        const storedSession = await this.repository.readJson(sessionPath(transaction.sessionId), head);
        const session = storedSession && storedSession.data?.kind !== "deletion_tombstone" ? validateSourceSession(storedSession.data) : null;
        const otherActive = await this.activePublications(transaction.sessionId, head, transaction.transactionId);
        if (session && session.revision === transaction.reservedSessionRevision && !session.workflows.announcement.outputs.length &&
            session.workflows.announcement.status === "in_progress" && !otherActive.length) {
          const next = structuredClone(session);
          next.workflows.announcement.status = next.workflows.announcement.currentDraft ? "in_progress" : "new";
          next.revision++;
          next.updatedAt = nowIso(this.clock);
          const catalogStored = await this.repository.readJson("catalog.json", head);
          const catalog = catalogStored ? validateCatalog(catalogStored.data) : emptyCatalog();
          await this.commitSession(head, next, catalog, `Discard Announcement publication ${transactionId}`, { [path]: transaction });
          return { job: this.publicPublicationJob(transaction), session: publicSession(next), idempotent: false };
        }
      }
      await this.repository.commitJson(head, { [path]: transaction }, `${discard ? "Discard" : "Cancel"} Announcement publication ${transactionId}`);
    }
    return { job: this.publicPublicationJob(transaction), idempotent: false };
  }

  async getAnnouncementPublication(transactionId) {
    return this.publicPublicationJob((await this.publicationSnapshot(transactionId)).transaction);
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
    const matchingAssets = assets.filter((item) => item.name === name);
    if (matchingAssets.length > 1) throw conflict("Duplicate release assets occupy the planned slot");
    let asset = matchingAssets[0];
    if (asset) {
      if (!Number.isSafeInteger(asset.id) || asset.id < 1 || asset.size !== bytes.byteLength ||
          (asset.digest && !sameDigest(String(asset.digest).replace(/^sha256:/, ""), hash))) {
        throw conflict("Existing release asset does not match the planned part");
      }
    } else {
      asset = await this.repository.uploadReleaseAsset(transaction.releaseId, name, bytes);
    }
    if (!Number.isSafeInteger(asset.id) || asset.id < 1 || asset.name !== name || asset.size !== bytes.byteLength ||
        (asset.digest && !sameDigest(String(asset.digest).replace(/^sha256:/, ""), hash))) {
      throw new Error("GitHub asset integrity response did not match upload");
    }
    const downloadUrl = canonicalReleaseAssetUrl(transaction.releaseTag, name);
    transaction = structuredClone(transaction);
    transaction.revision++;
    transaction.updatedAt = nowIso(this.clock);
    transaction.uploadedParts.push({ blobId: id, partNumber, assetName: name, sizeBytes: bytes.byteLength, sha256: hash, assetId: asset.id, downloadUrl });
    transaction.uploadedParts.sort((left, right) => left.blobId.localeCompare(right.blobId) || left.partNumber - right.partNumber);
    await this.repository.commitJson(head, { [path]: transaction }, `Record audio part ${transaction.sessionId} ${name}`);
    return { uploaded: true, assetId: asset.id, downloadUrl };
  }

  buildManifest(transaction) {
    const timestamp = nowIso(this.clock);
    const sourceTracks = transaction.plan.tracks.map((track) => ({
      ...track,
      parts: track.parts.map((part) => {
        const uploaded = transaction.uploadedParts.find((item) => item.blobId === track.blobId && item.partNumber === part.partNumber);
        if (!uploaded) throw conflict("Ingestion is incomplete");
        if (uploaded.downloadUrl !== canonicalReleaseAssetUrl(transaction.releaseTag, uploaded.assetName)) {
          throw conflict("Ingestion contains a non-canonical asset URL");
        }
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
      if (!asset || asset.size !== uploaded.sizeBytes ||
          (asset.digest && !sameDigest(String(asset.digest).replace(/^sha256:/, ""), uploaded.sha256))) {
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
    if (target === "archived" && (await this.activePublications(sessionId)).length) {
      throw conflict("Finish or discard pending Announcement publications before archiving");
    }
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
    if (workflow === "speaker" && (session.lifecycle.state !== "incoming" || session.sourceState !== "available")) {
      throw conflict("Restore an available Source Session before saving a Speaker draft");
    }
    const existing = await this.repository.readJson(path, head);
    const currentRevision = existing ? validateDraft(existing.data).draftRevision : 0;
    if (body.expectedDraftRevision !== currentRevision) throw conflict("Draft changed; reload before saving");
    if (typeof body.payloadSchema !== "string" || body.payloadSchema.length > 100) throw new ValidationError("payloadSchema is invalid");
    if (workflow === "announcement") {
      if (body.payloadSchema !== "announcement/v1") throw new ValidationError("Announcement draft schema is invalid");
      body = { ...body, payload: validateAnnouncementDraftPayload(body.payload) };
    } else {
      if (body.payloadSchema !== "speaker/v1") throw new ValidationError("Speaker draft schema is invalid");
      body = { ...body, payload: validateSpeakerDraftPayload(body.payload, session.sourceTracks.map((track) => track.trackId)) };
    }
    const draft = validateDraft({
      schemaVersion: SCHEMA_VERSION, sessionId, workflow, draftRevision: currentRevision + 1,
      sourceSessionRevision: session.revision + 1, savedAt: nowIso(this.clock), payloadSchema: body.payloadSchema,
      payload: structuredClone(body.payload)
    });
    const catalogStored = await this.repository.readJson("catalog.json", head);
    const catalog = catalogStored ? validateCatalog(catalogStored.data) : emptyCatalog();
    const next = structuredClone(session);
    next.workflows[workflow].currentDraft = { path, revision: draft.draftRevision };
    if (!next.workflows[workflow].outputs.length) next.workflows[workflow].status = "in_progress";
    next.revision++;
    next.updatedAt = nowIso(this.clock);
    const committed = await this.commitSession(head, next, catalog, `Save ${workflow} draft ${sessionId}`, { [path]: draft });
    return { draft, session: committed };
  }

  async dependencyPreview(sessionId) {
    const { head, session } = await this.sessionSnapshot(sessionId);
    const drafts = [];
    for (const workflow of WORKFLOWS) if (await this.repository.readJson(draftPath(sessionId, workflow), head)) drafts.push(workflow);
    const pendingAnnouncementPublications = (await this.activePublications(sessionId, head)).length;
    return {
      sessionId, revision: session.revision, sourceTracks: session.sourceTracks.length,
      announcementVersions: session.workflows.announcement.outputs.length,
      speakerVersions: session.workflows.speaker.outputs.length,
      drafts: drafts.length, draftWorkflows: drafts, pendingAnnouncementPublications
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
    if ((await this.activePublications(sessionId, head)).length) {
      throw conflict("Finish or discard pending Announcement publications before deletion");
    }
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
      for (const recipe of await this.repository.listJson("recipes/", head)) {
        if (recipe.path.startsWith(`recipes/${session.id}/`)) files[recipe.path] = null;
      }
      await this.repository.commitJson(head, files, `Purge audio session ${session.id}`);
      return { completed: true, transactionId: transaction.transactionId, tombstone };
    }
    const next = structuredClone(session);
    const extraFiles = { [path]: transaction };
    if (transaction.action.kind === "output-version") {
      const workflow = next.workflows[transaction.action.workflow];
      const removed = workflow.outputs.find((output) => output.version === transaction.action.version);
      workflow.outputs = workflow.outputs.filter((output) => output.version !== transaction.action.version);
      workflow.deletedVersions.push(transaction.action.version);
      workflow.deletedVersions.sort((a, b) => a - b);
      if (!workflow.outputs.length) workflow.status = workflow.currentDraft ? "in_progress" : "new";
      if (transaction.action.workflow === "announcement" && removed) extraFiles[recipePath(session.id, removed.outputId)] = null;
    } else if (transaction.action.kind === "output-series") {
      const workflow = next.workflows[transaction.action.workflow];
      if (transaction.action.workflow === "announcement") {
        for (const output of workflow.outputs) extraFiles[recipePath(session.id, output.outputId)] = null;
      }
      workflow.deletedVersions.push(...workflow.outputs.map((output) => output.version));
      workflow.deletedVersions = [...new Set(workflow.deletedVersions)].sort((a, b) => a - b);
      workflow.outputs = [];
      workflow.status = workflow.currentDraft ? "in_progress" : "new";
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
    extraFiles[path] = transaction;
    const result = await this.commitSession(head, next, catalog, `Complete deletion ${transaction.transactionId}`, extraFiles);
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
            transaction.plan.tracks.reduce((sum, track) => sum + track.parts.length, 0) :
            transaction.kind === "publication" ? transaction.plan.parts.length : null;
          const uploadedParts = ["ingestion", "publication"].includes(transaction.kind) ? transaction.uploadedParts.length : null;
          transactions.push({
            transactionId: transaction.transactionId, kind: transaction.kind, state: transaction.state,
            sessionId: transaction.sessionId, updatedAt: transaction.updatedAt,
            uploadedParts, totalParts,
            canFinalize: ["ingestion", "publication"].includes(transaction.kind) ? uploadedParts === totalParts : null,
            requiresOriginalFiles: transaction.kind === "ingestion" ? uploadedParts !== totalParts : false,
            requiresLocalResult: transaction.kind === "publication" ? uploadedParts !== totalParts : false,
            reservedVersion: transaction.kind === "publication" ? transaction.reservedVersion : null,
            failure: transaction.kind === "publication" ? structuredClone(transaction.failure) : null
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
    const publication = await this.repository.readJson(publicationPath(transactionId), await this.repository.getHead());
    if (publication && validateTransaction(publication.data).state !== "finalized") {
      const transaction = validateTransaction(publication.data);
      if (action === "discard") return this.cancelAnnouncementPublication(transactionId, { idempotencyKey: `maintenance-discard:${transactionId}` }, true);
      if (transaction.state === "discarded") throw conflict("Publication job was discarded");
      if (transaction.uploadedParts.length !== transaction.plan.parts.length) {
        throw conflict("Local processor result is required to continue this incomplete publication safely");
      }
      return this.finalizeAnnouncementPublication(transactionId);
    }
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
