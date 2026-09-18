#!/usr/bin/env bash
set -Eeuo pipefail

# Prepared only. A later reviewed operator copy must change both gates after the
# exact PR HEAD and off-VM recovery bundle have been accepted.
S10A_PRODUCTION_AUTHORIZED=false
S10A_INDEPENDENT_REVIEW_COMPLETE=false

die() { printf 'S10A ACTIVATION REFUSED: %s\n' "$*" >&2; exit 1; }
[[ "$S10A_PRODUCTION_AUTHORIZED" == true ]] || die 'production authorization gate is false'
[[ "$S10A_INDEPENDENT_REVIEW_COMPLETE" == true ]] || die 'independent review gate is false'
[[ $# -eq 5 ]] || die 'usage: activate-reviewed-service.sh <artifact.tar.gz> <artifact.sha256> <source-sha> <off-vm-recovery-bundle> <smoke-password-file>'

artifact=$1
checksum=$2
source_record=$3
recovery_bundle=$4
password_file=$5
runtime_env=/etc/meser-audio-archive/runtime.env
current_compose=/opt/meser-audio-archive/deploy/self-hosted/compose.yaml
rollback_root=/var/backups/meser-audio-archive/s10a
service_origin=https://meserproject.duckdns.org

for command in awk curl date docker grep hostname id install jq mktemp readlink sha256sum stat tar; do command -v "$command" >/dev/null || die "missing executable: $command"; done
[[ "${EUID:-$(id -u)}" -eq 0 ]] || die 'must run as root'
[[ "$(hostname)" == vmhome ]] || die 'unexpected host'
for path in "$artifact" "$checksum" "$source_record" "$recovery_bundle" "$password_file" "$runtime_env" "$current_compose"; do
  [[ -e "$path" && ! -L "$path" ]] || die "unsafe or missing input: $path"
done
[[ "$(stat -c '%a' "$password_file")" == 600 ]] || die 'smoke password must be mode 600'
[[ -f "$recovery_bundle/SHA256SUMS" && -f "$recovery_bundle/recovery-manifest.txt" ]] || die 'completed recovery bundle is required'
(cd "$recovery_bundle" && sha256sum -c SHA256SUMS >/dev/null) || die 'recovery bundle integrity failed'

source_sha=$(tr -d '\r\n' <"$source_record")
[[ "$source_sha" =~ ^[0-9a-f]{40}$ ]] || die 'invalid source SHA'
expected_hash=$(awk 'NF == 2 { print $1 }' "$checksum")
expected_name=$(awk 'NF == 2 { print $2 }' "$checksum")
[[ "$expected_hash" =~ ^[0-9a-f]{64}$ && "$expected_name" == "$(basename "$artifact")" ]] || die 'invalid checksum record'
[[ "$(sha256sum "$artifact" | awk '{print $1}')" == "$expected_hash" ]] || die 'artifact checksum mismatch'

work_dir=$(mktemp -d /var/tmp/meser-service-activate.XXXXXX)
cookie_jar=$(mktemp /var/tmp/meser-service-cookie.XXXXXX)
headers=$(mktemp /var/tmp/meser-service-headers.XXXXXX)
login_body=$(mktemp /var/tmp/meser-service-login.XXXXXX)
chmod 600 "$cookie_jar" "$headers" "$login_body"
rollback_dir="$rollback_root/$(date -u +%Y%m%dT%H%M%SZ)"
replacement_started=false
cleanup() { rm -f -- "$cookie_jar" "$headers" "$login_body"; rm -rf -- "$work_dir"; }
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

# Read-only capture of the complete Meser stack and ingress invariants. No secret
# values are printed or copied here; the encrypted recovery bundle is separate.
install -d -m 700 "$rollback_dir"
cp -- "$current_compose" "$rollback_dir/compose.yaml"
cp -- /opt/meser-audio-archive/deploy/self-hosted/Caddyfile "$rollback_dir/Caddyfile"
sha256sum /etc/haproxy/haproxy.cfg >"$rollback_dir/haproxy.sha256"
grep -E 'meserproject\.duckdns\.org|127\.0\.0\.1:9443|127\.0\.0\.1:9444|default_backend xray_reality' /etc/haproxy/haproxy.cfg >"$rollback_dir/haproxy-invariants.txt"
for service in gateway caddy; do
  container=$(docker compose --env-file "$runtime_env" -f "$current_compose" ps -q "$service")
  [[ -n "$container" ]] || die "current $service container is unavailable"
  docker inspect -f '{{.Id}} {{.Image}} {{.Config.Image}} {{.State.Status}}' "$container" >"$rollback_dir/prior-$service.txt"
done
chmod 600 "$rollback_dir"/*

listing="$work_dir/archive.list"
tar -tzf "$artifact" >"$listing"
grep -E "/gateway/audio-archive/Dockerfile$" "$listing" >/dev/null || die 'gateway source missing'
grep -E "/gateway/audio-archive/deploy/self-hosted/Caddy.Dockerfile$" "$listing" >/dev/null || die 'Caddy image source missing'
grep -E "/service/frontend/asset-allowlist.txt$" "$listing" >/dev/null || die 'protected frontend inventory missing'
tar -xzf "$artifact" -C "$work_dir" --no-same-owner --no-same-permissions
candidate=$(find "$work_dir" -mindepth 1 -maxdepth 1 -type d -name "meser-service-s10a-$source_sha" -print)
[[ -n "$candidate" && ! -L "$candidate" ]] || die 'artifact layout/source mismatch'
compose="$candidate/gateway/audio-archive/deploy/self-hosted/compose.yaml"
caddyfile="$candidate/gateway/audio-archive/deploy/self-hosted/Caddyfile"
SOURCE_SHA="$source_sha" docker compose --env-file "$runtime_env" -f "$compose" config >/dev/null
docker run --rm -v "$caddyfile:/etc/caddy/Caddyfile:ro" caddy:2.11.4-alpine@sha256:de23def33b17fb5d1290b0f6c2add1d70780e52341896c00a4c8a2a2fe9d355e caddy validate --config /etc/caddy/Caddyfile
SOURCE_SHA="$source_sha" docker compose --project-name meser-audio-archive --env-file "$runtime_env" -f "$compose" build --pull=false gateway caddy

replacement_started=true
SOURCE_SHA="$source_sha" docker compose --project-name meser-audio-archive --env-file "$runtime_env" -f "$compose" up -d --no-build gateway caddy

curl --fail --silent --show-error "$service_origin/healthz" | jq -e '.ok == true' >/dev/null
[[ "$(curl --silent --output /dev/null --write-out '%{http_code}' "$service_origin/")" == 303 ]] || die 'unauthenticated landing was not denied'
jq -Rs '{password: sub("\\r?\\n$"; "")}' <"$password_file" >"$login_body"
curl --fail --silent --show-error -D "$headers" -c "$cookie_jar" -H "Origin: $service_origin" -H 'Content-Type: application/json' --data-binary "@$login_body" "$service_origin/v1/session/login" -o /dev/null
printf '{}' >"$login_body"
[[ "$(grep -Eic '^set-cookie: __Host-meser_service_session=' "$headers")" -eq 1 ]] || die 'canonical session cookie missing'
csrf=$(curl --fail --silent --show-error -b "$cookie_jar" "$service_origin/v1/session" | jq -er '.csrfToken')
for path in / /Calendar.html /Google-Drive.html /Audio-Editor.html /Audio-Archive.html /v1/config; do curl --fail --silent --show-error -b "$cookie_jar" "$service_origin$path" -o /dev/null; done
curl --fail --silent --show-error -b "$cookie_jar" -H "Origin: $service_origin" -H "X-CSRF-Token: $csrf" -X POST "$service_origin/v1/session/logout" -o /dev/null
[[ "$(curl --silent --output /dev/null --write-out '%{http_code}' -b "$cookie_jar" "$service_origin/v1/session")" == 401 ]] || die 'logout did not revoke session'

replacement_started=false
printf 'S10A full-service activation checks passed for %s. Rollback identity: %s\n' "$source_sha" "$rollback_dir"
