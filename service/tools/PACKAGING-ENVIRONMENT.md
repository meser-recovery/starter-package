# Deterministic source packaging environment

`package-reviewed-service.sh` is the sole source-archive entry point. It fixes
`LC_ALL=C` and `TZ=UTC`, uses Git's commit/tree-backed `tar` archive, and applies
`gzip -n` so the gzip header contains neither a host timestamp nor an input
filename. The archive contains only `gateway/audio-archive`, `service/frontend`,
and `service/tools` from the exact full commit SHA; mutable working-tree files
are never read into the archive.

The canonical packaging baseline is the GitHub `ubuntu-24.04` runner with
Node.js **24.7.0** selected by `actions/setup-node`; Git and GNU gzip are the
runner-provided Ubuntu 24.04 tools. The byte format is fixed by `git archive
--format=tar` plus `gzip -n`, rather than embedding tool-version metadata. The
script also remains usable with compatible Git/gzip implementations for local
diagnostics, but only the pinned CI OS/Node job is acceptance evidence. Node
runs the protected-frontend inventory verifier. CI creates the artifact twice in independent empty
directories and requires byte equality plus identical SHA-256 records. This
byte-for-byte double build is authoritative reproducibility evidence; printed
tool versions are diagnostic metadata only and are not embedded in the archive.
