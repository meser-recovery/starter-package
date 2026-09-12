# S09A implementation validation

Current PR #36 workspace follow-up: [local browser validation and preview](S09A-workspace-validation.md). Earlier reports below retain their original environment and source SHA.

PR #36 P1 follow-up: [deletion during preparation — coverage gap and correction](S09A-PR36-review-fix.md).

Current post-merge corrective work: [all 43 PLAN sections, §42 expectations and A01–A18](S09A-corrective-audit.md). See [new source-bound evidence](evidence/s09a/corrective/README.md). The PR #35 implementation and Acceptance repair records below are historical, not proof of this corrective result.

Current PR #35 Acceptance corrections and regressions: [Acceptance repair record](S09A-acceptance-fixes.md). The original validation below is historical evidence for its stated SHAs.

This is implementation/PR evidence, not ACCEPT, stage closure or production E2E evidence.

- Contract: `S09A-Implementation-Contract-Audio-Editor-Archive-UX-Redesign.md`, SHA-256 `8c2ece54e97839a7e31b7978c8d0adea2a56dac5a9a9f67c0bf370e865b19002`.
- Base: `240e9e5fc45661d815f4193597cc04451bb1bdf0`, current `origin/main` verified before implementation; no newer delta to reconcile. Unrelated open PR #4 was inspected and left untouched.
- Branch: `codex/s09a-audio-editor-archive-ux-redesign`.
- Final implementation/screenshot SHA: `884ef5345cdcc3049e58eb9b97f771a00a815388`. The later evidence-only commit is distinguished in the [evidence index](evidence/s09a/README.md). PR CI is recorded on the submitted HEAD in the PR, not inferred from historical S09 runs.
- The attached document's instructions to update Project Sources, create PLAN/ACCEPT chats or update MASTER are handoff instructions, outside the user's implementation-and-PR request. None were executed.

## Evidence references

- **N**: [s09a-project.test.mjs](../../gateway/audio-archive/test/s09a-project.test.mjs), real in-memory gateway: exact source binding, duplicate filenames/reordering, partial/uncertain writes, cancellation, changed targets, edits after failed saves, boundaries, project projection and part authentication errors.
- **B**: [s09a_smoke.py](s09a_smoke.py), real in-memory gateway through [bridge](archive_management_bridge.mjs): local processing, no-write traces, Speaker save/retry/reconnect, provenance, reopening, mouse/keyboard/touch and responsive UI.
- **E**: `check_source_session_archive` in [browser_smoke.py](browser_smoke.py): canonical source/draft/output flows, unsupported/missing data, Speaker edit/render invariants, failures, recovery and legacy access.
- **P**: `check_audio_processor` in [browser_smoke.py](browser_smoke.py): actual bundled FFmpeg processing, common silence, byte-exact passthrough, multitrack preview and processing, cancel/filesystem cleanup.
- **M**: [archive_management_smoke.py](archive_management_smoke.py) and existing gateway management tests: validated lists, simplified filtering, details, metadata conflict, output integrity, deletion, races and recovery.
- **S**: [check_site.py](check_site.py), frontend syntax, gateway check/test and full browser smoke including root/subpath CORS.
- **V**: [screenshot index](evidence/s09a/README.md), actual Chromium captures and visual review.

## All 43 PLAN sections

| PLAN | Implementation / preservation | Evidence |
| --- | --- | --- |
| 1 Stage purpose | Import → one editor → finished archives; product terminology replaces storage vocabulary. | B, M, V |
| 2 Stage boundary | Scoped vanilla frontend orchestration and CSS; no history, new backend, DSP or durable store. | Diff, N, S |
| 3 Navigation | Existing service entries and public URLs retained; redundant Editor management link removed; Archive links target specific sources/projects. | E, M, S |
| 4 Editor structure | Actual picker in collapsible Import; active editing dominates; result archives follow both workspaces. | B, V |
| 5 Import terminology | Normative title, explanation and same-Zoom-recording reminder; no inference from filenames. | HTML, B, V |
| 6 Import sources | Validated merged lifecycle lists; file name/format/size plus remove/add/replace. | B, E, M |
| 7 Local behavior | Both modes use File references; processing/preview/download have zero archive writes; source save explicit. | B, P, E |
| 8 Local Speaker project | Explicit combined source/project confirmation; hashed plan binds every local track to canonical identity; retained attempt on failure. | N, B |
| 9 Authentication | Exact reconnect message; login without reload; canceled/failed/repeated-403 handling; part errors retain status; guarded original-action retry. | N, B, E |
| 10 Mode chooser | Two explanatory modes and active-mode label. | B, V |
| 11 Mode visibility | Inactive workspace hidden and excluded from focus; result navigation independent. | B |
| 12 Visual direction | Controls beside waveforms on desktop, compact surfaces, source transport, responsive stacking. | V, B, P |
| 13 Track row | Source identity, duration, S/M, inclusion, per-track DSP and waveform. | B, E, V |
| 14 Track states | Selected label/outline; pressed Solo/Mute and whole-row styles; excluded text/dashed row; monitoring stays separate from mix. | B, E, P, V |
| 15 Help | Keyboard/touch disclosure with normative Solo/Mute/DSP/limiter explanation and compression levels. | B, V |
| 16 No Announcement draft UX | Manual draft controls removed; supported existing payload readable internally; exact lineage created only during explicit result save. | E, B |
| 17 Announcement workspace | Compact shared transport, tracks, process, statistics, result/player and save/download. Existing audio semantics retained. | P, E, V |
| 18 Speaker project concept | Project title, source/count/duration, explicit save and truthful saved/unsaved status. | B, E |
| 19 Project contents | Existing five-key speaker/v1 payload only; monitoring, view state and temporary Blob excluded. | N, B, E |
| 20 Current identity | Canonical reopen downloads exact tracks/current supported payload; missing/unsupported sources fail closed. | B, E, M |
| 21 Unsaved protection | Save-and-continue/discard/cancel for application transitions; failure stays in montage; browser beforeunload warning. | B, E |
| 22 Waveform interaction | Mouse and touch selection, keyboard extension, start/end/duration, contextual cut/silence; precision controls in disclosure. | B, E |
| 23 Recording boundaries | Derived leading/trailing global cuts, existing normalization and history; no new schema keys. | N, B |
| 24 Overlays | Global cuts, per-track silence, selected region, boundary labels and collapsible region list. | B, E, V |
| 25 Transport | One sticky source transport with applicable controls; separate post-cut result timeline; synchronized preview preserved. | B, E, P, V |
| 26 Speaker output | Explicit final render, waveform/player/duration/size/format, MP3 download, canonical candidate gate and archive save. | B, E |
| 27 Archive definition | Three product sections plus collapsed maintenance. | M, B, V |
| 28 Source records | Title/date/count/availability/lifecycle/project/output counts and contextual entry points. | M, V |
| 29 Lifecycle labels | Ready/removed-from-work-list language; explicit restore, unchanged lifecycle API. | E, M |
| 30 Source detail | Tracks, supported project/save time, two independent output groups, metadata and guarded actions; internals in diagnostics. | M, V |
| 31 Search/filtering | Filename/title search, three source sorts and three secondary filters; validated identity/revision merge retained. | M |
| 32 Speaker projects | Current supported speaker/v1 projection uses actual savedAt; no Announcement draft or historical revision presented as a project. | N, B, M |
| 33 Finished recordings | Independent collections, actual version/date/size, verified listen/download actions; no editor-mode switching. | B, E, M |
| 34 Playback | Existing part/full hashes and output/recipe validation precede Blob/player/download exposure. | E, M, N |
| 35 Deletion | Fresh dependency impact; ordinary-language consequences; non-cascade deletion; strengthened purge under Danger. | M, gateway tests |
| 36 Recovery | Associated operations on source rows; safe applicable actions; pending-delete cannot cancel and unknown states fail closed. | E, M, V |
| 37 Maintenance | Collapsed Archive-only catalog/orphan/transaction controls; exact rebuild label/help; explicit action. | M, V |
| 38 Archive style | Compact library panels, simplified search, secondary destructive controls and textual states; no waveform editor in Archive. | V, M |
| 39 Technical invariants | No gateway runtime/schema/DSP-core/infrastructure/workflow changes; immutable bytes, revisions, provenance and security retained. | N, P, E, M, S, diff |
| 40 Compatibility | Old canonical fixtures, internal keys, legacy edited-audio list/deep links and independent version histories preserved. | E, M, S |
| 41 S09B exclusions | No autosave, history, reattachment, missing-byte replacement, historical project restoration or new persistent schema. | Diff, E, M |
| 42 Acceptance expectations | All 24 expectations covered by the concrete A01–A18 mapping below; human ACCEPT remains separate. | Matrix below |
| 43 Operator model | Import/local processing/project save/reopen and library access form the approved operator flow; technical recovery remains secondary. | B, M, V |

## Concrete acceptance scenarios

| ID | Observed checks |
| --- | --- |
| A01 | B verifies colocated file controls, unified archive and zero write delta during local work; E tests explicit ingestion. |
| A02 | B renders both local modes before any write; downloadable Blob URLs exist with local Speaker identity lacking session/revision; P tests actual downloaded MP3 and passthrough bytes. |
| A03 | N/B use two different synthetic WAVs both named duplicate.wav, reverse order, exclude a track, add cuts/silence/DSP, save and compare mapped payload/source hashes. |
| A04 | B injects 503 after source finalization: exactly one source session, no draft, montage/epoch unchanged; subsequent retry saves revision 1 with no extra ingestion. N covers lost finalize/write responses and continued edits. |
| A05 | B injects 401 then repeated 403 at project save, cancels reconnect, fails password and reconnects successfully; compares payload/files/epoch and Blob URL. Part-download 401 reconnect safely retries the same verified output. N tests source part 401/403 and revision conflict; E/M retain stale-response/auth fences. |
| A06 | B verifies inactive DOM subtree has no visible focusable controls; result collection changes leave Speaker active. |
| A07 | E completes Announcement archive save without any manual draft; checks exact internal track order after explicit save. B/E assert local processing does not create source/draft/output writes. |
| A08 | B verifies dirty montage, monitoring-only clean state, cancel focus return, failed save-and-continue, successful save-and-continue and explicit close discard. E covers source replacement and existing save/render locks. |
| A09 | B reopens project with only GET requests and exact saved payload; E/M exercise unsupported drafts, deleted/missing sources and ineligible lifecycle without writes or file substitution. |
| A10 | B tests boundaries, silence, undo/redo, mouse after zoom/scroll, Shift+Arrow, CDP touch drag and reopened markers at four sizes. E covers cut region precision/removal and render-duration mapping. |
| A11 | B verifies selected/Solo/Mute/excluded state, touch-accessible help and unchanged montage under monitoring; E/P verify synchronized playback and independent result timeline. |
| A12 | N compares pre/post canonical graph and reconstructed bytes; P checks actual common-silence/mix output, passthrough byte equality and unchanged monitoring-only semantics; DSP core is unmodified. |
| A13 | B/M verify source/project/results navigation, actual project savedAt, simplified filters, independent workflow versions and collapsed maintenance. |
| A14 | E/M exercise good playback/download after lifecycle/source deletion, bad hash, malformed/wrong-workflow metadata and delayed responses with no unsafe Blob exposure. |
| A15 | M/gateway tests cover non-cascade version/series/source/purge impacts, stale metadata/dependency revisions, phrase guard and transaction gates. |
| A16 | E/M cover contextual recovery and maintenance, incomplete source/output transactions, unavailable local bytes, unknown/ambiguous state, noncancelable pending deletion and explicit rebuild. |
| A17 | B/M assert no whole-page overflow and visible primary controls at 320/390/768/1280; V includes both editors, Import, projects, help, states and dialogs, plus baseline desktop captures. |
| A18 | S/E/M retain public/service/deep links, old fixtures, source/result lineage, root/subpath CORS and legacy archive access. Diff excludes infrastructure/Pages/meeting automation/data/audio. |

## Validation and narrowly superseded assertions

Commands run from repository root (local Python with the existing Playwright environment):

```sh
python3 tests/safety/check_site.py
npm --prefix gateway/audio-archive run check
npm --prefix gateway/audio-archive test
node --check scripts/audio-project.mjs
node --check scripts/audio-archive-client.mjs
node --check scripts/audio-archive-core.mjs
node --check scripts/audio-archive.mjs
node --check scripts/audio-processor.mjs
node --check scripts/source-session-archive.mjs
node --check scripts/speaker-editor.mjs
venv/bin/python -B tests/safety/browser_smoke.py --base-url http://127.0.0.1:8000
git diff --check
```

Results and exact source capture are recorded in the evidence index/logs. Gateway: 80 tests, including seven new S09A tests. The full browser suite contains S09A and the original local gateway/root/subpath CORS, source-session, Speaker, processor and unrelated-site checks. Focused runs were used to diagnose failures, not substituted for the full suite.

Updated obsolete UI expectations only: old heading order/processor location → PLAN 4/6/11; manual Announcement draft button → 16/17 (replaced with stronger no-write/explicit-save lineage checks); lifecycle/workflow filters and overview counters → 29/31/32; maintenance/purge placement → 35/37; renamed listen/save actions → 26/34; precision/help disclosure and shared scrollbar position → 15/22/25. Tests open visible disclosures and act on current controls. No tests click removed hidden legacy controls. Ingestion mocks now return accepted-plan canonical descriptors so exact binding is tested. The real bridge supports binary bodies for actual gateway ingestion. Existing security, hash, recovery, DSP and output identity assertions remain.

During development, old text/DOM expectations failed; the shared scrollbar also required moving into the sticky Announcement transport so real pointer dragging remained reachable. A success message that disappeared with the ingestion dialog was exposed in Import. Partial-save tests found and fixed retry after later edits. These are development failures followed by correction, not relabeled historical passes. Historical `evidence/s09` and S09 validation records are unchanged.

## Compatibility and limits

Gateway runtime (`gateway/audio-archive/src`), strict schemas, Speaker DSP core, codec/filter parameters, vendor binaries, deployment/configuration, workflows, Pages, credentials, data and existing audio are unchanged. Only gateway tests were added/updated. No dependencies, services, migrations or production records were created. All writes in validation target the in-memory repository with synthetic audio; interception is installed before navigation and unexpected outbound archive access is asserted absent. PR creation/push are the only authorized external mutations.

Browser coverage is Chromium with desktop and CSS viewport/touch emulation. A physical mobile device, Safari/Firefox and manual screen-reader testing were not performed. Native semantics, live status, focus visibility/return, keyboard interaction and hidden-workspace exclusion were checked. No crash/reload durability is promised for unsaved local bytes; beforeunload uses the browser warning.

Boundary markers use existing leading/trailing cuts. To preserve an interior cut's identity rather than merging it away, crossing an existing interior cut is rejected with guidance to edit that cut first in «Правки». Single-source Announcement passthrough keeps original WAV/M4A/MP3 bytes and labels the download truthfully; actual encoded results use «Скачать MP3». List-level duration is omitted where the canonical output summary has no duration field. These preserve current data/DSP semantics rather than adding fields or transcoding.

No live production archive E2E, deployment, merge, branch deletion, VM change or production mutation was performed. No material schema/trust-boundary PLAN conflict was introduced. ACCEPT and any later authorized production validation remain outside this PR.

## PR CI follow-up

The first PR run on `bd4d9d1a002d587b017eb77cc4a4deff3403eb94`, [34466098987](https://github.com/meser-recovery/starter-package/actions/runs/34466098987), passed archive/CORS checks but failed the new immediate visibility assertion following a touch tap on the help disclosure. The test now waits for the required visible state after the same actual tap. No UI, touch action, assertion target, security rule or screenshot-source implementation changed. The failed run remains historical evidence, not a pass; the corrected submitted HEAD must obtain its own successful local-safety result.

The second run, [34467864208](https://github.com/meser-recovery/starter-package/actions/runs/34467864208) on `4ab3a93`, showed that waiting alone did not resolve the Linux touch sequence: the disclosure stayed closed. The corrected test exercises native help tapping before the low-level CDP drag, resets the selection before that drag (so an old selection cannot satisfy it), and emits touch targets on failure. Both actual touch checks remain required. The focused local sequence passed; runtime and screenshot-source files remain unchanged.
