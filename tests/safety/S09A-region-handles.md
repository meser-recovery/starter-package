# S09A — Contextual restoration and live region edges

This report describes the supplied package environment. See
[current Mac validation](S09A-region-validation.md) for the applied branch,
additional regressions, full smoke/CI and persistent preview.

Base: `4d3bd133a1e8e3d482c3b515109c1b826546d528`, draft PR #36.
Package continuation; no merge, production changes or Closure.

## Requested behavior

- Cut/Silence still arm a tool; dragging then releasing commits a global cut or
  a same-duration silence on the originating track.
- Clicking or keyboard-selecting an existing region changes its matching toolbar
  button to Restore. There are no separate toolbar Restore buttons. The other
  tool keeps its Apply behavior. Clearing selection/Escape or entering a new
  numeric selection returns normal tools. Restoration targets the selected ID,
  never coincident cuts and silences together.
- Both edges of cut and silence regions have visible draggable handles. Cut
  geometry updates on all source rows, silence only on its own row. Keyboard
  arrows move an edge by 10ms; Shift+arrow by 1s. Focus survives a commit.
- Dragging recording Start/End flags updates the excluded span and flag positions
  on all rows immediately. Boundary-region IDs survive moving an existing flag.
- Pointermove changes a transient visual payload. Pointerup commits one history
  entry. Escape, pointercancel, lost capture or a source/state replacement cancels
  the preview. Exact source File objects and source-time coordinates are retained.
- Edges cannot cross each other, leave the recording or merge into another region
  of the same kind/track. Invalid moves retain the last valid displayed position.
- General Speaker source playback starts/restarts at the marked Start, stops at
  End, and Stop returns to Start. Seeking is clamped to those boundaries. A loop
  uses the intersection of selection and recording bounds; empty intersections
  disable Loop. Monitoring mute/solo and result playback remain independent.
- Loop has a stroked two-arrow cycle icon, a visible Loop label, tooltip and
  pressed state in both editors.

## Validation

- Site contract, JS syntax, Python compilation, diff whitespace: PASS.
- Transport/waveform/detail units: 18/18; includes playback bounds and loop clipping.
- Gateway syntax and 80/80 tests: PASS.
- Existing selection/tool/monitoring/loop/DSP/layout browser fixture plus new
  `s09a_region_handles_smoke.py`: Chromium DPR 1 and 2. Native two-track WAV audio,
  live geometry before release, one-step Undo/Redo, selective restore, cancellation,
  keyboard focus, 1000+px/s resizing, live flags and actual playback stopping at End.
- Complete S09A corrective browser fixture, DPR 1: PASS (bundled WASM, forced native
  failure, preparation/retry, hour-long synthetic M4As, both editors and four widths).
- New tests are called from the existing corrective smoke path. Old restore tests
  now explicitly select a region and use the contextual toolbar button.

Evidence is in `evidence/s09a/region-handles/`. No full site-wide smoke or remote
CI for this package was run here. The receiving Codex must run those on the
applied branch and keep PR #36 draft with a working Mac preview.

## Preview and limits

Local browser verification used the actual repository Audio-Editor.html, not a
mockup. The user's Mac preview at `http://127.0.0.1:55153/Audio-Editor.html` has not
been updated from this environment. Applying this package must update that
checkout and verify its HTTP bytes, leaving its preview running. Refresh only
manually after the user saves their work.

Loop still auditions source audio; interior cuts, silences and DSP are rendered
through the existing final-result path. Only recording Start/End now constrain
source playback. Real user Zoom files, physical listening, Safari/Firefox and
user visual acceptance are not claimed. Stored schemas and rendering algorithms
are unchanged.
