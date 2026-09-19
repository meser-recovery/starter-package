#!/usr/bin/env bash
set -Eeuo pipefail

die() { printf 'SYNTHETIC ROLLBACK REHEARSAL FAILED: %s\n' "$*" >&2; exit 1; }
[[ $# -eq 3 ]] || die 'usage: synthetic-docker-rollback-rehearsal.sh <release-dir> <config-root> <runtime-input>'
runtime_schema="$(dirname "$0")/../recovery/runtime-env.sh"
[[ -f "$runtime_schema" && ! -L "$runtime_schema" ]] || die 'canonical runtime schema is missing or unsafe'
# shellcheck source=../recovery/runtime-env.sh
source "$runtime_schema"
container_state_capture="$(dirname "$0")/capture-container-state.sh"
[[ -f "$container_state_capture" && ! -L "$container_state_capture" && -x "$container_state_capture" ]] || die 'container state capture helper is missing or unsafe'
release_dir=$1
config_root=$2
runtime_input=$3
for path in "$release_dir" "$config_root" "$runtime_input"; do [[ -e "$path" && ! -L "$path" ]] || die "unsafe input: $path"; done
meser_validate_runtime_env_shape "$runtime_input" || die 'runtime input is not the canonical 11-key schema'
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

runtime_value() { meser_runtime_value "$runtime_input" "$1"; }
write_runtime() {
  gateway=$1 caddy=$2 output=$3
  meser_write_runtime_env "$output" "$source_sha" "$gateway" "$caddy" \
    "$(runtime_value GITHUB_APP_ID)" "$(runtime_value GITHUB_APP_INSTALLATION_ID)" "$(runtime_value ALLOWED_ORIGIN)" \
    "$(runtime_value MESER_SITE_ADDRESS)" "$(runtime_value MESER_HTTP_BIND)" "$(runtime_value MESER_TLS_BIND)" \
    "$(runtime_value MESER_RUNTIME_UID)" "$(runtime_value MESER_SYNTHETIC_RUNTIME)" \
    || die 'failed to write canonical synthetic rollback runtime'
}
write_runtime "$prior_gateway" "$prior_caddy" "$work/runtime.env"
MESER_CONFIG_ROOT="$config_root" docker compose --project-name "$project" --env-file "$work/runtime.env" -f "$release_dir/compose.yaml" up -d --no-build gateway caddy
for attempt in {1..30}; do curl --fail --silent "$(runtime_value ALLOWED_ORIGIN)/healthz" >/dev/null 2>&1 && break; [[ "$attempt" -lt 30 ]] || die 'synthetic prior stack is unhealthy'; sleep 1; done
running_prior_gateway=$(MESER_CONFIG_ROOT="$config_root" docker compose --project-name "$project" --env-file "$work/runtime.env" -f "$release_dir/compose.yaml" ps -q gateway)
running_prior_caddy=$(MESER_CONFIG_ROOT="$config_root" docker compose --project-name "$project" --env-file "$work/runtime.env" -f "$release_dir/compose.yaml" ps -q caddy)
"$container_state_capture" "$running_prior_gateway" "$work/prior-gateway.container"
"$container_state_capture" "$running_prior_caddy" "$work/prior-caddy.container"
state_value() { awk -F= -v key="$1" '$1 == key { sub(/^[^=]*=/, ""); print }' "$2"; }
[[ "$(state_value container_id "$work/prior-gateway.container")" == "$running_prior_gateway" ]] || die 'gateway container identity capture mismatch'
[[ "$(state_value image_id "$work/prior-gateway.container")" == "$prior_gateway_id" ]] || die 'gateway image identity capture mismatch'
[[ "$(state_value status "$work/prior-gateway.container")" == running ]] || die 'gateway running status was not captured'
[[ "$(state_value health_status "$work/prior-gateway.container")" == healthy ]] || die 'gateway health status was not captured'
[[ "$(state_value container_id "$work/prior-caddy.container")" == "$running_prior_caddy" ]] || die 'Caddy container identity capture mismatch'
[[ "$(state_value image_id "$work/prior-caddy.container")" == "$prior_caddy_id" ]] || die 'Caddy image identity capture mismatch'
[[ "$(state_value status "$work/prior-caddy.container")" == running ]] || die 'Caddy running status was not captured'
[[ "$(state_value health_status "$work/prior-caddy.container")" == not-configured ]] || die 'healthless Caddy was not captured explicitly'
printf 'Synthetic Docker container-state capture: PASS (healthy gateway, healthless Caddy, exact container/image identities)\n'

cp "$release_dir/compose.yaml" "$work/compose.yaml"
cp "$release_dir/Caddyfile" "$work/Caddyfile"
printf 'synthetic haproxy invariant\n' >"$work/haproxy.cfg"
sha256sum "$work/haproxy.cfg" >"$work/haproxy.sha256"
timestamp=20260918-000000
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
