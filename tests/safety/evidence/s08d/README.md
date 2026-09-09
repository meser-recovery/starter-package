# S08D Speaker save/archive visual evidence

Final PR head ref: `codex/s08d-speaker-save-archive-integration`.

Tested implementation SHA: `8970829f6b36d77f442e5824d73ca4cd5c5e9e40`.

The deterministic Chromium scenario uses `https://gateway.test` request interception and never contacts or mutates the production archive. It verifies the exact local MP3 bytes and recipe, authoritative success when cancel races a server finalize, saved history, cancellable exact-candidate resume with editor/workspace locks, retry after cancellation, explicit mismatch discard, reload finalization of a fully uploaded job without local bytes, and authenticated reconstruction after source deletion. During a held resume it refreshes the incomplete list through a delayed response and repeats the resume action, verifies that only one transfer exists and cancellation remains available, then cancels and verifies authoritative reconciliation and lock release. It also executes a corrupt retrieval after successful playback and verifies that the prior player URL and download link are cleared.

| Scenario | 320 px | 390 px | 768 px | 1280 px |
| --- | --- | --- | --- | --- |
| Save confirmation | `s08d-speaker-save-confirmation-320.png` | `s08d-speaker-save-confirmation-390.png` | `s08d-speaker-save-confirmation-768.png` | `s08d-speaker-save-confirmation-1280.png` |
| Confirmation actions | `s08d-speaker-save-confirmation-actions-320.png` | `s08d-speaker-save-confirmation-actions-390.png` | covered in the full dialog | covered in the full dialog |
| Transfer in progress, editing locked | `s08d-speaker-save-progress-320.png` | `s08d-speaker-save-progress-390.png` | `s08d-speaker-save-progress-768.png` | `s08d-speaker-save-progress-1280.png` |
| Saved Speaker version history | `s08d-speaker-saved-history-320.png` | `s08d-speaker-saved-history-390.png` | `s08d-speaker-saved-history-768.png` | `s08d-speaker-saved-history-1280.png` |
| Exact-candidate resume after delayed recovery refresh and duplicate attempt; locks retained and cancel still exposed | `s08d-speaker-resume-locked-320.png` | `s08d-speaker-resume-locked-390.png` | `s08d-speaker-resume-locked-768.png` | `s08d-speaker-resume-locked-1280.png` |
| Fully uploaded job after reload; finalize offered without local bytes | `s08d-speaker-recovery-320.png` | `s08d-speaker-recovery-390.png` | `s08d-speaker-recovery-768.png` | `s08d-speaker-recovery-1280.png` |
| Corrupt retry after verified playback; stale player/download cleared | `s08d-speaker-restored-result-320.png` | `s08d-speaker-restored-result-390.png` | `s08d-speaker-restored-result-768.png` | `s08d-speaker-restored-result-1280.png` |

Generated locally with the contract command:

```bash
./venv/bin/python3 tests/safety/browser_smoke.py --base-url http://127.0.0.1:8765 --browser chromium --screenshot-dir /tmp/s08d-resume-cancel-evidence.mD61sE
```

All 26 images were generated at the tested SHA and representative 320 px and 1280 px views of each changed recovery state were visually inspected. Browser assertions cover 320, 390, 768, and 1280 px: text and controls remain readable, destructive actions stay distinct, dialogs scroll without clipping actions, and no horizontal page overflow is present.
