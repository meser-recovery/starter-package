# Site safety baseline

`site-contract.json` protects stable public URLs, the homepage's principal links, and the BT6 audio asset range. `bt6-player.html` is deliberately a support file rather than a stable public URL; its iframe reference from `AudioBook.html` protects it.

When intentionally adding or removing a stable public URL, update `stable_paths` and the related homepage destinations in the contract in the same change. Keep implementation details, including Nicepage classes, page IDs, and DOM structure, out of the contract.

Run the local static check with `python3 tests/safety/check_site.py`. Run browser smoke tests after installing `pip install -r requirements-test.txt` and `python3 -m playwright install chromium`, then serve the repository over HTTP (for example `python3 -m http.server 8000`) and run `python3 tests/safety/browser_smoke.py --base-url http://127.0.0.1:8000`.

Third-party sites are not blocking dependencies: the checks verify contracted external href values and our JavaScript's generated embed URLs, but never require external services to respond. This keeps the baseline focused on the site's own behavior.

## S09 audio archive management

`browser_smoke.py` also runs `archive_management_smoke.py`. Its JSON-lines bridge
(`archive_management_bridge.mjs`) uses the real authenticated gateway app, client,
and domain with `MemoryRepository`; it opens no network listener. The S09 browser
context allows only the local static server and intercepted `gateway.test` requests.
All other destinations, including production and GitHub assets, are blocked.
The 0.25-second synthetic MP3 fixture contains a generated sine tone, no user audio.

S09's focused Node tests are `gateway/audio-archive/test/archive-management.test.mjs`.
The requirement mapping and execution results are in [S09-validation.md](S09-validation.md).
Selected screenshots and their exact source revision are indexed in
[evidence/s09/README.md](evidence/s09/README.md).
