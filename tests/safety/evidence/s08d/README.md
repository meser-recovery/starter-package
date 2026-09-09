# S08D Speaker save/archive visual evidence

Final PR head ref: `codex/s08d-speaker-save-archive-integration`.

The deterministic browser scenario uses `https://gateway.test` request interception and never contacts or mutates the production archive. It verifies the exact local MP3 bytes, the Speaker recipe, version reservation, saved history, and authenticated reconstruction after a full page reload with source assets deleted.

| Scenario | 320 px | 390 px | 768 px | 1280 px |
| --- | --- | --- | --- | --- |
| Save confirmation | `s08d-speaker-save-confirmation-320.png` | `s08d-speaker-save-confirmation-390.png` | `s08d-speaker-save-confirmation-768.png` | `s08d-speaker-save-confirmation-1280.png` |
| Confirmation actions | `s08d-speaker-save-confirmation-actions-320.png` | `s08d-speaker-save-confirmation-actions-390.png` | covered in the full dialog | covered in the full dialog |
| Transfer in progress, editing locked | `s08d-speaker-save-progress-320.png` | `s08d-speaker-save-progress-390.png` | `s08d-speaker-save-progress-768.png` | `s08d-speaker-save-progress-1280.png` |
| Saved Speaker version history | `s08d-speaker-saved-history-320.png` | `s08d-speaker-saved-history-390.png` | `s08d-speaker-saved-history-768.png` | `s08d-speaker-saved-history-1280.png` |
| Interrupted-save recovery choices | `s08d-speaker-recovery-320.png` | `s08d-speaker-recovery-390.png` | `s08d-speaker-recovery-768.png` | `s08d-speaker-recovery-1280.png` |
| Verified playback/download after reload and source deletion | `s08d-speaker-restored-result-320.png` | `s08d-speaker-restored-result-390.png` | `s08d-speaker-restored-result-768.png` | `s08d-speaker-restored-result-1280.png` |

Generated locally with the contract command:

```bash
venv/bin/python tests/safety/browser_smoke.py --base-url http://127.0.0.1:8000 --screenshot-dir /tmp/s08d-speaker-save-evidence
```

All 22 images were visually inspected. Text and controls remain readable, destructive actions stay distinct, dialogs scroll without clipping actions, and no overlap or horizontal page overflow is visible at the captured widths.
