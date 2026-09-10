# S09 implementation evidence

Base: `8be4a95602e46653ce72fb131b59f6d9f49de17b` (current origin/main at implementation start).
Accepted S08D `6c24a3b60bd359f20ec44687abff776511946a61` is an ancestor.
The intervening change affects only `na_meetings_live.html` and is preserved.
Branch: `codex/s09-archive-management-re-scope`.

## Scope and API reuse

`Audio-Archive.html` provides overview, records, independent results, and maintenance.
`scripts/audio-archive-core.mjs` derives presentation state; `audio-archive.mjs` owns
page orchestration. No persistent index, dependency, schema or gateway runtime file
was added or changed. The existing authenticated client provides all reads, writes,
workflow-specific metadata validation, part adapters and reconstruction.

Management dates and date controls use UTC. An unchanged datetime input preserves
the exact original canonical timestamp, including its offset and subsecond value;
an empty value writes null. List requests are independent observations, merged by
identity/highest revision; they are not represented as an atomic snapshot.

Metadata/lifecycle/deletion writes retain the captured revision, recheck canonical
state and maintenance, and do not proceed through pending deletion or finalizing /
discarding publication states. A conflict preserves form input. Destructive dialogs
bind one target, revision and idempotency key; failure disables resubmission and
reconciles session/list/maintenance state before a new preview can be requested.

Editor intent carries only session/workflow. It survives archive authentication,
checks the current manifest and eligibility, and is removed from the URL once
consumed. Existing loaders and local-work/save guards remain in use. Links open new
tabs to preserve the original editor context. Missing local recovery bytes are not
transferred or replaced with a newly rendered candidate.

## Validation

Executed locally with Node v24.7.0 and the existing `venv/bin/python` + Chromium.
No new dependency installation was required.

| Command | Result |
| --- | --- |
| `git status --short --branch` | rc 0; feature branch; no pre-existing user changes |
| `git diff --check` | rc 0 |
| Individual `node --check` for all six changed/new MJS files (listed below) | all rc 0 |
| `npm --prefix gateway/audio-archive run check` | rc 0 |
| `npm --prefix gateway/audio-archive test` | rc 0; 73 tests, 73 pass, 0 fail/skip |
| `node --test gateway/audio-archive/test/archive-management.test.mjs` | rc 0; 10 tests, 10 pass |
| `python3 tests/safety/check_site.py` | rc 0; site contract passed |
| `python3 -m http.server 8000 --bind 127.0.0.1` | local server started in separate process |
| `venv/bin/python tests/safety/browser_smoke.py --base-url http://127.0.0.1:8000 --screenshot-dir /tmp/s09-archive-management-evidence` | rc 0; full browser smoke passed, including existing S07–S08D browser regressions |
| Focused `check_archive_management` via the existing Playwright environment | rc 0; 320/390/768/1280, 191 local gateway requests, zero outbound archive requests |

Individual syntax checks: `scripts/audio-archive-core.mjs`, `scripts/audio-archive.mjs`,
`scripts/source-session-archive.mjs`, `gateway/audio-archive/test/archive-management-fixture.mjs`,
`gateway/audio-archive/test/archive-management.test.mjs`, `tests/safety/archive_management_bridge.mjs`.
The final S09 browser coverage includes stale-detail and replacement-playback checks,
as well as invalid, archived, source-deleted and purged navigation targets. Screenshot evidence is
recaptured from the implementation commit and kept in a separate evidence-only commit.

Initial failures fixed during implementation: reset-event rendering before native
form reset, and four service buttons clipping at 768px. The service grid now uses two
columns on tablet widths, four on desktop, and one on mobile. Test synchronization
was also corrected to tolerate intentionally replaced detail DOM nodes. Tiny fixture
sizes use bytes/KB rather than rounding to zero MB.

The focused command used was:

```sh
venv/bin/python - <<'PYTHON'
import sys
sys.path.insert(0, 'tests/safety')
from playwright.sync_api import sync_playwright
from archive_management_smoke import check_archive_management
with sync_playwright() as p:
    b = p.chromium.launch()
    check_archive_management(b, 'http://127.0.0.1:8000', '/tmp/s09-archive-management-final')
    b.close()
PYTHON
```

## Files changed

- `Audio-Archive.html`, `styles/audio-archive.css`, `scripts/audio-archive.mjs`, `scripts/audio-archive-core.mjs`: new management surface and presentation.
- `Audio-Editor.html`, `scripts/source-session-archive.mjs`: archive link and validated editor intent.
- `Admin-panel_5ab2b48b89f2fe30ce3272f2816f7d3f19b45752737d55f70f8c3a7f117dc527.html`, `styles/service-landing.css`: archive entry and responsive four-action navigation.
- `gateway/audio-archive/test/archive-management.test.mjs`, `archive-management-fixture.mjs`, `fixtures/s09/tone.mp3`: focused tests, real in-memory fixtures and synthetic audio.
- `tests/safety/archive_management_smoke.py`, `archive_management_bridge.mjs`, `browser_smoke.py`: browser coverage and outbound isolation.
- `tests/safety/check_site.py`, `site-contract.json`, `README.md`, `S09-validation.md`, `evidence/s09/`: safety contract and review evidence.

## Requirement-to-test mapping (approved PLAN §24)

| # | Requirement | Evidence |
| --- | --- | --- |
| 1 | Dedicated management surface | Browser page/landmarks, `overview-*`, `detail-*` |
| 2 | Both lifecycles, unique identity/highest revision | Node: “both lifecycle observations”; browser counts/cards |
| 3 | Title/source filename/ID search, no audio requests | Node normalized search; browser combined filters and GET-only traces |
| 4 | Independent and combined filters, date validation | Node AND filters/UTC ranges; `combined-filters-*`, `no-matches-*` |
| 5 | All sorting is presentation only | Node immutable session/result sorts, varied dates and stable tie-breakers; browser controls |
| 6 | Lifecycle and source availability | Browser archive/source deletion/reload; `detail-*`, `results-restored-*` |
| 7 | Independent statuses/drafts/results | Node workflow ownership; browser detail and verified WAV/MP3 |
| 8 | Actual live/deleted versions, no renumbering | Node live 1/3, deleted 2, retained nextVersion; `detail-*`, recovery reservations |
| 9 | Revision-safe title/date correction | Real gateway conflict + null/offset tests; browser conflict preserves input, title-only edit preserves timestamp; `metadata-conflict-390` |
| 10 | Archive/restore semantics | Real gateway lifecycle test, source bytes unchanged; browser archive action |
| 11 | Integrity-verified playback/download | Node corrupt/missing/reordered/wrong-workflow rejection; browser actual WAV/MP3 decoding/download, reload after source deletion, late URL guards |
| 12 | Preview, exact purge, revision and non-cascade deletion | Real gateway version/series/source/purge tests; browser impact, wrong purge ID, ambiguous deletion; `delete-impact-*`, `purge-confirmation-390`, `ambiguous-deletion-390` |
| 13 | Ingestion + both save workflows + pending deletion | Real in-memory bridge creates interrupted canonical operations; `recovery-*` |
| 14 | Recovery actions only for supported states | Node matrix, existing domain/Speaker-save tests; browser pending-delete retry, uploaded finalize, discarding only offers complete-discard |
| 15 | Explicit catalog rebuild | Browser exact POST trace on click; no rebuild in read-only traces |
| 16 | Validated editor arrival | Browser both workflows after login, one-shot URL consumption, archived/invalid rejection; `editor-arrival-*`, `ineligible-*` |
| 17 | No hidden canonical writes | Browser read-only trace assertions for overview/filter/sort/detail/playback/navigation; Node client/app trace assertions |
| 18 | No additional storage/search authority | Frontend-only implementation; gateway runtime diff empty |
| 19 | Preserve S07–S08D | 73 gateway tests and full existing browser smoke; no DSP/schema/fixture migration |
| 20 | Russian operator UI, technical details opt-in | Visual review, collapsed details assertions; original user filenames/titles remain visible |
| 21 | Keyboard/focus/dialogs | Browser keyboard Escape, focus return, labelled inputs and landmarks; native dialogs and explicit action controls |
| 22 | 320/390/768/1280 layouts | Browser overflow/control geometry assertions and responsive screenshots, visually reviewed |
| 23 | No production changes | In-memory fixtures + outbound denial; no deployment/VM/restart/cleanup/live archive probes |

## Boundaries and limitations

These results are implementation evidence, not independent acceptance or Stage COMPLETE.
No production archive mutation, live Speaker save, gateway activation, deployment,
infrastructure change or retained-fixture cleanup was performed. During audit, the
pre-existing unsupported-browser smoke context was found without outbound isolation;
earlier baseline runs may have issued a gateway configuration GET (not an archive
write). That context now reuses the processor gateway isolation and the final full
run is isolated. The S09 test context has blocked outbound access from its first run. Gateway runtime files
under `gateway/audio-archive/src/` are unchanged. Scheduled meeting generation, generated
meeting data, GitHub Pages configuration and unrelated PR #4 remain untouched.

Pending deletion progress is not exposed by the existing maintenance API; the UI says
that detailed progress is unavailable and offers only the existing continue operation.
Incomplete ingestion may lack a final session/title and is shown honestly without a
failing forced lookup. Orphan observations stay informational. Exact-candidate recovery
with missing parts requires the original editor tab; the management page cannot recreate
lost local bytes. Browser evidence uses Chromium; it does not claim a manual screen-reader
or cross-browser audit. No external Project Sources / MASTER records were edited.
