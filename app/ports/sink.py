from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from app.ports.vault_port import DummyVaultPort


class Sink(Protocol):
    """Deprecated: use app.ports.vault_port.VaultPort."""

    def update_path(self, uuid_value: str, new_path: str) -> None: ...

    def upsert_object_from_note(
        self, path: str, frontmatter: dict[str, Any], body: str, fm_changed: bool, body_changed: bool
    ) -> None: ...


class DummySink:
    """Deprecated compatibility shim for legacy watcher tests."""

    def __init__(self) -> None:
        self._vault = DummyVaultPort()
        self.updates = self._vault.renames
        self.upserts = self._vault.upserts

    def update_path(self, uuid_value: str, new_path: str) -> None:
        self._vault.rename_note(uuid_value, Path(new_path))

    def upsert_object_from_note(
        self, path: str, frontmatter: dict[str, Any], body: str, fm_changed: bool, body_changed: bool
    ) -> None:
        self._vault.upsert_note_object(Path(path), frontmatter, body, fm_changed, body_changed)


__all__ = ["DummySink", "Sink"]
