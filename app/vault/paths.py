#!/usr/bin/env python3
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import yaml

from app.vault.layout import load_layout


_SETTINGS_REL_PATH = Path("_system") / "settings" / "system-settings.yaml"
_ALT_SETTINGS_REL_PATH = Path("@Settings") / "system-settings.yaml"


@dataclass(frozen=True)
class VaultPathValue:
    value: str
    provenance: str


def _resolve_vault_root(vault_root: Path | None = None) -> Path:
    if vault_root is not None:
        return vault_root.expanduser()
    env_root = os.getenv("VAULT_ROOT")
    if env_root:
        return Path(env_root).expanduser()
    # Keep the historical fallback for non-runtime contexts.
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
            if isinstance(value, str) and value.strip():
                out[key] = value.strip()
    for key in ("inbox_dir_rel", "runtime_dir_rel", "system_dir_rel"):
        if key in out:
            continue
        value = settings.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    return out


def _paths_data(vault_root: Path) -> Dict[str, str]:
    for settings_path in (vault_root / _SETTINGS_REL_PATH, vault_root / _ALT_SETTINGS_REL_PATH):
        settings = _read_system_settings(settings_path)
        if settings:
            return _extract_paths(settings)
    return {}


def resolve_vault_inbox_dir_rel(vault_root: Path) -> VaultPathValue:
    env_value = (os.getenv("VAULT_INBOX_DIR_REL") or "").strip()
    if env_value:
        return VaultPathValue(env_value, "env:VAULT_INBOX_DIR_REL")

    paths = _paths_data(vault_root)
    value = paths.get("inbox_dir_rel", "").strip()
    if value:
        return VaultPathValue(value, "system-settings.yaml:paths.inbox_dir_rel")

    layout = load_layout(vault_root)
    if layout.inbox_folder:
        return VaultPathValue(layout.inbox_folder, f"vault.layout.md:{layout.note_path}")

    raise ValueError(
        "inbox folder could not be resolved. Set VAULT_INBOX_DIR_REL, or ensure vault.layout.md has inbox_folder."
    )


def resolve_vault_system_dir_rel(vault_root: Path) -> VaultPathValue:
    env_value = (os.getenv("VAULT_SYSTEM_DIR_REL") or "").strip()
    if env_value:
        return VaultPathValue(env_value, "env:VAULT_SYSTEM_DIR_REL")

    paths = _paths_data(vault_root)
    value = paths.get("system_dir_rel", "").strip()
    if value:
        return VaultPathValue(value, "system-settings.yaml:paths.system_dir_rel")

    layout = load_layout(vault_root)
    if layout.system_folder:
        return VaultPathValue(layout.system_folder, f"vault.layout.md:{layout.note_path}")

    raise ValueError(
        "System folder could not be resolved. Set VAULT_SYSTEM_DIR_REL, or ensure vault.layout.md has system_folder."
    )


def resolve_vault_runtime_dir_rel(vault_root: Path) -> VaultPathValue:
    env_value = (os.getenv("VAULT_RUNTIME_DIR_REL") or "").strip()
    if env_value:
        return VaultPathValue(env_value, "env:VAULT_RUNTIME_DIR_REL")

    paths = _paths_data(vault_root)
    value = paths.get("runtime_dir_rel", "").strip()
    if value:
        return VaultPathValue(value, "system-settings.yaml:paths.runtime_dir_rel")

    layout = load_layout(vault_root)
    fm: dict[str, Any]
    try:
        raw = layout.note_path.read_text(encoding="utf-8")
    except Exception:
        raw = ""
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
            except Exception:
                fm = {}
            if isinstance(fm, dict):
                value2 = fm.get("runtime_dir_rel")
                if isinstance(value2, str) and value2.strip():
                    return VaultPathValue(value2.strip(), f"vault.layout.md:{layout.note_path}")

    raise ValueError(
        "Runtime folder could not be resolved. Set VAULT_RUNTIME_DIR_REL or configure paths.runtime_dir_rel in system-settings.yaml."
    )


def get_vault_inbox_dir_rel(vault_root: Path | None = None) -> str:
    root = _resolve_vault_root(vault_root)
    return resolve_vault_inbox_dir_rel(root).value


def get_vault_system_dir_rel(vault_root: Path | None = None) -> str:
    root = _resolve_vault_root(vault_root)
    return resolve_vault_system_dir_rel(root).value


def get_vault_runtime_dir_rel(vault_root: Path | None = None) -> str:
    root = _resolve_vault_root(vault_root)
    return resolve_vault_runtime_dir_rel(root).value


__all__ = [
    "VaultPathValue",
    "get_vault_inbox_dir_rel",
    "get_vault_runtime_dir_rel",
    "get_vault_system_dir_rel",
    "resolve_vault_inbox_dir_rel",
    "resolve_vault_runtime_dir_rel",
    "resolve_vault_system_dir_rel",
]
