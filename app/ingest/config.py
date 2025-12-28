from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

import yaml

from app.config.paths import resolve_system_settings_path
from app.services import settings as settings_service

DEFAULT_VAULT_ROOT = Path("vault")

_UNIVERSAL_IGNORES = [".obsidian/**", ".trash/**", "_system/**"]


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


def _resolve_override(vault_root: Path) -> dict:
    override_path = vault_root / "_system" / "settings" / "ingest.override.md"
    if not override_path.exists():
        return {}
    try:
        return _load_frontmatter(override_path)
    except OSError:
        return {}


def _append_universal_ignores(ignore_glob: List[str]) -> List[str]:
    merged = list(ignore_glob)
    for pattern in _UNIVERSAL_IGNORES:
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

    override = _resolve_override(vault_root)
    override_include = override.get("ingest_include_folders")
    override_ignore = override.get("ingest_ignore_glob")

    include = _normalize_include_folders(override_include if override_include is not None else include_folders)
    ignore = _normalize_list(override_ignore if override_ignore is not None else ignore_glob)
    ignore = _append_universal_ignores(ignore)

    return IngestConfig(include_folders=include, ignore_glob=ignore)


__all__ = ["DEFAULT_VAULT_ROOT", "IngestConfig", "resolve_ingest_config"]
