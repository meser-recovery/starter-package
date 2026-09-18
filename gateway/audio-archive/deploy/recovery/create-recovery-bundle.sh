#!/usr/bin/env bash
set -Eeuo pipefail

die() { printf 'RECOVERY BUNDLE REFUSED: %s\n' "$*" >&2; exit 1; }
[[ $# -eq 6 ]] || die 'usage: create-recovery-bundle.sh <release-dir> <secret-dir> <absolute-mounted-destination> <age-recipient> <expected-mount-id> <failure-domain-note>'
release_dir=$1
secret_dir=$2
destination=$3
recipient=$4
expected_mount_id=$5
failure_domain=$6

for command in age awk cp date find git mktemp readlink sha256sum stat tar uname; do command -v "$command" >/dev/null || die "missing executable: $command"; done
[[ "$destination" = /* && -d "$destination" && ! -L "$destination" ]] || die 'destination must be an absolute existing non-symlink directory'
[[ -d "$release_dir" && ! -L "$release_dir" && -d "$secret_dir" && ! -L "$secret_dir" ]] || die 'release/secret directory is unsafe'
[[ "$recipient" =~ ^age1[0-9a-z]+$ ]] || die 'age X25519 recipient is missing or invalid'
[[ -n "$expected_mount_id" && -f "$destination/.meser-recovery-target" && ! -L "$destination/.meser-recovery-target" ]] || die 'dedicated backup marker is missing'
[[ "$(tr -d '\r\n' <"$destination/.meser-recovery-target")" == "$expected_mount_id" ]] || die 'backup mount identity mismatch'
if [[ "${MESER_RECOVERY_SYNTHETIC_TEST:-false}" != true ]]; then
  command -v mountpoint >/dev/null || die 'mountpoint executable is required'
  mountpoint -q "$destination" || die 'destination is not a dedicated mounted filesystem'
fi

required_release=(release-manifest.txt meser-service-source.tar.gz meser-service-source.tar.gz.sha256 gateway-image.tar gateway-image.tar.sha256 caddy-frontend-image.tar caddy-frontend-image.tar.sha256 compose.yaml Caddyfile haproxy.cfg)
for name in "${required_release[@]}"; do [[ -f "$release_dir/$name" && ! -L "$release_dir/$name" ]] || die "release artifact missing: $name"; done
for manifest in meser-service-source.tar.gz.sha256 gateway-image.tar.sha256 caddy-frontend-image.tar.sha256; do
  (cd "$release_dir" && sha256sum -c "$manifest" >/dev/null) || die "release artifact checksum failed: $manifest"
done

expected_secrets=$'github-app.pem\nsession-signing-secret\nshared-password-verifier'
actual_secrets=$(find "$secret_dir" -mindepth 1 -maxdepth 1 -type f -printf '%f\n' | LC_ALL=C sort)
[[ "$actual_secrets" == "$expected_secrets" ]] || die 'secret directory contains missing or unknown files'
for name in github-app.pem shared-password-verifier session-signing-secret; do
  [[ ! -L "$secret_dir/$name" && "$(stat -c '%a' "$secret_dir/$name")" == 600 ]] || die "secret permission must be 600: $name"
done

source_sha=$(awk -F= '$1 == "source_sha" { print $2 }' "$release_dir/release-manifest.txt")
source_tree=$(awk -F= '$1 == "source_tree" { print $2 }' "$release_dir/release-manifest.txt")
[[ "$source_sha" =~ ^[0-9a-f]{40}$ && "$source_tree" =~ ^[0-9a-f]{40}$ ]] || die 'release manifest source identity is incomplete'
required_manifest_keys=(gateway_image_id caddy_frontend_image_id gateway_base caddy_base compose_sha256 caddy_sha256 haproxy_sha256)
for key in "${required_manifest_keys[@]}"; do
  value=$(awk -F= -v key="$key" '$1 == key { sub(/^[^=]*=/, ""); print }' "$release_dir/release-manifest.txt")
  [[ -n "$value" ]] || die "release manifest is incomplete: $key"
done
for pair in 'compose_sha256 compose.yaml' 'caddy_sha256 Caddyfile' 'haproxy_sha256 haproxy.cfg'; do
  read -r key filename <<<"$pair"
  expected=$(awk -F= -v key="$key" '$1 == key { print $2 }' "$release_dir/release-manifest.txt")
  [[ "$expected" =~ ^[0-9a-f]{64}$ && "$(sha256sum "$release_dir/$filename" | awk '{ print $1 }')" == "$expected" ]] || die "release manifest checksum failed: $filename"
done
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
bundle_name="meser-service-recovery-${timestamp}-${source_sha}"
[[ ! -e "$destination/$bundle_name" ]] || die 'bundle destination already exists'
work=$(mktemp -d /tmp/meser-recovery-create.XXXXXX)
trap 'rm -rf -- "$work"' EXIT
bundle="$work/$bundle_name"
mkdir -m 700 "$bundle"

for name in "${required_release[@]}"; do cp -- "$release_dir/$name" "$bundle/$name"; done
printf '%s\n' 'github-app.pem mode=600' 'shared-password-verifier mode=600' 'session-signing-secret mode=600' >"$work/secret-metadata.txt"
tar -C "$secret_dir" -cf - github-app.pem shared-password-verifier session-signing-secret -C "$work" secret-metadata.txt \
  | age -r "$recipient" -o "$bundle/secrets.age"

cat >"$bundle/recovery-manifest.txt" <<EOF
created_utc=$timestamp
source_sha=$source_sha
source_tree=$source_tree
supported_os=Ubuntu 24.04 LTS
architecture=$(uname -m)
required_runtime=Docker Engine with Compose v2, age, HAProxy, systemd
destination_mount_id=$expected_mount_id
failure_domain=$failure_domain
secrets_encryption=age X25519 recipient
EOF
cp -- "$(dirname "$0")/RESTORE-RUNBOOK.md" "$bundle/RESTORE-RUNBOOK.md"
(cd "$bundle" && find . -mindepth 1 -maxdepth 1 -type f ! -name SHA256SUMS -printf '%P\n' | LC_ALL=C sort | while IFS= read -r name; do sha256sum "$name"; done >SHA256SUMS)
(cd "$bundle" && sha256sum -c SHA256SUMS >/dev/null)
cp -R -- "$bundle" "$destination/$bundle_name"
(cd "$destination/$bundle_name" && sha256sum -c SHA256SUMS >/dev/null)
printf 'Recovery bundle created and verified: %s\n' "$destination/$bundle_name"
