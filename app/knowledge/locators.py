from __future__ import annotations

import os
from pathlib import Path

from app.knowledge.contracts import NoteLocator
from app.knowledge.vault_identity import resolve_obsidian_vault_name


def normalize_note_path(path: str | Path) -> str:
    return str(path).strip().replace("\\", "/")


def make_note_locator(path: str | Path, *, vault: str | None = None) -> NoteLocator:
    vault_name = (vault or "").strip() or resolve_obsidian_vault_name()
    return NoteLocator(vault=vault_name, path=normalize_note_path(path))


def make_note_locator_from_absolute(path: str | Path, *, vault_root: str | Path, vault: str | None = None) -> NoteLocator:
    resolved_path = Path(os.path.realpath(os.path.expanduser(os.fspath(path))))
    resolved_root = Path(os.path.realpath(os.path.expanduser(os.fspath(vault_root))))
    rel = resolved_path.relative_to(resolved_root).as_posix()
    return make_note_locator(rel, vault=vault)


__all__ = ["make_note_locator", "make_note_locator_from_absolute", "normalize_note_path"]
