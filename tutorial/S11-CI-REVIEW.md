# S11 CI correction: waveform reads during navigation

The complete S11 candidate is unchanged and still awaits separate acceptance.

## Failure and reproduction

The [original local-safety failure](https://github.com/meser-recovery/starter-package/actions/runs/37230780820) checked `4daf7ed5e03e8101c2ab89cd60aac298a2ea1a31`. S10B WebKit reported `Cannot load blob:… due to access control checks` from `speaker-waveform.mjs` / `FileReader.readAsArrayBuffer`.

Reproduction used Linux x86_64, Ubuntu 24.04, Python **3.14.7**, Node **24.7.0**, Playwright **1.63.0**, Chromium **153.0.8010.12**, Firefox **155.0**, and WebKit **26.6** (CI browser revisions 1243 / 1543 / 2359). The official Playwright Noble image and official Actions Python / Node binaries were used with an isolated process-local Archive preview. No production credentials or storage were available.

The controlled case holds a detached audio probe's successful `loadedmetadata` callback until `beforeunload`. The File is created in the main world and retained independently of the file input. It is not freed, and no application object URL is revoked. Releasing metadata during navigation reproduces two late reads and the same WebKit access-control page error on the old runtime. This also removes Playwright's `set_input_files` payload implementation from the failing path.

The sequence is: waveform preparation starts in the editor → navigation starts → pending metadata completes → its promise continuation starts FileReader, potentially followed by the FFmpeg fallback → `pagehide` cancellation arrives later. The reported Archive reconnect phase is sampled when the error is delivered; it is not the start of the waveform operation. The historical log has no per-read timestamps, so the exact historical filename cannot be recovered from that log. The controlled reproduction establishes the lifecycle race and records its ordering.

WebKit's FileReader loader creates its own temporary public blob URL through the request-loading layer ([primary source](https://github.com/WebKit/WebKit/blob/main/Source/WebCore/fileapi/FileReaderLoader.cpp)). Thus an internal URL absent from application create/revoke logs does not establish premature application revocation.

An ordinary diagnostic run with lifecycle tracing [passed without a product fix](https://github.com/meser-recovery/starter-package/actions/runs/37234145567). It was retained as diagnostic evidence, not treated as resolution. The controlled regression fails the old implementation independently of that incidental pass. Local x86_64 emulation also exposed an unrelated login action stability timeout; the controlled reproduction avoids that UI wait, while the final CI retains the original UI actions and deadlines.

## Minimal correction

- `audio-processor.mjs`: cancel the active operation at `beforeunload`, retaining the existing `pagehide` cleanup and FileReader AbortSignal cancellation.
- `speaker-waveform.mjs`: cross a task boundary before beginning a file read, then recheck disposal / cancellation. Promise continuations can run between unload listeners; an unload listener alone was proven insufficient. The task boundary lets cancellation complete before WebKit starts another blob load in the departing document.
- `s10b_browser_smoke.py`: retain file-read / navigation diagnostics and add the controlled metadata-navigation regression. It checks that metadata was actually released, no late FileReader started, and no Archive write was introduced. The existing final `page_errors` assertion remains strict. A→B with different and identical filenames, declined transitions, payload restoration, reconnect, write counts, responsive checks and outbound-request checks remain intact.

No error filter, browser exclusion, retry-to-pass policy, runtime upgrade, media rebuild or TTS request was added.

## Validation and evidence

- Controlled Linux regression: **PASS Chromium, Firefox, WebKit**; no page errors and no late reads. The same regression rejected the old runtime with the original WebKit error.
- Frontend Node safety suite: **110/110 PASS**, including cancellation of an already pending FileReader.
- Protected frontend inventory: **63 files PASS**; JavaScript syntax, repository contract, whitespace and canonical-content validation pass.
- The full final-HEAD `local-safety` gate, exact HEAD and concrete run link are recorded in PR #60 and `generated/s11-ci-webkit-review/FINAL-RESULT.md` / `final-ci.json`. The gate includes all original browser suites, inventory, deterministic packaging twice, Compose/Caddy validation, encrypted recovery and Docker rollback/clean-restore/Caddy runtime. `production-safety` must remain normally **SKIPPED**.

Raw old failure, insufficient-listener experiments, fixed three-browser results, native CI logs and preservation evidence remain under `generated/s11-ci-webkit-review/`. They are local diagnostics excluded from normal Git history. The corrected isolated interface preview remains at <http://localhost:4183/Audio-Editor.html>.

S11 MP4 SHA-256 remains `eb0356f191f8bb4b7b2d4f64e6b1a05b3a1543938fd41fb2ec03a725d62193b9`. The preservation check covers 254 approved / final files, including audio, alignment and subtitles. The original movie and all B01–B14 sources are not rebuilt or overwritten. No merge, publication or production activation is performed.
