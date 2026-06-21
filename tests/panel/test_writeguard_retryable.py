"""WriteGuard residual surfaces — retryability + governance 409 mapping (#2188).

Two bounded review residuals from the 2026-06-18 terminal audit (#2148):

1. ``app/panel/confirmation.py`` removed a WriteGuard-blocked proposal from
   staging, so a post-reopen retry failed as ``unknown_proposal``. A WriteGuard
   block is transient (health/maintenance lock), so the proposal must stay
   staged and remain retryable once the guard reopens.

2. ``app/api/routes/canvas.py`` let a ``WritesBlockedError`` raised on the
   governance-bearing routing path surface as a 500 instead of the structured,
   retryable 409 the body-edit paths return.

Both tests drive the production call paths (``PanelConfirmationService.confirm``
and the real ``/api/canvas`` HTTP routes).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.canvas as canvas_module
from app.agents.panel.writeback import stable_action_id
from app.api.app import app
from app.events.panel import (
    NoteRef,
    PanelInfo,
    PanelIntentAction,
    PanelIntentEvent,
    PanelIntentPayload,
)
from app.health_contract import WRITE_BLOCKED_STATES
from app.panel.confirmation import (
    ConfirmIdempotencyStore,
    ConfirmRequest,
    PanelConfirmationService,
    ProposalStore,
    StagedProposal,
)
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard


def _make_intent(
    note_uuid: str = "note-uuid-1",
    note_path: str | None = None,
    action_label: str = "send report",
) -> PanelIntentEvent:
    aid = stable_action_id(action_label)
    return PanelIntentEvent(
        payload=PanelIntentPayload(
            note=NoteRef(uuid=note_uuid, path=note_path),
            panel=PanelInfo(panel_id="panel-1", instruction="do it"),
            actions=[PanelIntentAction(id=aid, label=action_label, checked=True)],
        )
    )


# ---------------------------------------------------------------------------
# AC1: a WriteGuard-blocked proposal stays staged and is retryable after reopen
#      (production path: app/panel/confirmation.py :: PanelConfirmationService.confirm)
# ---------------------------------------------------------------------------


def test_writeguard_block_keeps_proposal_staged_and_retryable(tmp_path: Path) -> None:
    action_label = "send report"
    aid = stable_action_id(action_label)
    note_file = tmp_path / "test.md"
    note_file.write_text(
        f"# Note\n- [ ] {action_label} <!--ai:id={aid}-->\n",
        encoding="utf-8",
    )

    # A real WriteGuard backed by a mutable snapshot so the same service
    # instance can transition blocked -> open, exercising the production guard.
    snapshot = {"state": sorted(WRITE_BLOCKED_STATES)[0], "reason": "maintenance"}
    guard = WriteGuard(snapshot_fn=lambda: snapshot)

    ps = ProposalStore()
    ids = ConfirmIdempotencyStore()
    svc = PanelConfirmationService(ps, ids, write_guard=guard)
    ps.stage(
        "prop-1",
        StagedProposal(
            artifact_id="note-uuid-1",
            intent_event=_make_intent(note_path=str(note_file), action_label=action_label),
            proposed_at=0.0,
        ),
    )

    # First confirm: guard is closed -> blocked outcome.
    blocked = svc.confirm(
        ConfirmRequest(
            proposal_id="prop-1",
            artifact_id="note-uuid-1",
            action="confirm",
            idempotency_key="ikey-blocked",
        )
    )
    assert blocked.status == "blocked"

    # The proposal MUST stay staged (in-memory) so a retry can resolve it —
    # the residual fixed here previously removed it, causing unknown_proposal.
    assert ps.get("prop-1") is not None

    # Reopen the guard and retry with a fresh idempotency key (a retry is a new
    # confirm attempt). The retry must resolve the still-staged proposal instead
    # of raising UnknownProposalError, and reach a non-blocked outcome.
    snapshot["state"] = "ok"
    retried = svc.confirm(
        ConfirmRequest(
            proposal_id="prop-1",
            artifact_id="note-uuid-1",
            action="confirm",
            idempotency_key="ikey-retry",
        )
    )
    assert retried.status != "blocked"
    # Now that it executed, the proposal is removed (terminal outcome).
    assert ps.get("prop-1") is None


# ---------------------------------------------------------------------------
# AC2: governance-path writeguard failures map to the structured 409
#      (production path: real /api/canvas HTTP routes)
# ---------------------------------------------------------------------------


class _ClassifierStubFacade:
    """Returns a fixed intent-classification label as the JSON answer."""

    def __init__(self, label: str) -> None:
        self._label = label

    def answer(
        self,
        question: str,
        *,
        context: str | None = None,
        object_ids: list[str] | None = None,
        trace_id: str | None = None,
    ):
        from app.reasoning.models import ReasoningMode, ReasoningRun

        return ReasoningRun(
            id="run-classifier-stub-1",
            mode=ReasoningMode.ASK_ANSWER,
            status="ok",
            result={"answer": self._label},
            object_uuids=[],
            trace_id=trace_id,
            error=None,
        )


def _governance_label(action_type: str = "maturity_transition") -> str:
    return json.dumps({"intent_class": "governance_bearing", "action_type": action_type})


@pytest.fixture(autouse=True)
def _clear_sessions():
    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()
    yield
    canvas_module._sessions.clear()
    canvas_module._edit_history.clear()
    canvas_module._undone_history.clear()


@pytest.fixture()
def vault(tmp_path: Path) -> Path:
    note = tmp_path / "note.md"
    note.write_text(
        "---\nuuid: note-uuid-canvas\n---\n\n# Hello\n\nOriginal body.\n",
        encoding="utf-8",
    )
    return tmp_path


def _make_client(monkeypatch, vault: Path, classifier_label: str) -> TestClient:
    monkeypatch.setenv("CANVAS_ENABLED", "1")
    monkeypatch.setattr(canvas_module, "_get_vault_root", lambda: vault)
    monkeypatch.setattr(canvas_module, "_get_vault_root_or_picker", lambda **_: vault)
    classifier_facade = _ClassifierStubFacade(classifier_label)
    monkeypatch.setattr(
        canvas_module, "_intent_classifier_facade_factory", lambda: classifier_facade
    )
    return TestClient(app)


def _open_session(client: TestClient) -> str:
    resp = client.post(
        "/api/canvas/sessions", json={"note_path": "note.md", "label": "coauthor"}
    )
    assert resp.status_code == 200
    return resp.json()["session_id"]


def _assert_structured_blocked(resp) -> None:
    # Not a 500: a closed write-guard is a transient, retryable health-gate state.
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert isinstance(detail, dict), detail
    assert detail["error"] == "writeguard_blocked"
    assert detail["state"] == "blocked"
    assert detail["reason"] == "maintenance"
    assert isinstance(detail["message"], str) and detail["message"]


def test_governance_coauthor_path_blocked_returns_structured_409(
    monkeypatch, vault: Path
) -> None:
    """Classifier routes a governance-bearing intent to the gated pipeline; a
    closed write-guard there must return the structured 409, not a 500."""
    client = _make_client(monkeypatch, vault, _governance_label("maturity_transition"))
    session_id = _open_session(client)
    original = (vault / "note.md").read_text(encoding="utf-8")

    blocked_state = sorted(WRITE_BLOCKED_STATES)[0]
    monkeypatch.setattr(
        DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        lambda: {"state": blocked_state, "reason": "maintenance"},
    )

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/coauthor",
        json={"intent": "promote this note to evergreen"},
    )

    _assert_structured_blocked(resp)
    # The note was never touched on the blocked governance routing path.
    assert (vault / "note.md").read_text(encoding="utf-8") == original


def test_governance_endpoint_blocked_returns_structured_409(
    monkeypatch, vault: Path
) -> None:
    """The direct /governance endpoint must also map a closed write-guard to the
    structured 409 rather than letting WritesBlockedError surface as a 500."""
    client = _make_client(monkeypatch, vault, _governance_label("maturity_transition"))
    session_id = _open_session(client)
    original = (vault / "note.md").read_text(encoding="utf-8")

    blocked_state = sorted(WRITE_BLOCKED_STATES)[0]
    monkeypatch.setattr(
        DEFAULT_WRITE_GUARD,
        "snapshot_fn",
        lambda: {"state": blocked_state, "reason": "maintenance"},
    )

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/governance",
        json={"action_type": "maturity_transition", "payload": {"to": "evergreen"}},
    )

    _assert_structured_blocked(resp)
    assert (vault / "note.md").read_text(encoding="utf-8") == original
