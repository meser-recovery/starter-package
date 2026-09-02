# PDF.js vendor files

This directory contains only the PDF.js files required by the Literature reader.

- Version: `5.7.284`
- Build: official `legacy` prebuilt distribution (ES module)
- Worker: matching official `legacy` ES module worker
- Release: <https://github.com/mozilla/pdf.js/releases/tag/v5.7.284>
- Source archive: `pdfjs-5.7.284-legacy-dist.zip`
- Archive SHA-256: `b1edded128a7e50e7818bfe16564eb4012dd3f13f2847f9f94100c96567afbcc`
- License: Apache-2.0; see `LICENSE`

The extracted upstream files were renamed to make accidental use of the modern build visible:

- `build/pdf.mjs` -> `pdf.legacy.mjs` (`1aa308b64ccde6d6270975269ca7848a504579ef5059ea5ada6ea1290b9c1f30`)
- `build/pdf.worker.mjs` -> `pdf.worker.legacy.mjs` (`1f72bf3cf558de85a7190b542e7849886bbea9bc7a40ce610c2c6b4008e07a48`)

The PDF.js 5.7.284 release build configuration targets Safari 16.4+ and Chrome 118+ when transpiling/polyfilling its legacy build. Upstream does not state that this target is equivalent to real-device validation; the project therefore treats real Android Chrome, iPhone Safari, and iPhone Chrome checks as separate manual release gates.
