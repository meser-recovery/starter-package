# PR #36 shared workspace evidence

- Baseline/before: `756e3cd11b2307467ba1935c7ff87e4d1f55e5c2`.
- Final implementation and after capture SHA: `6ee46682b4cac65a1e9c228b4e2b6c1009084bb0`.
- This directory is added in a separate evidence-only commit. Its exact submitted
  HEAD and `local-safety` run/result are recorded in draft PR #36 without another
  commit changing that checked HEAD.

[Patch reconciliation, browser findings and regressions](../../../S09A-workspace-validation.md)
· [43 PLAN sections / all 24 §42 expectations / A01–A18](../../../S09A-corrective-audit.md)
· [Original PNG dimensions and SHA-256](MANIFEST.md).

Historical PR #36 logs and screenshots remain bound to their original SHAs.
The first workspace evidence commit `911f38e` remains historical for source `0033ae7`. Linux CI run `34524573749` found a 154.98px Announcement lane; its desktop actions now use five explicit columns, retaining the 150px limit. The current captures and full local logs below were refreshed after that correction.

CI run `34525654306` on evidence HEAD `a5bf2b0` passed the Linux geometry and signal checks, then exposed menu activation timing after resize without captures. The current source positions summary activation synchronously and reveals the anchor before Tab or queued scroll; its explicit offscreen-focus regression passes with and without captures. The current evidence also replaces an earlier static log that stopped at a trailing blank line in a gateway log; current static checks pass, and evidence log endings are normalized.

Neither the supplied package's non-browser checks nor earlier CI is substituted
for this implementation's browser run.

## Validation

- [Site contract, changed JS/Python syntax and whitespace](static.log): PASS.
- [Shared transport](transport.log): 5/5 PASS.
- [Gateway syntax](gateway-check.log) and [gateway tests](gateway-tests.log): 80/80 PASS.
- [Complete post-commit browser smoke](browser-full.log): PASS, default Chromium
  security, root/subpath CORS and isolated local fixtures. Command:
  `venv/bin/python -u -B tests/safety/browser_smoke.py --base-url http://127.0.0.1:8000 --screenshot-dir /private/tmp/s09a-workspace-final-v4`.
- [Native browser audio signal measurements](s09a-playback/signal.json) ([normalized capture rerun](signal-captures.log)): 20 cases
  measuring actual 330/660Hz media output after mute/volume. Both modes, each
  Mute/Solo, multiple Solo, reordered identities, monitoring volume, Exclude
  preserving source monitoring, rendered MP3 excluding the 330Hz source, and
  source/result isolation passed. This is signal analysis, not a claim of human
  listening through physical speakers.
- [Management regression without captures](management-no-captures.log): PASS, including offscreen focused summary activation, first-action focus, visible popover bounds, Escape return, resizing and prior preparation/deletion regressions.
- Preparation/version/series deletion, failure/retry, exact File/Blob/payload/
  epoch/latest canonical revision, 401/403/reconnect, delayed intents and actual
  local save/reopen/render remain in the full run.

Earlier failed discovery runs exposed sticky touch obstruction, excessive lane
height, inherited Announcement columns, low heading contrast and old tests that
expected the removed native source controls or visible Follow text. Those runs
are not counted as final PASS. The original 210px Speaker / 150px Announcement
lane limits, waveform width requirement and audio tolerances were retained.

## Captures and visual review

The manifest contains 156 original PNGs. The new [offscreen-focus menu capture](s09a-corrective-management/library-menu-offscreen-focus.png) shows the revealed row and fully visible menu with its first action focused.

`before/` and `after-paired/` use the same two synthetic 3-second WAV sources,
ready state and 320/390/768/1280 widths. Before pages are served from the exact
baseline HTML/modules/styles in a temporary overlay, with only unchanged assets
falling through to the working checkout. The current branch was not reset.
After pages are from the final checkout. The signal/layout and selection fixtures were rerun on the same UI source with full-page capture normalized to scroll position zero and blurred focus, avoiding Chromium sticky/fixed screenshot artifacts; short viewport captures retain their scroll position. Both wait for ready waveform state and
resize completion. Original full-page PNGs are retained, not QA composites.

| State | Current captures |
| --- | --- |
| Both editor layouts, all four widths | [before](before), [paired after](after-paired), [long M4A workspaces and preparation error](s09a-corrective) |
| Import, selection tools, exact editing, Solo/excluded lanes, help, saves and reconnect | [operator flow captures](s09a) |
| Long filenames, mobile DSP disclosure, short sticky transport | [playback/layout captures](s09a-playback) |
| Metadata/library/project/result states, menus, short-screen popovers and deletion during preparation | [management captures](s09a-corrective-management) |
| Earlier P1/P2 acceptance scenarios rerun on this source | [acceptance captures](s09a-acceptance) |

Visual review inspected paired editor states at all four widths, error/retry,
selection/Solo/exclusion, long names/open DSP, short transport, menu placement,
projects/results and reconnect states. Headers are readable; controls remain
beside waveforms on narrow screens; desktop tracks remain compact; selection
operations state their track/global scope. Short-screen transport deliberately
scrolls internally at its 45svh bound. Mobile context menus remain in document
flow, so resizing can put them below the current viewport; full-height mobile
library captures show those menus, while the short mobile capture records the
viewport after resize. Geometry/focus/interaction assertions, not a screenshot
alone, establish these behaviors.

## Working preview

Started with `python3 scripts/preview-audio-editor.py` and left running:
**http://127.0.0.1:55153/Audio-Editor.html**.

The real interface is also open in a separate visible Chromium session. The
local service-page UI marker is granted only in that preview browser; archive
authentication and gateway security are unchanged. No fixture was saved into the
user's archive. [HTTP byte verification](preview.log) confirms the server serves
this checkout's exact HTML/JS/CSS. The user can refresh after saving their work;
no existing user page was automatically reloaded.

AGENTS.md now permanently requires a working preview before merge for every UI
change, with URL, version and checked scenarios, continued preview availability
on follow-up changes and no automatic reload of unsaved work.

Actual user Zoom recordings were not supplied. Synthetic M4A/MP3/WAV and Chromium
emulation do not constitute physical-device/Safari/Firefox/screen-reader or
user visual/listening Acceptance. PR remains draft. No merge, deployment,
production mutation, branch deletion or Closure Record.
