# PR #35 — Acceptance corrections

Acceptance source: task “S09A · ACCEPT · Audio Editor & Archive UX Redesign”, four findings against `bd4d9d1a002d587b017eb77cc4a4deff3403eb94`. The three runtime defects were also present on the correction base `396d1b734985ad6e352f0b451bb3647997ff8c41`. Work stays on `codex/s09a-audio-editor-archive-ux-redesign`; no merge, production mutation or PLAN/MASTER/source updates.

## Findings and regression evidence

| Finding | Correction | Actual browser regression |
| --- | --- | --- |
| P1: a delayed Speaker load discards edits made while waiting; a delayed response reopens closed work | Remove the early-only confirmation and forced close. Keep the old work while fetching. Confirm the latest montage immediately before replacement and check request/auth generation again after the dialog/save. Closing work invalidates pending loads/retries; source changes and newer mode requests invalidate older loads. | Hold a real source-part response, edit and render the active project, release it, require the unsaved dialog, cancel and compare exact payload, session, File references, Blob reference, URL and epoch. Repeat with explicit close: a released response must leave the editor closed. A newer Announcement intent must win over the held Speaker request. |
| P1: switching/opening Announcement destroys Speaker before 401/403 | Prepare the manifest, draft, order, provenance and verified files in local variables. Do not clear the editor, result or active source until preparation and current-state protection succeed. Canonical mode switching uses this same path. | Inject both 401 and 403 at session, Announcement draft and source-part retrieval. Compare work/File/Blob/URL identity; cancel reconnect, reconnect and explicitly retry. Include an unsaved rendered montage and cancellation of the subsequent transition dialog. No data writes or auto-render during reconnect. |
| P2: Archive project requests swallow expired authorization and report success | Check rejected project fetches for 401/403 before projecting results. Reuse the existing authentication-error path, invalidating the view and exposing login instead of displaying a false loaded/unsupported-project state. Preserve list/auth generation fences. | Let initial lists succeed and fail only speaker draft retrieval with 401 and 403. Require the reconnect message, visible login, hidden logout, disabled refresh and “Проекты не загружены”. Login must restore the supported project list. A held draft response after logout must not restore projects or success status. |
| P2: required CI failed on the touch help check | Keep the existing native touch help and fresh CDP selection checks, including the previously corrected sequence. Include the new Acceptance regression module in the full browser suite. | Full local browser smoke and required PR local-safety on the corrected submitted HEAD. Earlier failures are retained as history; successful CI from an older HEAD is not reused. |

The transition guard also covers “Сохранить и продолжить” when saving advances the very source already fetched for reopening. The prepared revision is rejected, the new lineage is fetched while the current work remains intact, then the transition is attempted again. Regressions save/reopen the same Speaker project and compare its new cut, then save/switch to Announcement and compare rendered candidate provenance against the real gateway's current source revision.

## Test harness and before/after proof

[New regression module](s09a_acceptance_smoke.py) uses the existing real in-memory gateway bridge and synthetic audio fixtures. Interception is installed before navigation. Only the exact failed request or delayed response is injected; all other reads, logins, project writes, reconstruction and processing execute through the actual application. File and Blob identity checks use object references, not only filenames or sizes. Retained Blob URLs must still be fetchable. Read/reconnect scenarios assert no archive data writes; save-and-continue writes are explicit.

The three scenarios were independently run against the exact pre-fix frontend modules from `396d1b7`, served on a separate loopback port without altering the working tree. They failed as expected:

- delayed Speaker: no new unsaved confirmation after the held download was released;
- Announcement authentication: `Working File/Blob references changed`;
- Archive authentication: the required reconnect status never appeared.

The same regressions pass with the corrections. [Acceptance evidence](evidence/s09a/acceptance-fixes/README.md) records the exact corrected screenshot SHA, expected baseline failures, final passing logs and screenshots. Existing S09 and original S09A evidence are unchanged historical captures.

## Validation and scope

Commands:

```sh
python3 tests/safety/check_site.py
npm --prefix gateway/audio-archive run check
npm --prefix gateway/audio-archive test
node --check scripts/source-session-archive.mjs
node --check scripts/speaker-editor.mjs
node --check scripts/audio-archive.mjs
venv/bin/python -B tests/safety/s09a_acceptance_smoke.py
venv/bin/python -B tests/safety/browser_smoke.py --base-url http://127.0.0.1:8000
git diff --check
```

The new scenarios are part of the existing full local-safety browser command, alongside the touch help, source/project/output, S07 FFmpeg, S09 management and real root/subpath CORS checks. Exact results and final CI URL/HEAD are recorded in evidence and the PR. Gateway tests remain 80/80; no runtime/schema/DSP-core/infrastructure/Pages/workflow/data/audio/dependency changes accompany these corrections.

Browser coverage remains Chromium with synthetic/in-memory fixtures. No physical device, other-browser, manual screen-reader or production archive E2E claim is made. This document records implementation corrections, not ACCEPT or stage closure.
