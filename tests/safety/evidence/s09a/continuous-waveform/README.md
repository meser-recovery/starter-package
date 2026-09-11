# S09A — Continuous waveform correction (review evidence)

Base: `07e4e66ec1ae4058f822b35d4092e324dc443a36`, PR #36.
This record is implementation/review evidence, not acceptance or closure.

## Change

- Ordinary connected, filled peak envelope in both editors and their rendered results.
- Shared peak reader replaces the Announcement PNG overview; identical amplitude convention, colours from the same theme, no spaced-bar/word-zoom style threshold.
- Source-anchored, fixed 128-device-pixel raster tiles prevent contour edge rasterization from changing with viewport length. A bounded 192-CSS-pixel guard retains the bitmap during Follow; memory does not scale with the full zoomed timeline.
- Detail decoding, source clock, stale-result protections and bounded prefetch remain in place.
- Announcement recalculates zoom bounds when its visible slider is used; Speaker shares the 1000 px/s maximum.
- No DSP recipe, source bytes, monitoring, cuts, silence, bounds, archive protocol or production changes.

## Evidence and limits

`comparison.json`: real canvas contours for the same synthetic WAV in both editors at requested 80/159/160/300/1000 px/s. UI slider steps may round intermediate scales. Normalized contours differ by less than .035 (amplitude); fixed-tile overlap bytes are identical at DPR 1/1.1/1.25/1.5/2/3.

`speaker.png`, `announcement.png`: actual light-theme browser screenshots during playback of synthetic, amplitude-modulated tones. They are not mockups or user Zoom recordings. The accompanying external 15-second preview video shows Speaker followed by Announcement; it is a screen recording without an audio track.

The motion regression compares the *visible* source-aligned pixels, excluding offscreen guard pixels that can legitimately await a detail window. It verifies actual audio progress, frame/scroll updates, synchronized tracks, no overview fallback during prefetch, and no movement after pause. This is stronger than counting requestAnimationFrame callbacks alone.

Local environment: Chromium in Linux with software rendering, DPR 1 and 2 for editor interaction; bundled WASM and native decoding. No physical listening or real user Zoom-file testing is claimed. The user's Mac preview and remote PR are not changed by this local checkout. Receiving Codex must run the full browser suite and CI on the applied branch, keep PR #36 draft, and update the existing Mac preview without refreshing unsaved work.

## Validation

- Site contract and JavaScript syntax: PASS.
- Transport/waveform unit suite: 31/31 PASS.
- Gateway syntax/check and regression suite: 80/80 PASS.
- Full browser entry point was attempted; S09 archive/CORS, source-project acceptance, corrective DPR 1/2 and Design A scenarios passed. It stopped on an obsolete zoom assertion after the new shared maximum. That assertion was corrected, and the affected alignment fixture was rerun successfully. A single uninterrupted full-browser run or remote CI PASS is **not** claimed here.
- Follow-up browser validation covers actual processor output/download, intentional source/result waveform failures, exact-byte passthrough, worker cancel/retry/FS cleanup, multi-track mixes, duration protection, long-source Follow, both-editor timeline DPR 1/2, meters and independent audio signal. See `browser.txt`.
- Final waveform motion measurements are in `motion.json`; same-source editor comparisons and fractional-DPR tile overlap checks are in `comparison.json`.

Before merge, receiving Codex must rerun the full required suite and final-HEAD CI in the existing draft PR. The user reviews the updated working preview; no closure is implied.
