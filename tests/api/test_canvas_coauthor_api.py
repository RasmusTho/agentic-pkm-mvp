"""Canvas co-authoring API — acceptance tests (no Postgres, no live LLM)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.canvas as canvas_module
from app.api.app import app
from app.reasoning.models import ReasoningMode, ReasoningRun


class _StubFacade:
    """Deterministic facade returning a fixed generated body."""

    def __init__(self, body: str) -> None:
        self._body = body
        self.calls: list[dict[str, object]] = []

    def answer(
        self,
        question: str,
        *,
        context: str | None = None,
        object_ids: list[str] | None = None,
        trace_id: str | None = None,
    ) -> ReasoningRun:
        self.calls.append({"question": question, "context": context})
        return ReasoningRun(
            id="run-coauthor-api-1",
            mode=ReasoningMode.ASK_ANSWER,
            status="ok",
            result={"answer": self._body},
            object_uuids=[],
            trace_id=trace_id,
            error=None,
        )


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


# Classifier labels returned by the intent-classifier facade stub. The route
# classifies the *intent* first; existing generate-path tests pin the classifier
# to co-authoring so the body-frontmatter backstop is what is under test.
_CO_AUTHORING_LABEL = '{"intent_class": "co_authoring", "action_type": null}'
_GOVERNANCE_MATURITY_LABEL = (
    '{"intent_class": "governance_bearing", "action_type": "maturity_transition"}'
)
_EXPLORATORY_LABEL = '{"intent_class": "exploratory", "action_type": null}'
# Mock/degraded backend sentinel — the classifier returns classified=False.
_DEGRADED_LABEL = "MOCK_ASK_ANSWER: classify intent | context: ..."


def _make_client_with_facades(
    monkeypatch,
    vault: Path,
    generated_body: str,
    *,
    intent_label: str = _CO_AUTHORING_LABEL,
) -> tuple[TestClient, _StubFacade, _StubFacade]:
    """Build a TestClient with both the co-authoring and intent-classifier
    facades stubbed. Returns (client, coauthor_facade, classifier_facade) so
    tests can assert whether body generation was consulted at all."""
    monkeypatch.setenv("CANVAS_ENABLED", "1")
    monkeypatch.setattr(canvas_module, "_get_vault_root", lambda: vault)
    coauthor_facade = _StubFacade(generated_body)
    monkeypatch.setattr(
        canvas_module, "_coauthor_facade_factory", lambda: coauthor_facade
    )
    classifier_facade = _StubFacade(intent_label)
    monkeypatch.setattr(
        canvas_module, "_intent_classifier_facade_factory", lambda: classifier_facade
    )
    return TestClient(app), coauthor_facade, classifier_facade


def _make_client(
    monkeypatch,
    vault: Path,
    generated_body: str,
    *,
    intent_label: str = _CO_AUTHORING_LABEL,
) -> TestClient:
    client, _, _ = _make_client_with_facades(
        monkeypatch, vault, generated_body, intent_label=intent_label
    )
    return client


def _open_session(client: TestClient) -> str:
    resp = client.post(
        "/api/canvas/sessions", json={"note_path": "note.md", "label": "coauthor"}
    )
    assert resp.status_code == 200
    return resp.json()["session_id"]


# ---------------------------------------------------------------------------


def test_coauthor_applies_generated_body(monkeypatch, vault: Path) -> None:
    generated = "# Hello\n\nExpanded decision section with trade-offs.\n"
    client = _make_client(monkeypatch, vault, generated)
    session_id = _open_session(client)

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/coauthor",
        json={"intent": "expand the decision section", "change_summary": "expanded decision"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["generated"] is True
    assert body["applied_body"].strip() == generated.strip()
    # The note body on disk reflects the generated revision.
    note_text = (vault / "note.md").read_text(encoding="utf-8")
    assert "Expanded decision section with trade-offs." in note_text
    # Frontmatter is preserved.
    assert "uuid: note-uuid-canvas" in note_text


def test_coauthor_appends_intent_to_session_log(monkeypatch, vault: Path) -> None:
    generated = "# Hello\n\nRevised body.\n"
    client = _make_client(monkeypatch, vault, generated)
    open_resp = client.post(
        "/api/canvas/sessions", json={"note_path": "note.md", "label": "coauthor-log"}
    )
    session_id = open_resp.json()["session_id"]
    log_path = Path(open_resp.json()["log_path"])

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/coauthor",
        json={"intent": "tighten the intro", "change_summary": "tightened intro"},
    )
    assert resp.status_code == 200, resp.text

    log_content = log_path.read_text(encoding="utf-8")
    assert "tighten the intro" in log_content
    assert "tightened intro" in log_content


def test_coauthor_governance_bearing_is_routed_not_applied(monkeypatch, vault: Path) -> None:
    # The generated body contains a frontmatter block — governance-bearing.
    generated = "---\ntype: evergreen\n---\n\n# Hello\n\nRewritten body.\n"
    client = _make_client(monkeypatch, vault, generated)
    session_id = _open_session(client)
    original = (vault / "note.md").read_text(encoding="utf-8")

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/coauthor",
        json={"intent": "promote this note to evergreen"},
    )

    # Not applied in place; routed to the gated pipeline.
    assert resp.status_code == 409, resp.text
    assert (vault / "note.md").read_text(encoding="utf-8") == original


def test_governance_bearing_returns_handoff_reference(monkeypatch, vault: Path) -> None:
    # The generated body contains a frontmatter block — governance-bearing.
    generated = "---\ntype: evergreen\n---\n\n# Hello\n\nRewritten body.\n"
    client = _make_client(monkeypatch, vault, generated)
    session_id = _open_session(client)

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/coauthor",
        json={"intent": "promote this note to evergreen"},
    )

    # Structured handoff reference is returned (status preserved at 409).
    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["status"] == "routed_to_panel"
    assert isinstance(body["intent_id"], str) and body["intent_id"]
    assert body["action_type"] == "frontmatter_update"
    assert "detail" in body


def test_coauthor_mock_generation_is_not_applied(monkeypatch, vault: Path) -> None:
    # A mock/degraded backend response must not be written into the note.
    generated = "MOCK_ASK_ANSWER: expand the decision section | context: ..."
    client = _make_client(monkeypatch, vault, generated)
    session_id = _open_session(client)
    original = (vault / "note.md").read_text(encoding="utf-8")

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/coauthor",
        json={"intent": "expand the decision section"},
    )

    assert resp.status_code == 503, resp.text
    assert (vault / "note.md").read_text(encoding="utf-8") == original


def test_coauthor_requires_canvas_enabled(monkeypatch, vault: Path) -> None:
    monkeypatch.setenv("CANVAS_ENABLED", "0")
    monkeypatch.setattr(canvas_module, "_get_vault_root", lambda: vault)
    client = TestClient(app)
    resp = client.post(
        "/api/canvas/sessions/any-session/coauthor",
        json={"intent": "do something"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Intent-level governance routing (ROUTE_GOVERNANCE_INTENT_ON_COAUTHOR, #1744)
# ---------------------------------------------------------------------------


def test_natural_governance_intent_routes_to_panel(monkeypatch, vault: Path) -> None:
    # The co-authoring stub would return a frontmatter-FREE body — under the old
    # body-only detection this would have been applied in place. The classified
    # intent must route to Panel before any body is generated.
    generated = "# Hello\n\nRewritten body without any frontmatter.\n"
    client, coauthor_facade, _ = _make_client_with_facades(
        monkeypatch, vault, generated, intent_label=_GOVERNANCE_MATURITY_LABEL
    )
    session_id = _open_session(client)
    original = (vault / "note.md").read_text(encoding="utf-8")

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/coauthor",
        json={"intent": "promote this note to evergreen"},
    )

    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["status"] == "routed_to_panel"
    assert isinstance(body["intent_id"], str) and body["intent_id"]
    # Note never mutated on the governance path.
    assert (vault / "note.md").read_text(encoding="utf-8") == original
    # No body was generated: the co-authoring facade was never consulted.
    assert coauthor_facade.calls == []


def test_handoff_action_type_reflects_classified_intent(monkeypatch, vault: Path) -> None:
    # The handoff reference carries the classified action_type, not the
    # hardcoded frontmatter_update of the body-frontmatter backstop.
    generated = "# Hello\n\nRewritten body without any frontmatter.\n"
    client, _, _ = _make_client_with_facades(
        monkeypatch, vault, generated, intent_label=_GOVERNANCE_MATURITY_LABEL
    )
    session_id = _open_session(client)

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/coauthor",
        json={"intent": "promote this note to evergreen"},
    )

    assert resp.status_code == 409, resp.text
    assert resp.json()["action_type"] == "maturity_transition"


def test_exploratory_intent_does_not_mutate(monkeypatch, vault: Path) -> None:
    generated = "# Hello\n\nA body that must never be generated or applied.\n"
    client, coauthor_facade, _ = _make_client_with_facades(
        monkeypatch, vault, generated, intent_label=_EXPLORATORY_LABEL
    )
    session_id = _open_session(client)
    original = (vault / "note.md").read_text(encoding="utf-8")

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/coauthor",
        json={"intent": "what does this note argue?"},
    )

    # Read-only, non-mutating response: no generation, no write.
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "exploratory_no_edit"
    assert (vault / "note.md").read_text(encoding="utf-8") == original
    assert coauthor_facade.calls == []


def test_classifier_degraded_falls_through(monkeypatch, vault: Path) -> None:
    # A degraded classifier (classified=False) must not fabricate a governance
    # routing; the route falls through to the existing generate-and-apply path.
    generated = "# Hello\n\nExpanded decision section with trade-offs.\n"
    client, coauthor_facade, _ = _make_client_with_facades(
        monkeypatch, vault, generated, intent_label=_DEGRADED_LABEL
    )
    session_id = _open_session(client)

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/coauthor",
        json={"intent": "expand the decision section"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["applied_body"].strip() == generated.strip()
    note_text = (vault / "note.md").read_text(encoding="utf-8")
    assert "Expanded decision section with trade-offs." in note_text
    # The generate path WAS consulted (fall-through, no regression).
    assert coauthor_facade.calls, "expected fall-through to the generate path"
