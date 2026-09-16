# Audio archive storage repository bootstrap

These files initialize the separate public repository `meser-recovery/audio-archive`.

- `sessions/<sessionUUID>.json` is authoritative Source Session metadata.
- `catalog.json` is a derived listing and can be rebuilt from finalized session manifests.
- `drafts/<sessionUUID>/<workflow>.json` stores one current shared draft envelope.
- `project-states/<sessionUUID>/speaker/<draftRevision>.json` stores immutable explicit Speaker saves. A path may only receive an exact idempotent replay; individual states are never changed or deleted.
- `transactions/` stores recoverable ingestion, result-save, and `pending_delete` state.
- `recipes/<sessionUUID>/<workflow>/<outputUUID>.json` stores immutable finalized output lineage.
- `schemas/v1/` defines Source Session, draft, transaction, and Speaker project-state contracts. `schemas/v2/speaker-recipe.schema.json` adds exact project-state lineage while v1 recipes remain readable.
- Audio bytes must exist only as assets of the matching `audio-session-<sessionUUID>` GitHub Release.

Do not commit audio files, credentials, password verifiers, private keys, tokens, or private account data to this repository.
