import https from 'node:https';
import { lookup } from 'node:dns/promises';
import { isIP } from 'node:net';
import { Readable } from 'node:stream';
import { connectionFingerprint, settingsError } from './settings.mjs';
import { normalizeFilename } from './validation.mjs';

export const encodeZoomUuid = uuid => uuid.startsWith('/') || uuid.includes('//') ? encodeURIComponent(encodeURIComponent(uuid)) : encodeURIComponent(uuid);
export function monthRange(month) {
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(month)) throw settingsError('Выберите месяц.', 400);
  const [y, m] = month.split('-').map(Number);
  if (y < 2000 || y > 2200) throw settingsError('Недопустимый месяц.', 400);
  return { start: Date.UTC(y, m - 1, 1) - 3 * 3600_000, end: Date.UTC(y, m, 1) - 3 * 3600_000 };
}
export function participantFiles(recording) {
  const files = recording.participant_audio_files;
  if (!Array.isArray(files) || !files.length || files.length > 32) throw settingsError('Недоступен полный набор отдельных дорожек (допустимо 1–32).', 409);
  const ids = new Set(); let total = 0;
  return files.map((f, i) => {
    if (typeof f.id !== 'string' || !f.id || ids.has(f.id) || f.status !== 'completed' ||
        (f.file_type !== 'M4A' && f.file_extension !== 'M4A') || !Number.isSafeInteger(f.file_size) || f.file_size < 1 ||
        typeof f.download_url !== 'string') throw settingsError('Одна из отдельных M4A-дорожек недоступна.', 409);
    ids.add(f.id); total += f.file_size;
    if (total > 500 * 1024 * 1024) throw settingsError('Полная запись превышает 500 MiB.', 409);
    const name = normalizeFilename((typeof f.file_name === 'string' ? f.file_name : `Дорожка ${i + 1}`).normalize('NFC').replace(/[\x00-\x1f/\\]/g, '_').slice(0, 150).replace(/\.m4a$/i, '') + '.m4a');
    return { id: f.id, name, sizeBytes: f.file_size, startTime: f.recording_start || null, endTime: f.recording_end || null };
  });
}
export function safeDownloadUrl(value) {
  let url; try { url = new URL(value); } catch { throw settingsError('Небезопасный адрес дорожки.', 502); }
  if (url.protocol !== 'https:' || url.username || url.password || url.hash || (url.port && url.port !== '443') ||
      !['zoom.us', 'zoomcdn.net'].some(d => url.hostname === d || url.hostname.endsWith(`.${d}`))) throw settingsError('Небезопасный адрес дорожки.', 502);
  return url;
}
export function publicAddress(address) {
  if (isIP(address) === 4) {
    const [a, b, c] = address.split('.').map(Number);
    return a !== 0 && a !== 10 && a !== 127 && a < 224 && !(a === 169 && b === 254) && !(a === 172 && b >= 16 && b <= 31) &&
      !(a === 192 && (b === 168 || b === 0 || (b === 88 && c === 99))) && !(a === 100 && b >= 64 && b <= 127) &&
      !(a === 198 && (b === 18 || b === 19 || (b === 51 && c === 100))) && !(a === 203 && b === 0 && c === 113);
  }
  // Only global-unicast IPv6; excludes mapped IPv4, ULA, multicast and link local.
  if (isIP(address) !== 6) return false;
  const normalized = new URL(`http://[${address}]/`).hostname;
  return /^\[[23][0-9a-f]{3}:/i.test(normalized) && !/^\[(?:2002:|2001:(?:db8|0|2|10|20):)/i.test(normalized);
}
export async function openZoomStream(value, token, sizeBytes, signal, { lookupImpl = lookup, requestImpl = https.request } = {}) {
  let url = safeDownloadUrl(value);
  for (let redirects = 0; redirects <= 4; redirects++) {
    signal?.throwIfAborted();
    const addresses = await lookupImpl(url.hostname, { all: true });
    if (!addresses.length || addresses.some(a => !publicAddress(a.address))) throw settingsError('Небезопасный адрес сервера дорожки.', 502);
    const pinned = addresses[0];
    const response = await new Promise((resolve, reject) => {
      const req = requestImpl(url, { method: 'GET', signal, timeout: 30_000,
        lookup: (_host, options, callback) => options.all ? callback(null, [pinned]) : callback(null, pinned.address, pinned.family),
        headers: url.hostname === 'zoom.us' || url.hostname.endsWith('.zoom.us') ? { Authorization: `Bearer ${token}` } : {} }, resolve);
      req.once('timeout', () => req.destroy(settingsError('Время загрузки дорожки истекло.', 504)));
      req.once('error', () => reject(settingsError('Загрузка дорожки прервана.', 502))); req.end();
    });
    if ([301, 302, 303, 307, 308].includes(response.statusCode)) {
      response.destroy(); url = safeDownloadUrl(new URL(response.headers.location || '', url).href); continue;
    }
    const type = String(response.headers['content-type'] || '').toLowerCase().split(';')[0];
    if (response.statusCode !== 200 || !['audio/mp4', 'audio/x-m4a', 'application/octet-stream'].includes(type) ||
        (response.headers['content-length'] && Number(response.headers['content-length']) !== sizeBytes)) {
      response.destroy(); throw settingsError('Сервер Zoom не подтвердил M4A-дорожку.', 502);
    }
    const reader = Readable.toWeb(response, { strategy: { highWaterMark: 64 * 1024, size: chunk => chunk.length } }).getReader(); let received = 0;
    const body = new ReadableStream({
      async pull(controller) {
        try {
          const part = await reader.read();
          if (part.done) { if (received !== sizeBytes) throw new Error(); controller.close(); return; }
          received += part.value.byteLength; if (received > sizeBytes) throw new Error(); controller.enqueue(part.value);
        } catch { await reader.cancel().catch(() => {}); controller.error(settingsError('Неполная дорожка Zoom.', 502)); }
      }, cancel(reason) { response.destroy(); return reader.cancel(reason); }
    }, { highWaterMark: 1 });
    return new Response(body, { headers: { 'Content-Type': 'audio/mp4', 'Content-Length': String(sizeBytes) } });
  }
  throw settingsError('Слишком много перенаправлений Zoom.', 502);
}

export class ZoomClient {
  constructor({ fetchImpl = fetch, clock = () => Date.now(), streamImpl = openZoomStream } = {}) {
    this.fetchImpl = fetchImpl; this.clock = clock; this.streamImpl = streamImpl; this.tokens = new Map();
  }
  async response(url, options, phase) {
    let response;
    try { response = await this.fetchImpl(url, { ...options, redirect: 'error', signal: options.signal || AbortSignal.timeout(30_000) }); }
    catch { throw settingsError('Zoom: ошибка сети.', 502); }
    if (!response.ok) {
      const message = response.status === 429 ? 'Zoom: ограничение частоты запросов. Повторите позже.' : response.status === 403 ? 'Zoom: недостаточно прав чтения.' : phase === 'auth' ? 'Zoom: проверьте credentials и активацию приложения.' : phase === 'meeting' ? 'Zoom: Meeting ID недоступен.' : 'Zoom: запись или дорожки недоступны.';
      const error = settingsError(message, response.status === 429 ? 429 : 422);
      if (response.status === 429) error.retryAfter = Math.min(3600, Math.max(1, Number(response.headers.get('retry-after')) || 60));
      await response.body?.cancel(); throw error;
    }
    return response;
  }
  async token(c) {
    const key = connectionFingerprint(c), cached = this.tokens.get(key);
    if (cached?.expires > this.clock() + 60_000) return cached.token;
    const response = await this.response('https://zoom.us/oauth/token', { method: 'POST', headers: {
      Authorization: `Basic ${Buffer.from(`${c.clientId}:${c.clientSecret}`).toString('base64')}`, 'Content-Type': 'application/x-www-form-urlencoded'
    }, body: new URLSearchParams({ grant_type: 'account_credentials', account_id: c.accountId }).toString() }, 'auth');
    const body = await response.json().catch(() => null);
    if (!body || typeof body.access_token !== 'string' || !Number.isFinite(body.expires_in)) throw settingsError('Zoom: неверный ответ авторизации.', 502);
    if (this.tokens.size >= 64) this.tokens.delete(this.tokens.keys().next().value);
    this.tokens.set(key, { token: body.access_token, expires: this.clock() + Math.min(3600, body.expires_in) * 1000 }); return body.access_token;
  }
  async api(c, path, phase) {
    const response = await this.response(`https://api.zoom.us/v2${path}`, { headers: { Authorization: `Bearer ${await this.token(c)}` } }, phase);
    try { return await response.json(); } catch { throw settingsError('Zoom: неверный ответ API.', 502); }
  }
  meeting(c) { return this.api(c, `/meetings/${c.meetingId}`, 'meeting'); }
  recording(c, uuid) { return this.api(c, `/meetings/${encodeZoomUuid(uuid)}/recordings`, 'recording'); }
  async list(c, range) {
    const meeting = await this.meeting(c);
    if (String(meeting.id) !== c.meetingId || typeof meeting.host_id !== 'string') throw settingsError('Zoom: Meeting ID не совпал.', 422);
    const result = new Map();
    // Date-only Zoom filters cover at most 30 days; overlap edges and filter MSK exactly.
    for (let from = range.start; from < range.end; from += 28 * 86400_000) {
      const to = Math.min(range.end, from + 28 * 86400_000), tokens = new Set(); let next = '';
      do {
        const query = new URLSearchParams({ from: new Date(from).toISOString().slice(0, 10), to: new Date(to).toISOString().slice(0, 10), page_size: '100', next_page_token: next });
        const page = await this.api(c, `/users/${encodeURIComponent(meeting.host_id)}/recordings?${query}`, 'list');
        if (!Array.isArray(page.meetings)) throw settingsError('Zoom: неполный список записей.', 502);
        for (const m of page.meetings) if (String(m.id) === c.meetingId && Date.parse(m.start_time) >= range.start && Date.parse(m.start_time) < range.end) {
          if (typeof m.uuid !== 'string' || !m.uuid) throw settingsError('Zoom: отсутствует occurrence UUID.', 502); result.set(m.uuid, m);
        }
        next = page.next_page_token || '';
        if (next && (tokens.has(next) || tokens.size >= 1000)) throw settingsError('Zoom: pagination не завершена.', 502); tokens.add(next);
      } while (next);
    }
    return [...result.values()];
  }
  async check(c) {
    const now = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Moscow', year: 'numeric', month: '2-digit' }).format(new Date(this.clock()));
    const recordings = await this.list(c, monthRange(now));
    for (const sample of recordings) {
      const recording = await this.recording(c, sample.uuid);
      let files;
      try { files = participantFiles(recording); }
      catch (error) {
        // Ineligible participant sets are not authorization/download failures.
        // Inspect every occurrence before claiming there is no usable sample.
        if (error.status === 409) continue;
        throw error;
      }
      for (const file of files) { const response = await this.download(c, recording, file.id, undefined); await response.body.cancel(); }
      return { checkedAt: new Date(this.clock()).toISOString(), tracks: 'confirmed' };
    }
    return { checkedAt: new Date(this.clock()).toISOString(), tracks: 'unconfirmed' };
  }
  async download(c, recording, fileId, signal) {
    const files = participantFiles(recording), file = files.find(f => f.id === fileId);
    if (!file) throw settingsError('Zoom: дорожка отсутствует.', 409);
    return this.streamImpl(recording.participant_audio_files.find(f => f.id === fileId).download_url, await this.token(c), file.sizeBytes, signal);
  }
}
