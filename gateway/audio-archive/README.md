# Audio Archive gateway

Stateless Node.js gateway for the S08A Source Session archive and S08B Announcement publishing workflow. The browser authenticates with one shared service password; only this service holds the GitHub App installation credentials that can write to the dedicated `meser-recovery/audio-archive` repository. Canonical state remains in versioned JSON files and GitHub Releases. The self-hosted VM contains no application database and is not canonical audio or metadata storage.

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

The approved runtime is an existing Ubuntu 24.04 VM. Host-level HAProxy routes TLS ClientHello traffic by SNI: exact `meserproject.duckdns.org` traffic goes to loopback Caddy, while every other connection remains on the existing Xray REALITY path. Caddy terminates TLS only for the gateway hostname and proxies to the gateway container over the Compose-private network.

Committed non-secret deployment artifacts are in [`deploy/self-hosted/`](deploy/self-hosted/):

- `compose.yaml`: Caddy publishes host TCP `80` and loopback-only `127.0.0.1:9443`; the gateway publishes no host port;
- `Caddyfile`: ACME/TLS and reverse proxy to `gateway:8080`;
- `haproxy.cfg`: host-level TCP/SNI passthrough with unconditional Xray default;
- `deployment-state.template.md`: required unresolved discovery/evidence record.

The frontend retains the accepted production gateway origin. This repository change does not deploy or restart that gateway and does not mutate production archive data.

## Runtime configuration

Non-secret environment variables:

- `ALLOWED_ORIGIN=https://meser-recovery.github.io`: exact GitHub Pages browser origin;
- `GITHUB_APP_ID` and `GITHUB_APP_INSTALLATION_ID`: machine identity identifiers;
- `STORAGE_OWNER=meser-recovery` and `STORAGE_REPOSITORY=audio-archive`: fixed canonical target;
- `STORAGE_BRANCH`: defaults to `main`;
- `ACCEPTED_PART_BYTES`: defaults to 16 MiB and cannot exceed 64 MiB;
- `SESSION_LIFETIME_SECONDS`: defaults to four hours and cannot exceed 24 hours;
- `PORT`: defaults to `8080`.

Sensitive values are read once at startup from read-only files:

- `GITHUB_APP_PRIVATE_KEY_FILE=/run/secrets/github-app.pem`;
- `SHARED_PASSWORD_VERIFIER_FILE=/run/secrets/shared-password-verifier`;
- `SESSION_SIGNING_SECRET_FILE=/run/secrets/session-signing-secret`.

Missing, unreadable, non-text or empty secret files fail startup without including their contents in the error. Only the final text-file newline is removed; embedded PEM newlines are preserved. Direct secret environment variables are not a runtime interface.

Compose sources these mounts from the supplied existing `/etc/meser-audio-archive/` directory, expected to be `root:root` mode `0700`. Because local Compose implements file secrets as bind mounts, host files use `root:root` mode `0640`; the gateway runs with non-root UID `1000` and root group GID `0` solely to read those root-group files. The files are never world-readable, and the container is neither root nor privileged. Gate 2 must verify the supplied ownership and modes before they are relied on.

## Security boundaries

- Login verifies the shared password with scrypt only in the gateway.
- The signed session is carried in a `Secure; HttpOnly; SameSite=None; Partitioned; Path=/` cookie.
- Every non-safe authenticated request also requires the session-bound CSRF token.
- `/v1/*` accepts only the configured GitHub Pages origin and returns credentialed CORS headers only to it.
- Request bodies, part sizes and schemas are bounded and validated.
- Browser clients receive no GitHub write token, private key, password verifier or signing secret.
- The GitHub adapter exposes fixed domain operations, not a general-purpose repository proxy.

See [PROVISIONING.md](PROVISIONING.md) for the four gated, transactional future deployment phases and rollback requirements. Every host command there is explicitly unexecuted by this repository-only task.
