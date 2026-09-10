Current execution supersedes the pending/blocked state in this historical recovery note: [corrective audit](S09A-corrective-audit.md) and [new evidence](evidence/s09a/corrective/README.md). The original recovery narrative below is retained as history.

# S09A corrective editor work — pending browser acceptance

Base: PR #35 squash `5a3e793e6e33e1a15e27dd6408e733c87d9a939f`.

The user reported two real Zoom M4A files remaining visible in Announcement but
failing Speaker preparation, and rejected the retained large-card editor layout.
The exact user-file decoding exception has not been reproduced; no user audio
was available. This change addresses the identified fragile preparation path
and the approved PLAN §§12–13 layout requirements. It is not a closure record.

## Changes

- Prepare source waveforms sequentially. Short clips use Web Audio with fallback
  to the bundled FFmpeg; recordings over two minutes go directly to FFmpeg.
  Preview-only mono/8 kHz analysis produces a fixed 1400 × 100 envelope image.
  Input bytes and final-render DSP/filter/codec semantics stay unchanged.
- Keep selected File references and project payload after preparation failure.
  Name the failed file, offer explicit retry, and keep edit/save/render disabled
  until every source is prepared. Abort preparation on close/new source and
  retain epoch guards. An unprepared source set is not labelled saved.
- Use continuous track lanes with a shared time ruler, narrower controls,
  compact desktop buttons and full-height waveforms. Group Speaker controls
  beside each lane, remove phantom grid rows and card gaps, and retain 44 px
  controls on mobile. Existing selection/cut/silence/monitoring semantics remain.

## Validation

Executed in Work:

- `python3 tests/safety/check_site.py`: PASS.
- `npm --prefix gateway/audio-archive run check`: PASS.
- `npm --prefix gateway/audio-archive test`: 80/80 PASS.
- Changed JavaScript/Python syntax and `git diff --check`: PASS.
- Native FFmpeg: generated a synthetic 1:02:27 AAC/M4A and decoded it with
  the preview filter into a nonempty 1400 × 100 RGBA image: PASS. This verifies
  the filter with native FFmpeg, not its browser/WASM execution.

Browser execution and screenshots: **PENDING**. Local Chromium download failed;
the Work browser rejects the local server URL. No screenshot or full browser
pass is claimed. The real user's M4A files still require reproduction/verification.

New `s09a_editor_corrective_smoke.py`, integrated into `browser_smoke.py`, generates
AAC/M4A using the bundled codec and synthetic tones only. It covers native decode
failure fallback, failed decoder load with retained exact Files and retry, two
1:02:27 inputs avoiding native decoding, actual cut/undo, no archive writes, and
lane density/mobile overflow at 320/390/768/1280. With `--screenshot-dir`, it saves
both editors under `s09a-corrective/` for visual review against the approved PLAN.

The previous mismatch test expected the file list to be destroyed. It now
requires retained file rows and retry while preserving disabled editing/save,
no candidate and zero writes. The lazy-FFmpeg static check now also allows the
small DOM-only timeline module; FFmpeg still loads only after valid selection.

Required before acceptance: run the full browser suite, inspect before/after
screenshots, resolve any failures, and verify the reported M4A scenario. No merge
or production activation is authorized by this implementation note.

## Recovery on 2026-09-10

The user supplied `S09A-editor-corrective (1).patch` after workspace cleanup.
It contains only the original `95d902f` change; the stable patch ID after
application is `6f530202525ea9fe2ef515118d79068499e52aaf`, matching the attachment.
The later local `52d5559` change is absent from this patch. Its additional
selection/context actions, archive interaction changes and full requirements
audit are not recovered here. This branch is therefore a partial recovery,
not the complete corrective implementation or acceptance of all 43 sections.

Fresh recovery checks: site contract PASS, changed JS/Python syntax PASS,
gateway syntax PASS, gateway tests 80/80 PASS, and diff whitespace PASS.
The native FFmpeg result above belongs to the earlier run and was not repeated
during recovery. Browser and visual acceptance remain pending.

The user explicitly authorized publishing this corrective branch, creating a
draft PR and running CI, without merge or production changes. The draft PR
must retain the incomplete-recovery and pending-acceptance limitations above.

Publication remains blocked: HTTPS git push had no credentials, and the GitHub
connection rejected tree creation with HTTP 403 `Resource not accessible by
integration`. No remote branch or PR was created and CI was not started.
The fresh official Chromium installation also timed out; no browser PASS is
claimed for this recovery.

To publish this recovered subset from an authenticated local checkout, first
download `S09A-editor-recovered.patch` and run the following commands. Stop on
any error; do not merge the PR. The fixed base intentionally matches PR #35.

```sh
git fetch origin
git switch -c codex/s09a-editor-corrective-ux 5a3e793e6e33e1a15e27dd6408e733c87d9a939f
git am "$HOME/Downloads/S09A-editor-recovered.patch"
git push -u origin codex/s09a-editor-corrective-ux
```

Then create a draft PR targeting `main`, with this file as its description:

```sh
gh pr create --draft --base main --head codex/s09a-editor-corrective-ux --title 'S09A: recover Speaker preparation and compact lanes (partial)' --body-file tests/safety/S09A-corrective-ux.md
```
