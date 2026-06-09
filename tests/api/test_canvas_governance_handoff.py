"""Chat→Panel governance handoff reference — acceptance tests.

Covers CANVAS_CHAT_SURFACE/RETURN_GOVERNANCE_HANDOFF_REFERENCE (CHAT-PANEL-HANDOFF-01):
the governance-bearing co-authoring path surfaces a structured handoff reference
(``intent_id`` + ``action_type`` + ``status="routed_to_panel"``), the staged Panel
proposal carries a proposal-scoped origin of ``canvas_coauthoring`` distinct from any
vault-note/frontmatter origin, the returned ``intent_id`` matches the one recorded in
the ``.chats/`` session log, and the whole path stays gated behind ``CANVAS_ENABLED``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.canvas as canvas_module
from app.api.app import app
from app.panel.confirmation import _proposal_store as panel_proposal_store
from app.reasoning.models import ReasoningMode, ReasoningRun


class _StubFacade:
    """Deterministic facade returning a fixed (governance-bearing) generated body."""

    def __init__(self, body: str) -> None:
        self._body = body

    def answer(
        self,
        question: str,
        *,
        context: str | None = None,
        object_ids: list[str] | None = None,
        trace_id: str | None = None,
    ) -> ReasoningRun:
        return ReasoningRun(
            id="run-handoff-1",
            mode=ReasoningMode.ASK_ANSWER,
            status="ok",
            result={"answer": self._body},
            object_uuids=[],
            trace_id=trace_id,
            error=None,
        )


@pytest.fixture(autouse=True)
def _clear_state():
    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()
    panel_proposal_store.clear()
    yield
    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()
    panel_proposal_store.clear()


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    note = tmp_path / "note.md"
    note.write_text(
        "---\nuuid: note-uuid-handoff\norigin: human_capture\n---\n\n# Hello\n\nOriginal body.\n",
        encoding="utf-8",
    )
    return tmp_path


def _make_client(monkeypatch, vault: Path, generated_body: str) -> TestClient:
    monkeypatch.setenv("CANVAS_ENABLED", "1")
    monkeypatch.setattr(canvas_module, "_get_vault_root", lambda: vault)
    facade = _StubFacade(generated_body)
    monkeypatch.setattr(canvas_module, "_coauthor_facade_factory", lambda: facade)
    return TestClient(app)


def _open_session(client: TestClient) -> tuple[str, Path]:
    resp = client.post(
        "/api/canvas/sessions", json={"note_path": "note.md", "label": "handoff"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return body["session_id"], Path(body["log_path"])


# governance-bearing generated body (carries frontmatter)
_GOVERNANCE_BODY = "---\ntype: evergreen\n---\n\n# Hello\n\nRewritten body.\n"


def test_staged_proposal_marked_canvas_origin(monkeypatch, vault: Path) -> None:
    client = _make_client(monkeypatch, vault, _GOVERNANCE_BODY)
    session_id, _ = _open_session(client)

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/coauthor",
        json={"intent": "promote this note to evergreen"},
    )
    assert resp.status_code == 409, resp.text
    intent_id = resp.json()["intent_id"]

    proposal = panel_proposal_store.get(intent_id)
    assert proposal is not None, "Panel proposal should be staged under the handoff intent_id"
    # Proposal-scoped origin — distinct from the vault-note/frontmatter origin.
    assert proposal.proposal_origin == "canvas_coauthoring"
    # Note origin (NoteRef.origin) must NOT be overwritten with the proposal origin.
    assert proposal.intent_event.payload.note.origin != "canvas_coauthoring"


def test_handoff_reference_matches_session_log_intent(monkeypatch, vault: Path) -> None:
    client = _make_client(monkeypatch, vault, _GOVERNANCE_BODY)
    session_id, log_path = _open_session(client)

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/coauthor",
        json={"intent": "promote this note to evergreen"},
    )
    assert resp.status_code == 409, resp.text
    intent_id = resp.json()["intent_id"]

    log_content = log_path.read_text(encoding="utf-8")
    # GovernanceRouter records the same intent_id in the .chats/ session log.
    assert f"intent: {intent_id}" in log_content


def test_governance_handoff_requires_canvas_enabled(monkeypatch, vault: Path) -> None:
    monkeypatch.setenv("CANVAS_ENABLED", "0")
    monkeypatch.setattr(canvas_module, "_get_vault_root", lambda: vault)
    client = TestClient(app)

    resp = client.post(
        "/api/canvas/sessions/any-session/governance",
        json={"action_type": "frontmatter_update", "payload": {}},
    )
    assert resp.status_code == 403, resp.text
