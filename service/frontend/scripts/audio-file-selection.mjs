import { MAX_AUDIO_SESSION_BYTES, normalizedMediaType, sha256Hex } from './audio-archive-client.mjs';

export async function ingestionSessionId(key) {
  const hex = (await sha256Hex(key)).slice(0, 32).split('');
  hex[12] = '5';
  hex[16] = ['8', '9', 'a', 'b'][Number.parseInt(hex[16], 16) & 3];
  return `${hex.slice(0, 8).join('')}-${hex.slice(8, 12).join('')}-${hex.slice(12, 16).join('')}-${hex.slice(16, 20).join('')}-${hex.slice(20).join('')}`;
}

export function validateAudioSelection(files) {
  if (!files.length) return 'Выберите хотя бы одну аудиодорожку.';
  if (files.some(file => !file || !Number.isSafeInteger(file.size) || file.size < 1)) return 'Пустые аудиофайлы загружать нельзя.';
  if (files.reduce((sum, file) => sum + file.size, 0) > MAX_AUDIO_SESSION_BYTES) return 'Общий размер файлов превышает 500 МБ.';
  try { files.forEach(file => normalizedMediaType(file.name, file.type)); }
  catch (error) { return error.message; }
  return '';
}

export function recordedTimestamp(input) {
  if (!input.value) return null;
  if (!input.validity.valid) throw new Error('Проверьте дату и время записи.');
  const date = new Date(input.value);
  if (!Number.isFinite(date.getTime())) throw new Error('Проверьте дату и время записи.');
  return date.toISOString();
}

export function renderAudioSelection(list, summary, files, formatBytes) {
  list.replaceChildren();
  files.forEach(file => {
    const item = document.createElement('li');
    item.textContent = `${file.name} · ${file.name.split('.').pop().toUpperCase()} · ${formatBytes(file.size)}`;
    list.append(item);
  });
  summary.textContent = files.length ? `${files.length} дорожек · ${formatBytes(files.reduce((sum, file) => sum + file.size, 0))}` : 'Файлы не выбраны';
}

export function sameFileReferences(left, right) {
  return left.length === right.length && left.every((file, index) => file === right[index]);
}

// Resolve a local Speaker source change before any ingestion transaction can begin.
// The caller keeps its form and File objects if closing the current project is declined.
export async function prepareLocalIngestionSelection(files, { speakerFiles = null, forceSwitch = false, closeSpeaker, waitForIdle, currentFiles, loadFiles }) {
  if (!forceSwitch && speakerFiles && sameFileReferences(files, speakerFiles)) return { switched: false, declined: false };
  if (!forceSwitch && !speakerFiles && sameFileReferences(files, currentFiles())) return { switched: false, declined: false };
  if (speakerFiles && !await closeSpeaker()) return { switched: false, declined: true };
  await waitForIdle();
  loadFiles(files);
  if (!sameFileReferences(files, currentFiles())) throw new Error('Новые дорожки не стали текущими локальными исходниками.');
  return { switched: true, declined: false };
}

// File objects live in memory so a cancelled picker or service reconnect cannot clear them.
export class AudioFileSelection {
  files = [];
  choose(candidates, mode = 'replace') {
    const picked = Array.from(candidates || []);
    if (!picked.length) return false;
    const next = mode === 'add' ? [...this.files, ...picked] : picked;
    const error = validateAudioSelection(next);
    if (error) throw new Error(error);
    this.files = next;
    return true;
  }
  clear() { this.files = []; }
}
