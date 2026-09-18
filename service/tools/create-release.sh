#!/usr/bin/env bash
set -Eeuo pipefail

die() { printf 'RELEASE REFUSED: %s\n' "$*" >&2; exit 1; }
[[ $# -eq 2 ]] || die 'usage: create-release.sh <exact-git-sha> <empty-output-directory>'
source_sha=$1
output=$2
[[ "$source_sha" =~ ^[0-9a-f]{40}$ && "$(git rev-parse HEAD)" == "$source_sha" ]] || die 'checkout must be the exact source SHA'
git diff --quiet && git diff --cached --quiet || die 'working tree must be clean'
[[ -d "$output" && ! -L "$output" ]] || die 'output must be an existing non-symlink directory'
[[ -z "$(find "$output" -mindepth 1 -maxdepth 1 -print -quit)" ]] || die 'output directory must be empty'
for command in docker git sha256sum; do command -v "$command" >/dev/null || die "missing executable: $command"; done

"$(dirname "$0")/package-reviewed-service.sh" "$source_sha" "$output"
mv "$output/meser-service-s10a-${source_sha}.tar.gz" "$output/meser-service-source.tar.gz"
mv "$output/meser-service-s10a-${source_sha}.tar.gz.sha256" "$output/meser-service-source.tar.gz.sha256"
rm "$output/meser-service-s10a-${source_sha}.tar.gz.source-sha" "$output/meser-service-s10a-${source_sha}.tar.gz.source-tree"

gateway_tag="meser-service-gateway:${source_sha}"
caddy_tag="meser-service-caddy:${source_sha}"
docker build --pull=false --build-arg "SOURCE_SHA=$source_sha" -t "$gateway_tag" gateway/audio-archive
docker build --pull=false --build-arg "SOURCE_SHA=$source_sha" -f gateway/audio-archive/deploy/self-hosted/Caddy.Dockerfile -t "$caddy_tag" .
docker save -o "$output/gateway-image.tar" "$gateway_tag"
docker save -o "$output/caddy-frontend-image.tar" "$caddy_tag"
sha256sum "$output/gateway-image.tar" | sed "s#  .*/#  #" >"$output/gateway-image.tar.sha256"
sha256sum "$output/caddy-frontend-image.tar" | sed "s#  .*/#  #" >"$output/caddy-frontend-image.tar.sha256"
cp gateway/audio-archive/deploy/self-hosted/compose.yaml "$output/compose.yaml"
cp gateway/audio-archive/deploy/self-hosted/Caddyfile "$output/Caddyfile"
cp gateway/audio-archive/deploy/self-hosted/haproxy.cfg "$output/haproxy.cfg"

gateway_id=$(docker image inspect -f '{{.Id}}' "$gateway_tag")
caddy_id=$(docker image inspect -f '{{.Id}}' "$caddy_tag")
cat >"$output/release-manifest.txt" <<EOF
source_sha=$source_sha
source_tree=$(git rev-parse "${source_sha}^{tree}")
gateway_image_id=$gateway_id
caddy_frontend_image_id=$caddy_id
gateway_image_ref=$gateway_tag
caddy_frontend_image_ref=$caddy_tag
packaging_environment=ubuntu-24.04+node-24.7.0+git-archive-tar+gzip-n-v1
gateway_base=node:24-alpine@sha256:e67514e5d0f6c46656005e1b693b2ec9d52e80b641307de684d4a015ba7a4eaf
caddy_base=caddy:2.11.4-alpine@sha256:de23def33b17fb5d1290b0f6c2add1d70780e52341896c00a4c8a2a2fe9d355e
compose_sha256=$(sha256sum "$output/compose.yaml" | awk '{print $1}')
caddy_sha256=$(sha256sum "$output/Caddyfile" | awk '{print $1}')
haproxy_sha256=$(sha256sum "$output/haproxy.cfg" | awk '{print $1}')
EOF
