# PR #36 timeline controls: Mac validation

This continues draft PR #36 on `codex/s09a-editor-corrective-ux`.
User visual/listening Acceptance remains open. No merge, production mutation or
Closure Record is part of this work.

## Reconciliation

Local and remote HEAD were clean `76925d3bc268d6eb6a7657d80d7c4ab29a475eaa`.
Both archive SHA-256 checks passed. Stable patch-id
`3924d2dfc8203d61df27c62809dee5ac1b41c954` was absent from the corrective branch
history. The single new patch `108e5ee2e7fad9edc3563683ead274d0afbba485`
was applied once with `git am --3way` as
`cd78be4ad039ed20b2639813573b83e697f15c55`. Earlier workspace patches and later
preparation/menu safeguards were preserved; no reset, rebase or force push.

## Browser corrections and coverage

- Linux run `34532670932` passed timeline/Retina/signal/preparation checks but
  found an old result seek test expecting >0.2s at pixel 90 of a max-zoom image.
  At the new 4096px resolution that point is correctly about 0.096s. The test
  uses visible pixel 300, retains >0.2s and additionally checks the exact scaled
  time within 0.02s; source/result isolation and keyboard checks remain.


- At high zoom a previously queued Follow animation frame could still move the viewport after pause. The frame now exits when paused/ended and the pause event cancels it. The existing <2px stationary viewport regression is retained.
- The new compression control increased desktop lane height to 225.81px. Its
  label/value now sit beside the slider/ticks, and desktop panel spacing is
  tighter. The original 210px Speaker and 150px Announcement limits, majority
  waveform width and real signal tolerances remain unchanged.
- Remaining processor input tests now use the specified Alt-drag pan and Shift-arrow selection gestures. They retain pan-without-seek and normal Home/End/arrow seeking, and assert exact keyboard-selected bounds and loop enablement.
- The old touch-selection coordinate now hit a draggable flag. The regression
  explicitly hits the waveform body below the flags and retains its selection
  assertion. Flag drag/cancel has separate actual pointer coverage.
- The package's loop observer counted `seeked` after `timeupdate` had already
  replaced its previous time, reporting zero wraps despite real playback.
  The test now independently observes backwards jumps in the native media clock
  on animation frames. Playback methods and audio samples are not mocked.
- The Announcement assertion now waits for the actual play event's UI update,
  rather than checking aria-pressed between synchronous play and that event.

| Requirement | Actual browser/unit coverage |
| --- | --- |
| Detailed waveform | Renderer unit tests; actual bundled WASM after forced native decode failure; two synthetic 1:02:27 M4A tracks; native waveform canvas pixels and DPR 1/2 backing resolution; zoomed PNG envelopes |
| Click seek | Both editors at 320/390/768/1280 and DPR 1/2, expected source time after zoom plus scroll, synchronized clocks; ordinary clicks in corrective smoke |
| Loop selection | Two/three actual clock wraparounds, synchronization, independent Mute; transport invalid/cleared/replaced-source and result-exclusion unit cases; existing native RMS signal smoke retained |
| Selective restore | Same-range cut and track silence plus unrelated cut; restore by exact region, unrelated ID retained; Enter selection; original baseline payload restored |
| Boundary flags | Real drag previews without early commit, pointerup commits, both pointercancel paths retain payload and marker value; 0.1s and Shift 1s keyboard steps, Home/End, retained focus |
| Bottom navigation | Actual rail below the last track in both editors, including zoom/scroll at four widths and DPR 1/2 |
| DSP controls | Native switches via keyboard and pointer; all four compression presets, aria-valuetext and retained focus; other track unchanged; original processing/render regressions retained |

The complete browser suite retains exact File/Blob/session identity, source
preparation/retry, canonical revision refresh during deletion, epochs, 401/403
and reconnect, saved payload/reopen/render, real FFmpeg and root/subpath CORS.
Source-bound final logs, screenshots and exact-head CI are linked from the
[timeline evidence](evidence/s09a/timeline-interaction/README.md) and draft PR.
The package's original report remains historical; its missing Chromium is not a
claim about the Mac validation.

## Preview and limits

The existing `python3 scripts/preview-audio-editor.py` process continues serving
**http://127.0.0.1:55153/Audio-Editor.html** from this checkout. The user may
refresh manually after saving their work; no existing page is auto-reloaded.
The final SHA and checked scenarios are reported with the PR/evidence.

Loop auditions source audio. It does not apply the rendered cut/silence/DSP mix
and is not sample-accurate gapless playback. Actual user Zoom files were not
supplied. Native browser clock/signal measurements are not physical speaker
listening or Safari/Firefox/physical-device/user Acceptance.
