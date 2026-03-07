from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from app.knowledge.locators import make_note_locator
from app.knowledge.references import build_obsidian_advanced_uri
from app.knowledge.service import resolve_knowledge_port
from app.vault.paths import get_vault_inbox_dir_rel


def append_change(
    message: str,
    note_rel_path: str | None = None,
    *,
    vault_root: Path | str | None = None,
    vault_path: Path | str | None = None,
    uri: str | None = None,
) -> None:
    rel = note_rel_path or os.getenv("VAULT_CHANGE_LOG_NOTE_REL")
    if not rel:
        rel = _default_change_log_rel(vault_root)
    _append_line(rel, message, vault_root=vault_root, vault_path=vault_path, uri=uri)


def append_conflict(
    message: str,
    note_rel_path: str | None = None,
    *,
    vault_root: Path | str | None = None,
    vault_path: Path | str | None = None,
    uri: str | None = None,
) -> None:
    rel = note_rel_path or os.getenv("VAULT_CONFLICT_LOG_NOTE_REL")
    if not rel:
        rel = _default_conflict_log_rel(vault_root)
    _append_line(rel, message, vault_root=vault_root, vault_path=vault_path, uri=uri)


def _resolve_vault_root(vault_root: Path | str | None) -> Path:
    if vault_root is None:
        env_root = os.getenv("VAULT_ROOT")
        if env_root:
            return Path(env_root).expanduser()
        return Path("vault").expanduser()
    return Path(vault_root).expanduser()


def _default_change_log_rel(vault_root: Path | str | None) -> str:
    root = _resolve_vault_root(vault_root)
    inbox_rel = get_vault_inbox_dir_rel(root)
    return str(Path(inbox_rel) / "_system_changes.md")


def _default_conflict_log_rel(vault_root: Path | str | None) -> str:
    root = _resolve_vault_root(vault_root)
    inbox_rel = get_vault_inbox_dir_rel(root)
    return str(Path(inbox_rel) / "_conflicts.md")


def _append_line(
    note_rel_path: str,
    message: str,
    *,
    vault_root: Path | str | None = None,
    vault_path: Path | str | None = None,
    uri: str | None = None,
) -> None:
    root = _resolve_vault_root(vault_root)
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    action_link = uri or _build_uri(vault_path)
    suffix = f" | {action_link}" if action_link else ""
    line = f"- [{timestamp}] {message}{suffix}\n"

    locator = make_note_locator(note_rel_path)
    port = resolve_knowledge_port(vault_root=root)
    port.append_note(locator, line)


def _build_uri(vault_path: Path | str | None) -> str | None:
    if not vault_path:
        return None
    path_obj = Path(vault_path)
    try:
        rel = path_obj.relative_to(Path(os.getenv("VAULT_DIR", "vault")))
    except ValueError:
        rel = path_obj.name
    return build_obsidian_advanced_uri(make_note_locator(rel))
