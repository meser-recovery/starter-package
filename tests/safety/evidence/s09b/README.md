# S09B progressive-disclosure GUI evidence

Implementation target: `340c4d1813321de04181e81889150216a796d80b` on branch
`codex/s09b-unified-zoom-recording-ux`.

The directory contains 111 real Chromium PNG captures generated from that implementation.
The fixture uses generated audio and the real frontend client/gateway/domain over
`MemoryRepository`; production gateway and GitHub archive destinations are blocked.
The full browser suite passed at 320/390/768/1280 px, and the representative states
below were visually inspected for overflow, clipping, action visibility, disclosure
order and the Archive/Editor ownership boundary.

## Progressive entry and chooser

- `archive-initial-{320,390,768,1280}.png` — Archive entry without a selected record or collection DOM.
- `chooser-before-request-{320,390,768,1280}.png` — Archive chooser before an explicit search.
- `chooser-results-1000-{390,1280}.png` — first 10 rows and explicit pagination for the 1,000-record browser fixture; the test traverses all 100 pages without gaps or duplicates.
- `editor-initial-{320,390,768,1280}.png` — compact Editor entry and current-record card.
- `editor-chooser-before-request-{320,390,768,1280}.png` and `s08b-archive-overview-{390,1280}.png` — Editor chooser before and after an explicit request.

## Selected record and preserved functions

- `detail-{320,390,768,1280}.png` and `archive-intent-detail-390.png` — one selected record, latest ready result per workflow and the on-demand full histories/management.
- `s08b-selected-work-{390,1280}.png`, `s08b-local-result-{390,1280}.png` — Announcement workspace and local result.
- `s08c-speaker-opened-{390,1280}.png`, `s08c-local-result-{390,1280}.png` — Speaker workspace and local result.
- `verified-{announcement,speaker}-390.png` — verified playback/download for the two distinct histories.
- independent result-sort assertions run in `archive_management_smoke.py`; the sort controls remain inside their respective workflow histories.

## ACCEPT A — contextual Speaker recovery

- `s08d-speaker-resume-locked-{320,390,768,1280}.png` — exact local Blob continues the same transaction and reserved version while conflicting actions are locked.
- `s08d-speaker-recovery-{320,390,768,1280}.png` — fully uploaded current-record job can be finalized without local bytes.
- browser assertions cover no current record, record A/B mismatch, wrong workflow, candidate-fingerprint mismatch, exact match, cancel/retry and a context switch during delayed work.

## ACCEPT B and metadata safety

- `results-restored-after-source-deletion-390.png` — archived record with deleted sources truthfully keeps saved playback/download while new processing remains unavailable.
- `metadata-rerender-draft-390.png` — local title/date survive late result metadata.
- `metadata-conflict-390.png` and `metadata-conflict-reloaded-390.png` — conflict and explicit canonical reload preserve both entered fields until the user saves them.
- `contextual-recovery-{320,390,768,1280}.png` and `recovery-{320,390,768,1280}.png` — record-associated and unassociated maintenance recovery remain distinct.

All other PNGs in this directory are current executions of the preserved publication,
Speaker edit/render/save, deletion, error and reconnect scenarios. Historical S09A
evidence outside this directory was not replaced.
