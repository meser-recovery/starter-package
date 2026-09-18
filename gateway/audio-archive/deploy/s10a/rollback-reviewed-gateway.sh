#!/usr/bin/env bash
set -Eeuo pipefail

die() { printf 'S10A ROLLBACK REFUSED: %s\n' "$*" >&2; exit 1; }
[[ $# -eq 1 ]] || die 'usage: rollback-reviewed-gateway.sh <captured-rollback-directory>'
rollback_dir=$1
runtime_env=/etc/meser-audio-archive/runtime.env
compose_file=/opt/meser-audio-archive/deploy/self-hosted/compose.yaml
[[ "${EUID:-$(id -u)}" -eq 0 ]] || die 'must run as root'
[[ -d "$rollback_dir" && ! -L "$rollback_dir" && "$(readlink -f "$rollback_dir")" == /var/backups/meser-audio-archive/s10a/* ]] || die 'unsafe rollback directory'
for path in "$rollback_dir/prior-image-id" "$rollback_dir/prior-container-id" "$compose_file" "$runtime_env"; do [[ -f "$path" && ! -L "$path" ]] || die "unsafe or missing file: $path"; done
prior_image=$(<"$rollback_dir/prior-image-id")
[[ "$prior_image" =~ ^sha256:[0-9a-f]{64}$ ]] || die 'invalid prior image identity'
docker image inspect "$prior_image" >/dev/null 2>&1 || die 'prior gateway image is unavailable'

override=$(mktemp /var/tmp/meser-s10a-rollback.XXXXXX.yaml)
trap 'rm -f -- "$override"' EXIT
printf 'services:\n  gateway:\n    image: %s\n' "$prior_image" >"$override"
docker compose --project-name meser-audio-archive --env-file "$runtime_env" -f "$compose_file" -f "$override" \
  up -d --no-deps --no-build gateway
container=$(docker compose --project-name meser-audio-archive --env-file "$runtime_env" -f "$compose_file" ps -q gateway)
[[ -n "$container" ]] || die 'rolled-back gateway container is unavailable'
for attempt in $(seq 1 30); do
  [[ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container")" == healthy ]] && break
  sleep 2
done
[[ "$(docker inspect -f '{{.Image}}' "$container")" == "$prior_image" ]] || die 'gateway did not return to the captured image'
[[ "$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container")" == healthy ]] || die 'rolled-back gateway is unhealthy'
curl --fail --silent --show-error https://meserproject.duckdns.org/healthz | grep -Fq '"ok":true' || die 'public health check failed after rollback'
printf 'S10A rollback restored gateway image %s\n' "$prior_image"
