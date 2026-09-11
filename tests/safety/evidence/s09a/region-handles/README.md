# Region handles — local package evidence

These 12 PNGs/logs are supplied-package evidence for commit
`22e879bcb208d037ae3ea5cfb22fd23ebcb5912a`. They are preserved separately from
[current Mac evidence](mac/README.md), not attributed to the current checkout.

See [scope and validation](../../../S09A-region-handles.md).
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
