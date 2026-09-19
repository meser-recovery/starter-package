#!/usr/bin/env bash
set -Eeuo pipefail

die() { printf 'CONTAINER STATE CAPTURE REFUSED: %s\n' "$*" >&2; exit 1; }
[[ $# -eq 2 ]] || die 'usage: capture-container-state.sh <container> <output-file>'

container=$1
output=$2
output_dir=$(dirname -- "$output")
[[ -n "$container" ]] || die 'container identity is empty'
[[ -d "$output_dir" && ! -L "$output_dir" ]] || die 'output directory is missing or unsafe'
[[ ! -e "$output" && ! -L "$output" ]] || die 'output file already exists or is symlinked'

inspect_json=''
if ! inspect_json=$(docker inspect --type container "$container"); then
  die 'docker inspect failed'
fi
[[ -n "$inspect_json" ]] || die 'docker inspect returned an empty result'

parsed=''
if ! parsed=$(jq -er '
  if type != "array" or length != 1 then error("expected one inspected container") else .[0] end
  | . as $container
  | if ($container.Id | type) != "string" or ($container.Id | test("^[0-9a-f]{64}$") | not)
    then error("invalid container ID") else . end
  | if ($container.Image | type) != "string" or ($container.Image | test("^sha256:[0-9a-f]{64}$") | not)
    then error("invalid image ID") else . end
  | if ($container.State | type) != "object"
    then error("invalid container state") else . end
  | if ($container.State.Status | type) != "string" or ($container.State.Status | test("^[a-z][a-z0-9-]*$") | not)
    then error("invalid container status") else . end
  | ($container.State
      | if has("Health")
        then if (.Health | type) != "object"
             or (.Health.Status | type) != "string"
             or (.Health.Status | test("^[a-z][a-z0-9-]*$") | not)
             then error("invalid health status")
             else .Health.Status
             end
        else "not-configured"
        end) as $health
  | [$container.Id, $container.Image, $container.State.Status, $health]
  | @tsv
' <<<"$inspect_json"); then
  die 'docker inspect returned malformed container state'
fi

IFS=$'\t' read -r container_id image_id container_status health_status extra <<<"$parsed"
[[ -n "$container_id" && -n "$image_id" && -n "$container_status" && -n "$health_status" && -z "${extra:-}" ]] \
  || die 'parsed container state is incomplete'

temporary=$(mktemp "$output_dir/.container-state.XXXXXX")
cleanup() { rm -f -- "${temporary:-}"; }
trap cleanup EXIT
chmod 600 "$temporary"
printf 'container_id=%s\nimage_id=%s\nstatus=%s\nhealth_status=%s\n' \
  "$container_id" "$image_id" "$container_status" "$health_status" >"$temporary"
mv -- "$temporary" "$output"
temporary=''
trap - EXIT
