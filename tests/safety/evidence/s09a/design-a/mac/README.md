# Design A Light: receiving Mac validation

Source for the complete local smoke: 000cc7b444b1fc2f22cc7d306f62856d508f7146.
Final evidence-only HEAD and exact-HEAD CI are recorded in draft PR #36.

## Reconciliation

The receiving branch `codex/s09a-editor-corrective-ux` and remote draft PR were
clean at `eddac6b62b49c9bcab88203b2ac7f196193f4b17`. Previous A was absent.
Extracted both alternatives preserving UTF-8/LF and verified their SHA-256:

- DELTA: `ea169cca480f2abf8ee78916b4fbab20b0c7493e8885663e3cc7f95903ef63b0`.
- FULL: `44fdf6502c8f8482da7da1e147d88739475305b24ce2972d3c9e50630b3015b0`.

DELTA applicability failed on absent A files. FULL applicability passed and was
applied once as `a912926e2167e346346ed27cab728dca0b01c36d`. DELTA was not applied.
Stable patch-id `def8ae17a2d6ed1012deec4fb987c70dbedc9bcb` matches the FULL
commit. No reset, clean, force push or repetition of older packages. The supplied binary
PNG was applied unchanged and retains its author attribution one level above.
The A-only reference remains at `tests/safety/references/S09A-approved-concepts.html`.

## Actual receiving checks

- [Site contract, changed JS/Python syntax, both HTML documents and whitespace](static.log): PASS.
- [Workflow transport/waveform/detail command](units.log): 26/26 PASS.
- [Gateway check](gateway-check.log), [gateway tests](gateway.log): 80/80 PASS.
- [Complete post-commit local browser smoke](browser-full.log): PASS.
  Command: `venv/bin/python -u -B tests/safety/browser_smoke.py --base-url http://127.0.0.1:8000 --screenshot-dir /private/tmp/s09a-design-full-v4`.
- New Design A native signal regression: per-track silence/restoration, global
  cut skip across synchronized tracks, recording-end stop and preserved Solo/Mute.
  DSP changes and Undo/Redo retain actual rows/canvases/audio and viewport at
  three zoom factors. Light/dark Speaker layout at 320/390/768/1440, DPR 2.
- Both-editor meters: actual anti-phase L/R, summed overload, CLIP latch/reset,
  native mute/volume, fixed contextual button positions and thin 16px edge targets.
- [20 native tone/RMS cases](signal.json): both editors, volume/Solo/Mute/reorder,
  render exclusion and source/result isolation. No second audible analysis path.
- Full corrective fixtures at DPR 1/2: hour-long synthetic M4A, native-decoder
  failure/bundled WASM fallback, preparation/retry, File/Blob identity, word zoom,
  both editors and four widths. Live region resizing, actual touch, Escape,
  pointer cancellation, ID restoration, boundaries and Loop remain covered.
- Full site suite retains archive root/subpath CORS, menus/deletion races,
  save/reopen/reconnect, real DSP/mixing/silence/duration and resource cleanup.
- [Supplemental Announcement/theme and dark archive checks](extra.log): real
  processed WAV/result, light/dark 320/390/768/1440, DPR 2 detailed canvas pixels
  and actual theme repaint. Dark archive runs the complete management/menu
  fixture with the local in-memory gateway, 254 requests and no outbound access.

The first complete local run failed an old hard-coded waveform color check
(red channel 116 from `#74b2e6`). [Discovery log](discovery-failed.log) is retained,
not counted as PASS. The timeline regression now requires an opaque pixel matching
all three RGB channels of the active track/theme color, while retaining its
Retina, source-time seeking and media tolerances. Its focused DPR 1/2 test passed;
then the complete suite ran again after committing the change.

Supplemental visual inspection also found the Announcement result still using
a light background with light text in dark mode. The package targeted the
nonexistent `.processor-result` class. `3762611` corrects the selectors to the
actual `.processor-preview`. The Design A fixture now renders an actual result
and checks at least 4.5:1 contrast for its heading, time, track count and publish
explanation in both themes at 320/390/768/1440. The old screenshot is retained
under `discovery/`, separate from final captures. The new complete local run
started after this CSS/test correction was committed.

The later Source Session fixture still searched the long visible label
“Исключить из микса” after A shortened it to “В миксе”. `000cc7b` locates the
button by its retained exact accessible action name and preserves the disabled
state assertion. The focused Source Session fixture passed. This selector
failure is [recorded separately](selector-discovery-failed.log); only the final
post-commit full run is counted as complete smoke evidence.

## Visual evidence and preview

[PNG dimensions and SHA-256](MANIFEST.md) index original images. `full/` captures
come from the final full smoke; `supplemental/` images come from additional theme
checks on application commit a912926; they document the extra archive/theme checks before
the later result-selector correction. Final corrected result screenshots are
in `full/s09a-design-a/`, and the old result screenshot is explicitly discovery
evidence.
The reference screenshot was compared with the fresh `preview-a.png`: integrated
transport/clock/master, separate edit row, light panels, thin boundaries and
real spaced Speaker waveform strokes. Representative mobile dark Speaker,
Announcement light/dark and dark archive screens were also inspected.

Spaced overview strokes apply to the shared canvas renderer, which retains peaks
across the entire 3px cell and uses every device pixel at word zoom. Announcement's
existing coarse PNG overviews (including result overview) remain its fallback;
its detailed source canvas uses the new theme/Retina rendering. No decorative
waveform or new audio decoder was substituted for those existing assets.

The existing repository preview remains at
**http://127.0.0.1:55153/Audio-Editor.html**. [HTTP byte checks](preview.log) verify
both HTML pages, styles and modules against source HEAD. A separate headed window
opened the actual editor. User pages were not automatically reloaded; refresh
manually after saving work. Final evidence HEAD receives another HTTP check and
is recorded in PR #36; no duplicate server was started.

Synthetic media and Chromium emulation do not establish physical listening,
real user Zoom files, Safari/Firefox or user Acceptance. Edit audition applies
cuts/silence; enhancement/leveling/compression still use final rendering, and
native media scheduling is not sample accurate. No schema/backend/dependency
changes, merge, production mutations, deployment or Closure Record.
