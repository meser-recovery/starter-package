# S09B progressive-disclosure function matrix

| Existing function | New location | Regression / acceptance evidence |
| --- | --- | --- |
| Select an eligible archive recording | Inline `Выбрать запись` chooser in Editor; no collection on entry | `browser_smoke.py::check_source_session_archive`: initial, search, pagination, selection and close |
| Select any canonical recording | Inline `Выбрать запись` chooser in Archive; no collection on entry | `archive_management_smoke.py`: 1,000-record fixture, search and pagination |
| Device import | Editor header action `С устройства`, existing device panel | existing S09A browser suite + progressive-disclosure GUI states |
| Announcement processing | Editor workflow tab and existing announcement workspace | existing S09A processor/browser tests |
| Speaker processing | Editor workflow tab and existing DAW workspace | existing S09A timeline, edit-mode, waveform, meter and render tests |
| Local result playback/download | Existing result block inside the active workflow | existing processor and speaker browser tests |
| Save announcement output | Existing explicit archive-save action in announcement result | existing S09B publication browser tests |
| Save/resume Speaker output | Existing explicit Speaker archive-save action; contextual recovery only for the active recording | `browser_smoke.py::check_source_session_archive` and `s09a_acceptance_smoke.py`: no context, mismatch, match, switch, cancel/retry |
| Latest saved Announcement/Speaker output | Archive record: open `Готовые записи`, one canonical max-version result per workflow | progressive-disclosure browser test and GUI evidence |
| Full output history/playback/download/delete | Archive record: closed `Все версии и управление`, separate workflow histories | existing archive management tests + progressive-disclosure browser test |
| Independent result sorting | One sort control inside each workflow history | `s09b_unified_archive.test.mjs` and browser assertion |
| Continue saved Speaker project | Archive record: closed `Проект обработки спикерской` | existing project projection/deep-link tests |
| Source tracks and source deletion | Archive record: closed `Исходные дорожки` and `Управление записью` | existing archive deletion matrix tests |
| Metadata and lifecycle | Archive record: closed `Управление записью`; local draft survives async rerenders/conflicts | existing S09B draft regression + progressive-disclosure browser test |
| Contextual/global recovery | Current-record notice/details; unassociated work in closed maintenance section | existing recovery policy tests + Editor state-bound recovery regression |
| Technical diagnostics | Closed `Технические сведения` / `Техническое обслуживание` | existing archive management smoke tests |

This matrix records placement only. It does not change data ownership, gateway calls,
version numbering, transaction identity, Blob identity, or DSP behavior.
