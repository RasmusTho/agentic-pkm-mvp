from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

import yaml

from app.config.paths import resolve_system_settings_path
from app.services import settings as settings_service
from app.vault.layout import DEFAULT_INBOX_FOLDER, VaultLayout, load_or_create_layout, normalize_md_filename

DEFAULT_VAULT_ROOT = Path("vault")

_BASE_IGNORES = [".obsidian/**", ".trash/**", "System/Metadata/VaultMirror/**"]


@dataclass(frozen=True)
class IngestConfig:
    include_folders: List[str]
    ignore_glob: List[str]


def _normalize_list(raw: object | None) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, Iterable):
        values = [str(item).strip() for item in raw if str(item).strip()]
    else:
        values = [str(raw).strip()] if str(raw).strip() else []
    return [value for value in values if value]


def _normalize_include_folders(raw: object | None) -> List[str]:
    values = _normalize_list(raw)
    if any(value in {".", "./"} for value in values):
        return ["."]
    return values


def _finalize_include_folders(raw: object | None, fallback: List[str]) -> List[str]:
    values = _normalize_include_folders(raw)
    if values:
        return values
    return fallback


def _load_frontmatter(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        return {}
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}
    fm_block = parts[1]
    try:
        data = yaml.safe_load(fm_block) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _override_path(vault_root: Path, system_folder: str) -> Path:
    filename = normalize_md_filename("ingest.override.md")
    return vault_root / system_folder / "settings" / filename


def _resolve_override(vault_root: Path, system_folder: str) -> dict:
    override_path = _override_path(vault_root, system_folder)
    if not override_path.exists():
        return {}
    try:
        return _load_frontmatter(override_path)
    except OSError:
        return {}


def _append_universal_ignores(ignore_glob: List[str]) -> List[str]:
    merged = list(ignore_glob)
    safe_ignores = list(_BASE_IGNORES)
    for pattern in safe_ignores:
        if pattern not in merged:
            merged.append(pattern)
    return merged


def _fallback_include_folders(layout: VaultLayout) -> List[str]:
    values = [layout.inbox_folder, layout.desk_folder]
    values = [value for value in values if value]
    return values if values else [DEFAULT_INBOX_FOLDER]


def resolve_ingest_config(vault_root: Path) -> IngestConfig:
    include_folders = None
    ignore_glob = None
    settings_path = resolve_system_settings_path(vault_root=vault_root)
    if settings_path and settings_path.exists():
        try:
            settings = settings_service.load_settings(force=True, path=settings_path)
        except Exception:
            settings = None
        if settings:
            ingest = settings.get("ingest") or {}
            include_folders = ingest.get("include_folders")
            ignore_glob = ingest.get("ignore_glob")

    layout = load_or_create_layout(vault_root)
    override = _resolve_override(vault_root, layout.system_folder)
    override_include = override.get("include_folders")
    override_ignore = override.get("ignore_glob")

    fallback_include = _fallback_include_folders(layout)

    if override_include is not None:
        include = _finalize_include_folders(override_include, [DEFAULT_INBOX_FOLDER])
    elif layout.include_folders is not None:
        include = _finalize_include_folders(layout.include_folders, [DEFAULT_INBOX_FOLDER])
    elif include_folders is None or not _normalize_list(include_folders):
        include = _finalize_include_folders(fallback_include, [DEFAULT_INBOX_FOLDER])
    else:
        include = _finalize_include_folders(include_folders, [DEFAULT_INBOX_FOLDER])

    if override_ignore is not None:
        ignore = _normalize_list(override_ignore)
    elif ignore_glob is None:
        ignore = _normalize_list(layout.ignore_glob)
    else:
        ignore = _normalize_list(ignore_glob)

    ignore = _append_universal_ignores(ignore)

    return IngestConfig(include_folders=include, ignore_glob=ignore)


__all__ = ["DEFAULT_VAULT_ROOT", "IngestConfig", "resolve_ingest_config"]
