#!/usr/bin/env bash
set -Eeuo pipefail

MESER_RESTORE_AUTHORIZED=false
MESER_ISOLATED_ENVIRONMENT_CONFIRMED=false
die() { printf 'RESTORE REFUSED: %s\n' "$*" >&2; exit 1; }
[[ "$MESER_RESTORE_AUTHORIZED" == true ]] || die 'restore authorization gate is false'
[[ "$MESER_ISOLATED_ENVIRONMENT_CONFIRMED" == true ]] || die 'isolated environment gate is false'
[[ $# -eq 3 ]] || die 'usage: restore-meser-service.sh <recovery-bundle> <off-vm-age-identity> <service-root>'
bundle=$1
identity=$2
service_root=$3
[[ -d "$bundle" && ! -L "$bundle" && -f "$bundle/SHA256SUMS" ]] || die 'invalid bundle'
[[ -f "$identity" && ! -L "$identity" && "$(stat -c '%a' "$identity")" == 600 ]] || die 'age identity must be an off-VM mode-600 file'
(cd "$bundle" && sha256sum -c SHA256SUMS >/dev/null) || die 'bundle integrity failed before decrypt/load'
for key in created_utc source_sha source_tree supported_os architecture required_runtime destination_mount_id failure_domain secrets_encryption; do
  [[ -n "$(awk -F= -v key="$key" '$1 == key { sub(/^[^=]*=/, ""); print }' "$bundle/recovery-manifest.txt")" ]] || die "recovery manifest is incomplete: $key"
done
[[ "$(awk -F= '$1 == "supported_os" { print $2 }' "$bundle/recovery-manifest.txt")" == 'Ubuntu 24.04 LTS' ]] || die 'unsupported recovery operating-system baseline'
work=$(mktemp -d /tmp/meser-restore.XXXXXX)
trap 'rm -rf -- "$work"' EXIT
age -d -i "$identity" -o "$work/secrets.tar" "$bundle/secrets.age"
tar -tf "$work/secrets.tar" | LC_ALL=C sort >"$work/secret-list"
expected=$'github-app.pem\nsecret-metadata.txt\nsession-signing-secret\nshared-password-verifier'
[[ "$(<"$work/secret-list")" == "$expected" ]] || die 'encrypted secret allowlist mismatch'
mkdir -m 700 "$work/secrets"
tar -xf "$work/secrets.tar" -C "$work/secrets" --no-same-owner --no-same-permissions
for name in github-app.pem shared-password-verifier session-signing-secret; do chmod 600 "$work/secrets/$name"; done

install -d -m 750 "$service_root/deploy/self-hosted"
install -m 640 "$bundle/compose.yaml" "$service_root/deploy/self-hosted/compose.yaml"
install -m 640 "$bundle/Caddyfile" "$service_root/deploy/self-hosted/Caddyfile"
install -d -m 700 /etc/meser-audio-archive
for name in github-app.pem shared-password-verifier session-signing-secret; do install -m 600 "$work/secrets/$name" "/etc/meser-audio-archive/$name"; done
docker load -i "$bundle/gateway-image.tar" >/dev/null
docker load -i "$bundle/caddy-frontend-image.tar" >/dev/null
SOURCE_SHA=$(awk -F= '$1 == "source_sha" { print $2 }' "$bundle/recovery-manifest.txt") \
  docker compose --project-name meser-audio-archive --env-file /etc/meser-audio-archive/runtime.env -f "$service_root/deploy/self-hosted/compose.yaml" config >/dev/null
SOURCE_SHA=$(awk -F= '$1 == "source_sha" { print $2 }' "$bundle/recovery-manifest.txt") \
  docker compose --project-name meser-audio-archive --env-file /etc/meser-audio-archive/runtime.env -f "$service_root/deploy/self-hosted/compose.yaml" up -d --no-build gateway caddy
