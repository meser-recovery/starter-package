#!/usr/bin/env bash

# Shared, bounded readiness checks for the reviewed activation and rollback
# workflows. This file is sourced; it must not change state at load time.

meser_readiness_monotonic_ms() {
  python3 -c 'import time; print(time.monotonic_ns() // 1_000_000)'
}

meser_readiness_log() {
  local log_file=$1
  shift
  local line=$*
  printf '%s\n' "$line"
  printf '%s\n' "$line" >>"$log_file"
}

meser_readiness_prepare_log() {
  local log_file=$1
  : >"$log_file"
  chmod 600 "$log_file"
}

meser_readiness_sleep() {
  local remaining_ms=$1
  local interval=${MESER_READINESS_INTERVAL_SECONDS:-1}
  local requested_ms sleep_seconds
  requested_ms=$(awk -v interval="$interval" 'BEGIN { printf "%.0f\n", interval * 1000 }')
  (( requested_ms > 0 )) || requested_ms=1
  (( requested_ms < remaining_ms )) || requested_ms=$remaining_ms
  sleep_seconds=$(awk -v ms="$requested_ms" 'BEGIN { printf "%.3f\n", ms / 1000 }')
  sleep "$sleep_seconds"
}

meser_wait_container_ready() {
  local container=$1
  local expected_image=$2
  local service=$3
  local health_policy=$4
  local timeout_seconds=$5
  local log_file=$6
  local start now deadline elapsed attempt=0 inspect image status health result

  [[ "$expected_image" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
  [[ "$health_policy" == require-healthy || "$health_policy" == allow-not-configured ]] || return 1
  start=$(meser_readiness_monotonic_ms)
  deadline=$((start + timeout_seconds * 1000))

  while :; do
    attempt=$((attempt + 1))
    now=$(meser_readiness_monotonic_ms)
    elapsed=$((now - start))
    if (( now >= deadline )); then
      meser_readiness_log "$log_file" "READINESS layer=container service=$service attempt=$attempt elapsed_ms=$elapsed result=deadline-exhausted"
      return 1
    fi

    if ! inspect=$(docker inspect --type container "$container" 2>/dev/null); then
      result=inspect-transient
      meser_readiness_log "$log_file" "READINESS layer=container service=$service attempt=$attempt elapsed_ms=$elapsed status=unavailable health=unavailable result=$result"
    else
      image=$(jq -er 'if length == 1 then .[0].Image else error("unexpected inspect result") end' <<<"$inspect") || {
        meser_readiness_log "$log_file" "READINESS layer=container service=$service attempt=$attempt elapsed_ms=$elapsed result=malformed-inspect"
        return 1
      }
      status=$(jq -er '.[0].State.Status' <<<"$inspect") || return 1
      health=$(jq -er '.[0].State | if has("Health") and (.Health | type) == "object" then .Health.Status else "not-configured" end' <<<"$inspect") || return 1
      if [[ "$image" != "$expected_image" ]]; then
        meser_readiness_log "$log_file" "READINESS layer=container service=$service attempt=$attempt elapsed_ms=$elapsed status=$status health=$health result=image-mismatch"
        return 1
      fi
      case "$status" in
        exited|dead|removing)
          meser_readiness_log "$log_file" "READINESS layer=container service=$service attempt=$attempt elapsed_ms=$elapsed status=$status health=$health result=terminal-state"
          return 1
          ;;
        running)
          if [[ "$health_policy" == require-healthy && "$health" == healthy ]] ||
             [[ "$health_policy" == allow-not-configured && ( "$health" == healthy || "$health" == not-configured ) ]]; then
            meser_readiness_log "$log_file" "READINESS layer=container service=$service attempt=$attempt elapsed_ms=$elapsed status=$status health=$health result=ready"
            return 0
          fi
          ;;
      esac
      meser_readiness_log "$log_file" "READINESS layer=container service=$service attempt=$attempt elapsed_ms=$elapsed status=$status health=$health result=transient"
    fi

    now=$(meser_readiness_monotonic_ms)
    (( now < deadline )) || continue
    meser_readiness_sleep $((deadline - now))
  done
}

meser_wait_public_health() (
  local origin=$1
  local timeout_seconds=$2
  local phase=$3
  local log_file=$4
  local start now deadline elapsed remaining_ms attempt=0 consecutive=0
  local body error_file http curl_status result max_time connect_timeout
  body=$(mktemp /tmp/meser-readiness-body.XXXXXX)
  error_file=$(mktemp /tmp/meser-readiness-error.XXXXXX)
  trap 'rm -f -- "$body" "$error_file"' EXIT
  start=$(meser_readiness_monotonic_ms)
  deadline=$((start + timeout_seconds * 1000))

  while :; do
    attempt=$((attempt + 1))
    now=$(meser_readiness_monotonic_ms)
    elapsed=$((now - start))
    remaining_ms=$((deadline - now))
    if (( remaining_ms <= 0 )); then
      meser_readiness_log "$log_file" "READINESS layer=public phase=$phase attempt=$attempt elapsed_ms=$elapsed curl=none http=none consecutive=$consecutive result=deadline-exhausted"
      return 1
    fi
    max_time=$(awk -v remaining="$remaining_ms" -v configured="${MESER_READINESS_TOTAL_TIMEOUT_SECONDS:-5}" 'BEGIN { value=remaining/1000; if (value > configured) value=configured; if (value < 0.001) value=0.001; printf "%.3f\n", value }')
    connect_timeout=$(awk -v max_time="$max_time" -v configured="${MESER_READINESS_CONNECT_TIMEOUT_SECONDS:-2}" 'BEGIN { value=max_time; if (value > configured) value=configured; printf "%.3f\n", value }')
    : >"$body"
    : >"$error_file"
    set +e
    http=$(curl --silent --show-error --connect-timeout "$connect_timeout" --max-time "$max_time" --output "$body" --write-out '%{http_code}' "$origin/healthz" 2>"$error_file")
    curl_status=$?
    set -e
    http=${http:-000}

    if (( curl_status != 0 )); then
      consecutive=0
      case "$curl_status" in
        7|28|35|52|56) result=transient ;;
        *) result=contract-failure ;;
      esac
    elif [[ "$http" == 200 ]]; then
      if jq -e '.ok == true' "$body" >/dev/null 2>&1; then
        consecutive=$((consecutive + 1))
        if (( consecutive >= 2 )); then result=ready; else result=success-awaiting-confirmation; fi
      else
        result=malformed-response
      fi
    elif [[ "$http" == 502 || "$http" == 503 || "$http" == 504 ]]; then
      consecutive=0
      result=transient
    else
      consecutive=0
      result=contract-failure
    fi

    now=$(meser_readiness_monotonic_ms)
    elapsed=$((now - start))
    meser_readiness_log "$log_file" "READINESS layer=public phase=$phase attempt=$attempt elapsed_ms=$elapsed curl=$curl_status http=$http consecutive=$consecutive result=$result"
    case "$result" in
      ready) return 0 ;;
      contract-failure|malformed-response) return 1 ;;
    esac
    (( now < deadline )) || continue
    meser_readiness_sleep $((deadline - now))
  done
)
