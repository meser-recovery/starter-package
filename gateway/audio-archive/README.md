# Audio Archive gateway

Stateless Node.js gateway for the S08A Source Session archive and S08B Announcement publishing workflow. The browser authenticates with one shared service password; only this service holds the GitHub App installation credentials that can write to the dedicated `meser-recovery/audio-archive` repository. Canonical state remains in versioned JSON files and GitHub Releases. The self-hosted VM contains no application database and is not canonical audio or metadata storage.

## Speaker project history

Speaker project history is the gateway's canonical runtime behavior. `/v1/config` always advertises `speakerProjectHistory: 1` as the protocol-version contract. Each explicit Speaker project save atomically advances the existing `draftRevision`, updates the current draft, and creates one immutable `project-states/<sessionId>/speaker/<draftRevision>.json` record in the same archive commit. The server fingerprints canonical JSON containing project identity, source revision, normalized `speaker/v1` payload, and full ordered source provenance. Persisted idempotency receipts make a lost-response retry return the original state without advancing the revision.

Authenticated history routes return a newest-first summary and one strictly verified state at a time. Continuation into a newly ingested exact source set remaps track IDs by ordinal and cryptographic identity, creates revision 1 in the replacement recording, and confirms both supersession relations atomically. New Speaker finals use recipe v2 and must link the exact current state revision and fingerprint; recipe v1 remains readable without migration. See [S09D-SCHEMAS.md](S09D-SCHEMAS.md).

The browser treats a missing, malformed, or unsupported capability as an incompatible gateway for Speaker mutations. It does not fall back to legacy draft or recipe-v1 writes. Existing compatible records remain readable and downloadable, and local files, browser-only editing, the local project, and a locally rendered MP3 remain available without an archive mutation. Announcement behavior is independent of this Speaker capability.

## Announcement publication

Processing remains local in the browser. Publication is a separate confirmed operation implemented as a durable job:

1. `POST /v1/source-sessions/:sessionId/outputs/announcement/publications` validates the current Source Session/draft/provenance and atomically reserves `nextVersion`.
2. `PUT /v1/announcement-publications/:transactionId/blobs/:blobId/parts/:partNumber` uploads one bounded, hash-verified opaque part to the existing Source Session Release.
3. `POST /v1/announcement-publications/:transactionId/finalize` verifies every stored part and the whole logical SHA-256, then atomically exposes the output and immutable recipe.
4. `GET /v1/announcement-publications/:transactionId` and the maintenance endpoints expose resumable state. `cancel` stops the current attempt without reclaiming its version; `discard` explicitly closes the job without deleting orphan assets automatically.

Output metadata and parts are retrieved only through authenticated canonical identity routes. The client verifies part order, size, per-part hash, total size, and whole hash before playback/download. Presentation media type and filename come from the recipe, never a request parameter.

Canonical S08B records are:

- `transactions/publish-<transactionId>.json` — mutable durable upload/finalization progress;
- `recipes/<sessionId>/announcement/<outputId>.json` — immutable after finalization;
- `blob-<blobId>-part-NNNN.bin` — opaque Release assets in `audio-session-<sessionId>`;
- `workflows.announcement.outputs[]` — visible finalized descriptors only.

Version numbers are reserved monotonically at begin time and are never reused. Only finalization may establish `result_ready`. Pending or cancelled jobs block lifecycle/deletion mutations until finalized or explicitly discarded. Exact record fields and invariants are documented in [S08B-SCHEMAS.md](S08B-SCHEMAS.md).

## Local validation

Requires Node.js 22 or newer.

```sh
npm run check
npm test
```

The test suite uses a deterministic in-memory repository and mocked GitHub HTTP responses. It creates no external resources.

## Self-hosted runtime

The approved runtime target is an Ubuntu 24.04 VM. Host-level HAProxy routes TLS ClientHello traffic by SNI: exact `meserproject.duckdns.org` traffic goes to loopback Caddy, while every other connection remains on the existing Xray REALITY path. Caddy terminates TLS for that hostname, serves the immutable protected frontend, applies an internal gateway auth subrequest, and proxies same-origin `/v1/*` to the gateway over the Compose-private network.

Committed non-secret deployment artifacts are in [`deploy/self-hosted/`](deploy/self-hosted/):

- `compose.yaml`: custom gateway and Caddy/frontend images share a dedicated private network; Caddy publishes host TCP `80` and loopback-only `127.0.0.1:9443`; the gateway publishes no host port;
- `Caddy.Dockerfile`: digest-pinned Caddy image containing the reviewed Caddyfile and allowlisted protected frontend;
- `Caddyfile`: public health/login allowlist, internal auth gate, protected static delivery and same-origin `/v1/*` reverse proxy;
- `haproxy.cfg`: host-level TCP/SNI passthrough with unconditional Xray default;
- `deployment-state.template.md`: required unresolved discovery/evidence record.

Canonical protected frontend sources and their fail-closed inventory live under `service/frontend/`. Root GitHub Pages service paths are compatibility forwarders only. This repository change does not deploy or restart either container and does not mutate production archive data.

## Runtime configuration

Non-secret environment variables:

- `ALLOWED_ORIGIN=https://meserproject.duckdns.org`: exact canonical same-origin service origin;
- `GITHUB_APP_ID` and `GITHUB_APP_INSTALLATION_ID`: machine identity identifiers;
- `STORAGE_OWNER=meser-recovery` and `STORAGE_REPOSITORY=audio-archive`: fixed canonical target;
- `STORAGE_BRANCH`: defaults to `main`;
- `ACCEPTED_PART_BYTES`: defaults to 16 MiB and cannot exceed 64 MiB;
- `SESSION_LIFETIME_SECONDS`: defaults to four hours and cannot exceed four hours;
- `ACTIVE_SESSION_LIMIT`: bounded in-memory session-registry capacity;
- `PORT`: defaults to `8080`.

Sensitive values are read once at startup from read-only files:

- `GITHUB_APP_PRIVATE_KEY_FILE=/run/secrets/github-app.pem`;
- `SHARED_PASSWORD_VERIFIER_FILE=/run/secrets/shared-password-verifier`;
- `SESSION_SIGNING_SECRET_FILE=/run/secrets/session-signing-secret`.

Missing, unreadable, non-text or empty secret files fail startup without including their contents in the error. Only the final text-file newline is removed; embedded PEM newlines are preserved. Direct secret environment variables are not a runtime interface.

Compose sources these mounts from the supplied existing `/etc/meser-audio-archive/` directory, expected to be `root:root` mode `0700`. Because local Compose implements file secrets as bind mounts, host files use `root:root` mode `0640`; the gateway runs with non-root UID `1000` and root group GID `0` solely to read those root-group files. The files are never world-readable, and the container is neither root nor privileged. Gate 2 must verify the supplied ownership and modes before they are relied on.

## Security boundaries

- Login verifies the shared password with scrypt only in the gateway.
- The only accepted auth cookie is the host-only `__Host-meser_service_session`, carrying an opaque signed session identity with `Secure; HttpOnly; SameSite=Lax; Path=/` and bounded `Max-Age`.
- Active sessions and CSRF state live only in the bounded in-memory registry; logout, expiry, eviction and gateway replacement invalidate them fail closed.
- Every non-safe authenticated request also requires the session-bound CSRF token.
- State-changing `/v1/*` requests require the exact configured service Origin. Cross-origin Pages API access and wildcard CORS are not supported.
- Request bodies, part sizes and schemas are bounded and validated.
- Browser clients receive no GitHub write token, private key, password verifier or signing secret.
- The GitHub adapter exposes fixed domain operations, not a general-purpose repository proxy.

See [PROVISIONING.md](PROVISIONING.md), the prepared full-stack operator scripts under `deploy/s10a/`, and the recovery tooling under `deploy/recovery/`. Every host, activation, restore, timer and real-backup command is explicitly unexecuted by this repository-only task.
