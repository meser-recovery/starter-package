import { createSign } from "node:crypto";
import { UUID_PATTERN } from "./validation.mjs";

const API_VERSION = "2026-03-10";
const STORAGE_PATH = /^(?:catalog\.json|sessions\/[0-9a-f-]{36}\.json|drafts\/[0-9a-f-]{36}\/(?:announcement|speaker)\.json|transactions\/(?:ingest|delete)-(?:[0-9a-f-]{36}|[0-9a-f]{64})\.json)$/;

export class GitHubError extends Error {
  constructor(message, status, responseBody = null) {
    super(message);
    this.name = "GitHubError";
    this.status = status;
    this.responseBody = responseBody;
  }
}

function base64url(value) {
  return Buffer.from(value).toString("base64url");
}

function assertStoragePath(path) {
  if (!STORAGE_PATH.test(path) || path.includes("..")) throw new Error("Unsafe internal storage path");
  const uuid = path.match(/[0-9a-f-]{36}/)?.[0];
  if (uuid && !UUID_PATTERN.test(uuid)) throw new Error("Unsafe internal UUID path");
  return path;
}

export function createGitHubAppJwt(appId, privateKey, now = Date.now()) {
  const issuedAt = Math.floor(now / 1000) - 60;
  const header = base64url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const payload = base64url(JSON.stringify({ iat: issuedAt, exp: issuedAt + 9 * 60, iss: String(appId) }));
  const input = `${header}.${payload}`;
  const signer = createSign("RSA-SHA256");
  signer.update(input);
  signer.end();
  return `${input}.${signer.sign(privateKey, "base64url")}`;
}

export class GitHubArchiveRepository {
  constructor(config, fetchImpl = fetch, clock = () => Date.now()) {
    this.owner = config.storageOwner;
    this.repository = config.storageRepository;
    this.branch = config.storageBranch;
    this.appId = config.githubAppId;
    this.installationId = config.githubAppInstallationId;
    this.privateKey = config.githubAppPrivateKey;
    this.fetchImpl = fetchImpl;
    this.clock = clock;
    this.installationToken = null;
  }

  async token() {
    if (this.installationToken && this.installationToken.expiresAt > this.clock() + 60_000) return this.installationToken.value;
    const jwt = createGitHubAppJwt(this.appId, this.privateKey, this.clock());
    const response = await this.fetchImpl(`https://api.github.com/app/installations/${this.installationId}/access_tokens`, {
      method: "POST",
      headers: this.headers(jwt)
    });
    const body = await this.readJsonResponse(response, "installation token");
    if (!response.ok || typeof body.token !== "string") throw new GitHubError("GitHub installation authentication failed", response.status);
    this.installationToken = { value: body.token, expiresAt: Date.parse(body.expires_at) || this.clock() + 50 * 60_000 };
    return body.token;
  }

  headers(token, extra = {}) {
    return {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${token}`,
      "X-GitHub-Api-Version": API_VERSION,
      "User-Agent": "meser-audio-archive-gateway/1",
      ...extra
    };
  }

  async readJsonResponse(response, operation) {
    const type = response.headers.get("content-type") || "";
    if (!type.toLowerCase().includes("application/json")) {
      if (response.status === 204) return null;
      throw new GitHubError(`GitHub ${operation} returned an unexpected response`, response.status);
    }
    try {
      return await response.json();
    } catch {
      throw new GitHubError(`GitHub ${operation} returned invalid JSON`, response.status);
    }
  }

  async api(path, { method = "GET", body, headers = {}, allow404 = false } = {}) {
    const token = await this.token();
    const response = await this.fetchImpl(`https://api.github.com/repos/${this.owner}/${this.repository}${path}`, {
      method,
      headers: this.headers(token, body === undefined ? headers : { "Content-Type": "application/json", ...headers }),
      body: body === undefined ? undefined : JSON.stringify(body)
    });
    if (allow404 && response.status === 404) return null;
    const data = await this.readJsonResponse(response, path);
    if (!response.ok) throw new GitHubError(`GitHub storage operation failed`, response.status, data);
    return data;
  }

  async getHead() {
    const result = await this.api(`/git/ref/heads/${encodeURIComponent(this.branch)}`);
    return result.object.sha;
  }

  async readJson(path, ref) {
    assertStoragePath(path);
    const result = await this.api(`/contents/${path}?ref=${encodeURIComponent(ref)}`, { allow404: true });
    if (!result) return null;
    if (result.type !== "file" || result.encoding !== "base64") throw new GitHubError("GitHub storage file is not a regular base64 blob", 502);
    try {
      return { data: JSON.parse(Buffer.from(result.content, "base64").toString("utf8")), blobSha: result.sha };
    } catch {
      throw new GitHubError("GitHub storage JSON is invalid", 502);
    }
  }

  async listJson(prefix, ref) {
    if (!/^(sessions|transactions|drafts)\/$/.test(prefix)) throw new Error("Unsafe internal list prefix");
    const tree = await this.api(`/git/trees/${encodeURIComponent(ref)}?recursive=1`);
    const items = [];
    for (const entry of tree.tree || []) {
      if (entry.type !== "blob" || !entry.path.startsWith(prefix) || !entry.path.endsWith(".json") || !STORAGE_PATH.test(entry.path)) continue;
      const blob = await this.api(`/git/blobs/${entry.sha}`);
      try {
        items.push({ path: entry.path, data: JSON.parse(Buffer.from(blob.content, "base64").toString("utf8")), blobSha: entry.sha });
      } catch {
        items.push({ path: entry.path, invalid: true, blobSha: entry.sha });
      }
    }
    return items;
  }

  async commitJson(expectedHead, files, message) {
    const currentHead = await this.getHead();
    if (currentHead !== expectedHead) {
      const error = new Error("Canonical state changed; reload and retry");
      error.status = 409;
      throw error;
    }
    const commit = await this.api(`/git/commits/${currentHead}`);
    const treeEntries = [];
    for (const [path, value] of Object.entries(files)) {
      assertStoragePath(path);
      if (value === null) {
        treeEntries.push({ path, mode: "100644", type: "blob", sha: null });
      } else {
        const content = `${JSON.stringify(value, null, 2)}\n`;
        const blob = await this.api("/git/blobs", { method: "POST", body: { content: Buffer.from(content).toString("base64"), encoding: "base64" } });
        treeEntries.push({ path, mode: "100644", type: "blob", sha: blob.sha });
      }
    }
    const tree = await this.api("/git/trees", { method: "POST", body: { base_tree: commit.tree.sha, tree: treeEntries } });
    const nextCommit = await this.api("/git/commits", { method: "POST", body: { message, tree: tree.sha, parents: [currentHead] } });
    try {
      await this.api(`/git/refs/heads/${encodeURIComponent(this.branch)}`, { method: "PATCH", body: { sha: nextCommit.sha, force: false } });
    } catch (error) {
      if (error instanceof GitHubError && [409, 422].includes(error.status)) {
        const conflict = new Error("Canonical state changed; reload and retry");
        conflict.status = 409;
        throw conflict;
      }
      throw error;
    }
    return nextCommit.sha;
  }

  async findRelease(tag) {
    return this.api(`/releases/tags/${encodeURIComponent(tag)}`, { allow404: true });
  }

  async createDraftRelease(tag) {
    const existing = await this.findRelease(tag);
    if (existing) return existing;
    try {
      return await this.api("/releases", { method: "POST", body: { tag_name: tag, name: tag, draft: true, prerelease: false } });
    } catch (error) {
      if (error instanceof GitHubError && error.status === 422) {
        const raced = await this.findRelease(tag);
        if (raced) return raced;
      }
      throw error;
    }
  }

  async listReleaseAssets(releaseId) {
    const assets = [];
    for (let page = 1; page <= 10; page++) {
      const batch = await this.api(`/releases/${releaseId}/assets?per_page=100&page=${page}`);
      assets.push(...batch);
      if (batch.length < 100) break;
    }
    return assets;
  }

  async uploadReleaseAsset(releaseId, name, bytes) {
    if (!/^blob-[0-9a-f-]{36}-part-\d{4}\.bin$/.test(name)) throw new Error("Unsafe release asset name");
    const token = await this.token();
    const response = await this.fetchImpl(`https://uploads.github.com/repos/${this.owner}/${this.repository}/releases/${releaseId}/assets?name=${encodeURIComponent(name)}`, {
      method: "POST",
      headers: this.headers(token, { "Content-Type": "application/octet-stream", "Content-Length": String(bytes.byteLength) }),
      body: bytes
    });
    const data = await this.readJsonResponse(response, "asset upload");
    if (!response.ok) throw new GitHubError("GitHub asset upload failed", response.status, data);
    return data;
  }

  async publishRelease(releaseId) {
    return this.api(`/releases/${releaseId}`, { method: "PATCH", body: { draft: false, prerelease: false } });
  }

  async deleteAsset(assetId) {
    const token = await this.token();
    const response = await this.fetchImpl(`https://api.github.com/repos/${this.owner}/${this.repository}/releases/assets/${assetId}`, {
      method: "DELETE", headers: this.headers(token)
    });
    if (![204, 404].includes(response.status)) throw new GitHubError("GitHub asset deletion failed", response.status);
  }

  async deleteRelease(releaseId) {
    const token = await this.token();
    const response = await this.fetchImpl(`https://api.github.com/repos/${this.owner}/${this.repository}/releases/${releaseId}`, {
      method: "DELETE", headers: this.headers(token)
    });
    if (![204, 404].includes(response.status)) throw new GitHubError("GitHub release deletion failed", response.status);
  }

  async deleteTag(tag) {
    const token = await this.token();
    const response = await this.fetchImpl(`https://api.github.com/repos/${this.owner}/${this.repository}/git/refs/tags/${encodeURIComponent(tag)}`, {
      method: "DELETE", headers: this.headers(token)
    });
    if (![204, 404].includes(response.status)) throw new GitHubError("GitHub tag deletion failed", response.status);
  }

  async listReleases() {
    return this.api("/releases?per_page=100");
  }
}
