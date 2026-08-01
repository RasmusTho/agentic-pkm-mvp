"""Per-request active-scope binding activates the scope prefilter in production (#2921).

KERNEL-10 (#2772) delivered the prefilter MECHANISM; these tests bind its ACTIVATION half:

- ``test_ask_request_scope_excludes_out_of_scope_material`` — the production ``/api/ask``
  entrypoint binds the caller's active scope, so ``_partition_by_scope`` actually partitions.
  ``ASK_DOMAIN_SCOPE`` is deliberately absent: the scope must arrive through the request path.
- ``test_ambient_env_scope_remains_process_default`` — with no request-bound scope, the ambient
  ``ASK_DOMAIN_SCOPE`` still resolves, so existing callers and eval harnesses are unaffected.
- ``test_evidence_role_in_context_survives_capability_boundary`` — the per-hit in-context evidence
  role crosses ``RetrievalHit`` instead of being dropped, and the clamp stays non-upgrading.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.retrieval.hybrid as hybrid
from app.agents.ask import graph as ask_graph
from app.api.app import app
from app.retrieval.capability import RetrievalHit, RetrievalRequest, retrieve
from app.retrieval.hybrid import get_store


@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch):
    """Clean store around every test, so scope decides membership rather than leftover state."""
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    yield
    get_store().set_documents([])


def _seed_two_scopes() -> None:
    store = get_store()
    store.set_documents([])
    store.add_document(
        doc_id="work-1",
        text="stateful workflow engine event bus reconciliation",
        source_ref="work/arch.md",
        payload={"domain": "work", "title": "Work arch", "origin": "vault"},
    )
    store.add_document(
        doc_id="private-1",
        # Deliberately shares vocabulary with the work doc so similarity alone cannot separate
        # them: only the scope prefilter can keep it out of a work-scoped answer.
        text="stateful workflow engine event bus reconciliation therapy journal",
        source_ref="private/journal.md",
        payload={"domain": "private", "title": "Private journal", "origin": "vault"},
    )


def _spy_partition(monkeypatch) -> list[str | None]:
    """Record every scope value ``_partition_by_scope`` is actually invoked with."""
    seen: list[str | None] = []
    original = hybrid._partition_by_scope

    def _spy(docs, scope):
        seen.append(scope)
        return original(docs, scope)

    monkeypatch.setattr(hybrid, "_partition_by_scope", _spy)
    return seen


def test_ask_request_scope_excludes_out_of_scope_material(monkeypatch) -> None:
    """The PRODUCTION request path binds the active scope — not an injected ``ASK_DOMAIN_SCOPE``.

    This is the enforcement AC: the guard (``_partition_by_scope``) must be reached from the real
    runtime entrypoint (``app.api.routes.ask``) carrying the caller's scope, and the out-of-scope
    material must be absent from the answer's grounded sources.
    """
    monkeypatch.delenv("ASK_DOMAIN_SCOPE", raising=False)
    _seed_two_scopes()
    seen = _spy_partition(monkeypatch)

    captured: dict[str, dict] = {}
    original_assemble = ask_graph.assemble_and_validate_ask_envelope

    def _spy_assemble(scoped, **kwargs):
        envelope = original_assemble(scoped, **kwargs)
        captured["envelope"] = envelope
        captured["kwargs"] = kwargs
        return envelope

    monkeypatch.setattr(ask_graph, "retrieve_relevant_promoted", lambda *a, **k: [])
    monkeypatch.setattr(ask_graph, "assemble_and_validate_ask_envelope", _spy_assemble)
    monkeypatch.setattr(
        ask_graph, "llm_answer", lambda question, context, ask_settings: ("In scope.", {"provider": "mock"})
    )

    client = TestClient(app)
    response = client.post(
        "/api/ask", json={"question": "stateful workflow engine", "scope": "work"}
    )

    assert response.status_code == 200
    # The guard ran on the live path with the REQUEST-bound scope, with no ambient env var to
    # supply it. Without the binding this list is all-``None`` and the prefilter is a no-op.
    assert seen, "the scope prefilter must be reached from the production ASK entrypoint"
    assert set(seen) == {"work"}, f"expected the request-bound scope at the guard, saw {seen}"

    source_paths = {source.get("path") for source in response.json()["sources"]}
    assert "private/journal.md" not in source_paths, "out-of-scope material reached the answer"
    assert "work/arch.md" in source_paths

    # The envelope's declared active scope and the scope the prefilter used must not diverge.
    assert captured["kwargs"]["active_scope_id"] == "work"


def test_ambient_env_scope_remains_process_default(monkeypatch) -> None:
    """``ASK_DOMAIN_SCOPE`` stays supported as the process-level default.

    A request that binds no scope must keep resolving the ambient env var, so
    ``tests/evals/_app_adapter.py``, ``tests/boundaries/`` and ``app/eval/golden.py`` keep their
    current semantics rather than silently losing their scope.
    """
    monkeypatch.setenv("ASK_DOMAIN_SCOPE", "work")
    _seed_two_scopes()
    seen = _spy_partition(monkeypatch)

    monkeypatch.setattr(ask_graph, "retrieve_relevant_promoted", lambda *a, **k: [])
    monkeypatch.setattr(
        ask_graph, "llm_answer", lambda question, context, ask_settings: ("In scope.", {"provider": "mock"})
    )

    client = TestClient(app)
    response = client.post("/api/ask", json={"question": "stateful workflow engine"})

    assert response.status_code == 200
    assert set(seen) == {"work"}, f"ambient env scope must still reach the guard, saw {seen}"
    source_paths = {source.get("path") for source in response.json()["sources"]}
    assert "private/journal.md" not in source_paths

    # The capability seam honours the same default when the request carries no scope.
    assert retrieve(RetrievalRequest(query="stateful workflow engine")).hits


def test_evidence_role_in_context_survives_capability_boundary(monkeypatch) -> None:
    """The per-hit in-context evidence role crosses ``RetrievalHit`` and never upgrades.

    Before #2921 ``from_hybrid``/``to_hybrid_dict`` dropped the field, so the production ASK path
    always handed the envelope ``None`` and the clamp fell back to the intrinsic default.
    """
    monkeypatch.delenv("ASK_DOMAIN_SCOPE", raising=False)
    store = get_store()
    store.set_documents([])
    store.add_document(
        doc_id="explicit-evidence",
        text="stateful workflow engine event bus reconciliation",
        source_ref="work/evidence.md",
        payload={"domain": "work", "evidence_role": "evidence"},
    )
    store.add_document(
        doc_id="background-default",
        text="stateful workflow engine event bus reconciliation notes",
        source_ref="work/background.md",
        payload={"domain": "work"},
    )

    response = retrieve(RetrievalRequest(query="stateful workflow engine", k=5, scope="work"))
    by_id = {hit.doc_id: hit for hit in response.hits}
    assert by_id, "retrieval must return the in-scope hits"

    for doc_id, hit in by_id.items():
        # The field survived the boundary at all — this is what used to be dropped.
        assert hit.evidence_role_in_context is not None, f"{doc_id} lost its in-context role"
        # ...and it survives the round trip back out to the dict projection the ASK graph reads.
        assert hit.to_hybrid_dict()["evidence_role_in_context"] == hit.evidence_role_in_context

    order = ["background", "supporting", "evidence"]
    assert by_id["explicit-evidence"].evidence_role_in_context == "evidence"
    assert by_id["background-default"].evidence_role_in_context == "background"

    # Fail-safe discipline: the seam may lower a role, never raise it above the intrinsic one.
    upgraded = RetrievalHit.from_hybrid(
        {
            "id": "background-default",
            "doc_id": "background-default",
            "text": "body",
            "score": 0.5,
            "snippet": "body",
            "source_ref": "work/background.md",
            "payload": {"domain": "work"},
            "evidence_role_in_context": "evidence",
        }
    )
    assert upgraded.evidence_role_in_context == "background", "the clamp must never upgrade a role"
    assert order.index(upgraded.evidence_role_in_context) <= order.index("background")
