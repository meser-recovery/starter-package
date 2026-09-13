# S09C requirement-to-evidence matrix

This matrix maps the S09C acceptance criteria to the implemented surface and the
repeatable evidence. Browser coverage uses only the local synthetic gateway and
blocks every outbound request.

| AC | Requirement | Implementation location | Automated / visual evidence |
| --- | --- | --- | --- |
| 1 | Quiet Editor entry with one Archive/device decision | `Audio-Editor.html`; S09C portal rules in `styles/audio-studio.css` | `s09c_portal_smoke.py`; `editor-initial-{320,390,768,1280}.png` |
| 2 | Both entry paths produce the current-record summary before task choice | `renderCurrentRecording` and source-choice handlers in `scripts/source-session-archive.mjs` | `s09c_portal_smoke.py`; `editor-current-recording-and-workflow-choice-390.png` |
| 3 | One active workflow and guarded switching/closing | `activateMode`, `leaveAnnouncementWorkspace`, and existing Speaker close guard in `scripts/source-session-archive.mjs` | `s09c_portal_smoke.py`; full `browser_smoke.py` S09A acceptance/corrective checks |
| 4 | Focused Speaker workspace with waveform/timeline primary and full controls reachable | Existing Speaker DOM/modules, reorganized by `Audio-Editor.html` and `styles/audio-studio.css` | full `browser_smoke.py` Design A, waveform, meters, playback, timeline, selection, render and project checks; `speaker-workspace-selection-1280.png` |
| 5 | Simpler, related Announcement task flow without Speaker-only editing controls | Announcement section in `Audio-Editor.html`; light focused rules in `styles/audio-studio.css` | `s09c_portal_smoke.py`; full S09A corrective and selection-tool checks; `announcement-workspace-1280.png`, `announcement-result-1280.png` |
| 6 | Separate Archive entry/list/detail and preserved return context | `Audio-Archive.html`; `renderDetail` and list state in `scripts/audio-archive.mjs` | `s09c_portal_smoke.py`; archive-management smoke; `archive-initial-*`, `archive-record-list-1280.png`, `archive-record-detail-1280.png` |
| 7 | Detail prioritizes processing intents/results, then disclosure sections | `renderDetail` in `scripts/audio-archive.mjs`; S09C disclosure styling | `s09c_portal_smoke.py`; `archive-record-detail-1280.png`, `archive-detail-expanded-history-1280.png` |
| 8 | Every existing action remains reachable | Parity map below; unchanged IDs/listeners and existing modules | `check_site.py`; all 50 Node safety tests; full browser suite |
| 9 | Presentation actions do not write, render, mutate lifecycle, reserve versions, or recover | UI state changes remain separate from gateway operations | `s09c_portal_smoke.py` records zero writes before explicit management; 67 local requests, 2 explicitly initiated writes |
| 10 | Identity, histories, saves, playback/download, projects, recovery and deletion retain S09B semantics | Existing archive/editor/core/gateway contracts; only presentation orchestration changed | 50 Node safety tests; 80 gateway tests; full S09/S09A browser suite |
| 11 | Local objects and edit/candidate state survive permitted UI changes | Existing object URL, request-generation and unsaved-work guards; non-destructive Announcement close | S09A acceptance, corrective and Design A checks in `browser_smoke.py` |
| 12 | Required loading/error/disconnected/unavailable/recovery/delete states remain action-correct | Existing status/live regions and Archive dialogs, restyled consistently | S09C and archive-management smoke; reconnect, retained-result and deletion screenshots |
| 13 | Responsive 320/390/768/1280; page overflow absent and timeline overflow local | Responsive portal/workspace rules in `styles/audio-studio.css` | width assertions in `s09c_portal_smoke.py` and full browser suite; four-width evidence sets |
| 14 | Keyboard/focus/dialog/live-region/accessibility semantics preserved | Semantic HTML, existing dialog controller, labels, `:focus-visible`, reduced-motion-aware scrolling | `check_site.py`; browser dialog/focus checks; manual screenshot review |
| 15 | No gateway/schema/storage/security/infrastructure or unrelated site change | Diff is limited to two pages, their presentation orchestration/styles, preview fixture and safety evidence | `git diff --stat`; gateway check/tests pass without gateway source changes |
| 16 | Full safety suite and focused S09C coverage pass | `tests/safety/s09c_portal_smoke.py` plus existing suites | Exact commands/results are recorded in the PR and completion report |
| 17 | Real current preview is left running | `scripts/preview-audio-editor.py` seeds the synthetic multi-track review state | Preview URLs, exact checked SHA and clean/dirty state are recorded in the PR and completion report |

## Existing function → S09C location parity map

| Existing function | S09C location |
| --- | --- |
| Choose an archive recording | Editor entry → **Из аудиоархива** → focused picker |
| Search/month/recent/pagination | Picker disclosure opened only after the Archive choice |
| Choose/replace/remove synchronized local tracks | Editor entry → **С устройства** → local-file disclosure |
| Current record identity and readiness | Compact **Текущая запись Zoom** card |
| Open Announcement processing | Current record → equal **Анонс-мейкер** task card |
| Open Speaker editing | Current record → equal **Спикерская** task card |
| Speaker transport, waveform, selection, processing, mix, history, render and saves | Focused dark Speaker workspace; secondary explanations/settings remain in disclosures |
| Announcement ordering, monitoring, pause processing, result statistics, archive save and download | Focused light Announcement workspace in source → process → result order |
| Browse archive recordings | Audio Archive entry → explicit **Найти запись** request → focused list |
| Open record, play/download latest results and continue a workflow | Separate Archive record detail; processing intents and latest results first |
| Full histories and saved Speaker project | Record detail → workflow history/project disclosures |
| Sources, lifecycle/metadata and recovery | Record detail → source/management disclosures |
| Archive/restore, dependency preview, source/version/series/record deletion and purge | Record detail → management / danger disclosures and existing confirmation dialogs |
| Unassociated operations and rebuild | Collapsed maintenance area outside the ordinary record path |
| Technical record identifiers/details | Record detail → collapsed technical information |

No function in this map changes canonical ownership, DSP, persistence, versioning,
deletion, recovery, authentication, CORS, or storage behavior.
