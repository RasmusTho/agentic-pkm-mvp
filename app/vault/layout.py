from __future__ import annotations

from pathlib import Path
from typing import Any
import shutil

import yaml
from pydantic import BaseModel, Field


LAYOUT_NOTE_NAME = ".yggdrasil.md"


class VaultLayout(BaseModel):
    version: str = "1"
    inbox_folder: str = "@Inbox"
    desk_folder: str = "@Desk"
    system_folder: str = "~system"
    ensure_folders: list[str] = Field(default_factory=list)
    ingest_include_folders: list[str] = Field(default_factory=list)
    ingest_ignore_glob: list[str] = Field(default_factory=list)


def _normalize_md_name(name: str) -> str:
    return name if name.lower().endswith(".md") else f"{name}.md"


def _layout_note_path(vault_root: Path) -> Path:
    return vault_root / LAYOUT_NOTE_NAME


def _load_frontmatter(path: Path) -> dict[str, Any]:
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


def _render_default_note(layout: VaultLayout) -> str:
    frontmatter = yaml.safe_dump(
        {
            "version": layout.version,
            "inbox_folder": layout.inbox_folder,
            "desk_folder": layout.desk_folder,
            "system_folder": layout.system_folder,
            "ensure_folders": layout.ensure_folders,
            "ingest_include_folders": layout.ingest_include_folders,
            "ingest_ignore_glob": layout.ingest_ignore_glob,
        },
        sort_keys=False,
    ).strip()
    body = (
        "# Vault Layout Contract\n"
        "This note defines the vault layout contract for ingest and watcher defaults.\n\n"
        "- Edit the YAML frontmatter to change folder names or ingest defaults.\n"
        "- Folders listed here are created if missing; nothing is deleted.\n"
    )
    return f"---\n{frontmatter}\n---\n\n{body}"


def _copy_layout(layout: VaultLayout, update: dict) -> VaultLayout:
    if hasattr(layout, "model_copy"):
        return layout.model_copy(update=update)
    return layout.copy(update=update)


def _build_layout(frontmatter: dict[str, Any]) -> VaultLayout:
    layout = VaultLayout(**frontmatter)
    if not layout.ingest_include_folders:
        layout = _copy_layout(
            layout,
            {"ingest_include_folders": [layout.inbox_folder, layout.desk_folder]},
        )
    return layout


def load_vault_layout(vault_root: Path) -> VaultLayout:
    note_path = _layout_note_path(vault_root)
    if note_path.exists():
        frontmatter = _load_frontmatter(note_path)
    else:
        frontmatter = {}
    return _build_layout(frontmatter)


def ensure_vault_layout(vault_root: Path) -> VaultLayout:
    note_path = _layout_note_path(vault_root)
    layout = load_vault_layout(vault_root)
    if not note_path.exists():
        note_path.write_text(_render_default_note(layout), encoding="utf-8")

    legacy_system = vault_root / "System"
    target_system = vault_root / layout.system_folder
    mirror_root = legacy_system / "Metadata" / "VaultMirror"
    if legacy_system.exists() and not target_system.exists() and not mirror_root.exists():
        shutil.move(str(legacy_system), str(target_system))

    folders = {layout.inbox_folder, layout.desk_folder, layout.system_folder}
    folders.update(layout.ensure_folders)
    for folder in sorted(folders):
        if not folder:
            continue
        (vault_root / folder).mkdir(parents=True, exist_ok=True)

    return layout


__all__ = ["VaultLayout", "ensure_vault_layout", "load_vault_layout", "_normalize_md_name"]
