#!/usr/bin/env bash
set -Eeuo pipefail

for command in age age-keygen docker git node openssl python3 sha256sum; do command -v "$command" >/dev/null || { printf 'DOCKER RESTORE REHEARSAL SKIPPED: missing %s\n' "$command" >&2; exit 77; }; done
repository=$(git rev-parse --show-toplevel)
source_sha=$(git rev-parse HEAD)
work=$(mktemp -d /tmp/meser-docker-recovery.XXXXXX)
service_root=$(mktemp -d /tmp/meser-synthetic-restore.XXXXXX)
cleanup() {
  if [[ -f "$service_root/.restore-project-name" && -f "$service_root/config/runtime.env" ]]; then
    project=$(<"$service_root/.restore-project-name")
    MESER_CONFIG_ROOT="$service_root/config" docker compose --project-name "$project" --env-file "$service_root/config/runtime.env" -f "$service_root/deploy/self-hosted/compose.yaml" stop gateway caddy >/dev/null 2>&1 || true
    MESER_CONFIG_ROOT="$service_root/config" docker compose --project-name "$project" --env-file "$service_root/config/runtime.env" -f "$service_root/deploy/self-hosted/compose.yaml" rm -f gateway caddy >/dev/null 2>&1 || true
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
chmod 600 "$work/secrets"/*
cat >"$work/runtime.env" <<EOF
GITHUB_APP_ID=10001
GITHUB_APP_INSTALLATION_ID=20002
ALLOWED_ORIGIN=http://127.0.0.1:18080
MESER_SITE_ADDRESS=http://
MESER_HTTP_BIND=127.0.0.1:18080
MESER_TLS_BIND=127.0.0.1:19443
MESER_RUNTIME_UID=$(id -u)
EOF
"$repository/gateway/audio-archive/deploy/s10a/synthetic-docker-rollback-rehearsal.sh" "$work/release" "$work/secrets" "$work/runtime.env"
age-keygen -o "$work/identity.txt" >/dev/null 2>&1
chmod 600 "$work/identity.txt"
recipient=$(age-keygen -y "$work/identity.txt")
MESER_RECOVERY_SYNTHETIC_TEST=true "$repository/gateway/audio-archive/deploy/recovery/create-recovery-bundle.sh" \
  "$work/release" "$work/secrets" "$work/runtime.env" "$work/destination" "$recipient" synthetic-docker-mount 'CI Docker fixture'
bundle=$(find "$work/destination" -mindepth 1 -maxdepth 1 -type d -name 'meser-service-recovery-*' -print)
gateway_ref=$(awk -F= '$1 == "gateway_image_ref" { print $2 }' "$work/release/release-manifest.txt")
caddy_ref=$(awk -F= '$1 == "caddy_frontend_image_ref" { print $2 }' "$work/release/release-manifest.txt")
docker image rm "$gateway_ref" "$caddy_ref" >/dev/null
MESER_RECOVERY_SYNTHETIC_TEST=true "$repository/gateway/audio-archive/deploy/recovery/restore-meser-service.sh" "$bundle" "$work/identity.txt" "$service_root"
python3 "$repository/tests/safety/s10a_caddy_e2e.py" --base-url http://127.0.0.1:18080
printf 'Synthetic Docker clean-machine restore rehearsal: PASS (exact image IDs, health, Caddy runtime and no archive writes)\n'
