# S12 FIX — Zoom account/revision isolation

Repository implementation only. No merge or production activation. P0 containment remains open until separately authorized deployment and readback (O01–O03).

Base: `aea9f9580aafe8a0cd967d67178ea9223866d543`, tree `c1a3fabaacda4b639773ed0a7a26b3bbcb62488d`. Candidate: the commit containing this file; exact final HEAD, CI run and local result bindings are recorded in the PR and completion report.

## Implementation

- `ZoomArchive` derives authority from decrypted settings and the verified fingerprint. Calendar settings/imports/operation overlays share one immutable HEAD; rows and fallback require exact connection ID and connection revision. No active verified profile means an empty unconfigured calendar with no Zoom calls. Identity collisions exclude foreign details and fail closed without changing the existing dedup formula.
- Ordinary operation GET/reserve/plan/files/finalize and generic ingestion begin/upload/finalize validate active ownership. Async boundaries recheck authoritative context; mutations keep existing CAS. A settings revision change, including ABA, cannot authorize an old request's completion. The internal operation reader remains available to maintenance.
- Only the existing maintenance recovery entry can grant historical finalization, through an unexported internal capability. It verifies import/transaction/plan linkage, unique complete accepted parts, stored part and whole-file hashes, staged manifest, state and tombstones. No credentials or Zoom calls are needed for accepted bytes. Incomplete data stays incomplete; destructive settings guards and guarded discard remain.
- Protected UI clears calendar rows, selection and action closures on mutation/reload/close/auth invalidation. Calendar/import requests have cancellation plus generation/auth fencing through body reads, progress, success, error and finally. Focus observes settings changes without interrupting an unchanged import. Manual/device Archive editing and source playback retain their existing behavior.

## Acceptance evidence

`gateway/audio-archive/test/s12-isolation.test.mjs` supplies 49 checks (including nested state/fault/race cases); existing S12 assertions remain in `s12.test.mjs`. The contradictory test requiring A downloads and A fallback while B is active was replaced with refusal/isolation, same-context outage and original-file integrity checks. Separate maintenance tests preserve the all-parts recovery guarantee.

### ACCEPT blockers found at `589bb14` and corrected

- F1 (A03/A05/A06): holding the resolved immutable settings read across a real activation/disable previously allowed stale operation/calendar responses, old-profile metadata acquisition, or an asset upload before rejection. Settings reads now verify authority after the awaited read, including explicit historical refs. Bounded rechecks reject changed settings or unstable HEAD; unchanged settings permit unrelated archive commits while retaining the original coherent snapshot. Five deterministic barrier regressions fail on `589bb14` and pass with the correction, asserting 409, zero upstream calls and zero post-switch archive effects. An unrelated-commit regression remains successful.
- F2 (A09): pending file → expire synthetic session → Stop → warning configuration GET 401 previously retained rows, selected day and loading status. Warning errors now use the same generation-scoped expiry handler as ordinary UI actions and notify the existing Archive session clearing/reconnect path. Real browser regressions use native abort, require empty rows/day buttons/selection, hidden Stop, expiry status and working same-page login. A delayed old warning 401 after a newly confirmed login must preserve the new calendar. The observed-401 regression fails with the unchanged `589bb14` Zoom UI module; both cases run in every existing Chromium/Firefox/WebKit matrix.

These are repository/synthetic corrections. The prior ACCEPT FAIL is historical evidence; new exact-head CI and regression results are bound in the PR/completion report. This does not close operational O01–O03 or authorize activation.

### A14 WebKit blob URL follow-up

The automatic run on `8357858` failed S10B WebKit's existing page-error assertion for blob URL access control errors; later S12/packaging/recovery steps did not run. Tracing found a detached processor metadata audio element still holding `src` when synchronous `pagehide` revoked its track URL: cancellation only reached the promise's asynchronous `finally` cleanup. Processor operations now signal cancellation synchronously; metadata success/error/timeout/abort remove listeners, release the media source and clear the timer before settling. No error filter, browser skip, timeout relaxation, dependency pin, CI gate or DSP parameter changes.

The S10B browser suite adds a deterministic real-media barrier: hold metadata completion, dispatch `pagehide`, assert zero media consumers at every URL revocation, restore with `pageshow` and verify a fresh readable native audio URL, then cancel again. It fails the old runtime and passes the corrected runtime in Chromium/Firefox/WebKit. Existing page-error, outbound-request, source-transition, hash/identity, reconnect and geometry assertions remain. Final exact-head CI status is recorded in the PR/completion report; this paragraph is not a CI-success claim.

| Criterion | Evidence |
| --- | --- |
| A01 | Every durable state (reserved, bound, completed, discarded, effective deleted), available B rows, Moscow month exclusion, exact ownership and restart/ABA/collision cases. |
| A02 | Null/removed/unverified profiles produce empty unconfigured calendar without upstream calls; revised/foreign ordinary ingress refuses. |
| A03 | Warm/expired cache and restarted instance; same-context fallback, foreign outage rejection and list/recording barriers. Partial online rows are dropped on outage. |
| A04 | Stable opaque identity, same-account distinct connection collision, unchanged A returning after B, revised-profile rejection; no takeover or extra Session. |
| A05 | Real authenticated HTTP GET/reserve/plan/files/Zoom finalize and generic PUT/finalize, direct domain begin and forged recovery argument. Rejections assert unchanged canonical/storage effects and zero upstream calls. Existing 401/403/session tests preserved. |
| A06 | Two-instance barriers at list/recording/reserve CAS/lost response/bind CAS/release creation/download stream/upload listing/finalize bytes/publish/lost response. ABA during finalization refuses before further effects. Existing concurrent reserve/lost settings/assets/finalize tests preserved. |
| A07 | Restart with original credentials removed; actual maintenance resume/retry finishes accepted bytes without Zoom, ordinary finalize refuses and replay keeps one Session/Release. |
| A08 | Missing/corrupt/duplicate/aliased parts, whole hash, changed linkage/plan/staged manifest, tombstone and discarding/discarded faults reject without further effects. Existing CAS discard/finalize and lost DELETE tests preserved. |
| A09 | Real browser save/activate/disable/delete/reload/conflict readback; held calendar/file success/error and old finally cannot affect current rows/controller. Session expiry fences pending file. |
| A10 | Existing held month navigation plus ABA, focus external settings observation, reopen, detached old Open action, held completed reserve and successful new-account import. |
| A11 | Independent manual fixture keeps source, drafts, Speaker states, recipes, transactions, existing catalog entries and asset bytes exact across isolation and historical recovery. Existing S10A/S10B/S13 suites retained. |
| A12 | New HTTP/outage/recovery regressions run against archived base runtime: actual 200 instead of 409 and missing outage rejection; candidate passes. No weakened assertions. |
| A13 | `s12_browser_smoke.py`: Chromium/Firefox/WebKit, widths 320/390/768/1280, dialog/page overflow, Escape/focus/month/status, real import/recovery and held responses; page errors/unhandled rejections fail. Synthetic preview remains separate from production. |
| A14 | Required Node/site/frontend checks and exact-head PR `local-safety`, including existing packaging/Compose/Caddy/encrypted recovery/Docker rehearsal gates. Consult final CI result rather than treating a local test or a skipped production job as deployment proof. |

Local tooling limitations: one existing native waveform test requires explicit pinned FFmpeg/ffprobe paths and skips when absent; it was not changed. macOS encrypted rehearsal reaches synthetic create/rotate but BSD `find` lacks GNU `-printf`. Local Docker daemon is unavailable. Exact-head Linux CI must supply the existing toolchain/packaging/rehearsal evidence. No CI event gate is changed or dispatched manually.

## Read-only production inventory, distinct from synthetic PASS

Fresh read-only GitHub metadata inventory on 2026-10-26 matched the supplied handoff's canonical Archive revision. The complete tree was not truncated. Both old import records, their finalized ingestion transactions, completed purges, deletion tombstones and the related finalized publication transactions remain retained. Neither old Source Session belongs to the current catalog.

Both old Releases, both tag refs and all 11 known old source asset metadata requests returned 404. Complete current listing found one independent Release with five assets. No source asset bytes were downloaded. Absence in current storage does not prove erasure from Git history or backups.

The independent device Session remains available and is the sole catalog entry; its source, draft, seven Speaker-state and recipe blob identities remain unchanged. A fresh read-only settings GET observed the existing new active verified profile; no credentials were read and no profile was edited, checked by POST, activated or reset. A requested production calendar GET was rejected by automatic approval review as private recording/session data access; no bypass was attempted. Fresh calendar readback/effective old operation state is NOT_VERIFIED. Handoff calendar observations remain historical evidence.

A detailed sanitized audit with exact private IDs/revisions/blob hashes and host probes is retained in local scratch, outside the public PR. No participant filename lists, recording payloads, ciphertext, credentials, audio or private operational receipts are committed.

## S13 knowledge boundary and operational gates

Fresh fixed read-only host probes observed both Gateway and Caddy running with the accepted S13 source revision. This differs from the handoff's reported older Caddy. Exact container/image/mount identities are recorded only in the separate local audit. No secret contents were read.

Effective Compose/runtime files and retained S13 release directories were unreadable to the existing unprivileged account. Raw ledger/receipt, consumed scopes and the reported receipt hash could not be verified. Reported UNCONFIRMED smoke/stop is not changed to COMPLETE or KNOWN_FAILURE. Rollback image discovery does not establish usability or recovery input integrity. No operator/ledger files were edited or invoked.

O01–O03 remain pending/BLOCKED for separate operational authorization and reconciliation. Deployment must bind both backend guards and frontend invalidation, exact sources/images/mounts, authorization scopes and post-deployment inventory. Historical original activation, settings equality and restore/decrypt limitations remain unproven. This PR does not assert production fixed, P0 COMPLETE or S12 FIX CLOSED.

## P1 retirement analysis (no cleanup implemented)

Terminal dedup must retain enough exact identity to prevent a new Session for an old occurrence: opaque import ID, original connection/revision ownership, deterministic idempotency/transaction/Source Session linkage and terminal/deletion state. Current strict import/ingestion/publication schemas also retain occurrence UUID/time, title, participant filenames/file metadata, full frozen plans, part/asset descriptors, staged/output descriptors and recipe snapshots. Those fields need an explicit per-record retirement decision; hiding rows removes none of them.

Readers/dependencies include `validateImport`, `validateTransaction`, operation/calendar overlays, pending-connection guards, ingestion begin/upload/finalize, maintenance attention/recovery/discard, tombstones, lineage, catalog/read-model and restore/rollback tooling. Both related publication transactions must be assessed with their recipe/output provenance. Independent device data and its assets/states are excluded.

Unresolved: minimal terminal record/schema compatibility, linkage/integrity proof after retirement, retained recovery/rollback consumers and historical retention requirements. A future P1 plan needs exact before/after records, expected HEAD/revisions, dependency proof, CAS, rollback and post-readback approval. No schema migration, mass cleanup, new endpoint or history rewrite is supplied here.

Production Archive/settings/Zoom mutations=0; activation/rollback/restart/backup/import/merge=0. All writes/restarts in validation refer only to disposable local fixtures. Production gates and unrelated automation/assets are unchanged.
