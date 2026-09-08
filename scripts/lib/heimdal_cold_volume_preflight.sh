#!/usr/bin/env bash
# Shared, read-only HAR-03 gate for governed production startup and deployment.

heimdal_cold_volume_effective_channel() {
  local channel="${1:-}"
  local project="${2:-}"
  local compose_files="${3:-}"
  local compose_separator="${4-${COMPOSE_PATH_SEPARATOR-:}}"
  local normalized_channel normalized_project entry entry_name remainder compose_prod=0

  normalized_channel="$(printf '%s' "${channel}" | tr '[:upper:]' '[:lower:]' | xargs)"
  normalized_project="$(printf '%s' "${project}" | tr '[:upper:]' '[:lower:]' | xargs)"
  if [ -z "${compose_separator}" ] || [ "${#compose_separator}" -ne 1 ] || [ "${compose_separator}" = $'\n' ]; then
    return 78
  fi
  if [ -z "${compose_files}" ]; then
    if [ "${normalized_channel}" = "prod" ] || [ "${normalized_project}" = "pkm-prod" ]; then
      printf '%s\n' prod
    else
      printf '%s\n' "${normalized_channel}"
    fi
    return 0
  fi
  case "${compose_files}" in
    "${compose_separator}"*|*"${compose_separator}"|*"${compose_separator}${compose_separator}"*)
      return 78
      ;;
  esac
  remainder="${compose_files}"
  while :; do
    case "${remainder}" in
      *"${compose_separator}"*)
        entry="${remainder%%"${compose_separator}"*}"
        remainder="${remainder#*"${compose_separator}"}"
        ;;
      *)
        entry="${remainder}"
        remainder=""
        ;;
    esac
    [ -n "${entry}" ] || return 78
    entry_name="$(basename "${entry}" | tr '[:upper:]' '[:lower:]' | xargs)"
    [ -n "${entry_name}" ] || return 78
    if [ "${entry_name}" = "docker-compose.prod.yml" ]; then
      compose_prod=1
    fi
    [ -n "${remainder}" ] || break
  done
  if [ "${normalized_channel}" = "prod" ] || [ "${normalized_project}" = "pkm-prod" ] || [ "${compose_prod}" = "1" ]; then
    printf '%s\n' prod
  else
    printf '%s\n' "${normalized_channel}"
  fi
}

heimdal_cold_volume_preflight_effective() {
  local root="${1:-$(pwd)}"
  local channel="${2:-${PKM_ENVIRONMENT:-${ENVIRONMENT:-${CHANNEL:-${PKM_CHANNEL:-}}}}}"
  local project="${3:-${COMPOSE_PROJECT_NAME:-}}"
  local compose_files="${4:-${COMPOSE_FILE:-}}"
  local compose_separator="${COMPOSE_PATH_SEPARATOR-:}"

  PKM_EFFECTIVE_CHANNEL="$(
    heimdal_cold_volume_effective_channel \
      "${channel}" "${project}" "${compose_files}" "${compose_separator}"
  )" || return $?
  export PKM_EFFECTIVE_CHANNEL
  heimdal_cold_volume_preflight "${PKM_EFFECTIVE_CHANNEL}" "${root}"
}

heimdal_cold_volume_archive_configured() {
  local root="${1:-$(pwd)}"
  local channel="${2:-prod}"
  local channel_config="${root}/.env.${channel}.local"

  # An ambient declaration is enough to opt into the gate; the Python boundary
  # still requires the matching channel-local declaration before it can pass.
  if [ -n "${HEIMDAL_ARCHIVE_METADATA_FILE:-}" ]; then
    return 0
  fi
  if [ ! -e "${channel_config}" ]; then
    # A broken symlink is a configuration failure, not an absent declaration.
    [ -L "${channel_config}" ] && return 2
    return 1
  fi
  [ -f "${channel_config}" ] && [ -r "${channel_config}" ] || return 2
  local config_status=""
  if ! config_status="$(awk '
    BEGIN { status = 1 }
    {
      line = $0
      sub(/^[[:space:]]+/, "", line)
      sub(/[[:space:]]+$/, "", line)
      if (line == "" || line ~ /^#/) {
        next
      }
      if (line !~ /^(export[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*[[:space:]]*=/) {
        status = 2
        exit
      }
      if (line ~ /^HEIMDAL_ARCHIVE_METADATA_FILE[[:space:]]*=/) {
        status = 0
      }
    }
    END { print status }
  ' "${channel_config}")"; then
    return 2
  fi
  case "${config_status}" in
    0) return 0 ;;
    1) return 1 ;;
    *) return 2 ;;
  esac
}

heimdal_cold_volume_preflight() {
  local channel="${1:-}"
  local root="${2:-$(pwd)}"
  local python_bin="${PYTHON:-python3}"
  local rc=0

  # Dev/test remain resettable and may exercise the same module explicitly
  # without acquiring a host mount. Prod opts into HAR-03 only when the
  # channel declares that the archive capability is configured; the archive
  # boundary itself remains fail-closed once opted in.
  [ "${channel}" = "prod" ] || return 0
  local archive_config_rc=0
  if heimdal_cold_volume_archive_configured "${root}" "${channel}"; then
    :
  else
    archive_config_rc=$?
  fi
  if [ "${archive_config_rc}" -eq 1 ]; then
    echo "archive volume preflight: not configured"
    return 0
  elif [ "${archive_config_rc}" -ne 0 ]; then
    echo "archive volume preflight: configuration check failed" >&2
    return "${archive_config_rc}"
  fi

  (
    cd "${root}" || exit 1
    export PYTHONPATH="${root}${PYTHONPATH:+:${PYTHONPATH}}"
    exec "${python_bin}" -m app.ops.heimdal_cold_volume \
      require-ready --channel "${channel}" --config-root "${root}"
  ) >/dev/null 2>/dev/null || rc=$?
  if [ "${rc}" -ne 0 ]; then
    echo "archive volume preflight failed: output=redacted" >&2
    return "${rc}"
  fi
  echo "archive volume preflight: ready"
}
