# S09 delta-fix · test CORS

Base: `3bc6132e25ed1ec20e665f7f3d2ffa7120114678` (current origin/main, merge PR #33).
Branch: `codex/s09-test-cors-subpath-fix`. Validation date: 2026-09-10.

## Change

The S09 mock previously emitted `Access-Control-Allow-Origin: base_url.rstrip('/')`.
A Pages site URL includes `/starter-package`, which is not part of its origin.
The mock now separates the site URL (retaining its mount) from `scheme://authority`
(including the port). One shared response function supplies that exact origin for
successful responses, bridge errors, OPTIONS, and injected listing errors.
Page URL construction retains the subpath and normalizes its trailing slash.

The new `archive_management_cors_regression.py` mounts the repository at both `/`
and `/starter-package/` on a temporary loopback HTTP server with an allocated
nonstandard port. It runs the existing full S09 scenario suite unchanged in scope,
plus credentialed browser fetch assertions for OPTIONS 204, route-not-found 404,
and injected listing failure 503. The subpath case additionally asserts that every
static request remains under `/starter-package/`. The full site browser suite calls
this regression automatically; it does not replace or skip its existing S09 check.

## Before / after

- [Before](before.log): exit **1** with the original erroneous CORS expression and
  the new regression. Root `http://127.0.0.1:50546` passed all S09 scenarios (193
  gateway requests). `/starter-package/` failed at the initial `ready()` wait with
  the existing **30000 ms** timeout. The root-pass log also contains a harmless
  cancelled static response / BrokenPipe traceback from the initial local server;
  the harness now handles cancelled static responses without that log noise.
- [After](after.log): exit **0**. Root and `/starter-package/` both passed on port
  **50711**, with **193** in-memory gateway requests per case and zero outbound
  archive access. OPTIONS and error statuses were readable by browser fetch, so
  they were not merely successful callbacks hidden behind browser CORS rejection.
- [Full browser smoke](full-browser.log): exit **0**, including the ordinary local
  site checks, the original S09 check, the new root/subpath regression, and retained
  editor / DSP browser coverage. Each of the three S09 invocations passed 193 local
  gateway requests. The regression used a fresh allocated nonstandard port.

Chromium was launched with `playwright.chromium.launch()` and no security-disabling
flags. CORS protection, credentials, assertions, and original timeouts remain enabled.
No wildcard origin or permissive production CORS change was introduced.

## Exact commands and results

Commands were run from the repository root using its existing venv. No dependency
installation was needed.

```sh
# Before the CORS fix: rc 1. After the fix: rc 0.
venv/bin/python -B tests/safety/archive_management_cors_regression.py

# Separate local server process; started successfully.
python3 -m http.server 8000 --bind 127.0.0.1

# Full local site smoke, including both local mount regressions: rc 0.
venv/bin/python -B tests/safety/browser_smoke.py --base-url http://127.0.0.1:8000

# Static contract: rc 0, "Site contract check passed."
python3 tests/safety/check_site.py

# Python syntax: rc 0, 3/3 PASS, without writing bytecode.
venv/bin/python -B -c "import ast,pathlib; files=['archive_management_smoke.py','archive_management_cors_regression.py','browser_smoke.py']; [ast.parse((pathlib.Path('tests/safety')/f).read_text(), filename=f) for f in files]; print('Python syntax: 3/3 PASS')"

# rc 0.
git diff --check
git status --short --branch
```

The full general-site smoke ran at the root localhost URL. The **full S09 scenario
suite** ran at both root and subpath; this does not claim that all unrelated general
site smoke assertions were executed against a subpath base URL.

## Scope and isolation

Changed files are only `tests/safety/archive_management_smoke.py`,
`archive_management_cors_regression.py`, `browser_smoke.py`, `README.md`, and this
new evidence directory. Product frontend, gateway/client/domain/auth, DSP, workflows,
settings, infrastructure and audio data are unchanged. The synthetic archive is
served exclusively by the existing in-memory bridge. Its routing denies real archive
and GitHub asset requests; the existing full-suite network isolation remains intact.

Original branch `codex/s09-archive-management-re-scope` remains at
`d0540f75b609da48f39220a4b9d78a86a56501e8`; historical `evidence/s09/` is unchanged.
Production-safety run **34428935220 remains FAILURE** and was not rerun. No merge,
manual deployment, live archive action, PLAN/MASTER update or S09 COMPLETE declaration
is part of this fix. A successful production-safety run on a future merge SHA is still
required after separate acceptance and merge.
