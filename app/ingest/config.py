from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from app.config.paths import resolve_system_settings_path
from app.services import settings as settings_service

DEFAULT_VAULT_ROOT = Path("vault")


@dataclass(frozen=True)
class IngestConfig:
    include_folders: List[str]


def _normalize_include_folders(raw: object | None) -> List[str]:
    if raw is None:
        return ["."]
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, Iterable):
        values = [str(item).strip() for item in raw if str(item).strip()]
    else:
        values = [str(raw).strip()] if str(raw).strip() else []
    return values if values else ["."]


def resolve_ingest_config(vault_root: Path) -> IngestConfig:
    include_folders = None
    settings_path = resolve_system_settings_path(vault_root=vault_root)
    if settings_path and settings_path.exists():
        try:
            settings = settings_service.load_settings(force=True, path=settings_path)
        except Exception:
            settings = None
        if settings:
            ingest = settings.get("ingest") or {}
            include_folders = ingest.get("include_folders")
    return IngestConfig(include_folders=_normalize_include_folders(include_folders))


__all__ = ["DEFAULT_VAULT_ROOT", "IngestConfig", "resolve_ingest_config"]
