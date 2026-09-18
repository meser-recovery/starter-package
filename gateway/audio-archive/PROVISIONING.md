# S10A full-service deployment and recovery runbook

**Status: repository-only preparation. Every VM, router, DNS, production, restore, timer and real-backup command is unexecuted.**

This document does not authorize discovery, installation, secret creation, cutover or rollback. The canonical application origin is `https://meserproject.duckdns.org`; the public site remains on GitHub Pages. HAProxy/Xray routing is an existing host-level boundary and is not changed by S10A application activation.

## Repository validation

Run from an exact reviewed checkout:

```sh
python3 tests/safety/check_site.py
npm --prefix gateway/audio-archive run check
npm --prefix gateway/audio-archive test
node --test tests/safety/*.test.mjs
node service/tools/verify-frontend.mjs
git diff --check
```

When Docker is available, render Compose with validation-only identifiers and exact candidate image references, then validate Caddy using the pinned image. CI additionally starts the restored synthetic stack and tests the actual Caddy response path; no production secret or archive is used.

Evidence must show:

- only Caddy maps host `80` and loopback `127.0.0.1:9443`; gateway has private `expose` only;
- gateway and Caddy use the dedicated private network;
- only gateway receives the three secret files;
- Caddy contains the immutable allowlisted frontend and reviewed Caddyfile;
- both images carry the exact source SHA and use digest-pinned bases;
- HAProxy configuration is byte-for-byte unchanged;
- GitHub remains canonical archive storage and no credential material is packaged.

## Reviewed release creation

`service/tools/create-release.sh <exact-sha> <empty-output-directory>` is the future offline release entry point. It refuses a dirty checkout, packages reviewed source only, builds both images with exact-SHA OCI labels, saves immutable image archives and writes `release-manifest.txt` with exact image refs/IDs, source tree, base digests and Compose/Caddy/HAProxy checksums. `service/tools/PACKAGING-ENVIRONMENT.md` defines the canonical packaging environment; CI builds twice in independent empty directories and requires byte-identical source archives and SHA-256 records.

Do not build a release from mutable `/opt` state. Do not include credentials, runtime data or logs. The recovery bundle separately creates an allowlisted non-secret `runtime.env` containing only exact image/source identities, GitHub App public identifiers, origin/bind settings and the runtime UID.

## Pre-cutover recovery gate

Before a future activation, create an encrypted recovery bundle with `deploy/recovery/create-recovery-bundle.sh` on an operator-configured, marker-verified mounted destination outside the production VM filesystem. The age X25519 private identity stays outside the VM. The script accepts exactly the GitHub App key, shared-password verifier and session-signing secret, all mode `0600`; any missing, additional or symlinked secret is rejected.

Validate the bundle's `SHA256SUMS`, record its failure domain and follow `deploy/recovery/RESTORE-RUNBOOK.md`. The included weekly systemd templates remain disabled until separately authorized. Retention tooling targets the newest eight weekly points plus one monthly point for twelve months and operates only below the verified backup root after a new bundle passes integrity checks.

## Future full-stack activation

`deploy/s10a/activate-reviewed-service.sh` is inert because both authorization gates are committed as `false`. A separately reviewed operator copy may proceed only after it:

1. verifies exact source and artifact hashes;
2. verifies a completed off-VM encrypted recovery bundle;
3. captures current gateway/Caddy image IDs, uniquely tagged preserved rollback references, containers, Compose, Caddy and runtime identities plus the unchanged HAProxy checksum without printing secrets;
4. validates candidate Compose and Caddy;
5. loads the exact reviewed gateway and Caddy/frontend archives and verifies both tags resolve to manifest image IDs;
6. replaces only those two application containers while preserving Caddy volumes;
7. runs health, canonical unauthenticated redirect, login/replay, landing, protected pages, automatic Archive, Editor/config, exact read-only source-part size/SHA and logout checks with zero archive writes;
8. creates and verifies a post-activation off-VM bundle, then records exact deployment, rollback, source-smoke and recovery identities in the authoritative deployment record.

It must not use `docker compose down`, edit HAProxy/Xray/x-ui/MTProxy/n8n/router/DNS/firewall, rotate secrets or mutate archive data.

## Rollback

Any failed activation invokes `rollback-reviewed-service.sh` with the captured directory. Before candidate load, both prior image IDs are protected by unique rollback tags. Rollback uses an exact-image Compose override, force-recreates both services, verifies both running container image IDs and service health, preserves volumes, verifies HAProxy stayed unchanged and does not touch GitHub archive records. If any captured identity, preserved tag or checksum differs, rollback fails closed for operator intervention.

## Clean-machine restore

The supported target is a clean Ubuntu 24.04 LTS VM. Restore validates the recovery bundle before decrypting/loading, requires the off-VM age identity explicitly, restores mode-0600 secrets without printing them, installs the allowlisted non-secret runtime configuration, loads both image archives, verifies their refs resolve to the manifest IDs, verifies the running containers use those exact IDs, brings up only the Meser application stack and checks health. The CI rehearsal then runs the Caddy-backed redirect/login/protected API/internal denial/logout and real FFmpeg/WASM flow. The old VM filesystem and an application database are not inputs; `meser-recovery/audio-archive` and Releases remain canonical data.

Real decryptability, off-VM placement, isolated restore, production identities and real-device tests are separate authorized operational acceptance gates and are not claimed by repository work.
