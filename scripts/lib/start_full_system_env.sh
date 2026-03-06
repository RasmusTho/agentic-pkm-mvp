#!/usr/bin/env bash
set -euo pipefail

apply_start_full_system_defaults() {
  if [ -z "${WATCHER_AUTO_EXEC+x}" ]; then
    export WATCHER_AUTO_EXEC=1
  fi
  if [ -z "${STARTUP_ENFORCE_OBSIDIAN+x}" ]; then
    export STARTUP_ENFORCE_OBSIDIAN=0
  fi
}
