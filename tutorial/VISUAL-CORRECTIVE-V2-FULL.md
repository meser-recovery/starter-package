# S11 visual corrective v2 — full candidate

Branch: `codex/s11-automated-tutorial-production-pipeline`. Continuation of the user-approved six-scene pilot in PR #60. Output: `tutorial/generated/visual-corrective-v2-full/` (ignored by Git).

## Implemented

- Automatic semantic cursor lifecycle shared by every browser scene. Cursor state starts hidden. Removal, identity changes, occlusion, reflow, disabled targets, dialog/menu changes and navigation hide the old cursor. A new explicit target re-enters near that target. A stable unchanged target may remain visible.
- Real click feedback precedes hiding. Navigation and popup actions record the press feedback and a hidden-cursor frame before capture pauses for the real destination. No stale cursor coordinates appear on the new page. Gestures have their own lifecycle and hide on completion.
- Concrete controls, including keyboard-operable waveform regions, use cursor only. Semantic sections use an outline on the actual element. The viewport cursor stays in a manual top-layer popover attached to `body`; it is never reparented into dialogs.
- Alignment-driven arrivals; clicks wait for both arrival + 0.75 s and relevant phrase end + 0.25 s. Post-action hold is 0.45 s. Short capability demonstrations point at the real control without unnecessary extra clicks. Action sequences are never sped up to fit the narration.
- Continuous outline/cursor audit, screenshot geometry within 2 px, visible arrival checks, dwell/hold gates, real drag evidence and decoded navigation-feedback pixel checks. Invalid captures fail before final assembly.
- 050 retains the exact linked project-state selector (`Связанные финальные версии:`) and the separate current state. 044 highlights the actual source workspace to avoid its inner track list's clipped outline. 059 previews destructive consequences and cancels; it never confirms deletion.
- The full runner has no TTS generation path. Browser capture is restricted to process-local loopback Meser UI with synthetic data. Approved procedural animations are reused with verified input and artifact hashes. PCM-first assembly uses the existing eight modules and one final AAC encode.

## Narration cache

All eight modules are existing cache hits. No module is regenerated; no ElevenLabs request is issued. Audio, alignment, canonical narration and `tutorial.yaml` are unchanged.

| Module | Source MP3 duration | Cache |
| --- | ---: | --- |
| N01 | 159.085714 s | HIT |
| N02 | 144.927347 s | HIT |
| N03 | 116.767347 s | HIT |
| N04 | 78.994286 s | HIT |
| N05 | 106.031020 s | HIT |
| N06 | 82.520816 s | HIT |
| N07 | 168.045714 s | HIT |
| N08 | 97.724082 s | HIT |

Existing profile: `eleven_v3`, voice `LHi3adMlU7AICv8Yxpmm`, Russian, stability `0.5`, delivery prefix `[calm] [conversational]`. No request or pronunciation settings are changed.

## Review and evidence

- Review: `http://127.0.0.1:4198/index.html`.
- MP4: `http://127.0.0.1:4198/meser-audio-tutorial-v3.mp4`.
- `verification.json`, `manifest.json`, `video-qa/capture-coverage.json`, `video-qa/boundaries.json`.
- `evidence/cursor-lifecycle-regression.json`, `evidence/geometry-regression.json`, per-scene section screenshots and navigation feedback/hidden-frame pairs.
- `evidence/narration-cache.json`, `evidence/narration-preservation.json`, `evidence/audio-equivalence.json`.
- `audio/boundary-validation.json`, exact PCM master, unchanged SRT/VTT.

The review provides all 60 scene starts, all eight module starts, all seven audio boundaries, and all 59 visual transitions. The preceding full candidate and the approved six-scene pilot remain in their original directories.

## Files changed

- Capture infrastructure: `browser_capture.py`, `capture_director.py`, `capture_overlay.js`.
- Full rollout and scene choreography: `corrective_full.py`, `corrective_scenes.py`.
- Validation: `verify_cursor_lifecycle.py`, `video_qa.py`.
- Review: `module_review.html.in`, `serve_modules.py`.
- Documentation: this report, `README.md`, and the historical pilot's approval status.

All paths above are under `tutorial/` or `tutorial/scripts/`. Production frontend, production Audio Archive, canonical content, narration cache and `tutorial.yaml` are not modified. Generated media/evidence are not committed. PR #60 remains open and unmerged; the branch is retained.

## Validated capture gates

- 60 current visual caches: **51 real browser captures + 9 preserved approved animations**.
- Semantic-target coverage **51/51**. Cursor appears in 48 scenes; 011, 028 and 050 use section emphasis only.
- **57 cursor hides**, **0 invalid visible cursor frames**, **0 control-outline violations**.
- **25 rendered geometry checks**, maximum error **0.5 px** (limit 2 px).
- **69 clicks**, **77 actual pointerdown ripples**, **6 decoded navigation-feedback checks**. All required drag scenes pass.
- Maximum cue error **0.123 s** (rounded upward; limit 0.18 s). Maximum actual pointer movement **0.724 s**. Dwell, phrase-end, post-action and visible-tail hold gates all pass.
- **34 offline tests** and **14 Chromium lifecycle scenarios** pass. Negative cases reject outlined controls, orphan cursors and incorrect section geometry; the legacy transformed-dialog defect is reproduced at 485 px and corrected to at most 0.5 px.
- **CONTENT_DRIFT: PASS**. Preservation verifies SHA-256 and nanosecond mtimes for **564 existing files: 0 changed**. TTS requests: **0**.

Final file SHA-256, duration, PCM equivalence, complete decode, audio boundaries, 59 visual boundaries and subtitle checks are recorded in the generated `manifest.json`, `verification.json`, and linked evidence. Those artifact results are reported with the checked HEAD and CI status in the completion response. Generated evidence is intentionally kept outside Git history.
