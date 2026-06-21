from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from app.config.paths import resolve_optional_vault_root
from app.knowledge.write_ops import advanced_uri_from_vault_path, append_note_relative
from app.vault.paths import get_vault_inbox_dir_rel

logger = logging.getLogger(__name__)


def append_change(
    message: str,
    note_rel_path: str | None = None,
    *,
    vault_root: Path | str | None = None,
    vault_path: Path | str | None = None,
    uri: str | None = None,
) -> None:
    root = _resolve_vault_root(vault_root)
    if root is None:
        logger.debug("append_change skipped: no vault selected message=%s", message)
        return
    rel = note_rel_path or os.getenv("VAULT_CHANGE_LOG_NOTE_REL")
    if not rel:
        rel = _default_change_log_rel(root)
    _append_line(rel, message, vault_root=root, vault_path=vault_path, uri=uri)


def append_conflict(
    message: str,
    note_rel_path: str | None = None,
    *,
    vault_root: Path | str | None = None,
    vault_path: Path | str | None = None,
    uri: str | None = None,
) -> None:
    root = _resolve_vault_root(vault_root)
    if root is None:
        logger.debug("append_conflict skipped: no vault selected message=%s", message)
        return
    rel = note_rel_path or os.getenv("VAULT_CONFLICT_LOG_NOTE_REL")
    if not rel:
        rel = _default_conflict_log_rel(root)
    _append_line(rel, message, vault_root=root, vault_path=vault_path, uri=uri)


def _resolve_vault_root(vault_root: Path | str | None) -> Path | None:
    """Resolve the vault root for inbox appenders, or ``None`` when no vault is selected.

    An explicit ``vault_root`` always wins. Otherwise resolution defers to
    :func:`app.config.paths.resolve_optional_vault_root`, which returns ``None``
    when ``VAULT_ROOT`` is unset (no selected vault) and still raises
    :class:`VaultRootMisconfiguredError` for a set-but-missing root. The legacy
    silent ``Path("vault")`` CWD fallback is gone (#2384); callers skip rather
    than write under the current working directory.
    """
    if vault_root is not None:
        return Path(vault_root).expanduser()
    return resolve_optional_vault_root()


def _default_change_log_rel(vault_root: Path) -> str:
    inbox_rel = get_vault_inbox_dir_rel(vault_root)
    return str(Path(inbox_rel) / "_system_changes.md")


def _default_conflict_log_rel(vault_root: Path) -> str:
    inbox_rel = get_vault_inbox_dir_rel(vault_root)
    return str(Path(inbox_rel) / "_conflicts.md")


def _append_line(
    note_rel_path: str,
    message: str,
    *,
    vault_root: Path,
    vault_path: Path | str | None = None,
    uri: str | None = None,
) -> None:
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    action_link = uri or _build_uri(vault_path)
    suffix = f" | {action_link}" if action_link else ""
    line = f"- [{timestamp}] {message}{suffix}\n"

    append_note_relative(note_rel_path, line, vault_root=vault_root)


def _build_uri(vault_path: Path | str | None) -> str | None:
    if not vault_path:
        return None
    return advanced_uri_from_vault_path(vault_path, vault_root=Path(os.getenv("VAULT_DIR", "vault")))
