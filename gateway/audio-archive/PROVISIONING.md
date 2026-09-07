# S08A self-hosted transactional deployment runbook

**Status: repository-only preparation. Every VM, router, DNS and production command below is UNEXECUTED.**

This runbook does not authorize discovery, installation, secret creation, service changes, deployment or cutover. Each gate requires separate recorded authorization. Never continue after a failed invariant.

Target deployment root: `/opt/meser-audio-archive/`

Target secret root: `/etc/meser-audio-archive/`

Future gateway origin: `https://meserproject.duckdns.org`

Existing external Xray address that must not change: `meserproject.duckdns.org:443`

Supplied expected host state, which Gate 2 must verify rather than assume:

- `/opt/meser-audio-archive/` exists with owner/group `alex:alex`;
- `/etc/meser-audio-archive/` exists with owner/group `root:root` and mode `0700`.

The committed HAProxy configuration deliberately contains the future public `bind :443`. It must only be installed/enabled during separately confirmed Gate 4. Offline validation does not authorize that bind.

## Gate 1 — repository-only validation

This is the only gate authorized during implementation. It performs no VM or external mutation.

Run from the repository:

```sh
npm --prefix gateway/audio-archive run check
npm --prefix gateway/audio-archive test
python3 tests/safety/check_site.py
GITHUB_APP_ID=validation-only GITHUB_APP_INSTALLATION_ID=validation-only \
  docker compose -f gateway/audio-archive/deploy/self-hosted/compose.yaml config
```

When already installed locally, validate without starting a daemon or pulling an image:

```sh
caddy version
caddy validate --config gateway/audio-archive/deploy/self-hosted/Caddyfile --adapter caddyfile
haproxy -c -f gateway/audio-archive/deploy/self-hosted/haproxy.cfg
```

The local Caddy result is authoritative only when `caddy version` reports the pinned intended `v2.11.4`. Alternatively, if that image already exists locally, run `caddy validate` in `caddy:2.11.4-alpine` with the committed Caddyfile mounted read-only. Do not pull an image for this repository-only check. If a validator is unavailable or the installed version differs, record it as unperformed. Do not install software or start the stack merely to satisfy Gate 1.

Gate 1 evidence must also show:

- the three frontend `audio-archive-gateway` hooks are present and empty;
- rendered Compose has no gateway `ports`, no host networking and no sensitive environment value;
- only Caddy maps host `80` and `127.0.0.1:9443`, never host `443`;
- only the gateway receives the three file secrets;
- the gateway image runs as non-root and unprivileged;
- Caddy and gateway share only the dedicated `archive_private` network;
- GitHub remains canonical storage;
- repository scans contain no credential or private-key material.

Do not proceed until Gate 1 passes and the user separately authorizes read-only VM discovery.

## Gate 2 — future read-only VM discovery and baseline capture

**UNEXECUTED. Requires separate read-only VM access authorization.**

Copy `deploy/self-hosted/deployment-state.template.md` to the ignored `deployment-state.local.md`. Fill it only from actual evidence. No field may remain `UNRESOLVED` before later gates.

Read-only discovery must record complete output from commands equivalent to:

```sh
sudo ss -ltnp
sudo systemctl list-units --type=service --all
sudo systemctl list-unit-files
sudo docker ps --no-trunc
sudo docker compose ls
sudo ps -ef
```

From that evidence, identify—not guess:

- the processes/containers owning TCP `80`, `443`, `8443`, `5678` and `65000`;
- actual x-ui and Xray systemd unit/container names;
- authoritative x-ui/Xray configuration path;
- generated Xray configuration path, if separate;
- actual restart/reload procedure;
- installed HAProxy state/version and unit name;
- deployment operator/group;
- whether `127.0.0.1:9443` and proposed `127.0.0.1:9444` are free.

Required baseline listener table:

| Listener | Baseline invariant |
| --- | --- |
| TCP `443` | existing Xray REALITY owns it |
| TCP `80` | owner or free state recorded |
| TCP `8443` | MTProto owner and behavior recorded |
| TCP `5678` | n8n owner and behavior recorded |
| TCP `65000` | x-ui owner and behavior recorded |
| `127.0.0.1:9443` | confirmed free |
| `127.0.0.1:9444` | confirmed free before proposed Xray move |

Inspect actual unit definitions and configuration only after their paths/names are discovered. Do not mutate them. Gate 2 ends with a reviewed deployment-state record; it performs no backup, install, edit or restart.

## Gate 3 — future authorized Phase A preparation

**UNEXECUTED. Requires explicit authorization listing every mutation below. Xray must continue owning public TCP `443` throughout Gate 3.**

Before any edit, create a root-protected timestamped backup directory. Back up the discovered authoritative x-ui/Xray configuration and generated Xray configuration when separate. Record SHA-256 for originals and backups, compare them byte-for-byte, and perform a restore-to-temporary-path checksum test. Never overwrite the originals during this verification.

Phase A mutations, only after authorization:

1. Install HAProxy if discovery proved it absent, but do not start/enable it on TCP `443`.
2. Copy reviewed deployment files to `/opt/meser-audio-archive/` with owner/group discovered in Gate 2.
3. Confirm `/etc/meser-audio-archive/` is `root:root` mode `0700`.
4. Create these host files as `root:root` mode `0640` without printing their contents:
   - `/etc/meser-audio-archive/github-app.pem`;
   - `/etc/meser-audio-archive/shared-password-verifier`;
   - `/etc/meser-audio-archive/session-signing-secret`.
5. Set only non-secret `GITHUB_APP_ID` and `GITHUB_APP_INSTALLATION_ID` for Compose invocation.
6. Build the gateway image and validate `docker compose config`.
7. Validate the proposed Xray configuration with only its listener moved to `127.0.0.1:9444`; do not activate it.
8. Validate committed HAProxy configuration offline with `haproxy -c`; do not bind `443`.
9. Validate Caddy configuration with pinned image/version `caddy:2.11.4-alpine`.
10. Start only gateway and Caddy. Caddy may claim public TCP `80` and loopback `127.0.0.1:9443`; gateway must have no host port.
11. Confirm the gateway runs with UID `1000`, is unprivileged, and can read all three mounted files without outputting contents. Stop if root-group `0640` access does not work; never widen to world-readable.
12. Confirm gateway health from Caddy's container network, then confirm Caddy TLS routing through a separately reviewed temporary HAProxy config bound only to an unused loopback test port. Never use public `443` for this test.
13. Re-run listener inventory and prove `443`, `8443`, `5678` and `65000` are unchanged.

Required Phase A validation includes commands equivalent to:

```sh
sudo stat -c '%U %G %a %n' /etc/meser-audio-archive /etc/meser-audio-archive/*
sudo sha256sum DISCOVERED_XRAY_CONFIG DISCOVERED_BACKUP_COPY
sudo cmp --silent DISCOVERED_XRAY_CONFIG DISCOVERED_BACKUP_COPY
sudo haproxy -c -f /opt/meser-audio-archive/deploy/self-hosted/haproxy.cfg
sudo docker compose -f /opt/meser-audio-archive/deploy/self-hosted/compose.yaml config
sudo docker compose -f /opt/meser-audio-archive/deploy/self-hosted/compose.yaml exec -T caddy wget -qO- http://gateway:8080/healthz
sudo ss -ltnp
```

Every `DISCOVERED_*` token must be replaced with the actual reviewed value before execution. Any unresolved token, failed checksum, occupied internal port, unhealthy container, config validation error, changed protected listener or secret-permission failure stops Phase A immediately. Stop the new Compose stack if necessary; Xray remains untouched on public `443`.

Before Gate 4, materialize an ignored `rollback-resolved.sh` containing literal commands with the actual unit names, config paths and backup paths from Gate 2/3. It must start with guards that fail unless all required variables are non-empty, all backup checksums match, `PHASE_B_AUTHORIZED=yes`, and a second human has reviewed the file. Syntax-check it, review it line by line, and attach its checksum to the deployment-state record.

## Gate 4 — future separately confirmed Phase B cutover

**UNEXECUTED. Requires a new confirmation immediately before changing Xray or public TCP `443`. Gate 3 authorization is insufficient.**

Execute only the already materialized, reviewed literal commands. Sequence:

1. Reconfirm backup hashes, current protected listeners and healthy Caddy/gateway.
2. Activate the validated Xray listener change from public `:443` to `127.0.0.1:9444`, using the actual x-ui-managed procedure discovered in Gate 2.
3. Restart/reload the actual Xray unit and verify `127.0.0.1:9444` immediately.
4. Start/reload the discovered host HAProxy unit so it becomes the sole public TCP `443` owner.
5. Verify HAProxy owns public `443`, exact SNI `meserproject.duckdns.org` routes to Caddy, and unknown/absent SNI routes to Xray.
6. Verify `https://meserproject.duckdns.org/healthz` externally.
7. Verify the existing REALITY client still connects to `meserproject.duckdns.org:443` with no client configuration change.
8. Verify MTProto `8443`, n8n `5678` and x-ui `65000` are unchanged.
9. Run the separately approved application smoke only with disposable data.
10. Only after all infrastructure and application evidence passes, separately update the three frontend gateway meta values and deploy GitHub Pages.

After each step, stop immediately on failure. A failure affecting REALITY, Xray/x-ui, HAProxy, Caddy, TLS, the gateway or any protected listener triggers rollback before further diagnosis.

## Mandatory rollback to Xray public `:443`

**UNEXECUTED TEMPLATE. It is intentionally not runnable until discovery values are materialized.**

The resolved rollback script must perform these literal operations in this order:

```sh
set -eu
test "${PHASE_B_AUTHORIZED:-}" = yes
test "${SECOND_REVIEW_COMPLETE:-}" = yes
: "${HAPROXY_UNIT:?UNRESOLVED HAProxy unit}"
: "${XRAY_UNIT:?UNRESOLVED Xray unit}"
: "${XRAY_CONFIG:?UNRESOLVED authoritative config}"
: "${XRAY_BACKUP:?UNRESOLVED authoritative backup}"
: "${XRAY_BACKUP_SHA256:?UNRESOLVED backup checksum}"
printf '%s  %s\n' "$XRAY_BACKUP_SHA256" "$XRAY_BACKUP" | sha256sum --check --status
sudo systemctl stop "$HAPROXY_UNIT"
sudo install -o root -g root -m 0600 "$XRAY_BACKUP" "$XRAY_CONFIG"
sudo systemctl restart "$XRAY_UNIT"
sudo ss -ltnp
```

If a separate generated Xray config exists, the materialized script must add the same guarded checksum/restore operation for it. If actual services are container-managed, replace the `systemctl` lines with the literal discovered commands before review; do not use this template unchanged.

Rollback verification must prove:

- Xray directly owns public TCP `443` again;
- the existing REALITY client works unchanged;
- HAProxy no longer owns public `443`;
- `8443`, `5678` and `65000` remain intact;
- backup and restored authoritative configs match expected checksums.

For a full infrastructure rollback, stop the Caddy/gateway Compose stack after Xray recovery. Application rollback must never delete GitHub Releases, manifests, transactions, catalog entries or the storage repository. Restore the frontend meta hooks to empty if they had later been enabled, then use the normal GitHub Pages workflow only under separate authorization.

## Intended future external mutations requiring separate authorization

No item in this list has been executed:

1. Read-only SSH/VM discovery and creation of the local deployment-state record.
2. Possible HAProxy package installation and committed config installation as a host service.
3. Creation/backup files under the discovered root-protected backup location.
4. Deployment-file writes under `/opt/meser-audio-archive/`.
5. Secret-file writes and permission changes under `/etc/meser-audio-archive/`.
6. Gateway image build and gateway/Caddy Compose creation/start, claiming TCP `80` and loopback `9443`.
7. Minimal x-ui/Xray authoritative configuration edit moving only the listener from public `:443` to loopback `9444`, followed by its actual reload/restart.
8. HAProxy enable/start/reload to claim public TCP `443`.
9. Certificate issuance/renewal state written to the persistent Caddy volume.
10. External TLS, gateway and existing REALITY-client verification plus protected-service checks.
11. If still absent, separate creation/configuration of `meser-recovery/audio-archive` and a repository-scoped GitHub App; disposable storage writes for the authorized smoke.
12. Frontend meta-value update and GitHub Pages deployment only after the complete cutover passes.

No router, DNS, MTProto, n8n, x-ui behavior, REALITY target/server name/credentials/transport or client configuration change is planned.
