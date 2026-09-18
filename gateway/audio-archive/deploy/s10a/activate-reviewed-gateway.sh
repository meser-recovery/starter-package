#!/usr/bin/env bash
set -Eeuo pipefail

# Prepared only. Keep both gates false in Git. A later, explicit production
# authorization must name the reviewed HEAD and artifact before an operator may
# copy this script and change both values in that reviewed copy.
S10A_PRODUCTION_AUTHORIZED=false
S10A_INDEPENDENT_REVIEW_COMPLETE=false

die() { printf 'S10A ACTIVATION REFUSED: %s\n' "$*" >&2; exit 1; }
[[ "$S10A_PRODUCTION_AUTHORIZED" == true ]] || die 'production authorization gate is false'
[[ "$S10A_INDEPENDENT_REVIEW_COMPLETE" == true ]] || die 'independent review gate is false'
[[ $# -eq 4 ]] || die 'usage: activate-reviewed-gateway.sh <artifact.tar.gz> <artifact.sha256> <artifact.source-sha> <shared-password-file>'

artifact=$1
checksum_manifest=$2
source_record=$3
password_file=$4
gateway_origin=https://meserproject.duckdns.org
pages_origin=https://meser-recovery.github.io
runtime_env=/etc/meser-audio-archive/runtime.env
state_root=/var/backups/meser-audio-archive/s10a

for command in awk curl date docker grep gzip hostname id install jq mktemp readlink rm sed seq sha256sum sleep stat tar tr; do command -v "$command" >/dev/null || die "missing executable: $command"; done
[[ "${EUID:-$(id -u)}" -eq 0 ]] || die 'must run as root'
[[ "$(hostname)" == vmhome ]] || die 'unexpected host'
for path in "$artifact" "$checksum_manifest" "$source_record" "$password_file" "$runtime_env"; do [[ -f "$path" && ! -L "$path" ]] || die "unsafe or missing file: $path"; done
[[ "$(stat -c '%a' "$password_file")" == 600 ]] || die 'shared-password file must be mode 600'

source_sha=$(tr -d '\r\n' <"$source_record")
[[ "$source_sha" =~ ^[0-9a-f]{40}$ ]] || die 'invalid exact source SHA'
expected_hash=$(awk 'NF == 2 { print $1 }' "$checksum_manifest")
expected_name=$(awk 'NF == 2 { print $2 }' "$checksum_manifest")
[[ "$expected_hash" =~ ^[0-9a-f]{64}$ && "$expected_name" == "$(basename "$artifact")" ]] || die 'invalid checksum manifest'
[[ "$(sha256sum "$artifact" | awk '{print $1}')" == "$expected_hash" ]] || die 'artifact checksum mismatch'
[[ "$(basename "$artifact")" == "meser-audio-archive-s10a-${source_sha}.tar.gz" ]] || die 'artifact name/source mismatch'

work_dir=$(mktemp -d /var/tmp/meser-s10a-activate.XXXXXX)
cookie_jar=$(mktemp /var/tmp/meser-s10a-cookie.XXXXXX)
headers_file=$(mktemp /var/tmp/meser-s10a-headers.XXXXXX)
login_file=$(mktemp /var/tmp/meser-s10a-login.XXXXXX)
chmod 600 "$cookie_jar" "$headers_file" "$login_file"
replacement_started=false
rollback_dir=
cleanup() { rm -f -- "$cookie_jar" "$headers_file" "$login_file"; rm -rf -- "$work_dir"; }
rollback_on_failure() {
  status=$?
  trap - EXIT
  if (( status != 0 )) && [[ "$replacement_started" == true && -n "$rollback_dir" ]]; then
    "$(dirname "$0")/rollback-reviewed-gateway.sh" "$rollback_dir" || printf 'AUTOMATIC ROLLBACK FAILED; use %s immediately\n' "$rollback_dir" >&2
  fi
  cleanup
  exit "$status"
}
trap rollback_on_failure EXIT

curl --fail --silent --show-error "$gateway_origin/healthz" | jq -e '.ok == true and .service == "audio-archive-gateway"' >/dev/null
curl --fail --silent --show-error -H "Origin: $pages_origin" "$gateway_origin/v1/config" \
  | jq -e '.maximumSessionSize == 524288000 and .speakerProjectHistory == 1' >/dev/null

current_container=$(docker compose --env-file "$runtime_env" -f /opt/meser-audio-archive/deploy/self-hosted/compose.yaml ps -q gateway)
[[ -n "$current_container" ]] || die 'current gateway container is unavailable'
current_image=$(docker inspect -f '{{.Image}}' "$current_container")
[[ "$current_image" =~ ^sha256:[0-9a-f]{64}$ ]] || die 'current gateway image identity is invalid'
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
rollback_dir="$state_root/$timestamp"
install -d -m 700 "$rollback_dir"
printf '%s\n' "$current_image" >"$rollback_dir/prior-image-id"
printf '%s\n' "$current_container" >"$rollback_dir/prior-container-id"
printf '%s\n' "$source_sha" >"$rollback_dir/candidate-source-sha"
docker inspect -f '{{.Name}} {{.Config.Image}} {{.Image}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' "$current_container" >"$rollback_dir/prior-runtime-identity.txt"
chmod 600 "$rollback_dir"/*

tar -tzf "$artifact" | grep -E "^meser-audio-archive-s10a-${source_sha}/gateway/audio-archive/Dockerfile$" >/dev/null || die 'artifact layout is invalid'
tar -xzf "$artifact" -C "$work_dir" --no-same-owner --no-same-permissions
candidate="$work_dir/meser-audio-archive-s10a-${source_sha}/gateway/audio-archive"
[[ -f "$candidate/Dockerfile" && -f "$candidate/deploy/self-hosted/compose.yaml" ]] || die 'candidate gateway is incomplete'

docker compose --project-name meser-audio-archive --env-file "$runtime_env" -f "$candidate/deploy/self-hosted/compose.yaml" \
  build --pull=false gateway
replacement_started=true
docker compose --project-name meser-audio-archive --env-file "$runtime_env" -f "$candidate/deploy/self-hosted/compose.yaml" \
  up -d --no-deps --no-build gateway

new_container=$(docker compose --project-name meser-audio-archive --env-file "$runtime_env" -f "$candidate/deploy/self-hosted/compose.yaml" ps -q gateway)
[[ -n "$new_container" && "$new_container" != "$current_container" ]] || die 'gateway container was not replaced'
for attempt in $(seq 1 30); do
  [[ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$new_container")" == healthy ]] && break
  sleep 2
done
[[ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$new_container")" == healthy ]] || die 'candidate gateway did not become healthy'

curl --fail --silent --show-error "$gateway_origin/healthz" | jq -e '.ok == true' >/dev/null
curl --fail --silent --show-error -D "$headers_file" "$gateway_origin/safari-bootstrap" -o /dev/null
grep -Eiq '^cache-control: no-store' "$headers_file" && grep -Eiq "^content-security-policy:.*frame-ancestors 'none'" "$headers_file" || die 'bootstrap security headers failed'
curl --fail --silent --show-error -D "$headers_file" "$gateway_origin/storage-access-bridge" -o /dev/null
grep -Eiq '^cache-control: no-store' "$headers_file" && grep -Eiq '^content-security-policy:.*frame-ancestors https://meser-recovery.github.io' "$headers_file" || die 'bridge security headers failed'

jq -Rs '{password: sub("\\r?\\n$"; "")}' <"$password_file" >"$login_file"
curl --fail --silent --show-error -D "$headers_file" -c "$cookie_jar" -H "Origin: $pages_origin" -H 'Content-Type: application/json' \
  --data-binary "@$login_file" "$gateway_origin/v1/session/login" -o /dev/null
printf '{}' >"$login_file"
[[ "$(grep -Eic '^set-cookie: __Host-meser_audio_(session|storage_session)=' "$headers_file")" -eq 2 ]] || die 'two independent session cookies were not delivered'
grep -Eiq '^set-cookie: __Host-meser_audio_session=.*; Partitioned' "$headers_file" || die 'partitioned cookie attributes failed'
grep -Eiq '^set-cookie: __Host-meser_audio_storage_session=' "$headers_file" || die 'storage-access cookie is missing'
curl --fail --silent --show-error -b "$cookie_jar" -H "Origin: $pages_origin" "$gateway_origin/v1/session" \
  | jq -e '.authenticated == true and (.csrfToken | type == "string")' >/dev/null

replacement_started=false
printf 'S10A gateway activation checks passed for %s. Rollback identity: %s\n' "$source_sha" "$rollback_dir"
