# Site safety baseline

`site-contract.json` protects stable public URLs, the homepage's principal links, and the BT6 audio asset range. `bt6-player.html` is deliberately a support file rather than a stable public URL; its iframe reference from `AudioBook.html` protects it.

When intentionally adding or removing a stable public URL, update `stable_paths` and the related homepage destinations in the contract in the same change. Keep implementation details, including Nicepage classes, page IDs, and DOM structure, out of the contract.

Run the local static check with `python3 tests/safety/check_site.py`. Run browser smoke tests after installing `pip install -r requirements-test.txt` and `python3 -m playwright install chromium`, then serve the repository over HTTP (for example `python3 -m http.server 8000`) and run `python3 tests/safety/browser_smoke.py --base-url http://127.0.0.1:8000`.

Third-party sites are not blocking dependencies: the checks verify contracted external href values and our JavaScript's generated embed URLs, but never require external services to respond. This keeps the baseline focused on the site's own behavior.
