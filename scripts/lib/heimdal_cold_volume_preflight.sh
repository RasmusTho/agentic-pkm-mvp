#!/usr/bin/env bash
# Shared, read-only HAR-03 gate for governed production startup and deployment.

heimdal_cold_volume_effective_channel() {
  local channel="${1:-}"
  local project="${2:-}"
  local compose_files="${3:-}"
  local normalized_channel normalized_project entry entry_name

  normalized_channel="$(printf '%s' "${channel}" | tr '[:upper:]' '[:lower:]' | xargs)"
  normalized_project="$(printf '%s' "${project}" | tr '[:upper:]' '[:lower:]' | xargs)"
  if [ "${normalized_channel}" = "prod" ] || [ "${normalized_project}" = "pkm-prod" ]; then
    printf '%s\n' prod
    return 0
  fi
  while IFS= read -r entry; do
    entry_name="$(basename "${entry}" | tr '[:upper:]' '[:lower:]' | xargs)"
    if [ "${entry_name}" = "docker-compose.prod.yml" ]; then
      printf '%s\n' prod
      return 0
    fi
  done <<EOF
$(printf '%s' "${compose_files}" | tr ':' '\n')
EOF
  printf '%s\n' "${normalized_channel}"
}

heimdal_cold_volume_preflight_effective() {
  local root="${1:-$(pwd)}"
  local channel="${2:-${PKM_ENVIRONMENT:-${ENVIRONMENT:-${CHANNEL:-${PKM_CHANNEL:-}}}}}"
  local project="${3:-${COMPOSE_PROJECT_NAME:-}}"
  local compose_files="${4:-${COMPOSE_FILE:-}}"

  PKM_EFFECTIVE_CHANNEL="$(
    heimdal_cold_volume_effective_channel "${channel}" "${project}" "${compose_files}"
  )" || return $?
  export PKM_EFFECTIVE_CHANNEL
  heimdal_cold_volume_preflight "${PKM_EFFECTIVE_CHANNEL}" "${root}"
}

heimdal_cold_volume_preflight() {
  local channel="${1:-}"
  local root="${2:-$(pwd)}"
  local python_bin="${PYTHON:-python3}"
  local rc=0

  # HAR-03 makes this a production invariant. Dev/test remain resettable and
  # may exercise the same module explicitly without acquiring a host mount.
  [ "${channel}" = "prod" ] || return 0

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
