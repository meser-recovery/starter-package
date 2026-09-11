# Region handles — local package evidence

See [scope and validation](../../../../S09A-region-handles.md).
`manifest.json` binds application/test bytes and the 12 captured PNGs.
Screenshots are real Chromium views with synthetic two-track WAV audio.
DPR 1 and DPR 2 are emulated; they are not physical device or user acceptance.

- `browser.log`: existing tool/selection checks plus new resize/contextual restore/
  cancellation/high-zoom/flag/playback checks, DPR 1 and DPR 2.
- `corrective.log`: full S09A corrective fixture with actual bundled WASM,
  synthetic hour-long M4As, both editors and four viewport widths, DPR 1.
- `units.log`: 18/18 transport/waveform/detail tests.
- `gateway.log`: 80/80 existing gateway tests.

No remote CI, real user Zoom-file check or physical listening is claimed here.
The Mac preview still needs this package applied by the receiving Codex.
