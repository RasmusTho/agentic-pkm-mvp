from __future__ import annotations

from pathlib import Path

from app.knowledge.contracts import WriteReceipt
from app.knowledge.locators import make_note_locator, make_note_locator_from_absolute
from app.knowledge.service import resolve_knowledge_port


def default_vault_root_for_path(path: Path | str) -> Path:
    resolved = Path(path).expanduser().resolve()
    return Path(resolved.anchor) if resolved.anchor else Path("/")


def write_note_from_absolute(
    path: Path | str,
    content: str,
    *,
    vault_root: Path | str | None = None,
) -> WriteReceipt:
    resolved_path = Path(path).expanduser().resolve()
    resolved_root = (
        Path(vault_root).expanduser().resolve()
        if vault_root is not None
        else default_vault_root_for_path(resolved_path)
    )
    locator = make_note_locator_from_absolute(resolved_path, vault_root=resolved_root)
    port = resolve_knowledge_port(vault_root=resolved_root)
    return port.write_note(locator, content)


def write_note_relative(
    note_rel_path: str,
    content: str,
    *,
    vault_root: Path | str,
) -> WriteReceipt:
    resolved_root = Path(vault_root).expanduser().resolve()
    locator = make_note_locator(note_rel_path)
    port = resolve_knowledge_port(vault_root=resolved_root)
    return port.write_note(locator, content)


def append_note_relative(
    note_rel_path: str,
    content: str,
    *,
    vault_root: Path | str,
) -> WriteReceipt:
    resolved_root = Path(vault_root).expanduser().resolve()
    locator = make_note_locator(note_rel_path)
    port = resolve_knowledge_port(vault_root=resolved_root)
    return port.append_note(locator, content)


__all__ = [
    "append_note_relative",
    "default_vault_root_for_path",
    "write_note_from_absolute",
    "write_note_relative",
]
