import { createHash } from 'node:crypto';
import { validateCatalog, validateSourceSession, ValidationError } from './validation.mjs';

const fields = ['page', 'pageSize', 'snapshot', 'queryId', 'search', 'month', 'from', 'to', 'sort', 'lifecycle', 'sources', 'attention', 'speakerProject', 'announcementResult', 'speakerResult', 'announcementState', 'speakerState', 'view'];
const sorts = ['newest', 'oldest', 'updated', 'title', 'title-desc', 'version', 'version-desc'];
const bools = ['attention', 'speakerProject'];
const normalized = value => String(value || '').normalize('NFKC').toLocaleLowerCase('ru');
const text = (a, b) => String(a).localeCompare(String(b), 'ru');
const date = (a, b, direction) => {
  const x = Date.parse(a), y = Date.parse(b);
  if (!Number.isFinite(x)) return Number.isFinite(y) ? 1 : 0;
  if (!Number.isFinite(y)) return -1;
  return (x - y) * direction;
};
const changed = () => Object.assign(new Error('Archive snapshot changed; restart the list.'), { status: 409, code: 'snapshot_changed' });

export function listQuery(input = {}) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) throw new ValidationError('Invalid list query');
  for (const key of Object.keys(input)) if (!fields.includes(key)) throw new ValidationError('Unsupported list query');
  const q = { page: 0, pageSize: 10, snapshot: '', queryId: '', search: '', month: '', from: '', to: '', sort: 'newest', lifecycle: '', sources: '', attention: false, speakerProject: false, announcementResult: '', speakerResult: '', announcementState: '', speakerState: '', view: 'sessions', ...input };
  for (const key of ['page', 'pageSize']) {
    if (typeof q[key] === 'string' && /^(0|[1-9][0-9]*)$/.test(q[key])) q[key] = Number(q[key]);
    if (!Number.isSafeInteger(q[key]) || q[key] < (key === 'page' ? 0 : 10) || q[key] > (key === 'page' ? 1000000 : 10)) throw new ValidationError('Invalid list page');
  }
  for (const key of bools) {
    if (q[key] === 'true' || q[key] === 'false') q[key] = q[key] === 'true';
    if (typeof q[key] !== 'boolean') throw new ValidationError('Invalid list boolean');
  }
  for (const key of fields.filter(key => !['page', 'pageSize', ...bools].includes(key))) if (typeof q[key] !== 'string') throw new ValidationError('Invalid list text');
  if (q.search.length > 400 || q.snapshot.length > 128 || !sorts.includes(q.sort) || !['', 'incoming', 'archived'].includes(q.lifecycle) ||
      !['', 'available', 'unavailable'].includes(q.sources) || !['sessions', 'announcement', 'speaker'].includes(q.view)) throw new ValidationError('Invalid list filter');
  for (const key of ['announcementResult', 'speakerResult']) if (!['', 'yes', 'no'].includes(q[key])) throw new ValidationError('Invalid result filter');
  for (const key of ['announcementState', 'speakerState']) if (!['', 'new', 'in_progress', 'result_ready'].includes(q[key])) throw new ValidationError('Invalid workflow filter');
  for (const key of ['from', 'to']) if (q[key] && (!/^\d{4}-\d{2}-\d{2}$/.test(q[key]) || !Number.isFinite(Date.parse(q[key])) || new Date(q[key]).toISOString().slice(0, 10) !== q[key])) throw new ValidationError('Invalid list date');
  if (q.from && q.to && q.from > q.to) throw new ValidationError('Invalid list date range');
  if (q.month && !/^\d{4}-(0[1-9]|1[0-2])$/.test(q.month)) throw new ValidationError('Invalid list month');
  if (q.queryId && !/^[a-f0-9]{64}$/.test(q.queryId)) throw new ValidationError('Invalid list query identity');
  return q;
}

export function sessionSummary(session) {
  return { kind: 'source-session-summary', schemaVersion: 1, id: session.id, revision: session.revision, title: session.title,
    recordedAt: session.recordedAt, createdAt: session.createdAt, updatedAt: session.updatedAt, lifecycle: { ...session.lifecycle }, sourceState: session.sourceState,
    sourceTrackCount: session.sourceState === 'available' ? session.sourceTracks.length : session.deletedSources.tracks.length,
    sourceNames: session.sourceTracks.map(track => track.originalName),
    workflows: Object.fromEntries(['announcement', 'speaker'].map(name => [name, { status: session.workflows[name].status,
      hasDraft: Boolean(session.workflows[name].currentDraft), outputCount: session.workflows[name].outputs.length }])) };
}

// One validated immutable snapshot is shared by Archive and both editor pickers.
// It is never a write authority. Full selected reads and mutation guards stay canonical.
export class ArchiveReadModel {
  constructor(repository) { this.repository = repository; this.current = null; this.builds = new Map(); this.blobs = new Map(); }
  async snapshot() {
    const head = await this.repository.getHead(); // Always confirm current upstream access.
    if (this.current?.head === head) return this.current;
    if (this.builds.has(head)) return this.builds.get(head);
    // Bound simultaneous snapshots as well as the retained model.
    if (this.builds.size) { await Promise.allSettled([...this.builds.values()]); return this.snapshot(); }
    const build = this.build(head);
    this.builds.set(head, build);
    try { return await build; } finally { this.builds.delete(head); }
  }
  async build(head) {
    const stored = await this.repository.readJson('catalog.json', head);
    const catalog = stored ? validateCatalog(stored.data) : { revision: 0, entries: [] };
    if (catalog.entries.length > 10000) throw new ValidationError('Archive read model budget exceeded');
    const identities = this.repository.jsonIdentities ? await this.repository.jsonIdentities('sessions/', head) : null;
    const nextBlobs = new Map(), rows = [];
    let budget = 0;
    for (const entry of catalog.entries) {
      const path = `sessions/${entry.id}.json`, identity = identities?.get(path);
      if (identities && !identity) throw new Error('Catalog manifest is absent from the immutable tree');
      let canonical = identity && this.blobs.get(identity);
      if (!canonical) {
        const value = identity && this.repository.readJsonBlob ? await this.repository.readJsonBlob(identity) : await this.repository.readJson(path, head);
        if (!value || value.invalid || value.data?.kind === 'deletion_tombstone') throw new Error('Catalog references an unavailable manifest');
        canonical = validateSourceSession(value.data);
      }
      if (canonical.id !== entry.id) throw new Error('Catalog manifest identity mismatch');
      budget += Buffer.byteLength(JSON.stringify(canonical));
      if (budget > 32 * 1024 * 1024) throw new Error('Archive read model memory budget exceeded');
      if (identity) nextBlobs.set(identity, canonical);
      rows.push({ summary: sessionSummary(canonical), outputs: Object.fromEntries(['announcement', 'speaker'].map(name => [name,
        canonical.workflows[name].outputs.map(output => ({ outputId: output.outputId, version: output.version, createdAt: output.createdAt, sizeBytes: output.sizeBytes }))])) });
    }
    if (await this.repository.getHead() !== head) throw changed();
    const result = { head, revision: catalog.revision, rows };
    this.blobs = nextBlobs; this.current = result;
    return result;
  }
  async query(input, attentionProvider) {
    const q = listQuery(input), snapshot = await this.snapshot();
    if (q.snapshot && q.snapshot !== snapshot.head) throw changed();
    const attention = q.attention ? await attentionProvider(snapshot.head) : null;
    const attentionIds = new Set(attention?.transactions.map(t => t.sessionId));
    const query = normalized(q.search).trim();
    let rows = snapshot.rows.filter(({ summary: s }) => {
      if (query && normalized(s.id) !== query && ![s.title, ...s.sourceNames].some(value => normalized(value).includes(query))) return false;
      if (q.lifecycle && s.lifecycle.state !== q.lifecycle) return false;
      if (q.sources && (s.sourceState === 'available' ? 'available' : 'unavailable') !== q.sources) return false;
      if (q.attention && !attentionIds.has(s.id)) return false;
      if (q.speakerProject && !s.workflows.speaker.hasDraft) return false;
      for (const name of ['announcement', 'speaker']) {
        // Preserve the legacy selector's result-membership precondition as well
        // as its yes/no state filter (including the legacy empty "no" query).
        if (q[name + 'Result'] && !s.workflows[name].outputCount) return false;
        if (q[name + 'State'] && s.workflows[name].status !== q[name + 'State']) return false;
        if (q[name + 'Result'] && Boolean(s.workflows[name].outputCount) !== (q[name + 'Result'] === 'yes')) return false;
      }
      const day = s.recordedAt ? new Date(s.recordedAt).toISOString().slice(0, 10) : '';
      return !(q.month && !String(s.recordedAt || '').startsWith(q.month)) && !((q.from || q.to) && (!day || (q.from && day < q.from) || (q.to && day > q.to)));
    });
    let items;
    if (q.view === 'sessions') {
      items = rows.map(row => row.summary).sort((a, b) => (q.sort === 'title' ? text(a.title, b.title) : q.sort === 'title-desc' ? text(b.title, a.title) :
        q.sort === 'updated' ? date(a.updatedAt, b.updatedAt, -1) : date(a.recordedAt, b.recordedAt, q.sort === 'oldest' ? 1 : -1)) || text(a.id, b.id));
    } else {
      items = rows.flatMap(row => row.outputs[q.view].map(output => ({ session: row.summary, output, workflow: q.view }))).sort((a, b) =>
        (q.sort === 'version' ? a.output.version - b.output.version : q.sort === 'version-desc' ? b.output.version - a.output.version :
          q.sort === 'title' ? text(a.session.title, b.session.title) : date(a.output.createdAt, b.output.createdAt, q.sort === 'oldest' ? 1 : -1)) ||
        text(a.session.id, b.session.id) || a.output.version - b.output.version || text(a.output.outputId, b.output.outputId));
    }
    const queryId = createHash('sha256').update(JSON.stringify({ ...q, snapshot: '', queryId: '', page: 0 })).digest('hex');
    if (q.queryId && q.queryId !== queryId) throw changed();
    return { schemaVersion: 1, kind: 'archive-page', snapshot: snapshot.head, revision: snapshot.revision, queryId, page: q.page, pageSize: q.pageSize,
      total: items.length, view: q.view, items: structuredClone(items.slice(q.page * q.pageSize, (q.page + 1) * q.pageSize)) };
  }
}
