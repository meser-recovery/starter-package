# S09A — timeline interaction iteration

Base: `76925d3bc268d6eb6a7657d80d7c4ab29a475eaa` (draft PR #36).
Status: implemented locally; browser verification and user preview acceptance pending.

| Request | Implementation | Verification here |
| --- | --- | --- |
| Detailed waveform when zoomed | Speaker keeps up to 65,536 peaks (formerly 1,400); canvas draws only the visible time window at device resolution and aggregates peaks. Announcement envelope grows to 64 bins/second, capped at 65,536; source zoom accounts for DPR. | Three renderer unit tests; native FFmpeg generated a 65,536 × 100 RGBA envelope for 121 seconds of synthetic audio. Bundled WASM still needs browser validation. |
| Click to position playhead | Click without dragging seeks all synchronized source media; dragging selects. Announcement Alt-drag retains panning. | Browser regression added, not run here. |
| Loop selection | Shared repeat button starts at the selected interval, wraps at its end and preserves each track's mute and master volume. Stop pauses; clearing selection / replacing sources / unavailable sources disables repeat. | Transport suite 8/8. Real media browser regression added, not run here. |
| Remove silence/cut without Undo | Clicking an existing overlay selects its exact interval. Separate restore tools remove matching cut or silence regions by ID, retaining unrelated edits. Keyboard Enter selects a region too. | Browser regression added, not run here. |
| Drag start/end flags | Pointer drag previews the boundary; pointerup commits one edit. Cancellation does not commit. Existing boundary validation remains. Arrow keys adjust by 0.1 s, Shift by 1 s; Home/End reach source limits when valid. | Browser regression added, not run here. |
| Scrollbar below tracks | Both shared source navigation rails moved after track lists in actual DOM order. | HTML nesting + site contract pass; browser geometry assertions added. |
| Switches and four compression modes | Enhancement and leveling use native accessible switches; compression is a stepped slider with visible Off/Light/Medium/Strong labels and aria-valuetext. Maps to unchanged DSP presets. | Existing DSP browser scenarios updated; not run here. |

## Scope and behavior

- Loop auditions synchronized **source audio**, matching the existing source transport. It is not a rendered preview of cut/silence/DSP edits. Its boundaries use the media clock with animation-frame checks; sample-accurate, gapless DAW looping is not claimed.
- Restore acts on the complete selected existing region, not an arbitrary partial overlap. Cut restoration applies to all tracks; silence restoration applies only to the selected track. If both occupy exactly that interval, both restore buttons are available.
- Record-boundary changes retain the existing source-coordinate cut representation and reject intersections with existing interior cuts. Source bytes, source identity, recipes, archive protocol and render/DSP code remain unchanged.
- Selection/loop state is ephemeral; no new project schema or automatic writes.
- New native switches/sliders replace prior selects in the existing browser tests; waveform image expectations changed to the new explicit resolution contract. No geometry thresholds were relaxed.

## Checks actually performed

- `python3 tests/safety/check_site.py`: PASS.
- Strict HTML start/end nesting check on `Audio-Editor.html`: PASS.
- Node syntax of the five changed/new JS modules: PASS.
- Python compile of safety scripts: PASS.
- `node --test tests/safety/audio_transport.test.mjs tests/safety/audio_waveform_view.test.mjs`: **11/11 PASS**.
- Gateway syntax check and test suite: **80/80 PASS**.
- Native FFmpeg high-resolution envelope generation: PASS; this is not the browser WASM check.
- Preview script subprocess + HTTP fetch of HTML, both changed rendering modules, CSS: HTTP 200. The HTTP check server was stopped afterward.
- `git diff --check`: PASS.

## Unverified / handoff gates

Chromium is absent in this environment. Playwright launch reports a missing executable; installation download timed out. No new browser screenshots, browser audio measurements, physical listening, or remote CI success are claimed. The new regression code must run locally and in CI before acceptance.

The user's Mac preview at `http://127.0.0.1:55153/Audio-Editor.html` is a separate process; this environment cannot update that checkout or serve a replacement at that address. Apply the patch there, keep the preview alive, report its actual checkout SHA and ask the user to refresh only after saving current work. If the existing server stopped, use `python3 scripts/preview-audio-editor.py` and report its generated free-port URL.

On the Mac, run full browser smoke including two synthetic hour-long tracks, native M4A failure/WASM fallback, selection/loop synchronization, selective restore, draggable/cancelled boundaries, keyboard controls, DSP state/focus, and geometry at 320/390/768/1280 and Retina DPR. Check both editors and preserve the existing exact File/Blob/identity/epoch/retry regressions. Use actual Zoom files only if the user supplies them.

Keep PR #36 draft. No merge, production mutation, or Closure Record is part of this iteration.
