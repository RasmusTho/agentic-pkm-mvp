#!/usr/bin/env bash
# Single-sourced Signboard projection-root resolution for host launchers (#4198).
#
# The default board root is defined exactly once, in
# app/dispatcher/signboard.py (DEFAULT_SIGNBOARD_SUBPATH / default_signboard_root),
# which nests it under the human's actively-selected vault. Shell launchers must
# never carry their own board-root literal: three independent spellings of the
# same path is how the projection root diverged.
#
# Resolution order:
#   1. an operator-set SIGNBOARD_ROOT (normalized to an absolute host path)
#   2. default_signboard_root() from the active-vault selection
#   3. unset — no vault is selected, so there is no board root. Callers must
#      degrade visibly (builderops_startup reports `signboard_root_missing`,
#      and /signboard renders an error state) rather than invent a location.

resolve_signboard_root_env() {
  local resolved=""

  if [ -n "${SIGNBOARD_ROOT:-}" ]; then
    resolved="$(python3 -c 'import os, sys
from pathlib import Path

sys.stdout.write(str(Path(os.environ["SIGNBOARD_ROOT"]).expanduser().resolve()))' 2>/dev/null)" || resolved=""
  else
    resolved="$(python3 -c 'import sys

from app.dispatcher.signboard import NoActiveVaultError, default_signboard_root

try:
    sys.stdout.write(str(default_signboard_root()))
except NoActiveVaultError:
    raise SystemExit(3)' 2>/dev/null)" || resolved=""
  fi

  if [ -n "$resolved" ]; then
    SIGNBOARD_ROOT="$resolved"
    export SIGNBOARD_ROOT
  else
    unset SIGNBOARD_ROOT
  fi
}
