# Archive waveform sidecar contract

Archive waveforms are derived, read-only data. They never change Source Session
manifests, source assets, project history or canonical audio.

## Endpoint and identity

`GET /v1/source-sessions/{sessionId}/blobs/{blobId}/waveform` accepts exactly two
canonical UUID path identities and no query parameters. The Gateway resolves the
track, parts, sizes and SHA-256 digests from the canonical Source Session
manifest. The route requires the common service session. It accepts no client
URL, path, digest, filename or filesystem identity.

## Peak representation

- algorithm: `meser-peaks-f32le-v1`;
- exactly 65,536 IEEE-754 Float32 values;
- little-endian byte order;
- exactly 262,144 response bytes;
- every value is finite and in `[0, 1]`;
- every bin covers its ordered fraction of the complete decoded duration;
- silence is `0`, and absolute samples above full scale are clamped to `1`;
- short and long inputs use the same 65,536-bin representation;
- the existing renderer consumes the returned `Float32Array` unchanged.

The response reports source SHA-256 and peak-body SHA-256 separately. The client
validates both identities, the response size and every peak before publication.

## Resource and lifecycle limits

- maximum canonical source: 500 MiB;
- maximum decoded duration: 8 hours;
- active native FFmpeg processes: 1;
- queued distinct cache keys: 4;
- per-job timeout: 12 minutes;
- native stdout and source streams use bounded 64 KiB buffers;
- captured native stderr is capped at 32 KiB and is never returned to clients;
- cache maximum: 256 MiB with deterministic oldest-mtime/name eviction.

Parts are streamed sequentially into a mode `0600` temporary file. Each part and
the combined source are verified while streaming. Native FFmpeg output is
aggregated directly into the fixed peak array; decoded PCM is never accumulated.
Temporary source files are removed after success, failure, timeout, cancellation
or shutdown. Native processes receive `SIGKILL` on timeout/cancellation.

Concurrent requests coalesce only when algorithm version, canonical source
SHA-256 and peak count are identical. One disconnected subscriber does not
cancel a job that still has another subscriber.

## Disposable cache

Cache records contain a bounded JSON header followed by the fixed binary peak
body. Header identity, body length and result SHA-256 are verified on every read.
Corrupt entries are removed and regenerated. Publication uses a mode `0600`
temporary file, `fsync` and atomic rename.

The root-owned cache directory is mounted only on the private Gateway container;
the runtime UID receives write access through private group `0`. It has no Caddy
route and is not part of Archive or recovery data. A clean restore without the
volume starts normally and regenerates peaks on demand.
