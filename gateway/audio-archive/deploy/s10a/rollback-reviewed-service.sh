#!/usr/bin/env bash
set -Eeuo pipefail

die() { printf 'S10A ROLLBACK REFUSED: %s\n' "$*" >&2; exit 1; }
[[ $# -eq 1 ]] || die 'usage: rollback-reviewed-service.sh <captured-rollback-directory>'
state=$1
[[ "$state" = /var/backups/meser-audio-archive/s10a/* && -d "$state" && ! -L "$state" ]] || die 'unsafe rollback directory'
for file in compose.yaml Caddyfile prior-gateway.txt prior-caddy.txt haproxy.sha256; do [[ -f "$state/$file" && ! -L "$state/$file" ]] || die "missing rollback file: $file"; done
sha256sum -c "$state/haproxy.sha256" >/dev/null || die 'HAProxy changed; rollback refuses to alter it'

runtime_env=/etc/meser-audio-archive/runtime.env
restore_root=$(mktemp -d /var/tmp/meser-service-rollback.XXXXXX)
trap 'rm -rf -- "$restore_root"' EXIT
install -m 600 "$state/compose.yaml" "$restore_root/compose.yaml"
install -m 600 "$state/Caddyfile" "$restore_root/Caddyfile"

# Restore both application containers together. Never stop the project, remove
# volumes, touch archive records, or alter HAProxy/Xray.
docker compose --project-name meser-audio-archive --env-file "$runtime_env" -f "$restore_root/compose.yaml" up -d --no-build gateway caddy
docker compose --project-name meser-audio-archive --env-file "$runtime_env" -f "$restore_root/compose.yaml" ps gateway caddy
