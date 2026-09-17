# S10A requirement / evidence matrix

Status: implementation evidence only. This is not independent acceptance, production release, or proof of real iPhone Safari/ITP behavior.

| Requirement | Implementation evidence | Automated / visual evidence | Status |
| --- | --- | --- | --- |
| Login succeeds only after cookie replay | `AudioArchiveGateway.login()` performs login POST with CSRF capture disabled, then authenticated `GET /v1/session`; both portal entry points use `ArchiveAuthController` | Gateway client test covers POST 200 + replay 401 and successful replay | Covered locally |
| Distinct dual-cookie model | Gateway issues fixed host-only `__Host-meser_audio_session` (`Partitioned`) and `__Host-meser_audio_storage_session` (unpartitioned), both Secure/HttpOnly/SameSite=None and carrying one signed value | Auth tests cover attributes, identical values, either cookie, identical pair, conflicting pair, tamper, expiry, dual clear, Node multi-header adapter | Covered locally |
| First-party bootstrap and Storage Access bridge | Fixed gateway endpoints `/safari-bootstrap` and `/storage-access-bridge`; same-origin password form, fixed return action, exact frame ancestors, no-store/nosniff/no-referrer, versioned status-only messages | Gateway tests inspect CSP/header/content boundaries; `s10a_browser_smoke.py` covers explicit popup, deny, retry, grant, replay, exact parent origin/source behavior in Chromium/WebKit | Covered by deterministic regression |
| Shared auth state machine | `ArchiveAuthController` owns disconnected/checking/verifying/storage/bootstrap/grant/connected/denied/unsupported/error states for Archive and Editor | Screenshots `verified-login-390.png` and `storage-access-required-768.png`; focused Chromium/WebKit suite | Covered locally |
| Canonical prepared source batch | `prepareRemoteSourceBatch()` validates initial manifest, downloads authenticated parts, verifies each part and whole track, enforces 500 MiB, rereads canonical session, compares exact source fingerprint, and returns frozen ordered Files | Client tests cover multipart reconstruction, progress, corrupt bytes, abort, accepted metadata revision, rejected source change | Covered locally |
| Real progress, cancel, stale fencing | Verified byte/part progress feeds modal; each async boundary checks AbortSignal plus auth/source generation; cancel aborts and leaves prior context | `loading-progress-cancel-320.png`; Node abort test; browser source switch/reload generations | Covered locally |
| One batch reused by Announcement and Speaker | Selection commits one `preparedBatch`; Announcement maps the batch's exact File objects; Speaker receives `batch.files`; neither workflow reconstructs prepared sources | Full browser archive regression asserts Announcement → Speaker adds zero source-part GET; source uses reference equality when retaining processor files | Covered locally |
| Deep links and reconnect | Eligible direct links prepare before opening and remove intent only after editor handoff; deleted-source Speaker recovery retains its separate S09D path; 401/403 restart through verified auth | Full Chromium suite exercises direct Announcement/Speaker links, reload non-replay, deleted-source recovery and read-only request trace | Covered locally |
| Read-only selection/open | Preparation uses Session/part GET only; workflow reads remain GET; archive mutations remain behind existing explicit actions | Full browser trace assertion permits only GET plus session login while opening/reusing sources | Covered locally |
| Responsive and accessible states | Existing dialog/status semantics retained; fallback controls are buttons; loading cancel and bootstrap actions are keyboard focusable | `loading-progress-cancel-320.png`, `verified-login-390.png`, `storage-access-required-768.png`, `ready-integrity-reconnect-1280.png`; automated no-overflow/focus assertions at 320/390/768/1280 | Covered locally |
| Guarded production activation / rollback | Inert package builder, two-gate activation, captured prior image identity, checksum/source guards, health/header/cookie replay checks, automatic exact-image rollback, operator checklist | Shell syntax and repository tests; package is generated only after final commit | Prepared, not executed |
| Real iPhone/Safari gate | Requires separately authorized gateway activation and matching Pages deployment, retained-fixture read-only check, redacted device/runtime evidence and logout | No CODEX-stage production or device action | Intentionally unperformed |

## Visual evidence

- `tests/safety/evidence/s10a/loading-progress-cancel-320.png`
- `tests/safety/evidence/s10a/verified-login-390.png`
- `tests/safety/evidence/s10a/storage-access-required-768.png`
- `tests/safety/evidence/s10a/ready-integrity-reconnect-1280.png`

All screenshots use synthetic labels only and contain no password, cookie, CSRF token, session payload, or production archive data.
