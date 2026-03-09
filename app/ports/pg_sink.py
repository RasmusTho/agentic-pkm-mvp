from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.ports.filesystem_vault_adapter import FilesystemVaultAdapter


class PgSink:
    """Deprecated: legacy alias to FilesystemVaultAdapter watcher lifecycle ops."""

    def __init__(self, *, vault_root: Path | str | None = None) -> None:
        root = Path(vault_root or os.getenv("VAULT_DIR", "vault")).expanduser().resolve()
        self._adapter = FilesystemVaultAdapter(vault_root=root)

    def update_path(self, uuid_value: str, new_path: str) -> None:
        self._adapter.rename_note(uuid_value, Path(new_path))

    def delete_note(self, path: str, *, uuid_value: str | None = None) -> None:
        self._adapter.delete_note(Path(path), uuid_value=uuid_value)

    def upsert_object_from_note(
        self, path: str, frontmatter: dict[str, Any], body: str, fm_changed: bool, body_changed: bool
    ) -> None:
        self._adapter.upsert_note_object(Path(path), frontmatter, body, fm_changed, body_changed)


__all__ = ["PgSink"]
