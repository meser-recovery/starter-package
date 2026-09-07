# S08B Announcement storage contracts

All objects use `schemaVersion: 1`, reject unsupported fields, and use structural UUIDs plus lowercase SHA-256 hex digests. Existing S08A Source Session v1 records remain readable without migration.

## Shared draft

The existing draft envelope at `drafts/<sessionId>/announcement.json` uses `payloadSchema: "announcement/v1"`. Its payload is exactly `{ "trackIds": [<ordered track UUIDs>] }`. The list contains one to 32 unique source tracks. Draft saves use both expected draft revision and expected Source Session revision.

## Publication plan and job

The begin request contains the expected revisions, an idempotency key, and a plan with `outputId`, `blobId`, `processorVersion`, logical size/hash, ordered part descriptors, and a recipe template. Each part descriptor contains only `partNumber`, `sizeBytes`, `sha256`, and the canonical opaque `assetName`.

The persisted `publication` transaction additionally records its UUID, hashed idempotency key, immutable request fingerprint, workflow/session/output/blob identities, expected and reserved Source Session revisions, reserved version, Release identity, uploaded-part progress, completed recipe snapshot, optional finalized output descriptor, sanitized failure field, timestamps, revision, and state.

Allowed states are `uploading`, `cancelled`, `finalized`, and `discarded`. `uploading` and `cancelled` remain recoverable. Only `finalized` contains an output descriptor. A discarded version remains burned.

## Immutable recipe

`recipes/<sessionId>/announcement/<outputId>.json` contains:

- identity: schema/workflow/session/output/version/processor/timestamp;
- `sourceSessionRevision` and ordered sources with track/blob IDs, ordinal, size, hash, and media type;
- exact draft revision, schema, and ordered track payload;
- mode plus effective S07 detection/cut/mix/limiter/codec settings and intervals;
- result media type, safe presentation filename, size/hash, durations, and pause count.

Modes are `passthrough`, `processed_single`, and `mixed_multi`. Passthrough has no removal, mix, limiter, or codec and must match its one source byte-for-byte. Processed results use `libmp3lame` at `128k`; multi-track recipes record `amix=normalize=0` and `alimiter=limit=0.95:level=0:latency=1`.

The output descriptor keeps the established v1 shape and references this exact recipe path through `recipeSnapshotRef`. Deleting an Announcement version/series removes the corresponding recipe in the same canonical commit; deleting sources preserves finalized outputs and recipes.
