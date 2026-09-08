# S08C Speaker draft boundary

S08C adds only the current shared `speaker/v1` draft. It does not add Speaker output uploads,
versions, recipes, publication/finalization transactions, or archived playback.

The existing S08A envelope is unchanged:

```json
{
  "schemaVersion": 1,
  "sessionId": "<Source Session UUID>",
  "workflow": "speaker",
  "draftRevision": 1,
  "sourceSessionRevision": 1,
  "savedAt": "<ISO timestamp>",
  "payloadSchema": "speaker/v1",
  "payload": {}
}
```

`payload` has exactly these keys:

```json
{
  "trackIds": ["<all current source track UUIDs in editor order>"],
  "excludedTrackIds": [],
  "globalCuts": [
    { "regionId": "<UUID>", "startSeconds": 1.25, "endSeconds": 3.5 }
  ],
  "trackSilenceRegions": [
    { "regionId": "<UUID>", "trackId": "<track UUID>", "startSeconds": 8, "endSeconds": 9.75 }
  ],
  "trackProcessing": [
    { "trackId": "<track UUID>", "enhancement": "off", "leveling": "off", "compression": "off" }
  ]
}
```

The gateway accepts at most 10,000 normalized regions in each region array and at most
900 KiB of UTF-8 JSON for the serialized payload. This stays below the existing 1 MiB request-body
limit; S08C does not raise that global limit. Region times are finite, ordered, positive, and serialized
at microsecond precision. The gateway checks exact keys, UUIDs, enums, all-track coverage, subsets,
normalization, and current Source Session track identities. The browser additionally checks decoded
source duration bounds before save and render.

Existing `announcement/v1` envelopes, routes, records, and recipe validation are unchanged. Legacy
opaque Speaker drafts remain readable for storage compatibility, but a new Speaker save must use
`speaker/v1`; the editor fails closed instead of overwriting an unsupported legacy Speaker draft.
