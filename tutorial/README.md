# Meser Audio Tutorial production pipeline

## Current S11 audio review: B01 first

The [Canonical Content Pack](content/meser-audio-tutorial-canonical-content-pack.md) is the exact narration source. `tutorial.yaml` and its fail-closed `CONTENT_DRIFT` validator map all 14 approved B-blocks and 54 technical scene units without changing PART A. The [current block map](content/S11-Narration-Module-Map.md) names each block; N01–N08 and their generated artifacts are historical.

```sh
python3 tutorial/scripts/build.py validate
PYTHONPATH=tutorial/scripts python3 -m unittest -v tutorial/scripts/test_audio_blocks.py
python3 tutorial/scripts/build.py dry-run --module B01
python3 tutorial/scripts/build.py narration --module B01
```

Only the last command can contact ElevenLabs, and only for B01 while its audio review is pending. A valid cache hit makes zero new TTS requests. The complete B01 remains one continuous request using voice `LHi3adMlU7AICv8Yxpmm`, `eleven_v3`, `ru`, stability `0.5`, and `mp3_44100_128`. The revised request retains `[calm] [conversational]`, reapplies `[slowly]` after each semantic break, uses `[pause]` within paragraphs and `[long pause]` at paragraph boundaries, and sets voice speed to `0.7`. Four topic transitions also add `[pause]`. Because the provider kept a fast phrase rate, `finish_b01_review.py` applies pitch-preserving tempo `0.84` to that single continuous provider take and extends only the marked gaps to aligned targets of `1.0` or `1.4` seconds; it retimes the exact provider character alignment. The original provider MP3 is retained under `provider-source/`. The exact canonical text and punctuation stay separate from provider markup. Character mapping excludes the tags from scene and subtitle alignment. The ignored `generated/narration-blocks-v2/B01/` folder retains the review MP3, alignment/timing, exact transcript, request metadata and hashes; `requests.jsonl` records attempts without the API key. Prior takes are preserved under `takes/` and as named comparison MP3s.

`dry-run --all-modules` is read-only and reports the planned requests for each selected block. Audio generation of B02–B14 and all visual, capture, assembly and video modes are gated until the corresponding review stages and visual migration. The previous implementation and commands below are historical reference only.

The old pilot/module regression tests run against the preserved [v1 specification](content/historical/tutorial-N01-N08.yaml); the current v2 validation and B01 gate use `tutorial.yaml`.

## Historical N01–N08 candidate and visual corrections

The [Canonical Content Pack](content/meser-audio-tutorial-canonical-content-pack.md) controls approved content. `tutorial.yaml` is the executable specification (JSON syntax, a YAML 1.2 subset). `CONTENT_DRIFT` fails closed on changed narration, captions, storyboard goals, mapping or approved pack hash. The approved closing is paragraph n133. The versioned [Narration Module Map](content/S11-Narration-Module-Map.md) defines N01–N08.

## Current full candidate: continuous v3 modules

Run from the repository root with Python 3.12+, Node 22+, FFmpeg/ffprobe and the existing Playwright test dependency (`requirements-test.txt`). No additional package is required for generation/assembly. `venv/bin/python` means the local Python with Playwright installed.

```sh
python3 tutorial/scripts/build.py validate
python3 -m unittest discover -s tutorial/scripts -p 'test*.py'
python3 tutorial/scripts/build.py dry-run --all-modules
venv/bin/python tutorial/scripts/build.py narration --all-modules
venv/bin/python tutorial/scripts/build.py visual --all-modules
venv/bin/python tutorial/scripts/build.py assemble
venv/bin/python tutorial/scripts/build.py verify
python3 tutorial/scripts/module_audio_qa.py
python3 tutorial/scripts/serve_modules.py --port 4196
```

Review: `http://127.0.0.1:4196/index.html`. The loopback server implements HTTP byte ranges for reliable seeking. The page provides all eight module starts, seven boundaries starting five seconds before the join, all 60 scene starts, canonical text, the exact profile, MP4, PCM WAV, SRT/VTT and evidence. Generated media is local and ignored by Git.

- N01: 001–005; N02: 006–018; N03: 019–022; N04: 023–029.
- N05: 030–036; N06: 037–043; N07: 044–055; N08: 056–060.
- Voice `LHi3adMlU7AICv8Yxpmm`, `eleven_v3`, `ru`, `mp3_44100_128`, `{"stability":0.5}`; prefix `[calm] [conversational]` followed by a newline.
- Each module is **one continuous POST** to `/v1/text-to-speech/{voice_id}/with-timestamps`. Its exact scene narrations are joined with two newlines. No scene TTS requests, audio splitting, old fragments or AAC scene concat are used in the current pipeline.
- The key is read from `ELEVENLABS_API_KEY` or local `~/.codex/.env`, never printed, saved or served. The endpoint, body (without credentials), response ID, HTTP status, hashes and paid-request ledger are retained under `generated/narration-modules/`.
- Cache identity covers module ID, ordered scene IDs, exact canonical text, complete profile and module-scoped pronunciation dictionary locators. No pronunciation override is configured. Canonical text remains independent from delivery instructions and dictionaries; pronunciation needs speech review.
- Exact character alignment supplies scene ranges, sentence/phrase ranges and visual cues. Delivery tags are excluded from scene text and subtitles. Hashes cover audio bytes and timing as well as source text, so a new take invalidates dependent visuals even if its request text is unchanged.

## Selective regeneration

```sh
python3 tutorial/scripts/build.py dry-run --module N03
python3 tutorial/scripts/build.py dry-run --module N03 --force
venv/bin/python tutorial/scripts/build.py narration --module N03 --force
venv/bin/python tutorial/scripts/build.py visual --module N03
venv/bin/python tutorial/scripts/build.py assemble
venv/bin/python tutorial/scripts/build.py verify
# Reuse valid cache; only N03 may spend narration credits if missing/stale:
venv/bin/python tutorial/scripts/build.py all --module N03
```

`--scene 020-one-translator` expands to N03; `--chapter NAME` selects complete matching modules. `--force` requires one explicit module and narration/dry-run mode. An incomplete selective build fails when global assembly needs missing unselected modules; it never generates them implicitly. Dry-run reports each reusable module, exact request count/character count and timing-dependent visual misses. Paid errors are not automatically retried; a successfully returned response is retained in `pending/` even if later validation fails.

## Visuals and final audio

The current visual correction uses **Real UI first**. All existing Meser controls, forms, Archive records, project history, final versions, and Editor timelines are recorded from the real loopback frontend with synthetic data. Scenes 005, 011, 044 and 050 therefore join the browser captures: **51 browser scenes / 9 conceptual scenes**. The remaining animations (001–004, 019–022, 060) preserve the approved waveform/object/transformation language and contain no imitation Meser windows. Missing real controls fail the capture; there is no illustrated UI fallback.

`capture_director.py` and `capture_overlay.js` are capture-only. They add a normal visible pointer, eased 300–700 ms motion, real pointerdown ripples, element/section/dialog focus and real drag gestures. Phrase cues use existing module alignment; focus arrival errors are recorded on the original capture clock. Captures are never sped up to fit: only an extra final idle hold is trimmed, and frame rounding gaps are padded. Actions exceeding their alignment range fail validation. Navigation holds the last stable frame until the real destination is ready, preventing initialization frames. Production frontend files are unchanged. Browser requests outside the process-local preview are blocked.

`generated/visual-corrective/` contains the new candidate; `generated/module-candidate/` preserves the preceding review. N01–N08 are reused without TTS requests. The eight MP3 sources are decoded to 48 kHz mono PCM and placed once on a continuous WAV timeline, with 0.35 seconds of silence between modules. Speech samples are never cut or crossfaded. A decay of at most 5 ms is applied only to appended non-speech padding. AAC is encoded once from that PCM master.

For video, each cacheable visual source is decoded/normalized to raw 1920×1080 YUV420P frames at 30 fps. Sequential decoder output feeds **one continuous final H.264 encoder**, with timestamps generated from frame position. No encoded scene packets or GOPs are concatenated into the master; `-c:v copy` is not used. For browser entries, the second decoded frame is held at PTS 0 and 1/30 to replace a possible pre-focus compositor sample; subsequent frame times are unchanged. Scene frame counts are derived from global alignment positions, avoiding accumulated rounding drift. Subtitles use the same global PCM offsets.

`video_qa.py` decodes nine final frames around each of 59 scene boundaries. It fails near-uniform black/white flashes and isolated frame excursions while permitting normal hard cuts. Contact strips and per-frame metrics are retained. Capture QA reports cursor, actual click ripple, element/section/dialog focus, drag and cue timing coverage. Automated checks supplement human review; they cannot certify semantic continuity or visual comfort.

```sh
# Visual-only corrective revision: never invoke narration/all here.
venv/bin/python tutorial/scripts/build.py dry-run
venv/bin/python tutorial/scripts/build.py visual
venv/bin/python tutorial/scripts/build.py assemble
venv/bin/python tutorial/scripts/build.py verify
python3 tutorial/scripts/serve_modules.py --port 4196
```

Review at `http://127.0.0.1:4196/index.html`. Scene links accept `?scene=049-final-download-save`. The page includes all browser scenes, all 59 transitions with seeks two seconds before the cut, module audio boundaries, subtitles and QA evidence. Generated files remain ignored.

`module_audio_qa.py` checks exact inserted silence, source-to-padding and module boundary sample discontinuities, decoded PCM identity, aligned speech gaps and loudness changes. Optional independently produced local ASR evidence is accepted only when all source audio hashes match. These checks supplement full decoding; human assessment of natural delivery remains available through boundary review controls. Generated acoustic and speech evidence is kept separate from the immutable request/timestamp evidence.

Provider reference: [ElevenLabs Create speech with timing](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps).

## Limited narration and visuals pilot (001–006)

The approved greeting was prepended to the existing first canonical paragraph; all later paragraph references and scene definitions remain unchanged. The original full candidate is retained as historical review evidence. It does not contain the new greeting and is not a current build of the revised source. The module build below is the current full candidate; historical pilot commands remain explicitly isolated.

`tutorial.yaml` also specifies the pilot selection, three variants, visual source, and narration anchors that drive animation timing. The pilot retains its historical Multilingual v2 profile in `pilot.narration_profile`; all A/B/C variants use that profile. A preserves the existing request method and copies valid current caches into its own directory. B adds the preceding/following scene text via ElevenLabs `previous_text`/`next_text`. C adds one explicit voice settings configuration. The first scene has no previous context; scene 006 uses the unchanged text of 007 as next context without generating 007. The context is separate from the spoken request `text` and is covered by the narration hash. Exact alignment validation rejects any response that includes extra context characters.

```sh
venv/bin/python tutorial/scripts/build.py validate --pilot
venv/bin/python tutorial/scripts/build.py dry-run --pilot
venv/bin/python tutorial/scripts/build.py narration --pilot
venv/bin/python tutorial/scripts/build.py visual --pilot
venv/bin/python tutorial/scripts/build.py assemble --pilot
venv/bin/python tutorial/scripts/build.py verify --pilot
# Or: build.py all --pilot (reuses valid narration/visual caches)
python3 -m unittest discover -s tutorial/scripts -p 'test*.py'
python3 tutorial/scripts/serve_pilot.py --port 4191
```

Open `http://127.0.0.1:4191/index.html`. Each variant has a complete M4A, a 1920×1080/30 fps H.264/AAC MP4, six scene clips, and SRT/VTT. The page provides scene seek controls, mutually exclusive playback, all C settings, a manual animation scrubber, and links to the manifest, request/cache ledger, and verification evidence. No winner is selected automatically.

Use the dedicated loopback review server above: HTTP byte-range responses are needed for reliable scene seeking in audio/video. It uses only the Python standard library and serves only the pilot output directory.

All pilot output is isolated under `generated/pilot/`. A preservation baseline checks both SHA-256 and modification time of every existing generated artifact, plus scene definitions 007–060, before and after work. The offline fixture test uses a temporary directory. Pilot scene 006 reuses the existing validated local browser capture, trims/pads it to each narration, and scene 005 dissolves into its first real frame. Therefore `visual --pilot` requires that capture and its original deterministic fixture files to be present; it fails clearly if missing or stale. It never contacts the Archive or starts a production environment.

The procedural Canvas source is `animations/pilot.html`. It depicts audio waveforms and edits directly; it has no remote assets or dependencies. Timing comes from each variant's exact ElevenLabs alignment. Changing a neighboring fragment invalidates B/C audio cache; changing the visual source or rendering code invalidates only pilot visual cache. The original no-context cache hash remains compatible. A/B omit `voice_settings` as before; historical provider-side default values were not recorded in old caches and cannot be reconstructed exactly.

Provider reference: [ElevenLabs Create speech with timing](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps).

## Approved visual corrective v2 rollout

The six-scene pilot was approved. The follow-up adds an automatic semantic cursor lifecycle to every browser capture. Concrete controls use cursor only; semantic sections use an outline on the actual element. The cursor starts hidden, hides after a target disappears, changes identity, becomes occluded or moves away, and re-enters near the next explicit target. Dialog/menu transitions never reuse old cursor coordinates. Gestures have an explicit start/end lifecycle. Click feedback precedes transition hiding; a stable unchanged target may retain its cursor.

The full revision is isolated under `generated/visual-corrective-v2-full/`. It reads the existing N01–N08 audio/alignment cache and the nine approved animation clips; missing or stale audio fails without a TTS fallback. Browser scenes are recaptured against the process-local loopback Meser frontend. `corrective_scenes.py` contains only real-UI choreography, with a separate fingerprint per scene for selective visual retries. Neither `tutorial.yaml` nor canonical narration is edited.

```sh
venv/bin/python tutorial/scripts/corrective_full.py check
venv/bin/python tutorial/scripts/verify_cursor_lifecycle.py
venv/bin/python tutorial/scripts/corrective_full.py capture
# Optional selective visual retry; no audio regeneration:
venv/bin/python tutorial/scripts/corrective_full.py capture --scenes 15,16,29,32,50,59
venv/bin/python tutorial/scripts/corrective_full.py assemble
venv/bin/python tutorial/scripts/corrective_full.py verify
python3 tutorial/scripts/serve_modules.py --directory tutorial/generated/visual-corrective-v2-full --port 4198
```

The preserved generated inputs and `evidence/preservation-before.json` are required for this continuation. Review: `http://127.0.0.1:4198/index.html`. The previous full candidate and six-scene approval pilot remain in their original directories. Validation rejects an outlined control, displaced section geometry, visible orphan cursor, late cue, insufficient dwell, rapid post-action movement, missing drag evidence or an overrun of the existing alignment range. The final PCM soundtrack and subtitles must match the preceding candidate byte for byte; the MP4 uses one final AAC encode from that continuous PCM timeline.
