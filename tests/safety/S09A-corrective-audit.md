# S09A corrective audit after PR #35

This records implementation verification, not ACCEPT, a Closure Record, or S09A COMPLETE.

**2026-09-10: UI acceptance reopened by the user.** The historical PASS entries below
do not accept the current interface. Selection/tool placement, overlapping controls,
and the distinction between per-track Mute and suppression by another track's Solo
remain subject to browser verification and user review. See
[the new toolbar correction and its explicit validation limits](S09A-selection-toolbar-review.md).

Current follow-up: [shared DAW workspace iteration](S09A-workspace-iteration.md).
The current [workspace validation](S09A-workspace-validation.md) and its source-bound evidence supersede historical browser/CI attribution. User Acceptance remains open.

PR #36 review follow-up: the previous D PASS covered deletion **after ready**, not during preparation. See [the discovered gap, correction and new browser regression](S09A-PR36-review-fix.md).

- Base: `5a3e793e6e33e1a15e27dd6408e733c87d9a939f` (`origin/main` rechecked before work). The only open PR was unrelated #4; its branch/content was not changed.
- Branch: `codex/s09a-editor-corrective-ux`.
- Corrective handoff SHA-256: `c95bfe10226fa3527d132f877e32b9b643dccaf09401968a44e995ff532386b4`.
- Approved full contract SHA-256: `8c2ece54e97839a7e31b7978c8d0adea2a56dac5a9a9f67c0bf370e865b19002`; read including all 43 Appendix A sections. Its historical main/approval/chat-transfer instructions do not replace this corrective task.
- Recovered patch SHA-256: `502d2314d744521e08d71dbc8f0d8a20492aceb8c7c047d03616005fad6587fa`. Applied once on the confirmed base: implementation `d393aa4`, recovery documentation `21fc901`. The implementation's stable patch-id is `6f530202525ea9fe2ef515118d79068499e52aaf`, matching the handoff. These recover `95d902f`'s change and the recovery note only. Lost `52d5559` code was **not** recovered; subsequent corrections below are newly written.
- Exact final implementation/capture SHA, separate evidence commit and submitted-HEAD CI are identified in the [new evidence index](evidence/s09a/corrective/README.md) and draft PR. Original S09/S09A evidence is historical and remains unchanged, apart from navigation links in the S09A index/validation document.

## Verification sources

- **C** — [s09a_editor_corrective_smoke.py](s09a_editor_corrective_smoke.py): actual bundled FFmpeg/WASM generates synthetic M4A/MP3, exercises native decode failure, decoder-load failure/retry with the same Files, all three local formats, local processing/download, close during decoder load, two 1:02:27 M4A tracks avoiding native PCM decode, cut/undo, selection validity/track identity, DSP/region focus, scroll retention and lane geometry at 320/390/768/1280.
- **D** — [s09a_corrective_management_smoke.py](s09a_corrective_management_smoke.py): real in-memory gateway; stale/failed/unsupported draft projection, fresh detail read, keyboard contextual menus, changed dependency preview, expired deletion consent, version removal with exact montage/File/Blob/download preservation, unsaved source deletion, stale revisions, unknown counts and a delayed source deletion versus newer work.
- **B** — [s09a_smoke.py](s09a_smoke.py): local-to-canonical binding, partial save, reconnect, exact saved payload/reopen, local renders, monitoring/selection/help and responsive screenshots.
- **R** — [s09a_acceptance_smoke.py](s09a_acceptance_smoke.py): retained PR #35 delayed-load, 401/403 session/draft/part, newer-intent/close, save-and-continue lineage and logout-race regressions.
- **E/P** — source-session and audio-processor checks in [browser_smoke.py](browser_smoke.py): prior source/project/output/DSP/preview/byte identity/recovery/integrity checks and actual bundled S07 processing.
- **M** — [archive_management_smoke.py](archive_management_smoke.py), also run through the existing root/subpath CORS regression with default Chromium security: metadata conflict, UTC date, lifecycle, playback integrity, version/series/source/purge, incomplete operations and malformed/stale data.
- **G/S** — 80 gateway tests; site contract, changed JavaScript/Python syntax and whitespace checks. No gateway runtime/schema/fixture mutation in production.
- **V** — actual source-bound screenshots in the new evidence index, including baseline desktop captures served from exact base `5a3e793` and corrected captures. Visual review is recorded separately from browser assertions.
- **Diff** — scoped comparison against the base. `scripts/speaker-editor-core.mjs`, gateway runtime/schemas, vendor/codec files, production workflow jobs, Pages/infrastructure/configuration, audio/data and unrelated content are unchanged. `audio-processor.mjs` retains the timeline/fit corrections and now adds shared custom transport and truthful monitoring labels; its DSP code is unchanged. The local-safety job adds the five transport tests.

## Current workspace verification overlay

The 43-section and 24-expectation mapping below is retained. The full suite
re-executes B/C/D/R/E/P/M for the new workspace; current source SHA, captures and
exact-head CI are linked above. New evidence extends these specific rows:

| PLAN / §42 / contract | Current additional check |
| --- | --- |
| §§4,10–13,17,25; §42.6/11/21/22; A06/A17 | Shared source transport, all inactive audio paused, preserved separate result player, aligned lanes at four widths and short viewport; unchanged 210/150px desktop thresholds |
| §§14–15,25; §42.9/10/13; A11/A12 | Native 330/660Hz signal/RMS for each Mute/Solo, multiple Solo, volume, reordered identity, Exclude versus final MP3; touch/keyboard DSP and readable heading contrast |
| §§22–24; §42.12/22; A10/A17 | Exact selection scope, drag-time overlay, global cut/local silence, history and a touch hit target below expanded sticky transport |
| §§27–38; §42.14–20/22; A13–A17 | Short-screen top-layer menus, resize into mobile flow, Escape/focus/outside click; all prior canonical management and preparation/revision cases rerun |
| §§39–41; §42.24; A18 | No DSP/core/storage/auth/production changes. The only workflow delta adds local transport tests to local-safety; production jobs and permissions remain unchanged. AGENTS adds the requested permanent preview rule. |
| §§42–43 | Automated implementation verification is recorded separately from pending user visual/listening Acceptance. |

## All 43 PLAN sections: requirement → implementation → correction → evidence → status

The status column is an implementation verification result, not a human Acceptance verdict. Browser evidence is never inferred from code reading.

| § | Requirement and current implementation | Defect/correction or verified invariant | Test / screenshot | Status |
| --- | --- | --- | --- | --- |
| 1 | Import → active editing → finished recordings | Preserve the three-zone flow; replace remaining oversized lanes/library cards | B, C, D, V | PASS checks |
| 2 | S09A UX scope; no new audio backend/history | Only vanilla frontend, tests and evidence; recovered vs rewritten changes distinguished | Diff, S | Diff verified |
| 3 | Preserve URLs/service entries; contextual Archive links | Native action disclosures retain source/workflow-specific editor URLs | M, S, D | PASS checks |
| 4 | Import above dominant workspace, results below | Picker stays in Import; selected Import collapses; compact source lanes dominate desktop editor | B, C, V | PASS checks |
| 5 | Normative source explanation and same-Zoom reminder | Retained exact Import copy; duration mismatch now also explains one Zoom recording | E, B, C | PASS checks |
| 6 | Unified archive/device sources, file details/add/remove/replace | Validated merged lists retained; unknown result counts use “—”, never false zero | B, D, E | PASS checks |
| 7 | Local MP3/M4A/WAV editing with no hidden upload | Sequential native/FFmpeg preview; long M4A bypasses full native decode; explicit source save blocked while Speaker is unprepared | C, B, P | PASS checks |
| 8 | Explicit local source+project persistence | Existing exact source/track binding, partial-save retry and unchanged current payload retained | B, G, R | PASS checks |
| 9 | Reconnect preserves local work and safe intent | Expired lists/projections cleared; login rereads lists; no automatic destructive consent replay | R, B, D | PASS checks |
| 10 | Two explicit editing modes | Existing copy/actions retained; long/unsupported-native sources prepare in both modes | B, C, V | PASS checks |
| 11 | One visible, keyboard-reachable workspace | Inactive workspace remains hidden; ready/error/retry transitions keep active mode honest | B, C, R | PASS checks |
| 12 | Compact audio workspace, waveform central | Continuous lanes, desktop control panel left, shared ruler, readable controls; recovered excessive 768px lane height fixed | C geometry, V before/after | PASS checks |
| 13 | Control panel beside waveform | Readable labeled DSP rows; waveform > half lane width and fills its height on desktop | C, V | PASS checks |
| 14 | Distinct normal/selected/Mute/Solo/excluded states | S/M pressed indicators retained; selected label, dimmed waveform and separate excluded label/border | B, E/P, V | PASS checks |
| 15 | Keyboard/touch help and readable DSP labels | Exact accessible DSP names; focus survives rerender; native help disclosure remains keyboard/touch operated | B, C, V | PASS checks |
| 16 | No Announcement draft UI | Existing internal announcement/v1 lineage unchanged; no visible manual draft step | B, E, Diff | PASS checks |
| 17 | Announcement sources/process/player/stats/save/download | Shared compact transport/ruler/lanes; actual local processing/download retained | B, C, P, V | PASS checks |
| 18 | Speaker project identity/save truth | Named preparation error retains rows/Files/payload; unknown duration shown as unknown; unprepared work never marked saved/ready | C, E, B | PASS checks |
| 19 | Persist render state only | Payload schema, monitoring-only state and render identity preserved; error/retry does not substitute files | B, C, E, G, Diff | PASS checks |
| 20 | Current source/project identity and canonical reopen | Supported current draft must actually be read; no stale successful detail projection after failed/unsupported fresh read | D, B, R, E | PASS checks |
| 21 | Save/discard/cancel protection | Retained even for unprepared source replacement; source deletion protects montage before consent; delayed replies cannot close newer work | B, R, D, E | PASS checks |
| 22 | Waveform selection primary, precision secondary | Cut/silence disabled for empty/out-of-range selection; summary names selected track and updates with selector | C, B, E, V | PASS checks |
| 23 | Compatible start/end markers | Existing leading/trailing global cuts and Undo/Redo preserved; actions unavailable before preparation | B, C, G | PASS checks |
| 24 | Global cut, per-track silence, selection and boundaries | Geometry survives zoom/scroll/resize; DSP rerender retains scroll; region controls retain logical keyboard focus | C, B, E, V | PASS checks |
| 25 | One compact sticky source transport | Existing sync/drift/rate/volume/follow behavior preserved; shared ruler follows actual viewport; result uses separate timeline | E/P, B, C, V | PASS checks |
| 26 | Final render, compact player, MP3 save/download | Final DSP/render graph unchanged; result waveform also uses decoder fallback; local Blob survives archive/auth/version-delete operations | B, C, D, E | PASS checks |
| 27 | Source/project/finished Archive plus secondary maintenance | Three sections retained with actual current draft projection; no DAW controls in library | D, M, B, V | PASS checks |
| 28 | Source rows with truthful state/counts | Compact rows and text badges; currentDraft reference alone no longer earns “saved project” | D, M, V | PASS checks |
| 29 | Product lifecycle terminology | Ready/removed labels retained; restore remains explicit, read-only links do not mutate lifecycle | M, E, Diff | PASS checks |
| 30 | Source detail with tracks/current project/results/metadata | Fresh session+draft read; actual savedAt only; explicit “Сохранить название и дату”; UTC/conflict behavior retained | D, M, V | PASS checks |
| 31 | Simple title/file search and secondary filters | Search/sort/filter semantics preserved; controls kept compact and accessible | M, D, V | PASS checks |
| 32 | Supported current Speaker projects only | Failed/unsupported draft has no continue button/save timestamp; clear projections on auth/list/detail replacement | D, R, M, G | PASS checks |
| 33 | Independent finished collections | Real versions/date/size and workflow identity retained; menus contain target-specific version removal | B, D, M | PASS checks |
| 34 | Verified playback/download | Integrity and ownership checks unchanged; compact library player after verification | M, E, B, V | PASS checks |
| 35 | Non-cascade contextual deletion with fresh consent | Removed Editor target-switching radios; version/series/source/purge actions tied to target; preview/revision/incomplete reread before write; source work protected; purge remains reinforced in Danger | D, M, E, G, V | PASS checks |
| 36 | Contextual, fail-closed recovery | Allowed server actions preserved; auth/operation state rechecked; no advice to manufacture missing result bytes; late state cannot revive old work | M, E, D, Diff | PASS checks |
| 37 | Collapsed technical maintenance | Catalog/orphan diagnostics remain Archive-only; exact help, explicit rebuild; no production maintenance | M, B, S, V | PASS checks |
| 38 | Dense media library, badges, menus, compact player | Native keyboard/touch action disclosures, Escape focus return, secondary destructive controls, 44px mobile targets | D, M, V before/after | PASS checks |
| 39 | Audio/storage/security/infrastructure invariants | Final-render DSP/core/codec, identities, recipes, transactions, integrity, CORS/CSRF and unrelated files unchanged | G, E/P, M, S, Diff | PASS checks |
| 40 | Existing canonical/legacy compatibility | Existing fixtures/deep links/legacy audio paths retained, no production migration | E, M, S, Diff | PASS checks |
| 41 | S09B excluded | No history, autosave, restore-old-state, exact-source reattachment or new persistence | Diff | Diff verified |
| 42 | All 24 expectations | Explicit mapping below; synthetic browser implementation evidence does not replace human acceptance | Mapping below | PASS checks |
| 43 | Understandable operator workflow | Local source → either editor → explicit save; current project/library/recovery flows all remain available | B, C, D, M, V | PASS checks |

## PLAN §42: all 24 expectations

| Expectation | Evidence / concrete check |
| --- | --- |
| 1 Device import obvious | B Import screenshots and colocated picker; C actual local file setup |
| 2 Archive import obvious | B/M unified source list and contextual entry points |
| 3 No silent upload | B/C isolated local preparation/render/download; write traces |
| 4 Explicit source saving | B combined confirmation and exact ingestion; E explicit source save |
| 5 Reauth preserves work | R/B/D exact File/Blob/montage/download identity |
| 6 Modes cannot coexist | B/C hidden inactive subtree and explicit mode |
| 7 No Announcement draft UX | B/E complete result-save lineage without manual draft |
| 8 Project terminology | B/D supported current project and truthful failed/unprepared status |
| 9 Solo/Mute/Exclude distinct | B/E monitoring invariants and V states |
| 10 Accessible DSP help | B native touch/keyboard disclosure; C exact labels and focus |
| 11 Central waveform/timeline | C geometry at four widths and V desktop before/after |
| 12 Editing through new UI | C/B/E selection/cut/silence/boundaries/history/precision |
| 13 Processing semantics preserved | E/P actual WASM output checks; G; unchanged DSP diff |
| 14 Archive product sections | D/M/B section headings, supported projects and independent outputs |
| 15 No normal technical lifecycle labels | M/E UI and preserved internal keys |
| 16 Simplified search/filter | M responsive search/sort/filter checks |
| 17 Integrity retained | M/E canonical playback/download, bad hash/stale metadata rejection |
| 18 Actual deletion impact | D/M/G changed-preview/revision/pending/consent and non-cascade checks |
| 19 Contextual recovery | M/E associated incomplete operations and available policy actions |
| 20 Technical controls secondary | M/B collapsed maintenance, explicit rebuild |
| 21 Dense desktop | C/D geometry and V matching base/corrected desktop captures |
| 22 Usable mobile | B/C/D/M no overflow, touch help, keyboard menus, dialogs at four widths |
| 23 Canonical compatibility | G/M/E existing saved-source/project/result fixtures |
| 24 No unrelated/infrastructure change | S/Diff scope; no deployment or production writes |

## Contract A01–A18

| ID | Current corrective verification |
| --- | --- |
| A01 | B/E import and no-write traces; D unknown counts and honest project badges |
| A02 | C/B actual local modes/FFmpeg/render/download; MP3/M4A/WAV and long M4A preparation |
| A03 | B/G exact duplicate-name/reordered local-to-canonical payload binding |
| A04 | B/G finalized sources plus failed project, retained work and no duplicate retry ingestion |
| A05 | R/B/D 401/403, cancel/fail/reconnect, exact File/Blob, no stale destructive retry |
| A06 | B/C mode/focus exclusion; result collection does not change editor |
| A07 | E/B explicit Announcement save creates required lineage internally |
| A08 | B/R truthful dirty/save state and three transition choices; C/E preparation errors are not saved success |
| A09 | B/R/D current canonical reopen, unsupported/failed draft, source missing/ineligible behavior |
| A10 | B/C/E waveform mouse/touch/keyboard, precision, zoom/scroll/resize, boundaries, cut/silence/Undo/Redo |
| A11 | B/C/E/P track states, DSP help/focus, synchronized monitoring and result timeline |
| A12 | G/E/P source hashes, deterministic passthrough/mixes and unchanged final DSP/filter/codec |
| A13 | D/M actual project savedAt, three sections, simple filters, independent results and secondary maintenance |
| A14 | M/E integrity playback after lifecycle/source removal; malformed/wrong/stale content rejected |
| A15 | D/M/E/G concrete deletion target, fresh dependencies/revision/pending gates, purge, expired consent and no cascade |
| A16 | M/E permitted contextual recovery; unavailable bytes not recreated; unknown/pending state fails closed |
| A17 | C/D/B/M real geometry and screenshots at 320/390/768/1280, source-bound desktop before/after |
| A18 | S/E/M/G old fixtures, legacy links and unrelated URLs/data/automation preserved |

## Corrections discovered while executing tests

The recovered code passed actual decoder/fallback/hour-long preparation, but its 768px lane exceeded the original 210px assertion. The layout was corrected; the threshold was retained. Keyboard testing found an inexact DSP accessible name, then verified stable focus after rerender. Source list clearing exposed an empty post-login list; reconnect now rereads it before resuming safe work.

Obsolete test expectations were updated narrowly: metadata button text follows the handoff; source details open through the visible contextual disclosure; ordinary project badges now require GET draft reads on reload (still no audio download, auto-open or writes); duration mismatch includes the Zoom guidance; replacing retained unprepared files requires explicit discard. The older isolated source fixture lacked canonical deletion-preview identity/revision; it now supplies the same fields as the real gateway. Actual in-memory deletion regressions separately reject stale/changed previews. Visual review then found missing Announcement S/M labels, the empty native player showing 0:00/0:00 during a preparation error, weak disabled-button presentation, and cramped closed source rows on mobile. These were corrected; the pending source now says it awaits retry, and Archive copy consistently says removed from the work list. The unprepared native player is explicitly asserted hidden. Screenshot capture avoids offscreen fixed skip-link artifacts. No safety assertion or audio tolerance was loosened.

## Validation and limitations

Full local browser smoke passed after the corrections, along with site contract, changed syntax, gateway check, all 80 gateway tests and whitespace checks. Final post-commit command logs, screenshots, source SHA and submitted-head CI are recorded separately in the new evidence index/PR. The table reports executed automated checks and inspected invariants; source-bound visual review is recorded in that index, not inferred from these checks. Browser assertions are executed through the full `tests/safety/browser_smoke.py`, including both corrective modules and the root/subpath CORS regression. The gateway suite remains 80 tests. No new dependencies/build system/runtime provider were added.

Real user files were **not supplied or tested**. Synthetic M4A files are exactly 1:02:27, generated by the bundled browser codec; they do not reproduce the user's exact Zoom bytes, content, file sizes, device, or decoder exception. This proves the implemented preparation/fallback path on these fixtures, not resolution of the unidentified real-file cause. Browser coverage is Chromium emulation, not physical-device, Safari/Firefox or manual screen-reader testing.

No merge, branch deletion, production archive write, deployment, VM/infrastructure modification, Closure Record, PLAN/MASTER update or S09A COMPLETE declaration. The draft PR and its exact-HEAD CI are a reviewable implementation result; final Acceptance remains separate.

The post-commit screenshot run at `2ac3ef8` passed the corrective scenarios but failed the existing strict source-fit scrollbar assertion. Refreshing the fit bounds alone did not resolve it. A direct browser probe measured a 666.40625px rail with a 664px thumb at 768px: `clientWidth` rounded down fractional geometry. The shared scrollbar now measures its precise inner width; fit also refreshes bounds before choosing the value. The original full-width assertion remains unchanged and is additionally exercised by C in CI without screenshot mode. Neither failed run is counted as final validation.

Submitted-head CI at evidence commit `bfcf034` (run `34501984178`) passed Archive/CORS and prior Acceptance regressions but found 227px Speaker lanes at 768px on Linux. The system font wrapped a track action onto a third row. The desktop control column now reserves 280px for the full labels; the waveform still takes more than half the lane. The <=210px assertion is retained. The earlier source-bound screenshots/local PASS remain attributable to `e0e4431`/`bfcf034`; final evidence is refreshed after this cross-platform layout correction.

## PR #36 preparation/deletion coverage correction

The PASS entries for PLAN §§9, 19–21, 35 and A05/A08/A15 above describe the original executed coverage. They did not establish safety for deletion during active preparation. Review on `773975e` identified that gap. D now holds actual native decode completion while deleting a version or series through the visible UI and real in-memory gateway, then checks exact File references/order/payload/source epoch and the latest canonical revision. It also covers decoder failure after the revision update, an explicit successful retry, stale revision rejection and changed-source identity rejection. Existing close/new-source and deletion-after-ready checks remain enabled. [Follow-up evidence](evidence/s09a/pr36-review/README.md) is bound to the new implementation SHA; the earlier PNGs and PASS logs retain their original attribution.

## Shared workspace Linux follow-up

The first workspace CI at `0033ae7` (run `34524573749`) failed the unchanged <=150px Announcement lane limit: Linux font metrics wrapped a fifth action, producing 154.98px. Desktop action columns now reserve space for all five controls and a separate status row. The prior local PASS at `0033ae7` remains historical; the workspace evidence index and PR identify the refreshed source and exact submitted-head result. No geometry or audio assertion was weakened.

Workspace follow-up: CI `34525654306` passed Linux geometry and native signal checks but exposed keyboard menu timing after resize without captures. Synchronous summary activation and anchor reveal fix that path; management smoke now explicitly covers an offscreen focused summary, top-layer bounds, first-action focus and Escape return. See the current workspace evidence and PR exact-head CI result.
