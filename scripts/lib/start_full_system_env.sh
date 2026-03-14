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

import yaml

vault_root = Path(sys.argv[1]).expanduser()

preferred_layout_rels = [
    "⚙️ System/vault.layout.md",
    "System/vault.layout.md",
    "_system/vault.layout.md",
    "~system/vault.layout.md",
]
preferred_folders = {
    "VAULT_SYSTEM_DIR_REL": ["⚙️ System", "System", "_system", "~system"],
    "VAULT_INBOX_DIR_REL": ["📥 Inbox", "Inbox", "✉️ Inbox"],
    "VAULT_DESK_DIR_REL": ["🛠️ Workbench", "Workbench", "Desk", "🔍 Focus"],
}


def _parse_frontmatter(path: Path) -> dict[str, object]:
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return {}
    if not raw.startswith("---"):
        return {}
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        data = yaml.safe_load(parts[1]) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _pick_layout_note(root: Path) -> Path | None:
    for rel in preferred_layout_rels:
        candidate = root / rel
        if candidate.exists():
            return candidate
    matches = sorted(p for p in root.glob("*/vault.layout.md") if p.is_file())
    if len(matches) == 1:
        return matches[0]
    return None


def _pick_folder(root: Path, names: list[str]) -> str:
    for name in names:
        if (root / name).is_dir():
            return name
    return ""


layout_path = _pick_layout_note(vault_root)
frontmatter = _parse_frontmatter(layout_path) if layout_path else {}

resolved = {
    "VAULT_SYSTEM_DIR_REL": str(frontmatter.get("system_folder") or "").strip(),
    "VAULT_INBOX_DIR_REL": str(frontmatter.get("inbox_folder") or "").strip(),
    "VAULT_DESK_DIR_REL": str(frontmatter.get("desk_folder") or "").strip(),
}

if not resolved["VAULT_SYSTEM_DIR_REL"] and layout_path is not None:
    resolved["VAULT_SYSTEM_DIR_REL"] = layout_path.parent.name

for key, names in preferred_folders.items():
    if resolved[key]:
        continue
    resolved[key] = _pick_folder(vault_root, names)

for key in ("VAULT_SYSTEM_DIR_REL", "VAULT_INBOX_DIR_REL", "VAULT_DESK_DIR_REL"):
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
