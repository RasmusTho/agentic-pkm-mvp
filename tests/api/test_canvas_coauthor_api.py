"""Canvas co-authoring API — acceptance tests (no Postgres, no live LLM)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes.canvas as canvas_module
from app.api.app import app
from app.health_contract import WRITE_BLOCKED_STATES
from app.reasoning.models import ReasoningMode, ReasoningRun
from app.write_guard import DEFAULT_WRITE_GUARD


class _StubFacade:
    """Deterministic facade returning a fixed generated body (co-author cognition)."""

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


class _ClassifierStubFacade:
    """Deterministic facade returning a fixed intent classification label.

    Returns the given label as the JSON answer so the intent classifier
    parses it into the appropriate ``IntentClassification``.
    """

    def __init__(self, label: str) -> None:
        self._label = label
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
            id="run-classifier-stub-1",
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


def _exploratory_label() -> str:
    return json.dumps({"intent_class": "exploratory", "action_type": None})


def _degraded_label() -> str:
    # Degraded backend returns a MOCK_ sentinel that the classifier ignores,
    # defaulting conservatively to CO_AUTHORING with classified=False.
    return "MOCK_ASK_ANSWER: classify intent | context: ..."


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


def _make_client(
    monkeypatch,
    vault: Path,
    generated_body: str,
    *,
    classifier_label: str | None = None,
) -> TestClient:
    """Build a TestClient with both the co-author and classifier stubs wired in.

    ``classifier_label`` defaults to a plain co_authoring label so existing
    tests that don't care about classification still take the generate-and-apply
    path without change.
    """
    monkeypatch.setenv("CANVAS_ENABLED", "1")
    monkeypatch.setattr(canvas_module, "_get_vault_root", lambda: vault)
    coauthor_facade = _StubFacade(generated_body)
    monkeypatch.setattr(
        canvas_module, "_coauthor_facade_factory", lambda: coauthor_facade
    )
    if classifier_label is None:
        classifier_label = _co_authoring_label()
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


# ---------------------------------------------------------------------------
# AC: co-authoring intent generates and applies in place
# ---------------------------------------------------------------------------


def test_coauthor_applies_generated_body(monkeypatch, vault: Path) -> None:
    generated = "# Hello\n\nExpanded decision section with trade-offs.\n"
    client = _make_client(monkeypatch, vault, generated, classifier_label=_co_authoring_label())
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


def test_coauthor_blocked_when_writes_disabled(monkeypatch, vault: Path) -> None:
    """A closed write-guard makes /coauthor return 409 and leaves the note unchanged (#1961)."""
    generated = "# Hello\n\nShould not be written.\n"
    client = _make_client(monkeypatch, vault, generated, classifier_label=_co_authoring_label())
    session_id = _open_session(client)

    blocked_state = sorted(WRITE_BLOCKED_STATES)[0]
    monkeypatch.setattr(
        DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": blocked_state, "reason": "maintenance"}
    )

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/coauthor",
        json={"intent": "expand the decision section", "change_summary": "expanded"},
    )

    assert resp.status_code == 409, resp.text
    note_text = (vault / "note.md").read_text(encoding="utf-8")
    assert "Original body." in note_text
    assert "Should not be written." not in note_text


def test_blocked_write_returns_structured_response(monkeypatch, vault: Path) -> None:
    """A closed write-guard yields a structured 409 (not a flat string), mirroring
    the companion/capture boundary translation, across /coauthor, /edits, and undo.

    The structured body lets a client distinguish a transient health-gate block
    (retryable) from a permanent rejection. Regression for the canvas write-guard
    HTTP mapping (#2017): previously these paths returned ``detail=str(exc)``.
    """
    generated = "# Hello\n\nShould not be written.\n"
    client = _make_client(monkeypatch, vault, generated, classifier_label=_co_authoring_label())
    session_id = _open_session(client)

    blocked_state = sorted(WRITE_BLOCKED_STATES)[0]
    monkeypatch.setattr(
        DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": blocked_state, "reason": "maintenance"}
    )

    def _assert_structured_blocked(resp) -> None:
        assert resp.status_code == 409, resp.text
        detail = resp.json()["detail"]
        assert isinstance(detail, dict), detail
        assert detail["error"] == "writeguard_blocked"
        assert detail["state"] == "blocked"
        assert detail["reason"] == "maintenance"
        assert isinstance(detail["message"], str) and detail["message"]

    # /coauthor — co-authoring generate-and-apply path.
    _assert_structured_blocked(
        client.post(
            f"/api/canvas/sessions/{session_id}/coauthor",
            json={"intent": "expand the decision section", "change_summary": "expanded"},
        )
    )

    # /edits — direct in-place body edit.
    _assert_structured_blocked(
        client.post(
            f"/api/canvas/sessions/{session_id}/edits",
            json={"new_body": "# Hello\n\nBlocked edit.\n", "change_summary": "edit"},
        )
    )

    # The note was never touched on any blocked path.
    note_text = (vault / "note.md").read_text(encoding="utf-8")
    assert "Original body." in note_text
    assert "Should not be written." not in note_text
    assert "Blocked edit." not in note_text


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
    assert log_content.count("**User:** tighten the intro") == 1
    assert log_content.count("**Change:** tightened intro") == 1
    assert "**User:** \n" not in log_content


# ---------------------------------------------------------------------------
# AC: natural governance intent routes to Panel via intent path (not backstop)
# ---------------------------------------------------------------------------


def test_natural_governance_intent_routes_to_panel(monkeypatch, vault: Path) -> None:
    """A governance intent detected at the classifier level routes to Panel.

    The co-authoring stub would return a frontmatter-free body — so without
    the intent classifier the intent would have been applied as a co-authoring
    edit. The classifier routes it to Panel *before* generation; the note is
    unchanged and no body is generated.
    """
    # Co-authoring stub returns a body WITHOUT frontmatter — the backstop alone
    # would NOT have fired. Only the intent classifier routes this to Panel.
    generated_no_frontmatter = "# Hello\n\nBody without frontmatter.\n"
    client = _make_client(
        monkeypatch,
        vault,
        generated_no_frontmatter,
        classifier_label=_governance_label("maturity_transition"),
    )
    session_id = _open_session(client)
    original = (vault / "note.md").read_text(encoding="utf-8")

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/coauthor",
        json={"intent": "promote this note to evergreen"},
    )

    assert resp.status_code == 409, resp.text
    # Note body is unchanged — no body was generated or applied.
    assert (vault / "note.md").read_text(encoding="utf-8") == original
    body = resp.json()
    assert body["status"] == "routed_to_panel"
    assert isinstance(body["intent_id"], str) and body["intent_id"]


def test_handoff_action_type_reflects_classified_intent(monkeypatch, vault: Path) -> None:
    """The handoff carries the classified action_type, not a hardcoded value.

    The classifier labels the intent ``maturity_transition``; the returned
    ``GovernanceHandoffRef`` must carry ``action_type == "maturity_transition"``,
    not the backstop default ``"frontmatter_update"``.
    """
    generated_no_frontmatter = "# Hello\n\nBody without frontmatter.\n"
    client = _make_client(
        monkeypatch,
        vault,
        generated_no_frontmatter,
        classifier_label=_governance_label("maturity_transition"),
    )
    session_id = _open_session(client)

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/coauthor",
        json={"intent": "promote this note to evergreen"},
    )

    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["status"] == "routed_to_panel"
    assert body["action_type"] == "maturity_transition"
    assert "detail" in body


# ---------------------------------------------------------------------------
# AC: exploratory intent is non-mutating
# ---------------------------------------------------------------------------


def test_exploratory_intent_does_not_mutate(monkeypatch, vault: Path) -> None:
    """Exploratory intent produces no generation, no write, note unchanged."""
    # Co-authoring stub is wired but must never be called on the exploratory path.
    generated = "# Hello\n\nSome generated body.\n"
    client = _make_client(
        monkeypatch,
        vault,
        generated,
        classifier_label=_exploratory_label(),
    )
    session_id = _open_session(client)
    original = (vault / "note.md").read_text(encoding="utf-8")

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/coauthor",
        json={"intent": "what does this note argue?"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "exploratory_no_edit"
    assert body["session_id"] == session_id
    # Note body is untouched.
    assert (vault / "note.md").read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# AC: body-frontmatter defense-in-depth still fires (backstop with FRONTMATTER_UPDATE)
# ---------------------------------------------------------------------------


def test_coauthor_governance_bearing_is_routed_not_applied(monkeypatch, vault: Path) -> None:
    """Defense-in-depth backstop fires when the generated body contains frontmatter.

    The classifier labels the intent CO_AUTHORING (e.g. "rewrite the body"),
    so the intent path does not route to Panel. But the co-authoring stub
    returns a frontmatter-bearing body — the backstop fires via
    ``GovernanceBearingMutationError`` and routes to Panel with the default
    ``frontmatter_update`` action type.
    """
    # The classifier labels this as co_authoring — intent path does not route.
    generated = "---\ntype: evergreen\n---\n\n# Hello\n\nRewritten body.\n"
    client = _make_client(
        monkeypatch,
        vault,
        generated,
        classifier_label=_co_authoring_label(),
    )
    session_id = _open_session(client)
    original = (vault / "note.md").read_text(encoding="utf-8")

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/coauthor",
        json={"intent": "rewrite the body"},
    )

    # Not applied in place; routed to the gated pipeline.
    assert resp.status_code == 409, resp.text
    assert (vault / "note.md").read_text(encoding="utf-8") == original
    body = resp.json()
    assert body["status"] == "routed_to_panel"
    # Defense-in-depth backstop uses the default frontmatter_update action type.
    assert body["action_type"] == "frontmatter_update"
    assert "detail" in body


def test_governance_bearing_returns_handoff_reference(monkeypatch, vault: Path) -> None:
    """Frontmatter-bearing generation from a co-authoring intent returns structured 409.

    This is the defense-in-depth backstop path: the classifier says co_authoring
    but the generation contains frontmatter, so the backstop fires. The returned
    handoff action_type is the backstop default ``frontmatter_update``.
    """
    generated = "---\ntype: evergreen\n---\n\n# Hello\n\nRewritten body.\n"
    client = _make_client(
        monkeypatch,
        vault,
        generated,
        classifier_label=_co_authoring_label(),
    )
    session_id = _open_session(client)

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/coauthor",
        json={"intent": "rewrite the body"},
    )

    assert resp.status_code == 409, resp.text
    body = resp.json()
    assert body["status"] == "routed_to_panel"
    assert isinstance(body["intent_id"], str) and body["intent_id"]
    assert body["action_type"] == "frontmatter_update"
    assert "detail" in body


# ---------------------------------------------------------------------------
# AC: degraded classifier falls through to existing generate path
# ---------------------------------------------------------------------------


def test_classifier_degraded_falls_through(monkeypatch, vault: Path) -> None:
    """A degraded classifier (classified=False) falls through to generate-and-apply.

    No fabricated governance routing — the path degrades gracefully to today's
    behavior (body generated and applied in place) when the classifier is
    unavailable.
    """
    generated = "# Hello\n\nBody after degraded classifier.\n"
    client = _make_client(
        monkeypatch,
        vault,
        generated,
        classifier_label=_degraded_label(),
    )
    session_id = _open_session(client)

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/coauthor",
        json={"intent": "expand the introduction"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["generated"] is True
    # The degraded-classifier path falls through to the apply path — note changed.
    note_text = (vault / "note.md").read_text(encoding="utf-8")
    assert "Body after degraded classifier." in note_text


# ---------------------------------------------------------------------------
# AC: path gated behind CANVAS_ENABLED
# ---------------------------------------------------------------------------


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
# Existing negative paths (still covered)
# ---------------------------------------------------------------------------


def test_coauthor_mock_generation_is_not_applied(monkeypatch, vault: Path) -> None:
    # A mock/degraded backend response from the co-authoring cognition must not
    # be written into the note. The classifier is degraded too (mock), so it
    # falls through — the co-author cognition raises CoAuthoringUnavailableError.
    generated = "MOCK_ASK_ANSWER: expand the decision section | context: ..."
    client = _make_client(
        monkeypatch,
        vault,
        generated,
        classifier_label=_degraded_label(),
    )
    session_id = _open_session(client)
    original = (vault / "note.md").read_text(encoding="utf-8")

    resp = client.post(
        f"/api/canvas/sessions/{session_id}/coauthor",
        json={"intent": "expand the decision section"},
    )

    assert resp.status_code == 503, resp.text
    assert (vault / "note.md").read_text(encoding="utf-8") == original
