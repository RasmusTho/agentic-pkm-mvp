"""Disk-backed session store for CLI persistence across process restarts.

Sessions are stored as JSON in ~/.{vault}/.canvas-sessions/ so that subsequent
CLI invocations (new processes) can access them.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from app.chat.session_log import SessionLog
from app.services.note_uuid import ensure_note_uuid


class SessionStore:
    """Load/store SessionLog pointers; disk-backed unless explicitly ephemeral."""

    def __init__(self, vault_root: Path, *, durable: bool = True) -> None:
        self._vault_root = vault_root.resolve()
        self._session_dir = self._vault_root / ".canvas-sessions"
        # Voice live-session pointers are explicitly process-local. The chat
        # transcript is their only durable artifact; never load it as context.
        self._durable = durable
        self._memory: dict[str, SessionLog] = {}

    def load(self, session_id: str) -> SessionLog | None:
        """Load a pointer by ID, or None; ephemeral mode never consults disk."""
        if not self._durable:
            return self._memory.get(session_id)
        session_file = self._session_dir / f"{session_id}.json"
        if not session_file.exists():
            return None
        data = json.loads(session_file.read_text(encoding="utf-8"))
        note_path = Path(data["note_path"])
        vault_root = Path(data.get("vault_root") or self._vault_root)
        note_uuid = data.get("note_uuid")
        if note_uuid is None and note_path != Path(data["log_path"]):
            note_uuid = ensure_note_uuid(note_path, vault_root=vault_root)
        return SessionLog(
            log_path=Path(data["log_path"]),
            session_id=data["session_id"],
            note_path=note_path,
            label=data["label"],
            vault_root=vault_root,
            note_uuid=note_uuid,
        )

    def save(self, session: SessionLog) -> None:
        """Save a pointer in the explicitly selected durability mode."""
        if not self._durable:
            self._memory[session.session_id] = session
            return
        self._session_dir.mkdir(parents=True, exist_ok=True)
        session_file = self._session_dir / f"{session.session_id}.json"
        data = asdict(session)
        data["log_path"] = str(data["log_path"])
        data["note_path"] = str(data["note_path"])
        if data.get("vault_root") is not None:
            data["vault_root"] = str(data["vault_root"])
        session_file.write_text(json.dumps(data), encoding="utf-8")

    def delete(self, session_id: str) -> None:
        """Delete a pointer in the explicitly selected durability mode."""
        if not self._durable:
            self._memory.pop(session_id, None)
            return
        session_file = self._session_dir / f"{session_id}.json"
        if session_file.exists():
            session_file.unlink()


__all__ = ["SessionStore"]
