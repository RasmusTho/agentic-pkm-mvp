from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class NoteRead:
    path: Path
    frontmatter: dict[str, Any]
    body: str
    mtime_ns: int


@dataclass(frozen=True)
class EnsureUuidResult:
    deferred: bool
    wrote: bool
    uuid_value: str | None
    reason: str | None = None


class VaultPort(Protocol):
    """Vault lifecycle boundary for legacy watcher note handling."""

    def read_note(self, path: Path) -> NoteRead: ...

    def ensure_uuid(
        self,
        note: NoteRead,
        *,
        expected_mtime_ns: int | None = None,
    ) -> EnsureUuidResult: ...

    def write_frontmatter(
        self,
        path: Path,
        frontmatter: dict[str, Any],
        body: str,
        *,
        expected_mtime_ns: int | None = None,
    ) -> bool: ...

    def rename_note(self, uuid_value: str, new_path: Path) -> None: ...

    def delete_note(self, path: Path, *, uuid_value: str | None = None) -> None: ...

    def upsert_note_object(
        self,
        path: Path,
        frontmatter: dict[str, Any],
        body: str,
        fm_changed: bool,
        body_changed: bool,
    ) -> None: ...

    def append_inbox_item(self, message: str, *, vault_path: Path | None = None, uri: str | None = None) -> None: ...


class DummyVaultPort:
    """Test double + no-op fallback when no DB is configured."""

    def __init__(self) -> None:
        self.upserts: list[tuple[str, dict[str, Any], str, bool, bool]] = []
        self.renames: list[tuple[str, str]] = []
        self.deletes: list[tuple[str, str | None]] = []
        self.messages: list[tuple[str, str | None]] = []

    def read_note(self, path: Path) -> NoteRead:
        text = path.read_text(encoding="utf-8")
        import yaml

        if text.startswith("---"):
            _, fm_block, remainder = text.split("---", 2)
            loaded = yaml.safe_load(fm_block) or {}
            frontmatter = loaded if isinstance(loaded, dict) else {}
            body = remainder.lstrip("\n")
        else:
            frontmatter = {}
            body = text
        return NoteRead(path=path, frontmatter=frontmatter, body=body, mtime_ns=path.stat().st_mtime_ns)

    def ensure_uuid(
        self,
        note: NoteRead,
        *,
        expected_mtime_ns: int | None = None,
    ) -> EnsureUuidResult:
        if note.frontmatter.get("uuid"):
            return EnsureUuidResult(deferred=False, wrote=False, uuid_value=str(note.frontmatter["uuid"]))
        import uuid

        note.frontmatter["uuid"] = uuid.uuid4().hex
        return EnsureUuidResult(deferred=False, wrote=True, uuid_value=str(note.frontmatter["uuid"]))

    def write_frontmatter(
        self,
        path: Path,
        frontmatter: dict[str, Any],
        body: str,
        *,
        expected_mtime_ns: int | None = None,
    ) -> bool:
        return True

    def rename_note(self, uuid_value: str, new_path: Path) -> None:
        self.renames.append((uuid_value, str(new_path)))

    def delete_note(self, path: Path, *, uuid_value: str | None = None) -> None:
        self.deletes.append((str(path), uuid_value))

    def upsert_note_object(
        self,
        path: Path,
        frontmatter: dict[str, Any],
        body: str,
        fm_changed: bool,
        body_changed: bool,
    ) -> None:
        self.upserts.append((str(path), frontmatter, body, fm_changed, body_changed))

    def append_inbox_item(self, message: str, *, vault_path: Path | None = None, uri: str | None = None) -> None:
        self.messages.append((message, uri))


__all__ = ["DummyVaultPort", "EnsureUuidResult", "NoteRead", "VaultPort"]
