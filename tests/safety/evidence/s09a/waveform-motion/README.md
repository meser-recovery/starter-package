# Stable waveform playback and smooth Follow

Receiving Mac regression for waveform changes during playback and jerky scrolling.
Baseline: `cd051fd7067fa80f32317a7609e5f6a8e091fbbf`. These captures and logs use
the implementation in this commit. Final tested HEAD, complete post-commit local
browser output and exact-HEAD CI status are recorded in draft PR #36.

## Reproduction

[Before](before.json): a real two-second Speaker playback interval had 121 RAF
frames but only **8 scroll updates**, with a maximum **268.5 ms** gap. Baseline
modules were read with `git show cd051fd:scripts/...` and served only to an
isolated Playwright page. The working tree and user preview were not reset.
[After](after.json): **121 updates / 121 frames**, maximum **18.6 ms** gap. Both
measurements wait for actual native playback to advance before collecting data.

The renderer regrouped peaks from the current viewport edge, so scrolling
changed the bars assigned to the same source interval. Bars now use absolute
source pixel coordinates and a device-pixel-aligned canvas. A stationary view
reuses its bitmap; unchanged dimensions no longer reset the canvas each frame.

Detail decoding also used to restart its debounce on every scroll and replace
usable detail with an overview at 8-second cache boundaries. It now keeps the
covering window, prefetches before its end, and does not overwrite ready detail.
All detailed windows, including short final windows, use the same 0.5 ms bin
spacing. Decoder failures retain covering detail with retry backoff. Source and
result Speaker playheads use RAF, and synchronized scroll events no longer drop
frames behind a one-frame lock. Source files, playback clock and DSP are unchanged.

## Receiving validation

- [31 transport / waveform / detail tests](units.log): PASS. New cases cover
  absolute grid stability at DPR 1/2 and three scales, fractional panning,
  stationary/theme repaint, non-starved continuous Follow, prefetch and failures.
- [Focused motion browser test](browser-focused.log), [measurements](measurements.json): PASS.
  Two real 73.3-second WAVs; both editors; Fit, 80, 300 and ~1000 px/s; DPR 2.
  The detailed scenario runs at 4x through several decoded windows and the final
  short window. No loading/overview fallback, synchronization loss or movement
  after pause. Native playback advances; no media clock or decoder mocks.
- Seven pixel rows form a signature for every visible source column. Compare
  signatures in overlapping source coordinates between frames (excluding six
  boundary pixels). **Zero changed signatures** at all tested scales, including
  cache replacements. Log comparison counts are source-column signatures, not
  full-frame pixel comparisons. Static PNG overview retains its identity/size.
- Local measured RAF rate is ~60 Hz; moving scroll and playhead updates follow
  >99% of available frames in the long scenarios. CI asserts >75% and checks
  long update gaps relative to the observed frame cadence; this is not a promise
  of a fixed physical display refresh rate on every device.
- Actual rendered Speaker result: 91/91 playhead updates over 1.5 seconds, with
  an unchanged waveform bitmap. Source/result playback remains exclusive.
- [Prior zoom/onset regression](alignment.log): PASS, real decoder, native audio
  and pixels; 41.3/129.37-second sources, right-only/anti-phase peaks and tails.
- [Gateway check](gateway-check.log), [80 gateway tests](gateway.log): PASS.
- The motion browser regression is included in full local-safety.

Four full-page PNGs are original browser captures (no image edits), checked for
readable waveform/controls and synchronized tracks. They document the layout;
the frame measurements establish motion behavior. Preview stays running at
http://127.0.0.1:55153/Audio-Editor.html. Existing user pages were not reloaded.
Physical listening, real user files and other browser engines are not claimed.
No merge, production mutations or Closure Record.

## PNG SHA-256

- [speaker-airy.png](speaker-airy.png): `83efc85aff768403c9308d25498a607f1b15fde055759d2e190158f94845bb3f`
- [speaker-detail.png](speaker-detail.png): `151b1ce0944c4cefc54037dff502927800bf70cfeb2e98efdf3c242e2352afed`
- [announcement-airy.png](announcement-airy.png): `9a81240fe5e25e30674c31fe71d454c19248b4cfdc6d4cb912d79f0ad7786580`
- [announcement-detail.png](announcement-detail.png): `2bcd537193b3b6e6e7a2bd1a26d0e5aca49f3567f52a94103d45ddc8b75690a5`
