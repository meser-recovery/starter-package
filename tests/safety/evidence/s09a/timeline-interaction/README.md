# PR #36 timeline interaction evidence

- Package base: `76925d3bc268d6eb6a7657d80d7c4ab29a475eaa`.
- Current implementation and capture source: `ae9bfc9fa4fdb8d0a89a088b07dbe2f4b2fd303f`.
- This evidence is committed separately. Exact submitted HEAD and final Linux
  `local-safety` result are recorded in draft PR #36, without another commit
  changing that checked HEAD.
- [Seven requirements, patch reconciliation, findings and limits](../../../S09A-timeline-validation.md).
- [Original PNG dimensions and SHA-256](MANIFEST.md).

## Final validation

- [Site contract, JS/Python syntax, strict HTML nesting, whitespace](static.log): PASS.
- [Transport and waveform renderer units](unit.log): 11/11 PASS.
- [Gateway syntax](gateway-check.log), [gateway tests](gateway.log): 80/80 PASS.
- [Complete post-commit browser smoke](browser-full.log): PASS. Command:
  `venv/bin/python -u -B tests/safety/browser_smoke.py --base-url http://127.0.0.1:8000 --screenshot-dir /private/tmp/s09a-timeline-final-v3`.
- Actual browser clock tests cover three loop cycles in each editor, independent
  Mute, exact zoom/scroll seek at four widths and DPR 1/2, cancelled start/end
  flag drags, keyboard boundary steps, native switches, four compression modes
  and focus retention.
- [Native media signal measurements](s09a-playback/signal.json): 20 tone/RMS
  cases with real media output, both editors, each Mute/Solo, volume, reorder,
  Exclude versus rendered mix and result/source isolation.
- Complete smoke retains bundled WASM, forced native M4A decode failure, two
  synthetic 1:02:27 M4A tracks, exact File/Blob/session identity, preparation/
  deletion/retry/latest revision, 401/403 reconnect, saved payload/reopen/render,
  actual FFmpeg mix/silence/passthrough/drift/duration/cancellation and root/subpath
  CORS using normal Chromium security. Fixture requests are local/isolated.

## Captures and visual review

The manifest contains 63 current original PNGs. The current originals cover both editors at 320/390/768/1280, DPR 1 and Retina
DPR 2, zoom plus scroll, waveform detail, loop, multiple edits/selective restore,
recording flags, keyboard DSP, long sources, failed preparation/retry, source
session deletion safeguards and edge/keyboard menus. Full-page timeline captures
normalize scroll/focus before capture; short-screen captures retain their scroll
position. Corrective and playback fixtures were rerun on the same source with full-page capture normalized to scroll zero and blurred focus ([corrective log](selection-captures.log), [signal log](signal-captures.log)); the complete suite also ran with its normal capture behavior. The manifest lists original pixel sizes and hashes, not QA thumbnails.

| Current state | Original captures |
| --- | --- |
| Both editors, four widths, DPR 1/2, zoom/scroll and keyboard DSP | [Timeline](s09a-timeline) |
| Active loop, cuts and silence, selective restore, dragged flags, two long M4A tracks, error/retry and four-width layout | [Corrective](s09a-corrective) |
| Long filenames, mobile open DSP and short transport | [Playback/layout](s09a-playback) |
| Preserved preparation/deletion/retry safeguards | [Preparation](preparation) |
| Offscreen focus and short-viewport menus | [Menus](menus) |

The [previous workspace captures](../workspace/README.md) remain historical
before-evidence, bound to their original source SHA. The editor implementation
at their final source `6ee4668` is unchanged in the timeline package base
`76925d3`; they are not presented as screenshots of the new timeline code.

Visual inspection found the compression controls exceeded the 210px lane limit
and split the last letter of their label. Both were corrected without relaxing
geometry checks. Current images show intact labels, controls beside waveforms,
bottom rails, visible flag markers and selective restoration retaining the
unrelated cut. Pointer/keyboard/media assertions establish behavior beyond a
still screenshot.

Earlier failed discovery runs are not counted as final success: touch hit the
new flag instead of the waveform body; the loop observer depended on seeked/
timeupdate ordering; old processor tests expected old pixel resolution, plain
pan and Shift-seek gestures. Linux run `34532670932` exposed the result-seek
expectation. At high zoom an already queued Follow frame also moved the viewport
after pause; the implementation now guards/cancels that frame, retaining the
existing <2px stationary-viewport assertion.

## Working preview and limits

The existing `python3 scripts/preview-audio-editor.py` process is left running at
**http://127.0.0.1:55153/Audio-Editor.html**.
[HTTP byte checks](preview.log) verify this checkout's actual editor, styles and
all changed timeline modules. The user can refresh manually after saving work;
no existing user page is automatically reloaded. The AGENTS.md preview rule
continues to apply through further changes.

Loop auditions source audio, not the rendered cut/silence/DSP mix, and does not
claim sample-accurate gapless playback. Actual user Zoom files were not supplied.
Native signal/clock checks do not claim physical-speaker listening, other browser
or physical-device acceptance. User visual/listening Acceptance remains open.
PR remains draft. No merge, production mutation, deployment or Closure Record.
