import test from "node:test";
import assert from "node:assert/strict";
import { AudioArchiveGateway, createIngestionPlan, reconstructSessionTracks, serializeIngestionPlan } from "../../../scripts/audio-archive-client.mjs";
import { createApp } from "../src/app.mjs";
import { createPasswordVerifier } from "../src/auth.mjs";
import { AudioArchiveDomain } from "../src/domain.mjs";
import { GitHubArchiveRepository } from "../src/github.mjs";
import { canonicalReleaseAssetUrl, hashIdempotencyKey, uuidFromIdempotencyKey, validateSourceSession, validateTransaction } from "../src/validation.mjs";
import { sha } from "./helpers.mjs";

const ORIGIN = "https://meser-recovery.github.io";
const BASE_URL = "https://gateway.test";
const PASSWORD = "correct horse battery staple";
const CLOCK = () => Date.parse("2026-01-02T03:04:05.000Z");
const UNTAGGED = "untagged-0123456789abcdefabcd";

function jsonResponse(value, status = 200) {
  return new Response(value === null ? null : JSON.stringify(value), {
    status,
    headers: value === null ? {} : { "Content-Type": "application/json" }
  });
}

class GitHubHttpTransport {
  constructor() {
    this.head = "head-0";
    this.files = new Map([["catalog.json", { schemaVersion: 1, revision: 0, updatedAt: null, entries: [] }]]);
    this.blobs = new Map();
    this.trees = new Map();
    this.commits = new Map();
    this.releases = new Map();
    this.assetBytes = new Map();
    this.nextObject = 1;
    this.nextRelease = 100;
    this.nextAsset = 1_000;
    this.uploadedDraftUrls = [];
  }

  fileBlob(path) {
    const content = `${JSON.stringify(this.files.get(path), null, 2)}\n`;
    const blobSha = `stored-${Buffer.from(path).toString("hex")}`;
    this.blobs.set(blobSha, Buffer.from(content).toString("base64"));
    return { blobSha, content };
  }

  seedRelease(tag) {
    const release = { id: this.nextRelease++, tag_name: tag, name: tag, draft: true, prerelease: false, assets: [] };
    this.releases.set(release.id, release);
    return release;
  }

  seedAsset(release, name, bytes) {
    const asset = {
      id: this.nextAsset++, name, size: bytes.byteLength, digest: `sha256:${sha(bytes)}`,
      browser_download_url: `https://github.com/meser-recovery/audio-archive/releases/download/${UNTAGGED}/${name}`
    };
    release.assets.push(asset);
    this.assetBytes.set(asset.id, Uint8Array.from(bytes));
    return asset;
  }

  releaseClone(release) {
    return structuredClone(release);
  }

  async fetch(input, options = {}) {
    const url = new URL(input);
    const method = options.method || "GET";
    if (url.hostname === "github.com") {
      const asset = [...this.releases.values()].flatMap((release) => release.assets)
        .find((candidate) => candidate.browser_download_url === String(input));
      return asset ? new Response(this.assetBytes.get(asset.id)) : new Response(null, { status: 404 });
    }

    if (url.hostname === "uploads.github.com" && method === "POST") {
      const releaseId = Number(url.pathname.match(/\/releases\/(\d+)\/assets$/)?.[1]);
      const release = this.releases.get(releaseId);
      const name = url.searchParams.get("name");
      const bytes = new Uint8Array(options.body);
      if (!release || !name) return jsonResponse({ message: "not found" }, 404);
      const asset = this.seedAsset(release, name, bytes);
      this.uploadedDraftUrls.push(asset.browser_download_url);
      return jsonResponse(asset, 201);
    }

    const prefix = "/repos/meser-recovery/audio-archive";
    assert.equal(url.hostname, "api.github.com");
    assert.ok(url.pathname.startsWith(prefix));
    const path = url.pathname.slice(prefix.length);
    const body = options.body === undefined ? null : JSON.parse(options.body);

    if (method === "GET" && path === "/git/ref/heads/main") return jsonResponse({ object: { sha: this.head } });
    if (method === "GET" && path.startsWith("/contents/")) {
      const storagePath = decodeURIComponent(path.slice("/contents/".length));
      if (!this.files.has(storagePath)) return jsonResponse({ message: "not found" }, 404);
      const stored = this.fileBlob(storagePath);
      return jsonResponse({ type: "file", encoding: "base64", content: Buffer.from(stored.content).toString("base64"), sha: stored.blobSha });
    }
    if (method === "GET" && path.startsWith("/git/commits/")) return jsonResponse({ tree: { sha: `tree-${this.head}` } });
    if (method === "POST" && path === "/git/blobs") {
      const objectSha = `blob-${this.nextObject++}`;
      this.blobs.set(objectSha, body.content);
      return jsonResponse({ sha: objectSha }, 201);
    }
    if (method === "POST" && path === "/git/trees") {
      const objectSha = `tree-${this.nextObject++}`;
      this.trees.set(objectSha, body.tree);
      return jsonResponse({ sha: objectSha }, 201);
    }
    if (method === "POST" && path === "/git/commits") {
      const objectSha = `head-${this.nextObject++}`;
      this.commits.set(objectSha, body.tree);
      return jsonResponse({ sha: objectSha }, 201);
    }
    if (method === "PATCH" && path === "/git/refs/heads/main") {
      const entries = this.trees.get(this.commits.get(body.sha));
      for (const entry of entries) {
        if (entry.sha === null) this.files.delete(entry.path);
        else this.files.set(entry.path, JSON.parse(Buffer.from(this.blobs.get(entry.sha), "base64").toString("utf8")));
      }
      this.head = body.sha;
      return jsonResponse({ object: { sha: this.head } });
    }
    if (method === "GET" && path.startsWith("/git/trees/")) {
      const tree = [...this.files.keys()].map((storagePath) => ({ path: storagePath, type: "blob", sha: this.fileBlob(storagePath).blobSha }));
      return jsonResponse({ tree, truncated: false });
    }
    if (method === "GET" && path.startsWith("/git/blobs/")) {
      const blobSha = path.slice("/git/blobs/".length);
      return jsonResponse({ encoding: "base64", content: this.blobs.get(blobSha) });
    }
    if (method === "GET" && path.startsWith("/releases/tags/")) {
      const tag = decodeURIComponent(path.slice("/releases/tags/".length));
      const release = [...this.releases.values()].find((candidate) => candidate.tag_name === tag);
      return release ? jsonResponse(this.releaseClone(release)) : jsonResponse({ message: "not found" }, 404);
    }
    if (method === "POST" && path === "/releases") return jsonResponse(this.releaseClone(this.seedRelease(body.tag_name)), 201);
    const assetsMatch = path.match(/^\/releases\/(\d+)\/assets$/);
    if (method === "GET" && assetsMatch) return jsonResponse(this.releaseClone(this.releases.get(Number(assetsMatch[1]))).assets);
    const releaseMatch = path.match(/^\/releases\/(\d+)$/);
    if (method === "PATCH" && releaseMatch) {
      const release = this.releases.get(Number(releaseMatch[1]));
      release.draft = false;
      for (const asset of release.assets) asset.browser_download_url = canonicalReleaseAssetUrl(release.tag_name, asset.name);
      return jsonResponse(this.releaseClone(release));
    }
    if (method === "GET" && path === "/releases") return jsonResponse([...this.releases.values()].map((release) => this.releaseClone(release)));
    throw new Error(`Unexpected GitHub request: ${method} ${url}`);
  }
}

async function integrationHarness(transport = new GitHubHttpTransport()) {
  const repository = new GitHubArchiveRepository({
    storageOwner: "meser-recovery", storageRepository: "audio-archive", storageBranch: "main",
    githubAppId: "1", githubAppInstallationId: "2", githubAppPrivateKey: "unused"
  }, transport.fetch.bind(transport), CLOCK);
  repository.installationToken = { value: "installation-token", expiresAt: Number.MAX_SAFE_INTEGER };
  const domain = new AudioArchiveDomain(repository, { acceptedPartBytes: 4, clock: CLOCK });
  const verifier = await createPasswordVerifier(PASSWORD, Buffer.alloc(16, 7), { N: 16_384, r: 8, p: 1 });
  const app = createApp({
    config: {
      allowedOrigin: ORIGIN, acceptedPartBytes: 4, sessionSigningSecret: "0123456789abcdef0123456789abcdef",
      sessionLifetimeSeconds: 3_600, sharedPasswordVerifier: verifier
    },
    domain,
    clock: CLOCK
  });
  let cookie = "";
  const fetchImpl = async (input, init = {}) => {
    const url = new URL(input);
    if (url.hostname === "github.com") return transport.fetch(input, init);
    const headers = new Headers(init.headers || {});
    headers.set("Origin", ORIGIN);
    if (cookie) headers.set("Cookie", cookie);
    const response = await app(new Request(input, { ...init, headers }));
    const setCookie = response.headers.get("set-cookie");
    if (setCookie) cookie = setCookie.split(";", 1)[0];
    return response;
  };
  const gateway = new AudioArchiveGateway(BASE_URL, fetchImpl);
  await gateway.login(PASSWORD);
  await gateway.configuration();
  return { transport, repository, gateway };
}

test("real GitHub adapter canonicalizes draft upload URLs for a new frontend ingestion", async () => {
  const harness = await integrationHarness();
  const bytes = Uint8Array.from([0, 1, 2, 3, 4, 5]);
  const completed = await harness.gateway.ingestFiles({
    files: [new File([bytes], "new.wav", { type: "audio/wav" })],
    title: "New adapter ingestion", recordedAt: null, origin: "device", idempotencyKey: "new-adapter-ingestion-operation"
  });
  assert.equal(harness.transport.uploadedDraftUrls.length, 2);
  assert.ok(harness.transport.uploadedDraftUrls.every((url) => url.includes(`/releases/download/${UNTAGGED}/`)));
  const transaction = harness.transport.files.get(`transactions/ingest-${completed.session.transaction.id}.json`);
  const manifest = harness.transport.files.get(`sessions/${completed.session.id}.json`);
  assert.ok(transaction.uploadedParts.every((part) => part.downloadUrl === canonicalReleaseAssetUrl(transaction.releaseTag, part.assetName)));
  assert.ok(manifest.sourceTracks[0].parts.every((part) => part.downloadUrl === canonicalReleaseAssetUrl(manifest.storage.tag, part.assetName)));
  validateSourceSession(manifest);
});

test("frontend resumes one production-shaped legacy draft transaction through the real GitHub adapter", async () => {
  const transport = new GitHubHttpTransport();
  const key = "production-shaped-recovery-operation";
  const bytes = Uint8Array.from([10, 11, 12, 13, 14, 15]);
  const file = new File([bytes], "recovery.wav", { type: "audio/wav" });
  const plan = serializeIngestionPlan(await createIngestionPlan([file], 4, { idempotencyKey: key }));
  const transactionId = uuidFromIdempotencyKey(key);
  const releaseTag = `audio-session-${transactionId}`;
  const release = transport.seedRelease(releaseTag);
  const firstBytes = bytes.subarray(0, 4);
  const firstPlanned = plan.tracks[0].parts[0];
  const firstAsset = transport.seedAsset(release, firstPlanned.assetName, firstBytes);
  const timestamp = "2026-01-02T03:04:05.000Z";
  const transactionPath = `transactions/ingest-${transactionId}.json`;
  transport.files.set(transactionPath, {
    schemaVersion: 1, kind: "ingestion", transactionId, idempotencyHash: hashIdempotencyKey(key), revision: 2, state: "uploading",
    sessionId: transactionId, releaseId: release.id, releaseTag, title: "Production recovery", recordedAt: null, origin: "device",
    supersedesSessionId: null, plan, uploadedParts: [{
      blobId: plan.tracks[0].blobId, partNumber: 1, assetName: firstPlanned.assetName, sizeBytes: firstPlanned.sizeBytes,
      sha256: firstPlanned.sha256, assetId: firstAsset.id, downloadUrl: firstAsset.browser_download_url
    }], stagedManifest: null, createdAt: timestamp, updatedAt: timestamp
  });

  const harness = await integrationHarness(transport);
  const incomplete = await harness.gateway.listIncomplete();
  assert.equal(incomplete.transactions.length, 1);
  assert.equal(incomplete.transactions[0].transactionId, transactionId);

  const repeat = await harness.gateway.request(`/v1/source-sessions/ingestions/${transactionId}/blobs/${plan.tracks[0].blobId}/parts/1`, {
    method: "PUT", body: new Blob([firstBytes]),
    headers: { "Content-Type": "application/octet-stream", "X-Part-SHA256": firstPlanned.sha256, "Idempotency-Key": "repeat-existing-first-part" }
  });
  assert.equal(repeat.assetId, firstAsset.id);
  assert.equal(repeat.downloadUrl, canonicalReleaseAssetUrl(releaseTag, firstPlanned.assetName));
  assert.equal(release.assets.length, 1);

  const secondPlanned = plan.tracks[0].parts[1];
  await harness.gateway.request(`/v1/source-sessions/ingestions/${transactionId}/blobs/${plan.tracks[0].blobId}/parts/2`, {
    method: "PUT", body: new Blob([bytes.subarray(4)]),
    headers: { "Content-Type": "application/octet-stream", "X-Part-SHA256": secondPlanned.sha256, "Idempotency-Key": "upload-missing-second-part" }
  });
  const afterSecond = transport.files.get(transactionPath);
  assert.equal(afterSecond.uploadedParts.length, 2);
  assert.ok(afterSecond.uploadedParts.every((part) => part.downloadUrl === canonicalReleaseAssetUrl(releaseTag, part.assetName)));

  const finalized = await harness.gateway.request(`/v1/source-sessions/ingestions/${transactionId}/finalize`, {
    method: "POST", body: { idempotencyKey: "finalize-existing-transaction" }
  });
  assert.equal(finalized.session.id, transactionId);
  assert.equal(transport.releases.size, 1);
  assert.equal(release.assets.length, 2);
  assert.equal(release.draft, false);
  assert.equal([...transport.files.keys()].filter((path) => path.startsWith("transactions/ingest-")).length, 1);
  assert.equal([...transport.files.keys()].filter((path) => path.startsWith("sessions/")).length, 1);
  assert.equal(transport.files.get("catalog.json").entries.length, 1);
  const storedTransaction = validateTransaction(transport.files.get(transactionPath));
  const manifest = validateSourceSession(transport.files.get(`sessions/${transactionId}.json`));
  assert.equal(storedTransaction.state, "finalized");
  assert.ok(storedTransaction.uploadedParts.every((part) => part.downloadUrl === canonicalReleaseAssetUrl(releaseTag, part.assetName)));
  assert.ok(manifest.sourceTracks[0].parts.every((part) => part.downloadUrl === canonicalReleaseAssetUrl(releaseTag, part.assetName)));
  assert.deepEqual(await harness.gateway.listIncomplete(), { transactions: [], orphans: [] });
  const [reconstructed] = await reconstructSessionTracks(await harness.gateway.getSession(transactionId), harness.gateway.fetchImpl);
  assert.deepEqual(new Uint8Array(await reconstructed.arrayBuffer()), bytes);
});

test("legacy draft URL normalization is narrow and finalized transactions stay strict", async () => {
  const key = "legacy-url-validation-operation";
  const bytes = Uint8Array.from([1, 2, 3, 4]);
  const file = new File([bytes], "strict.wav", { type: "audio/wav" });
  const plan = serializeIngestionPlan(await createIngestionPlan([file], 4, { idempotencyKey: key }));
  const transactionId = uuidFromIdempotencyKey(key);
  const releaseTag = `audio-session-${transactionId}`;
  const part = plan.tracks[0].parts[0];
  const legacy = `https://github.com/meser-recovery/audio-archive/releases/download/${UNTAGGED}/${part.assetName}`;
  const base = {
    schemaVersion: 1, kind: "ingestion", transactionId, idempotencyHash: hashIdempotencyKey(key), revision: 2, state: "uploading",
    sessionId: transactionId, releaseId: 9, releaseTag, title: "Legacy", recordedAt: null, origin: "device", supersedesSessionId: null,
    plan, uploadedParts: [{ blobId: plan.tracks[0].blobId, partNumber: 1, assetName: part.assetName, sizeBytes: part.sizeBytes,
      sha256: part.sha256, assetId: 10, downloadUrl: legacy }], stagedManifest: null,
    createdAt: "2026-01-02T03:04:05.000Z", updatedAt: "2026-01-02T03:04:05.000Z"
  };
  assert.equal(validateTransaction(base).uploadedParts[0].downloadUrl, canonicalReleaseAssetUrl(releaseTag, part.assetName));
  const invalidUrls = [
    legacy.replace(UNTAGGED, "untagged-not-hex"),
    legacy.replace("github.com", "example.com"),
    legacy.replace("meser-recovery/audio-archive", "other/audio-archive"),
    legacy.replace(part.assetName, `wrong-${part.assetName}`),
    `${legacy}?download=1`,
    `${legacy}#fragment`,
    legacy.replace("github.com", "github.com:443")
  ];
  for (const downloadUrl of invalidUrls) {
    await assert.rejects(async () => validateTransaction({ ...base, uploadedParts: [{ ...base.uploadedParts[0], downloadUrl }] }), /Uploaded part URL is invalid/);
  }
  await assert.rejects(async () => validateTransaction({ ...base, state: "finalized" }), /Uploaded part URL is invalid/);
});

test("real GitHub adapter still accepts deletion transaction paths", async () => {
  const transport = new GitHubHttpTransport();
  const repository = new GitHubArchiveRepository({
    storageOwner: "meser-recovery", storageRepository: "audio-archive", storageBranch: "main",
    githubAppId: "1", githubAppInstallationId: "2", githubAppPrivateKey: "unused"
  }, transport.fetch.bind(transport), CLOCK);
  repository.installationToken = { value: "installation-token", expiresAt: Number.MAX_SAFE_INTEGER };
  const transactionId = "22222222-2222-4222-8222-222222222222";
  const path = `transactions/delete-${transactionId}.json`;
  transport.files.set(path, { marker: "deletion" });
  assert.deepEqual((await repository.readJson(path, transport.head)).data, { marker: "deletion" });
});
