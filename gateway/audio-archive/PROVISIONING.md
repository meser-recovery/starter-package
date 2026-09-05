# S08A external provisioning runbook

No command in this document has been run by the implementation task. Provisioning starts only after explicit authorization names all of these exact targets:

- Google Cloud account and `PROJECT_ID`;
- Cloud Run `REGION` and `SERVICE_NAME`;
- runtime `SERVICE_ACCOUNT`;
- public GitHub repository `meser-recovery/audio-archive`;
- GitHub App name/owner and installation ID;
- exact production GitHub Pages `ALLOWED_ORIGIN`.

Do not substitute inferred values. Record the approved values in the change ticket, not in repository source.

## 1. GitHub storage and machine identity

1. Create the public repository `meser-recovery/audio-archive` with branch `main`.
2. Copy only the contents of `storage-repository/` into its initial commit.
3. Create a GitHub App with no user authorization callback and no webhooks.
4. Grant repository permissions only: Contents read/write and Metadata read. Releases use Contents permission.
5. Install the App only on `meser-recovery/audio-archive`, never on all organization repositories.
6. Record the App ID and installation ID in Secret Manager. Store the generated private key directly in Secret Manager; never copy it into this repository or the container image.

Validate the installation scope in GitHub before deploying. The gateway itself also refuses any storage owner/repository other than `meser-recovery/audio-archive`.

## 2. Google Cloud prerequisites

With the explicitly authorized project selected, enable only the APIs required for the chosen build path: Cloud Run, Secret Manager, IAM, Service Usage, and Artifact Registry/Cloud Build if those services are used to build the container.

Create one dedicated runtime service account with no broad project role. Create these five secrets:

- `audio-archive-github-app-id`
- `audio-archive-github-installation-id`
- `audio-archive-github-private-key`
- `audio-archive-password-verifier`
- `audio-archive-session-signing-secret`

Generate the shared password verifier locally with `createPasswordVerifier` from `src/auth.mjs`; store only the resulting `scrypt$...` value. Generate the session signing secret from at least 32 cryptographically random bytes. Do not paste either value into logs or PRs.

Grant the runtime service account `roles/secretmanager.secretAccessor` separately on exactly those five secrets. Do not grant project-wide Secret Manager access, Owner, Editor, or repository permissions to human users for gateway operation.

## 3. Build and deploy

Build `gateway/audio-archive/Dockerfile`, push the immutable image to the authorized project registry, and deploy it to the authorized Cloud Run region/service. Configure:

- public HTTPS invocation so the GitHub Pages browser can reach login and domain endpoints;
- runtime identity set to the dedicated service account;
- secret-to-environment mappings for the five runtime variable names documented in `README.md`;
- `ALLOWED_ORIGIN` set to the exact production Pages origin;
- `STORAGE_BRANCH=main`;
- optional `ACCEPTED_PART_BYTES=16777216`;
- no persistent volume, database, or Google Cloud audio storage.

Cloud Run ingress/authentication settings must allow the browser to invoke the service while application authentication remains enforced by the gateway. Keep the deployed revision URL stable through the Cloud Run service URL.

After the service passes validation, set the neutral `audio-archive-gateway` meta content in the three service HTML entry points to that exact HTTPS service URL and deploy the static site through its existing GitHub Pages workflow. This URL is configuration, not a credential.

## 4. Post-provision validation

Using disposable data, verify every item required by the S08A contract: real shared-password login, cross-origin HttpOnly cookie, CSRF rejection/acceptance, logout, GitHub App installation scope, multi-part upload, byte-identical reconstruction, incomplete-ingestion recovery, archive/restore without binary mutation, concurrent revision conflict, dependency-aware deletion, catalog rebuild, and local S07 processing while the gateway is unavailable.

Inspect Cloud Run logs to confirm they contain request IDs and safe error categories but no password, cookie, CSRF token, GitHub token, private key, verifier or request body. If a Russia-based connectivity test is unavailable, record it as unperformed.

## 5. Rollback

1. Point Cloud Run traffic back to the last validated revision, or set the frontend meta content back to empty to retain local S07-only operation.
2. Do not delete Releases, manifests, transaction records or the storage repository as part of application rollback.
3. If credentials may have leaked, revoke the GitHub App private key and rotate the session signing secret and shared password verifier in Secret Manager; deploy a new revision.
4. Remove an unsafe revision only after traffic has moved away and audit evidence is retained.
5. Destructive storage cleanup requires a separately approved, dependency-reviewed operation through the domain deletion workflow.

