#!/usr/bin/env bash

# Canonical non-secret service runtime schema. Keep this as the single writer
# and shape validator used by activation, scheduled backup and clean restore.
MESER_RUNTIME_KEYS_SORTED=$'ALLOWED_ORIGIN\nCADDY_IMAGE\nGATEWAY_IMAGE\nGITHUB_APP_ID\nGITHUB_APP_INSTALLATION_ID\nMESER_HTTP_BIND\nMESER_RUNTIME_UID\nMESER_SITE_ADDRESS\nMESER_SYNTHETIC_RUNTIME\nMESER_TLS_BIND\nSOURCE_SHA'

meser_runtime_value() {
  local runtime_file=$1 key=$2
  awk -F= -v key="$key" '$1 == key { sub(/^[^=]*=/, ""); print }' "$runtime_file"
}

meser_validate_runtime_env_shape() {
  local runtime_file=$1 actual_keys
  [[ -f "$runtime_file" && ! -L "$runtime_file" ]] || return 1
  awk -F= '
    NF != 2 || $1 !~ /^[A-Z][A-Z0-9_]*$/ || $2 == "" || index($0, "\r") { exit 1 }
    END { if (NR != 11) exit 1 }
  ' "$runtime_file" || return 1
  actual_keys=$(awk -F= '{ print $1 }' "$runtime_file" | LC_ALL=C sort)
  [[ "$actual_keys" == "$MESER_RUNTIME_KEYS_SORTED" ]]
}

meser_write_runtime_env() {
  [[ $# -eq 12 ]] || return 1
  local output=$1
  cat >"$output" <<EOF
SOURCE_SHA=$2
GATEWAY_IMAGE=$3
CADDY_IMAGE=$4
GITHUB_APP_ID=$5
GITHUB_APP_INSTALLATION_ID=$6
ALLOWED_ORIGIN=$7
MESER_SITE_ADDRESS=$8
MESER_HTTP_BIND=$9
MESER_TLS_BIND=${10}
MESER_RUNTIME_UID=${11}
MESER_SYNTHETIC_RUNTIME=${12}
EOF
  meser_validate_runtime_env_shape "$output"
}
