from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def append_change(message: str, inbox: str = "Inbox/System-changes.md") -> None:
    _append_line(inbox, message)


def append_conflict(message: str, inbox: str = "Inbox/Conflicts.md") -> None:
    _append_line(inbox, message)


def _append_line(path: str, message: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with target.open("a", encoding="utf-8") as handle:
        handle.write(f"- [{timestamp}] {message}\n")
