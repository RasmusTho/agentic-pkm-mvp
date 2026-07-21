#!/usr/bin/env bash

# Resolve the one host-global ownership authority independently of checkout and
# Compose project. Callers export the absolute path before Compose interpolation.
resolve_instance_ownership_host_state_dir() {
  local configured="${INSTANCE_OWNERSHIP_HOST_STATE_DIR:-}"
  if [ -z "${configured}" ]; then
    configured="${XDG_STATE_HOME:-${HOME:?HOME is required}/.local/state}/agentic-pkm/instance-ownership"
  fi
  case "${configured}" in
    /*) ;;
    *)
      echo "INSTANCE_OWNERSHIP_HOST_STATE_DIR must be an absolute host path" >&2
      return 64
      ;;
  esac
  INSTANCE_OWNERSHIP_HOST_STATE_DIR="$(python3 - "${configured}" <<'PY'
import os
import sys

print(os.path.realpath(sys.argv[1]))
PY
)" || return $?
  export INSTANCE_OWNERSHIP_HOST_STATE_DIR
}

prepare_instance_ownership_host_state_dir() {
  resolve_instance_ownership_host_state_dir || return $?
  (umask 077 && mkdir -p -- "${INSTANCE_OWNERSHIP_HOST_STATE_DIR}") || return $?
  chmod 0700 "${INSTANCE_OWNERSHIP_HOST_STATE_DIR}" || return $?
  python3 - "${INSTANCE_OWNERSHIP_HOST_STATE_DIR}" <<'PY'
import os
import stat
import sys

path = sys.argv[1]
metadata = os.lstat(path)
if (
    not stat.S_ISDIR(metadata.st_mode)
    or metadata.st_uid != os.geteuid()
    or stat.S_IMODE(metadata.st_mode) != 0o700
    or os.path.realpath(path) != path
):
    raise SystemExit(
        "host-global ownership state directory must be canonical, private, and caller-owned"
    )
PY
}
