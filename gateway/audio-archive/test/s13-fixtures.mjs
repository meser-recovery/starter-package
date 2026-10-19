import { createHash } from 'node:crypto';
import { MemoryRepository, sha } from './helpers.mjs';
import { AudioArchiveDomain } from '../src/domain.mjs';
import { catalogEntry } from '../src/validation.mjs';
import { createIngestionPlan, serializeIngestionPlan } from '../../../service/frontend/scripts/audio-archive-client.mjs';

export const clock = () => Date.parse('2026-10-18T08:00:00.000Z');
export const uuid = n => `10000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
export const identity = value => createHash('sha1').update(JSON.stringify(value)).digest('hex');
export class SnapshotRepository extends MemoryRepository {
  constructor() { super(); this.reads = []; this.blobReads = []; this.trees = 0; }
  async readJson(path, head) { this.reads.push(path); return super.readJson(path, head); }
  async jsonIdentities(prefix, head) {
    if (head !== await this.getHead()) throw new Error('stale fixture ref');
    this.trees++; this.byIdentity = new Map();
    return new Map([...this.files].filter(([path]) => path.startsWith(prefix)).map(([path, value]) => {
      const sha = identity(value); this.byIdentity.set(sha, value); return [path, sha];
    }));
  }
  async readJsonBlob(sha) {
    this.blobReads.push(sha);
    const value = this.byIdentity.get(sha);
    if (!value) return null;
    return { data: structuredClone(value), blobSha: sha };
  }
}
export async function sourceFixture({ tracks = 3, partBytes = 4 } = {}) {
  const repository = new SnapshotRepository(), domain = new AudioArchiveDomain(repository, { acceptedPartBytes: partBytes, clock });
  const originals = Array.from({ length: tracks }, (_, i) => Buffer.from(`source-${i}-audio`));
  const files = originals.map((bytes, i) => new File([bytes], `Дорожка-${i}.wav`, { type: 'audio/wav' }));
  const key = 's13-regression-source-fixture';
  const plan = await createIngestionPlan(files, partBytes, { idempotencyKey: key });
  const op = await domain.beginIngestion({ schemaVersion: 1, idempotencyKey: key, title: 'Запись', recordedAt: null,
    origin: 'manual', supersedesSessionId: null, plan: serializeIngestionPlan(plan) });
  for (const track of plan.tracks) for (const part of track.parts) await domain.uploadPart(op.transactionId, track.blobId, part.partNumber,
    Buffer.from(await part.blob.arrayBuffer()), part.sha256, `${key}:${track.blobId}:${part.partNumber}`);
  const session = (await domain.finalizeIngestion(op.transactionId)).session;
  repository.reads = []; repository.blobReads = [];
  return { repository, domain, session, originals, fetchPart: async url => {
    const part = session.sourceTracks.flatMap(t => t.parts).find(p => p.downloadUrl === url);
    if (!part) throw new Error('Unexpected synthetic part');
    return new Response(repository.assetBytes.get(part.assetId));
  } };
}
export function collection(repository, template, n) {
  const sessions = [];
  for (let i = 1; i <= n; i++) {
    const id = uuid(i), s = JSON.parse(JSON.stringify(template).replaceAll(template.id, id));
    s.id = id; s.title = i === n ? 'Последняя Ё запись' : `Запись ${i % 3}`;
    s.recordedAt = i % 4 ? '2026-10-10T08:00:00.000Z' : null;
    s.lifecycle.state = i % 2 ? 'incoming' : 'archived';
    sessions.push(s); repository.files.set(`sessions/${id}.json`, s);
  }
  repository.files.set('catalog.json', { schemaVersion: 1, revision: n, updatedAt: new Date(clock()).toISOString(), entries: sessions.map(catalogEntry) });
  repository.head++;
  return sessions;
}
