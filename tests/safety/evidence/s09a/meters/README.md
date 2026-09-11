# S09A: thin region edges, stable tools, digital meters

Implementation base: `7680424624a231191e228e71190a8b1dbf7c9af0`.
Local review branch: `codex/s09a-meters`. Intended receiving branch: `codex/s09a-editor-corrective-ux`, draft PR #36.

## Behavior

- Cut/silence edges and recording start/end markers use 1px lines (2px on hover). Transparent 16px drag targets and keyboard interaction remain. Recording labels are separate from the line, with no opaque bar. Live updates and region-ID restoration remain.
- Four fixed tool slots reserve both width and two-line label height. Selecting a cut or silence region changes its tool to restore without changing button geometry.
- Both editors have per-track L/R RMS bars, sample-peak hold, numeric dBFS, and a resettable CLIP indicator. The left-panel meter adds at most 52px plus 5px spacing; the pre-existing controls retain their previous compactness budget.
- A master meter measures the audible source sum, or the rendered result while that player runs. It includes native media volume and Solo/Mute. Exclude-from-render still does not mute source monitoring. Per-track meters describe source monitoring; DSP is reflected in the rendered result meter under the existing rendering model.
- RMS power smoothing is 300ms; peak hold 1.5s; bars span −60…0 dBFS; readings may exceed 0 dBFS. CLIP latches at sample magnitude ≥1 and resets on click or project clear. Pause/stop clears live bars and peak hold, retaining CLIP until reset. These are digital RMS/sample-peak readings, not calibrated analogue VU or true-peak/loudness measurements.
- One shared lazy AudioContext and one MediaElementAudioSourceNode per media element. Each has one unity connection to the destination; analyser taps do not add an audible path. Stereo splitting prevents opposite-phase channels from cancelling in the analyser. Track bindings use stable IDs; removed secondary media and analyser connections are released. Persistent clocks keep their audible route during row changes.
- No source payload, DSP recipe, archive write, backend, or deployment changes.

The native playback contract for volume, seek and source replacement is documented in the [W3C Web Audio specification](https://www.w3.org/TR/webaudio/#MediaElementAudioSourceNode).

## Validation performed locally

- Site contract, changed JavaScript syntax and git whitespace checks: PASS.
- Existing transport/waveform command including three meter numeric regressions: **21/21 PASS**.
- Gateway syntax/check and tests: **80/80 PASS**; gateway source unchanged.
- New `check_audio_meters`: PASS in Chromium, DPR 2, both editors, 320/390/768/1280px. Native stereo calibration verifies non-cancelling L/R readings, summed master overload, per-track mute, stop and CLIP reset. Button geometry includes x/y relative to the toolbar and width/height before and after contextual restore selection. Thin visible borders and wide targets checked.
- Existing `check_playback_signal`: **20 tone/RMS cases PASS**, both editors, native media signal, Solo/Mute, volume, reordering, stable track IDs, render exclusion, source/result isolation. Independent test analysers observe the application's native source nodes without introducing a second audible path. Also checks result master reading and silent source meters during result playback.
- Existing selection tools at DPR 1 and region handle suite at DPR 2: PASS, including touch, live dragging, cancellation, boundary-limited playback/loop and replacement during a gesture.
- Full `check_s09a_editor_corrective`, DPR 1: PASS, M4A native-decoder failure/WASM fallback, retries, retained Files, two hour-long sources, word zoom/editing, four widths.

The new browser test is wired into `browser_smoke.py`. The receiving checkout still needs its complete browser smoke and exact-HEAD CI. This local run does not claim that the entire site-wide browser suite or GitHub CI was run here.

## Review and delivery

Two representative PNGs and test logs are retained with this local branch. The TXT handoff contains the code/test diff and this note; binary screenshots/logs are not required to apply it. The receiver should regenerate evidence on its own final commit.

The interface was opened in real headless Chromium using a loopback server in the test process. This environment cannot refresh or verify the user's Mac preview at `http://127.0.0.1:55153/Audio-Editor.html`. On the Mac, keep that preview running on the resulting branch, verify served files match the final SHA, and allow manual refresh after the user saves their work.

Safari, physical listening and user Zoom files were not tested. No merge, production mutation or Closure Record.
