# Receiving Mac validation — continuous waveform

Applied once on clean `codex/s09a-editor-corrective-ux` at base `07e4e66ec1ae4058f822b35d4092e324dc443a36`.
Embedded patch SHA256: `0326c54696f6b382bb310c0e614ba8cc70d803e2cbda6878aa74de70e38b04ed` (verified before `git apply --index`). Parent-folder evidence belongs to the patch author; this folder contains fresh receiving-Mac results.

The implementation changes exactly match the supplied patch. Receiving changes add both-editor live playback zoom 80→1000→300→80 regression and correct two pre-existing test assumptions: pointer-selection scale now caps at 1000 px/s, and rendered-result CSS timeline width excludes offscreen physical canvas guard tiles. Source-time, result-duration, actual decoded audio, signal and cleanup assertions remain.

## Performed before commit

- Site contract, changed JS/Python syntax and strict editor HTML nesting: PASS (`static.txt`). The log identifies base HEAD plus the applied working changes, not a committed final HEAD.
- Transport/waveform/detail units: 31/31 PASS (`unit.txt`). Gateway check and tests: 80/80 PASS (`gateway.txt`).
- Full attempt 1 stopped at the obsolete uncapped selection expectation. Full attempt 2 passed archive/CORS, project acceptance, region handles, M4A fallback, two hour-long tracks at DPR 1/2, Design A/DSP/result, alignment, consistency, motion/live zoom, meters/signals, timeline and management; stopped at the obsolete canvas-width expectation. These are preserved as failed attempts, not full PASS claims.
- After correcting the latter assertion, the source-session/result and complete processor scenarios passed directly on `http://127.0.0.1:55153` (`source-result-processor.txt`). This includes actual render/download, waveform failure fallback, passthrough, cancel/retry, manual scroll/Follow, mixed signal, duration bounds and virtual-FS cleanup.
- Actual contour comparison: same source at 80/159/160/300/1000 px/s in both editors. Tile overlap bytes identical at DPR 1/1.1/1.25/1.5/2/3. See consistency JSON.
- Real playback: about 60 RAF fps, zero differing sampled visible source-column signatures in all eight editor/scale cases, including prefetch windows 0/16/32/40/56 seconds. Both editors retain audio progress and stable pixels during live zoom in/out; Speaker rendered-result pixels remain unchanged. See motion JSON.
- Four PNGs were captured from the actual Mac Chromium editor after playback at overview/detail, with two synthetic 73.3-second tracks. The overview images were visually inspected: continuous filled envelopes, matching channel contours, intact light-theme controls and timeline. Alignment screenshots were inspected for silence/onset placement. Hashes identify original PNGs.

`implementation-sha256.txt` identifies tested code and regressions independently of the evidence-only commit metadata. The final post-commit full-browser log, exact HEAD and GitHub local-safety result will be recorded in the PR body after those runs finish; they are not inferred from partial runs here.

## Preview and limits

The existing `scripts/preview-audio-editor.py` server (PID 24348 when checked) continues on port 55153 and serves this checkout; no other preview was killed. The full post-commit browser run uses that URL. User tabs were not reloaded. Save work before manually refreshing.

Synthetic WAV/M4A, native and bundled WASM decoding and decoded output signal were tested. No physical listening, private user Zoom recordings or design acceptance is claimed. No merge, production mutation, deployment or Closure Record.

## Post-commit run and CI follow-up

The complete uninterrupted Mac browser entry point **passed** on `c9df96dbf51d43642242ec171e65f5405060a27d` through port 55153 (`full-c9df96d.txt`). GitHub run [34645759125](https://github.com/meser-recovery/starter-package/actions/runs/34645759125) passed site and units but failed the new contour comparison with `comparison outside viewport` (`ci-c9df96d-failed.txt`). A ready retained bitmap could still precede the queued seek/scroll update on that runner.

The follow-up changes only that regression: it waits until the canvas covers every comparison coordinate and reads all pixels atomically in the same callback. All amplitude, inter-editor difference, zoom and raster-seam assertions remain; no timeout was increased or assertion removed. Focused both-editor/five-scale/fractional-DPR comparison passed after this change (`consistency-followup.txt`). Final full Mac and exact-HEAD GitHub results are recorded in the PR body, separately from the c9df96d results here.
