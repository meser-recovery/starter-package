# S09A meters: receiving Mac validation

Implementation/regression and full smoke source:
`83e9efe1ce4e6eeadf776385ade4ffc98e2dad4c`.
The final evidence-only commit and its exact-HEAD local-safety result are recorded
in draft PR #36 without adding another commit after that verification.

## Patch reconciliation

The checkout and remote draft PR were clean at the supplied base
`7680424624a231191e228e71190a8b1dbf7c9af0` on
`codex/s09a-editor-corrective-ux`. Extracted the text between the standalone
BEGIN PATCH / END PATCH lines with UTF-8/LF. SHA-256 matched
`3f80d6ba87ad06123c8ac6d226cc4177724118960f2d9c765e31522793ee9ed4`.
`git apply --check` passed; the meter module was absent from branch history.
Applied once as `27d5fc7bad7b072b038b0768d2631ec2ccbb8867`, whose stable patch-id
matches `6b448e10b3d63657d6b46b988b5359cb9608bd7d`.
No reset, force push or repetition of previous packages.

The supplied [author's README](../README.md) describes a different environment.
Its two PNGs and logs were not in the TXT. All evidence in this directory was
regenerated on this Mac; earlier region/word/timeline evidence remains historical.

## Actual checks

- [Site contract, changed JS/Python syntax, HTML nesting and whitespace](static.log): PASS.
- [Workflow transport/waveform/detail command](units.log): 21/21 PASS.
- [Gateway check](gateway-check.log) and [gateway tests](gateway.log): 80/80 PASS;
  gateway source unchanged.
- [Complete post-commit browser smoke](browser-full.log): PASS, including both
  corrective DPR 1/2 fixtures, synthetic hour-long M4As, native failure/bundled WASM
  fallback, preparation/retry, four widths, word detail, live region edges/flags,
  mouse/touch, Escape/pointer cancellation, bounded source playback and Loop.
  Command: `venv/bin/python -u -B tests/safety/browser_smoke.py --base-url http://127.0.0.1:8000 --screenshot-dir /private/tmp/s09a-meters-full-final`.
- New native meter fixture: stereo anti-phase L/R do not cancel; each .8 source
  peaks near -1.9 dBFS and their overlapping master sum near +4.1 dBFS; CLIP
  latches, Stop clears RMS/peak while preserving CLIP, explicit reset clears it.
  Per-track mute and four-width toolbar geometry assertions pass.
- [20 native tone/RMS measurements](signal.json): Solo/Mute, native volume,
  stable-ID reordering, render exclusion and source/result isolation in both
  editors. Result master measures the result while source meters are silent.
  Observer analysers add no audible route; the application owns the unity route.
- Full suite also covers exact Files/Blobs, replacing sources, editor switching,
  saved montage/reopen/reconnect, menus and archive deletion races, real DSP/mix,
  cancellation/resource cleanup, root/subpath CORS, and unsupported-browser UI.

## Regression found and fixed

The first complete local smoke with screenshots failed when its old mouse
selection gesture landed on the sticky “Точное редактирование” summary and
closed the fields. [Diagnostic hit target](diagnostic.log) records that exact
summary. Without screenshots the same old point could land on the master meter,
and the old non-empty selection assertion could pass using stale values.

`83e9efe` centers the waveform before the gesture, checks that the real hit
target belongs to it and is not an edge, verifies both resulting source times
within 2 microseconds, and verifies unchanged payload/Files/epoch plus visible
precision fields. The focused save/reconnect scenario passed with screenshots,
then the complete suite was rerun after committing. It also adds an explicit
Stop-preserves-CLIP regression. No application workaround or weaker tolerance.
The failed discovery log is [retained separately](discovery-failed.log), not
counted as a pass. The original patch's CI passed without screenshots; that alone
did not validate the screenshot-dependent gesture.

## Captures and preview

[PNG dimensions and SHA-256](MANIFEST.md) index original captures, not resized
composites. The meters folder comes from a [supplementary run](capture.log) of
the same native meter fixture on the source SHA above. Screenshot-only wrappers
blur focus and capture from document origin, restoring scroll afterward, to
avoid Chromium fixed-position artifacts in tall element screenshots; application
bytes and test assertions remain unchanged. Corrective captures come from the
complete smoke. Representative desktop/mobile layouts, thin region lines,
fixed contextual tool slots and running L/R/master meters were visually inspected.

Existing preview: **http://127.0.0.1:55153/Audio-Editor.html**.
The repository's `python3 scripts/preview-audio-editor.py` remains running with
WASM/CORS support. [HTTP byte verification](preview.log) matches this source.
A separate headed Chromium window opened the actual editor. User pages were not
reloaded; refresh manually after saving work. The final evidence HEAD is checked
again over HTTP and reported in PR #36. AGENTS.md's permanent preview rule remains.

Synthetic media and Chromium DPR emulation are not physical listening, real user
Zoom files, Safari/Firefox or user Acceptance. Readings are RMS/sample peak,
not true peak or calibrated analogue VU. Source meters monitor source playback;
interior cuts/silence/DSP are reflected in the rendered result under the existing
model. No dependencies, backend/API/schema changes, merge, production mutations,
deployment or Closure Record.
