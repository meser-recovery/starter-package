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
