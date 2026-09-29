# Meser Audio Tutorial production pipeline

The approved [Canonical Content Pack](content/meser-audio-tutorial-canonical-content-pack.md) is the content authority. `tutorial.yaml` is the executable build specification and uses JSON syntax, a YAML 1.2 subset, so the pipeline needs no YAML parser package. The validator fails with `CONTENT_DRIFT` if the approved pack identity, narration, captions, scene coverage, or storyboard goals differ. A semantic change must be approved in the Content Pack before the build specification changes.

Run from the repository root. Python 3.12+, Node 22+, FFmpeg/ffprobe, and the existing `requirements-test.txt` Playwright dependency are required for full media generation. `venv/bin/python` below denotes any Python with Playwright installed.

```sh
python3 tutorial/scripts/build.py validate
python3 tutorial/scripts/build.py dry-run
python3 tutorial/scripts/build.py dry-run --scene 038-speaker-global-cut
python3 tutorial/scripts/fixtures.py
python3 tutorial/scripts/test_s11.py
python3 tutorial/scripts/build.py verify  # after complete local assembly
```

The one build entrypoint is `tutorial/scripts/build.py`. It supports `all`, `narration`, `visual`, `assemble`, `dry-run`, `validate`, and full-candidate `verify`, with `--scene ID`, `--chapter NAME`, or `--slice` selection. `--slice` is the two-scene vertical slice (animation 002 and real Meser browser scene 006). `narration --scene ID --force` explicitly spends credits to regenerate that scene. `visual --animations-only` selects graphics. A selected scene/chapter produces a separately named candidate; only an unfiltered complete build writes `generated/final/meser-audio-tutorial-ru.mp4`.

For browser capture, start the existing in-memory preview with a tutorial-specific part size for the synthetic WAVs:

```sh
S11_PREVIEW_PART_BYTES=262144 node tests/safety/s10b_preview_server.mjs 4185 http://localhost:4185
venv/bin/python tutorial/scripts/build.py all --slice --base-url http://localhost:4185
```

The preview serves the real protected frontend and real gateway logic with a process-local `MemoryRepository`. Its synthetic password is `local-test-password`. A new server process resets demo state. The default preview behavior used by existing safety tests stays at 1024-byte parts. Capture rejects non-loopback origins and blocks all browser requests outside the local preview. No production Archive endpoint or credential is used.
For a full build, omit `--base-url`; the entrypoint starts a fresh in-memory preview for each browser scene so recordings cannot share demo Archive state.

The ElevenLabs key is loaded from `ELEVENLABS_API_KEY` or local `~/.codex/.env`; it is never copied to the repository or output. Each scene's cache hash covers exact text, voice, model, output format, voice settings, and pronunciation configuration. A valid MP3 and character alignment with a matching hash avoids a second API request. Generated media is ignored by Git under `tutorial/generated/`. The recipe in `fixtures/recipes/` contains only deterministic, speech-free synthetic tones and disturbances.

Scene review clips and a local HTML index are written under `generated/review/`. A successful complete assembly writes SRT/VTT, `generated/manifests/build.json`, and the 1920×1080/30 fps H.264/AAC master. FFmpeg decodes the candidate before atomic rename. `generated/` is intentionally local review evidence and is not committed.

## Limited narration and visuals pilot (001–006)

The approved greeting was prepended to the existing first canonical paragraph; all later paragraph references and scene definitions remain unchanged. The original full candidate is retained as historical review evidence. It does not contain the new greeting and is not a current build of the revised source. Do not run an unfiltered full build for this pilot.

`tutorial.yaml` also specifies the pilot selection, three variants, visual source, and narration anchors that drive animation timing. The pilot uses the same Voice ID/model in all variants. A preserves the existing request method and copies valid current caches into its own directory. B adds the preceding/following scene text via ElevenLabs `previous_text`/`next_text`. C adds one explicit voice settings configuration. The first scene has no previous context; scene 006 uses the unchanged text of 007 as next context without generating 007. The context is separate from the spoken request `text` and is covered by the narration hash. Exact alignment validation rejects any response that includes extra context characters.

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
