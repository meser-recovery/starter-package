#!/usr/bin/env bash
set -Eeuo pipefail

for command in age age-keygen docker git node openssl python3 sha256sum; do command -v "$command" >/dev/null || { printf 'DOCKER RESTORE REHEARSAL SKIPPED: missing %s\n' "$command" >&2; exit 77; }; done
repository=$(git rev-parse --show-toplevel)
runtime_schema="$repository/gateway/audio-archive/deploy/recovery/runtime-env.sh"
[[ -f "$runtime_schema" && ! -L "$runtime_schema" ]] || { printf 'DOCKER RESTORE REHEARSAL FAILED: canonical runtime schema is missing or unsafe\n' >&2; exit 1; }
# shellcheck source=runtime-env.sh
source "$runtime_schema"
source_sha=$(git rev-parse HEAD)
rehearsal_tmp_root=${MESER_REHEARSAL_TMP_ROOT:-/tmp}
[[ -d "$rehearsal_tmp_root" && ! -L "$rehearsal_tmp_root" ]] || { printf 'DOCKER RESTORE REHEARSAL FAILED: temporary root is missing or unsafe\n' >&2; exit 1; }
work=$(mktemp -d "$rehearsal_tmp_root/meser-docker-recovery.XXXXXX")
service_root=$(mktemp -d "$rehearsal_tmp_root/meser-synthetic-restore.XXXXXX")
cleanup() {
  if [[ -f "$service_root/.restore-project-name" && -f "$service_root/config/runtime.env" ]]; then
    project=$(<"$service_root/.restore-project-name")
    cleanup_extra=()
    if [[ -f "$service_root/deploy/self-hosted/compose.s12.yaml" ]]; then cleanup_extra=(-f "$service_root/deploy/self-hosted/compose.s12.yaml"); fi
    MESER_CONFIG_ROOT="$service_root/config" docker compose --project-name "$project" --env-file "$service_root/config/runtime.env" -f "$service_root/deploy/self-hosted/compose.yaml" "${cleanup_extra[@]}" stop gateway caddy >/dev/null 2>&1 || true
    MESER_CONFIG_ROOT="$service_root/config" docker compose --project-name "$project" --env-file "$service_root/config/runtime.env" -f "$service_root/deploy/self-hosted/compose.yaml" "${cleanup_extra[@]}" rm -f gateway caddy >/dev/null 2>&1 || true
  fi
  rm -rf -- "$work" "$service_root"
}
trap cleanup EXIT
mkdir "$work/release" "$work/secrets" "$work/destination"
printf '%s\n' synthetic-docker-mount >"$work/destination/.meser-recovery-target"

"$repository/service/tools/create-release.sh" "$source_sha" "$work/release"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out "$work/secrets/github-app.pem" >/dev/null 2>&1
node --input-type=module -e 'import { createPasswordVerifier } from "./gateway/audio-archive/src/auth.mjs"; console.log(await createPasswordVerifier("synthetic-caddy-password", Buffer.alloc(16, 23), { N: 16384, r: 8, p: 1 }));' >"$work/secrets/shared-password-verifier"
printf '%s\n' 'synthetic-signing-secret-0123456789abcdef' >"$work/secrets/session-signing-secret"
if [[ "${MESER_S12_RECOVERY_SYNTHETIC_TEST:-false}" == true ]]; then
  node "$repository/tests/safety/s12_recovery_fixture.mjs" create "$work" "$work/secrets/archive-settings-key"
  node "$repository/tests/safety/s12_recovery_fixture.mjs" rotate "$work" "$work/secrets/archive-settings-key"
fi
chmod 600 "$work/secrets"/*
gateway_ref=$(awk -F= '$1 == "gateway_image_ref" { print $2 }' "$work/release/release-manifest.txt")
caddy_ref=$(awk -F= '$1 == "caddy_frontend_image_ref" { print $2 }' "$work/release/release-manifest.txt")
meser_write_runtime_env "$work/runtime.env" "$source_sha" "$gateway_ref" "$caddy_ref" \
  10001 20002 http://127.0.0.1:18080 http:// 127.0.0.1:18080 127.0.0.1:19443 "$(id -u)" true
"$repository/gateway/audio-archive/deploy/s10a/synthetic-docker-rollback-rehearsal.sh" "$work/release" "$work/secrets" "$work/runtime.env"
age-keygen -o "$work/identity.txt" >/dev/null 2>&1
chmod 600 "$work/identity.txt"
recipient=$(age-keygen -y "$work/identity.txt")
MESER_RECOVERY_SYNTHETIC_TEST=true "$repository/gateway/audio-archive/deploy/recovery/create-recovery-bundle.sh" \
  "$work/release" "$work/secrets" "$work/runtime.env" "$work/destination" "$recipient" synthetic-docker-mount 'CI Docker fixture'
bundle=$(find "$work/destination" -mindepth 1 -maxdepth 1 -type d -name 'meser-service-recovery-*' -print)
docker image rm "$gateway_ref" "$caddy_ref" >/dev/null
if [[ "${MESER_S12_RECOVERY_SYNTHETIC_TEST:-false}" == true ]]; then rm "$work/secrets/archive-settings-key"; fi
MESER_RECOVERY_SYNTHETIC_TEST=true MESER_RECOVERY_SYNTHETIC_ROOT="$rehearsal_tmp_root" \
  "$repository/gateway/audio-archive/deploy/recovery/restore-meser-service.sh" "$bundle" "$work/identity.txt" "$service_root"
if [[ "${MESER_S12_RECOVERY_SYNTHETIC_TEST:-false}" == true ]]; then
  node "$repository/tests/safety/s12_recovery_fixture.mjs" verify "$work" "$service_root/config/archive-settings-key"
  project=$(<"$service_root/.restore-project-name")
  container=$(MESER_CONFIG_ROOT="$service_root/config" docker compose --project-name "$project" --env-file "$service_root/config/runtime.env" -f "$service_root/deploy/self-hosted/compose.yaml" -f "$service_root/deploy/self-hosted/compose.s12.yaml" ps -q gateway)
  sudo chown 0:0 "$service_root/config/archive-settings-runtime-key"
  # Run as the actual non-root container user; only a boolean, never the key, is printed.
  docker exec "$container" node --input-type=module -e 'import { loadConfig } from "./src/config.mjs"; if (!loadConfig().settingsKey || process.getuid() === 0) process.exit(1); console.log("S12 non-root key readiness: PASS");'
  test "$(stat -c '%a' "$service_root/config/archive-settings-key")" = 600
  test "$(stat -c '%a' "$service_root/config/archive-settings-runtime-key")" = 640
fi
python3 "$repository/tests/safety/s10a_caddy_e2e.py" --base-url http://127.0.0.1:18080
printf 'Synthetic Docker clean-machine restore rehearsal: PASS (exact image IDs, health, Caddy runtime and no archive writes)\n'
