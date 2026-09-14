# S09C corrective visual evidence

These screenshots were captured by `tests/safety/s09c_portal_smoke.py` from the real
`Audio-Editor.html` and `Audio-Archive.html` pages after the corrective visual pass.
The browser used the repository's local synthetic preview gateway. It made no outbound
requests and did not contact or mutate the production archive.

The binding visual comparison and required corrections are recorded in
`tests/safety/S09C_CORRECTIVE_VISUAL_MATRIX.md`.

## Required states

- Editor entry: `editor-initial-1280.png`, `editor-initial-390.png`
- Archive record picker: `editor-archive-selection-1280.png`, `editor-archive-selection-390.png`
- Local file picker: `editor-local-files-1280.png`, `editor-local-files-390.png`
- Loading: `editor-loading-1280.png`
- Workflow choice: `editor-workflow-choice-1280.png`, `editor-workflow-choice-390.png`
- Announcement workspace and result: `announcement-workspace-1280.png`, `announcement-result-1280.png`
- Full Speaker workspace: `speaker-workspace-1680.png`, `speaker-workspace-1280.png`, `speaker-workspace-390.png`
- Speaker transport delta: `speaker-follow-off-1280.png`, `speaker-follow-on-1280.png`,
  `speaker-scale-time-1280.png`, `speaker-scale-height-1280.png`, `speaker-fit-after-zoom-1280.png`
- Speaker result: `speaker-result-1680.png`, `speaker-result-1280.png`
- Archive list: `archive-list-1536.png`, `archive-list-1280.png`, `archive-list-390.png`
- Archive record detail: `archive-record-detail-1280.png`, `archive-detail-expanded-history-1280.png`
- Dialogs: `dialog-save-announcement-1280.png`, `deletion-dependency-dialog-1280.png`,
  `archive-reconnect-required-390.png`, `archive-exact-id-purge-confirmation-390.png`

The synthetic WAV shapes and illustrative record metadata exist only in the test fixture
so that the real waveform, loading, editing, result, archive, recovery, and dialog UI can
be rendered deterministically. Production processing, DSP, gateway, archive model,
recovery, versioning, and deletion semantics are unchanged by the evidence fixture.
