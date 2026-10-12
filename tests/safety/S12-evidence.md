# S12 requirement evidence

This is the evidence index, not Stage closure. The PR body records the exact
checked HEAD and CI run for every row below. All fixtures are disposable and
synthetic. Production Archive mutations = **0**. Actual Zoom/App permissions,
key provisioning, production bundles/activation and real import are **NOT RUN**.
No repository/App was created; no production secrets/permissions/runtime were
changed. Merge/activation/restore authorization gates remain false.

Base: `abb64d92a01c3028aad67ef883661e1c26e98b98`; tree:
`5d1d0767a506a3d0e46e2db88b3c25758c8313d1`.
Branch: `codex/s12-zoom-cloud-import-audio-archive-settings`.

## Acceptance regression corrections

The acceptance review reproduced gaps in A03/A15/A18/A21 at `6d65455`;
the earlier PASS claims for those scenarios were incomplete. The PR records
the corrected exact HEAD and its new CI result. Added regressions cover:

- A03: search every paginated occurrence until a usable participant set is
  found; all ineligible/no-recording results allow tracks-unconfirmed activation.
  Auth, Meeting ID, permissions, recording API and download failures propagate.
- A15/A21: manual and Zoom ingestion after a successful DELETE with a lost reply
  remains `discarding`, advertises no finalize, and offers only discard in the
  canonical main UI. New Gateway instances complete discard after lost DELETE
  and final-commit replies without creating a Session/Release or requiring files.
- A18: one authoritative usage response renders both counter and warning;
  late responses cannot overwrite newer state. Browser tests reproduce 40 GB
  to 0 MB and back, then cross the actual configured threshold upward via manual
  ingestion and downward via source deletion without a reload.

All three engines exercise these UI corrections in addition to the existing
four-width matrix, with strict page errors and PNG/JSON evidence.

## Evidence references

- [Domain/API and fault injection](../../gateway/audio-archive/test/s12.test.mjs):
  encrypted settings/CAS/lost response; exact Zoom pagination; frozen plans;
  actual two-Gateway concurrent reservation, Release/part/publish/commit failures;
  original connection during active switch; missing/changed files; actual source
  deletion/purge; discard/finalize ownership; physical usage; old reader proof.
- [Real local HTTP stream](../../gateway/audio-archive/test/s12-stream.test.mjs):
  native sockets through the production HTTP adapter; exact bytes, backpressure,
  bounded queues, downstream disconnect → upstream abort, redirects/DNS/length.
- [Protected browser matrix](s12_browser_smoke.py): Chromium/Firefox/WebKit,
  320/390/768/1280; Los Angeles timezone with fixed October 2026 client clock;
  profiles/Check/Save, Moscow calendar, late month response, failed reply after
  successful canonical part write, tab close and a new context resume, duplicate
  filenames, stored part hashes, workflow links, soft limit exceeded import,
  Escape/focus return, overflow and strict page errors. PNG/JSON evidence is a
  CI artifact (`s12-browser-evidence`); it is not committed binary media.
- [Moscow UTC edge tests](s12_calendar.test.mjs).
- [Optional secret startup](../../gateway/audio-archive/test/github-config.test.mjs).
- [Recovery fixture](s12_recovery_fixture.mjs),
  [encrypted rehearsal](../../gateway/audio-archive/deploy/recovery/synthetic-recovery-rehearsal.sh)
  and [Docker restore](../../gateway/audio-archive/deploy/recovery/synthetic-docker-restore-rehearsal.sh):
  legacy/version-1 exact allowlists; actual AES decrypt after key destruction and
  encrypted recovery; CAS rotation/interruption; actual non-root read-only mount;
  exact images and Caddy runtime. No production material or Archive API writes.
- [API, schema, caches and compatibility documentation](../../gateway/audio-archive/S12-ZOOM-IMPORT.md)
  and [operator recovery/rotation gates](../../gateway/audio-archive/deploy/recovery/RESTORE-RUNBOOK.md).

## Requirement matrix

`PASS` below denotes completed synthetic/local repository validation.
`NOT RUN (CI pending)` must be replaced by exact-HEAD CI evidence in the PR
before reporting READY FOR ACCEPTANCE. No local Docker skip is a PASS.

| ID | Status at local handoff | Evidence/scenarios |
| --- | --- | --- |
| A01 | PASS | Browser creates a second profile in existing service session; settings DTO and single-active invariant |
| A02 | PASS | Domain Check creates no commits; invalid/edited credentials save but cannot activate; check binding rejects forgery/stale form |
| A03 | PASS | Actual ZoomClient no-sample branch, unconfirmed receipt/save/activation; sanitized auth/meeting/permissions/rate-limit paths |
| A04 | PASS | Old revision conflicts; committed-but-lost settings reply reconciles; empty credentials preserve; no secret in DTO |
| A05 | PASS | AES random nonce uniqueness, wrong key/tag failures, encrypted canonical bytes; optional key startup/legacy reads |
| A06 | PASS | Moscow month/day UTC edges; two same-minute occurrences; browser device timezone Los Angeles |
| A07 | PASS | Full Zoom pagination, UUID URL encoding; delayed October cannot overwrite November; connection/revision cache invalidation |
| A08 | PASS | Two distinct M4A/same filename, complete ordered set, stored bytes/part/whole SHA; 33 tracks/over 500 MiB/missing track rejected |
| A09 | PASS | `zoom_cloud` import link; actual Editor source preparation reconstructs both files through authenticated API; both workflow links; existing S10A/S10B regressions |
| A10 | PASS | Two Gateway/domain instances concurrently reserve the first occurrence with one key/Session identity; separate occurrence stays distinct; new browser context resumes same assets |
| A11 | PASS | Switch active during pending; download uses original account/revision; destructive credential edits/delete blocked |
| A12 | PASS | Failed part reply halts uploads; tab close/new context discovers canonical pending and resumes; native disconnect aborts real upstream |
| A13 | PASS | Changed hash/frozen plan and missing track rejected; accepted slots reused; all parts finalize while Zoom is unavailable |
| A14 | PASS | Actual lost reserve/part/finalize commits, Release create/publish failures, new Gateway objects; browser post-commit failed HTTP reply; no duplicate assets |
| A15 | PASS | CAS discard claim and staged-finalize ownership; actual source delete then purge; existing import identity returns deleted and never recreates |
| A16 | PASS | Fixed IDs/path/query guards; private/redirect/CDN-token/length checks; real backpressure and abort; safe DTO/upstream errors |
| A17 | PASS | 101 Releases/1001 assets pagination, drafts/orphans, dedup, two full stable scans, partial/moving failures retain dated complete total |
| A18 | PASS | Default 50 decimal GB/80% warns at 40 GB; browser changed threshold persists; over-limit second import succeeds |
| A19 | NOT RUN (CI pending) | Both legacy and S12 encrypted/Docker rehearsals configured; isolated actual decrypt, rotation/interruption and non-root mount require CI PASS |
| A20 | PASS | All 3 engines × 4 widths, keyboard/Escape/focus/live statuses, no overflow/page errors; running synthetic review preview |
| A21 | NOT RUN (CI pending) | Local Gateway/frontend/inventory/site/shell checks pass; exact HEAD Safety, pinned native toolchain, deterministic packaging, Compose/Caddy/recovery require CI PASS |
| A22 | PASS | Actual baseline validator accepts manual and rejects `zoom_cloud`; absent S12 capability blocks Zoom while manual works; explicit before/after-writes rollback matrix |

## Commands and local limits

```sh
python3 tests/safety/check_site.py
npm --prefix gateway/audio-archive run check
npm --prefix gateway/audio-archive test
node --test tests/safety/*.test.mjs
node service/tools/verify-frontend.mjs
bash -n service/tools/*.sh gateway/audio-archive/deploy/s10a/*.sh gateway/audio-archive/deploy/recovery/*.sh
git diff --check
node tests/safety/s12_preview_server.mjs 4185 http://localhost:4185
python3 tests/safety/s12_browser_smoke.py --base-url http://localhost:4185 --output /tmp/s12-browser-evidence
```

The complete existing public/S10A/S10B/mobile-waveform/Speaker browser commands
remain in `local-safety` unchanged. They passed locally on all requested engines.
One local concurrent S10A UI run lost its fixture session because the other suite
explicitly expires all shared sessions; its isolated rerun passed all engines.
This was a test-run orchestration issue, not an ignored page error.

Local full Gateway result: 151 PASS / 1 SKIP (152 tests). The skip is the existing
pinned native 3747-second fixture because the pinned container toolchain is not
available locally; the canonical pinned toolchain and realistic three-track load
run separately in CI. Frontend Node: 110 PASS / 0 SKIP. Inventory: 64 files.
Docker daemon and GNU Linux recovery toolchain are unavailable on this macOS
host; CI must supply those results. Playwright engines do not establish real
mobile-device acceptance or real account permissions.

Review preview: `http://localhost:4175/Audio-Archive.html`, password
`local-test-password` (disposable fixture only). Start command:
`node tests/safety/s12_preview_server.mjs 4175 http://localhost:4175`.
Its canonical storage is process-local and cannot access a real repository/token.
The separate 4185 test server can be reset by the browser suite; the review
server is left running. Preview artifacts and existing S11 tutorial artifacts
stay outside this commit. The PR/final report records checked SHA and tree state.
