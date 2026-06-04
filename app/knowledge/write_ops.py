from __future__ import annotations

from pathlib import Path

from app.knowledge.contracts import WriteReceipt
from app.knowledge.locators import make_note_locator, make_note_locator_from_absolute
from app.knowledge.references import build_obsidian_advanced_uri
from app.knowledge.settings import KnowledgeAdapter, KnowledgeSettings
from app.knowledge.service import resolve_knowledge_port


def default_vault_root_for_path(path: Path | str) -> Path:
    resolved = Path(path).expanduser().resolve()
    return Path(resolved.anchor) if resolved.anchor else Path("/")


def _local_fs_settings() -> KnowledgeSettings:
    return KnowledgeSettings(
        primary_adapter=KnowledgeAdapter.FS_VAULT,
        fallback_adapter=KnowledgeAdapter.OBSIDIAN_CLI,
        allow_fallback=False,
        strict_startup=False,
    )


def write_note_from_absolute(
    path: Path | str,
    content: str,
    *,
    vault_root: Path | str,
) -> WriteReceipt:
    resolved_path = Path(path).expanduser().resolve()
    resolved_root = Path(vault_root).expanduser().resolve()
    resolved_path.relative_to(resolved_root)
    locator = make_note_locator_from_absolute(resolved_path, vault_root=resolved_root)
    # Absolute path writes target the local filesystem boundary directly.
    port = resolve_knowledge_port(vault_root=resolved_root, settings=_local_fs_settings())
    return port.write_note(locator, content)


def write_note_relative(
    note_rel_path: str,
    content: str,
    *,
    vault_root: Path | str,
) -> WriteReceipt:
    resolved_root = Path(vault_root).expanduser().resolve()
    locator = make_note_locator(note_rel_path)
    port = resolve_knowledge_port(vault_root=resolved_root, settings=_local_fs_settings())
    return port.write_note(locator, content)


def append_note_relative(
    note_rel_path: str,
    content: str,
    *,
    vault_root: Path | str,
) -> WriteReceipt:
    resolved_root = Path(vault_root).expanduser().resolve()
    locator = make_note_locator(note_rel_path)
    port = resolve_knowledge_port(vault_root=resolved_root, settings=_local_fs_settings())
    return port.append_note(locator, content)


def advanced_uri_from_vault_path(path: Path | str, *, vault_root: Path | str) -> str:
    resolved_path = Path(path).expanduser().resolve()
    resolved_root = Path(vault_root).expanduser().resolve()
    try:
        rel = resolved_path.relative_to(resolved_root).as_posix()
    except ValueError:
        rel = resolved_path.name
    return build_obsidian_advanced_uri(make_note_locator(rel))


__all__ = [
    "advanced_uri_from_vault_path",
    "append_note_relative",
    "default_vault_root_for_path",
    "write_note_from_absolute",
    "write_note_relative",
]
