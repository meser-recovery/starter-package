# S09A: selection toolbar — correction awaiting browser review

Base: `756e3cd11b2307467ba1935c7ff87e4d1f55e5c2` (PR #36).
Local branch: `codex/s09a-daw-selection-toolbar`.
Date: 2026-09-10.

## User rejection remains authoritative

The user rejected the interface: overlapping/misaligned controls, indistinct white
buttons, confusing Solo/Mute, and four detached textual edit commands without a
clear relationship to the selected segment. This correction is not ACCEPT,
Closure, COMPLETE, or permission to merge/deploy.

## Implemented in this patch

- Move the four editing commands into the source transport above the timeline and
  lanes. Use inline SVG icons plus short visible labels, with explicit all-track
  versus selected-track scope. No icon/font dependency.
- Display the selected track name, start, end and duration next to the commands.
  Tool descriptions include the exact range and target. Disable all four tools
  when there is no valid segment, including the start/end boundary commands.
- Draw the selection while dragging, before pointerup.
- Show separate per-track monitoring states: audible, explicit Mute, Solo, and
  suppression caused by another track's Solo. S/M pressed states belong only to
  that track. Solo remains nonexclusive (several Solo tracks may play together).
- Give S and M distinct active colors, accessible names and track-specific
  descriptions/tooltips; shorten speaker order controls to arrows with names.
- Remove the selected-track badge's absolute positioning. Increase DSP select
  width and separate selected-lane indication from Solo. Use colored tool surfaces.
- Keep the selection tools in normal flow on narrow/short viewports. Isolate the
  workspace's stacking context so its sticky transport cannot paint over unrelated
  sections. Desktop sticky transport remains bounded by the source section.
- Add a browser regression to the existing corrective suite. It checks actual
  audio-element mute flags, live selection, single-track silence/global cuts,
  and tool geometry/screenshots at 320, 390, 768 and 1280 px. Existing boundary
  scenarios now supply a valid range rather than just a start coordinate.

The sound-routing handlers already addressed tracks by stable ID. Their routing
semantics are unchanged. An isolated execution of both current handlers did not
reproduce a Mute operation changing another track's mute flag. This is **not** a
claim that the user's audible problem is resolved: actual browser playback and
the reported files still require verification. Suppression by Solo was formerly
styled as Mute; that confirmed ambiguity is corrected here.

## Validation actually performed here

- `python3 tests/safety/check_site.py`: PASS.
- `node --check scripts/speaker-editor.mjs`: PASS.
- `node --check scripts/audio-processor.mjs`: PASS.
- Python syntax compilation of changed smoke modules: PASS.
- `git diff --check`: PASS.
- Isolated Node execution of the actual monitoring functions from both modules:
  PASS for independent Mute, one and two Solo tracks, suppression labels, and
  stable identity after reordering. Actual selection functions: PASS for empty,
  reversed and out-of-range disabling, valid ranges and track/scope descriptions.
  This used DOM/media stubs and is not an audible browser test.
- Chromium launch: BLOCKED — executable absent at
  `/root/.cache/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-linux64/chrome-headless-shell`.
- New browser regression, full browser smoke, responsive screenshots and listening:
  **NOT RUN here**. No earlier PR #36 screenshots/CI result attest to this patch.
- Gateway code, storage schema, DSP, authentication, source preparation/retry and
  the PR #36 revision/identity fix were not modified.

## Local Codex handoff

1. Check the current PR #36 HEAD and local worktree. Apply this patch once on the
   stated base (or reconcile against later commits without discarding their work).
   Do not reset or force-push an existing branch. Keep PR #36 draft.
2. Run site contract and JS/Python syntax checks, gateway check/tests and the full
   browser smoke with ordinary browser security and the existing local gateway
   fixtures. The new `s09a_selection_tools_smoke.py` is invoked from the existing
   corrective suite. Fix failures introduced by this patch.
3. Inspect actual screenshots of both editors at all four widths, including open
   menus, long filenames, selected segments, Solo/Mute, DSP selectors, page scroll,
   and narrow landscape. Check that the toolbar does not hide selection or menus.
   Do not relax existing geometry checks just to obtain green tests.
4. Listen with two recognizably different synthetic signals (then the user's files
   if available): Mute A leaves B audible, Mute B leaves A audible; Solo A, Solo B,
   both Solo; after reordering and metadata refresh; switch editors and ensure
   the previous editor's audio is stopped. Verify buttons, statuses and actual
   audible output agree. The native transport's speaker icon must not be mistaken
   for a separate global Mute; inspect that ambiguity before acceptance.
5. Check selection by mouse/touch/keyboard, clear/invalid ranges, Undo/Redo, scope
   overlays, and exact saved payload. Preserve File/Blob/montage and pending
   preparation protections from PR #36.
6. Commit fixes/evidence, push the corrective PR branch, run local-safety on the
   resulting exact HEAD, and provide a working preview URL on the user's Mac plus
   before/after screenshots. Explicitly list any remaining discrepancy.
7. No merge, production mutation or Closure Record. User visual acceptance remains
   pending, regardless of automated test results.
