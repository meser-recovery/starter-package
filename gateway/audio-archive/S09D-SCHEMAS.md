# Canonical Speaker project history contracts

The current gateway always exposes `/v1/config.speakerProjectHistory: 1`. Project history is not a rollout mode. It keeps one current Speaker draft and `speaker/v1`; the existing `draftRevision` is the only project-state counter.

## Immutable state

Each successful explicit save writes `project-states/<sessionUUID>/speaker/<draftRevision>.json` with schema version 1. The document contains the session/workflow identity, positive draft and Source Session revisions, save timestamp, normalized payload, complete ordered track provenance, and a server-computed SHA-256 `stateFingerprint`. The fingerprint is canonical JSON over `sessionId`, `workflow`, `draftRevision`, `sourceSessionRevision`, `payloadSchema`, `payload`, and `sources`; presentation-only fields and the fingerprint itself are excluded.

The current draft, new immutable state, Source Session/catalog update, and `transactions/project-save-<transactionUUID>.json` receipt share one Git commit. Replaying the same canonical request and idempotency key returns that state. Reusing the key with changed input or attempting different content at an existing revision conflicts.

## History and continuation API

- `GET /v1/source-sessions/<sessionId>/projects/speaker` returns summary metadata newest-first, including the current marker, source/editing availability, fingerprint, and linked recipe-v2 finals.
- `GET /v1/source-sessions/<sessionId>/projects/speaker/states/<draftRevision>` returns one fully validated immutable state.
- `POST /v1/source-sessions/<sessionId>/projects/speaker/continuations` accepts exactly one source intent (`sourceDraftRevision` or `sourceOutputId`) and an already ingested replacement Source Session.

Continuation verifies the complete replacement set by ordinal, size, and SHA-256, remaps every payload track reference, creates the target current draft and immutable revision 1, and writes both `supersedesSessionId`/`supersededBySessionId` references in one commit. Its transaction receipt makes completion retry-safe. It never restores bytes or changes a deletion tombstone in the old recording.

## Final recipe v2

`schemas/v2/speaker-recipe.schema.json` preserves every self-contained v1 field and adds required `projectState: {sessionId, draftRevision, stateFingerprint}`. A new final is accepted only when this link, the current draft/payload, full source provenance, Source Session revision, and local candidate all agree. Final save never creates a state. Deleting a final leaves its project state; full Source Session purge removes drafts, states, recipes, and owned storage under the existing purge contract.

Recipe v1 and existing `speaker/v1` records remain strict read-compatibility boundaries. They are verified, reconstructed, played, downloaded, and—where the accepted recovery contract permits—opened locally without rewriting stored history. They are never used for a new final or as a fallback write path. A browser connected to a gateway that omits capability version 1 blocks Speaker archive mutations with a visible incompatibility message while retaining local files, edits, and rendered output. Local-only work does not require an archive mutation.
