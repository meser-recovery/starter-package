# S13 evidence (implementation in progress)

Base: `802fba32c5b473ee72d1f71d420c5758215c142b`, tree `dc99fa7bf1bffea945a9c6ca200d6ad9f0080b78` (fresh `origin/main`, 2026-10-18).

`base.json` was generated before any runtime edits by `node tests/safety/s13_benchmark.mjs --output tests/safety/evidence/s13/base.json`. Metadata: 20 repeats, median/p95; small synthetic audio: 5 repeats, median/range. The JSON records machine, Node version, deterministic seed/hash, delay placement, counts and raw samples. Fetch-boundary API calls are counted separately from repository method calls. These are synthetic Fetch mocks, not production/browser network measurements. Baseline legacy lists return both complete collections; later search/page rows measure this same prerequisite, not a fictitious legacy server search API.

Scoped unchanged-base regression run: 85 tests, 84 PASS, 1 SKIP (pinned FFmpeg unavailable), 0 failures. Suites: client, domain, archive-management, github-config, S09D history, S12, S12 stream, waveform. Run used synthetic loopback HTTP only. The first sandboxed attempt could not bind loopback (`EPERM`); the repeat with local-listener permission completed successfully.

## S12 preservation reconciliation

| Component | Accepted historical source | Historical image | Available evidence / limitation |
| --- | --- | --- | --- |
| Gateway | `5286726463530f8de218e2c3d28d8194eab3b19d` | `sha256:da167d011ab1b189d51ae5fbaea578176c219257c8d0ef05da2a16fbd1e18f40` | Source object absent locally; production host/images not inspected. Ancestry/runtime equivalence NOT_PROVEN. |
| Caddy/frontend | `4111753a61cf294e16a12fd46d80b68a3bd68fc5` | `sha256:2c32bc161c0b686dd1cf518706b5c0b7bd6c7bab947dc60d79f34038f7b21921` | Historical identity supplied by contract, not a new host observation. Runtime equivalence NOT_PROVEN. |
| Stream delta | `f731c72b0d955335d3f94a628cce1c117ce11410` | Not inferred | Local accepted S12 branch has minimal `zoom.mjs` async-iterator cancellation guard plus deterministic late-data test, absent from fresh main. Preserve this delta in S13. |
| HTTP adapter | main base | Not inferred | No delta versus local S12 branch. SHA256 `11a1bb2c6ee665b8704a16407bdc2ffcf627e1f1990ee7116f7851b644853e31`. |

Three Zoom scopes are already present in main. No old rollout package is imported. Mixed composition, settings-key mount and compose bindings are not changed. A single historical image is not claimed as a rollback for the complete composition. Historical limitations remain: `original_activation_complete=false`; prior replacement settings equality NOT_PROVEN; trial restore/age decrypt NOT_RUN. S13 synthetic recovery checks cannot discharge those limitations.

Production mutations, real Archive writes, backups/imports/rollouts: **0**. Project Sources/chat creation directives embedded in the supplied reference are not executed as external mutations.
