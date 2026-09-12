# PR #36 word-scale editing: current Mac evidence

- Package base: `80c1ef5c83fd6317f11ca3ecd539a03f82d8d101`.
- Implementation and PNG capture source:
  `9e3881c00c866cbf1a3d87302475ab828a92d96e`.
- Complete post-commit browser smoke and current Worker/seek regressions:
  `7c4cd0801e895460a325554a76361143fee856bd`. Application bytes are unchanged
  from the PNG source; only test/evidence files changed.
- Evidence is committed separately. Draft PR #36 records the exact submitted
  HEAD and its final Linux local-safety result without another commit changing
  that verified HEAD.
- [Patch reconciliation, coverage and limits](../../../../S09A-word-edit-validation.md).
- [Original PNG dimensions and SHA-256](MANIFEST.md).

## Checks

- [Site contract, JS/Python syntax, strict HTML nesting, whitespace](static.log): PASS.
- [Transport/waveform/detail units](unit.log): 15/15 PASS.
- [Gateway syntax](gateway-check.log), [gateway tests](gateway.log): 80/80 PASS.
- [Complete post-commit browser smoke](browser-full.log): PASS, default Chromium
  security and isolated local fixtures. Command:
  `venv/bin/python -u -B tests/safety/browser_smoke.py --base-url http://127.0.0.1:8000 --screenshot-dir /private/tmp/s09a-word-final-v4`.
- Full corrective smoke runs at DPR 1 and 2, including four widths, two synthetic
  1:02:27 M4As, forced native decode failure/bundled WASM fallback, exact Files and
  retry, per-track detail after immediate scroll to 80s, <=32-second windows,
  viewport/DPR canvas pixels and seek within 0.02s.
- Tool checks cover arming without an edit, global preview before pointerup on
  all rows including an excluded track, a single commit after pointerup, local
  silence, Escape and both pointercancel paths, ~100ms word cut on an hour-long
  source, exact File preservation and restoration without Undo.
- [Real media signal](s09a-playback/signal.json): 20 tone/RMS cases covering both
  editors, Mute/Solo, volume, reorder, Exclude versus render and source/result
  isolation. Native media clock checks retain loop cycles and mode isolation.
- Existing File/Blob/identity/epoch/abort protections, deletion during preparation,
  canonical revision, 401/403/reconnect, saved payload/reopen/render, keyboard DSP,
  flags, menus, paused Follow, immediate scroll, actual mixes/silence detection,
  duration safeguards, cancellation and root/subpath CORS remain in the full run.

The initial discovery run stopped at an obsolete selector that prohibited a
class now used for per-track detail canvases. It was corrected to keep the old
non-canvas UI prohibited and require both new canvases. That failed run is not
counted as a pass. A later capture-enabled run exposed Follow disengagement on
long sources. Delayed unchanged events and browser rounding reproduced the
problem; synchronization now compares the actual assigned scroll position.
Long playback, fractional seeks and delayed events run unconditionally in CI at
390/768/1280. The deterministic delayed-event test failed on the pre-fix app.
Existing geometry limits and signal tolerances remain intact.

The first evidence-head CI failed an obsolete total-Worker-count assertion.
Maximum zoom may start a debounced display decoder. The smoke now waits for
actual detail, observes native Worker IDs, and checks the same processing
Worker's reuse, exact cancel termination and one live replacement on retry.
The full post-commit run above includes that correction. The failed CI attempt
is preserved in the PR history and is not counted as a pass. A subsequent CI
caught the paused-seek wait accepting old centered geometry before seeking
began. It now requires the requested clock, completed native seek and the new
rendered source position, preserving the 8px/2px geometry limits. The full run
linked above includes both test corrections.

## Current captures

| State | Originals |
| --- | --- |
| Word detail, global preview while dragging, committed short-word cut, layouts, preparation error/retry at DPR 1 | [Corrective DPR 1](s09a-corrective) |
| The same full corrective fixture at Retina DPR 2, including word edit on hour-long audio | [Corrective DPR 2](s09a-corrective-dpr2) |
| Long names, mobile DSP and bounded short-screen transport | [Playback/layout](s09a-playback) |
| Exact preparation/deletion/retry safeguards | [Preparation](preparation) |
| Long-source Follow, maximum zoom, playing and paused end seek | [Follow](follow) |
| Preserved keyboard and short-screen menus | [Menus](menus) |

Visual inspection covers both editors, all four widths and DPR 1/2, active-tool
color, global/track scope, fractional source ruler, visible word-scale waveforms
and matching cut regions. Captures are original PNGs; the manifest is not a set
of resized QA composites. Earlier package and timeline/workspace evidence keeps
its original source attribution and is not proof of this new UI.

## Preview and limits

The existing `python3 scripts/preview-audio-editor.py` process remains running at
**http://127.0.0.1:55153/Audio-Editor.html**.
[HTTP byte verification](preview.log) confirms the actual editor/styles/modules
are served from this checkout. The user may refresh manually after saving work;
no existing user page was automatically reloaded. The permanent preview rule in
AGENTS.md continues to apply.

Detail decoding is display-only; bounded windows do not modify source bytes or
recipes. Source loop is not a rendered edit/DSP or sample-accurate loop. Actual
user Zoom files and physical-speaker listening are not claimed. Chromium DPR
emulation is not other-browser/physical-device/user Acceptance. User acceptance
remains open. PR remains draft; no merge, production mutation or Closure Record.
