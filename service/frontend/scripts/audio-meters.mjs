import { createEditGate } from "./audio-edit-preview.mjs";
// Native media remains the playback clock and owns volume/mute. A single unity
// connection carries sound; separate, unconnected-to-output taps only measure it.
let context;
const mediaTaps = new WeakMap();
const mediaRegions = new WeakMap();
export function setPlaybackRegions(audio, regions) {
  if (!audio) return;
  mediaRegions.set(audio, regions);
  mediaTaps.get(audio)?.edits.set(regions);
}
export function getPlaybackTap(audio) {
  if (!context) {
    const AudioContext = globalThis.AudioContext || globalThis.webkitAudioContext;
    if (!AudioContext) throw new Error('Web Audio unavailable');
    context = new AudioContext();
  }
  let tap = mediaTaps.get(audio);
  if (!tap) {
    const input = context.createMediaElementSource(audio), source = context.createGain();
    input.connect(source);
    const edits = createEditGate(audio, context, source.gain); edits.set(mediaRegions.get(audio) || []);
    tap = { context, source, input, edits, connected: false }; mediaTaps.set(audio, tap);
  }
  if (!tap.connected) { tap.source.connect(context.destination); tap.connected = true; }
  return tap;
}
export function signalLevel(samples) {
  let squares = 0, peak = 0;
  for (const sample of samples) { squares += sample * sample; peak = Math.max(peak, Math.abs(sample)); }
  return { power: samples.length ? squares / samples.length : 0, peak };
}
export const toDecibels = amplitude => amplitude > 0 ? 20 * Math.log10(amplitude) : -Infinity;
function stereoTap(ctx, source) {
  // Split before analysing: mono downmix would hide opposite-phase stereo peaks.
  const splitter = ctx.createChannelSplitter(2);
  // Explicit stereo upmix duplicates a mono recording into L/R like playback.
  const stereo = ctx.createGain(); stereo.channelCount = 2; stereo.channelCountMode = 'explicit';
  source.connect(stereo); stereo.connect(splitter);
  const channels = [0, 1].map(channel => {
    const analyser = ctx.createAnalyser(); analyser.fftSize = 2048; analyser.smoothingTimeConstant = 0;
    splitter.connect(analyser, channel); return { analyser, samples: new Float32Array(analyser.fftSize) };
  });
  return { read: () => channels.map(({ analyser, samples }) => { analyser.getFloatTimeDomainData(samples); return signalLevel(samples); }),
    dispose: () => { source.disconnect(stereo); stereo.disconnect(); splitter.disconnect(); channels.forEach(c => c.analyser.disconnect()); } };
}
function meterView(label, master = false) {
  const node = document.createElement('div'); node.className = `audio-meter${master ? ' audio-meter--master' : ''}`;
  node.setAttribute('role', 'group'); node.setAttribute('aria-label', label);
  node.title = 'Уровень прослушивания: RMS и sample peak, dBFS. CLIP фиксирует достижение 0 dBFS. Это не измерение true peak.';
  const heading = document.createElement('div'); heading.className = 'audio-meter__heading';
  const name = document.createElement('span'); name.textContent = label;
  const clip = document.createElement('button'); clip.type = 'button'; clip.className = 'audio-meter__clip'; clip.textContent = 'CLIP';
  clip.title = 'Сбросить индикатор перегрузки'; clip.setAttribute('aria-label', `${label}: сбросить перегрузку`); clip.setAttribute('aria-pressed', 'false');
  clip.addEventListener('click', () => { clip.dataset.clipped = 'false'; clip.setAttribute('aria-pressed', 'false'); });
  heading.append(name, clip); node.append(heading);
  const rows = ['L', 'R'].map(channel => {
    const row = document.createElement('div'); row.className = 'audio-meter__channel';
    const letter = document.createElement('span'); letter.textContent = channel;
    const rail = document.createElement('span'); rail.className = 'audio-meter__rail'; rail.setAttribute('aria-hidden', 'true');
    const mask = document.createElement('span'); mask.className = 'audio-meter__mask';
    const peak = document.createElement('span'); peak.className = 'audio-meter__peak'; rail.append(mask, peak);
    row.append(letter, rail); node.append(row); return { mask, peak, power: 0, hold: 0, holdUntil: 0 };
  });
  const numbers = document.createElement('output'); numbers.className = 'audio-meter__numbers'; numbers.setAttribute('aria-live', 'off'); node.append(numbers);
  const percent = value => Math.max(0, Math.min(100, (toDecibels(value) + 60) / 60 * 100));
  const format = value => value < .001 ? '−∞' : toDecibels(value).toFixed(1);
  function paint(levels, now, dt, running) {
    let rms = 0, held = 0;
    rows.forEach((row, i) => {
      const level = levels?.[i] || { power: 0, peak: 0 };
      row.power = running ? row.power + (level.power - row.power) * (1 - Math.exp(-dt / 300)) : 0;
      if (!running) { row.hold = 0; row.holdUntil = 0; }
      else if (level.peak >= row.hold) { row.hold = level.peak; row.holdUntil = now + 1500; }
      else if (now > row.holdUntil) row.hold = Math.max(level.peak, row.hold * Math.exp(-dt / 700));
      row.mask.style.width = `${100 - percent(Math.sqrt(row.power))}%`;
      row.peak.style.left = `${percent(row.hold)}%`; row.peak.hidden = !row.hold;
      if (level.peak >= 1) { clip.dataset.clipped = 'true'; clip.setAttribute('aria-pressed', 'true'); }
      rms = Math.max(rms, Math.sqrt(row.power)); held = Math.max(held, row.hold);
    });
    node.dataset.rmsDb = String(toDecibels(rms)); node.dataset.peakDb = String(toDecibels(held));
    numbers.textContent = `RMS ${format(rms)} · PK ${format(held)} dBFS`;
  }
  paint(null, 0, 0, false);
  return { node, name, paint, resetClip: () => { clip.dataset.clipped = 'false'; clip.setAttribute('aria-pressed', 'false'); }, unavailable: () => { paint(null, 0, 0, false); numbers.textContent = 'Измерение недоступно'; } };
}
export function createAudioMeters({ root, resultAudio }) {
  const master = meterView('Микс', true);
  const persistentMedia = new Set([resultAudio, root.querySelector('audio.daw-media-clock')]);
  const playback = root.querySelector('.daw-playback');
  const main = document.createElement('div'); main.className = 'studio-transport-main';
  playback.before(main); main.append(playback);
  const clock = root.querySelector('#speaker-editor-source-time, #processor-source-time');
  if (clock) main.append(clock);
  main.append(master.node);
  const scale = document.createElement('div'); scale.className = 'audio-meter__scale'; scale.setAttribute('aria-hidden', 'true');
  for (const value of ['−60', '−36', '−24', '−12', '0 dBFS']) { const label = document.createElement('span'); label.textContent = value; scale.append(label); }
  master.node.append(scale);
  let entries = new Map(), bus, masterTap, frame = null, last = 0;
  const playing = audio => Boolean(audio?.src && !audio.paused && !audio.ended);
  function disconnect(entry) {
    entry.analysis?.dispose();
    if (entry.input && bus) entry.input.source.disconnect(bus);
    // Persistent clocks may still play a retained result while source rows rebuild.
    if (entry.input?.connected && !persistentMedia.has(entry.audio)) { entry.input.source.disconnect(entry.input.context.destination); entry.input.connected = false; }
  }
  function connect(entry) {
    if (entry.input || entry.failed || !entry.audio) return;
    try {
      entry.input = getPlaybackTap(entry.audio);
      if (!bus) { bus = entry.input.context.createGain(); masterTap = stereoTap(entry.input.context, bus); }
      entry.input.source.connect(bus); entry.analysis = stereoTap(entry.input.context, entry.input.source);
    } catch { entry.failed = true; entry.view?.unavailable(); master.unavailable(); }
  }
  function tick(now) {
    frame = null;
    const dt = last ? Math.min(100, now - last) : 33;
    if (dt < 30) { frame = requestAnimationFrame(tick); return; }
    last = now;
    let active = false;
    for (const entry of entries.values()) {
      const running = playing(entry.audio) && !entry.audio.muted && entry.audio.volume > 0 && context?.state === 'running'; active ||= playing(entry.audio);
      if (entry.failed) entry.view?.unavailable();
      else entry.view?.paint(running ? entry.analysis?.read() : null, now, dt, running);
    }
    const running = active && context?.state === 'running';
    if ([...entries.values()].some(entry => entry.failed)) master.unavailable();
    else master.paint(running ? masterTap?.read() : null, now, dt, running);
    master.name.textContent = playing(resultAudio) ? 'MASTER · результат' : root.id === 'speaker-editor' ? 'MASTER · монтаж' : 'MASTER · исходники';
    if (active && !document.hidden) frame = requestAnimationFrame(tick); else last = 0;
  }
  function wake() {
    for (const entry of entries.values()) connect(entry);
    if (context?.state === 'suspended' || context?.state === 'interrupted') void context.resume().catch(() => {});
    if (frame === null) { last = 0; frame = requestAnimationFrame(tick); }
  }
  // Capture the gesture before play(), including native result-player controls.
  root.addEventListener('pointerdown', wake, true); root.addEventListener('keydown', wake, true);
  for (const event of ['play', 'pause', 'ended', 'emptied']) root.addEventListener(event, wake, true);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { if (frame !== null) cancelAnimationFrame(frame); frame = null; last = 0; }
    else wake();
  });
  function sync(tracks) {
    const next = new Map();
    for (const track of [...tracks, { id: '$result', audio: resultAudio }]) {
      const old = entries.get(track.id);
      const entry = old && old.audio === track.audio ? old : { audio: track.audio, view: track.id === '$result' ? null : meterView('Уровень дорожки') };
      if (old && entry !== old) disconnect(old);
      next.set(track.id, entry);
      if (entry.view && track.container) { entry.view.node.dataset.trackId = String(track.id); track.container.append(entry.view.node); }
    }
    for (const [id, entry] of entries) if (!next.has(id)) disconnect(entry);
    entries = next;
    if (context) wake();
  }
  function clear() {
    for (const entry of entries.values()) disconnect(entry);
    entries.clear(); masterTap?.dispose(); masterTap = null; bus?.disconnect(); bus = null;
    if (frame !== null) cancelAnimationFrame(frame); frame = null; last = 0;
    master.paint(null, 0, 0, false); master.resetClip();
  }
  // Register the persistent clocks before their first gesture, even with no tracks.
  sync([]);
  return { sync, clear };
}
