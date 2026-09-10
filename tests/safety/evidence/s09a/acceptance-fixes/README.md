# PR #35 Acceptance repair evidence

Correction base: `396d1b734985ad6e352f0b451bb3647997ff8c41`.
Corrected implementation and exact screenshot/full-browser source: **`577c8cbabdf399ff086cad3a7aaa8ee2d764edb4`**. Captures and both passing browser logs below were generated after committing that source, with a clean working tree. This evidence-only update does not change runtime or test code.

See the [finding-to-regression mapping](../../../S09A-acceptance-fixes.md). Original S09/S09A captures remain historical evidence; their source SHAs are not relabeled.

## Passing corrected-code validation

- [Focused Acceptance browser regression](acceptance-browser.txt): exit 0; all three scenario groups passed, including delayed downloads, later edits, close/newer intent, save-and-continue lineage, Announcement session/draft/part 401 and 403, dirty rendered work, reconnect/cancel/retry, project-only auth expiry and late response after logout.
- [Full browser smoke](full-browser.txt): exit 0 at the exact implementation SHA above. Includes the new regressions plus existing native help touch/fresh CDP selection, local processing, save/reopen/retry, real FFmpeg, deletion/recovery, and root/subpath CORS checks with default Chromium web security.
- [Gateway tests](gateway-tests.txt): 80 passed, 0 failed, 0 skipped, run on the same gateway code (unchanged by this repair).
- Site contract, gateway check, all three changed JavaScript modules' syntax and `git diff --check` passed. Commands are in the repair record.
- Required PR `local-safety` for the final submitted evidence HEAD is tracked in the PR description with its exact SHA and run URL. A prior HEAD's passing run is not evidence for this new HEAD.

Commands used for the two post-commit browser runs:

```sh
venv/bin/python -B tests/safety/s09a_acceptance_smoke.py --screenshot-dir /private/tmp/s09a-acceptance-final
venv/bin/python -B tests/safety/browser_smoke.py --base-url http://127.0.0.1:8000
```

## Expected failures on the pre-fix source

Each scenario was independently run using the original three frontend modules from `396d1b7`, served from a separate loopback origin over the otherwise identical repository. All three processes exited 1 as expected. These logs prove reproduction and are **not** passing checks:

- [Delayed Speaker load](expected-baseline-delayed-speaker.txt): unsaved dialog never appears after editing during a held download.
- [Announcement authentication](expected-baseline-announcement-auth.txt): `Working File/Blob references changed` before reconnect can retain the active work.
- [Archive project authentication](expected-baseline-archive-auth.txt): reconnect status never appears after project-only authorization failure.

## Screenshots

All captures use a 390 × 900 CSS-pixel Chromium viewport; full-page heights vary. The explicitly named viewport capture shows the pending-transition dialog at readable scale. Visually inspected the dialog viewport and Archive reconnect capture; the browser regressions additionally assert retained File/Blob identity, valid downloads and exact montage/provenance, which screenshots alone cannot establish.

| Capture | Pixels | SHA-256 |
| --- | --- | --- |
| [announcement-draft-401-keeps-work.png](announcement-draft-401-keeps-work.png) | 390 × 8645 | `2baccb2e55e6734f95b7a6af9c6ba6aa980bd987974f909d3efec7f8ed640e8d` |
| [announcement-draft-403-keeps-work.png](announcement-draft-403-keeps-work.png) | 390 × 8645 | `2baccb2e55e6734f95b7a6af9c6ba6aa980bd987974f909d3efec7f8ed640e8d` |
| [announcement-part-401-keeps-work.png](announcement-part-401-keeps-work.png) | 390 × 8645 | `2baccb2e55e6734f95b7a6af9c6ba6aa980bd987974f909d3efec7f8ed640e8d` |
| [announcement-part-403-keeps-work.png](announcement-part-403-keeps-work.png) | 390 × 8858 | `69aff9f7e3f4e9cbb782bb621987b00009cd5e00b4431959a0dc267cdcc38ad2` |
| [announcement-session-401-keeps-work.png](announcement-session-401-keeps-work.png) | 390 × 6325 | `9c0022483353e158a42905f874f1f749a90cea09c2eeae80894922da2621ce79` |
| [announcement-session-403-keeps-work.png](announcement-session-403-keeps-work.png) | 390 × 6325 | `9c0022483353e158a42905f874f1f749a90cea09c2eeae80894922da2621ce79` |
| [archive-project-401-reconnect.png](archive-project-401-reconnect.png) | 390 × 1815 | `fe82bb950150394599b8fcb7e2c23338479a766c8e85ae24b780b1bbf449f3b3` |
| [archive-project-403-reconnect.png](archive-project-403-reconnect.png) | 390 × 1815 | `fe82bb950150394599b8fcb7e2c23338479a766c8e85ae24b780b1bbf449f3b3` |
| [closed-work-rejects-delayed-source.png](closed-work-rejects-delayed-source.png) | 390 × 5476 | `df923eeec6617209a7013216dc26bb34abc9c0009fd9ce4b781f34e3791e8014` |
| [delayed-source-new-edits-protected-viewport.png](delayed-source-new-edits-protected-viewport.png) | 390 × 900 | `3de6ba38b4c49f351eae2abc826e5b0cb7f7ab3fb784662e1b1fe4db6c3994fe` |
| [delayed-source-new-edits-protected.png](delayed-source-new-edits-protected.png) | 390 × 8657 | `0bd3887135b68a775e11b5101c9036696a9f25139188a963f334643f8cd44d11` |

Synthetic fixtures and the real in-memory gateway only; interception is installed before navigation and rejects unintended outbound archive access. No production writes, deployment or merge. Coverage is Chromium emulation, not physical-device, other-browser or manual screen-reader testing. This is implementation evidence, not an Acceptance verdict or stage closure.
