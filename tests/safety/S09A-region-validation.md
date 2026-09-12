# PR #36 region handles: Mac validation

Continues `codex/s09a-editor-corrective-ux`; PR remains draft. User visual/listening
acceptance remains open. No merge, production mutation or Closure Record.

## Reconciliation

Local checkout and remote PR were clean at package base
`4d3bd133a1e8e3d482c3b515109c1b826546d528`. All three SHA-256 checks passed.
Stable patch-id `30878bd3a654a60502b3c539c783cf5c23f2749c` was absent from branch
history. Applied package `22e879bcb208d037ae3ea5cfb22fd23ebcb5912a` once with
`git am --3way` as `192f3e9526971a164adee21d7a7c09cbb712521e`, without conflicts,
reset, force push or duplication of previous packages.

## Coverage

The package's corrective fixture is part of the full smoke at DPR 1 and 2.
It checks contextual restoration, live cut/silence edges, live recording flags,
one-step Undo/Redo, source-time resizing at >=1000px/s, native bounded playback,
Stop/replay, hour-long M4As, fallback/retry and four widths (320–1280).

Additional browser regressions verify:

- Coincident cut and silence remain distinct; restoration removes only the
  selected ID/type. A new numeric selection restores the ordinary toolbar mode.
- Same-kind/same-track collisions and inverted boundaries reject the move while
  keeping both region IDs, displayed geometry and the saved payload.
- Native touch input intentionally resizes both kinds of region; pointermove
  preserves the payload and pointerup creates one undoable change.
- Escape, pointercancel and actual release of pointer capture roll back a drag.
  Keyboard edges move exactly 10ms or 1s with Shift and retain focus.
- Replacing prepared source state during an edge drag cancels it. A late
  pointerup on the detached handle cannot mutate the new state; exact Files stay
  identical and source epoch advances.
- Actual Loop repeats an oversized selection clipped to the recording bounds;
  an empty intersection disables it. Native Start/End stop/replay checks remain.

The first full discovery run found an old touch-selection point only a few
pixels beyond the new Start-cut edge. Chromium touch hit testing selected the
nearby handle and resized the cut, so the unchanged-payload check correctly
failed. The plain-selection target now stays clear of handles; payload equality
is checked before and immediately after the gesture, and intentional touch
resizing has its own regression. No geometry or audio tolerance was relaxed.

The old timeline fixture expected 100ms flag keyboard steps and failed against
the package's new 10ms contract. It now asserts exactly 10ms and 1s with Shift,
retaining the numeric tolerance and adding boundary region-ID preservation.
Live recording-flag gestures also explicitly verify one-step Undo/Redo.
Supplementary WAV capture found that the expanded sticky precision/error panel
could cover an edge despite Playwright considering it in view. Edge gestures
now center the handle and assert the actual hit target before mouse/touch input;
collision tests therefore cannot pass by accidentally dragging the error panel.

Site contract, JS/Python syntax, strict HTML nesting, 18 transport/waveform/detail
units, gateway syntax and 80 gateway tests are required alongside the complete
site-wide browser smoke. [Mac evidence](evidence/s09a/region-handles/mac/README.md)
records actual source SHAs, logs and original PNG hashes. Final-head local-safety
is recorded in PR #36 without another commit changing that verified HEAD.

## Preview and limits

The existing `python3 scripts/preview-audio-editor.py` server remains at
**http://127.0.0.1:55153/Audio-Editor.html**. HTTP byte checks cover actual HTML,
CSS and modules. A separate headed browser opens the actual editor; existing
user pages are never reloaded automatically. Refresh manually after saving work.

The source-time model, File/Blob identity, prior epoch/abort/reconnect protections,
Solo/Mute/Include, DSP/render algorithms, stored schema and archive protocols are
preserved. Source playback obeys recording flags; interior cuts/silence/DSP still
require the rendered result. Tests use synthetic audio and Chromium DPR emulation;
real user Zoom files, physical listening and Safari/Firefox are not claimed.
