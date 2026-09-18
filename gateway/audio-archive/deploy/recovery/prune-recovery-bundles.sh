#!/usr/bin/env bash
set -Eeuo pipefail

die() { printf 'RECOVERY PRUNE REFUSED: %s\n' "$*" >&2; exit 1; }
[[ $# -eq 3 ]] || die 'usage: prune-recovery-bundles.sh <verified-backup-root> <expected-mount-id> <new-verified-bundle-name>'
root=$1
expected=$2
newest=$3
[[ "$root" = /* && -d "$root" && ! -L "$root" && -f "$root/.meser-recovery-target" ]] || die 'unsafe backup root'
[[ "$(tr -d '\r\n' <"$root/.meser-recovery-target")" == "$expected" ]] || die 'backup mount identity mismatch'
[[ "$newest" =~ ^meser-service-recovery-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{40}$ && -d "$root/$newest" && ! -L "$root/$newest" ]] || die 'new verified bundle missing'
(cd "$root/$newest" && sha256sum -c SHA256SUMS >/dev/null) || die 'new bundle integrity failed'

# Retention target: newest 8 weekly points plus the newest point in each UTC
# calendar month for 12 months. Only validated bundle directories below the
# verified root are candidates; symlinks and unexpected names fail closed.
mapfile -t bundles < <(find "$root" -mindepth 1 -maxdepth 1 -type d -name 'meser-service-recovery-*' -printf '%f\n' | LC_ALL=C sort -r)
keep=()
for index in "${!bundles[@]}"; do (( index < 8 )) && keep+=("${bundles[$index]}"); done
declare -A months=()
for bundle in "${bundles[@]}"; do
  stamp=${bundle#meser-service-recovery-}; month=${stamp:0:6}
  if [[ -z "${months[$month]:-}" && ${#months[@]} -lt 12 ]]; then months[$month]=1; keep+=("$bundle"); fi
done
for bundle in "${bundles[@]}"; do
  [[ "$bundle" =~ ^meser-service-recovery-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{40}$ ]] || die "unexpected bundle name: $bundle"
  [[ ! -L "$root/$bundle" ]] || die 'symlink bundle refused'
  retained=false
  for item in "${keep[@]}"; do [[ "$item" == "$bundle" ]] && retained=true; done
  [[ "$retained" == true ]] || rm -rf -- "$root/$bundle"
done
