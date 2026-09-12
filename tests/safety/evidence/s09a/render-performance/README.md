# S09A — one-shot tools and Speaker render performance evidence

This is implementation and review evidence for draft PR #36. It is not an
acceptance or closure record. The comparison base is
`419869e5f91c1b057a92c1bd2585540a7c057fe1`.

## Implemented behavior

- Cut and Silence are one-shot Speaker tools. A successful region commit
  consumes the armed tool; invalid or zero selections, rejected commits and
  `pointercancel` retain it. Escape disarms it. Selection, region restoration,
  handle drag and history traversal do not arm it.
- Successful loudnorm measurements use a 128-entry in-memory LRU. Its canonical
  key contains the File-object identity, analysis and processor versions,
  bundled FFmpeg build, exact normalized analysis graph, original duration,
  global cuts, per-track silence and enhancement. Compression, track order,
  region IDs, monitoring and other UI state do not change the key.
- Each analysis `EXEC` receives one input and uses graph input zero. The final
  `EXEC` receives only included tracks and uses an explicit compact
  `trackId -> input index` map.
- The loaded Speaker engine is retained between renders. For results longer
  than 120 seconds, waveform extraction reads the already prepared result path
  from that engine. Temporary inputs, filter scripts, waveform bytes and event
  listeners are removed after success, failure or cancellation.
- The UI reports the active render stage and elapsed time at 2.5 updates per
  second without rebuilding the timeline. Cancellation remains tied to the
  operation and source epochs.
- Speaker zoom records the browser-rounded synchronized scroll position before
  queued scroll events run. This removes a reproduced race where adjacent
  slider values resolved to the same `px/s` and an immediate manual scroll
  could leave the retained waveform canvas outside the viewport.
- A localhost request to the configured production archive now explains the
  known origin restriction. Gateway CORS, credentials and production settings
  are unchanged.

The Announcement editor was audited. It runs silence detection rather than the
Speaker two-pass loudness analysis, so the Speaker measurement cache is not
applied to it. Its existing shared waveform reader, progress, cancellation and
temporary-file cleanup remain covered by the full browser suite.

## Reproducible browser benchmark

`tests/safety/s09a_render_benchmark.py` runs the actual page, bundled Worker and
WASM engine. The benchmark used headless Chromium 151.0.7922.34 on the same
Apple Silicon Mac for before and after runs. All tracks used gentle enhancement,
leveling on and light compression, with no cuts or silence. Sources were
synthetic one-hour AAC/M4A files generated locally:

| Source | Sample rate | Channels | Duration | Size |
| --- | ---: | ---: | ---: | ---: |
| hour-330-44k-mono.m4a | 44.1 kHz | 1 | 3600 s | 29,556,739 B |
| hour-440-48k-stereo.m4a | 48 kHz | 2 | 3600 s | 29,615,865 B |
| hour-550-48k-mono.m4a | 48 kHz | 1 | 3600 s | 29,766,204 B |

One-track results:

| Build/run | Wall | Analysis | Final graph | Result waveform | Analysis cache |
| --- | ---: | ---: | ---: | ---: | --- |
| base cold | 175.630 s | 61.730 s | 109.630 s | 3.820 s | unavailable |
| optimized cold | 169.452 s | 60.597 s | 104.539 s | 3.611 s | 0 hit / 1 miss |
| base repeat | 178.613 s | 61.622 s | 112.467 s | 3.773 s | unavailable |
| optimized repeat | 108.530 s | 0 s | 104.469 s | 3.615 s | 1 hit / 0 miss |

Three-track results:

| Build/run | Wall | Analysis total | Final graph | Result waveform | Analysis cache |
| --- | ---: | ---: | ---: | ---: | --- |
| base cold | 523.668 s | 243.915 s | 274.954 s | 3.826 s | unavailable |
| optimized cold | 518.955 s | 238.256 s | 276.377 s | 3.845 s | 0 hit / 3 miss |
| base repeat | 506.226 s | 234.663 s | 267.062 s | 3.906 s | unavailable |
| optimized repeat | 281.995 s | 0 s | 277.717 s | 3.776 s | 3 hit / 0 miss |

The optimized repeat saved 70.083 seconds (39.2%) for one track and 224.231
seconds (44.3%) for three tracks. The first new-material render remains almost
unchanged, as expected: the cache cannot avoid a required first analysis. The
final graph remains the dominant warm-run cost and was not relabeled as a
separate limiter measurement.

The one-track MP3 SHA-256 was
`7a2ed13407ac6ab7aea51f000d398eba6ce1c2d408d6001e33333db441aa4d91`
for base cold/repeat and optimized cold/repeat. The three-track SHA-256 was
`6e71e4bc29d5add21eb4c2da6ce92b1db97e6e7b8097f7a7c6f43d73ecf2d332`
for all four corresponding runs. Exact MP3 equality confirms the I/O and cache
changes did not alter these deterministic outputs.

The final FFmpeg log records `Normalization Type`. The controlled short browser
fixture fell back to `Dynamic`; this is recorded rather than hidden. No
resampling, loudness target, compression, limiter, bitrate or processor recipe
was changed. A multithreaded core would require a different WASM distribution
and cross-origin-isolation headers, so it is outside this static GitHub Pages
change.

`performance.memory` was available but coarse and unchanged within each
cold/repeat pair (about 60.3 MB for the base one-track context, 31.2 MB for its
separate optimized context, and 10 MB for both three-track contexts). Separate
contexts and browser GC make cross-build heap values unsuitable as an
improvement claim. Worker counts, bounded cache entries, and file/listener
cleanup showed no accumulating resources. Large input bytes are therefore read
once per render rather than retained in another unbounded in-memory cache.

## Regression coverage and limits

- Node tests cover canonical key dependencies, LRU promotion/eviction, copied
  values, invalid-measurement rejection, weak File identity/reset, processor and
  engine versioning, and compact non-contiguous input mapping.
- The real-browser regression counts Worker `EXEC` messages for cold/repeat,
  compression, one-track enhancement and silence, common cut, exclusion,
  reorder, return, cancellation/retry, Undo/Redo, replacement by new File
  objects, and repeated invalid loudness output. It also checks actual final
  normalization log entries and stage transitions.
- Existing browser coverage exercises stale source epochs, metadata/draft
  revisions, mono/stereo 44.1/48 kHz, padding, cuts, silence, final duration,
  result/source isolation and cancellation during result waveform preparation.
- One-shot tool coverage exercises pointer and keyboard commits, a second drag
  without a new edit, re-arming, invalid selection, pointer cancel, Escape,
  restoration by region ID and history.
- The same-file, both-editor 80/159/160/300/1000 px/s parity fixture was run
  three times consecutively after the zoom/scroll race correction.

No user Zoom recording was used or uploaded. The synthetic benchmark does not
claim physical listening, Safari/Firefox performance, a physical pinch gesture,
or production archive access. Final repository gates and GitHub CI are run and
reported against the resulting PR HEAD.
