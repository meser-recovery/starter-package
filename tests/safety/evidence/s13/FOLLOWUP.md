# S13 auth / strict-attention correction

Requested follow-up to initial closure `7e0407f2836981d3321d636bf8cf164526f56078`, on the same `codex/s13-audio-archive-editor-performance` branch and PR #63. No production mutation, real Archive write, backup/import/rollout or merge.

Runtime: `f2d4c91ee938803f168e99562947554649d93d97`, tree `d5cc89b6212ef9e3f77f89b7a8d5ef1da929ab18`; auth/core correction commit `71a0ee2cca88dc1d6509fed866d2630849f63eec`. Final evidence-only descendant and its exact-head CI verdict are recorded in PR #63. `provenance.json` includes every affected script SHA256 and per-measurement source binding.

## Corrected behavior

JSON, protected binary waveform and source-part response paths capture the gateway auth generation before issuing the request. They check it before interpreting the response and after asynchronous body reads. A stale response is discarded with `AbortError` / `stale_auth_response`, its body is cancelled and it cannot invalidate the newer generation or expose an old `401` to that generation. Late successful binary data is also rejected. Late login POST/replay and logout completion cannot replace or clear a new CSRF. The Editor reconnect wrapper checks both its UI sequence and gateway auth generation.

A genuine current `401` still clears CSRF, advances the auth generation, aborts source preparation with the original `401` reason and invalidates verified-batch reuse. Binary `401` aborts immediately before reading an error body. The generation is checked again after delayed error-body reads/cancellation, so a login that occurs during cleanup is protected. Positive tests verify cancellation and required re-download after a new login, not merely that old failures are ignored. Public and protected clients share these guards; protected binary endpoints remain absent from the public client.

Maintenance renders actionable attention and diagnostic observations independently. Attention pending/error/invalid data stays unknown; the diagnostic result is still shown. Diagnostics preserve independent loading/error state when attention completes. Diagnostics' lenient `transactions` are never substituted for strict attention. Both explicit buttons (maintenance refresh and main list refresh) issue a fresh strict attention read rather than joining an older in-flight GET. Ordinary compatible reads retain default coalescing; the explicit bypass is a client option, not a new endpoint or query parameter. Existing immutable-HEAD strict server validation/cache and fresh mutation guards are unchanged.

## Deterministic regressions and actual checks

`gateway/audio-archive/test/s13-auth-generation.test.mjs`: **25/25 PASS** on corrected clients. The same test file against an isolated `git archive 7e0407f` client snapshot yields **23 FAIL / 2 PASS / 0 cancelled**. This is intentional red-baseline evidence, not a candidate failure. Gates control response/header/body/cancel completion explicitly; no sleeps determine request ordering. Covered boundaries:

- Old JSON / binary / source-part `401` after successful new login: new token and generation survive, new preparation remains un-aborted, its verified batch still reuses with zero source downloads.
- Genuine current `401`: abort and reuse invalidation remain active; next authorized selection re-downloads instead of reusing invalidated ownership.
- Delayed JSON error body, login POST/replay, logout completion, successful binary body and delayed error-body cancellation cannot affect the replacement session.
- Binary current `401` aborts before delayed JSON-body completion; error-body cancellation failures retain the original current `401`.
- Explicit attention reads issue a second request before the old read is released; ordinary identical reads still share.

S12 browser matrix adds real-UI deterministic routes in Chromium/Firefox/WebKit. With attention held, diagnostics are visible. A newer canonical session-less transaction is shown after explicit refresh while diagnostic `transactions` deliberately remain empty. Late empty attention is ignored. Strict `503` and malformed success both remain unknown rather than zero; diagnostics stay visible. A diagnostic error survives later attention completion. Main list refresh also bypasses the held older attention request. All engines keep page-error and unhandled-rejection checks; no existing assertion or workflow gate is removed.

Full local Gateway retry: **196 tests, 195 PASS, 1 SKIP** (pinned container unavailable locally); Node safety **110/110 PASS**. Site validation, Gateway syntax and protected inventory **64 files PASS**. Public browser smoke PASS. S12 all-engine matrix PASS, including previous settings/calendar/import/storage/recovery/focus cases. `followup-checks.json` preserves actual summaries and log hashes; `s12-browser-followup.json` preserves the browser results. One initial local full run stalled in the unchanged native-timeout test and was terminated; isolated waveform immediately passed 11/12 with the pinned case skipped, then the complete retry passed. No unrelated native code was changed.

## Evidence scope

`browser-candidate-followup.json` repeats the complete list/first-useful matrix on runtime f2d4c91: 20 repetitions per N=1/10/100/1000 per engine, visible first card required, complete refresh tracked independently. `editor-candidate-followup.json` repeats five cold/warm selected-record cases per workflow, engine and 10/80 ms per-asset profile. Editor measurements used 71a0ee2; every Editor-loaded changed script is byte-identical at f2d4c91. Base data, fixtures, browser versions, host/cache and fixed delay profiles are the same as the initial paired measurements. No exclusive CPU reservation is claimed; these are local synthetic models, not geographic or production measurements. Resources are compacted by the existing collector with `--followup`; individual timing samples and request/body/transfer counters remain intact.

Gateway/read-model/strict server paths, waveform, source reconstruction, hashing, two-slot queue and batch preparation helpers are byte-identical to the previous closure (algorithm hashes verified in provenance). Their existing Node network/native waveform/495 MiB resource evidence is retained as historical evidence rather than relabelled as a new run. The changed auth failure/reuse and strict-attention boundaries are validated by the new tests and repeated frontend paths above. Physical Safari/Android, production timings, total browser native RSS and installed S12 source/image equivalence remain unproven/NOT_RUN, as before.

A02/A03/A04/A07/A11/A12/A13/A15 are updated by these regressions and source-bound evidence. A18 is closed only by the final exact-head `local-safety SUCCESS` in PR #63; the old `7e0407f` green run is not reused. Production-safety stays SKIPPED on PR by unchanged workflow gates.

Preview: http://localhost:4188/Audio-Archive.html, synthetic password `local-test-password`. Existing server remains running; static frontend serves the corrected scripts. Actual list, maintenance disclosure and explicit refresh were checked in a separate temporary browser tab, then that tab was closed. The user's existing tab was never reloaded. A manual refresh loads the updated code. Final source SHA is the evidence-only descendant of f2d4c91 recorded in PR #63.

## Repeated frontend results

Milliseconds, same unchanged base. Browser N=1000: median (p95). Complete refresh and request/byte counters remain available separately in raw/summary JSON.

| Engine | First useful base → follow-up | Warm useful base → follow-up |
| --- | --- | --- |
| chromium | 1908 (2585) → 233 (246) | 1892 (2438) → 51 (57) |
| firefox | 2013 (2852) → 269 (294) | 1935 (2437) → 90 (118) |
| webkit | 2000 (2049) → 297 (308) | 1941 (2025) → 53 (61) |

Selected UI, fixed 80 ms synthetic per-asset read delay: median, five repeats; complete ranges and preparation-after-verification are in `followup-summary.json`. No p95 is inferred from five samples.

| Engine / workflow | Verified base → follow-up | Interactive base → follow-up | Warm verified base → follow-up |
| --- | --- | --- | --- |
| chromium / announcement | 597 → 378 | 848 → 640 | 611 → 123 |
| chromium / speaker | 631 → 379 | 674 → 429 | 600 → 130 |
| firefox / announcement | 712 → 372 | 994 → 629 | 653 → 97 |
| firefox / speaker | 686 → 374 | 774 → 431 | 735 → 93 |
| webkit / announcement | 592 → 339 | 632 → 378 | 579 → 45 |
| webkit / speaker | 592 → 329 | 631 → 365 | 576 → 57 |

All repeated matrices passed. Ordinary first/complete list still has zero full maintenance/Release scans and zero hidden drafts/history/recipes; only the separately requested lightweight attention read remains. Selected warm batch keeps zero source asset bytes with fresh access/source confirmation. These measurements do not establish an absolute SLA or production speedup.
