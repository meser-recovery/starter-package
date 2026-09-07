import { createHash } from "node:crypto";

export const IDS = Object.freeze({
  session: "11111111-1111-4111-8111-111111111111",
  transaction: "22222222-2222-4222-8222-222222222222",
  track: "33333333-3333-4333-8333-333333333333",
  blob: "44444444-4444-4444-8444-444444444444",
  output: "55555555-5555-4555-8555-555555555555",
  outputBlob: "66666666-6666-4666-8666-666666666666"
});

export function sha(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

export class MemoryRepository {
  constructor() {
    this.head = 0;
    this.files = new Map();
    this.releases = new Map();
    this.nextRelease = 1;
    this.nextAsset = 1;
    this.commits = [];
  }

  async getHead() { return `h${this.head}`; }

  async readJson(path, ref) {
    if (ref !== `h${this.head}`) throw new Error("stale test ref");
    return this.files.has(path) ? { data: structuredClone(this.files.get(path)), blobSha: `b-${path}-${this.head}` } : null;
  }

  async listJson(prefix, ref) {
    if (ref !== `h${this.head}`) throw new Error("stale test ref");
    return [...this.files.entries()].filter(([path]) => path.startsWith(prefix) && path.endsWith(".json"))
      .map(([path, data]) => ({ path, data: structuredClone(data), blobSha: `b-${path}-${this.head}` }));
  }

  async commitJson(expectedHead, files, message) {
    if (expectedHead !== `h${this.head}`) {
      const error = new Error("Canonical state changed; reload and retry"); error.status = 409; throw error;
    }
    for (const [path, value] of Object.entries(files)) value === null ? this.files.delete(path) : this.files.set(path, structuredClone(value));
    this.head++;
    this.commits.push({ message, files: structuredClone(files) });
    return `h${this.head}`;
  }

  async findRelease(tag) { return [...this.releases.values()].find((release) => release.tag_name === tag) || null; }

  async createDraftRelease(tag) {
    const existing = await this.findRelease(tag);
    if (existing) return structuredClone(existing);
    const release = { id: this.nextRelease++, tag_name: tag, draft: true, assets: [] };
    this.releases.set(release.id, release);
    return structuredClone(release);
  }

  async listReleaseAssets(releaseId) { return structuredClone(this.releases.get(releaseId)?.assets || []); }

  async uploadReleaseAsset(releaseId, name, bytes) {
    const release = this.releases.get(releaseId);
    if (!release) throw new Error("release missing");
    const asset = {
      id: this.nextAsset++, name, size: bytes.byteLength, digest: `sha256:${sha(bytes)}`,
      browser_download_url: `https://github.com/meser-recovery/audio-archive/releases/download/${release.tag_name}/${name}`
    };
    release.assets.push(asset);
    return structuredClone(asset);
  }

  async publishRelease(releaseId) { this.releases.get(releaseId).draft = false; }
  async deleteAsset(assetId) {
    for (const release of this.releases.values()) release.assets = release.assets.filter((asset) => asset.id !== assetId);
  }
  async deleteRelease(releaseId) { this.releases.delete(releaseId); }
  async deleteTag() {}
  async listReleases() { return structuredClone([...this.releases.values()]); }
}

export function sampleOutput(sessionId = IDS.session) {
  const bytes = Buffer.from("result");
  const name = `blob-${IDS.outputBlob}-part-0001.bin`;
  return {
    outputId: IDS.output, version: 1, sessionId, createdAt: "2026-01-02T03:04:05.000Z", blobId: IDS.outputBlob,
    sizeBytes: bytes.length, sha256: sha(bytes),
    parts: [{ partNumber: 1, sizeBytes: bytes.length, sha256: sha(bytes), assetName: name, assetId: 90,
      downloadUrl: `https://github.com/meser-recovery/audio-archive/releases/download/audio-session-${sessionId}/${name}` }],
    recipeSnapshotRef: `drafts/${sessionId}/announcement.json#1`, processorVersion: "s07"
  };
}
