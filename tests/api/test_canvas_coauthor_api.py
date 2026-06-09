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


def _make_client(monkeypatch, vault: Path, generated_body: str) -> TestClient:
    monkeypatch.setenv("CANVAS_ENABLED", "1")
    monkeypatch.setattr(canvas_module, "_get_vault_root", lambda: vault)
    facade = _StubFacade(generated_body)
    monkeypatch.setattr(
        canvas_module, "_coauthor_facade_factory", lambda: facade
    )
    return TestClient(app)


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


def test_coauthor_requires_canvas_enabled(monkeypatch, vault: Path) -> None:
    monkeypatch.setenv("CANVAS_ENABLED", "0")
    monkeypatch.setattr(canvas_module, "_get_vault_root", lambda: vault)
    client = TestClient(app)
    resp = client.post(
        "/api/canvas/sessions/any-session/coauthor",
        json={"intent": "do something"},
    )
    assert resp.status_code == 403
