"""Chat→Panel governance handoff reference — acceptance tests.

Covers CANVAS_CHAT_SURFACE/RETURN_GOVERNANCE_HANDOFF_REFERENCE (CHAT-PANEL-HANDOFF-01):
the governance-bearing co-authoring path surfaces a structured handoff reference
(``intent_id`` + ``action_type`` + ``status="routed_to_panel"``), the staged Panel
proposal carries a proposal-scoped origin of ``canvas_coauthoring`` distinct from any
vault-note/frontmatter origin, the returned ``intent_id`` matches the one recorded in
the ``.chats/`` session log, and the whole path stays gated behind ``CANVAS_ENABLED``.

Also covers the carried governance intent (#1772): the staged Panel proposal payload
threads the original natural-language request (and the classified fields on the
intent-classifier path) so Panel review/confirmation can see what the human asked for.
"""

from __future__ import annotations

import json
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


class _ClassifierStubFacade:
    """Deterministic facade returning a fixed intent-classification label."""

    def __init__(self, label: str) -> None:
        self._label = label

    def answer(
        self,
        question: str,
        *,
        context: str | None = None,
        object_ids: list[str] | None = None,
        trace_id: str | None = None,
    ) -> ReasoningRun:
        return ReasoningRun(
            id="run-handoff-classifier-1",
            mode=ReasoningMode.ASK_ANSWER,
            status="ok",
            result={"answer": self._label},
            object_uuids=[],
            trace_id=trace_id,
            error=None,
        )


def _co_authoring_label() -> str:
    return json.dumps({"intent_class": "co_authoring", "action_type": None})


def _governance_label(action_type: str = "maturity_transition") -> str:
    return json.dumps({"intent_class": "governance_bearing", "action_type": action_type})


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


def _make_client(
    monkeypatch,
    vault: Path,
    generated_body: str,
    *,
    classifier_label: str | None = None,
) -> TestClient:
    """Build a TestClient with the co-author and classifier stubs wired in.

    ``classifier_label`` defaults to a plain co_authoring label so the existing
    handoff tests deterministically exercise the body-frontmatter defense-in-depth
    backstop (the classifier does not route; the frontmatter-bearing generation does).
    """
    monkeypatch.setenv("CANVAS_ENABLED", "1")
    monkeypatch.setattr(canvas_module, "_get_vault_root", lambda: vault)
    monkeypatch.setattr(canvas_module, "_get_vault_root_or_picker", lambda **_: vault)
    facade = _StubFacade(generated_body)
    monkeypatch.setattr(canvas_module, "_coauthor_facade_factory", lambda: facade)
    if classifier_label is None:
        classifier_label = _co_authoring_label()
    classifier_facade = _ClassifierStubFacade(classifier_label)
    monkeypatch.setattr(
        canvas_module, "_intent_classifier_facade_factory", lambda: classifier_facade
    )
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
    # Carried governance intent (#1772): the projected proposal payload is not empty —
    # it carries at least the original request text.
    params = proposal.intent_event.payload.actions[0].mapping.params
    assert params["original_request"] == "promote this note to evergreen"


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


# ---------------------------------------------------------------------------
# Carried governance intent in the staged proposal payload (#1772)
# ---------------------------------------------------------------------------


def _staged_action_params(intent_id: str) -> dict:
    proposal = panel_proposal_store.get(intent_id)
    assert proposal is not None, "Panel proposal should be staged under the handoff intent_id"
    actions = proposal.intent_event.payload.actions
    assert len(actions) == 1
    return actions[0].mapping.params


def test_classifier_routed_payload_carries_intent_and_classified_fields(
    monkeypatch, vault: Path
) -> None:
    """The classifier-routed handoff threads the original request and classified fields.

    For "promote this note to evergreen" the staged proposal must carry the
    original natural-language request plus what the classifier extracted
    (intent class + classified action type) — not an empty payload — so the
    Panel review/confirmation path can see and act on what the human asked for.
    """
    # Frontmatter-free generation: only the intent classifier routes this.
    client = _make_client(
        monkeypatch,
        vault,
        "# Hello\n\nBody without frontmatter.\n",
        classifier_label=_governance_label("maturity_transition"),
    )
    session_id, _ = _open_session(client)

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/coauthor",
        json={"intent": "promote this note to evergreen"},
    )
    assert resp.status_code == 409, resp.text

    params = _staged_action_params(resp.json()["intent_id"])
    assert params["original_request"] == "promote this note to evergreen"
    assert params["routed_via"] == "intent_classifier"
    assert params["intent_class"] == "governance_bearing"
    assert params["classified_action_type"] == "maturity_transition"


def test_backstop_routed_payload_carries_original_request(monkeypatch, vault: Path) -> None:
    """The defense-in-depth (GovernanceBearingMutationError) path supplies the request text.

    No classified fields exist on this path (the classifier labeled the intent
    co_authoring; the frontmatter-bearing generation tripped the backstop), so
    the payload carries at least the original request plus the routing marker.
    """
    client = _make_client(
        monkeypatch,
        vault,
        _GOVERNANCE_BODY,
        classifier_label=_co_authoring_label(),
    )
    session_id, _ = _open_session(client)

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/coauthor",
        json={"intent": "rewrite the body"},
    )
    assert resp.status_code == 409, resp.text

    params = _staged_action_params(resp.json()["intent_id"])
    assert params["original_request"] == "rewrite the body"
    assert params["routed_via"] == "body_frontmatter_backstop"
    # No fabricated classifier fields on the backstop path.
    assert "intent_class" not in params
    assert "classified_action_type" not in params


def test_staged_proposal_review_surfaces_original_request(monkeypatch, vault: Path) -> None:
    """Panel proposal review surfaces the carried intent, not only the coarse action type.

    The staged proposal's human-facing instruction must include the original
    request text so reviewing the proposal shows what the human actually asked
    for (instead of the generic ``canvas governance: <action_type>``).
    """
    client = _make_client(
        monkeypatch,
        vault,
        "# Hello\n\nBody without frontmatter.\n",
        classifier_label=_governance_label("maturity_transition"),
    )
    session_id, _ = _open_session(client)

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/coauthor",
        json={"intent": "promote this note to evergreen"},
    )
    assert resp.status_code == 409, resp.text

    proposal = panel_proposal_store.get(resp.json()["intent_id"])
    assert proposal is not None
    instruction = proposal.intent_event.payload.panel.instruction
    assert "promote this note to evergreen" in instruction
    assert "maturity_transition" in instruction


def test_governance_handoff_requires_canvas_enabled(monkeypatch, vault: Path) -> None:
    monkeypatch.setenv("CANVAS_ENABLED", "0")
    monkeypatch.setattr(canvas_module, "_get_vault_root", lambda: vault)
    client = TestClient(app)

    resp = client.post(
        "/api/canvas/sessions/any-session/governance",
        json={"action_type": "frontmatter_update", "payload": {}},
    )
    assert resp.status_code == 403, resp.text
