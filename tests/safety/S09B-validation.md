# S09B validation — unified Zoom-recording UX

The recording-detail layout and primary scenario are refined by `S09B-archive-ux-amendment.md`.

Implementation base: `70a9dfe7996d213ca57c5b897cb2d53419067e09` (`origin/main`).
Implementation screenshot target: `[IMPLEMENTATION_SHA]`. Evidence-only HEAD may be later.

The browser fixture uses `MemoryRepository`, generated audio and the real gateway/client/domain code through `archive_management_bridge.mjs`. Production gateway and GitHub archive traffic are blocked. The focused run observed 319 local gateway requests and no outbound archive access.

## Acceptance §54

| # | Implementation | Evidence |
|---:|---|---|
| 1 | One `Запись Zoom` row/detail is the product object. | `archive_management_smoke.py`: H1, row and detail assertions. |
| 2 | Incoming/removed lists merge by UUID and higher revision. | `s09b_unified_archive.test.mjs`: default-all merge test. |
| 3 | Archive has no primary project/result libraries. | Browser assertion that `#projects` and `#results` are absent. |
| 4 | Consolidated detail renders sources, Announcement, current Speaker project and Speaker versions. | `archive_management_smoke.py`: consolidated-detail assertions. |
| 5 | Work-list and source badges are independent. | Core vocabulary test plus detail/list browser checks. |
| 6 | Removed records remain in default all-record list. | Default list includes archived fixture; lifecycle filter checks. |
| 7 | Deleted sources retain output playback/download. | Source-delete and verified playback browser trace. |
| 8 | Speaker draft is loaded/validated by record ID. | `projectProjection` and consolidated-detail browser checks. |
| 9 | Workflow-owned output metadata and reconstruction stay separate. | Wrong-workflow identity tests and per-workflow lists. |
| 10 | Stored/deleted/reserved version numbers are rendered without compaction. | Deleted/reserved unit and browser assertions. |
| 11 | Recording-only search/filter/sort emits GET-only traces. | Combined-filter responsive loop and read-only trace assertion. |
| 12 | Editor default archive surface is an eligible-record picker. | `check_source_session_archive` picker assertions. |
| 13 | Editor picker exposes no delete/lifecycle/purge/rebuild controls. | Browser role assertions; management controls exist only in Archive. |
| 14 | Persistent `Текущая запись Zoom` distinguishes local/canonical state. | Editor DOM/runtime assertions and evidence index. |
| 15 | Device selection changes only local File state. | Retained S07/S09A browser tests; zero archive writes before explicit save. |
| 16 | Explicit source save retains plan/key and canonical identity. | Gateway S09A cancellation/response-loss/idempotency tests. |
| 17 | Local Speaker save reuses `ProjectSave`/`bindLocalPayload`. | Gateway S09A duplicate-name/reorder/exact-montage tests. |
| 18 | Source-finalized/project-failed displays canonical record plus unsaved local project. | Runtime state update before project write; S09A retry tests. |
| 19 | Announcement processing remains local until explicit save. | Existing processor browser trace and gateway publication tests. |
| 20 | Workspace activation keeps only one work surface active. | Existing Editor mode/transition tests. |
| 21 | Current record card remains visible throughout work. | `#current-recording` is outside both workspaces. |
| 22 | Editor versions filter by current record and active workflow. | `renderResultArchive` plus adapted browser counts. |
| 23 | Version/series deletion is present in Archive detail only. | Archive deletion browser matrix; Editor has no delete button. |
| 24 | Playback validates metadata, part order/size/hash and whole output. | Existing client/gateway integrity tests and corrupt-part browser case. |
| 25 | Lifecycle calls the unchanged `archive`/`restore` client actions. | Archive lifecycle browser trace and gateway regression. |
| 26 | Source deletion uses unchanged preview/revision/confirmation action. | Archive source-delete browser case and gateway deletion suite. |
| 27 | All four workflow version/series targets remain available. | Archive deletion target matrix. |
| 28 | Purge requires exact canonical ID and keeps tombstone behavior. | Purge challenge browser case and gateway tombstone test. |
| 29 | Recovery actions come only from `recoveryPolicy` after re-read. | Unit recovery test and contextual/maintenance browser cases. |
| 30 | Missing local bytes offer explanation/discard, never replacement render. | Recovery policy assertions. |
| 31 | Reconnect does not reload or clear File/Blob/montage state. | Existing S09A reconnect browser cases retained. |
| 32 | Retried writes re-fetch session/operation/revision. | `writeSession`, deletion and recovery traces. |
| 33 | Auth/list/detail/play/delete generations fence late responses. | Delayed response browser assertions and `RequestGeneration` tests. |
| 34 | Projection reads existing manifests; no migration exists. | No schema/domain/storage changes; full gateway suite. |
| 35 | Legacy edited-audio HTML/data/runtime are unchanged and pass safety checks. | `check_site.py` and legacy browser suite scope. |
| 36 | Announcement DSP modules and semantics are unchanged. | Existing processor Node/browser regressions. |
| 37 | Speaker DSP/editor modules are unchanged except surrounding orchestration. | 46 safety tests plus retained browser interactions. |
| 38 | Authenticated client reconstruction and exact-origin security remain. | Full 80-test gateway suite. |
| 39 | One dense recording list replaces three global collections. | 1280px focused screenshot/index. |
| 40 | Layout checks cover 320/390/768/1280 without page overflow. | Focused S09B browser run and responsive loop. |
| 41 | Headings, live regions, focus return and dialogs are asserted. | `check_site.py`, browser dialog/focus assertions. |
| 42 | Ordinary labels use the approved Russian vocabulary. | Static vocabulary contract and browser text assertions. |
| 43 | Parity map below locates every former capability. | Functional parity table and contextual-action tests. |
| 44 | Frontend/projection/test files only; no gateway runtime/schema/storage/security edit. | Git diff and full gateway suite. |
| 45 | Only an in-memory fixture was mutated; no production/infra/deploy action occurred. | Blocked outbound trace; repository diff. |

## PLAN §§1–59

Status: **I** implemented here, **P** preserved, **S** superseded definition/documentation, **O** explicitly out of scope.

| § | Status | Mapping |
|---:|:---:|---|
| 1 | S | Stage purpose executed by this PR. |
| 2 | I | Recording-centric Archive/Editor. |
| 3 | P | Existing canonical model and legacy viewer boundaries kept. |
| 4 | S | S09B naming/scope adopted. |
| 5 | P | Source Session model remains internal and unchanged. |
| 6 | I | Binding Russian vocabulary in HTML/runtime/errors. |
| 7 | I | Record-first, progressive disclosure, no hidden persistence. |
| 8 | I | Six scenario observations below; independent ACCEPT remains external. |
| 9 | I | Archive is record lookup/management/history. |
| 10 | I | Sole primary `Записи Zoom` collection. |
| 11 | I | Default merges both lifecycles once by UUID/revision. |
| 12 | I | Search, exact ID, quick/secondary filters and stable sorts. |
| 13 | I | Compact row and primary `Открыть запись`. |
| 14 | I | Consolidated record detail sections. |
| 15 | I | Lifecycle/source state separate. |
| 16 | I | Reversible work-list actions. |
| 17 | I | One current validated Speaker draft projection. |
| 18 | I | Record/workflow ownership enforced. |
| 19 | I | Canonical deleted/reserved versions shown explicitly. |
| 20 | I | Editor is picker/work surface. |
| 21 | I | Archive vs device source modes. |
| 22 | I | Eligible archive picker only. |
| 23 | I | Local file details and add/remove/replace retained. |
| 24 | P | Local process/download needs no archive auth/write. |
| 25 | I | Explicit source-save confirmation and safe ingestion. |
| 26 | I | Confirmed source → exact binding → project save sequence. |
| 27 | I | Partial save truth and remaining-step retry. |
| 28 | P | Announcement source/process/listen/save lineage. |
| 29 | P | S09A Speaker workflow and controls. |
| 30 | I | Two choices, one active guarded workspace. |
| 31 | I | Current-record/current-workflow versions only. |
| 32 | I | Validated Archive → Editor intent. |
| 33 | I | UUID-validated Editor → Archive detail intent. |
| 34 | I | Removed/deleted explanations and no hidden restore. |
| 35 | I | Title/date-only optimistic metadata editing with retained conflict form. |
| 36 | I | Contextual canonical recovery matrix. |
| 37 | I | Collapsed unassociated operations/observations/rebuild. |
| 38 | I | Six contextual deletion targets. |
| 39 | P | Source deletion retains independent results. |
| 40 | P | Exact-ID full purge/tombstone protection. |
| 41 | I | Reconnect state preserves local work. |
| 42 | I | Independent request generations and URL revocation. |
| 43 | I | Read-only trace assertions; rebuild explicit only. |
| 44 | P | No backend/storage extension. |
| 45 | P | Announcement and Speaker processing semantics unchanged. |
| 46 | P | Integrity, versioning, recovery and deletion guards retained. |
| 47 | P | Auth/CORS/CSRF/GitHub boundary unchanged. |
| 48 | P | Public URLs/subpaths/legacy deep links retained. |
| 49 | P | Legacy edited-audio viewer remains separate. |
| 50 | I | 320/390/768/1280 responsive rules/checks. |
| 51 | I | Semantic/focus/status/dialog regressions retained. |
| 52 | I | Functional parity table below. |
| 53 | O | Listed future/domain expansion not implemented. |
| 54 | I | All 45 expectations mapped above. |
| 55 | I | Automated operator walkthrough observations below. |
| 56 | I | Rendered evidence indexed under `evidence/s09b/`. |
| 57 | P | Preservation set covered by existing suites/diff. |
| 58 | I | Archive answers “what belongs to this recording”; Editor answers “work on it”. |
| 59 | S | Approved contract authorized implementation; merge/deploy remain prohibited. |

## Functional parity

| Old capability | New home | Regression evidence |
|---|---|---|
| Find any recording | Archive · all records | default/filter browser and unit tests |
| Open source for work | Editor picker / detail contextual action | Editor intent tests |
| Speaker project | Record detail + Speaker workspace | project projection/browser cases |
| Announcement/Speaker outputs | Record detail; current record in Editor | ownership/count/playback tests |
| Metadata/lifecycle | Record detail | conflict and transition tests |
| Playback/download | Record detail/current versions | integrity/corruption tests |
| Version/series deletion | Record detail workflow disclosure | all-target deletion matrix |
| Source deletion/full purge | Record detail Dangerous Zone | source/purge safety cases |
| Record recovery | Record detail | contextual recovery cases |
| Unassociated recovery/rebuild/diagnostics | Technical Maintenance | unassociated/explicit-only cases |
| Local processing/source/project/output save | Audio Editor | retained S07–S09A suites |

## Usability scenarios A–F

These are deterministic operator walkthrough observations, not a novice-user study; independent ACCEPT remains required.

- **A:** the default page presents one list; opening its primary action reveals source state, current Speaker project, both histories and edit actions without exposing backend terms.
- **B:** device mode labels the selection `Только на этом устройстве`; local processing remains enabled; only the explicit save action opens metadata/count/size confirmation and then changes the current-record card to canonical.
- **C:** an eligible record opens its current Speaker project; save/final version stays bound to that UUID and is found in the same Archive detail.
- **D:** the deleted-source fixture explains that new processing is unavailable while retained output listen/download remains enabled.
- **E:** `Требуют внимания` finds associated work; detail exposes only policy-approved finalize/discard/continue actions, and unknown states are read-only.
- **F:** Archive contains lifecycle/deletion/recovery/global histories; Editor contains selection, processing and current-record versions, with cross-links in both directions.

## Commands executed

- `python3 tests/safety/check_site.py` — PASS.
- `npm --prefix gateway/audio-archive run check` — PASS.
- `npm --prefix gateway/audio-archive test` — PASS, 80/80.
- `node --test tests/safety/*.test.mjs` — PASS, 46/46.
- `node --check` for each changed MJS module — PASS.
- `git diff --check` — PASS.
- Focused S09B in-memory browser smoke — PASS at 320/390/768/1280; 319 local gateway requests; no outbound archive access. The run covers the separate record screen, both primary intents and return to the preserved list state.
- Root/subpath CORS browser regression — PASS with default Chromium web security.
- Focused S09A replacement scenario — PASS. The former test clicked hidden legacy switch `#source-session-results-speaker`; the approved model now selects the saved-version panel from the currently open workflow. The replacement asserts that local-only work has no canonical history, results belong only to the current recording UUID, Announcement and Speaker histories remain separate, and verified playback/download are available from the active workflow.
- Corrective management scenario — PASS. Version/series/source deletion and contextual recovery now follow `Записи Zoom → Открыть запись`; an already-open Editor retains exact `File` objects, recipe, source epoch and result `Blob` across deletion, stale-revision and reconnect paths.
- Project-validation regression — PASS. A saved Speaker draft that is unavailable or fails projection validation no longer exposes `Продолжить обработку`; the Archive explains that the project was not validated and will not be overwritten.
- Full `browser_smoke.py` against a clean static test server — PASS: `Browser smoke suite passed.` The review preview is intentionally separate because it injects the local service-session marker for manual review.
