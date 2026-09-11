# PR #36 word-scale editing: Mac validation

The requested continuation uses `codex/s09a-editor-corrective-ux`, draft PR #36.
User visual/listening Acceptance remains open. No merge, production mutation or
Closure Record is authorized or performed.

## Reconciliation

The local checkout and remote PR were clean at
`80c1ef5c83fd6317f11ca3ecd539a03f82d8d101`. Both archive SHA-256 checks passed.
Stable patch-id `8dea46e2c380f5e603dc397e99319db714430b6a` was absent from the
corrective branch history. The one new package commit
`138ad70c11abacfe30ec8e971f2ecd68822d6b18` was applied with `git am --3way` as
`8426cc3b50d0715f3be85fff00d4a4343c8fd52c`. Earlier patches were not repeated;
subsequent branch corrections were preserved without reset or force push.

The [supplied implementation report](S09A-word-edit-tools.md) and its seven PNGs
remain historical package evidence. Current Mac captures/logs have their own
source SHA in [the evidence index](evidence/s09a/word-tools/mac/README.md).

## Browser coverage

The full corrective fixture now runs at both DPR 1 and 2 in the site-wide smoke
and Linux CI, including its 320/390/768/1280 layouts and preserved geometry limits.
It generates two synthetic 1:02:27 M4A tracks with the bundled codec, forces
native decoding to fail for the short fixture, exercises retry, and verifies
that the hour-long sources do not enter whole-file native PCM decoding.

| Scenario | Regression |
| --- | --- |
| Bounded detailed waveforms | Both editors decode the visible window after max zoom and immediate scroll to 80s; <=32s, enough sample bins, viewport-sized canvas at DPR 1/2, exact seek within 0.02s |
| Word editing on a long source | At >=1000 CSS px/s, 100px drag creates one ~100ms global cut after pointerup; preview changes no payload; restore preserves the original payload and exact File objects |
| Tool-first cut | Arming does not change the recipe; live preview appears on every row, including an excluded row; pointerup commits one global cut |
| Tool-first silence | Only the originating track previews and receives silence; global cuts and other tracks remain unchanged |
| Cancellation | Escape cancels gesture/tool; pointercancel on each active tool commits nothing, preserves prior exclusion/payload and releases the gesture |
| Existing editing | Exact numeric selections via keyboard Enter, per-region restore without Undo, Undo/Redo, boundaries, loop, Mute/Solo and DSP remain in the existing fixture |
| Preserved safety | File/Blob/session identity, epoch/abort, preparation/retry, deletion during preparation and latest revision, 401/403 reconnect, save/reopen/render |
| Transport/navigation | Real signal/RMS, loop cycles, zoom/scroll seek, source/result/editor isolation, paused Follow, immediate scroll after zoom, pan and shared rail checks |

The first full discovery run found an obsolete selector that prohibited the old
single-track detail UI by class name. The patch uses that class for new per-track
canvases. The test now prohibits the obsolete non-canvas detail UI and separately
requires a detail canvas on each track. No waveform geometry or audio tolerance
was relaxed. The existing source overview PNG assertions and independent result
waveform behavior remain.

The capture-enabled discovery run also exposed Follow disengaging on a long
source at maximum zoom. A delayed scroll notification for the already assigned
position reproduced the bug at all three widths after the old two-frame lock
expired. Synchronization now ignores that unchanged position independently of
frame timing and records the actual browser-rounded/clamped scroll position.
Diagnostics also reproduced a floating target of 149940.49999999997px rounded
to 149941px, which exceeded the former 0.5px comparison. Different user positions
still apply immediately after zoom.
The long-source navigation fixture runs without screenshot capture in CI too,
with playback, paused end seeking and a deterministic delayed-event regression.
The regression failed before the fix; no media-clock or geometry tolerance was
relaxed. The rail is scrolled into view before coordinate-based interaction.

Site contract, JS/Python syntax, strict HTML nesting, all 15 transport/waveform/
detail units, gateway syntax and 80 gateway tests are required alongside the
complete browser smoke. Source-bound results and exact submitted-head CI are
recorded in the evidence index and draft PR, rather than substituting old CI.

## Preview and limits

The existing `python3 scripts/preview-audio-editor.py` process continues serving
**http://127.0.0.1:55153/Audio-Editor.html** from this checkout. Exact HTTP bytes
are checked for the editor, styles and changed modules. The user can manually
refresh after saving their work; no existing page is automatically reloaded.

Detailed waveforms are display-only, bounded source windows. Tool mode and loop
selection are ephemeral; source bytes, stored schema, DSP/render algorithms and
archive protocols are preserved. Loop auditions sources, not the edited/DSP mix.
Actual user Zoom files and physical-speaker listening are not claimed. Chromium
DPR emulation is not Safari/Firefox, physical-device or user Acceptance.
