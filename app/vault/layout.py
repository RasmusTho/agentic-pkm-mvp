from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
import shutil

import yaml

DEFAULT_SYSTEM_FOLDER = "~system"
DEFAULT_INBOX_FOLDER = "@Inbox"
DEFAULT_DESK_FOLDER = "@Desk"
LAYOUT_NOTE_NAME = "vault.layout.md"


@dataclass(frozen=True)
class VaultLayout:
    system_folder: str
    inbox_folder: str
    desk_folder: str
    include_folders: list[str] | None
    ignore_glob: list[str] | None
    note_path: Path
    version: str = "1"


def normalize_md_filename(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        return "note.md"
    while cleaned.lower().endswith(".md.md"):
        cleaned = cleaned[:-3]
    if not cleaned.lower().endswith(".md"):
        cleaned = f"{cleaned}.md"
    return cleaned


def _layout_note_path(vault_root: Path, system_folder: str) -> Path:
    filename = normalize_md_filename(LAYOUT_NOTE_NAME)
    return vault_root / system_folder / filename


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


def _normalize_optional_list(value: object | None) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, Iterable):
        values = [str(item).strip() for item in value if str(item).strip()]
    else:
        values = [str(value).strip()] if str(value).strip() else []
    values = [item for item in values if item]
    return values or None


def _render_default_note(layout: VaultLayout) -> str:
    frontmatter = yaml.safe_dump(
        {
            "version": layout.version,
            "system_folder": layout.system_folder,
            "inbox_folder": layout.inbox_folder,
            "desk_folder": layout.desk_folder,
            "include_folders": layout.include_folders or [],
            "ignore_glob": layout.ignore_glob or [],
        },
        sort_keys=False,
    ).strip()
    body = (
        "# Vault Layout Contract\n"
        "This note defines the vault layout contract for agents and ingest defaults.\n\n"
        "## Description\n"
        "- Edit the YAML frontmatter to change folder names or ingest defaults.\n"
        "- Folders listed here are created if missing; nothing is deleted.\n"
        "- Unknown folders are allowed to remain.\n\n"
        "## Guidance for agents\n"
        "- System notes live under the system folder.\n"
        "- Inbox is the capture surface for new notes.\n"
        "- Desk is the active workspace.\n"
    )
    return f"---\n{frontmatter}\n---\n\n{body}"


def load_or_create_layout(vault_root: Path) -> VaultLayout:
    note_path = _layout_note_path(vault_root, DEFAULT_SYSTEM_FOLDER)
    if note_path.exists():
        frontmatter = _load_frontmatter(note_path)
    else:
        frontmatter = {}

    system_folder = str(frontmatter.get("system_folder") or DEFAULT_SYSTEM_FOLDER)
    inbox_folder = str(frontmatter.get("inbox_folder") or DEFAULT_INBOX_FOLDER)
    desk_folder = str(frontmatter.get("desk_folder") or DEFAULT_DESK_FOLDER)
    include_folders = _normalize_optional_list(frontmatter.get("include_folders"))
    ignore_glob = _normalize_optional_list(frontmatter.get("ignore_glob"))
    version = str(frontmatter.get("version") or "1")

    layout = VaultLayout(
        system_folder=system_folder,
        inbox_folder=inbox_folder,
        desk_folder=desk_folder,
        include_folders=include_folders,
        ignore_glob=ignore_glob,
        note_path=note_path,
        version=version,
    )

    if not note_path.exists():
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(_render_default_note(layout), encoding="utf-8")

    return layout


def ensure_vault_layout_report(vault_root: Path) -> tuple[VaultLayout, bool, list[str]]:
    layout = load_or_create_layout(vault_root)
    warnings: list[str] = []
    migrated = False

    legacy_system = vault_root / "System"
    target_system = vault_root / layout.system_folder
    if legacy_system.exists() and not target_system.exists():
        if legacy_system.is_dir():
            shutil.move(str(legacy_system), str(target_system))
            migrated = True
        else:
            warnings.append("Legacy System path exists but is not a directory; leaving in place.")
    elif legacy_system.exists() and target_system.exists():
        warnings.append(
            f"Legacy System/ exists alongside {layout.system_folder}/; leaving legacy in place."
        )

    folders = {layout.system_folder, layout.inbox_folder, layout.desk_folder}
    if layout.include_folders:
        folders.update(layout.include_folders)
    for folder in sorted(folders):
        if not folder or folder == ".":
            continue
        (vault_root / folder).mkdir(parents=True, exist_ok=True)

    return layout, migrated, warnings


def ensure_vault_layout(vault_root: Path) -> VaultLayout:
    layout, _, _ = ensure_vault_layout_report(vault_root)
    return layout


__all__ = [
    "VaultLayout",
    "ensure_vault_layout",
    "ensure_vault_layout_report",
    "load_or_create_layout",
    "normalize_md_filename",
]
