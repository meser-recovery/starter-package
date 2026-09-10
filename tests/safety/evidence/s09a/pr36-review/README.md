# PR #36 preparation/deletion regression evidence

Reviewed base: `773975e402d083b860207629d20356e0d072e0e6`.
Implementation and capture SHA: `3927c9edbcaa175868b73130309d3d6d309aaadb`.
The next commit contains evidence only. Exact submitted HEAD and CI URL/result are recorded in draft PR #36 without changing that checked HEAD.

[Cause, correction and coverage gap](../../../S09A-PR36-review-fix.md). The previous audit PASS only covered deletion after ready. Prior screenshots/CI remain evidence for their original SHA, not this implementation.

## Regression

The real in-memory gateway and visible UI are used for all reads and deletion writes. Only completion of the first actual native audio decode is held. Version and series deletion must finish while preparation is still pending. On release, the editor must be ready with identical File objects, order, payload and source epoch, and the entire latest canonical session (including revision) must equal the gateway snapshot. Exactly one delete POST is allowed; no extra writes or production access.

The third scenario causes native and bundled decoder failure after the version deletion, checks the named error and visible retry, then requires explicit retry to reach ready with the same work and canonical revision. A metadata refresh cannot roll back revision or replace a source hash. The full suite retains close/new-source, decoder failure, post-ready deletion, authentication and late-response regressions.

The pre-fix browser reproduction failed exact epoch/File preservation: the full loader reopened the recording after the preparation identity check failed. Ready alone would have missed the defect.

## Validation

- `python3 tests/safety/check_site.py`; `node --check` for both changed frontend modules; changed Python syntax; `git diff --check 773975e`: [PASS log](static.log).
- `npm --prefix gateway/audio-archive run check`: [PASS log](gateway-check.log).
- `npm --prefix gateway/audio-archive test`: [80/80 PASS log](gateway-tests.log).
- `venv/bin/python -u -B tests/safety/browser_smoke.py --base-url http://127.0.0.1:8000 --screenshot-dir /private/tmp/pr36-review-final`: [complete PASS log](browser-full.log), including actual bundled WASM, all new scenarios and root/subpath CORS with default Chromium security.

## Captures

Seven original screenshots were visually inspected. They show the held preparation after deletion, ready completion for version/series, and named error/retry after decoder failure. No layout/style changes were made. The synthetic gateway fixture is 0.5 seconds long: a ready transport displays 0:00 at whole-second precision, while the track explicitly shows 0.5 s; pending/failed preparation shows unknown duration and hides the native player. Assertions, not screenshots, prove File identity, revision and write counts.

| Original PNG | Pixels | SHA-256 |
| --- | --- | --- |
| [preparation-decoder-failure-deleted.png](preparation-decoder-failure-deleted.png) | 1120 × 931 | `1cddae2c8fc6608c81acae8988c2a5d9f1b1b8d61cd231798506dba9464b282c` |
| [preparation-decoder-failure-ready.png](preparation-decoder-failure-ready.png) | 1120 × 937 | `bee3ae006aea1f749bb56ad038a47e73223a9378bf209dc537530483019f191d` |
| [preparation-delete-decoder-retry.png](preparation-delete-decoder-retry.png) | 1120 × 996 | `39082e18ef1f765aeafb51e4d18dff07637acd637875b922e69fc63c847feac7` |
| [preparation-series-deleted.png](preparation-series-deleted.png) | 1120 × 931 | `126dc02172bd89aa3136f19ab6de846a1f27eb2acc9c37f343a3172500b19524` |
| [preparation-series-ready.png](preparation-series-ready.png) | 1120 × 937 | `0f44729884f23248699bd096524591e72500a283628642d567ff521641a01675` |
| [preparation-version-deleted.png](preparation-version-deleted.png) | 1120 × 931 | `1cddae2c8fc6608c81acae8988c2a5d9f1b1b8d61cd231798506dba9464b282c` |
| [preparation-version-ready.png](preparation-version-ready.png) | 1120 × 937 | `0f44729884f23248699bd096524591e72500a283628642d567ff521641a01675` |

Real user Zoom files were not supplied/tested. Chromium and synthetic audio coverage does not constitute physical-device or full product Acceptance. No production mutations, merge, Closure Record or COMPLETE declaration.
