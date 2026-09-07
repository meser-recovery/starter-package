import test from "node:test";
import assert from "node:assert/strict";
import { AudioArchiveGateway, reconstructAnnouncementOutput, reconstructSessionTracks } from "../../../scripts/audio-archive-client.mjs";
import { createApp } from "../src/app.mjs";
import { createPasswordVerifier } from "../src/auth.mjs";
import { AudioArchiveDomain } from "../src/domain.mjs";
import { MemoryRepository } from "./helpers.mjs";

const ORIGIN = "https://meser-recovery.github.io";
const BASE_URL = "https://gateway.test";
const PASSWORD = "correct horse battery staple";
const KEY = "frontend-integration-operation";
const CLOCK = () => Date.parse("2026-01-02T03:04:05.000Z");

class ByteRepository extends MemoryRepository {
  constructor() {
    super();
    this.assetBytes = new Map();
  }

  async uploadReleaseAsset(releaseId, name, bytes) {
    const asset = await super.uploadReleaseAsset(releaseId, name, bytes);
    this.assetBytes.set(asset.id, Uint8Array.from(bytes));
    return asset;
  }
}

async function frontendHarness() {
  const repository = new ByteRepository();
  const verifier = await createPasswordVerifier(PASSWORD, Buffer.alloc(16, 9), { N: 16384, r: 8, p: 1 });
  const domain = new AudioArchiveDomain(repository, { acceptedPartBytes: 4, clock: CLOCK });
  const app = createApp({
    config: {
      allowedOrigin: ORIGIN, acceptedPartBytes: 4, sessionSigningSecret: "0123456789abcdef0123456789abcdef",
      sessionLifetimeSeconds: 3600, sharedPasswordVerifier: verifier
    },
    domain,
    clock: CLOCK
  });
  let cookie = "";
  let acceptedPartRequests = 0;
  let interruptAfter = Infinity;
  const fetchImpl = async (input, init = {}) => {
    const url = new URL(input);
    if (url.hostname === "github.com") {
      for (const release of repository.releases.values()) {
        const asset = release.assets.find((candidate) => candidate.browser_download_url === String(input));
        if (asset) return new Response(repository.assetBytes.get(asset.id));
      }
      return new Response(null, { status: 404 });
    }
    const headers = new Headers(init.headers || {});
    headers.set("Origin", ORIGIN);
    if (cookie) headers.set("Cookie", cookie);
    const isPart = init.method === "PUT" && url.pathname.includes("/parts/");
    if (isPart && acceptedPartRequests >= interruptAfter) throw new DOMException("Interrupted upload", "AbortError");
    const response = await app(new Request(input, { ...init, headers }));
    const setCookie = response.headers.get("set-cookie");
    if (setCookie) cookie = setCookie.split(";", 1)[0];
    if (isPart && response.ok) acceptedPartRequests++;
    return response;
  };
  const gateway = new AudioArchiveGateway(BASE_URL, fetchImpl);
  await gateway.login(PASSWORD);
  await gateway.configuration();
  return {
    gateway, repository,
    interruptAfterParts(value) { interruptAfter = value; },
    allowUploads() { interruptAfter = Infinity; }
  };
}

test("real frontend client resumes one interrupted logical ingestion without duplicates", async () => {
  const harness = await frontendHarness();
  const bytes = Uint8Array.from([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
  const files = [new File([bytes], "meeting.wav", { type: "audio/wav" })];
  const request = { files, title: "Запись", recordedAt: null, origin: "manual", idempotencyKey: KEY };

  harness.interruptAfterParts(1);
  await assert.rejects(() => harness.gateway.ingestFiles(request), (error) => error?.name === "AbortError");
  const [partial] = (await harness.gateway.listIncomplete()).transactions;
  const originalTransaction = structuredClone(harness.repository.files.get(`transactions/ingest-${partial.transactionId}.json`));
  const firstAssetId = [...harness.repository.releases.values()][0].assets[0].id;
  assert.deepEqual(
    { uploadedParts: partial.uploadedParts, totalParts: partial.totalParts, canFinalize: partial.canFinalize, requiresOriginalFiles: partial.requiresOriginalFiles },
    { uploadedParts: 1, totalParts: 3, canFinalize: false, requiresOriginalFiles: true }
  );
  await assert.rejects(
    () => harness.gateway.recoverIncomplete(partial.transactionId, "resume"),
    (error) => error.status === 409 && /Original files are required/.test(error.message)
  );

  harness.allowUploads();
  const completed = await harness.gateway.ingestFiles(request);
  assert.equal(harness.repository.releases.size, 1);
  const [release] = harness.repository.releases.values();
  assert.equal(release.assets.length, 3);
  assert.equal(release.assets[0].id, firstAssetId);
  const listed = await harness.gateway.listSessions("incoming");
  assert.equal(listed.sessions.length, 1);
  assert.equal([...harness.repository.files.keys()].filter((path) => path.startsWith("sessions/")).length, 1);
  assert.equal(harness.repository.files.get("catalog.json").entries.length, 1);
  const stored = await harness.gateway.getSession(completed.session.id);
  assert.deepEqual({
    totalBytes: stored.sourceTracks.reduce((sum, track) => sum + track.sizeBytes, 0),
    tracks: stored.sourceTracks.map((track) => ({
      trackId: track.trackId, blobId: track.blobId, ordinal: track.ordinal, originalName: track.originalName,
      mediaType: track.mediaType, sizeBytes: track.sizeBytes, sha256: track.sha256,
      parts: track.parts.map(({ partNumber, sizeBytes, sha256, assetName }) => ({ partNumber, sizeBytes, sha256, assetName }))
    }))
  }, originalTransaction.plan);
  const [restored] = await reconstructSessionTracks(stored, harness.gateway.sourcePartFetch(stored));
  assert.deepEqual(new Uint8Array(await restored.arrayBuffer()), bytes);

  const changedFiles = [new File([Uint8Array.from([...bytes, 10])], "meeting.wav", { type: "audio/wav" })];
  await assert.rejects(
    () => harness.gateway.ingestFiles({ ...request, files: changedFiles }),
    (error) => error.status === 409 && /request mismatch/.test(error.message)
  );
  assert.equal(harness.repository.releases.size, 1);
  assert.equal((await harness.gateway.listSessions("incoming")).sessions.length, 1);
});

test("real frontend client cancels during hashing before contacting ingestion API", async () => {
  const controller = new AbortController();
  let fetchCalls = 0;
  let reads = 0;
  const gateway = new AudioArchiveGateway(BASE_URL, async () => { fetchCalls++; return new Response(); });
  gateway.acceptedPartSize = 1;
  const file = {
    name: "meeting.wav", type: "audio/wav", size: 1,
    slice() {
      return { async arrayBuffer() { reads++; controller.abort(); return Uint8Array.of(1).buffer; } };
    }
  };
  await assert.rejects(
    () => gateway.ingestFiles({ files: [file], title: "Запись", origin: "manual", idempotencyKey: "cancel-frontend-operation", signal: controller.signal }),
    (error) => error?.name === "AbortError"
  );
  assert.equal(reads, 1);
  assert.equal(fetchCalls, 0);
});

test("real frontend and gateway publish, retrieve, and verify one Announcement output", async () => {
  const harness = await frontendHarness();
  const source = new File([Uint8Array.of(1, 2, 3, 4)], "meeting.wav", { type: "audio/wav" });
  const ingested = await harness.gateway.ingestFiles({ files: [source], title: "Запись", origin: "manual", idempotencyKey: `${KEY}:source` });
  let session = ingested.session;
  const saved = await harness.gateway.saveDraft(session.id, "announcement", {
    schemaVersion: 1, expectedDraftRevision: 0, expectedSourceSessionRevision: session.revision,
    payloadSchema: "announcement/v1", payload: { trackIds: [session.sourceTracks[0].trackId] }, idempotencyKey: `${KEY}:draft`
  });
  session = saved.session;
  const outputBytes = Uint8Array.of(9, 8, 7, 6, 5);
  const track = session.sourceTracks[0];
  const recipe = {
    sourceSessionRevision: session.revision,
    sources: [{ trackId: track.trackId, blobId: track.blobId, ordinal: 1, sizeBytes: track.sizeBytes, sha256: track.sha256, mediaType: track.mediaType }],
    draft: { revision: saved.draft.draftRevision, payloadSchema: "announcement/v1", payload: saved.draft.payload },
    processing: { mode: "processed_single", silenceThresholdDb: -45, minimumSilenceSeconds: 2, retainedSilenceSeconds: 0.35,
      detectedIntervals: [[2, 5]], removalRanges: [[2.175, 4.825]], mix: null, limiter: null,
      codec: { name: "libmp3lame", bitrate: "128k" } },
    result: { mediaType: "audio/mpeg", presentationFilename: "meeting-edited.mp3", sizeBytes: outputBytes.length,
      sha256: "0".repeat(64), originalDurationSeconds: 8, resultDurationSeconds: 5.35, removedDurationSeconds: 2.65, pauseCount: 1 }
  };
  const progress = [];
  const published = await harness.gateway.publishAnnouncement({ sessionId: session.id, expectedRevision: session.revision,
    expectedDraftRevision: saved.draft.draftRevision, blob: new Blob([outputBytes], { type: "audio/mpeg" }), recipe,
    idempotencyKey: `${KEY}:publish`, onProgress: (event) => progress.push(event) });
  assert.equal(published.output.version, 1);
  assert.equal(progress.length, 2);
  const metadata = await harness.gateway.getAnnouncementOutput(session.id, published.output.outputId);
  const file = await reconstructAnnouncementOutput(metadata, harness.gateway.announcementPartFetch(metadata));
  assert.equal(file.name, "meeting-edited.mp3");
  assert.equal(file.type, "audio/mpeg");
  assert.deepEqual(new Uint8Array(await file.arrayBuffer()), outputBytes);
  assert.equal(harness.repository.files.has(`recipes/${session.id}/announcement/${published.output.outputId}.json`), true);
});
