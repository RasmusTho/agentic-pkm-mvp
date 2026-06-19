#!/usr/bin/env python3
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import yaml

from app.vault.layout import load_layout
from app.vault.manager import VaultContext
from app.vault.settings_service import SettingsService


_SETTINGS_REL_PATH = Path("_system") / "settings" / "system-settings.yaml"
_ALT_SETTINGS_REL_PATH = Path("@Settings") / "system-settings.yaml"


@dataclass(frozen=True)
class VaultPathValue:
    value: str
    provenance: str


@dataclass(frozen=True)
class ResolvedVaultPaths:
    vault_root: Path
    settings_dir: Path
    handoff_dir: Path
    assets_dir: Path
    templates_dir: Path
    archive_dir: Path
    local_export_path: Path | None


class VaultPathResolutionError(RuntimeError):
    """Raised when vault-scoped paths cannot be resolved from the active context."""


class VaultPathResolver:
    def __init__(self, settings_service: SettingsService | None = None) -> None:
        self.settings_service = settings_service or SettingsService()

    def resolve(self, context: VaultContext) -> ResolvedVaultPaths:
        if context.status != "selected" or not context.active_vault_path or not context.settings_path:
            raise VaultPathResolutionError(
                f"vault path resolution requires a selected initialized vault; current status is {context.status}"
            )

        vault_root = Path(context.active_vault_path).expanduser()
        settings_dir = Path(context.settings_path).expanduser()
        effective = self.settings_service.effective_settings(context)

        return ResolvedVaultPaths(
            vault_root=vault_root,
            settings_dir=settings_dir,
            handoff_dir=_vault_relative_path(vault_root, effective["handoffFolder"]),
            assets_dir=_vault_relative_path(vault_root, effective["assetsFolder"]),
            templates_dir=_vault_relative_path(vault_root, effective["templatesFolder"]),
            archive_dir=_vault_relative_path(vault_root, effective["archiveFolder"]),
            local_export_path=_optional_local_path(vault_root, effective["localExportPath"].value),
        )


def _vault_relative_path(vault_root: Path, setting: Any) -> Path:
    raw = str(setting.value).strip()
    if not raw:
        raise VaultPathResolutionError(f"{setting.key} must not be empty")
    path = Path(raw).expanduser()
    if path.is_absolute():
        raise VaultPathResolutionError(f"{setting.key} must be vault-relative; absolute paths are local-only")
    resolved = (vault_root / path).resolve()
    if not _is_within(resolved, vault_root.resolve()):
        raise VaultPathResolutionError(
            f"{setting.key} resolves outside the selected vault; parent traversal is not allowed"
        )
    return vault_root / path


def _is_within(candidate: Path, root: Path) -> bool:
    """True if ``candidate`` is ``root`` itself or contained within it."""
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _optional_local_path(vault_root: Path, value: object) -> Path | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path
    return vault_root / path


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


def _default_system_dir_rel() -> str:
    """The packaged default system folder name.

    Used as a graceful fallback for runtime paths that must keep working on a
    vault that was created by ``initialize_vault`` before it bootstrapped a
    layout note (only ``settings/*.md`` present, no ``vault.layout.md`` /
    ``system-settings.yaml``). Importing lazily avoids a hard dependency on the
    layout/settings packages at module import time.
    """

    try:
        from app.settings.default_vault_layout import load_default_vault_layout

        payload = load_default_vault_layout()
        layout = payload.get("layout")
        if isinstance(layout, dict):
            value = layout.get("system_folder")
            if isinstance(value, str) and value.strip():
                return value.strip()
        paths = payload.get("paths")
        if isinstance(paths, dict):
            value = paths.get("system_dir_rel")
            if isinstance(value, str) and value.strip():
                return value.strip()
    except Exception:
        pass
    return "_system"


def resolve_vault_system_dir_rel_or_default(vault_root: Path | None = None) -> str:
    """Resolve the vault system dir, degrading to the packaged default.

    The deterministic resolver raises when a vault carries no layout note,
    ``system-settings.yaml``, or env override. The Contextual Relevance Engine
    runs on a default-on background tick that must not raise on a freshly
    ``initialize_vault``-created vault, so it resolves through this helper and
    falls back to the packaged default system folder instead of raising.
    """

    root = _resolve_vault_root(vault_root)
    try:
        return resolve_vault_system_dir_rel(root).value
    except (ValueError, FileNotFoundError):
        return _default_system_dir_rel()


def get_vault_runtime_dir_rel(vault_root: Path | None = None) -> str:
    root = _resolve_vault_root(vault_root)
    return resolve_vault_runtime_dir_rel(root).value


__all__ = [
    "ResolvedVaultPaths",
    "VaultPathResolutionError",
    "VaultPathResolver",
    "VaultPathValue",
    "get_vault_inbox_dir_rel",
    "get_vault_runtime_dir_rel",
    "get_vault_system_dir_rel",
    "resolve_vault_inbox_dir_rel",
    "resolve_vault_runtime_dir_rel",
    "resolve_vault_system_dir_rel",
    "resolve_vault_system_dir_rel_or_default",
]
