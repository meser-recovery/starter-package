import test from 'node:test';
import assert from 'node:assert/strict';
import { createAudioTransport } from '../../scripts/audio-transport.mjs';

// DOM/media adapter for transport logic. Browser geometry and real playback are
// covered separately by s09a_selection_tools_smoke.py, not by this adapter.
class Element extends EventTarget {
  constructor(tag, doc) { super(); this.tag = tag; this.ownerDocument = doc; this.children = []; this.attrs = new Map(); this.dataset = {}; this.classList = { add() {} }; }
  setAttribute(key, value) { this.attrs.set(key, String(value)); }
  getAttribute(key) { return this.attrs.get(key) ?? null; }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  closest() { return null; }
  before(node) { this.ownerDocument.bar = node; }
  querySelector(tag) { return this.children.find(node => node.tag === tag) || this.children.map(node => node.querySelector(tag)).find(Boolean) || null; }
}
function fixture(selection = null, bounds = null, cuts = []) {
  const doc = { createElement(tag) { return new Element(tag, this); }, createElementNS(ns, tag) { return this.createElement(tag); } };
  const audio = doc.createElement('audio'); audio.id = 'source-audio'; audio.setAttribute('src', 'blob:one');
  audio.currentTime = 0; audio.paused = true; audio.ended = false; audio.volume = 1; audio.muted = true;
  let plays = 0, enabled = true; const seeks = [], errors = [];
  audio.play = async () => { plays++; audio.paused = false; audio.dispatchEvent(new Event('play')); };
  audio.pause = () => { audio.paused = true; audio.dispatchEvent(new Event('pause')); };
  const resultAudio = doc.createElement('audio'); resultAudio.paused = true;
  resultAudio.pause = () => { resultAudio.paused = true; resultAudio.dispatchEvent(new Event('pause')); };
  resultAudio.play = () => { resultAudio.paused = false; resultAudio.dispatchEvent(new Event('play')); };
  const transport = createAudioTransport({ audio, resultAudio, canPlay: () => enabled, seek: time => { seeks.push(time); audio.currentTime = time; }, getSelection: selection ? () => selection : undefined, getBounds: () => bounds, getCuts: () => cuts, reportError: text => errors.push(text) });
  const [play, stop, volumeLabel] = doc.bar.children;
  return { audio, resultAudio, transport, play, stop, loop: doc.bar.children.find(node => node.id === "source-audio-loop"), setSelection: value => { selection = value; transport.refresh(); }, setBounds: value => { bounds = value; transport.refresh(); }, volume: volumeLabel.querySelector('input'), seeks, errors, plays: () => plays, enable: value => { enabled = value; transport.refresh(); } };
}
const click = async element => { element.dispatchEvent(new Event('click')); await new Promise(resolve => setImmediate(resolve)); };

test('play/pause and stop preserve per-track mute; controls follow media events', async () => {
  const f = fixture();
  assert.equal(f.audio.controls, false);
  assert.equal(f.play.getAttribute('aria-label'), 'Воспроизвести исходники');
  await click(f.play); assert.equal(f.plays(), 1); assert.equal(f.audio.paused, false); assert.equal(f.audio.muted, true);
  assert.equal(f.play.getAttribute('aria-label'), 'Приостановить исходники');
  await click(f.play); assert.equal(f.audio.paused, true); assert.equal(f.audio.muted, true);
  await click(f.play); await click(f.stop); assert.deepEqual(f.seeks, [0]); assert.equal(f.audio.paused, true); assert.equal(f.audio.muted, true);
});
test('unready/locked sources cannot start playback or seek', async () => {
  const f = fixture(); f.enable(false);
  assert(f.play.disabled); assert(f.stop.disabled);
  await click(f.play); await click(f.stop); assert.equal(f.plays(), 0); assert.deepEqual(f.seeks, []);
  f.enable(true); await click(f.play); assert.equal(f.plays(), 1);
});
test('source and result cannot play over each other; track mute remains unchanged', async () => {
  const f = fixture(); await click(f.play); assert.equal(f.audio.paused, false);
  f.resultAudio.play(); assert.equal(f.audio.paused, true); assert.equal(f.resultAudio.paused, false);
  await click(f.play); assert.equal(f.resultAudio.paused, true); assert.equal(f.audio.paused, false); assert.equal(f.audio.muted, true);
});
test('master listening volume does not alter any track mute flag', () => {
  const f = fixture(); f.volume.value = '.35'; f.volume.dispatchEvent(new Event('input'));
  assert.equal(f.audio.volume, .35); assert.equal(f.audio.muted, true);
  f.audio.volume = .8; f.audio.dispatchEvent(new Event('volumechange')); assert.equal(f.volume.value, '0.8');
});
test('failed playback can retry; stale failures cannot overwrite a new source status', async () => {
  const f = fixture(); let reject;
  f.audio.play = () => new Promise((resolve, fail) => { reject = fail; });
  f.play.dispatchEvent(new Event('click')); f.audio.setAttribute('src', 'blob:two'); reject(new Error('aborted'));
  await new Promise(resolve => setImmediate(resolve)); assert.deepEqual(f.errors, []);
  f.audio.play = async () => { throw new Error('blocked'); };
  await click(f.play); assert.equal(f.errors.length, 1); assert.equal(f.audio.muted, true);
  f.audio.play = async () => { f.audio.paused = false; f.audio.dispatchEvent(new Event('play')); };
  await click(f.play); assert.equal(f.play.dataset.playing, 'true'); assert.equal(f.errors.length, 1);
});

test('loop starts at selection and wraps at its right edge without changing mute or volume', async () => {
  const f = fixture({ startSeconds: 2, endSeconds: 3 });
  await click(f.loop); assert.equal(f.audio.currentTime, 2); assert.equal(f.audio.paused, false);
  assert.equal(f.loop.getAttribute('aria-pressed'), 'true');
  f.audio.currentTime = 2.8; f.audio.dispatchEvent(new Event('timeupdate')); assert.deepEqual(f.seeks, [2]);
  f.audio.currentTime = 3.01; f.audio.dispatchEvent(new Event('timeupdate')); assert.deepEqual(f.seeks, [2, 2]);
  assert.equal(f.audio.muted, true); assert.equal(f.audio.volume, 1);
  await click(f.loop); f.audio.currentTime = 3.1; f.audio.dispatchEvent(new Event('timeupdate'));
  assert.deepEqual(f.seeks, [2, 2]); assert.equal(f.audio.paused, false);
});
test('stop pauses loop; clearing selection, locking and replacing media disable it', async () => {
  const f = fixture({ startSeconds: 1, endSeconds: 2 });
  await click(f.loop); await click(f.stop); assert.equal(f.audio.currentTime, 0);
  f.audio.dispatchEvent(new Event('timeupdate')); assert.equal(f.audio.currentTime, 0);
  await click(f.play); assert.equal(f.audio.currentTime, 1);
  f.setSelection(null); assert.equal(f.loop.getAttribute('aria-pressed'), 'false'); assert(f.loop.disabled);
  f.setSelection({ startSeconds: 2, endSeconds: 4 }); await click(f.loop);
  f.enable(false); assert.equal(f.loop.getAttribute('aria-pressed'), 'false');
  f.enable(true); await click(f.loop); f.audio.dispatchEvent(new Event('emptied'));
  assert.equal(f.loop.getAttribute('aria-pressed'), 'false');
});
test('loop handles an end-of-file range and never restarts after result playback takes over', async () => {
  const f = fixture({ startSeconds: 1, endSeconds: 2 }); await click(f.loop);
  f.audio.currentTime = 2; f.audio.paused = true; f.audio.dispatchEvent(new Event('ended'));
  await new Promise(resolve => setImmediate(resolve)); assert.equal(f.audio.currentTime, 1); assert.equal(f.audio.paused, false);
  f.resultAudio.play(); f.audio.currentTime = 2; f.audio.dispatchEvent(new Event('timeupdate'));
  assert.equal(f.audio.paused, true); assert.equal(f.resultAudio.paused, false);
});


test('recording bounds govern play, replay, stop and an external playing seek', async () => {
  const f = fixture(null, { start: 2, end: 5 });
  await click(f.play); assert.equal(f.audio.currentTime, 2);
  f.audio.currentTime = 5.01; f.audio.dispatchEvent(new Event('timeupdate'));
  assert.equal(f.audio.paused, true); assert.equal(f.audio.currentTime, 5);
  await click(f.play); assert.equal(f.audio.currentTime, 2); assert.equal(f.audio.paused, false);
  f.audio.currentTime = 0; f.audio.dispatchEvent(new Event('seeked')); assert.equal(f.audio.currentTime, 2);
  await click(f.stop); assert.equal(f.audio.currentTime, 2); assert.equal(f.audio.paused, true);
});
test('loop intersects recording bounds and disables for an outside selection', async () => {
  const f = fixture({ startSeconds: 1, endSeconds: 8 }, { start: 2, end: 5 });
  await click(f.loop); assert.equal(f.audio.currentTime, 2);
  f.audio.currentTime = 5; f.audio.dispatchEvent(new Event('timeupdate'));
  assert.equal(f.audio.currentTime, 2); assert.equal(f.audio.paused, false);
  f.setSelection({ startSeconds: 6, endSeconds: 8 });
  assert.equal(f.loop.getAttribute('aria-pressed'), 'false'); assert(f.loop.disabled);
  f.audio.currentTime = 5.1; f.audio.dispatchEvent(new Event('timeupdate')); assert.equal(f.audio.paused, true);
});
test('moving bounds during playback takes effect immediately without changing monitor controls', async () => {
  const f = fixture(null, { start: 0, end: 10 }); await click(f.play);
  f.audio.currentTime = 3; f.setBounds({ start: 4, end: 8 }); assert.equal(f.audio.currentTime, 4);
  f.audio.currentTime = 7; f.setBounds({ start: 4, end: 6 });
  assert.equal(f.audio.currentTime, 6); assert.equal(f.audio.paused, true);
  assert.equal(f.audio.muted, true); assert.equal(f.audio.volume, 1);
});

import { signalLevel, toDecibels } from '../../scripts/audio-meters.mjs';

test('digital meters measure silence without NaN', () => {
  assert.deepEqual(signalLevel(new Float32Array(64)), {power: 0, peak: 0});
  assert.equal(toDecibels(0), -Infinity);
  assert.deepEqual(signalLevel([]), {power: 0, peak: 0});
});
test('RMS and peak retain independent meaning and do not clamp clipping', () => {
  const samples = Float32Array.from({length: 4800}, (_, i) => 1.25 * Math.sin(i * Math.PI / 24));
  const {power, peak} = signalLevel(samples);
  assert.ok(Math.abs(power - 1.25 ** 2 / 2) < .000001);
  assert.equal(peak, 1.25);
  assert.ok(toDecibels(peak) > 0);
  assert.ok(Math.abs(toDecibels(peak) - toDecibels(Math.sqrt(power)) - 3.0103) < .0001);
});
test('both polarities contribute equally to level', () => {
  assert.deepEqual(signalLevel([-.5,.5,-.5,.5]), {power:.25,peak:.5});
  assert.ok(Math.abs(toDecibels(.5) + 6.0206) < .0001);
});


test('cuts skip their union, preserve monitoring, and stop at recording end', async () => {
  const f = fixture(null, {start:1,end:9}, [{startSeconds:2,endSeconds:4},{startSeconds:3,endSeconds:5},{startSeconds:8,endSeconds:9}]);
  await click(f.play); assert.equal(f.audio.currentTime,1);
  f.audio.currentTime=2.01; f.audio.dispatchEvent(new Event('timeupdate'));
  assert.equal(f.audio.currentTime,5); assert.equal(f.audio.muted,true);
  f.audio.currentTime=8.01; f.audio.dispatchEvent(new Event('timeupdate'));
  assert.equal(f.audio.currentTime,9); assert.equal(f.audio.paused,true);
});
test('loop skips cuts including its start and rejects a fully cut selection', async () => {
  const f=fixture({startSeconds:2,endSeconds:7},{start:0,end:9},[{startSeconds:2,endSeconds:4},{startSeconds:6,endSeconds:7}]);
  await click(f.loop); assert.equal(f.audio.currentTime,4);
  f.audio.currentTime=6.1; f.audio.dispatchEvent(new Event('timeupdate')); assert.equal(f.audio.currentTime,4);
  f.setSelection({startSeconds:2,endSeconds:3}); assert.equal(f.loop.disabled,true);
  await click(f.stop);
});
import { mergeMutedRegions, editEnvelope, createEditGate } from '../../scripts/audio-edit-preview.mjs';
test('edit envelope handles overlapping cut/silence and partial restoration', () => {
  const regions=mergeMutedRegions([{startSeconds:1,endSeconds:3},{startSeconds:2,endSeconds:4},{startSeconds:5,endSeconds:6}]);
  assert.deepEqual(regions,[{startSeconds:1,endSeconds:4},{startSeconds:5,endSeconds:6}]);
  assert.deepEqual(editEnvelope(3,regions,4),{value:0,events:[{after:1,value:1},{after:2,value:0},{after:3,value:1}]});
  assert.deepEqual(editEnvelope(4,regions,3),{value:1,events:[{after:1,value:0},{after:2,value:1}]});
});
test('edit gate reanchors on seek and restores unity without modifying mute', () => {
  const audio=new EventTarget();Object.assign(audio,{currentTime:3,paused:true,muted:true,playbackRate:1});
  const calls=[];const gain={cancelScheduledValues(){},setValueAtTime(value,time){calls.push([value,time]);}};
  const gate=createEditGate(audio,{currentTime:10},gain);
  gate.set([{startSeconds:2,endSeconds:5}]);assert.deepEqual(calls.at(-1),[0,10]);
  audio.currentTime=6;audio.dispatchEvent(new Event('seeked'));assert.deepEqual(calls.at(-1),[1,10]);
  gate.clear();assert.equal(audio.muted,true);assert.deepEqual(calls.at(-1),[1,10]);
});
