import test from 'node:test';
import assert from 'node:assert/strict';
import { createWaveformReader } from '../../service/frontend/scripts/speaker-waveform.mjs';

test('waveform read aborts its pending FileReader before page teardown', async () => {
  const original = globalThis.FileReader;
  let started;
  const reading = new Promise(resolve => { started = resolve; });
  let aborts = 0;
  let fallbackReads = 0;
  class PendingFileReader extends EventTarget {
    static LOADING = 1;
    readyState = 0;
    readAsArrayBuffer() { this.readyState = PendingFileReader.LOADING; started(); }
    abort() {
      aborts += 1;
      this.readyState = 2;
      this.dispatchEvent(new Event('abort'));
    }
  }
  globalThis.FileReader = PendingFileReader;
  const controller = new AbortController();
  const engine = { async load() {}, terminate() {} };
  const reader = createWaveformReader(controller.signal, null, {
    createEngine: async () => engine, onDiagnostic() {}
  });
  try {
    const pending = reader.read({ size: 2, async arrayBuffer() { fallbackReads += 1; return new ArrayBuffer(2); } }, 121);
    await reading;
    controller.abort();
    await assert.rejects(pending, error => error.name === 'AbortError' && error.waveformDiagnostic.stage === 'aborted');
    assert.equal(aborts, 1);
    assert.equal(fallbackReads, 0);
  } finally {
    reader.dispose();
    globalThis.FileReader = original;
  }
});
