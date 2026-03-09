from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from app.knowledge.write_ops import advanced_uri_from_vault_path, write_note_from_absolute
from app.ports.vault_port import EnsureUuidResult, NoteRead
from app.services.inbox import append_change
from app.services.vault_sync import active_edit, delete_note, update_path, upsert_object_from_note
from scripts.yaml_roundtrip import dump_frontmatter, load_frontmatter


class FilesystemVaultAdapter:
    """Vault adapter used by legacy fs watcher."""

    def __init__(self, *, vault_root: Path | str, backend_writes_enabled: bool = True) -> None:
        self.vault_root = Path(vault_root).expanduser().resolve()
        self.backend_writes_enabled = backend_writes_enabled

    def read_note(self, path: Path) -> NoteRead:
        resolved = Path(path).resolve()
        text = resolved.read_text(encoding="utf-8")
        frontmatter, body = load_frontmatter(text)
        return NoteRead(path=resolved, frontmatter=frontmatter, body=body, mtime_ns=resolved.stat().st_mtime_ns)

    def ensure_uuid(
        self,
        note: NoteRead,
        *,
        expected_mtime_ns: int | None = None,
    ) -> EnsureUuidResult:
        current_uuid = str(note.frontmatter.get("uuid") or "").strip()
        if current_uuid:
            return EnsureUuidResult(deferred=False, wrote=False, uuid_value=current_uuid)
        if active_edit(note.path):
            self.append_inbox_item(
                f"Deferred UUID injection for {note.path.name}",
                vault_path=note.path,
                uri=self._make_uri(note.path),
            )
            return EnsureUuidResult(deferred=True, wrote=False, uuid_value=None, reason="active_edit")
        note.frontmatter["uuid"] = uuid.uuid4().hex
        wrote = self.write_frontmatter(
            note.path,
            note.frontmatter,
            note.body,
            expected_mtime_ns=expected_mtime_ns,
        )
        if not wrote:
            self.append_inbox_item(
                f"Deferred UUID injection for {note.path.name} (concurrent edit detected)",
                vault_path=note.path,
                uri=self._make_uri(note.path),
            )
            return EnsureUuidResult(deferred=True, wrote=False, uuid_value=None, reason="mtime_mismatch")
        self.append_inbox_item(f"Injected UUID in {note.path.name}", vault_path=note.path, uri=self._make_uri(note.path))
        return EnsureUuidResult(deferred=False, wrote=True, uuid_value=str(note.frontmatter["uuid"]))

    def write_frontmatter(
        self,
        path: Path,
        frontmatter: dict[str, Any],
        body: str,
        *,
        expected_mtime_ns: int | None = None,
    ) -> bool:
        resolved = Path(path).resolve()
        if expected_mtime_ns is not None and resolved.exists():
            current_mtime_ns = resolved.stat().st_mtime_ns
            if current_mtime_ns != expected_mtime_ns:
                return False
        rendered = dump_frontmatter(frontmatter, body)
        write_note_from_absolute(resolved, rendered, vault_root=self.vault_root)
        return True

    def rename_note(self, uuid_value: str, new_path: Path) -> None:
        if not self.backend_writes_enabled:
            return
        update_path(uuid_value, str(Path(new_path).resolve()))

    def delete_note(self, path: Path, *, uuid_value: str | None = None) -> None:
        if not self.backend_writes_enabled:
            return
        delete_note(str(Path(path).resolve()), uuid_value=uuid_value)

    def upsert_note_object(
        self,
        path: Path,
        frontmatter: dict[str, Any],
        body: str,
        fm_changed: bool,
        body_changed: bool,
    ) -> None:
        if not self.backend_writes_enabled:
            return
        upsert_object_from_note(str(Path(path).resolve()), frontmatter, body, fm_changed, body_changed)

    def append_inbox_item(self, message: str, *, vault_path: Path | None = None, uri: str | None = None) -> None:
        append_change(message, vault_path=vault_path, uri=uri)

    def _make_uri(self, path: Path) -> str:
        return advanced_uri_from_vault_path(path, vault_root=self.vault_root)


__all__ = ["FilesystemVaultAdapter"]
