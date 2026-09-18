#!/usr/bin/env bash
set -Eeuo pipefail

die() { printf 'S10A ROLLBACK REFUSED: %s\n' "$*" >&2; exit 1; }
[[ $# -eq 1 ]] || die 'usage: rollback-reviewed-service.sh <captured-rollback-directory>'
state=$1
synthetic=${MESER_ROLLBACK_SYNTHETIC_TEST:-false}
if [[ "$synthetic" == true ]]; then
  [[ "$state" == /tmp/meser-synthetic-rollback.* && -d "$state" && ! -L "$state" ]] || die 'unsafe synthetic rollback directory'
else
  [[ "$state" = /var/backups/meser-audio-archive/s10a/* && -d "$state" && ! -L "$state" ]] || die 'unsafe rollback directory'
fi
for file in compose.yaml Caddyfile runtime.env rollback-compose.override.yaml prior-gateway.image-id prior-caddy.image-id prior-gateway.image-ref prior-caddy.image-ref haproxy.sha256; do
  [[ -f "$state/$file" && ! -L "$state/$file" ]] || die "missing rollback file: $file"
done
haproxy_config=${MESER_HAPROXY_CONFIG:-/etc/haproxy/haproxy.cfg}
expected_haproxy=$(awk '{ print $2 }' "$state/haproxy.sha256")
[[ "$expected_haproxy" == "$haproxy_config" ]] || die 'HAProxy checksum targets an unexpected file'
(cd / && sha256sum -c "$state/haproxy.sha256" >/dev/null) || die 'HAProxy changed; rollback refuses to alter it'

gateway_id=$(<"$state/prior-gateway.image-id")
caddy_id=$(<"$state/prior-caddy.image-id")
gateway_ref=$(<"$state/prior-gateway.image-ref")
caddy_ref=$(<"$state/prior-caddy.image-ref")
[[ "$gateway_id" =~ ^sha256:[0-9a-f]{64}$ && "$caddy_id" =~ ^sha256:[0-9a-f]{64}$ ]] || die 'captured image ID is invalid'
[[ "$gateway_ref" =~ ^meser-s10a-rollback-[0-9-]+-gateway:preserved$ && "$caddy_ref" =~ ^meser-s10a-rollback-[0-9-]+-caddy:preserved$ ]] || die 'captured rollback image reference is invalid'
[[ "$(docker image inspect -f '{{.Id}}' "$gateway_ref")" == "$gateway_id" ]] || die 'preserved gateway rollback reference changed'
[[ "$(docker image inspect -f '{{.Id}}' "$caddy_ref")" == "$caddy_id" ]] || die 'preserved Caddy rollback reference changed'

project_name=${MESER_ROLLBACK_PROJECT_NAME:-meser-audio-archive}
config_root=${MESER_CONFIG_ROOT:-/etc/meser-audio-archive}
compose=(docker compose --project-name "$project_name" --env-file "$state/runtime.env" -f "$state/compose.yaml" -f "$state/rollback-compose.override.yaml")
MESER_CONFIG_ROOT="$config_root" "${compose[@]}" config >/dev/null
MESER_CONFIG_ROOT="$config_root" "${compose[@]}" up -d --no-build --force-recreate gateway caddy
gateway_container=$(MESER_CONFIG_ROOT="$config_root" "${compose[@]}" ps -q gateway)
caddy_container=$(MESER_CONFIG_ROOT="$config_root" "${compose[@]}" ps -q caddy)
[[ "$(docker inspect -f '{{.Image}}' "$gateway_container")" == "$gateway_id" ]] || die 'gateway did not return to the exact prior image ID'
[[ "$(docker inspect -f '{{.Image}}' "$caddy_container")" == "$caddy_id" ]] || die 'Caddy did not return to the exact prior image ID'
service_origin=$(awk -F= '$1 == "ALLOWED_ORIGIN" { print $2 }' "$state/runtime.env")
for attempt in {1..30}; do
  if curl --fail --silent --show-error "$service_origin/healthz" >/dev/null 2>&1; then break; fi
  [[ "$attempt" -lt 30 ]] || die 'rolled-back service failed its health check'
  sleep 1
done
if [[ "$synthetic" != true ]]; then
  install -m 640 "$state/compose.yaml" /opt/meser-audio-archive/deploy/self-hosted/compose.yaml
  install -m 640 "$state/Caddyfile" /opt/meser-audio-archive/deploy/self-hosted/Caddyfile
  install -m 600 "$state/runtime.env" /etc/meser-audio-archive/runtime.env
fi
printf 'Rollback restored exact gateway %s and Caddy %s image IDs and healthy service.\n' "$gateway_id" "$caddy_id"
