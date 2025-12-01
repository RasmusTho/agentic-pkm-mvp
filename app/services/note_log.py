from __future__ import annotations

from pathlib import Path


def note_log_path(note_uuid: str, vault_relative_path: Path | str) -> Path:
    """
    Return the canonical per-note log path (`uuid.md`) under the VaultMirror metadata tree,
    preserving the note's vault-relative folder structure for sync/merge.
    TODO: Future mirror writes should materialize system-owned metadata/log entries here
    (frontmatter + agent decisions, not full note bodies). Humans should read but not edit
    these files; automation will append new log entries per ingest/promotion run.
    """
    uuid_str = str(note_uuid).strip()
    rel_path = Path(str(vault_relative_path).lstrip("/"))
    # If a file path is provided, mirror only the directory structure and replace the filename with uuid.md
    if rel_path.suffix:
        rel_path = rel_path.parent
    mirror_root = Path("System/Metadata/VaultMirror")
    return mirror_root / rel_path / f"{uuid_str}.md"


__all__ = ["note_log_path"]
