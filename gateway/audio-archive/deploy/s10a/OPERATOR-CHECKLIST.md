# S10A gateway activation checklist (prepared, unexecuted)

This package changes only the `gateway` application container. It does not change HAProxy, Caddy, Xray, DNS, firewall, secrets, GitHub App scope, or archive data.

1. Obtain explicit authorization naming the exact reviewed PR HEAD and the three generated artifact files.
2. Independently compare the PR HEAD, `.source-sha`, archive filename, and `.sha256` manifest.
3. Generate the artifact from a clean reviewed checkout with `package-reviewed-head.sh <full-head-sha> <empty-output-directory>`.
4. Copy the artifact, checksum manifest, source record, guarded activation script, guarded rollback script, and this checklist to the gateway host without changing their contents.
5. Keep both activation gates false until the separate review and authorization are recorded. Never place the password in an argument, environment variable, log, or shell history; provide it in a root-owned mode-0600 temporary file.
6. Review the captured pre-change runtime identity under `/var/backups/meser-audio-archive/s10a/<timestamp>/`. It intentionally excludes environment values and secret contents.
7. Run the guarded activation. Confirm `/healthz`, exact Pages-origin config/CORS, bootstrap and bridge security headers, two independent `Set-Cookie` headers, and cookie replay. Do not display the captured headers or cookie jar.
8. From a trusted Chromium browser, confirm direct password login and mandatory `/v1/session` replay. From the separately authorized real iPhone/Safari, perform the contract's read-only retained-fixture check and record only redacted versions/digests and pass/fail steps.
9. Confirm the trace contains no archive-domain write except session login/logout, and confirm opening Announcement then Speaker makes no second source-part download.
10. On any failure, run `rollback-reviewed-gateway.sh <captured-rollback-directory>` and verify the exact prior image and public health. Preserve the rollback directory and logs for review.

No command in this directory has been executed against production during the CODEX stage.
