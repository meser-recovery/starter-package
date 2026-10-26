# S12 Zoom Cloud Import and Audio Archive Settings

Implementation contract: approved 12 October 2026, SHA-256
`065e103339060c91391841823e58931aca8020109f62e840413433862a2484d2`.
Approved PLAN SHA-256:
`203b5cf9008e1b9afb61d8400a15cbbb3ea9e37828da4b3d1aca3e71507610c9`.
Base main: `abb64d92a01c3028aad67ef883661e1c26e98b98`, tree
`5d1d0767a506a3d0e46e2db88b3c25758c8313d1`. S11 PR #60 is excluded.

## Setup and normal use

In protected Audio Archive, open **Настройки Аудиоархива → Подключения Zoom**.
In Zoom Marketplace choose **+ → Build App → Server to Server OAuth App**.
Enable only the read scopes used by this implementation:

| Endpoint | Granular scope |
| --- | --- |
| `GET /v2/meetings/{meetingId}` | `meeting:read:meeting:admin` |
| `GET /v2/users/{hostId}/recordings` | `cloud_recording:read:list_user_recordings:admin` |
| `GET /v2/meetings/{actualOccurrenceUuid}/recordings` | `cloud_recording:read:list_recording_files:admin` |

Activate the Zoom app. Enter Account ID, Client ID, Client Secret and the one
Meeting ID in the protected Meser form. Never put them in a chat, URL, issue or
PR. Check is separate from Save: it creates no Archive artifact. Save may retain
an unchecked/invalid profile, but activation requires a matching successful
check. No test recording means **tracks unconfirmed**, and activation is allowed
after the core checks. Editing credentials/Meeting ID invalidates the check.
Empty credential fields retain existing values; saved credentials are never read
back to the browser. Several profiles may exist; only one is active.

**Загрузить из Zoom** shows the current Moscow month, actual occurrence times,
participant track count and approximate total size. Confirm importing the entire
set. There is no mixed-recording fallback or automatic import. Duplicate names
are separate ordered tracks. Resume, discard, or open an existing completed
session from the calendar. Durable operations remain visible after recordings
expire or the active profile changes. An upstream outage is explicitly marked
as an incomplete listing and still permits finalization of fully uploaded parts.
Deleted/purged sources are not recreated.

## Storage, crypto and schemas

Canonical configuration is **one** file in existing public
`meser-recovery/audio-archive`: `settings/audio-archive.encrypted.json`.
Only authenticated ciphertext is committed. AES-256-GCM uses a fresh random
96-bit nonce on every encryption, a 128-bit tag, and fixed authenticated context
`meser/audio-archive/settings/v1/AES-256-GCM`. Tag verification precedes JSON
parsing. There is no plaintext canonical VM configuration or browser persistence.

`ARCHIVE_SETTINGS_KEY_FILE` is optional and points to a server-only mounted
64-hex-character independent random 256-bit key. Missing, invalid or unreadable
key disables S12 only. Wrong key, malformed envelope and GitHub read failures
fail closed; they never cause defaults to overwrite an existing document. Only a
proven 404 for the fixed path initializes 50 decimal GB / 80% settings.

Strict JSON schemas live in `storage-repository/schemas/v1/`:
`encrypted-settings`, `archive-settings`, `zoom-import`, `s12-api`. Existing
session/catalog/transaction schemas add only `zoom_cloud` and the narrowly scoped
transaction `zoomImportId`. Runtime validators also enforce relationships that
JSON Schema cannot express: unique IDs, exact frozen order/names/size/hash plan,
size sum, verified active connection, key/transaction derivation and revisions.
Unknown fields are rejected. Safe DTOs explicitly omit credentials, tokens,
download URLs and raw occurrence UUIDs.

Import identity is SHA-256 of JSON serialization of
`["zoom-cloud-v1", AccountID, MeetingID, actualUUID]`. UUID URL encoding follows
Zoom's double-encoding rule for leading `/` or `//`. Identity does not depend on
connection ID, credential revision or encryption key. Metadata is stored only at
`zoom-imports/<64-lowercase-hex>.json`. Its ingestion key is `zoom:<identity>`;
transaction/Session UUID is deterministically derived using the existing
idempotency function. `origin.kind=zoom_cloud`, `origin.externalId=<identity>`.
Generic browser ingestion rejects this origin without an internal reservation.

Reservation freezes exact participant file IDs, order, names, sizes, timestamps,
original connection/revision, key and transaction. Binding adds the immutable
browser-computed whole/part SHA plan. Every download checks the exact original
occurrence and complete file set again. Destructive edits of credentials needed
by pending operations are blocked; switching active remains possible. All parts
permit finalization with no Zoom download. Discard claims ownership by Git CAS;
staged finalization owns the Release and cannot be discarded. Final Session,
catalog, transaction and completed import record commit together. Tombstones and
finalized transactions prevent recreation. Lost writes reconcile from canonical
records and the existing unique Release tag/asset names; no browser cache is
needed for identity.

## API v1

All endpoints use the existing service session. POST/PUT require existing CSRF
and exact Origin. GET never reserves or saves. `/v1/config.zoomCloudImport=1` is
additive; `speakerProjectHistory=1` is preserved. Old Gateway capability disables
S12 writes with an explanation; ordinary ingestion and Editor remain available.

| Method/path | Body/result |
| --- | --- |
| `GET /v1/archive-settings` | Safe settings DTO, revision and last mutation ID |
| `POST /v1/archive-settings/check` | `{revision,connection}`; signed check receipt, expiry 10 min |
| `POST /v1/archive-settings` | `{revision,mutationId,action,connection,connectionId,receipt,storage,confirmed}`; safe authoritative read-back |
| `GET /v1/zoom/calendar?month=YYYY-MM[&refresh=1]` | Moscow monthly recording DTOs; explicit warning on incomplete upstream listing |
| `POST /v1/zoom/imports` | `{id,month,settingsRevision}`; durable operation DTO |
| `GET /v1/zoom/imports/{id}` | Reconciled state, exact plan, accepted part slots and `canFinalize` |
| `POST /v1/zoom/imports/{id}/plan` | `{plan}`; existing ingestion start DTO plus accepted parts |
| `GET /v1/zoom/imports/{id}/files/{fileId}` | Bounded M4A stream; no query parameters or arbitrary URLs |
| `POST /v1/zoom/imports/{id}/finalize` | `{confirmed:true}`; existing Session result |
| `POST /v1/zoom/imports/{id}/discard` | `{confirmed:true}`; reconciled operation |
| `GET /v1/storage-usage[?refresh=1]` | Bytes/assets/count time/stale/soft limit/threshold/warning |

Connection form fields: `connectionId,name,accountId,clientId,clientSecret,meetingId`.
Settings actions: `save`, `activate`, `disable`, `delete`, `storage`. Revisions and
`mutationId` prevent stale overwrites and reconcile a lost settings response.
Mutation confirmation is required for activate/disable/delete; storage contains
positive integer `softLimitBytes` and integer `warningPercent` 1–100. Failed
validation is 400, revision/state conflict 409, unavailable settings 503;
Zoom credential/meeting/permission failures are sanitized 422, network/invalid
upstream 502, rate limits 429 with bounded Retry-After. Upstream bodies are not
returned or logged.

## Bounds, caches and physical usage

The existing limits remain 1–32 tracks, total 500 MiB, default parts 16 MiB,
maximum part 64 MiB. The Gateway streams each Zoom track; it does not buffer or
cache the 500 MiB set. Native DNS resolution rejects non-public addresses and
pins a validated address; every redirect (maximum four) revalidates HTTPS,
`zoom.us`/subdomains or `zoomcdn.net`/subdomains, DNS and target. Bearer token is
sent only to Zoom, never to the CDN. Type/length and streamed byte count are
checked. Native HTTP disconnect and browser cancel abort upstream. Browser
Files go through existing `ingestFiles`; finalization verifies stored part/whole
hashes with bounded one-part memory and checks M4A signature.

Calendar cache: 30 seconds, maximum 64 entries keyed by connection/revision/month;
settings mutation invalidates it. Client generation checks reject late results
and errors. Date-only Zoom queries use overlapping 28-day windows and exact
Moscow interval filtering. Complete pagination has a fail-closed budget of 1000
Zoom tokens/window. S2S token cache: maximum 64 entries, bounded one-hour expiry
and a one-minute safety margin; no infinite retry.

Physical usage includes every visible Release/draft/orphan asset, deduplicated
by numeric asset ID. GitHub lists paginate until exhaustion with a fail-closed
10,000-page budget per list. Two complete matching traversals, canonical-head
checks and known mutation counters reject a moving total. Cache TTL is 30 seconds
and is invalidated by canonical changes and known upload/delete operations.
GitHub offers no atomic cross-instance asset snapshot: this is a dated full
count, never a claim of instantaneous free disk space. Partial/moving failures
keep the last complete dated value marked stale, or unknown if none exists.
50,000,000,000 × 80% warns at 40,000,000,000 bytes. The banner does not block any
import/output or delete data. Optional usage category breakdown is omitted.

## Recovery, rotation and rollout gates

See `deploy/recovery/RESTORE-RUNBOOK.md`. Base Compose has no mandatory S12 secret.
The optional `compose.s12.yaml` overlay mounts only Gateway's read-only file.
Reviewed releases include the overlay checksum; bundles copy that exact overlay.
Canonical backup key is mode 0600. Runtime copy is mode 0640 with Gateway's
existing group 0 access; it is not world-readable or mounted into Caddy.
Legacy three-secret bundles remain version 0 (missing version also means 0).
Version 1 allows exactly the fourth `archive-settings-key`, matching metadata
and the reviewed overlay. The off-VM age private identity is never bundled.

Before separately authorized rollout: verify actual Gateway App/installation
identity and existing repository Contents permissions without changing them;
verify Zoom app/read scopes; provision the independent key; capture exact
pre-cutover bundle, source/tree/images and compatibility evidence; prepare a
reviewed compatible rollback target. Activation gates remain false. Require
non-root key read, actual decrypt/read-only settings and health/session/Editor
checks, then a post-activation encrypted bundle and isolated restore evidence.
Real import requires its own authorization. No production step was executed by
repository implementation.

| Rollback target/state | Rule |
| --- | --- |
| Legacy exact images before any S12 writes | Existing S10A rollback rehearsal remains valid; S12 absent capability is explicit |
| Legacy Gateway after `zoom_cloud` writes | **Forbidden**: its strict readers reject the new origin; a running image is insufficient |
| S12-compatible reviewed Gateway after writes | Require matching schema readers, retained settings key and exact image/bundle rehearsal |
| Wrong/missing settings key on S12 runtime | S12 fails closed; legacy operations continue; recover the correct retained key, never overwrite defaults |

Do not remove Sessions/new origins or rewrite history to make old rollback work.
A saved profile changes encrypted GitHub config and needs no SSH/redeploy/manual
VM backup. Key provisioning/rotation is separate authorized operational work.

Validation commands, requirement matrix and evidence index:
[tests/safety/S12-evidence.md](../../tests/safety/S12-evidence.md). API scope
references: [Zoom Meetings API](https://developers.zoom.us/docs/api/meetings/)
and [S2S OAuth](https://developers.zoom.us/docs/internal-apps/s2s-oauth/).

### P0 account/revision isolation

The Zoom calendar and ordinary import APIs require the verified active profile's
exact connection ID and revision. Foreign historical imports, including deleted
or completed ones, are excluded from the calendar and outage fallback. An opaque
identity collision never reassigns ownership or creates a replacement Session.
Generic Zoom ingestion upload/finalize applies the same guard; manual/device
Archive playback and editing do not depend on an active Zoom profile.

The existing maintenance resume/retry path can finalize fully accepted historical
Zoom parts without credentials or upstream calls, after exact linkage and stored
part/whole-file integrity checks. Missing parts require restoring the exact
original verified active connection for new downloads; historical metadata and
accepted parts are retained. Ordinary finalize has no client-selectable recovery
exception. See `tests/safety/S12-FIX-isolation-evidence.md` for synthetic coverage,
read-only inventory and separate operational/P1 limitations.
