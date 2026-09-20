import { createWaveformReader } from '../../scripts/speaker-waveform.mjs';

const fixtureUrl = './fixtures/s10a-long-aac-lc-3747s.m4a';
const duration = 3747.648;
const report = document.getElementById('report');
const abortButton = document.getElementById('abort');
const retryButton = document.getElementById('retry');
let controller = null;
let lastCount = 1;
let runId = 0;
const safe = value => { report.textContent += `\n${JSON.stringify(value)}`; };

async function run(count) {
  const generation = ++runId;
  lastCount = count;
  controller?.abort();
  controller = new AbortController();
  abortButton.disabled = false;
  retryButton.disabled = true;
  report.textContent = 'Loading synthetic fixture…';
  const response = await fetch(fixtureUrl, { cache: 'no-store' });
  if (!response.ok) throw new Error(`fixture HTTP ${response.status}`);
  const bytes = await response.arrayBuffer();
  const reader = createWaveformReader(controller.signal, null, { onDiagnostic: safe });
  const started = performance.now();
  try {
    for (let index = 1; index <= count; index++) {
      const file = new File([bytes], `synthetic-track-${index}.m4a`, { type: 'audio/mp4', lastModified: 0 });
      const peaks = await reader.read(file, duration, { trackIndex: index });
      if (generation !== runId) return;
      safe({ result: 'track-pass', trackIndex: index, peaks: peaks.length,
        elapsedMs: Math.round(performance.now() - started), sourceBytes: file.size });
    }
    safe({ result: 'PASS', tracks: count, archiveMutations: 0 });
  } catch (error) {
    safe({ result: error?.name === 'AbortError' ? 'ABORTED' : 'FAIL', diagnostic: error?.waveformDiagnostic || null });
  } finally {
    reader.dispose();
    abortButton.disabled = true;
    retryButton.disabled = false;
  }
}

document.getElementById('run-one').addEventListener('click', () => run(1));
document.getElementById('run-three').addEventListener('click', () => run(3));
abortButton.addEventListener('click', () => controller?.abort());
retryButton.addEventListener('click', () => run(lastCount));
window.__s10aMobileWaveformHarness = { run };
