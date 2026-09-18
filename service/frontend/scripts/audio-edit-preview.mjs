// Source-time edit decisions for native, synchronised media playback.
export function mergeMutedRegions(regions, duration = Infinity) {
  const result = [];
  for (const r of regions.filter(r => Number.isFinite(r.startSeconds) && Number.isFinite(r.endSeconds))
    .map(r => ({startSeconds: Math.max(0, r.startSeconds), endSeconds: Math.min(duration, r.endSeconds)}))
    .filter(r => r.endSeconds > r.startSeconds).sort((a,b) => a.startSeconds-b.startSeconds)) {
    const last = result.at(-1);
    if (last && r.startSeconds <= last.endSeconds) last.endSeconds = Math.max(last.endSeconds, r.endSeconds);
    else result.push({...r});
  }
  return result;
}
export function nextAudibleTime(time, cuts, end = Infinity) {
  let next = time;
  // The canonical collection need not be sorted; coalescing also handles overlap.
  for (const cut of mergeMutedRegions(cuts, end)) {
    if (next >= cut.startSeconds && next < cut.endSeconds) next = cut.endSeconds;
  }
  return Math.min(next, end);
}
export function editEnvelope(time, regions, horizon = 2) {
  const end = time+horizon, events = [];
  let value = 1;
  for (const r of regions) {
    if (r.endSeconds <= time || r.startSeconds >= end) continue;
    if (r.startSeconds <= time) value = 0;
    else events.push({after: r.startSeconds-time, value: 0});
    if (r.endSeconds < end) events.push({after:r.endSeconds-time,value:1});
  }
  return {value, events};
}
// AudioParam automation applies silence to the actual audible signal, before
// metering. It never changes media.muted (the user's Solo/Mute state).
export function createEditGate(audio, context, gain) {
  let regions = [], timer = null;
  function schedule() {
    clearTimeout(timer); timer = null;
    const now = context.currentTime;
    gain.cancelScheduledValues(now);
    const rate = audio.playbackRate || 1;
    const envelope = editEnvelope(audio.currentTime || 0, regions, 2*rate);
    gain.setValueAtTime(envelope.value, now);
    if (!audio.paused && !audio.ended && !audio.seeking) {
      for (const event of envelope.events) gain.setValueAtTime(event.value, now+event.after/rate);
      timer = setTimeout(schedule, 250);
    }
  }
  for (const event of ['play','playing','pause','seeking','seeked','ratechange','ended','emptied']) audio.addEventListener(event,schedule);
  return {set(regionsToMute) { regions=mergeMutedRegions(regionsToMute); schedule(); },
    clear() { regions=[]; clearTimeout(timer); timer=null; gain.cancelScheduledValues(context.currentTime); gain.setValueAtTime(1,context.currentTime); }};
}
