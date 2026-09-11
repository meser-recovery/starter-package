# S09A — word-scale zoom and tool-first edits

Base: `80c1ef5c83fd6317f11ca3ecd539a03f82d8d101` (draft PR #36).
This is a new implementation delta, not Acceptance or Closure.

## User-visible behavior

- Speaker zoom no longer stops at 8×. Plus/minus double/halve the scale;
  the range reaches at least 1000 CSS px/s on a long recording. Zoom anchors
  to the selection, playhead or visible center. Announcement source zoom also
  reaches 1000 px/s and its slider uses a logarithmic scale.
- The common ruler shows fractional seconds. Detailed source waveforms are
  decoded on demand in windows of at most 32 seconds, with up to 65,536 bins.
  Only the visible canvas is drawn, with DPR support. Overview remains available
  while detail loads. No whole-hour native PCM is retained.
- Cut/Silence buttons arm exclusive tools even without a selection. Arming
  never changes the recipe. The active tool has aria-pressed and visible color.
- With Cut armed, dragging previews the same source-time interval on every
  track, including excluded tracks, and pointerup commits one global cut.
- With Silence armed, the gesture targets only the track where it started.
  Other tracks and synchronization remain unchanged.
- Ordinary mode retains click-to-seek and drag-to-select/loop. Clicking an
  existing marked region selects it for restoration even with a tool armed.
- Escape during a drag restores the previous selection and cancels the gesture
  and tool. Pointer cancellation commits nothing. Clicking the active tool
  again returns to ordinary mode. Enter on the waveform or exact-time field
  applies the active tool to the current valid selection (keyboard access).
- The order is Start, End, Cut, Restore cut, Silence, Restore silence. Existing
  per-region restoration, Undo/Redo, boundaries, DSP, monitoring and archives
  retain their existing semantics. Source loop remains source monitoring,
  not a rendered edit/DSP audition.

## Implementation protections

Source File identity keys the detail cache. A single sequential detail decoder
per editor serves coalesced viewport requests. Abort/generation checks reject
late source results; detached or differently positioned canvases are not painted.
Cached detail is bounded to one window per File and cleared on source release.
Failures preserve the overview and allow retry on later interaction after a
short backoff. Decoder detail never writes a recipe or modifies playback.
The Announcement scroll guard now ignores only synchronized positions; a real
scroll immediately after zoom is processed, including its detailed waveform.
Zero-width hidden viewports cannot create infinite Speaker zoom limits.

## Validation actually performed in this environment

- Site contract: PASS. Its explicit import allowlist includes the new lazy
  detail helper; FFmpeg is still dynamically loaded only for valid audio.
- JavaScript syntax, Python compilation and git whitespace check: PASS.
- Transport/waveform/detail Node tests: 15/15 PASS.
- Gateway syntax check and tests: 80/80 PASS.
- The complete `check_s09a_editor_corrective` browser function: PASS, including
  its pre-existing real bundled WASM generation/decode/render/download,
  retained File/retry scenarios, native decode failure, both editors,
  two 3747-second M4As, four viewport widths, layout limits, monitoring,
  selection/loop, flags/DSP and new tool-first/word-detail checks.
- Separate real-browser DPR2 check: PASS in both editors on two 121-second
  M4A tracks; window decode, viewport canvas size and source seek checked.
- Native FFmpeg reference of the 80–112 second detail window: PASS,
  26,214,400 RGBA bytes, matching the same bounded filter dimensions.
- Seven selected PNGs and logs: `evidence/s09a/word-tools/`.

Browser: locally unpacked Chromium from the temporary @sparticuz/chromium
package, controlled by Playwright. No project runtime dependency was added.
The normal Playwright browser download failed with timeout/502; a runnable
Chromium package was then obtained through npm. Tests used local HTTP servers
and synthetic audio with external archive traffic blocked/stubbed.

During validation: fixed selection scope after changing target track; corrected
an overbroad test selector that included the hidden result canvas; fixed the
Announcement immediate-scroll guard. Final logs are from subsequent successful
runs. Earlier failures are not used as pass evidence.

The complete site-wide `browser_smoke.py` and exact-HEAD GitHub local-safety
have NOT been run for this new delta here. The receiving Codex must run them
before updating the PR evidence and must leave the Mac preview working. No
physical listening, user Zoom-file validation, Safari/Firefox acceptance,
production changes, PR update, merge or Closure is claimed by this package.
