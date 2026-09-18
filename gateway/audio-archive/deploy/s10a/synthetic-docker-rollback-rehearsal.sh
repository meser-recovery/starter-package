#!/usr/bin/env bash
set -Eeuo pipefail

die() { printf 'SYNTHETIC ROLLBACK REHEARSAL FAILED: %s\n' "$*" >&2; exit 1; }
[[ $# -eq 3 ]] || die 'usage: synthetic-docker-rollback-rehearsal.sh <release-dir> <config-root> <runtime-input>'
release_dir=$1
config_root=$2
runtime_input=$3
for path in "$release_dir" "$config_root" "$runtime_input"; do [[ -e "$path" && ! -L "$path" ]] || die "unsafe input: $path"; done
manifest="$release_dir/release-manifest.txt"
value() { awk -F= -v key="$1" '$1 == key { sub(/^[^=]*=/, ""); print }' "$manifest"; }
source_sha=$(value source_sha)
candidate_gateway=$(value gateway_image_ref)
candidate_caddy=$(value caddy_frontend_image_ref)
candidate_gateway_id=$(value gateway_image_id)
candidate_caddy_id=$(value caddy_frontend_image_id)
work=$(mktemp -d /tmp/meser-synthetic-rollback.XXXXXX)
project="meser-synthetic-rollback-${BASHPID}"
cleanup() {
  if [[ -f "$work/runtime.env" ]]; then
    MESER_CONFIG_ROOT="$config_root" docker compose --project-name "$project" --env-file "$work/runtime.env" -f "$release_dir/compose.yaml" stop gateway caddy >/dev/null 2>&1 || true
    MESER_CONFIG_ROOT="$config_root" docker compose --project-name "$project" --env-file "$work/runtime.env" -f "$release_dir/compose.yaml" rm -f gateway caddy >/dev/null 2>&1 || true
  fi
  rm -rf -- "$work"
}
trap cleanup EXIT

gateway_container=$(docker create "$candidate_gateway")
caddy_container=$(docker create "$candidate_caddy")
prior_gateway="meser-synthetic-prior-gateway:$source_sha"
prior_caddy="meser-synthetic-prior-caddy:$source_sha"
docker commit --change 'LABEL meser.synthetic.identity=prior-gateway' "$gateway_container" "$prior_gateway" >/dev/null
docker commit --change 'LABEL meser.synthetic.identity=prior-caddy' "$caddy_container" "$prior_caddy" >/dev/null
docker rm "$gateway_container" "$caddy_container" >/dev/null
prior_gateway_id=$(docker image inspect -f '{{.Id}}' "$prior_gateway")
prior_caddy_id=$(docker image inspect -f '{{.Id}}' "$prior_caddy")
[[ "$prior_gateway_id" != "$candidate_gateway_id" && "$prior_caddy_id" != "$candidate_caddy_id" ]] || die 'synthetic prior images are not distinct candidates'

runtime_value() { awk -F= -v key="$1" '$1 == key { sub(/^[^=]*=/, ""); print }' "$runtime_input"; }
write_runtime() {
  gateway=$1 caddy=$2 output=$3
  cat >"$output" <<EOF
SOURCE_SHA=$source_sha
GATEWAY_IMAGE=$gateway
CADDY_IMAGE=$caddy
GITHUB_APP_ID=$(runtime_value GITHUB_APP_ID)
GITHUB_APP_INSTALLATION_ID=$(runtime_value GITHUB_APP_INSTALLATION_ID)
ALLOWED_ORIGIN=$(runtime_value ALLOWED_ORIGIN)
MESER_SITE_ADDRESS=$(runtime_value MESER_SITE_ADDRESS)
MESER_HTTP_BIND=$(runtime_value MESER_HTTP_BIND)
MESER_TLS_BIND=$(runtime_value MESER_TLS_BIND)
MESER_RUNTIME_UID=$(runtime_value MESER_RUNTIME_UID)
MESER_SYNTHETIC_RUNTIME=$(runtime_value MESER_SYNTHETIC_RUNTIME)
EOF
}
write_runtime "$prior_gateway" "$prior_caddy" "$work/runtime.env"
MESER_CONFIG_ROOT="$config_root" docker compose --project-name "$project" --env-file "$work/runtime.env" -f "$release_dir/compose.yaml" up -d --no-build gateway caddy
for attempt in {1..30}; do curl --fail --silent "$(runtime_value ALLOWED_ORIGIN)/healthz" >/dev/null 2>&1 && break; [[ "$attempt" -lt 30 ]] || die 'synthetic prior stack is unhealthy'; sleep 1; done

cp "$release_dir/compose.yaml" "$work/compose.yaml"
cp "$release_dir/Caddyfile" "$work/Caddyfile"
printf 'synthetic haproxy invariant\n' >"$work/haproxy.cfg"
sha256sum "$work/haproxy.cfg" >"$work/haproxy.sha256"
timestamp=20260918T000000Z
gateway_rollback_ref="meser-s10a-rollback-$timestamp-gateway:preserved"
caddy_rollback_ref="meser-s10a-rollback-$timestamp-caddy:preserved"
docker image tag "$prior_gateway_id" "$gateway_rollback_ref"
docker image tag "$prior_caddy_id" "$caddy_rollback_ref"
printf '%s\n' "$prior_gateway_id" >"$work/prior-gateway.image-id"
printf '%s\n' "$prior_caddy_id" >"$work/prior-caddy.image-id"
printf '%s\n' "$gateway_rollback_ref" >"$work/prior-gateway.image-ref"
printf '%s\n' "$caddy_rollback_ref" >"$work/prior-caddy.image-ref"
cat >"$work/rollback-compose.override.yaml" <<EOF
services:
  gateway:
    image: $gateway_rollback_ref
  caddy:
    image: $caddy_rollback_ref
EOF

write_runtime "$candidate_gateway" "$candidate_caddy" "$work/candidate.env"
MESER_CONFIG_ROOT="$config_root" docker compose --project-name "$project" --env-file "$work/candidate.env" -f "$release_dir/compose.yaml" up -d --no-build --force-recreate gateway caddy
running_gateway=$(docker inspect -f '{{.Image}}' "$(MESER_CONFIG_ROOT="$config_root" docker compose --project-name "$project" --env-file "$work/candidate.env" -f "$release_dir/compose.yaml" ps -q gateway)")
running_caddy=$(docker inspect -f '{{.Image}}' "$(MESER_CONFIG_ROOT="$config_root" docker compose --project-name "$project" --env-file "$work/candidate.env" -f "$release_dir/compose.yaml" ps -q caddy)")
[[ "$running_gateway" == "$candidate_gateway_id" && "$running_caddy" == "$candidate_caddy_id" ]] || die 'candidate replacement did not occur'

# This is the forced post-replacement failure path under test.
MESER_ROLLBACK_SYNTHETIC_TEST=true MESER_ROLLBACK_PROJECT_NAME="$project" MESER_CONFIG_ROOT="$config_root" MESER_HAPROXY_CONFIG="$work/haproxy.cfg" \
  "$(dirname "$0")/rollback-reviewed-service.sh" "$work"
running_gateway=$(docker inspect -f '{{.Image}}' "$(MESER_CONFIG_ROOT="$config_root" docker compose --project-name "$project" --env-file "$work/runtime.env" -f "$release_dir/compose.yaml" ps -q gateway)")
running_caddy=$(docker inspect -f '{{.Image}}' "$(MESER_CONFIG_ROOT="$config_root" docker compose --project-name "$project" --env-file "$work/runtime.env" -f "$release_dir/compose.yaml" ps -q caddy)")
[[ "$running_gateway" == "$prior_gateway_id" && "$running_caddy" == "$prior_caddy_id" ]] || die 'exact prior image IDs were not restored'
curl --fail --silent "$(runtime_value ALLOWED_ORIGIN)/healthz" >/dev/null || die 'rolled-back stack is unhealthy'
printf 'Synthetic Docker rollback rehearsal: PASS (forced replacement failure restored exact gateway/Caddy image IDs and health)\n'
