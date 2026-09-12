# PR #36 approved timeline UX validation

This continues draft PR #36 on `codex/s09a-editor-corrective-ux`. The
implementation and browser-capture source is
`7408600b81385eb7a4a1188c51f1b02747c64fdc`. Earlier S09A editor, waveform,
transport, region, meter and design changes remain in the branch.

## Implemented behavior

| Requirement | Browser-visible result and regression |
| --- | --- |
| Shared selection | A new source opens with the whole source interval selected across all tracks in both editors. Speaker Cut stays global; arming Silence narrows the same selection to the track under the pointer. |
| Time / Height | One control switches between independent retained values. Time reaches 1000 px/s; Height changes every visible track together without modifying the Speaker recipe. |
| Regions | Cut is red `rgba(221,66,75,.27)`, Silence is yellow `rgba(234,184,47,.36)`, Loop is light green, and excluded recording bounds are gray `rgba(75,86,100,.64)` while retaining the waveform. Labels and exact edit identity survive reorder and restore. |
| Shared Loop | Both editors show one strip under the ruler and a matching interval on every track. Its two keyboard and pointer handles update the live selection used by the existing source transport. |
| Track colors | Deterministic distinct colors are assigned by track identity. The native round color input changes display state only and follows its track through reorder. |
| Space transport | Space controls the visible editor and follows the last source/result pointer or focus context. Repeats, modifiers, composition, dialogs and native controls are ignored. The result case uses an actually rendered MP3. |
| Pinch zoom | Ctrl+wheel uses `deltaMode`, keeps the source time under the pointer, disengages Follow and remains a horizontal zoom while the slider displays Height. Safari gesture start/change/end uses the same anchored path. |
| Expanded editor | Each editor can fill the page and return without losing selection, zoom or horizontal position. Escape returns focus to the control and does not steal active edit/handle/dialog gestures. |

The dedicated browser regression uses two real synthetic WAV inputs and the
actual editors, media elements, waveform decoders, Speaker renderer and DOM. It
also switches editors, reorders tracks, performs Cut and Silence, drags a Loop
handle, checks ignored Space cases, and exercises normal/expanded geometry.
Pure tests cover deterministic colors and bounded wheel normalization for pixel,
line and page delta modes.

## Validation and evidence

- `python3 tests/safety/check_site.py`: PASS.
- `node --test tests/safety/*.test.mjs`: 33/33 PASS.
- Changed JavaScript syntax and `git diff --check`: PASS.
- Complete browser smoke with default Chromium security and isolated local
  requests: PASS. It retains the full archive, source-session, real FFmpeg,
  waveform onset/amplitude, continuous Follow, native signal, editing, meters,
  result isolation, responsive layout and root/subpath CORS coverage.
- The waveform parity regression passes in both editors at
  80/159/160/300/1000 px/s. Continuous playback/Follow preserves the same source
  pixels, updates scroll/playhead on animation frames and remains stationary
  after pause.

[Evidence](evidence/s09a/approved-timeline/README.md) contains the original DPR 2
PNG captures and the interaction recording. The media fixtures contain generated
tones and no user audio.

## Preview and limits

`python3 scripts/preview-audio-editor.py --port 0 --no-browser` is left running
at **http://127.0.0.1:56893/Audio-Editor.html** from this checkout. Existing user
pages were not reloaded. Refresh manually after saving any work.

Synthetic Chromium media/gesture checks are not physical-trackpad, physical
speaker, Safari/Firefox, screen-reader or user Acceptance. Actual user Zoom
files were not supplied. PR #36 remains draft; no merge, deployment, production
mutation or Closure Record is part of this change.
