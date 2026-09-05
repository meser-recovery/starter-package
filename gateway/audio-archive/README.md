# Audio Archive gateway

Stateless Node.js gateway for S08A. The browser authenticates with one shared service password; only this service holds the GitHub App installation credentials that can write to the dedicated public `meser-recovery/audio-archive` repository. Canonical state remains in versioned JSON files and GitHub Releases. The service does not use an application database and does not store audio in Google Cloud.

## Local validation

Requires Node.js 22 or newer.

```sh
npm run check
npm test
```

The test suite uses a deterministic in-memory repository and mocked GitHub HTTP responses. It creates no external resources.

## Runtime configuration

Non-secret environment variables:

- `ALLOWED_ORIGIN`: one exact HTTPS GitHub Pages origin, without a path or trailing slash.
- `STORAGE_BRANCH`: storage repository branch; defaults to `main`.
- `ACCEPTED_PART_BYTES`: accepted upload part size; defaults to 16 MiB and cannot exceed 64 MiB.
- `SESSION_LIFETIME_SECONDS`: defaults to four hours and cannot exceed 24 hours.
- `PORT`: supplied by Cloud Run; defaults to `8080` locally.

Secret values supplied from Google Secret Manager:

- `GITHUB_APP_ID`
- `GITHUB_APP_INSTALLATION_ID`
- `GITHUB_APP_PRIVATE_KEY`
- `SHARED_PASSWORD_VERIFIER`
- `SESSION_SIGNING_SECRET`

`STORAGE_OWNER` and `STORAGE_REPOSITORY` are deliberately fixed to `meser-recovery/audio-archive`; attempts to point the gateway elsewhere fail startup. Never place any of the five secret values in frontend files, Git, container layers, PR text, command logs or HTTP responses.

## Security boundaries

- Login verifies the shared password with scrypt only in the gateway.
- The signed session is carried in a `Secure; HttpOnly; SameSite=None; Partitioned; Path=/` cookie.
- Every non-safe authenticated request also requires the session-bound CSRF token.
- `/v1/*` accepts one exact configured origin and returns credentialed CORS headers only to it.
- Request bodies, part sizes and schemas are bounded and validated.
- Browser clients receive no GitHub write token, private key, password verifier or signing secret.
- The GitHub adapter exposes fixed domain operations, not a general-purpose repository proxy.

See [PROVISIONING.md](PROVISIONING.md) for the explicit external provisioning checkpoint and rollback procedure.

