from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from app.chat.canvas_writer import GovernanceBearingMutationError
from app.chat.governance_router import (
    GovernanceActionType,
    GovernanceRouter,
    PendingAction,
)
from app.chat.session_log import SessionLog, SessionLogWriter
from app.write_guard import WritesBlockedError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _MockPipeline:
    """Stub Panel pipeline for test isolation — no DB, no outbox."""

    def __init__(self, intent_id: str = "intent-abc123") -> None:
        self._intent_id = intent_id
        self.submitted: list[dict[str, Any]] = []

    def submit_intent(self, action_type: str, payload: dict, session_id: str) -> str:
        self.submitted.append({"action_type": action_type, "payload": payload, "session_id": session_id})
        return self._intent_id


class _BlockedWriteGuard:
    """Write guard stub that always blocks writes."""

    def assert_writes_allowed(self, action: str) -> None:
        raise WritesBlockedError(state="blocked", reason="test lock", action=action)


class _OpenWriteGuard:
    """Write guard stub that always permits writes."""

    def assert_writes_allowed(self, action: str) -> None:
        pass  # always open


def _log_writer(vault_root: Path) -> SessionLogWriter:
    fixed_now = datetime(2026, 4, 24, 10, 0)
    return SessionLogWriter(vault_root=vault_root, now_fn=lambda: fixed_now, uuid_fn=lambda: "test-uuid")


def _session(vault_root: Path) -> SessionLog:
    note = vault_root / "notes" / "my-note.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("---\ntype: note\n---\n\nOriginal body.\n", encoding="utf-8")
    lw = _log_writer(vault_root)
    return lw.open_session(note, "governance-test")


# ---------------------------------------------------------------------------
# AC1: request_governance_action routes to Panel pipeline (not note directly)
# ---------------------------------------------------------------------------

def test_request_routes_to_panel_pipeline(tmp_path: Path) -> None:
    pipeline = _MockPipeline()
    lw = _log_writer(tmp_path)
    session = _session(tmp_path)
    router = GovernanceRouter(panel_pipeline=pipeline, session_log_writer=lw, write_guard=_OpenWriteGuard())

    result = router.request_governance_action(
        session=session,
        action_type=GovernanceActionType.FRONTMATTER_UPDATE,
        payload={"field": "maturity", "value": "evergreen"},
    )

    assert len(pipeline.submitted) == 1
    assert pipeline.submitted[0]["action_type"] == GovernanceActionType.FRONTMATTER_UPDATE
    assert isinstance(result, PendingAction)
    assert result.intent_id == "intent-abc123"


# ---------------------------------------------------------------------------
# AC2: governance request does not immediately mutate the note
# ---------------------------------------------------------------------------

def test_request_does_not_write_note_directly(tmp_path: Path) -> None:
    pipeline = _MockPipeline()
    lw = _log_writer(tmp_path)
    session = _session(tmp_path)
    note = session.note_path
    original = note.read_text(encoding="utf-8")

    router = GovernanceRouter(panel_pipeline=pipeline, session_log_writer=lw, write_guard=_OpenWriteGuard())
    router.request_governance_action(
        session=session,
        action_type=GovernanceActionType.FRONTMATTER_UPDATE,
        payload={"field": "maturity", "value": "evergreen"},
    )

    # Note must be byte-for-byte unchanged
    assert note.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# AC3: session log records pending governance action with Panel intent ID
# ---------------------------------------------------------------------------

def test_session_log_records_pending_intent(tmp_path: Path) -> None:
    pipeline = _MockPipeline(intent_id="intent-xyz999")
    lw = _log_writer(tmp_path)
    session = _session(tmp_path)
    router = GovernanceRouter(panel_pipeline=pipeline, session_log_writer=lw, write_guard=_OpenWriteGuard())

    router.request_governance_action(
        session=session,
        action_type=GovernanceActionType.FRONTMATTER_UPDATE,
        payload={"field": "maturity", "value": "evergreen"},
    )

    log_content = session.log_path.read_text(encoding="utf-8")
    assert "intent-xyz999" in log_content
    assert "pending" in log_content.lower()


# ---------------------------------------------------------------------------
# AC4 (regression): CanvasWriter.apply_edit still raises on frontmatter
# ---------------------------------------------------------------------------

def test_apply_edit_rejects_frontmatter_in_body_regression(tmp_path: Path) -> None:
    """Regression: GovernanceBearingMutationError guard in CanvasWriter must not be removed."""
    from app.chat.canvas_writer import CanvasWriter

    note = tmp_path / "notes" / "reg-note.md"
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text("---\ntype: note\n---\n\nBody.\n", encoding="utf-8")
    lw = _log_writer(tmp_path)
    session = lw.open_session(note, "regression")
    writer = CanvasWriter(vault_root=tmp_path, log_writer=lw)

    with pytest.raises(GovernanceBearingMutationError):
        writer.apply_edit(session, "---\nmaturity: evergreen\n---\n\nBody", "frontmatter sneak")


# ---------------------------------------------------------------------------
# AC5: request_governance_action respects write_guard
# ---------------------------------------------------------------------------

def test_request_respects_write_guard(tmp_path: Path) -> None:
    pipeline = _MockPipeline()
    lw = _log_writer(tmp_path)
    session = _session(tmp_path)
    router = GovernanceRouter(
        panel_pipeline=pipeline,
        session_log_writer=lw,
        write_guard=_BlockedWriteGuard(),
    )

    with pytest.raises(WritesBlockedError):
        router.request_governance_action(
            session=session,
            action_type=GovernanceActionType.FRONTMATTER_UPDATE,
            payload={"field": "maturity", "value": "evergreen"},
        )

    # Pipeline must not have been called
    assert len(pipeline.submitted) == 0


# ---------------------------------------------------------------------------
# Extra: PendingAction carries session linkage
# ---------------------------------------------------------------------------

def test_pending_action_carries_session_id(tmp_path: Path) -> None:
    pipeline = _MockPipeline(intent_id="intent-link-test")
    lw = _log_writer(tmp_path)
    session = _session(tmp_path)
    router = GovernanceRouter(panel_pipeline=pipeline, session_log_writer=lw, write_guard=_OpenWriteGuard())

    result = router.request_governance_action(
        session=session,
        action_type=GovernanceActionType.FRONTMATTER_UPDATE,
        payload={"field": "maturity", "value": "evergreen"},
    )

    assert result.session_id == session.session_id
    assert result.intent_id == "intent-link-test"
