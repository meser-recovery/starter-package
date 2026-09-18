# Browser audio processor runtime

Unmodified official upstream ESM assets, self-hosted for Stage 7. No build step,
package manager, CDN, backend, or runtime npm dependency is used by the site.

- Upstream project: https://github.com/ffmpegwasm/ffmpeg.wasm
- `@ffmpeg/ffmpeg` **0.12.15**: `ffmpeg/` is the minimal browser ESM closure
  from `dist/esm/`: `index.js`, `classes.js`, `types.js`, `const.js`, `errors.js`,
  `utils.js`, and the module `worker.js`. Type declarations, Node's empty entry,
  UMD bundles, and source maps are not needed.
- `@ffmpeg/core` **0.12.10**, official **single-thread** ESM distribution:
  `core/ffmpeg-core.js` and `core/ffmpeg-core.wasm` copied byte-for-byte.
  This is not `@ffmpeg/core-mt`; no SharedArrayBuffer, COOP, COEP, or GitHub
  Pages configuration change is required.

## Artifact provenance

Retrieved from the official npm registry on 2026-09-04:

| Package tarball | Registry SHA-1 (verified) |
| --- | --- |
| https://registry.npmjs.org/@ffmpeg/ffmpeg/-/ffmpeg-0.12.15.tgz | `e5b05c2b5c946f3464b3aa85461e4654a4649d80` |
| https://registry.npmjs.org/@ffmpeg/core/-/core-0.12.10.tgz | `3177e88852bfbfaad5d258e9e0ac1fd9dffd3223` |

Vendored WASM byte size: **32232419**.

Vendored WASM SHA-256:
`9f57947a5bd530d8f00c5b3f2cb2a3492faa7e5d823315342d6a8656d0a6b7b7`

The upstream `const.js` includes an unused default CDN URL/core version. It is
preserved verbatim, not edited. The application always passes explicit same-origin
`coreURL` and `wasmURL` and imports the wrapper only on the user's Run action.
Safety checks guard those overrides and verify that no remote runtime is requested.

## Licenses and source

The npm tarballs omit license files. These upstream texts are included verbatim:

- `licenses/ffmpeg-wasm-MIT.txt`: wrapper license from upstream tag `v12.15`,
  commit `71aa99d37c02a7b4c435275ca9ef50e612f6efa1`, file `LICENSE`:
  https://github.com/ffmpegwasm/ffmpeg.wasm/blob/71aa99d37c02a7b4c435275ca9ef50e612f6efa1/LICENSE
- `licenses/FFmpeg-GPLv2.txt`: `COPYING.GPLv2` from FFmpeg `n5.1.4`:
  https://github.com/FFmpeg/FFmpeg/blob/n5.1.4/COPYING.GPLv2
- `licenses/FFmpeg-LGPLv2.1.txt`: `COPYING.LGPLv2.1` from FFmpeg `n5.1.4`:
  https://github.com/FFmpeg/FFmpeg/blob/n5.1.4/COPYING.LGPLv2.1

The core package declares `GPL-2.0-or-later` (not the wrapper's MIT license).
Upstream's release source, Dockerfile, build scripts, FFmpeg source references,
and bundled codec/library source references are available at:
https://github.com/ffmpegwasm/ffmpeg.wasm/tree/71aa99d37c02a7b4c435275ca9ef50e612f6efa1
The Dockerfile pins FFmpeg `n5.1.4` and enables `libmp3lame`, among other upstream
codecs. This repository does not rebuild or alter that core.
