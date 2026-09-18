# S10A FIX requirement / evidence matrix

Status: repository implementation evidence only. This is not independent acceptance, merge authorization, deployment evidence, recovery readiness, or proof of behavior on real iPhone/Android devices.

| Requirement | Implementation evidence | Automated / visual evidence | Status |
| --- | --- | --- | --- |
| Canonical same-origin boundary | `service/frontend/`, custom `Caddy.Dockerfile`, `Caddyfile`, private `gateway:8080`, relative `/v1` client | gateway/self-hosted tests, frontend inventory, focused browser suite | Covered locally; container validation delegated to CI |
| One server-side session | `__Host-meser_service_session`, signed opaque ID, bounded in-memory `SessionRegistry`, restart invalidation | auth/app tests cover attributes, tamper, unknown, expiry, eviction, retired-cookie rejection/clearing and logout revocation | Covered locally |
| Login requires replay | `/login` submits once and accepts success only after authenticated `GET /v1/session` returns CSRF | client/gateway tests plus focused browser request trace | Covered locally |
| Caddy protected delivery | only health, login document and minimal login assets bypass `forward_auth`; `/internal/*` is publicly hidden | self-hosted topology tests; browser unauthenticated redirect/direct-route checks | Covered locally; `caddy validate` delegated to CI |
| Pages/public separation | root service paths are compatibility stubs; ordinary public content remains on Pages and service links use the canonical origin | `check_site.py`, Node safety tests and public Chromium smoke | Covered locally |
| Strict deep-link transfer | Archive forwards only `session`; Editor forwards only `session`, `workflow`, `projectRevision`, `speakerOutput`; duplicates, unknowns, fragments and malformed values are dropped | compatibility parser and site-contract assertions | Covered locally |
| No superseded auth | client verifier, sessionStorage authority, Storage Access state machine, bootstrap/bridge routes, dual-cookie and Archive login/connect UI removed | production-string/static scans and gateway/frontend tests | Covered locally |
| Common reconnect | shared `ServiceSessionController`; exact expiry message; 401 reconnect only, 403 stays an authorization error; auth-generation fencing | focused browser suite preserves a synthetic local `File` across expiry/re-login and distinguishes 403 | Covered in Chromium locally; all engines in CI |
| Canonical prepared source batch | strict manifest/part/track validation, authenticated full download, byte/hash verification, authoritative reread and atomic commit retained | existing client/unit tests remain green | Covered locally |
| Progress/cancel/stale/shared Files/read-only open | abort/generation fencing and previous-context preservation retained; Announcement/Speaker receive exact prepared `File[]` | existing Node/browser regressions and static safety checks remain in the suite | Covered locally/CI |
| Reproducible full-service release | deterministic reviewed-source archive, digest-pinned gateway/Caddy images, OCI source labels and release manifest | packaging/topology tests and CI Docker/Caddy validation | Prepared, unexecuted |
| Guarded activation/rollback | two false gates; pre-cutover recovery prerequisite; both containers captured/replaced/rolled back; no `compose down` | shell syntax and static operator tests | Prepared, unexecuted |
| Encrypted recovery | age X25519, exact three-secret allowlist, mount marker + mountpoint guard, integrity manifest, clean-machine runbook, disabled timer, retention tooling | synthetic create/integrity/decrypt rehearsal in CI | Prepared; local `age` unavailable; no real backup |
| Responsive protected UI | landing, Archive and Editor exercised at 320/390/768/1280 with overflow checks | focused Chromium smoke | Covered locally |
| Real devices / operational restore | separate authorized desktop, iPhone/Safari, Android/Chrome and off-VM decrypt/restore gates | none claimed in this repository stage | Intentionally unperformed |

## Superseded visual evidence

The PNG files under `tests/safety/evidence/s10a/` document the rejected cross-origin Storage Access implementation from the earlier S10A iteration. They are retained only as historical artifacts and **must not be used as acceptance evidence** for this FIX. Current acceptance evidence is the deterministic same-origin browser suite; it uses synthetic data and never contacts production.

Current Chromium screenshots are under `tests/safety/evidence/s10a-fix/`: landing, Archive and Editor at 320, 390, 768 and 1280 CSS pixels. They were inspected for layout/overflow and contain synthetic empty-archive/local-WAV state only. Login/reconnect password fields, cookies and CSRF values are intentionally not captured.

No merge, Pages/VM deployment, production activation, timer installation, real secrets backup, secret rotation, or archive mutation was performed for this matrix.
