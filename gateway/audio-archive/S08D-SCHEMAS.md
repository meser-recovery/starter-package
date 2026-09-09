# S08D Speaker save and archive contracts

S08D extends the existing internal `publication` transaction record to `workflow: "speaker"` without changing Announcement records or routes. Product UI calls the operation saving to archive «Спикерская».

## Save plan and reservation

`POST /v1/source-sessions/<sessionId>/outputs/speaker/saves` accepts the expected Source Session and non-zero Speaker draft revisions, an idempotency key, and a strict plan. The plan contains deterministic output/blob UUIDs, `speaker-editor-v1`, whole-file size/SHA-256, ordered opaque multipart descriptors, and an immutable recipe template. Successful begin atomically increments only `workflows.speaker.nextVersion`; that number is never reclaimed.

Transactions remain under `transactions/publish-<transactionId>.json` for v1 storage compatibility. They expose the workflow, reserved version, accepted part slots, exact candidate fingerprint/size/hash, finalization capability, attributable failure phase, and timestamps. The `finalizing` and `discarding` claims make canonical finalization and destructive asset removal mutually exclusive and allow an interrupted discard to resume safely. Upload, cancel, finalize, and discard use `/v1/speaker-saves/<transactionId>/...`. Discard removes only uploaded assets attributable to the incomplete job and retains the consumed version.

## Immutable recipe

The strict runtime validator and `storage-repository/schemas/v1/speaker-recipe.schema.json` define the record at:

`recipes/<sessionId>/speaker/<outputId>.json`

It contains exact identity/timestamps; pre-reservation Source Session revision; non-zero canonical `speaker/v1` draft revision and normalized payload; ordered source track/blob/name/type/size/hash provenance; effective included/excluded/edit/processing state; the 48 kHz renderer, enhancement filters, actual first-pass loudness measurements, compression mappings, mix, limiter, and MP3 codec; candidate fingerprint; and exact result filename/type/size/hash/durations.

The recipe and output descriptor become visible together only after every stored part and the reconstructed logical file pass size and SHA-256 verification. Retrieval repeats per-part and whole-file verification through the authenticated gateway. Source deletion preserves Speaker output bytes, recipe, and verified playback/download. Version or series deletion removes only selected Speaker outputs, recipes, and assets while retaining the draft, source lineage metadata, deleted-version history, and monotonic counter.
