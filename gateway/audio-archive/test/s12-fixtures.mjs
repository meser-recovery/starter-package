import { MemoryRepository } from './helpers.mjs';
import { Buffer } from 'node:buffer';
// Two 120 ms synthetic sine waves encoded by FFmpeg. No real recordings.
export const A = Buffer.from('AAAAHGZ0eXBNNEEgAAACAE00QSBpc29taXNvMgAAAxZtb292AAAAbG12aGQAAAAAAAAAAAAAAAAAAAPoAAAAeAABAAABAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAAACQXRyYWsAAABcdGtoZAAAAAMAAAAAAAAAAAAAAAEAAAAAAAAAeAAAAAAAAAAAAAAAAQEAAAAAAQAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAACRlZHRzAAAAHGVsc3QAAAAAAAAAAQAAAHgAAAQAAAEAAAAAAbltZGlhAAAAIG1kaGQAAAAAAAAAAAAAAAAAAKxEAAAYrFXEAAAAAAAtaGRscgAAAAAAAAAAc291bgAAAAAAAAAAAAAAAFNvdW5kSGFuZGxlcgAAAAFkbWluZgAAABBzbWhkAAAAAAAAAAAAAAAkZGluZgAAABxkcmVmAAAAAAAAAAEAAAAMdXJsIAAAAAEAAAEoc3RibAAAAGpzdHNkAAAAAAAAAAEAAABabXA0YQAAAAAAAAABAAAAAAAAAAAAAQAQAAAAAKxEAAAAAAA2ZXNkcwAAAAADgICAJQABAASAgIAXQBUAAAAAAIl2AACJdgWAgIAFEghW5QAGgICAAQIAAAAgc3R0cwAAAAAAAAACAAAABgAABAAAAAABAAAArAAAABxzdHNjAAAAAAAAAAEAAAABAAAABwAAAAEAAAAwc3RzegAAAAAAAAAAAAAABwAAAJcAAAChAAAAPQAAAEYAAABBAAAAdQAAAAUAAAAUc3RjbwAAAAAAAAABAAADQgAAABpzZ3BkAQAAAHJvbGwAAAACAAAAAf//AAAAHHNiZ3AAAAAAcm9sbAAAAAEAAAAHAAAAAQAAAGF1ZHRhAAAAWW1ldGEAAAAAAAAAIWhkbHIAAAAAAAAAAG1kaXJhcHBsAAAAAAAAAAAAAAAALGlsc3QAAAAkqXRvbwAAABxkYXRhAAAAAQAAAABMYXZmNjEuMS4xMDAAAAAIZnJlZQAAAn5tZGF03ABMYXZjNjEuMy4xMDAAAmClVJDacjLzx6eeNV5y5arrJEeUki/MJBt3A/Beq9i77hstqWkf49Lze96vyeBtTFVjbNaa8+slJpqqYrmKoyaUslLJaaUmjJQpRkoyUSa0NobQwMbNgwMiRAxs2bNokSKU2bNxRRRRRRRRRRRRRRRIiiiiiiiRERESERRREUUSIooiiiii4AE4lNrJXZRTqynVkunP8+3Gmzxq//rX79ca41ev/7Xj+fPGuNXr/+L3/nzxrrWrDf62NH0UGAugTLCFn6nWbymNucBnOAwM7hMwMDO4SEgwM7hISDAwM7uEhKwYGBndwkJOQmwl3+EKsN1PnLlelK3pQm9mblCSpLMGlCQkleBpQkJJXnBjcoSElSWbgwMbCQkqxy8Q1FFFBqKKKNe4zdBuATryixrXjnv9n7+3xbpppeqlyOOSSSLqQO5/fOm7NmNn9yGT4MM/uBk+DDP7wj4+DDP7gcPgDP7gZPgDgAEIMpHinQiHVqz5/+n8f+v/WXxetZM+Pz8T7frt27pKqCYJppsYPV6pplzTTLmymwmXaNj+frzEpj81ymbb/yn4dcsQbOABOFKTGtc+u/4n6+fb4rV3NNLks4UlpIiA/AIEWZnz7cAAAMOHh7biAAw48PPuIAGHHh59xAAYeMPD3sADD2h7fAE6labIxLaHmy21h28fz1PPHF6/+kJclvHjoHpVg93vCaME5xihsvDZeEQ4slnK4TMDXpXCQkGJSyhISEgxJmVThKVKDAxKVl9zf+dL1MpaFf6DD535P2NP5H7XPz4D8Pz4D8NU/df3u3j/OuftpiSmKmIW4AEYgbRw', 'base64');
export const B = Buffer.from('AAAAHGZ0eXBNNEEgAAACAE00QSBpc29taXNvMgAAAxZtb292AAAAbG12aGQAAAAAAAAAAAAAAAAAAAPoAAAAeAABAAABAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAAACQXRyYWsAAABcdGtoZAAAAAMAAAAAAAAAAAAAAAEAAAAAAAAAeAAAAAAAAAAAAAAAAQEAAAAAAQAAAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAACRlZHRzAAAAHGVsc3QAAAAAAAAAAQAAAHgAAAQAAAEAAAAAAbltZGlhAAAAIG1kaGQAAAAAAAAAAAAAAAAAAKxEAAAYrFXEAAAAAAAtaGRscgAAAAAAAAAAc291bgAAAAAAAAAAAAAAAFNvdW5kSGFuZGxlcgAAAAFkbWluZgAAABBzbWhkAAAAAAAAAAAAAAAkZGluZgAAABxkcmVmAAAAAAAAAAEAAAAMdXJsIAAAAAEAAAEoc3RibAAAAGpzdHNkAAAAAAAAAAEAAABabXA0YQAAAAAAAAABAAAAAAAAAAAAAQAQAAAAAKxEAAAAAAA2ZXNkcwAAAAADgICAJQABAASAgIAXQBUAAAAAAH/cAAB/3AWAgIAFEghW5QAGgICAAQIAAAAgc3R0cwAAAAAAAAACAAAABgAABAAAAAABAAAArAAAABxzdHNjAAAAAAAAAAEAAAABAAAABwAAAAEAAAAwc3RzegAAAAAAAAAAAAAABwAAAIoAAACbAAAAPgAAAEAAAABBAAAAYQAAAAUAAAAUc3RjbwAAAAAAAAABAAADQgAAABpzZ3BkAQAAAHJvbGwAAAACAAAAAf//AAAAHHNiZ3AAAAAAcm9sbAAAAAEAAAAHAAAAAQAAAGF1ZHRhAAAAWW1ldGEAAAAAAAAAIWhkbHIAAAAAAAAAAG1kaXJhcHBsAAAAAAAAAAAAAAAALGlsc3QAAAAkqXRvbwAAABxkYXRhAAAAAQAAAABMYXZmNjEuMS4xMDAAAAAIZnJlZQAAAlJtZGF03ABMYXZjNjEuMy4xMDAAAlSlU9E6kiOb5rd/t8a+LW8dbuJI91pJJ7IHGuOz07nWUyUbJTraRx3uq7OPrabkr7+TNstr2Nnp2OkX5iqaxylspZKTQMDfq3wYGBgYGBgYGBgYGBkQMDGzYMDIkSI2bNm4ooooooooooooooooooooooooooooooouAR6U2sldllOrI9WU6f/2v/X24069Tj/x/b/39uNca1f/1/+P/X2411q+P/7n/H/v7ca41rQWfs5FFFERtxm+Bm/sqd1M5myWYMDXgaUGzvODGwYlecGBgYGvODAxIGNjiWbgwMbBiTObubKKB+pRp4jGKMUdiOwi2RNj+Wwi/lsET1euw2Rer4eobkRazgSEzBJwJCQkJShISE8BJvKLGtVz65zf/T/208+ZqXc1dy3MuSILwOwv5Pj4zI3/Hw3mHv76A/8NhPvCB8AO+4D/w2LPeEHbzB33LgD+MpHinWqzM3/9P+3+P/v+s1LycZfjWezymS+UEwAwMOHAw62BhY4GBrw68zeBgalWL0X0r8+ZcpDiFNNKTrwBMFKSYl1pfr134/P17e31rjUuSLkcsi0uVLoB4e3AIECBOZ8+4AAMOHh5+wAAGLQ8PewAMJf40H9Puf40H9IDgAE0labI9WR6sldgdv9f/XzxqcXf/j/9v/KXclz3/7ffiR82gGrgZldDM76IfCeb4a4fy1v5a9YmD4aw/lMBOIBdaQHDdZIQcH4PzOH4GqZ+2kfl+2kfls3wn+DDBy5tznABGIG0cA==', 'base64');
export const CONNECTION = Object.freeze({ connectionId: 'c1111111-1111-4111-8111-111111111111', name: 'Synthetic Zoom', accountId: 'synthetic-account', clientId: 'synthetic-client', clientSecret: 'synthetic-secret', meetingId: '12345678901' });
export class SyntheticZoom {
  constructor() { this.fail = false; this.changed = false; this.downloads = 0; }
  async check(c) { if (c.clientSecret === 'invalid') throw Object.assign(new Error('Zoom: credentials invalid'), { status: 422 }); return { checkedAt: new Date().toISOString(), tracks: 'confirmed' }; }
  async list(c, range) {
    if (this.fail) throw new Error('Synthetic Zoom outage');
    const start = '2026-10-04T08:17:00.000Z';
    if (Date.parse(start) < range.start || Date.parse(start) >= range.end) return [];
    return [{ id: c.meetingId, uuid: 'same-day-A', start_time: start }, { id: c.meetingId, uuid: 'same-day-B', start_time: start }];
  }
  async recording(c, uuid) {
    if (this.fail) throw new Error('Synthetic Zoom outage');
    return { id: c.meetingId, uuid, start_time: new Date(Date.UTC(2026, 9, 4, 8, 17)).toISOString(), participant_audio_files: [A, B].map((bytes, i) => ({
      id: `file-${i + 1}`, file_name: 'participant.m4a', file_type: 'M4A', status: 'completed', file_size: bytes.length,
      recording_start: '2026-10-04T08:17:00Z', recording_end: '2026-10-04T08:17:01Z', download_url: `https://zoom.us/rec/download/synthetic-${i + 1}`
    })) };
  }
  async download(_c, _recording, fileId, signal) {
    signal?.throwIfAborted(); this.downloads++;
    const bytes = Buffer.from(fileId === 'file-1' ? A : B); if (this.changed) bytes[bytes.length - 1] ^= 1;
    return new Response(bytes, { headers: { 'Content-Type': 'audio/mp4', 'Content-Length': String(bytes.length) } });
  }
}

// Models Git's immutable historical refs and GitHub's unique Release tags/asset names.
export class SyntheticArchiveRepository extends MemoryRepository {
  constructor() { super(); this.history = new Map([['h0', new Map()]]); }
  commitJson(...args) { const pending = super.commitJson(...args); this.history.set(`h${this.head}`, structuredClone(this.files)); return pending; }
  async readJson(path, ref) { const files = this.history.get(ref); if (!files) throw new Error('Unknown ref'); return files.has(path) ? { data: structuredClone(files.get(path)), blobSha: `${ref}:${path}` } : null; }
  async listJson(prefix, ref) { return [...this.history.get(ref)].filter(([path]) => path.startsWith(prefix)).map(([path, data]) => ({ path, data: structuredClone(data) })); }
  async createDraftRelease(tag) {
    const found = [...this.releases.values()].find(r => r.tag_name === tag); if (found) return structuredClone(found);
    const release = { id: this.nextRelease++, tag_name: tag, draft: true, assets: [] }; this.releases.set(release.id, release); return structuredClone(release);
  }
  async uploadReleaseAsset(id, name, bytes) { if (this.releases.get(id).assets.some(a => a.name === name)) throw Object.assign(new Error('Name occupied'), { status: 422 }); return super.uploadReleaseAsset(id, name, bytes); }
  async deleteRelease(id) {
    for (const asset of this.releases.get(id)?.assets || []) this.assetBytes.delete(asset.id);
    return super.deleteRelease(id);
  }
}
