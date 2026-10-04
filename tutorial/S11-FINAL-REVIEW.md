# S11 · Complete approved-block candidate

Status: **READY FOR S11 ACCEPTANCE**. The complete film requires separate user acceptance.

## Delivered candidate

- MP4: `generated/s11-final-review/S11.mp4`.
- Duration: **1305.800 s / 21:45.800**; **39,174 frames**.
- SHA-256: `eb0356f191f8bb4b7b2d4f64e6b1a05b3a1543938fd41fb2ec03a725d62193b9`.
- Format: 1920×1080, 30 fps, yuv420p, H.264; mono 44.1 kHz AAC.
- Player: <http://127.0.0.1:4218/s11-final-review/index.html?v=eb0356f191f8>.
- Exact inputs / offsets / commands: `generated/s11-final-review/manifest.json`.
- PCM master: `S11-master.wav`; global alignment: `S11-alignment.json`.
- Subtitles: `S11.ru.srt`, `S11.ru.vtt`, extracted `S11.embedded.ru.srt`.
- Navigation: `navigation.json`; checks: `verification.json`, `boundary-report.json`, `source-preservation.json`, `browser-player-check/report.json`.

All paths without another prefix in this report are under `generated/s11-final-review/`. Generated media remains local and excluded from normal Git history.

## Approved inputs

All 14 current `AUDIO_APPROVED` / `BLOCK_APPROVED` records were checked against actual MP4, MP3, WAV/PCM, alignment, subtitle and visual-source files before assembly. Exact input digests are pinned in the manifest and `approvals/`. It selects the latest reopened B01/B02, the shortened B09 and animated B14 ending. Historical candidates are excluded. B02's current accepted MP4 is `8b122abd98ca9552d568c7179e0627a31547eb78f843cb34b070bdfb8b15ca6d`.

The master preserves every sample from each approved WAV byte for byte, in order. No source speech was trimmed, stretched, faded, amplified, re-synthesized or split into new phrase takes. Interblock quiet is exactly 35,280 samples (0.8 s) at |sample| ≤ 8, accounting for existing quiet and the incoming 0.6 s picture pre-roll. A ≤5 ms decay shapes only newly appended boundary samples. No silence was added inside a block. There are **0 TTS requests and 0 block rebuilds**.

The visual input is the decoded picture stream of each approved block MP4. This retains accepted capture, cursor and montage fixes. Source AAC is excluded. Existing picture frames remain in order; final frames are briefly held where needed to align the interblock gap. The delivered movie receives one H.264 encode and one AAC encode from its single PCM master. The first unsuccessful normalization attempt was discarded; no intermediate encoded movie was used as an input.

## Verification performed

- `CONTENT_DRIFT`: current 14-block / 54-scene text and storyboard pass unchanged.
- All 57,585,780 master PCM samples checked; every approved source segment is identical. Decoded final AAC zero-lag correlation to the master: **0.9999507541**; no block AAC concatenation or editor sound overlay.
- Entire final MP4 decoded: **39,174 frames**, no blank/black frames. Every frame compared to its approved source (including held ends); maximum mean gray difference after the final lossy encode: **0.1536 / 255** or less. No introduced crop, scroll, reordered frame or cursor relocation.
- **13** interblock pauses measured in the master; **53** consecutive technical scene boundaries inspected with before/at/after frames. The 53 include the 13 block boundaries. All boundary windows pass; contact sheets remain under `boundary-sheets/`.
- Full-frame short screen/scroll-return scan runs across the whole film. Eight clustered-change candidates at three locations were retained for explicit inspection, rather than silently treating them as failures or ignoring them. B03 at **04:12.567–04:12.667** contains a brief real loading-status modal after selecting the archive recording; it does not return to the earlier screen. B10 at **12:35.833–12:36.333** contains the approved result-panel expansion followed by one-way scrolling. B11 at **14:37.767–14:37.867** contains the approved explainer's exit to the real Archive page. These are inside approved source blocks, away from assembly boundaries, and are preserved. No short A→B→A screen return was detected. Detailed findings: `transition-candidates.json` / `transition-review.json`.
- Extracted **359** `mov_text` cues from the delivered MP4. All canonical text, cue order and timings match the global SRT; final cue is **«Спасибо за внимание.»**. Browser VTT also has the same 359 cues and times, with the final cue active at its actual time.
- Actual served MP4 SHA matches the checked file; HTTP Range returns 206 and `video/mp4`. Chromium native-player checks exercise all block links, all 53 boundaries in motion, beginning/middle/end, seek, changing rendered frames while time advances, and playback after returning to the tab. The native in-app player was also opened and checked visibly. Evidence remains in `browser-player-check/`.
- Approved original hashes, sizes and modification times remain unchanged; `source-preservation.json` checks **248** protected files. No production mutation, publication, activation or merge.

Direct listening was unavailable. PCM identity and AAC checks establish preservation and synchronization; they do not establish natural intonation or perceptual audio quality.

## Repository / CI

Local checks: tutorial unit suite, repository contract, gateway syntax/tests and frontend Node tests. Exact commands, counts and final HEAD are saved in `repository-validation.json`. CI results for the final pushed HEAD are saved separately in `ci-results.json` and linked from PR #60.

The preceding HEAD's CI failed because approval integration tests required large ignored local media files in a clean checkout. Tracked approval relationships and canonical hashes now run everywhere; actual binary validation remains mandatory before assembly and in local integration tests. Offline synthetic tests exercise approval/binary tampering and complete subtitle extraction, so no product test or safety control is weakened. Large historical media fixtures are explicitly skipped when absent from CI.

Branch: `codex/s11-automated-tutorial-production-pipeline`; PR #60 remains open. B01–B14 approvals are preserved; acceptance of this whole candidate is pending.
