from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from app.components.settings.panel_actions_loader import (
    PanelActionCatalog,
    PanelActionDescriptor,
    DEFAULT_PANEL_ACTIONS_PATH,
    load_panel_action_catalog,
)
from app.settings.panel_actions import resolve_panel_actions_root
from app.settings.source import SettingsSource, build_source


@dataclass(frozen=True)
class PanelActionsSettings:
    catalog: PanelActionCatalog
    paths: tuple[Path, ...]
    sources: tuple[SettingsSource, ...]
    combined_sha: str


def _panel_action_env_paths() -> tuple[Path, ...]:
    overrides: List[Path] = []
    for key in ("PANEL_ACTIONS_PATH", "PANEL_ACTIONS_FILE"):
        value = os.getenv(key)
        if value:
            overrides.append(Path(value).expanduser())
    return tuple(overrides)


def _panel_action_paths() -> tuple[Path, ...]:
    env_paths = _panel_action_env_paths()
    if env_paths:
        return env_paths
    resolved = resolve_panel_actions_root()
    candidates: List[Path] = []
    if resolved is not None:
        if resolved.is_file():
            candidates = [resolved]
        elif resolved.is_dir():
            candidates = sorted(p for p in resolved.glob("*.md") if p.is_file())
    if not candidates and DEFAULT_PANEL_ACTIONS_PATH.exists():
        candidates = [DEFAULT_PANEL_ACTIONS_PATH]
    return tuple(candidates)


def _combined_sha(sources: Iterable[SettingsSource]) -> str:
    digest = hashlib.sha256()
    for src in sorted(sources, key=lambda s: s.path):
        digest.update(src.path.encode())
        digest.update((src.sha256 or "").encode())
    return digest.hexdigest()


def load_panel_actions_settings() -> PanelActionsSettings:
    paths = _panel_action_paths()
    if not paths:
        raise ValueError("panel action catalog is missing; ensure docs/settings/panel-actions.md exists")
    descriptors: List[PanelActionDescriptor] = []
    sources: List[SettingsSource] = []
    for path in paths:
        catalog = load_panel_action_catalog(path)
        descriptors.extend(catalog.actions)
        sources.append(build_source(path))
    catalog = PanelActionCatalog.from_descriptors(descriptors)
    if not catalog.actions:
        raise ValueError("panel action catalog is empty; update the mapping file")
    combined_sha = _combined_sha(sources)
    return PanelActionsSettings(
        catalog=catalog,
        paths=paths,
        sources=tuple(sources),
        combined_sha=combined_sha,
    )


def panel_action_ids(settings: PanelActionsSettings) -> set[str]:
    return settings.catalog.ids()
