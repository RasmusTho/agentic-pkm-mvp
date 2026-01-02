#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import yaml

_DEFAULT_INBOX_DIR = "Inbox"
_DEFAULT_RUNTIME_DIR = "System/Runtime"
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
    raw = settings.get("paths")
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(value, str) and value:
            out[key] = value
    return out


def _paths_data(vault_root: Path | None = None) -> Dict[str, str]:
    root = _resolve_vault_root(vault_root)
    settings = _read_system_settings(root / _SETTINGS_REL_PATH)
    return _extract_paths(settings)


def get_vault_inbox_dir_rel(vault_root: Path | None = None) -> str:
    env_value = os.getenv("VAULT_INBOX_DIR_REL")
    if env_value:
        return env_value
    paths = _paths_data(vault_root)
    return paths.get("inbox_dir_rel", _DEFAULT_INBOX_DIR)


def get_vault_runtime_dir_rel(vault_root: Path | None = None) -> str:
    env_value = os.getenv("VAULT_RUNTIME_DIR_REL")
    if env_value:
        return env_value
    paths = _paths_data(vault_root)
    return paths.get("runtime_dir_rel", _DEFAULT_RUNTIME_DIR)


def ensure_vault_path_env_defaults(vault_root: Path | None = None) -> None:
    os.environ.setdefault("VAULT_INBOX_DIR_REL", get_vault_inbox_dir_rel(vault_root))
    os.environ.setdefault("VAULT_RUNTIME_DIR_REL", get_vault_runtime_dir_rel(vault_root))


__all__ = [
    "get_vault_inbox_dir_rel",
    "get_vault_runtime_dir_rel",
    "ensure_vault_path_env_defaults",
]
