#!/usr/bin/env bash
set -euo pipefail

resolve_start_full_system_python_bin() {
  if [ -x ".venv/bin/python" ]; then
    printf '%s\n' ".venv/bin/python"
    return 0
  fi
  if command -v python3.12 >/dev/null 2>&1; then
    command -v python3.12
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi
  return 1
}

if ! command -v python >/dev/null 2>&1; then
  _start_full_system_python_bin="$(resolve_start_full_system_python_bin || true)"
  if [ -n "${_start_full_system_python_bin:-}" ]; then
    python() {
      "${_start_full_system_python_bin}" "$@"
    }
    export -f python
  fi
fi

apply_start_full_system_defaults() {
  if [ -z "${WATCHER_AUTO_EXEC+x}" ]; then
    export WATCHER_AUTO_EXEC=1
  fi
  if [ -z "${STARTUP_ENFORCE_OBSIDIAN+x}" ]; then
    export STARTUP_ENFORCE_OBSIDIAN=0
  fi
}
