# S11 visual corrective v2 — six-scene approval pilot

Scope: **015, 016, 029, 032, 050, 059 only**. Await visual approval before any of the other 45 browser recaptures or full MP4 assembly. PR #60 remains open; no merge or production mutation.

## Implementation

- `Director.aim()` targets a concrete control with the cursor only. `Director.highlight()` decorates the actual semantic section with a capture-only outline and hides cursor emphasis.
- The cursor uses a viewport-sized manual popover in the browser top layer, attached to `body`. It is never reparented into a transformed dialog. Section outlines use the target element itself.
- Pointer arrival is scheduled against the existing character alignment. Movement starts before the cue. Click waits until both **arrival + 0.75 s** and **phrase end + 0.25 s**; post-action hold is **0.45 s**.
- Highlight identity includes the element, its parent, tag, ID, role, type, href and accessible label (or text). Dynamic meter readings do not change its stable accessible identity. Actions, removal, replacement, role/identity changes, hiding and modal occlusion clear stale highlights.
- Continuous browser auditing rejects control outlines. A screenshot pixel gate checks every section outline against its semantic target, with a **2 px** maximum tolerance. Failed capture aborts before publishing its video.
- `corrective_pilot.py` has an explicit six-scene allowlist and no audio generation/assembly path. Missing narration cache is an error. Existing CLIP WAV fixtures are reused read-only.
- `corrective_review.py` plays silent visual clips alongside the original module MP3s using their existing timing ranges. No new audio files or audio encodes. Each clip has 1.2 s visual lead-in for the first pointer approach and a stable tail.

## Regression evidence

Generated evidence and videos are ignored by Git, under `tutorial/generated/visual-corrective-v2/`.

- Before frames reproduce **015 footer outline at 04:24**, **016 displaced file-selection outline at 04:40**, and **029 underlying button outline while save modal is open at 08:10.35**.
- Native transformed-dialog regression reproduces **485 px** displacement with the previous layer. New rendered geometry differs by at most **0.5 px** in that test.
- Negative tests reject displaced outline geometry and any outlined cursor target. Role change, replacement and opening a modal clear previous highlights.
- 050 preserves the existing `project-state-row` filtered by `Связанные финальные версии:` and the separate current state. Its semantic selection is not redesigned.
- 059 opens real deletion consequence previews and cancels; it never confirms deletion.

| Scene | Visual clip | Narration | Pixel checks |
| --- | ---: | ---: | ---: |
| 015 | 11.133 s | 7.440 s | cursor only |
| 016 | 24.100 s | 20.408 s | 1 |
| 029 | 21.300 s | 17.594 s | 1 |
| 032 | 12.467 s | 8.772 s | 2 |
| 050 | 22.633 s | 18.946 s | 4 |
| 059 | 28.467 s | 24.765 s | 2 |

Actual six-scene gates: maximum cursor arrival error **0.061 s**, minimum dwell **0.751 s**, maximum section pixel error **0.469 px**. All six videos completely decode, have no audio streams, and report no control-outline violations. CONTENT_DRIFT: **PASS**.

Preservation baseline: **506 existing files** checked by SHA-256 and nanosecond mtime, including narration/cache/alignment, every existing generated audio file, Canonical Content Pack, `tutorial.yaml`, and the previous full candidate. **0 changed; 0 TTS requests; 0 audio encodes.**

## Local review and checks

Review: `http://127.0.0.1:4197/index.html`.

Commands from repository root (existing generated narration, fixtures and preservation baseline required):

```sh
venv/bin/python -m unittest discover -s tutorial/scripts -p 'test*.py'
venv/bin/python tutorial/scripts/verify_capture_v2.py
venv/bin/python tutorial/scripts/corrective_pilot.py --scenes 15,16,29,32,50,59
venv/bin/python tutorial/scripts/validate_corrective_pilot.py
venv/bin/python tutorial/scripts/corrective_review.py --serve --port 4197
```

34 offline tests passed. The Chromium geometry regression and six-scene validation passed. Detailed machine-readable results: `evidence/geometry-regression.json`, `evidence/pilot-validation.json`, `evidence/preservation.json`, per-scene capture metadata and section screenshots. The existing full candidate remains unchanged.
