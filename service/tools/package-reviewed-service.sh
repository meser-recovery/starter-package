#!/usr/bin/env bash
set -Eeuo pipefail

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
git archive --format=tar --prefix="meser-service-s10a-${source_sha}/" "$source_sha" \
  gateway/audio-archive service/frontend service/tools \
  | gzip -n >"$archive"
printf '%s  %s\n' "$(sha256sum "$archive" | awk '{print $1}')" "$(basename "$archive")" >"$manifest"
printf '%s\n' "$source_sha" >"$source_record"
git rev-parse "${source_sha}^{tree}" >"$tree_record"
printf 'Created %s\nManifest %s\nSource %s\nTree %s\n' "$archive" "$manifest" "$source_record" "$tree_record"
