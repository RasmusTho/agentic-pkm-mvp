"""Disk-backed session store for CLI persistence across process restarts.

Sessions are stored as JSON in ~/.{vault}/.canvas-sessions/ so that subsequent
CLI invocations (new processes) can access them.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from app.chat.session_log import SessionLog


class SessionStore:
    """Load/store SessionLog to disk for cross-process access."""

    def __init__(self, vault_root: Path) -> None:
        self._vault_root = vault_root.resolve()
        self._session_dir = self._vault_root / ".canvas-sessions"

    def load(self, session_id: str) -> SessionLog | None:
        """Load a session by ID from disk, or None if not found."""
        session_file = self._session_dir / f"{session_id}.json"
        if not session_file.exists():
            return None
        data = json.loads(session_file.read_text(encoding="utf-8"))
        return SessionLog(
            log_path=Path(data["log_path"]),
            session_id=data["session_id"],
            note_path=Path(data["note_path"]),
            label=data["label"],
            vault_root=Path(data.get("vault_root") or self._vault_root),
        )

    def save(self, session: SessionLog) -> None:
        """Save a session to disk."""
        self._session_dir.mkdir(parents=True, exist_ok=True)
        session_file = self._session_dir / f"{session.session_id}.json"
        data = asdict(session)
        data["log_path"] = str(data["log_path"])
        data["note_path"] = str(data["note_path"])
        if data.get("vault_root") is not None:
            data["vault_root"] = str(data["vault_root"])
        session_file.write_text(json.dumps(data), encoding="utf-8")

    def delete(self, session_id: str) -> None:
        """Delete a session from disk."""
        session_file = self._session_dir / f"{session_id}.json"
        if session_file.exists():
            session_file.unlink()


__all__ = ["SessionStore"]
