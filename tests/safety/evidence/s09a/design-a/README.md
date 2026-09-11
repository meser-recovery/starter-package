# S09A — approved design A, edited audition

Receiving Mac reconciliation, final smoke and captures: [Mac validation](mac/README.md).

Author handoff status: implemented locally for handoff; no merge, production mutations or closure.
Base: `eddac6b62b49c9bcab88203b2ac7f196193f4b17` (PR #36).

The user selected A and asked to extend it to the rest of the audio interface.
A means one top row containing transport, clock and a long integrated stereo
master meter, followed by a separate editing-tool row. The light/dark palette,
thin borders, compact controls and blue/green waveforms extend to import, both
editors, results and Audio Archive. Existing URLs and archive operations remain.
The reference is `tests/safety/references/S09A-approved-concepts.html`: A only;
B/C are retained as historical alternatives and are not requested for production.

`preview-a.png` is an actual Chromium screenshot with generated test tones and
real meter readings, not a rendered mockup or the user's recordings.

## Behavior

- DSP changes update existing controls; rows, canvases, audio/File objects,
  source pixels-per-second and horizontal viewport are retained. Undo/redo of
  these settings follows the same path. Structural edits still rebuild safely.
- Speaker audition skips global cuts with a shared seek; silent regions gate
  only the corresponding track. The non-destructive source timeline and region
  restoration by ID remain available. Bounds and loop constrain playback.
- A Web Audio gain gate precedes both the audible output and meter taps.
  It does not rewrite the native media mute flag; Solo/Mute stay independent.
- Enhancement, leveling and compression still apply during final rendering;
  this patch does not introduce real-time DSP or claim that raw audition is
  identical to the rendered result. Meters measure the signal being heard.
- Native media remains the playback clock. This is not a sample-accurate DAW
  scheduler or a true-peak meter; physical listening was not performed.

## Validation performed by the patch author

- Site contract and JavaScript syntax: PASS.
- Transport/waveform unit suite: 25/25.
- Gateway syntax and tests: 80/80.
- New design-A browser regression: DSP identity/viewport at three zoom levels,
  real per-track silence and restoration, cut skip, recording-end stop;
  320/390/768/1440 widths, light/dark, DPR 2.
- Meter regression: both editors, actual stereo sum, clip retention/reset,
  Solo/Mute, stable contextual tool geometry, thin edges, four widths.
- Existing real-signal suite: 20 cases, both editors, result/source isolation.
- Region/selection suite: DPR 1 and 2, live edges, cancel and identity restore.
- Full corrective fixture: DPR 1, M4A native failure/WASM retry, retained files,
  long recordings, word zoom, editing and compact lanes at four widths.
- Archive management fixture: four widths, 254 local gateway requests;
  no outbound archive access.

The site-wide browser suite and GitHub CI must be run by receiving Codex after
application to the actual PR branch. This local handoff does not update PR #36
or the existing Mac preview. Leave that preview running, verify served files
against the resulting HEAD, and let the user refresh manually after saving.

## Reproduce

The new `check_design_a` function is registered in `browser_smoke.py`; ordinary
full browser smoke now includes it. Existing fixtures generate all wider
responsive evidence on request via the existing screenshot-directory option.
No new dependencies or backend configuration are introduced.

## Visual correction after the user's review

The first implementation was too heavy compared with A. This follow-up uses
1.5 CSS pixel strokes spaced every 3 CSS pixels in overview, aggregating the
whole cell (including the visual gap) to retain brief peaks. At >=160 px/sec
it switches to device-pixel detail. No invented amplitudes or decorative
smoothing are used. The screenshot uses the same synthetic audio fixture.

Playheads and region boundaries have 1px ink, no doubled outlines, and retain
16px invisible drag targets. Selected regions use a faint fill; track meters
lose their box borders, marker labels are lighter, and the light theme is
brighter. Contextual buttons keep their fixed positions.

Follow-up validation: 26 unit tests, site contract, design-A browser fixture
and both-editor meter/geometry fixture PASS. Gateway/long-recording/region
results above belong to the preceding A implementation and were not rerun
for this visual-only correction. No new CI or physical listening is claimed.
