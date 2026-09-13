# S09B rendered evidence

Source target: `739e6b4b2b6b1b256796f5140bcd228f1350d0af` from branch `codex/s09b-unified-zoom-recording-ux`.
Fixture: generated audio + real client/gateway/domain over `MemoryRepository`; production gateway and GitHub archive destinations blocked.

This directory contains 93 real Chromium PNG captures generated at the source target. The focused Archive and Editor runs passed at 320/390/768/1280 px. Representative files were visually inspected for overflow, clipping, control overlap, block order, recovery readability and consistent Archive/Editor boundaries.

The committed rendered states include:

- `overview-{320,390,768,1280}.png` — default all-record list.
- `combined-filters-{320,390,768,1280}.png`, `no-matches-{...}.png` — filters/reset/empty result.
- `detail-{320,390,768,1280}.png` and `archive-intent-detail-390.png` — consolidated detail, project, both histories and deep link.
- `metadata-rerender-draft-390.png`, `metadata-conflict-390.png`, `metadata-conflict-reloaded-390.png` — entered title/date survive late result metadata and conflict reload.
- `results-restored-after-source-deletion-390.png` — deleted sources with retained result access.
- `contextual-recovery-{320,390,768,1280}.png`, `recovery-{...}.png` — associated and maintenance recovery separation.
- `delete-impact-{320,390,768,1280}.png`, `purge-confirmation-390.png`, `ambiguous-deletion-390.png` — contextual destructive confirmations.
- `editor-arrival-{announcement,speaker}-390.png` and `ineligible-*.png` — Editor current record/workspace and ineligible arrivals.
- `s08b-archive-overview-{390,1280}.png` inside this S09B directory — Editor picker (historical filename retained only inside the new evidence directory).
- `s08d-speaker-resume-locked-{320,390,768,1280}.png` and `s08d-speaker-recovery-{...}.png` — contextual exact-result continuation and complete-job finalization in Editor.
- `verified-{announcement,speaker}-390.png` — verified playback/download states for the two distinct histories.
- the additional `s08b-*`, `s08c-*`, `s08d-*` files are current S09B executions of preserved Announcement/Speaker interactions; no historical evidence directory is overwritten.

## Visual gate A–F

- **A — record-first Archive:** `overview-390.png`, `detail-390.png` and `detail-1280.png` show one recording list, a separate detail screen, two primary intents and both version histories in the required order.
- **B — local device work:** `s08b-local-result-390.png` and `s08b-save-confirmation-390.png` show the local-only result before explicit archive persistence.
- **C — Speaker continuation:** `editor-arrival-speaker-390.png` and `s08d-speaker-saved-history-390.png` keep project/result work under the current recording.
- **D — deleted sources:** `results-restored-after-source-deletion-390.png` keeps the two histories and playback actions visible while explaining why new processing is unavailable.
- **E — recovery:** `contextual-recovery-390.png`, `recovery-390.png` and `s08d-speaker-resume-locked-390.png` distinguish canonical Archive recovery from exact-local-Blob continuation in Editor.
- **F — ownership boundary:** `editor-arrival-announcement-390.png`, `editor-arrival-speaker-390.png`, `detail-390.png` and `verified-{announcement,speaker}-390.png` show processing in Editor and lifecycle/deletion/history in Archive without merging the two workflows.

The live review preview remains the approval surface; this committed evidence makes the same implementation states independently inspectable in the PR.
