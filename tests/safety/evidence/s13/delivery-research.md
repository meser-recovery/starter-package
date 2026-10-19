# S13 audio delivery research

The source route remains **GitHub Releases → existing vmhome Gateway → browser**. No deployment, credentials, network configuration or CSP was changed.

| Boundary | Verified fact | Evidence / limit |
| --- | --- | --- |
| Browser → Gateway | `sourcePartFetch()` maps only parts belonging to the selected validated manifest to authenticated `/v1/source-sessions/.../content`; arbitrary URLs are rejected. | Shared client tests and S13 byte-identity/authorization regressions. |
| Gateway → GitHub | GitHub App authorization remains server-side; the reader calls GitHub's API asset endpoint using the existing fetch runtime. The domain verifies returned bytes. | `src/github.mjs`, `downloadSourcePart()`, github/config and frontend integration tests. An actual GitHub redirect chain was not probed; no server token is returned by the list projection. |
| Existing protected CSP | `connect-src 'self'` and `media-src 'self' blob:` are the checked-in Caddy policy. A cross-origin browser asset fetch is outside that existing policy. | `deploy/self-hosted/Caddyfile`; this is a source fact, not a fresh observation of the installed Caddy image. |
| Direct browser fetch | Actual GitHub Release asset byte readability, CORS headers and redirect behavior in Chromium/Firefox/WebKit/mobile: **NOT_RUN**. | No disposable public Release test asset was supplied. Private/server credentials were not sent to browsers, and a download link is not treated as fetch evidence. No claim that GitHub universally prevents direct fetch. |
| Browser matrix | Chromium, Firefox and Playwright WebKit exercise the unchanged Gateway route against synthetic loopback resources. | Browser reports; WebKit is not physical Safari, narrow emulation is not physical Android. |
| Remote users / production | Geographic latency and production measurements: **NOT_RUN**. | Injected RTT/bandwidth profiles are local models only. |

Cold server waveform generation still obtains its own canonical source bytes through the existing repository reader. Browser verified bytes are not uploaded back to the server. The existing derived waveform cache, native process limit 1, queue 4 and cleanup remain intact; warm waveform hits do not reconstruct source parts. This is measured separately from verified browser source transfer and must not be reported as an eliminated cold download.

Direct browser fetch was not adopted. No edge proxy, Worker, CDN, hosting migration, persistent audio cache or new infrastructure was introduced.
