# S10 validation record

Baseline: `24dc631df3dbc9c674d5d357e33d6b96bdf9eee8`.

This record is completed from commands run on the final branch HEAD. S10 changes only the repository runtime, tests, CI, documentation, and repository hygiene. It performs no deployment, production request, archive write, migration, merge, or branch deletion.

## Contract covered

- canonical always-on Speaker project history and capability version 1;
- immutable state on every explicit Speaker project save;
- recipe v2 with exact state linkage on every new Speaker final;
- fail-closed behavior before Speaker mutations for missing, malformed, or unsupported capability;
- local File/Blob/project/render retention and clear user messaging;
- Announcement mutations and compatible archive reads remain available;
- strict legacy recipe-v1 and `speaker/v1` reads remain supported;
- tracked platform junk and the unreferenced empty root file are removed;
- pull-request CI runs the complete static, gateway, frontend Node, and browser gate.

## Local results

All commands ran against the final runtime/test tree on branch `codex/s10-final-architecture-cleanup`:

| Command | Result |
| --- | --- |
| `git diff --check` | PASS |
| `python3 tests/safety/check_site.py` | PASS |
| `npm --prefix gateway/audio-archive run check` | PASS |
| `npm --prefix gateway/audio-archive test` | PASS, 92/92 |
| `node --test tests/safety/*.test.mjs` | PASS, 59/59 |
| `venv/bin/python tests/safety/s09c_portal_smoke.py` | PASS, synthetic local gateway, zero outbound requests |
| `venv/bin/python tests/safety/s09d_project_history_smoke.py --base-url http://127.0.0.1:8000` | PASS at 1280/768/390/320 px; incompatible capability blocks Speaker writes and retains local objects |
| `venv/bin/python -B tests/safety/archive_management_cors_regression.py` | PASS at root and `/starter-package/` with default Chromium web security |
| `venv/bin/python tests/safety/s09a_waveform_motion_smoke.py --base-url http://127.0.0.1:8000` | PASS |
| `venv/bin/python tests/safety/browser_smoke.py --base-url http://127.0.0.1:8000` | PASS; full suite, including 320/390/768/1280 Editor/Archive coverage and blocked outbound archive access |
| tracked `.DS_Store` check | PASS after staging; none in the index |
| retired rollout-switch search in `gateway`, `scripts`, `tests`, `.github` | PASS via equivalent recursive `grep`; no active occurrence (`rg` is unavailable in this checkout environment) |

The first full browser attempt completed the functional suites but hit one transient Chromium scheduler gap in the late waveform-motion benchmark (`maxGap 283 ms`, no desynchronization or image changes). No threshold or implementation was changed. The focused benchmark passed unchanged, and the complete browser suite then passed unchanged on rerun.

Preview: `http://127.0.0.1:8000`. The server remains running for review. The exact reviewed commit SHA and CI run are added to the PR/completion report after commit and push.
