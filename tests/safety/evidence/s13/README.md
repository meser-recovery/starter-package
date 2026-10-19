# S13 implementation evidence

**Auth/attention follow-up:** see [FOLLOWUP.md](FOLLOWUP.md) and its source-bound browser/regression evidence. The paired measurements below describe the initial S13 candidate; they are retained as historical evidence. The follow-up supersedes auth-isolation and maintenance/strict-attention claims at the affected boundaries. Final exact-head CI closure is recorded in PR #63.

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

Three Zoom scopes are already present in main. The available local S12 branch also has meeting-ID whitespace normalization and guidance-copy deltas outside the minimal stream fix; these were not wholesale imported. Full branch/runtime equivalence is not claimed. No old rollout package is imported. Mixed composition, settings-key mount and compose bindings are not changed. A single historical image is not claimed as a rollback for the complete composition. Historical limitations remain: `original_activation_complete=false`; prior replacement settings equality NOT_PROVEN; trial restore/age decrypt NOT_RUN. S13 synthetic recovery checks cannot discharge those limitations.

Production mutations, real Archive writes, backups/imports/rollouts: **0**. Project Sources/chat creation directives embedded in the supplied reference are not executed as external mutations.

## Completed candidate and evidence binding

Measured runtime: `3278954fd03425d41ba2a69275aa86cb4f23cf44`, tree `df8c90a2294ee117c3d9de217f8667feb8fe7e83`. Through initial closure `7e0407f`, subsequent changes contained tests/evidence and one native-month focus-outline CSS fallback. The later auth/attention follow-up changes four frontend scripts; Gateway sources and reconstruction algorithms remain unchanged. Its source identity, new regressions and remeasured browser/Editor paths are recorded in FOLLOWUP.md. `provenance.json` records SHA256 for every changed runtime file and verifies unchanged-base files in the separate `git archive` checkout. Final PR HEAD/tree and its exact-head CI verdict are recorded in PR #63, not inferred from an earlier green run. This evidence is an implementation handoff, not acceptance or deployment authorization.

P1 removes hidden lifecycle/draft/history/recipe and maintenance/recount work from ordinary entry/list paths; optional attention and cached usage load independently. Detail reads the selected canonical manifest/current draft; history and output metadata are lazy. Projects in list summaries explicitly remain unverified until selected data is read.

P2 adds one shared immutable-HEAD read model for Archive and Editor, distinct validated summary/page types, global search/filter/sort before ten-item slicing, query/snapshot identity checks, single-flight builds/queries and reuse of unchanged validated blob identities. Cold rebuild remains O(N). The in-memory canonical snapshot budget is 10,000 records / 32 MiB; attention is separately bounded at 8 MiB. Invalid, missing or truncated canonical data fails closed. Existing write/recovery guards still obtain fresh canonical data.

P3 uses two global source-part slots across tracks, bounded readers, per-part and whole-track hashes and canonical File order. Cancellation drains a previous intent before new transfers, propagates through HTTP/domain/GitHub body reads, and rejects stale waveform completion before internal Editor ready. Warm reuse owns only the current batch through a WeakMap, confirms fresh access/manifests twice and invalidates on source/auth changes. Heavy decode remains sequential. Requested Editor readiness includes waveform/preparation; the overlay is not dismissed at transfer completion.

Consumer mapping: protected Archive and Editor use the protected client; public audiobook/editor consumers keep the existing public client interface. Only the common source reconstruction/reuse/read helpers are changed in both copies. Public client does not gain protected waveform/Zoom/binary endpoints, Zoom ingest validation or protected UI. No new protected asset was introduced: inventory remains 64. Meeting generator, scheduled workflow, Pages configuration, S11 and deployment files are unchanged.

## Paired measurements

All numbers below are local synthetic measurements, milliseconds. macOS 25.1 / Apple M1 / 8 CPU / 16 GiB; Node 24.7; Playwright 1.63: Chromium 153.0.8010.12, Firefox 155.0, WebKit 26.x (exact reported versions in JSON). Temporary Python environment only; repository dependencies unchanged. Runs are sequential base then candidate, without exclusive CPU reservation; other validation jobs can contend for the same host. No production/geographic SLA or universal speedup is inferred. Seed/hash, cache/profile, individual samples, API counts and bytes are in paired JSON. `summary.json` derives the selected rows.

Browser first useful means status loaded **and the picker and first card visible**. Complete refresh separately records the last API response end; `networkidle` waiting time is excluded. Twenty repeats per N=1/10/100/1000 per engine; median/p95. All-draft fixtures make lazy-read savings observable. Counts are separately measured at browser API and repository boundaries.

| N=1000 browser | First useful base → candidate (median; p95) | Warm list base → candidate (median; p95) |
| --- | --- | --- |
| Chromium | 1908 → 244; 2585 → 421 | 1892 → 46; 2438 → 63 |
| Firefox | 2013 → 264 | 1935 → 74 |
| WebKit | 2000 → 317 | 1941 → 49 |

Repository counters in the UI fixture, first useful through complete refresh: base 2,000 session reads + 1,000 draft reads, 2 listJson calls, 5 listReleases and 12 listReleaseAssets calls. Candidate: 1,000 cold session reads, **0 drafts/recipes/history, 0 listReleases/listReleaseAssets**. One lightweight transactions-only attention read remains; it is not the full incomplete/orphan scan.

| Isolated API N=1000 | Base | Candidate cold | Candidate warm/page/search |
| --- | --- | --- | --- |
| GitHub mock JSON requests | 2004 | 1004 | 1 HEAD |
| GitHub JSON bytes | 7,121,504 | 3,622,934 | 43 |
| Canonical session reads | 2000 | 1000 | 0 |
| Serialized list body | 2,269,817 | 5,351 (10 summaries) | 5,351 warm / 5,354 page 2 / 761 last match |

The isolated Node fixture differs from the all-draft UI fixture; those byte/count totals must not be combined. Old zero-delay Node page/search rows include the complete-list prerequisite. `network-base.json` instead measures the old **local search/page after its list is already loaded**; it is faster than a new server HEAD request. No claim of faster individual cached local search is made.

| GitHub JSON network model N=1000 | Cold base → candidate | Warm base → candidate | Page 2 base → candidate | Search base → candidate |
| --- | --- | --- | --- | --- |
| 10 ms + 10 MB/s | 11839 → 11247 | 12110 → 17 | 1.60 → 17 | 1.57 → 23 |
| 80 ms + 1 MB/s | 87072 → 85746 | 87842 → 82 | 3.13 → 83 | 4.15 → 87 |

Twenty isolated instances per case, each cold then warm; injected delay at every mock GitHub JSON response, no shared-link contention modeled. Cold O(N) remains dominant; its timing difference is not treated as a production improvement.

Realistic M4A: existing 3747-second AAC-LC fixture, three ordered tracks, 5,303,517 total bytes / 21 parts. Five repeats; medians with full ranges, no p95 from five samples. Native SHA verification is included.

| Verified transfer profile | Base median [range] | Candidate median [range] |
| --- | --- | --- |
| 10 ms + 10 MB/s | 946 [939–953] | 562 [547–659] |
| 80 ms + 1 MB/s | 7222 [7214–7225] | 4099 [3748–4919] |

Selected UI opening: three 8044-byte, 0.5-second deterministic WAV files; five repeats per workflow/engine at 10 and 80 ms per synthetic Gateway asset read. Below is the 80 ms profile. Warm batch is a second explicit selection in a separate fresh page, before opening an Editor; setup selection is excluded. Raw JSON includes all ranges and preparation-after-verification timings.

| Engine/workflow | Verified base → candidate | Interactive base → candidate | Warm verified base → candidate |
| --- | --- | --- | --- |
| Chromium Announcement | 597 → 395 | 848 → 662 | 611 → 114 |
| Chromium Speaker | 631 → 425 | 674 → 476 | 600 → 109 |
| Firefox Announcement | 712 → 366 | 994 → 621 | 653 → 76 |
| Firefox Speaker | 686 → 356 | 774 → 412 | 735 → 76 |
| WebKit Announcement | 592 → 339 | 632 → 377 | 579 → 44 |
| WebKit Speaker | 592 → 374 | 631 → 417 | 576 → 71 |

Cold batch bytes are identical (24,132); warm base downloads 24,132, candidate **0**. Maximum active transfers 1 → 2. Tiny-WAV Editor timing does not stand in for near-limit decoding or realistic M4A interactive time.

Server waveform is separately measured with actual Homebrew FFmpeg 7.0.2 and ffprobe (hashes recorded), not the pinned production container. Five cache-miss/hit cycles, three distinct-hash 3747-second M4As. Cold median base 4348 / candidate 4178 ms; warm 1.66 / 1.76 ms. This unchanged stage has **no claimed speedup**. Each cold generation reads 5,303,652 source bytes / 21 parts; hits read 0. Native concurrency remains 1, end jobs/temp files 0. Existing listener-count warnings occur in both local native runs; pinned CI is separately required.

## Resources, cancellation and actual validation

Near-limit input is 495 MiB total (three 165 MiB tracks), 16 MiB parts / 33 requests. Node independent whole-File SHA verification passes for both versions. Base peak sampled RSS 797,818,880 bytes; candidate 777,895,936. Candidate transfer 20,313 ms versus base 16,897 ms: this CPU/memory case did **not** improve. Base exposes no reorder-slot instrumentation (null, not zero). Candidate max active 2, reorder slots 2 / 33,554,432 bytes. General hard bound is 2 × validated part size, at most 128 MiB for 64 MiB parts; verified File data/runtime copies are additional and bounded by the existing 500 MiB session limit.

Actual Chromium/Firefox/WebKit each transfer, verify every byte of valid generated 495 MiB WAVs, cancel, retry and reuse with 0 warm part requests, 0 page errors/unhandled rejections and 0 active requests at end. Verified times 17.9 / 28.0 / 19.6 seconds; cancellation 0.5 / 1 / 2 ms. Synthetic source server RSS sampled peak 192,954,368 bytes. Chrome heap samples exclude Blob/native memory; other engines expose no reliable total heap metric. Full browser/native peak RSS is **NOT_MEASURED**. This is a source reconstruction boundary test, not 495 MiB FFmpeg/Editor decode. Independent readback hashes use 4 MiB File slices, the same read API used by the product. An exploratory File.stream readback failed in WebKit for composite Files; product does not use that API. Every byte of final slice readback is verified; no byte/error assertion is skipped.

Actual local checks on final runtime: Gateway **171 tests: 170 PASS, 1 SKIP** (pinned native container unavailable locally); Node safety **110/110 PASS**; check_site, npm check and protected inventory PASS. Public smoke, S10A auth/sidecar, S10A geometry/focus and S10B browser matrices PASS locally in all three engines. S12 final all-engine result is preserved in `s12-browser.json`: settings/scopes/calendar, lost replies/resume, cancel/recovery, both threshold directions, stale response ordering, keyboard Escape/focus and manual/Zoom lost-delete cleanup PASS. New ordinary-refresh-versus-explicit-recount regression passes. Source upstream abort is exercised through real loopback HTTP → adapter → app → domain → repository, including stalled body abort and retry. Zoom late data **and late error** after cancellation are deterministic regressions.

Earlier Linux CI runs failed the month-input :focus-visible assertion. Diagnostics show the native month control is focused but :focus-visible is false and its outline is absent in Linux WebKit. A product CSS :focus fallback now renders that month outline. The test requires actual focus, the applicable product focus selector and the same rendered 3px outline/offset/edge geometry; other controls still require :focus-visible. No engine, field or rendered-focus assertion is skipped. Final exact-head CI is a separate mandatory gate. Docker CLI is present locally but daemon absent, so local Compose/container restore is NOT_RUN. Existing CI must supply pinned FFmpeg/realistic three-track, all existing browser suites, deterministic packaging twice, Compose/Caddy and synthetic encrypted/Docker recovery. Production-safety remains SKIPPED on PR by the unchanged event gate. A green prior SHA must not be substituted for final HEAD.

## Acceptance evidence map

PASS below means implementation plus the named local synthetic/browser evidence, within the stated measurement limits. It does not assert physical-device or production acceptance.

| ID | Local result | Evidence |
| --- | --- | --- |
| A01 | PASS | `provenance.json`, paired node/network/browser/editor/waveform/resource JSON, unchanged-base baseline commit `07f65cc` |
| A02 | PASS | UI first/complete refresh counters; portal/editor entry assertions; lazy detail tests |
| A03 | PASS, follow-up updated | stalled attention does not block list, retained page/error state; independent maintenance/usage/history paths |
| A04 | PASS, follow-up updated | session-less transactions, malformed unknown, HEAD invalidation, fresh mutation/recovery guards; S12 matrix |
| A05 | PASS | read-model coalescing/blob-identity tests; warm 1 HEAD / 0 manifest reads |
| A06 | PASS | 1000-record differential/global filters/results/search, first/last/empty, max 10 summaries |
| A07 | PASS | stable tie ordering, query/snapshot mismatch reset, changed HEAD, invalid/truncated fail-closed tests |
| A08 | PASS | browser detail lazy history/recipes, deep links; existing S09D/S10B selected project/history/restoration regressions |
| A09 | PASS | no ordinary scans; explicit double scan/pagination/dedup; stale/error tests; S12 warning/recount races |
| A10 | PASS | multipart out-of-order overlap, stable byte identity/order; two slots in unit/realistic/browser resource |
| A11 | PASS, follow-up updated | wrong size/part/hash/whole hash/identities/reordered parts, auth loss incl. failed body cancel, changed/deleted source tests |
| A12 | PASS, follow-up updated | cancel/drain/new intent/pagehide/logout checks, real upstream abort/retry, Zoom terminal late-data/error tests; stale waveform caller regression |
| A13 | PASS, follow-up updated | authorized current-batch reuse 0 bytes; initial/final manifest/access and auth/source invalidation tests |
| A14 | PASS | separate transfer/preparation/interactive marks and actual native cold/hit counters; cold re-reads explicitly remain |
| A15 | PASS locally; final CI required | full Gateway + Node safety, S09D, S10A/B/S12 browser, timeline/provenance/render tests; pinned native gated in CI |
| A16 | PASS in paired models | warm useful list and realistic latency-bound transfer improve; UI readiness after waveform; unchanged waveform and slower near-limit case disclosed |
| A17 | PASS for source-transfer boundary | 495 MiB all-engine byte/hash/cancel/retry; hard slot budget; RSS samples. Total browser RSS/near-limit Editor decode NOT_MEASURED/NOT_RUN |
| A18 | PENDING final exact-head CI | PR #63 checks; local package/preview, public/protected checks; no gate changes |
| A19 | PASS for preservation; equivalence NOT_PROVEN | mixed identities above, minimal stream delta + regressions, http-adapter unchanged, production writes 0 |
| A20 | PASS | `delivery-research.md`, unchanged route/CSP/credentials/infrastructure; actual direct Release browser fetch NOT_RUN |

Physical Safari/Android, geographic users, real Archive/production timing, installed source/image equivalence, historical activation completeness and real trial restore/age decrypt are not proven by these local checks. No real credentials or recordings are included in evidence.

## Reproduction and review

Use a disposable checkout for the unchanged base. `git archive 802fba32c5b473ee72d1f71d420c5758215c142b` provides runtime; copy only synthetic harness/fixture/preview instrumentation for baseline measurement. Do not copy candidate runtime over it. `s13_benchmark.mjs --root BASE --sha SHA --tree TREE --realistic --output FILE` and `--metadata-network` accept explicit base identity; candidate defaults to current Git HEAD. Harness source comments describe fixture generation and delay placement.

Candidate preview: `MESER_S13_PREVIEW=true node tests/safety/s12_preview_server.mjs 4188 http://localhost:4188`. This owns process-local synthetic memory, no production credentials/Archive. Only loopback requests are permitted in browser performance harnesses. Run list and selected-editor harnesses on **different** preview ports to avoid fixture resets racing. `s13_browser_smoke.py --complete-refresh --repeats 20`, `s13_editor_benchmark.py` (5 repeats), `s13_resource_benchmark.mjs`, `s13_browser_resource_preview.mjs` + `s13_browser_resource_benchmark.py`, and `s13_waveform_benchmark.mjs` emit sanitized raw JSON. Resource tests generate bytes in memory/temp only. `s13_collect_evidence.py --input-dir DIR --output-dir DIR` aggregates repeated browser resource URLs by endpoint class, preserving exact counts/body/transfer bytes and per-phase timing samples; original input SHA256 is stored. Summed resource durations overlap and are not elapsed wall time.

Preview retained for review: **http://localhost:4188/Audio-Archive.html**, synthetic password `local-test-password`. Checked runtime equals `3278954` and final evidence descendant; final exact HEAD is in PR closure. Do not use this synthetic preview as a production replacement or reload a user page with unsaved work.
