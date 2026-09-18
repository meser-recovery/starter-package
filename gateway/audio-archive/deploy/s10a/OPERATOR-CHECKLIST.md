# S10A full-service activation checklist (prepared, unexecuted)

This package replaces the Meser `gateway` and custom `caddy` application containers together. It must not edit HAProxy, Xray/REALITY, x-ui, MTProxy, n8n, router, DNS, firewall, secrets, GitHub App scope, or archive data.

1. Obtain explicit authorization naming the exact reviewed PR HEAD, source tree and generated full-service artifact hashes.
2. Independently verify the source SHA/tree, source archive, gateway image archive, Caddy/frontend image archive and release manifest.
3. Create and integrity-check an encrypted recovery bundle on a verified off-VM mount. Keep the age private identity outside the production VM.
4. Capture the current gateway/Caddy container IDs, image IDs, Compose/Caddy checksums and HAProxy checksum without printing environment or secret values.
5. Keep both authorization gates in `activate-reviewed-service.sh` false until the separate review and authorization are recorded. Supply the smoke password only in a root-owned mode-0600 file.
6. Validate the candidate with `docker compose config` and the pinned Caddy image before replacement.
7. Replace only `gateway` and `caddy`; preserve Caddy volumes and never use `docker compose down`.
8. Run the script's zero-write smoke: health, unauthenticated denial, one-password login, `/v1/session` replay, protected routes, automatic Archive access, Editor/config and logout.
9. Separately perform the authorized read-only retained-fixture/source-integrity checks. Confirm the request trace contains no archive mutation.
10. On failure, run `rollback-reviewed-service.sh <captured-rollback-directory>` to restore both prior application containers. Preserve the rollback identity and redacted logs.

The superseded gateway-only scripts are hard-disabled. No command in this directory was executed against production during the repository stage.
