#!/usr/bin/env bash
set -Eeuo pipefail

die() { printf 'RECOVERY BUNDLE REFUSED: %s\n' "$*" >&2; exit 1; }
[[ $# -eq 7 ]] || die 'usage: create-recovery-bundle.sh <release-dir> <secret-dir> <runtime-env> <absolute-mounted-destination> <age-recipient> <expected-mount-id> <failure-domain-note>'
release_dir=$1
secret_dir=$2
runtime_env=$3
destination=$4
recipient=$5
expected_mount_id=$6
failure_domain=$7

for command in age awk cp date find git mktemp readlink sha256sum stat tar uname; do command -v "$command" >/dev/null || die "missing executable: $command"; done
[[ "$destination" = /* && -d "$destination" && ! -L "$destination" ]] || die 'destination must be an absolute existing non-symlink directory'
[[ -d "$release_dir" && ! -L "$release_dir" && -d "$secret_dir" && ! -L "$secret_dir" ]] || die 'release/secret directory is unsafe'
[[ -f "$runtime_env" && ! -L "$runtime_env" ]] || die 'runtime environment file is unsafe or missing'
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
required_manifest_keys=(gateway_image_id caddy_frontend_image_id gateway_image_ref caddy_frontend_image_ref gateway_base caddy_base compose_sha256 caddy_sha256 haproxy_sha256)
for key in "${required_manifest_keys[@]}"; do
  value=$(awk -F= -v key="$key" '$1 == key { sub(/^[^=]*=/, ""); print }' "$release_dir/release-manifest.txt")
  [[ -n "$value" ]] || die "release manifest is incomplete: $key"
done

expected_runtime_keys=$'ALLOWED_ORIGIN\nGITHUB_APP_ID\nGITHUB_APP_INSTALLATION_ID\nMESER_HTTP_BIND\nMESER_RUNTIME_UID\nMESER_SITE_ADDRESS\nMESER_SYNTHETIC_RUNTIME\nMESER_TLS_BIND'
actual_runtime_keys=$(awk -F= 'NF >= 2 && $1 !~ /^#/ { print $1 }' "$runtime_env" | LC_ALL=C sort)
[[ "$actual_runtime_keys" == "$expected_runtime_keys" ]] || die 'runtime environment contains missing or unknown keys'
runtime_value() { awk -F= -v key="$1" '$1 == key { sub(/^[^=]*=/, ""); print }' "$runtime_env"; }
github_app_id=$(runtime_value GITHUB_APP_ID)
github_installation_id=$(runtime_value GITHUB_APP_INSTALLATION_ID)
allowed_origin=$(runtime_value ALLOWED_ORIGIN)
site_address=$(runtime_value MESER_SITE_ADDRESS)
http_bind=$(runtime_value MESER_HTTP_BIND)
tls_bind=$(runtime_value MESER_TLS_BIND)
runtime_uid=$(runtime_value MESER_RUNTIME_UID)
synthetic_runtime=$(runtime_value MESER_SYNTHETIC_RUNTIME)
[[ "$github_app_id" =~ ^[0-9]+$ && "$github_installation_id" =~ ^[0-9]+$ ]] || die 'runtime GitHub App identities are invalid'
[[ "$runtime_uid" =~ ^[0-9]+$ ]] || die 'runtime UID is invalid'
if [[ "${MESER_RECOVERY_SYNTHETIC_TEST:-false}" == true ]]; then
  [[ "$synthetic_runtime" == true && "$allowed_origin" =~ ^http://127\.0\.0\.1:[0-9]+$ && "$site_address" == http:// ]] || die 'synthetic runtime origin is invalid'
  [[ "$http_bind" =~ ^127\.0\.0\.1:[0-9]+$ && "$tls_bind" =~ ^127\.0\.0\.1:[0-9]+$ ]] || die 'synthetic runtime binds are invalid'
else
  [[ "$synthetic_runtime" == false && "$allowed_origin" == https://meserproject.duckdns.org && "$site_address" == meserproject.duckdns.org ]] || die 'production runtime origin is invalid'
  [[ "$http_bind" == 80 && "$tls_bind" == 127.0.0.1:9443 ]] || die 'production runtime binds are invalid'
fi
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
gateway_image_ref=$(awk -F= '$1 == "gateway_image_ref" { print $2 }' "$release_dir/release-manifest.txt")
caddy_image_ref=$(awk -F= '$1 == "caddy_frontend_image_ref" { print $2 }' "$release_dir/release-manifest.txt")
cat >"$bundle/runtime.env" <<EOF
SOURCE_SHA=$source_sha
GATEWAY_IMAGE=$gateway_image_ref
CADDY_IMAGE=$caddy_image_ref
GITHUB_APP_ID=$github_app_id
GITHUB_APP_INSTALLATION_ID=$github_installation_id
ALLOWED_ORIGIN=$allowed_origin
MESER_SITE_ADDRESS=$site_address
MESER_HTTP_BIND=$http_bind
MESER_TLS_BIND=$tls_bind
MESER_RUNTIME_UID=$runtime_uid
MESER_SYNTHETIC_RUNTIME=$synthetic_runtime
EOF
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
gateway_image_id=$(awk -F= '$1 == "gateway_image_id" { print $2 }' "$release_dir/release-manifest.txt")
caddy_frontend_image_id=$(awk -F= '$1 == "caddy_frontend_image_id" { print $2 }' "$release_dir/release-manifest.txt")
gateway_image_ref=$gateway_image_ref
caddy_frontend_image_ref=$caddy_image_ref
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
