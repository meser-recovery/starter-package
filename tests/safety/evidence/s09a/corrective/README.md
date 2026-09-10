# S09A corrective evidence

This is implementation verification for a draft PR, not Acceptance or stage closure.

- Base/before: `5a3e793e6e33e1a15e27dd6408e733c87d9a939f`.
- Implementation/after: `e0e4431eff0620944f8deddb3522d807faed19ea`.
- Branch: `codex/s09a-editor-corrective-ux`.
- This directory is added by the separate evidence-only commit following the implementation SHA. Its exact commit ID, submitted HEAD and CI run are recorded in the draft PR so recording CI does not change the checked HEAD.
- [43-section PLAN audit, all 24 §42 expectations and A01–A18](../../../S09A-corrective-audit.md).
- [Every original PNG, dimensions and SHA-256](MANIFEST.md). `after/s09/` contains newly captured S09 regression states from the corrective implementation, not relabeled historical S09 evidence.

## Executed checks

All commands below passed on the implementation SHA. Screenshots were captured during the complete post-commit browser run, with synthetic audio and isolated in-memory/test gateways. No production archive writes or relaxed browser security.

| Check | Command / evidence |
| --- | --- |
| Site contract | `python3 tests/safety/check_site.py` — [log](logs/static.log) |
| Changed frontend/Python syntax; whitespace | `node --check` on all 7 changed modules; `ast.parse` on all 6 changed Python files; `git diff --check origin/main` — [log](logs/static.log) |
| Gateway contract | `npm --prefix gateway/audio-archive run check` — [log](logs/gateway-check.log) |
| Gateway behavior | `npm --prefix gateway/audio-archive test` — **80/80** — [log](logs/gateway-tests.log) |
| Complete browser suite with screenshots | `venv/bin/python -u -B tests/safety/browser_smoke.py --base-url http://127.0.0.1:8000 --screenshot-dir /private/tmp/s09a-corrective-final-v2` — [full log](logs/browser-full.log) |
| Exact base desktop comparison | B browser scenarios served from git-archived base scripts/styles/Editor/Archive, unchanged assets from the repository, loopback port 8002 — [baseline log](logs/baseline-browser.log) |

The full browser run includes the actual bundled FFmpeg/WASM C scenarios: native decode rejection/fallback; named decoder-load failure and retry with the same File objects; all MP3/M4A/WAV local inputs and valid local rendered downloads; close during pending decoder load; two synthetic M4A tracks of 3747 seconds with no full native PCM decode; montage, focus, fit geometry and layout. It also executes D deletion/library corrections, prior PR #35 Acceptance regressions, source/processor checks, and root/subpath CORS regression under default Chromium security. The source duration tolerance and existing geometry thresholds are unchanged.

The earlier `2ac3ef8` screenshot run and subsequent preflight failed strict source-fit geometry. Those are debugging history, not final PASS evidence; the audit explains the measured fractional-width cause and fix.

## Visual coverage and review

Actual PNGs were visually inspected using 12 four-width contact sheets and individual desktop/mobile frames. Coverage is 320/390/768/1280 CSS px; clipping captures the named UI region, while `*-viewport.png` records the visible viewport. Original PNGs are unchanged. Contact sheets were temporary review aids, not substitutes for these originals.

| State | 320 | 390 | 768 | 1280 |
| --- | --- | --- | --- | --- |
| Import | [PNG](after/s09a/import-320.png) | [PNG](after/s09a/import-390.png) | [PNG](after/s09a/import-768.png) | [PNG](after/s09a/import-1280.png) |
| Announcement, two hour-long tracks | [PNG](after/s09a-corrective/announcement-320.png) | [PNG](after/s09a-corrective/announcement-390.png) | [PNG](after/s09a-corrective/announcement-768.png) | [PNG](after/s09a-corrective/announcement-1280.png) |
| Speaker, two hour-long tracks/actions | [PNG](after/s09a-corrective/speaker-320.png) | [PNG](after/s09a-corrective/speaker-390.png) | [PNG](after/s09a-corrective/speaker-768.png) | [PNG](after/s09a-corrective/speaker-1280.png) |
| Track states, selection, boundaries, precision/help | [PNG](after/s09a/speaker-edits-help-320.png) | [PNG](after/s09a/speaker-edits-help-390.png) | [PNG](after/s09a/speaker-edits-help-768.png) | [PNG](after/s09a/speaker-edits-help-1280.png) |
| Preparation error/retry | [PNG](after/s09a-corrective/preparation-error-320.png) | [PNG](after/s09a-corrective/preparation-error-390.png) | [PNG](after/s09a-corrective/preparation-error-768.png) | [PNG](after/s09a-corrective/preparation-error-1280.png) |
| Reconnect | [PNG](after/s09a/reconnect-320-viewport.png) | [PNG](after/s09a/reconnect-390-viewport.png) | [PNG](after/s09a/reconnect-768-viewport.png) | [PNG](after/s09a/reconnect-1280-viewport.png) |
| Unsaved dialog | [PNG](after/s09a/unsaved-cancel-320-viewport.png) | [PNG](after/s09a/unsaved-cancel-390-viewport.png) | [PNG](after/s09a/unsaved-cancel-768-viewport.png) | [PNG](after/s09a/unsaved-cancel-1280-viewport.png) |
| Archive source rows/context menu | [PNG](after/s09a-corrective-management/library-menu-320.png) | [PNG](after/s09a-corrective-management/library-menu-390.png) | [PNG](after/s09a-corrective-management/library-menu-768.png) | [PNG](after/s09a-corrective-management/library-menu-1280.png) |
| Actual saved Speaker projects | [PNG](after/s09a-corrective-management/library-projects-320.png) | [PNG](after/s09a-corrective-management/library-projects-390.png) | [PNG](after/s09a-corrective-management/library-projects-768.png) | [PNG](after/s09a-corrective-management/library-projects-1280.png) |
| Finished results, both workflows | [PNG](after/s09a-corrective-management/library-results-320.png) | [PNG](after/s09a-corrective-management/library-results-390.png) | [PNG](after/s09a-corrective-management/library-results-768.png) | [PNG](after/s09a-corrective-management/library-results-1280.png) |
| Deletion dependencies | [PNG](after/s09/delete-impact-320.png) | [PNG](after/s09/delete-impact-390.png) | [PNG](after/s09/delete-impact-768.png) | [PNG](after/s09/delete-impact-1280.png) |
| Contextual recovery | [PNG](after/s09/contextual-recovery-320.png) | [PNG](after/s09/contextual-recovery-390.png) | [PNG](after/s09/contextual-recovery-768.png) | [PNG](after/s09/contextual-recovery-1280.png) |

Additional indexed frames show failed/unsupported drafts, unknown counts, metadata/detail, verified playback, purge, partial save, repeated 403, stale deletion consent, source unsaved protection and preserved local work after version deletion.

Desktop comparisons use the same B fixtures and viewport width. The before and after images intentionally retain the different layout/scroll placement caused by the implementation.

| Surface | Base before (1280) | Corrected after (1280) |
| --- | --- | --- |
| Announcement | [Before](before/announcement-1280.png) | [After](after/s09a/announcement-1280.png) |
| Speaker states/help | [Before](before/speaker-edits-help-1280-viewport.png) | [After](after/s09a/speaker-edits-help-1280-viewport.png) |
| Archive | [Before](before/archive-1280.png) | [After](after/s09a/archive-1280.png) |

Visual findings resolved during this task: overly tall lanes at 768px, missing Announcement S/M letters, empty native player showing zero duration during preparation failure, weak disabled presentation, cramped closed source rows on mobile, and an offscreen skip-link capture artifact. Final review shows continuous desktop lanes, controls directly left of dominant waveforms, shared source ruler/compact transport, distinct selected/Solo/Mute/Excluded indicators, readable DSP labels and accessible mobile dialogs/menus. Playback and retained work are verified by browser assertions rather than inferred from still images.

## Limits and scope

The user's real Zoom M4A files (about 14.3 and 22 MB) were not provided or tested. Synthetic tracks are each 1:02:27 and about 12.44 MB; they verify the implemented path, not the unidentified cause on the user's exact bytes/device. Coverage uses Chromium with mobile viewport/touch emulation, not physical devices, Safari/Firefox or a manual screen reader.

Recovered implementation `d393aa4` plus recovery note `21fc901` preserve only the supplied patch; lost `52d5559` was not recovered. Further implementation is newly written in `2ac3ef8`, `9cee9fe` and `e0e4431`. DSP/core, codec/vendor, gateway/schema, source/recipe identity, transactions/integrity, workflows, Pages and infrastructure are unchanged. No merge, deployment, branch deletion, production mutations, Closure Record or COMPLETE declaration.
