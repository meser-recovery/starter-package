#!/usr/bin/env bash
set -Eeuo pipefail

# Canonical packaging environment. git archive takes timestamps/modes from the
# reviewed commit, gzip -n removes host time/name fields, and locale/order are
# fixed so independent hosts emit identical bytes.
export LC_ALL=C
export TZ=UTC

die() { printf 'PACKAGE REFUSED: %s\n' "$*" >&2; exit 1; }
[[ $# -eq 2 ]] || die 'usage: package-reviewed-service.sh <exact-git-sha> <output-directory>'
source_sha=$1
output_dir=$2
git rev-parse --verify "${source_sha}^{commit}" >/dev/null 2>&1 || die 'source SHA is not a commit'
[[ "$(git rev-parse "${source_sha}^{commit}")" == "$source_sha" ]] || die 'source SHA must be the full exact commit'
[[ -d "$output_dir" && ! -L "$output_dir" ]] || die 'output directory must already exist and must not be a symlink'

archive="$output_dir/meser-service-s10a-${source_sha}.tar.gz"
manifest="$archive.sha256"
source_record="$archive.source-sha"
tree_record="$archive.source-tree"
[[ ! -e "$archive" && ! -e "$manifest" && ! -e "$source_record" && ! -e "$tree_record" ]] || die 'refusing to overwrite an existing artifact'

node service/tools/verify-frontend.mjs
git_version=$(git version)
gzip_version=$(gzip --version 2>&1 | awk 'NR == 1 { print }')
node_version=$(node --version)
[[ -n "$git_version" && -n "$gzip_version" && "$node_version" =~ ^v[0-9]+\. ]] || die 'packaging toolchain versions are unavailable'
git archive --format=tar --prefix="meser-service-s10a-${source_sha}/" "$source_sha" \
  gateway/audio-archive service/frontend service/tools \
  | gzip -n >"$archive"
printf '%s  %s\n' "$(sha256sum "$archive" | awk '{print $1}')" "$(basename "$archive")" >"$manifest"
printf '%s\n' "$source_sha" >"$source_record"
git rev-parse "${source_sha}^{tree}" >"$tree_record"
printf 'Created %s\nManifest %s\nSource %s\nTree %s\n' "$archive" "$manifest" "$source_record" "$tree_record"
