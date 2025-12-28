from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

import yaml

from app.config.paths import resolve_system_settings_path
from app.services import settings as settings_service
from app.vault.layout import _normalize_md_name, load_vault_layout

DEFAULT_VAULT_ROOT = Path("vault")

_BASE_IGNORES = [".obsidian/**", ".trash/**", "_system/**", ".yggdrasil.md"]


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
    return values if values else ["."]


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


def _override_path(vault_root: Path) -> Path:
    filename = _normalize_md_name("ingest.override.md")
    return vault_root / "_system" / "settings" / filename


def _resolve_override(vault_root: Path) -> dict:
    override_path = _override_path(vault_root)
    if not override_path.exists():
        return {}
    try:
        return _load_frontmatter(override_path)
    except OSError:
        return {}


def _append_universal_ignores(ignore_glob: List[str], system_folder: str) -> List[str]:
    merged = list(ignore_glob)
    for pattern in _BASE_IGNORES + [f"{system_folder}/**"]:
        if pattern not in merged:
            merged.append(pattern)
    return merged


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

    layout = load_vault_layout(vault_root)
    override = _resolve_override(vault_root)
    override_include = override.get("ingest_include_folders")
    override_ignore = override.get("ingest_ignore_glob")

    if override_include is not None:
        include = _normalize_include_folders(override_include)
    elif include_folders is None or not _normalize_list(include_folders):
        include = _normalize_include_folders(layout.ingest_include_folders)
    else:
        include = _normalize_include_folders(include_folders)

    if override_ignore is not None:
        ignore = _normalize_list(override_ignore)
    elif ignore_glob is None:
        ignore = _normalize_list(layout.ingest_ignore_glob)
    else:
        ignore = _normalize_list(ignore_glob)

    ignore = _append_universal_ignores(ignore, layout.system_folder)

    return IngestConfig(include_folders=include, ignore_glob=ignore)


__all__ = ["DEFAULT_VAULT_ROOT", "IngestConfig", "resolve_ingest_config"]
