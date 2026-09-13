# S09C Chromium evidence index

Implementation target: `f8db221177e85937a76313f701999fedf4c116aa`

These screenshots were captured from the real `Audio-Editor.html` and
`Audio-Archive.html` at the implementation target above. This directory is an
evidence-only follow-up commit; the screenshots do not claim to prove that
self-referential evidence commit. The browser used a local synthetic gateway,
blocked all outbound traffic, and used generated WAV inputs only.

| File | Scenario | Viewport | Acceptance criteria |
| --- | --- | ---: | --- |
| `editor-initial-320.png` | Quiet Editor entry; Archive/device decision; inactive workspaces absent | 320 | 1, 13, 14 |
| `editor-initial-390.png` | Quiet Editor entry and wrapped Russian labels | 390 | 1, 13, 14 |
| `editor-initial-768.png` | Quiet Editor entry at tablet width | 768 | 1, 13 |
| `editor-initial-1280.png` | Quiet Editor entry at desktop width | 1280 | 1, 13 |
| `editor-archive-picker-before-request-390.png` | Focused Archive picker before explicit list request | 390 | 1, 6, 9, 12 |
| `editor-archive-picker-results-390.png` | Explicit search results and record selection path | 390 | 2, 6, 12, 13 |
| `editor-current-recording-and-workflow-choice-390.png` | Canonical current-record summary followed by equal workflow choice | 390 | 2, 3, 13 |
| `announcement-workspace-1280.png` | Light focused Announcement source → process flow with three synchronized tracks | 1280 | 3, 5, 8, 10 |
| `announcement-result-1280.png` | Completed result, statistics, explicit archive-save and MP3 download affordances | 1280 | 5, 9, 10, 12 |
| `speaker-workspace-selection-1280.png` | Dark focused Speaker workspace, three tracks, timeline, controls and edit selection | 1280 | 3, 4, 8, 10 |
| `speaker-workspace-contained-timeline-320.png` | Narrow Speaker adaptive layout and locally contained timeline | 320 | 4, 13, 14 |
| `speaker-workspace-contained-timeline-390.png` | Narrow Speaker layout with readable controls and local timeline scroll | 390 | 4, 13, 14 |
| `archive-initial-320.png` | Separate Archive entry before explicit record request | 320 | 6, 13, 14 |
| `archive-initial-390.png` | Separate Archive entry at narrow width | 390 | 6, 13 |
| `archive-initial-768.png` | Separate Archive entry at tablet width | 768 | 6, 13 |
| `archive-initial-1280.png` | Separate Archive entry at desktop width | 1280 | 6, 13 |
| `archive-record-list-1280.png` | Scan-friendly record list after explicit request | 1280 | 6, 8 |
| `archive-record-detail-1280.png` | Separate detail: processing intents and latest usable results first | 1280 | 6, 7, 10 |
| `archive-detail-expanded-history-1280.png` | Workflow history disclosed below primary content | 1280 | 7, 8, 10 |
| `archive-reconnect-required-390.png` | Disconnected Archive with explicit reconnect path | 390 | 12, 13 |
| `archive-unavailable-sources-retained-results-390.png` | Deleted/unavailable sources while retained result remains usable | 390 | 10, 12, 13 |
| `deletion-dependency-dialog-320.png` | Dependency preview dialog at minimum width | 320 | 10, 12, 13, 14 |
| `deletion-dependency-dialog-1280.png` | Dependency preview and non-cascading consequence disclosure | 1280 | 10, 12, 14 |
| `archive-exact-id-purge-confirmation-390.png` | Exact-ID permanent purge confirmation | 390 | 10, 12, 13, 14 |

## Repeatable run records

| Command | Result | Acceptance criteria |
| --- | --- | --- |
| `venv/bin/python tests/safety/s09c_portal_smoke.py --screenshot-dir tests/safety/evidence/s09c` | PASS: 67 local gateway requests, 2 explicitly initiated writes (source deletion and logout), 0 outbound requests | 1–14, 16 |
| `venv/bin/python tests/safety/browser_smoke.py --base-url http://127.0.0.1:8767` | PASS: full Chromium safety suite, including S09/S09A archive, auth, DSP, waveform, timeline, edit, project, recovery, cancellation and responsive coverage | 3–16 |
| `node --test tests/safety/*.test.mjs` | PASS: 50/50 | 8–11, 15–16 |
| `npm --prefix gateway/audio-archive test` | PASS: 80/80 | 10–11, 15–16 |

## Manual visual inspection

The screenshots above were inspected for information hierarchy, clipping,
overlap, unexpected whitespace, long Russian wrapping, dialog fit,
page-vs-local horizontal overflow, and accidental exposure of backend terms.
The four-width entry sets, both focused workspaces, the narrow Speaker timeline,
Archive detail/history, reconnect, retained-result, dependency-preview and
exact-confirmation states were reviewed. No blocking visual defect was found.
