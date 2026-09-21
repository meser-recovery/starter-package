#!/bin/sh
set -eu

destination=${1:?usage: generate-s10a-real-mobile-waveform-fixture.sh DESTINATION}
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repository=$(CDPATH= cd -- "$script_dir/../../.." && pwd)
: "${FFMPEG_BIN:?FFMPEG_BIN is required}"
: "${FFPROBE_BIN:?FFPROBE_BIN is required}"
: "${FFMPEG_VERSION:?FFMPEG_VERSION is required}"
: "${FFMPEG_SHA256:?FFMPEG_SHA256 is required}"
: "${FFPROBE_SHA256:?FFPROBE_SHA256 is required}"
node "$repository/gateway/audio-archive/tools/verify-ffmpeg-toolchain.mjs"
duration=3747.648
mkdir -p "$destination"
[ -d "$destination" ] && [ ! -L "$destination" ] || { echo 'fixture destination must be a directory, not a symlink' >&2; exit 1; }

generate() {
  name=$1 frequency=$2 bitrate=$3
  "$FFMPEG_BIN" -hide_banner -loglevel error -nostdin -y \
    -f lavfi -i "sine=frequency=${frequency}:sample_rate=48000:duration=${duration}" \
    -c:a aac -profile:a aac_low -b:a "$bitrate" -ar 48000 -ac 1 -movflags +faststart \
    "$destination/$name"
}

generate track-1.m4a 311 28k
generate track-2.m4a 523 32k
generate track-3.m4a 887 48k

for file in "$destination/track-1.m4a" "$destination/track-2.m4a" "$destination/track-3.m4a"; do
  [ -f "$file" ] && [ ! -L "$file" ] || exit 1
  sha256sum "$file"
done
