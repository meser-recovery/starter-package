# S09A — shared workspace iteration, pending browser acceptance

Current PR #36 workspace follow-up: [local browser validation and preview](S09A-workspace-validation.md). Earlier reports below retain their original environment and source SHA.

Source base: PR #36 HEAD `756e3cd11b2307467ba1935c7ff87e4d1f55e5c2`.
Branch: `codex/s09a-daw-selection-toolbar`.
The user supplied the full 43-section S09A plan again and rejected the first
icon-only corrective scope as insufficient. This iteration includes that first
patch and continues the agreed workspace redesign. It is not Closure or ACCEPT.

## Implemented

| Plan | Current change |
| --- | --- |
| §4, §10–12 | Active editor remains the primary area. Compact header styling; announcement explanations become an accessible disclosure; active mode buttons are visually distinct without duplicate status text. |
| §12–13 | Shared workspace component styling, continuous aligned lanes, controls next to waveforms on desktop and narrow screens; secondary per-track DSP disclosure on mobile. |
| §14–15 | Explicit per-track Mute, Solo and Solo-suppressed states from the first patch; selected lane and mix exclusion remain distinct; S/M names, track-specific descriptions and accessible explanations retained. |
| §22–24 | SVG selection tools with current range/track and explicit operation scope. Selection is drawn during dragging. Existing global-cut, per-track-silence and boundary semantics preserved. |
| §25 | Shared custom Play/Pause, Stop and monitoring-level controls in both editors. Existing media element remains the synchronization clock but has no visible native source-player controls. Undo/Redo, zoom, Fit and Follow use compact icons. Source transport stays sticky at all widths, with bounded internal overflow for short screens. Result retains its separate player/time scale. |
| §11, §25 | Pause all media in the inactive editor, including results. Within each editor, source and result playback are mutually exclusive. |
| §27–38 | Existing media-library navigation, records/projects/results, search, deletion and recovery flows retained. Desktop context menus use the browser top layer and are placed within the viewport; mobile disclosures stay in normal flow. Keyboard Escape, focus return and outside-click closing retained. |
| §39–41 | No DSP, storage, API, canonical-data or infrastructure changes. PR #36 preparation/session revision safeguards remain intact. |
| §42–43 | Acceptance remains OPEN. Local checks below do not establish browser rendering, audible output or user acceptance. |

## Concrete playback finding

Previously `activateMode('speaker')` paused only `processor-source-audio`.
It did not pause `processor-result-audio`. An announcement result could therefore
keep playing after its workspace was hidden. Source and result playback within
an editor also had no mutual-exclusion guard.

This patch pauses every audio element in the inactive workspace and pairs each
source master with its result player. It does not mute other tracks as a shortcut
and does not change monitoring flags or final mix settings. This is a confirmed
code path, not a claim that the user's original audible symptom was reproduced.

## Checks completed in this environment

- Site contract: PASS. Its explicit local stylesheet/import allowlist now includes
  `audio-workspace.css` and `audio-transport.mjs`; FFmpeg remains lazily imported.
- JS syntax and changed Python syntax: PASS.
- Shared transport behavioral tests: 5/5 PASS. Includes play/pause/stop, locked
  sources, source/result exclusion, volume independent of track mute, failed
  playback retry and rejection after source replacement. These tests use a
  DOM/media adapter; they are not a real audio or visual test.
- Gateway tests: 80/80 PASS.
- Preview server: PASS. Starts on a kernel-selected free loopback port and serves
  the real editor HTML and transport module from the checkout.
- Patch whitespace check: PASS.

Chromium is absent in this environment. No new browser screenshots, full browser
smoke, listening test or remote CI pass is claimed for this iteration. The prior
PR #36 CI and screenshots do not validate these changes.

## Browser regressions added/extended (not run here)

- Custom source play/stop operate all synchronized tracks.
- Master listening volume preserves per-track mute flags.
- Source/result listening cannot overlap.
- Opening Speaker explicitly pauses the hidden Announcement result, including
  while Speaker preparation is pending.
- Selection tools operate on the selected range and exact track identity;
  global cuts remain global, single-track silence remains local; Undo restores.
- Sticky transport and tool geometry at 320/390/768/1280 px.
- Desktop menus are inside the viewport and above other elements; mobile inline
  menus preserve keyboard navigation and Escape focus return.

The local-safety workflow now runs the five transport tests before browser smoke.
Production jobs, workflow permissions and deployment steps are unchanged.

## Preview before merge

After applying this cumulative change to the local PR checkout:

```bash
python3 scripts/preview-audio-editor.py
```

This opens the actual `Audio-Editor.html` in the default browser and prints the URL
and checkout SHA. Port 0 is the default, so occupied 8000/8001 are not a problem.
Keep the terminal open; Ctrl+C stops the server. `--no-browser` prints the URL
without opening a browser. The archive still uses the configured gateway; this
launcher does not create any archive records or perform a deployment.

## Local Codex completion task

1. Check current PR #36 HEAD and worktree. Apply the cumulative package once,
   reconciling later branch work without reset, force-push or duplicate patching.
2. Run site contract, JS/Python syntax, `node --test tests/safety/audio_transport.test.mjs`,
   gateway tests and the full browser smoke with normal browser security.
3. Fix regressions. Keep existing geometry thresholds; do not weaken them to get
   green output. Inspect both editors at all four widths, long names, open DSP,
   precise selection, menus near screen edges, scroll, touch and keyboard focus.
4. Listen to distinguishable tracks: each Mute separately, each Solo, multiple
   Solo, reorder, source/result switching and editor-mode switching. Verify that
   every hidden player is paused and exclude-from-mix semantics are unchanged.
5. Recheck delayed source preparation, retry, exact File/Blob preservation,
   401/403 reconnect, metadata/result deletion refresh, saved payload and render.
6. Capture before/after evidence from the actual implementation; update the full
   existing audit, including §42. Push to the corrective PR and obtain local-safety
   on the resulting exact HEAD. Provide the user a preview and a truthful list of
   unresolved points. User visual acceptance is still required.
7. No merge, production mutation, Closure Record or COMPLETE.
