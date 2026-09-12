# S09A — first mixdown and compression-scale evidence

This is implementation evidence for draft PR #36, not an acceptance or closure
record. The implementation base was
`a5d29503e088ef1e11e48c06e351692ee3882ed8`. All long sources were generated
locally and were not committed.

## Shipped behavior

Speaker loudness cache misses use a bounded queue. Zero or one miss uses the
main FFmpeg instance only. Two or more misses use the main instance plus one
temporary auxiliary instance when `navigator.hardwareConcurrency >= 4` and
`navigator.deviceMemory >= 8`. Missing `deviceMemory` is recorded as unknown
capacity and selects the conservative sequential path. An internal benchmark
override can select one or two workers without changing the UI or recipe.

Each instance executes one analysis at a time. An analysis always has one input
at index zero and its own bounded log listener. Results are bound by operation
identity, track ID, and cache key, then committed to the cache in canonical
track order after every required measurement succeeds. The auxiliary FS holds
only its current task input. It is deleted and the auxiliary Worker is
terminated before the unchanged final graph runs on the main instance.

Auxiliary load failures and diagnosed Worker infrastructure failures cause one
bounded retry of unfinished work on the main instance. DSP errors, invalid
loudnorm JSON, and user cancellation do not retry. Cancel/close/source changes
abort the queue, terminate the operation-owned instances, await in-flight queue
promises, and prevent later tasks or cache writes. Cleanup uses captured engine
references rather than a later `state.engine`.

The compression range and ticks now share a wrapper and the same width in each
layout. Four explicit positions account for the 16 px native thumb. The full
labels and current selected value remain visible. Browser geometry checks cover
two rendered controls, values 0–3, embedded/expanded/compact layouts, 390 px and
desktop widths, and layout zoom 100/125/150%. Screenshots:

- `speaker-compression-normal.png`
- `speaker-compression-expanded.png`
- `speaker-compression-compact-narrow.png`

## Cold benchmark

Headless Chromium 151.0.7922.34 ran on the same Apple Silicon Mac against the
same local preview. Sequential and parallel three-track runs used separate new
browser contexts, empty measurement caches, the same HTTP cache conditions,
and the same three one-hour AAC/M4A sources and settings (gentle enhancement,
leveling on, light compression). The source sizes and full profiles are in the
adjacent JSON files.

| Cold run | Analysis wall | Final graph | Result waveform | Full browser wall | Main-window JS heap |
| --- | ---: | ---: | ---: | ---: | ---: |
| 3 tracks, forced sequential | 240.087 s | 272.449 s | 3.829 s | 516.857 s | 10.0 → 10.0 MB |
| 3 tracks, forced parallel | 129.564 s | 272.320 s | 3.800 s | 406.157 s | 33.1 → 33.1 MB |
| 1 track, forced override `2` | 60.911 s | 106.529 s | 3.773 s | 171.746 s | 60.3 → 60.3 MB |

The parallel three-track run reduced analysis wait by 46.0% and complete first
mixdown wall time by 21.4% (110.700 seconds). Auxiliary load took 67.7 ms. The
one-track policy still selected concurrency one and created no auxiliary input
or Worker; its wall result remains close to the earlier 169.452 s cold control.

Both three-track outputs are 3,600 seconds, 57,600,912 bytes, and have SHA-256
`6e25aebf3cdf089c9d89eb08eb39ef0601d94f877a628eacb486b41e3011fad9`.
The short isolated-context regression additionally requires exact equality of
all five parsed loudnorm measurements per track, DSP settings, final
normalization logs, duration, and MP3 SHA-256 between concurrency one and two.

`performance.memory` describes the page heap, not the auxiliary Worker's WASM
memory or total browser process footprint. The figures above therefore do not
prove absence of memory pressure. Peak OS process memory was not isolated
reliably from Chromium's other processes. The bounded two-instance policy,
single auxiliary input, prompt termination, FS deletion, and conservative
capability threshold constrain the added load.

## Limited ebur128 and sample-rate experiment

The vendored WASM build lists both `ebur128` and `loudnorm`. A real eight-second
scan showed that ebur128 reports integrated loudness, integrated and LRA
thresholds, LRA, and true peak, but does not emit loudnorm's `target_offset`.
Its summary and gating surface are not a drop-in source for all five strict
fields consumed by the existing two-pass graph. No ebur128 substitution,
derived constant, approximation, or schema change was shipped.

Verbose logging of the unchanged debug-only render showed the actual path for
a 16 kHz mono fixture: input `s16 16000 Hz` → explicit `s16p 48000 Hz` →
loudnorm's automatic `dbl 192000 Hz`; `amix` also ran at 192 kHz, followed by
the existing limiter, then automatic `fltp 48000 Hz` conversion for the MP3
encoder. This confirms that dynamic loudnorm keeps the high rate through the
downstream graph. No downsample or forced linear mode was shipped because that
would alter true-peak and DSP behavior.

## Regression coverage

- Node tests cover 0/1/2/3 policy decisions, the two-worker maximum, reverse
  completion binding, stop-on-failure, abort, and reuse after cancellation.
- Browser render tests cover 0/1/2/3 misses, cache hits, two concurrent Workers,
  per-engine input isolation, exclusion/reorder, invalid results, auxiliary
  load fallback, cancellation of both Workers, retry, and exact cold
  sequential/parallel equivalence.
- The full repository browser suite retains mono/stereo 44.1/48 kHz, different
  duration/padding, cuts, silence, dynamic fallback, archive, playback,
  waveform, zoom, Follow, selection, and both editor regressions.

No user recording was used or uploaded. Physical listening, Safari/Firefox,
physical pinch input, and production archive access were not tested.
