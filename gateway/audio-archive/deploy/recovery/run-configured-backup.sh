#!/usr/bin/env bash
set -Eeuo pipefail
: "${MESER_RELEASE_DIR:?}"
: "${MESER_SECRET_DIR:?}"
: "${MESER_BACKUP_DESTINATION:?}"
: "${MESER_AGE_RECIPIENT:?}"
: "${MESER_BACKUP_MOUNT_ID:?}"
: "${MESER_FAILURE_DOMAIN_NOTE:?}"
if [[ "${MESER_RECOVERY_SYNTHETIC_TEST:-false}" == true ]]; then
  : "${MESER_RUNTIME_ENV:?}"
else
  MESER_RUNTIME_ENV=${MESER_RUNTIME_ENV:-/etc/meser-audio-archive/runtime.env}
  [[ "$MESER_RUNTIME_ENV" == /etc/meser-audio-archive/runtime.env ]] || { printf 'CONFIGURED BACKUP REFUSED: production runtime must be the installed canonical runtime.env\n' >&2; exit 1; }
fi
runtime_schema="$(dirname "$0")/runtime-env.sh"
[[ -f "$runtime_schema" && ! -L "$runtime_schema" ]] || { printf 'CONFIGURED BACKUP REFUSED: canonical runtime schema is missing or unsafe\n' >&2; exit 1; }
# shellcheck source=runtime-env.sh
source "$runtime_schema"
meser_validate_runtime_env_shape "$MESER_RUNTIME_ENV" || { printf 'CONFIGURED BACKUP REFUSED: runtime environment is not the canonical 11-key schema\n' >&2; exit 1; }
"$(dirname "$0")/create-recovery-bundle.sh" "$MESER_RELEASE_DIR" "$MESER_SECRET_DIR" "$MESER_RUNTIME_ENV" "$MESER_BACKUP_DESTINATION" "$MESER_AGE_RECIPIENT" "$MESER_BACKUP_MOUNT_ID" "$MESER_FAILURE_DOMAIN_NOTE"
