from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class ResolvedPaths:
    vault_root: Path
    yggdrasil_root: Optional[Path]
    system_settings_path: Optional[Path]


_DEFAULT_VAULT = Path("vault")


def _clean_path(value: str | Path | None) -> Optional[Path]:
    if value is None:
        return None
    if isinstance(value, Path):
        return value
    value = value.strip()
    return Path(value) if value else None


def resolve_vault_root(cli_override: Path | None = None) -> Path:
    if cli_override is not None:
        return Path(cli_override)
    env_root = _clean_path(os.getenv("VAULT_ROOT"))
    if env_root is not None:
        return env_root
    return _DEFAULT_VAULT


def resolve_yggdrasil_root() -> Optional[Path]:
    env_root = _clean_path(os.getenv("YGGDRASIL_ROOT"))
    if env_root:
        return env_root
    home_default = Path.home() / "Yggdrasil"
    return home_default if home_default.exists() else None


def _candidate_settings_paths(vault_root: Path | None, yggdrasil_root: Path | None) -> list[Path]:
    candidates: list[Path] = []
    if vault_root is not None:
        candidates.append(vault_root / "_system" / "settings" / "system-settings.yaml")
        candidates.append(vault_root / "@Settings" / "system-settings.yaml")
    if yggdrasil_root is not None:
        mimer_root = yggdrasil_root / "Mimer"
        candidates.append(mimer_root / "@Settings" / "system-settings.yaml")
    return candidates


def resolve_system_settings_path(
    *,
    explicit: Path | None = None,
    vault_root: Path | None = None,
    yggdrasil_root: Path | None = None,
) -> Optional[Path]:
    if explicit is not None:
        return Path(explicit)
    env_override = _clean_path(os.getenv("SETTINGS_PATH"))
    if env_override is not None:
        return env_override

    vault = resolve_vault_root(vault_root)
    ygg = yggdrasil_root or resolve_yggdrasil_root()

    for candidate in _candidate_settings_paths(vault, ygg):
        if candidate.exists():
            return candidate

    return vault / "_system" / "settings" / "system-settings.yaml"


def resolve_flow_settings_path(path: Path | None = None, vault_root: Path | None = None) -> Optional[Path]:
    if path is not None:
        return Path(path)
    env_path = _clean_path(os.getenv("FLOW_SETTINGS_PATH"))
    if env_path is not None:
        return env_path
    vault = resolve_vault_root(vault_root)
    default_path = vault / "_system" / "settings" / "flows.settings.yaml"
    if default_path.exists():
        return default_path
    fallback = Path("docs/settings/flows.settings.yaml")
    if fallback.exists():
        return fallback
    return default_path


def resolve_paths(
    *,
    vault_root: Path | None = None,
    settings_path: Path | None = None,
    yggdrasil_root: Path | None = None,
) -> ResolvedPaths:
    vault = resolve_vault_root(vault_root)
    ygg = yggdrasil_root or resolve_yggdrasil_root()
    system_settings = resolve_system_settings_path(explicit=settings_path, vault_root=vault, yggdrasil_root=ygg)
    return ResolvedPaths(vault_root=vault, yggdrasil_root=ygg, system_settings_path=system_settings)


__all__ = [
    "ResolvedPaths",
    "resolve_vault_root",
    "resolve_yggdrasil_root",
    "resolve_system_settings_path",
    "resolve_flow_settings_path",
    "resolve_paths",
]
