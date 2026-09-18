#!/usr/bin/env bash
set -Eeuo pipefail

MESER_RESTORE_AUTHORIZED=false
MESER_ISOLATED_ENVIRONMENT_CONFIRMED=false
die() { printf 'RESTORE REFUSED: %s\n' "$*" >&2; exit 1; }
[[ $# -eq 3 ]] || die 'usage: restore-meser-service.sh <recovery-bundle> <off-vm-age-identity> <service-root>'
bundle=$1
identity=$2
service_root=$3
synthetic=${MESER_RECOVERY_SYNTHETIC_TEST:-false}
if [[ "$synthetic" == true ]]; then
  [[ "$service_root" == /tmp/meser-synthetic-restore.* && -d "$service_root" && ! -L "$service_root" ]] || die 'synthetic restore root must be an existing dedicated /tmp directory'
else
  [[ "$MESER_RESTORE_AUTHORIZED" == true ]] || die 'restore authorization gate is false'
  [[ "$MESER_ISOLATED_ENVIRONMENT_CONFIRMED" == true ]] || die 'isolated environment gate is false'
fi
[[ -d "$bundle" && ! -L "$bundle" && -f "$bundle/SHA256SUMS" ]] || die 'invalid bundle'
[[ -f "$identity" && ! -L "$identity" && "$(stat -c '%a' "$identity")" == 600 ]] || die 'age identity must be an off-VM mode-600 file'
(cd "$bundle" && sha256sum -c SHA256SUMS >/dev/null) || die 'bundle integrity failed before decrypt/load'
for key in created_utc source_sha source_tree supported_os architecture required_runtime destination_mount_id failure_domain secrets_encryption gateway_image_id caddy_frontend_image_id gateway_image_ref caddy_frontend_image_ref; do
  [[ -n "$(awk -F= -v key="$key" '$1 == key { sub(/^[^=]*=/, ""); print }' "$bundle/recovery-manifest.txt")" ]] || die "recovery manifest is incomplete: $key"
done
[[ "$(awk -F= '$1 == "supported_os" { print $2 }' "$bundle/recovery-manifest.txt")" == 'Ubuntu 24.04 LTS' ]] || die 'unsupported recovery operating-system baseline'
for file in runtime.env release-manifest.txt compose.yaml Caddyfile gateway-image.tar caddy-frontend-image.tar; do
  [[ -f "$bundle/$file" && ! -L "$bundle/$file" ]] || die "required restore input is missing: $file"
done
expected_runtime_keys=$'ALLOWED_ORIGIN\nCADDY_IMAGE\nGATEWAY_IMAGE\nGITHUB_APP_ID\nGITHUB_APP_INSTALLATION_ID\nMESER_HTTP_BIND\nMESER_RUNTIME_UID\nMESER_SITE_ADDRESS\nMESER_SYNTHETIC_RUNTIME\nMESER_TLS_BIND\nSOURCE_SHA'
actual_runtime_keys=$(awk -F= 'NF >= 2 && $1 !~ /^#/ { print $1 }' "$bundle/runtime.env" | LC_ALL=C sort)
[[ "$actual_runtime_keys" == "$expected_runtime_keys" ]] || die 'runtime environment contains missing or unknown keys'
bundle_runtime_value() { awk -F= -v key="$1" '$1 == key { sub(/^[^=]*=/, ""); print }' "$bundle/runtime.env"; }
if [[ "$synthetic" == true ]]; then
  [[ "$(bundle_runtime_value MESER_SYNTHETIC_RUNTIME)" == true && "$(bundle_runtime_value ALLOWED_ORIGIN)" =~ ^http://127\.0\.0\.1:[0-9]+$ && "$(bundle_runtime_value MESER_SITE_ADDRESS)" == http:// ]] || die 'synthetic runtime origin is invalid'
  [[ "$(bundle_runtime_value MESER_HTTP_BIND)" =~ ^127\.0\.0\.1:[0-9]+$ && "$(bundle_runtime_value MESER_TLS_BIND)" =~ ^127\.0\.0\.1:[0-9]+$ ]] || die 'synthetic runtime bind is invalid'
else
  [[ "$(bundle_runtime_value MESER_SYNTHETIC_RUNTIME)" == false && "$(bundle_runtime_value ALLOWED_ORIGIN)" == https://meserproject.duckdns.org && "$(bundle_runtime_value MESER_SITE_ADDRESS)" == meserproject.duckdns.org ]] || die 'production runtime origin is invalid'
  [[ "$(bundle_runtime_value MESER_HTTP_BIND)" == 80 && "$(bundle_runtime_value MESER_TLS_BIND)" == 127.0.0.1:9443 && "$(bundle_runtime_value MESER_RUNTIME_UID)" == 1000 ]] || die 'production runtime identity/binds are invalid'
fi
for pair in 'compose_sha256 compose.yaml' 'caddy_sha256 Caddyfile'; do
  read -r key filename <<<"$pair"
  expected_hash=$(awk -F= -v key="$key" '$1 == key { print $2 }' "$bundle/release-manifest.txt")
  [[ "$expected_hash" =~ ^[0-9a-f]{64}$ && "$(sha256sum "$bundle/$filename" | awk '{ print $1 }')" == "$expected_hash" ]] || die "release manifest checksum failed: $filename"
done
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
config_root=/etc/meser-audio-archive
project_name=meser-audio-archive
if [[ "$synthetic" == true ]]; then config_root="$service_root/config"; project_name="meser-synthetic-restore-${BASHPID}"; fi
if [[ "$synthetic" == true ]]; then printf '%s\n' "$project_name" >"$service_root/.restore-project-name"; fi
install -d -m 700 "$config_root"
for name in github-app.pem shared-password-verifier session-signing-secret; do install -m 600 "$work/secrets/$name" "$config_root/$name"; done
install -m 600 "$bundle/runtime.env" "$config_root/runtime.env"

docker load -i "$bundle/gateway-image.tar" >/dev/null
docker load -i "$bundle/caddy-frontend-image.tar" >/dev/null
gateway_ref=$(awk -F= '$1 == "gateway_image_ref" { print $2 }' "$bundle/release-manifest.txt")
caddy_ref=$(awk -F= '$1 == "caddy_frontend_image_ref" { print $2 }' "$bundle/release-manifest.txt")
gateway_id=$(awk -F= '$1 == "gateway_image_id" { print $2 }' "$bundle/release-manifest.txt")
caddy_id=$(awk -F= '$1 == "caddy_frontend_image_id" { print $2 }' "$bundle/release-manifest.txt")
runtime_value() { awk -F= -v key="$1" '$1 == key { sub(/^[^=]*=/, ""); print }' "$config_root/runtime.env"; }
manifest_value() { awk -F= -v key="$1" '$1 == key { sub(/^[^=]*=/, ""); print }' "$bundle/recovery-manifest.txt"; }
[[ "$gateway_ref" == "$(manifest_value gateway_image_ref)" && "$caddy_ref" == "$(manifest_value caddy_frontend_image_ref)" ]] || die 'recovery and release image references disagree'
[[ "$gateway_id" == "$(manifest_value gateway_image_id)" && "$caddy_id" == "$(manifest_value caddy_frontend_image_id)" ]] || die 'recovery and release image IDs disagree'
[[ "$(runtime_value SOURCE_SHA)" == "$(manifest_value source_sha)" && "$(runtime_value GATEWAY_IMAGE)" == "$gateway_ref" && "$(runtime_value CADDY_IMAGE)" == "$caddy_ref" ]] || die 'runtime configuration does not bind exact manifest source/images'
[[ "$(docker image inspect -f '{{.Id}}' "$gateway_ref")" == "$gateway_id" ]] || die 'loaded gateway image ID does not match release manifest'
[[ "$(docker image inspect -f '{{.Id}}' "$caddy_ref")" == "$caddy_id" ]] || die 'loaded Caddy/frontend image ID does not match release manifest'

MESER_CONFIG_ROOT="$config_root" docker compose --project-name "$project_name" --env-file "$config_root/runtime.env" -f "$service_root/deploy/self-hosted/compose.yaml" config >/dev/null
MESER_CONFIG_ROOT="$config_root" docker compose --project-name "$project_name" --env-file "$config_root/runtime.env" -f "$service_root/deploy/self-hosted/compose.yaml" up -d --no-build gateway caddy
gateway_container=$(MESER_CONFIG_ROOT="$config_root" docker compose --project-name "$project_name" --env-file "$config_root/runtime.env" -f "$service_root/deploy/self-hosted/compose.yaml" ps -q gateway)
caddy_container=$(MESER_CONFIG_ROOT="$config_root" docker compose --project-name "$project_name" --env-file "$config_root/runtime.env" -f "$service_root/deploy/self-hosted/compose.yaml" ps -q caddy)
[[ "$(docker inspect -f '{{.Image}}' "$gateway_container")" == "$gateway_id" ]] || die 'restored gateway container does not use exact manifest image ID'
[[ "$(docker inspect -f '{{.Image}}' "$caddy_container")" == "$caddy_id" ]] || die 'restored Caddy container does not use exact manifest image ID'
service_origin=$(awk -F= '$1 == "ALLOWED_ORIGIN" { print $2 }' "$config_root/runtime.env")
for attempt in {1..30}; do
  if curl --fail --silent --show-error "$service_origin/healthz" >/dev/null 2>&1; then break; fi
  [[ "$attempt" -lt 30 ]] || die 'restored service health check failed'
  sleep 1
done
printf 'Restore completed with exact gateway %s and Caddy %s image IDs.\n' "$gateway_id" "$caddy_id"
