# S11 · pilot 001–006 · A/B/C review

This report covers the limited follow-up in existing PR [#60](https://github.com/meser-recovery/starter-package/pull/60). No voice variant has been selected as the winner.

## Scope and content

- Branch: `codex/s11-automated-tutorial-production-pipeline`.
- Original S11 starting `origin/main`: `249433e9e6518c92c257d157c8280121ab3e4f98`.
- This follow-up starts from S11 commit `4a99eabc417a3e9ab156175dacb0e8a5f185509a`; it continues that branch without rebasing or rebuilding the full tutorial.
- Pilot selection: `001-purpose`, `002-zoom-multitrack`, `003-announcement-benefit`, `004-speaker-benefit`, `005-two-tools`, `006-archive-open`.
- The exact approved greeting is prepended to the first canonical paragraph. Nothing else in the Pack was changed. Keeping it in `n001` preserves every later canonical reference.
- Pack: `tutorial/content/meser-audio-tutorial-canonical-content-pack.md`.
- Pack SHA-256: `298d7b54918f6983d2ec1d2b2454d52992e9db4b4d3617ec3e00905149e49ee8`.
- `tutorial/tutorial.yaml`: 60 scenes, 9 chapters, 132 canonical paragraph references; a separate `pilot` section defines selection, variants, visual source and spoken-text animation cues.
- Definitions of scenes 002–060 and the default narration settings are identical to the starting commit. No scenes 007–060 were regenerated.

Approved addition:

> Привет. Позвольте представить вам несколько новых возможностей, доступных на сайте Мэсэр в разделе для служащих.

The pasted request ends mid-sentence at “Главное визуально” in Scene 005. The received requirements were implemented; scene 006 retains the approved real-interface capture.

## Narration comparison

| Parameter | A — CURRENT | B — CONTEXT | C — TUNED |
|---|---|---|---|
| Voice ID | `LHi3adMlU7AICv8Yxpmm` | same | same |
| Model | `eleven_multilingual_v2` | same | same |
| Output format | `mp3_44100_128` | same | same |
| Spoken text | approved 001–006 including greeting | identical | identical |
| Previous/next text | omitted | neighboring scene text | neighboring scene text |
| Voice settings | omitted, as in original requests | omitted, as in original requests | explicit settings below |
| Initial cache use | 002–006 reused; 001 generated | six new fragments | six new fragments |

C parameters: `stability=0.45`, `similarity_boost=0.75`, `style=0.0`, `use_speaker_boost=true`, `speed=0.96`. This is one moderate-variation, slightly slower instructional candidate, not a conclusion about audio quality. No alternative voices or models were generated. No seed, language override, request IDs, pronunciation dictionary or text normalization override was added.

Endpoint: `POST /v1/text-to-speech/{voice_id}/with-timestamps`. [ElevenLabs documents previous_text and next_text for continuity](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps). They are separate fields from spoken `text`. Scene 001 has no previous context. Scene 006 uses the unchanged narration of scene 007 as next context; no audio for 007 is generated.

The hash covers exact narration, voice, model, output format, voice settings, pronunciation configuration and supplied context. Legacy no-context hashes remain compatible. Every generated response must have character alignment exactly equal to the approved scene narration. This checks the returned alignment; a human still needs to listen for delivery and audible artifacts.

Generation evidence: 13 new requests / 6,264 spoken-text characters; five existing fragments reused. A second narration run produced 18 cache HIT and zero new generation. The original generation decisions and actual request bodies are retained in `generated/pilot/generation-ledger.json`; the replay log is `generated/pilot/cache-replay.log`.

A/B preserve the original omission of `voice_settings`. Historical values stored on the provider side were not captured in the old cache, so exact historical defaults cannot be reconstructed. All variants retain the same per-scene 0.5 s head / 0.8 s tail padding for a consistent comparison.

## Visual evidence

| Scene | Pilot explanation |
|---|---|
| 001 | Recording and participants lead to website playback and an announcement document. |
| 002 | One colored composite waveform separates into three different stacked waveforms on a shared time axis. |
| 003 | Speaker audio fades out; translation remains with visible empty intervals; those intervals physically contract and the output becomes shorter. |
| 004 | One multitrack view demonstrates normalization, hum reduction, local muting, exclusion of an unwanted participant, synchronized cutting and head/tail trim boundaries. Other voices remain visible during local edits. |
| 005 | Source files enter one Archive record. Tracks open in the editor; a project and two results return to the same record identity. |
| 006 | Existing validated real local Meser editor-to-Archive navigation. Scene 005 dissolves into its first actual frame. |

The first five scenes are deterministic Canvas graphics with short labels, not narration in text cards. `animations/pilot.html` provides manual scene selection, playback and a scrubber. Per-variant animation progress is tied to ElevenLabs character timing through anchors in YAML. Output is 1920×1080, 30 fps. There are no external visual assets or new dependencies.

Scene 006 uses the original real-browser capture and its existing expected-state/network evidence. It is padded or trimmed only in the isolated pilot directory. No new Archive capture or fixture generation was required. The speech-free WAV fixtures and their recipe remain unchanged. The deterministic fixture test now generates into a temporary directory.

## Outputs and validation

The local review server is `http://127.0.0.1:4191/index.html`. Its page offers three full narration players, three videos, 18 scene seek controls, subtitles, settings, and animation inspection. Starting one player pauses the others. Scene seek playback continues across scene boundaries for assessing continuity.

All paths below are relative to `tutorial/`:

- `generated/pilot/index.html` — A/B/C review page.
- `generated/pilot/{a-current,b-context,c-tuned}/pilot.mp4` — three six-scene videos.
- `generated/pilot/{a-current,b-context,c-tuned}/pilot.m4a` — corresponding audio.
- `generated/pilot/{a-current,b-context,c-tuned}/pilot.ru.{srt,vtt}` — aligned subtitles.
- `generated/pilot/{a-current,b-context,c-tuned}/{narration,visuals,clips}/` — independently cached scene artifacts.
- `generated/pilot/manifest.json` — parameters, hashes, scene offsets and durations.
- `generated/pilot/verification.json` — media/coverage/cache/preservation verification and checked commit.
- `generated/pilot/browser-review-check.json` — actual local review UI smoke evidence.
- `generated/pilot/preservation-baseline.json` — original artifact hashes and modification times.

| Variant | MP4 duration | Subtitle cues | Format |
|---|---:|---:|---|
| a-current | 208.156553 s | 58 | H.264 / AAC, 1920×1080, 30 fps |
| b-context | 210.956315 s | 58 | H.264 / AAC, 1920×1080, 30 fps |
| c-tuned | 214.623220 s | 58 | H.264 / AAC, 1920×1080, 30 fps |

Current validation: CONTENT_DRIFT PASS; 16/16 offline unit tests PASS; repository contract PASS; protected frontend inventory 63/63 PASS; Python and JavaScript syntax PASS; diff whitespace PASS. All three final videos passed full FFmpeg decode. All 18 narration alignments match the approved text. Final dry run: 18 narration HIT, 18 visual HIT, zero new TTS characters. All 54 original narration caches for scenes 007–060 remain HIT.

Actual Chromium review-page smoke: three M4A and three MP4 players loaded; A/B/C scene seeks, exclusive playback, every variant's video playback, VTT loading, animation controls and 390 px mobile layout PASS. No page errors or failed HTTP responses; all requests were loopback-only. Desktop and mobile screenshots were inspected. The initial plain HTTP server could not seek media reliably; it was replaced by `scripts/serve_pilot.py` with bounded HTTP byte-range support, then the same smoke passed.

Checked commit is recorded in `generated/pilot/verification.json` after committing. The implementation commit and final PR state are supplied in the completion response.


Preservation checks cover all 324 pre-existing generated files by SHA-256 **and modification time**, including the original full MP4, subtitles, manifests, review clips, narration, captures and fixtures. The original full candidate remains historical evidence from `4a99eabc`; it does not include the approved greeting and was not rebuilt or presented as a current full candidate.

The original S11 vertical slice (002 + 006), full candidate and regression results remain from the earlier implementation. Its GitHub Safety baseline run [36488326383](https://github.com/meser-recovery/starter-package/actions/runs/36488326383) completed successfully. This pilot's new checks are listed separately; the full gateway/frontend suites were not rerun locally because production application code did not change.

## Files and repository boundary

Changes are limited to the Canonical Content Pack, YAML/schema/validator, context-aware narration cache support, the `--pilot` build path, new pilot renderer/review assembly, tests, documentation and the existing S11 CI test step. Original explanatory animations, browser capture scripts, production frontend/gateway, meeting generation, Pages configuration and archive assets are unchanged.

New source files: `animations/pilot.html`, `scripts/pilot.py`, `scripts/test_pilot.py`, `scripts/serve_pilot.py`, `PILOT-REVIEW.md`.

Modified source files: `README.md`, `content/meser-audio-tutorial-canonical-content-pack.md`, `schemas/tutorial.schema.json`, `scripts/build.py`, `scripts/narration.py`, `scripts/test_s11.py`, `scripts/validate.py`, `tutorial.yaml`, plus the S11 test command in `.github/workflows/safety-baseline.yml`.

No production deployment or Production Audio Archive mutation was performed. Browser generation is procedural and offline; scene 006 is reused from the loopback-only in-memory capture. Generated heavy media, API credentials and environment files are not committed. PR #60 remains for review; no merge or branch deletion is part of this work.
