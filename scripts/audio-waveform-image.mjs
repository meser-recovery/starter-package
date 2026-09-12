// showwavespic puts the division remainder in its LAST column. Feeding an
// exact multiple of the image width makes every column the same source-time
// interval. Keep the padded duration for drawing; never stretch it to the file.
export function waveformImageSpec(duration, width, height, color = 'white') {
  if (!(duration > 0) || !Number.isFinite(duration)) throw new Error('Invalid waveform duration');
  const rate = 48000;
  const perColumn = Math.max(1, Math.ceil(duration * rate / width));
  const count = perColumn * width;
  return {
    sampleRate: rate / perColumn,
    duration: count / rate,
    // Overlay channel peaks, preserving right-only and anti-phase signals.
    // Explicit linear peaks match native analysis at every zoom level.
    filter: `aresample=${rate},apad=whole_len=${count},atrim=end_sample=${count},showwavespic=s=${width}x${height}:colors=${color}:scale=lin:filter=peak:draw=full`
  };
}
