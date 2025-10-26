from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote


def append_change(message: str, inbox: str = "Inbox/System-changes.md", *, vault_path: Path | str | None = None, uri: str | None = None) -> None:
    _append_line(inbox, message, vault_path=vault_path, uri=uri)


def append_conflict(message: str, inbox: str = "Inbox/Conflicts.md", *, vault_path: Path | str | None = None, uri: str | None = None) -> None:
    _append_line(inbox, message, vault_path=vault_path, uri=uri)


def _append_line(path: str, message: str, *, vault_path: Path | str | None = None, uri: str | None = None) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    action_link = uri or _build_uri(vault_path)
    suffix = f" | {action_link}" if action_link else ""
    with target.open("a", encoding="utf-8") as handle:
        handle.write(f"- [{timestamp}] {message}{suffix}\n")


def _build_uri(vault_path: Path | str | None) -> str | None:
    if not vault_path:
        return None
    vault_name = os.getenv("OBSIDIAN_VAULT_NAME", "Vault")
    path_obj = Path(vault_path)
    try:
        rel = path_obj.relative_to(Path(os.getenv("VAULT_DIR", "vault")))
    except ValueError:
        rel = path_obj.name
    return f"obsidian://advanced-uri?vault={quote(vault_name)}&filepath={quote(str(rel))}"
