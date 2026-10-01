from __future__ import annotations

from pathlib import PurePath


def normalize_note_path(path: str | PurePath) -> str:
    """Normalize the separator spelling used by vault-relative note paths."""
    return str(path).strip().replace("\\", "/")


__all__ = ["normalize_note_path"]
