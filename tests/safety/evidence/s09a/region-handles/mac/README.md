# Region handles: current Mac evidence

Implementation/regression and capture source:
`4a2315224bdf945180587a4e6571cbbcb09b841a`.
Evidence is committed separately; PR #36 records the exact submitted HEAD and
its local-safety result without another commit changing that verified HEAD.

[Reconciliation and coverage](../../../../S09A-region-validation.md) ·
[Original PNG sizes and SHA-256](MANIFEST.md).
The supplied package's 12 PNGs/logs retain their original attribution one level
above this directory; earlier word/timeline captures are historical too.

## Checks

- [Site contract, JS/Python syntax, strict HTML nesting and whitespace](static.log): PASS.
- [Transport/waveform/detail units](unit.log): 18/18 PASS.
- [Gateway syntax](gateway-check.log), [gateway tests](gateway.log): 80/80 PASS.
- [Complete post-commit local browser smoke](browser-full.log): PASS. Command:
  `venv/bin/python -u -B tests/safety/browser_smoke.py --base-url http://127.0.0.1:8000 --screenshot-dir /private/tmp/s09a-region-final-v3`.
- Corrective fixture DPR 1 and 2: both editors, four widths, synthetic hour-long
  M4As, native failure/bundled WASM fallback, preparation/retry and word detail.
- Region creation and contextual restoration by ID/type, coincident cut/silence,
  numeric reset, live edges and flags, canonical payload unchanged during drag,
  exactly one Undo step, same-kind collision/inversion rejection, 10ms/1s keys,
  focus, Esc/pointercancel/lost capture and source replacement/late pointerup.
- Actual touch edge drags are separate from ordinary touch waveform selection.
- Native bounded playback reaches End and pauses all tracks; Stop/replay use
  Start. Actual loop repeats inside the intersection and an empty range disables
  it. Existing editor/result isolation, mute/solo/include and DSP checks remain.
- [Native media tone/RMS measurements](signal.json): 20 cases PASS.
- Full suite also retains exact File/Blob/session/epoch/abort protections,
  deletion during preparation, canonical revision, save/reopen/reconnect,
  menus, real mixing/silence/duration/cancel/cleanup, and root/subpath CORS.

The first discovery run's touch coordinate hit a new nearby handle; the old
keyboard regression also still expected 100ms. Both failures are documented in
the validation report. Corrected tests preserve payload equality, exact numeric
steps and all previous media/geometry tolerances. Edge drags center their
handles and assert actual hit targets, including after an error expands the
sticky precision panel. No failed run is counted as a
pass. The new full log above was generated after committing the corrections.

## Captures and preview

[Current DPR 1](s09a-corrective) and [current DPR 2](s09a-corrective-dpr2) show live
cut/silence and recording-flag geometry, contextual toolbar, both editor layouts,
word-scale selection and region handles. Visual inspection covers those states
and compact controls at representative desktop/mobile sizes. Live-region and
toolbar PNGs come from a [supplementary capture run](capture-controls.log) of the
same region helper using short real WAV fixtures at DPR 1/2. It captures from
the document origin to avoid Chromium fixed-position artifacts in tall element
screenshots; application bytes and assertions are unchanged. Hour-long/detail
captures and the complete smoke log come from the full run. PNGs are original
captures, not resized QA composites.

The existing `python3 scripts/preview-audio-editor.py` remains running at
**http://127.0.0.1:55153/Audio-Editor.html**. [Exact HTTP bytes](preview.log) match
this checkout. A separate headed browser opened the actual editor; existing
user pages were not reloaded. Refresh manually after saving work. AGENTS.md's
permanent preview rule remains in force.

Synthetic media and Chromium DPR emulation are not real user Zoom files,
physical listening, Safari/Firefox or user Acceptance. Source playback obeys
recording flags; interior cuts/silence/DSP require the existing rendered result.
PR remains draft. No merge, production mutation or Closure Record.
