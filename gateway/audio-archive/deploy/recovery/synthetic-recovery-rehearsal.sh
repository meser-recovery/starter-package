#!/usr/bin/env bash
set -Eeuo pipefail

for command in age age-keygen sha256sum tar; do command -v "$command" >/dev/null || { printf 'SYNTHETIC REHEARSAL SKIPPED: missing %s\n' "$command" >&2; exit 77; }; done
work=$(mktemp -d /tmp/meser-recovery-rehearsal.XXXXXX)
trap 'rm -rf -- "$work"' EXIT
mkdir "$work/release" "$work/secrets" "$work/destination"
printf '%s\n' 'synthetic-mount' >"$work/destination/.meser-recovery-target"
printf '%s\n' 'synthetic github app key' >"$work/secrets/github-app.pem"
printf '%s\n' 'synthetic verifier' >"$work/secrets/shared-password-verifier"
printf '%s\n' 'synthetic signing secret' >"$work/secrets/session-signing-secret"
chmod 600 "$work/secrets"/*
source_sha=1111111111111111111111111111111111111111
source_tree=2222222222222222222222222222222222222222
for name in meser-service-source.tar.gz gateway-image.tar caddy-frontend-image.tar compose.yaml Caddyfile haproxy.cfg; do printf 'synthetic %s\n' "$name" >"$work/release/$name"; done
sha256sum "$work/release/meser-service-source.tar.gz" | sed 's#  .*/#  #' >"$work/release/meser-service-source.tar.gz.sha256"
sha256sum "$work/release/gateway-image.tar" | sed 's#  .*/#  #' >"$work/release/gateway-image.tar.sha256"
sha256sum "$work/release/caddy-frontend-image.tar" | sed 's#  .*/#  #' >"$work/release/caddy-frontend-image.tar.sha256"
cat >"$work/release/release-manifest.txt" <<EOF
source_sha=$source_sha
source_tree=$source_tree
gateway_image_id=sha256:synthetic-gateway
caddy_frontend_image_id=sha256:synthetic-caddy
gateway_base=node@sha256:synthetic
caddy_base=caddy@sha256:synthetic
compose_sha256=$(sha256sum "$work/release/compose.yaml" | awk '{ print $1 }')
caddy_sha256=$(sha256sum "$work/release/Caddyfile" | awk '{ print $1 }')
haproxy_sha256=$(sha256sum "$work/release/haproxy.cfg" | awk '{ print $1 }')
EOF
age-keygen -o "$work/identity.txt" >/dev/null 2>&1
chmod 600 "$work/identity.txt"
recipient=$(age-keygen -y "$work/identity.txt")
MESER_RECOVERY_SYNTHETIC_TEST=true "$(dirname "$0")/create-recovery-bundle.sh" "$work/release" "$work/secrets" "$work/destination" "$recipient" synthetic-mount 'synthetic isolated fixture'
bundle=$(find "$work/destination" -mindepth 1 -maxdepth 1 -type d -name 'meser-service-recovery-*' -print)
[[ -n "$bundle" ]]
(cd "$bundle" && sha256sum -c SHA256SUMS >/dev/null)
age -d -i "$work/identity.txt" -o "$work/secrets.tar" "$bundle/secrets.age"
expected=$'github-app.pem\nsecret-metadata.txt\nsession-signing-secret\nshared-password-verifier'
[[ "$(tar -tf "$work/secrets.tar" | LC_ALL=C sort)" == "$expected" ]]

expect_refusal() {
  label=$1
  shift
  if "$@" >"$work/refusal.log" 2>&1; then
    printf 'Synthetic refusal case unexpectedly succeeded: %s\n' "$label" >&2
    exit 1
  fi
  grep -Eq 'REFUSED|invalid|missing|failed|incomplete|permission|unsafe' "$work/refusal.log"
}
create=(env MESER_RECOVERY_SYNTHETIC_TEST=true "$(dirname "$0")/create-recovery-bundle.sh")
expect_refusal wrong-mount "${create[@]}" "$work/release" "$work/secrets" "$work/destination" "$recipient" wrong-mount synthetic
expect_refusal missing-recipient "${create[@]}" "$work/release" "$work/secrets" "$work/destination" '' synthetic-mount synthetic
ln -s "$work/destination" "$work/destination-link"
expect_refusal symlink-destination "${create[@]}" "$work/release" "$work/secrets" "$work/destination-link" "$recipient" synthetic-mount synthetic
printf 'unexpected\n' >"$work/secrets/unknown-secret"
chmod 600 "$work/secrets/unknown-secret"
expect_refusal unknown-secret "${create[@]}" "$work/release" "$work/secrets" "$work/destination" "$recipient" synthetic-mount synthetic
rm "$work/secrets/unknown-secret"
chmod 644 "$work/secrets/session-signing-secret"
expect_refusal wrong-permissions "${create[@]}" "$work/release" "$work/secrets" "$work/destination" "$recipient" synthetic-mount synthetic
chmod 600 "$work/secrets/session-signing-secret"
cp "$work/release/gateway-image.tar" "$work/gateway-image.original"
printf 'corrupt\n' >>"$work/release/gateway-image.tar"
expect_refusal bad-checksum "${create[@]}" "$work/release" "$work/secrets" "$work/destination" "$recipient" synthetic-mount synthetic
cp "$work/gateway-image.original" "$work/release/gateway-image.tar"
cp "$work/release/release-manifest.txt" "$work/release-manifest.original"
grep -v '^gateway_image_id=' "$work/release-manifest.original" >"$work/release/release-manifest.txt"
expect_refusal incomplete-manifest "${create[@]}" "$work/release" "$work/secrets" "$work/destination" "$recipient" synthetic-mount synthetic

printf 'Synthetic recovery rehearsal: PASS (fixture only; create/integrity/decrypt plus seven refusal cases; no production material)\n'
