"""Process-local voice context, with the existing append-only chat writer."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from app.chat.session_log import SessionLogWriter
from app.chat.session_store import SessionStore


class VoiceSessionContextLost(ValueError):
    """A session is absent, closed, restarted, or outside the current scope."""


class VoiceSessions:
    """Own one selected vault's ephemeral session pointers and prior Q&A.

    The synchronous voice turn has no await between context lookup and record,
    so turns on the API event loop are serialized. No distributed/session
    resume guarantee is supplied: another worker must refuse an unknown id.
    """

    def __init__(self, vault_root: Path) -> None:
        self._writer = SessionLogWriter(vault_root=vault_root)
        self._store = SessionStore(vault_root, durable=False)
        self._turns: dict[str, list[dict[str, Any]]] = {}
        self._scopes: dict[str, str | None] = {}

    def question(self, question: str, *, session_id: str | None, scope: str | None) -> str:
        if session_id is None:
            return question
        if self._store.load(session_id) is None or self._scopes.get(session_id) != scope:
            raise VoiceSessionContextLost("earlier voice context is unavailable; start a new session")
        history = json.dumps(self._turns[session_id], ensure_ascii=False)
        return (
            f"{question}\n\nPrior Q&A from this voice session "
            f"(conversation context, not new source evidence):\n{history}"
        )

    def record(
        self,
        *,
        session_id: str | None,
        scope: str | None,
        question: str,
        answer: str,
        citations: list[dict[str, Any]],
        end_session: bool = False,
    ) -> tuple[str | None, str | None]:
        session = self._store.load(session_id) if session_id is not None else None
        if session_id is not None and (session is None or self._scopes.get(session_id) != scope):
            raise VoiceSessionContextLost("earlier voice context is unavailable; start a new session")
        if session is None:
            try:
                session = self._writer.open_session(None, "voice")
            except Exception:
                return None, "session_transcript_unavailable"
            self._store.save(session)
            self._turns[session.session_id] = []
            self._scopes[session.session_id] = scope
        # This is live context for the answer the user actually received,
        # independent of best-effort episode-signal logging (INV-VOICE-A).
        self._turns[session.session_id].append(
            {"question": question, "answer": answer, "citations": citations}
        )
        transcript_error = None
        try:
            summary = answer
            if citations:
                summary += "\nCitations: " + json.dumps(citations, ensure_ascii=False)
            self._writer.append_turn(
                session, question, summary, timestamp=datetime.now(timezone.utc)
            )
        except Exception:
            transcript_error = "session_transcript_unavailable"
        if end_session:
            try:
                self._writer.close_session(session, "Voice session ended.")
            except Exception:
                transcript_error = "session_transcript_unavailable"
            else:
                self._store.delete(session.session_id)
                self._turns.pop(session.session_id, None)
                self._scopes.pop(session.session_id, None)
        return session.session_id, transcript_error


__all__ = ["VoiceSessionContextLost", "VoiceSessions"]
