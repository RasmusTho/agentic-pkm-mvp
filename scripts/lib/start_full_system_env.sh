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
  if [ -z "${STARTUP_CHECK_OBSIDIAN+x}" ]; then
    export STARTUP_CHECK_OBSIDIAN=1
  fi
  if [ -z "${STARTUP_ENFORCE_OBSIDIAN+x}" ]; then
    export STARTUP_ENFORCE_OBSIDIAN=0
  fi
}

infer_start_full_system_vault_layout_env() {
  local vault_root="${1:-}"
  if [ -z "$vault_root" ] || [ ! -d "$vault_root" ]; then
    return 0
  fi

  python - "$vault_root" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

from app.vault.layout import load_layout
from app.vault.paths import resolve_vault_inbox_dir_rel, resolve_vault_system_dir_rel

vault_root = Path(sys.argv[1]).expanduser()

resolved: dict[str, str] = {}

for key, resolver in (
    ("VAULT_SYSTEM_DIR_REL", resolve_vault_system_dir_rel),
    ("VAULT_INBOX_DIR_REL", resolve_vault_inbox_dir_rel),
):
    try:
        resolved[key] = resolver(vault_root).value
    except Exception:
        resolved[key] = ""

try:
    layout = load_layout(vault_root)
except Exception:
    layout = None
else:
    try:
        resolved["VAULT_LAYOUT_NOTE_REL"] = str(layout.note_path.relative_to(vault_root))
    except Exception:
        pass
    resolved["VAULT_DESK_DIR_REL"] = layout.desk_folder

for key in ("VAULT_LAYOUT_NOTE_REL", "VAULT_SYSTEM_DIR_REL", "VAULT_INBOX_DIR_REL", "VAULT_DESK_DIR_REL"):
    value = resolved.get(key, "")
    if value:
        print(f"{key}={value}")
PY
}


apply_start_full_system_vault_defaults() {
  local vault_root="${1:-}"
  local line key value inferred_env_path
  inferred_env_path="$(mktemp)"
  trap 'rm -f "$inferred_env_path"' RETURN
  infer_start_full_system_vault_layout_env "$vault_root" >"$inferred_env_path"
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    key="${line%%=*}"
    value="${line#*=}"
    [ -n "$key" ] || continue
    if [ -n "${!key+x}" ]; then
      continue
    fi
    export "$key=$value"
  done <"$inferred_env_path"
  trap - RETURN
  rm -f "$inferred_env_path"
}
