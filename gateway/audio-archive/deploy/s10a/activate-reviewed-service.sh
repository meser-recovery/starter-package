#!/usr/bin/env bash
set -Eeuo pipefail

# Prepared only. A later reviewed operator copy must change both gates after the
# exact PR HEAD and off-VM recovery bundle have been accepted.
S10A_PRODUCTION_AUTHORIZED=false
S10A_INDEPENDENT_REVIEW_COMPLETE=false

die() { printf 'S10A ACTIVATION REFUSED: %s\n' "$*" >&2; exit 1; }
[[ "$S10A_PRODUCTION_AUTHORIZED" == true ]] || die 'production authorization gate is false'
[[ "$S10A_INDEPENDENT_REVIEW_COMPLETE" == true ]] || die 'independent review gate is false'
[[ $# -eq 9 ]] || die 'usage: activate-reviewed-service.sh <release-dir> <precutover-recovery-bundle> <smoke-password-file> <source-smoke-record> <secret-dir> <backup-destination> <age-recipient> <backup-mount-id> <failure-domain-note>'

release_dir=$1
precutover_bundle=$2
password_file=$3
source_smoke_record=$4
secret_dir=$5
backup_destination=$6
age_recipient=$7
backup_mount_id=$8
failure_domain_note=$9
runtime_env=/etc/meser-audio-archive/runtime.env
current_compose=/opt/meser-audio-archive/deploy/self-hosted/compose.yaml
current_caddyfile=/opt/meser-audio-archive/deploy/self-hosted/Caddyfile
haproxy_config=/etc/haproxy/haproxy.cfg
rollback_root=/var/backups/meser-audio-archive/s10a
deployment_root=/var/lib/meser-audio-archive/deployments
service_origin=https://meserproject.duckdns.org

for command in age awk curl date docker grep hostname id install jq mktemp readlink sha256sum stat; do command -v "$command" >/dev/null || die "missing executable: $command"; done
[[ "${EUID:-$(id -u)}" -eq 0 ]] || die 'must run as root'
[[ "$(hostname)" == vmhome ]] || die 'unexpected host'
for path in "$release_dir" "$precutover_bundle" "$password_file" "$source_smoke_record" "$secret_dir" "$backup_destination" "$runtime_env" "$current_compose" "$current_caddyfile" "$haproxy_config"; do
  [[ -e "$path" && ! -L "$path" ]] || die "unsafe or missing input: $path"
done
[[ "$(stat -c '%a' "$password_file")" == 600 ]] || die 'smoke password must be mode 600'
[[ -f "$precutover_bundle/SHA256SUMS" && -f "$precutover_bundle/recovery-manifest.txt" ]] || die 'completed precutover recovery bundle is required'
(cd "$precutover_bundle" && sha256sum -c SHA256SUMS >/dev/null) || die 'precutover recovery bundle integrity failed'

required_release=(release-manifest.txt meser-service-source.tar.gz meser-service-source.tar.gz.sha256 gateway-image.tar gateway-image.tar.sha256 caddy-frontend-image.tar caddy-frontend-image.tar.sha256 compose.yaml Caddyfile haproxy.cfg)
for name in "${required_release[@]}"; do [[ -f "$release_dir/$name" && ! -L "$release_dir/$name" ]] || die "release artifact missing: $name"; done
for manifest in meser-service-source.tar.gz.sha256 gateway-image.tar.sha256 caddy-frontend-image.tar.sha256; do
  (cd "$release_dir" && sha256sum -c "$manifest" >/dev/null) || die "release checksum failed: $manifest"
done
manifest_value() { awk -F= -v key="$1" '$1 == key { sub(/^[^=]*=/, ""); print }' "$release_dir/release-manifest.txt"; }
source_sha=$(manifest_value source_sha)
source_tree=$(manifest_value source_tree)
gateway_id=$(manifest_value gateway_image_id)
caddy_id=$(manifest_value caddy_frontend_image_id)
gateway_ref=$(manifest_value gateway_image_ref)
caddy_ref=$(manifest_value caddy_frontend_image_ref)
[[ "$source_sha" =~ ^[0-9a-f]{40}$ && "$source_tree" =~ ^[0-9a-f]{40}$ ]] || die 'release source identity is invalid'
[[ "$gateway_id" =~ ^sha256:[0-9a-f]{64}$ && "$caddy_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die 'release image identity is invalid'
[[ "$gateway_ref" == "meser-service-gateway:$source_sha" && "$caddy_ref" == "meser-service-caddy:$source_sha" ]] || die 'release image references are not exact-source tags'
for pair in 'compose_sha256 compose.yaml' 'caddy_sha256 Caddyfile' 'haproxy_sha256 haproxy.cfg'; do
  read -r key filename <<<"$pair"
  [[ "$(sha256sum "$release_dir/$filename" | awk '{ print $1 }')" == "$(manifest_value "$key")" ]] || die "release manifest checksum failed: $filename"
done
[[ "$(sha256sum "$haproxy_config" | awk '{ print $1 }')" == "$(manifest_value haproxy_sha256)" ]] || die 'deployed HAProxy differs from reviewed release reference'

timestamp=$(date -u +%Y%m%dT%H%M%SZ)
rollback_dir="$rollback_root/$timestamp-$source_sha"
work_dir=$(mktemp -d /var/tmp/meser-service-activate.XXXXXX)
candidate_runtime="$work_dir/runtime.env"
cookie_jar="$work_dir/cookie.jar"
headers="$work_dir/headers"
login_body="$work_dir/login.json"
source_body="$work_dir/source-part"
chmod 700 "$work_dir"
touch "$cookie_jar" "$headers" "$login_body" "$source_body"
chmod 600 "$cookie_jar" "$headers" "$login_body" "$source_body"
replacement_started=false
cleanup() { rm -rf -- "$work_dir"; }
rollback_on_failure() {
  status=$?
  trap - EXIT
  if (( status != 0 )) && [[ "$replacement_started" == true ]]; then
    "$(dirname "$0")/rollback-reviewed-service.sh" "$rollback_dir" || printf 'AUTOMATIC ROLLBACK FAILED: %s\n' "$rollback_dir" >&2
  fi
  cleanup
  exit "$status"
}
trap rollback_on_failure EXIT

# Preserve immutable references before loading/building any candidate tag. The
# unique tags prevent a candidate build or later dangling-image cleanup from
# destroying the only usable rollback reference.
install -d -m 700 "$rollback_dir"
install -m 600 "$current_compose" "$rollback_dir/compose.yaml"
install -m 600 "$current_caddyfile" "$rollback_dir/Caddyfile"
install -m 600 "$runtime_env" "$rollback_dir/runtime.env"
sha256sum "$haproxy_config" >"$rollback_dir/haproxy.sha256"
grep -E 'meserproject\.duckdns\.org|127\.0\.0\.1:9443|127\.0\.0\.1:9444|default_backend xray_reality' "$haproxy_config" >"$rollback_dir/haproxy-invariants.txt"
for service in gateway caddy; do
  container=$(docker compose --project-name meser-audio-archive --env-file "$runtime_env" -f "$current_compose" ps -q "$service")
  [[ -n "$container" ]] || die "current $service container is unavailable"
  prior_id=$(docker inspect -f '{{.Image}}' "$container")
  [[ "$prior_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die "current $service image ID is invalid"
  rollback_ref="meser-s10a-rollback-$timestamp-$service:preserved"
  docker image tag "$prior_id" "$rollback_ref"
  printf '%s\n' "$prior_id" >"$rollback_dir/prior-$service.image-id"
  printf '%s\n' "$rollback_ref" >"$rollback_dir/prior-$service.image-ref"
  docker inspect -f '{{.Id}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container" >"$rollback_dir/prior-$service.container"
done
cat >"$rollback_dir/rollback-compose.override.yaml" <<EOF
services:
  gateway:
    image: $(<"$rollback_dir/prior-gateway.image-ref")
  caddy:
    image: $(<"$rollback_dir/prior-caddy.image-ref")
EOF
chmod 600 "$rollback_dir"/*

# Preserve only allowlisted non-secret runtime values and bind candidate Compose
# to the exact image references recorded by the reviewed release.
runtime_value() { awk -F= -v key="$1" '$1 == key { sub(/^[^=]*=/, ""); print }' "$runtime_env"; }
github_app_id=$(runtime_value GITHUB_APP_ID)
github_installation_id=$(runtime_value GITHUB_APP_INSTALLATION_ID)
[[ "$github_app_id" =~ ^[0-9]+$ && "$github_installation_id" =~ ^[0-9]+$ ]] || die 'runtime GitHub App identities are invalid'
cat >"$candidate_runtime" <<EOF
SOURCE_SHA=$source_sha
GATEWAY_IMAGE=$gateway_ref
CADDY_IMAGE=$caddy_ref
GITHUB_APP_ID=$github_app_id
GITHUB_APP_INSTALLATION_ID=$github_installation_id
ALLOWED_ORIGIN=$service_origin
MESER_SITE_ADDRESS=meserproject.duckdns.org
MESER_HTTP_BIND=80
MESER_TLS_BIND=127.0.0.1:9443
MESER_RUNTIME_UID=1000
MESER_SYNTHETIC_RUNTIME=false
EOF
chmod 600 "$candidate_runtime"

docker load -i "$release_dir/gateway-image.tar" >/dev/null
docker load -i "$release_dir/caddy-frontend-image.tar" >/dev/null
[[ "$(docker image inspect -f '{{.Id}}' "$gateway_ref")" == "$gateway_id" ]] || die 'loaded gateway image ID differs from manifest'
[[ "$(docker image inspect -f '{{.Id}}' "$caddy_ref")" == "$caddy_id" ]] || die 'loaded Caddy image ID differs from manifest'
MESER_CONFIG_ROOT=/etc/meser-audio-archive docker compose --project-name meser-audio-archive --env-file "$candidate_runtime" -f "$release_dir/compose.yaml" config >/dev/null
docker run --rm -v "$release_dir/Caddyfile:/etc/caddy/Caddyfile:ro" "$caddy_ref" caddy validate --config /etc/caddy/Caddyfile

replacement_started=true
MESER_CONFIG_ROOT=/etc/meser-audio-archive docker compose --project-name meser-audio-archive --env-file "$candidate_runtime" -f "$release_dir/compose.yaml" up -d --no-build gateway caddy

curl --fail --silent --show-error "$service_origin/healthz" | jq -e '.ok == true' >/dev/null
curl --silent --show-error -D "$headers" -o /dev/null "$service_origin/"
[[ "$(awk 'NR == 1 { print $2 }' "$headers")" == 303 ]] || die 'unauthenticated landing was not redirected'
[[ "$(awk 'tolower($1) == "location:" { sub(/\r$/, "", $2); print $2 }' "$headers")" == '/login?return=%2F' ]] || die 'unauthenticated redirect return intent is not canonical'
jq -Rs '{password: sub("\\r?\\n$"; "")}' <"$password_file" >"$login_body"
curl --fail --silent --show-error -D "$headers" -c "$cookie_jar" -H "Origin: $service_origin" -H 'Content-Type: application/json' --data-binary "@$login_body" "$service_origin/v1/session/login" -o /dev/null
[[ "$(grep -Eic '^set-cookie: __Host-meser_service_session=' "$headers")" -eq 1 ]] || die 'canonical session cookie missing'
csrf=$(curl --fail --silent --show-error -b "$cookie_jar" "$service_origin/v1/session" | jq -er '.csrfToken')
for path in / /Calendar.html /Google-Drive.html /Audio-Editor.html /Audio-Archive.html /v1/config; do curl --fail --silent --show-error -b "$cookie_jar" "$service_origin$path" -o /dev/null; done

smoke_path=$(awk -F= '$1 == "path" { sub(/^[^=]*=/, ""); print }' "$source_smoke_record")
smoke_sha=$(awk -F= '$1 == "sha256" { print $2 }' "$source_smoke_record")
smoke_bytes=$(awk -F= '$1 == "bytes" { print $2 }' "$source_smoke_record")
[[ "$smoke_path" =~ ^/v1/source-sessions/[0-9a-f-]+/blobs/[0-9a-f-]+/parts/[0-9]+/content$ ]] || die 'source smoke path is not an allowlisted read-only part route'
[[ "$smoke_sha" =~ ^[0-9a-f]{64}$ && "$smoke_bytes" =~ ^[0-9]+$ ]] || die 'source smoke integrity record is invalid'
curl --fail --silent --show-error -b "$cookie_jar" "$service_origin$smoke_path" -o "$source_body"
[[ "$(sha256sum "$source_body" | awk '{ print $1 }')" == "$smoke_sha" && "$(stat -c '%s' "$source_body")" == "$smoke_bytes" ]] || die 'read-only source smoke integrity failed'

curl --fail --silent --show-error -b "$cookie_jar" -H "Origin: $service_origin" -H "X-CSRF-Token: $csrf" -X POST "$service_origin/v1/session/logout" -o /dev/null
[[ "$(curl --silent --output /dev/null --write-out '%{http_code}' -b "$cookie_jar" "$service_origin/v1/session")" == 401 ]] || die 'logout did not revoke session'

# The activation is accepted only after a new encrypted off-VM bundle for the
# activated identities has been created and verified.
post_output=$("$(dirname "$0")/../recovery/create-recovery-bundle.sh" "$release_dir" "$secret_dir" "$candidate_runtime" "$backup_destination" "$age_recipient" "$backup_mount_id" "$failure_domain_note")
post_bundle=${post_output#Recovery bundle created and verified: }
[[ -d "$post_bundle" && -f "$post_bundle/SHA256SUMS" ]] || die 'post-activation recovery bundle identity was not produced'
(cd "$post_bundle" && sha256sum -c SHA256SUMS >/dev/null) || die 'post-activation recovery bundle integrity failed'

install -m 640 "$release_dir/compose.yaml" "$current_compose"
install -m 640 "$release_dir/Caddyfile" "$current_caddyfile"
install -m 600 "$candidate_runtime" "$runtime_env"
deployment_dir="$deployment_root/$timestamp-$source_sha"
install -d -m 700 "$deployment_dir"
cat >"$deployment_dir/deployment-record.txt" <<EOF
activated_utc=$timestamp
source_sha=$source_sha
source_tree=$source_tree
gateway_image_id=$gateway_id
caddy_frontend_image_id=$caddy_id
compose_sha256=$(manifest_value compose_sha256)
caddy_sha256=$(manifest_value caddy_sha256)
haproxy_sha256=$(manifest_value haproxy_sha256)
precutover_recovery_bundle=$(basename "$precutover_bundle")
rollback_identity=$(basename "$rollback_dir")
source_integrity_path=$smoke_path
source_integrity_sha256=$smoke_sha
source_integrity_bytes=$smoke_bytes
smoke_archive_mutations=0
post_activation_recovery_bundle=$(basename "$post_bundle")
post_activation_recovery_sha256s=$(sha256sum "$post_bundle/SHA256SUMS" | awk '{ print $1 }')
EOF
chmod 600 "$deployment_dir/deployment-record.txt"

replacement_started=false
cleanup
trap - EXIT
printf 'S10A full-service activation checks passed for %s. Deployment record: %s. Post-activation recovery: %s\n' "$source_sha" "$deployment_dir" "$post_bundle"
