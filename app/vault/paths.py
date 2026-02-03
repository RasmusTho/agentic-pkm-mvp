#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml

_DEFAULT_INBOX_DIR = "Inbox"
_DEFAULT_RUNTIME_DIR = "System/Runtime"
_DEFAULT_SYSTEM_DIR = "System"
_SETTINGS_REL_PATH = Path("_system") / "settings" / "system-settings.yaml"


def _resolve_vault_root(vault_root: Path | None = None) -> Path:
    if vault_root is not None:
        return vault_root.expanduser()
    env_root = os.getenv("VAULT_ROOT")
    if env_root:
        return Path(env_root).expanduser()
    return Path("vault").expanduser()


def _read_system_settings(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _extract_paths(settings: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    raw = settings.get("paths")
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, str) and value:
                out[key] = value
    for key in ("inbox_dir_rel", "runtime_dir_rel", "system_dir_rel"):
        if key in out:
            continue
        value = settings.get(key)
        if isinstance(value, str) and value:
            out[key] = value
    return out


def _paths_data(vault_root: Path | None = None) -> Dict[str, str]:
    root = _resolve_vault_root(vault_root)
    settings = _read_system_settings(root / _SETTINGS_REL_PATH)
    return _extract_paths(settings)


def _layout_frontmatter(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        return {}
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}
    block = parts[1]
    try:
        payload = yaml.safe_load(block) or {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _inbox_dir_from_vault_layout(vault_root: Path) -> str:
    candidates = [
        vault_root / "⚙️ System" / "vault.layout.md",
        vault_root / "System" / "vault.layout.md",
    ]
    for path in candidates:
        if not path.exists():
            continue
        fm = _layout_frontmatter(path)
        value = fm.get("inbox_folder")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def get_vault_inbox_dir_rel(vault_root: Path | None = None) -> str:
    env_value = os.getenv("VAULT_INBOX_DIR_REL")
    if env_value:
        return env_value
    root = _resolve_vault_root(vault_root)
    paths = _paths_data(root)
    if paths.get("inbox_dir_rel"):
        return paths["inbox_dir_rel"]
    layout_inbox = _inbox_dir_from_vault_layout(root)
    if layout_inbox:
        return layout_inbox
    return _DEFAULT_INBOX_DIR


def get_vault_runtime_dir_rel(vault_root: Path | None = None) -> str:
    env_value = os.getenv("VAULT_RUNTIME_DIR_REL")
    if env_value:
        return env_value
    paths = _paths_data(vault_root)
    return paths.get("runtime_dir_rel", _DEFAULT_RUNTIME_DIR)


def get_vault_system_dir_rel(vault_root: Path | None = None) -> str:
    env_value = os.getenv("VAULT_SYSTEM_DIR_REL")
    if env_value:
        return env_value
    paths = _paths_data(vault_root)
    return paths.get("system_dir_rel", _DEFAULT_SYSTEM_DIR)


def ensure_vault_path_env_defaults(vault_root: Path | None = None) -> None:
    os.environ.setdefault("VAULT_INBOX_DIR_REL", get_vault_inbox_dir_rel(vault_root))
    os.environ.setdefault("VAULT_RUNTIME_DIR_REL", get_vault_runtime_dir_rel(vault_root))
    os.environ.setdefault("VAULT_SYSTEM_DIR_REL", get_vault_system_dir_rel(vault_root))


__all__ = [
    "get_vault_inbox_dir_rel",
    "get_vault_runtime_dir_rel",
    "get_vault_system_dir_rel",
    "ensure_vault_path_env_defaults",
]
