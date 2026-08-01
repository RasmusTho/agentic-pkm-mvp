"""Per-request active-scope binding activates the scope prefilter in production (#2921).

KERNEL-10 (#2772) delivered the prefilter MECHANISM; these tests bind its ACTIVATION half:

- ``test_ask_request_scope_excludes_out_of_scope_material`` — the production ``/api/ask``
  entrypoint binds the caller's active scope, so ``_partition_by_scope`` actually partitions.
  ``ASK_DOMAIN_SCOPE`` is deliberately absent: the scope must arrive through the request path.
- ``test_ambient_env_scope_remains_process_default`` — with no request-bound scope, the ambient
  ``ASK_DOMAIN_SCOPE`` still resolves, so existing callers and eval harnesses are unaffected.
- ``test_unmatched_bound_scope_admits_nothing_and_denies`` — a scope no document matches starves
  the result set and records a denial; it never falls back to admit-all.
- ``test_evidence_role_in_context_survives_capability_boundary`` — the per-hit in-context evidence
  role crosses ``RetrievalHit`` instead of being dropped, and the clamp stays non-upgrading.
- ``test_request_scope_overrides_ambient_env_scope`` — PRECEDENCE: a request binding REPLACES
  ``ASK_DOMAIN_SCOPE``. It narrows only relative to the UNSCOPED default, so the env var is a
  default and not a containment control. Pinned so the property is deliberate and visible.
- ``test_recall_node_uses_request_bound_scope`` — the recall leg of the no-divergence invariant:
  the recall node consumes the turn's bound scope rather than re-resolving the ambient default.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.retrieval.hybrid as hybrid
from app.agents.ask import graph as ask_graph
from app.agents.ask.state import AgentState
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


def test_unmatched_bound_scope_admits_nothing_and_denies(monkeypatch) -> None:
    """A bound scope no document matches admits NOTHING and records a content-free denial.

    The fail-safe direction: an unmatched scope must starve the result set rather than fall back to
    admit-all. Whitespace around the scope is normalized, so `" work "` cannot silently become an
    unmatchable scope.
    """
    monkeypatch.delenv("ASK_DOMAIN_SCOPE", raising=False)
    _seed_two_scopes()

    unmatched = retrieve(RetrievalRequest(query="stateful workflow engine", k=5, scope="operator"))
    assert unmatched.hits == [], "an unmatched bound scope must not fall back to admit-all"
    assert unmatched.denials, "relevant excluded material must be recorded, never silently dropped"
    assert {d.denial_class for d in unmatched.denials} == {"cross_scope_no_flow"}
    assert unmatched.diagnostics["active_scope"] == "operator"

    padded = retrieve(RetrievalRequest(query="stateful workflow engine", k=5, scope="  work  "))
    assert {hit.doc_id for hit in padded.hits} == {"work-1"}
    assert padded.diagnostics["active_scope"] == "work"


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


def test_request_scope_overrides_ambient_env_scope(monkeypatch) -> None:
    """PRECEDENCE, pinned deliberately: a request binding REPLACES `ASK_DOMAIN_SCOPE`.

    The binding narrows only relative to the UNSCOPED default. It does not narrow within a
    configured ambient scope — it overrides it, so `ASK_DOMAIN_SCOPE` is a default and NOT a
    containment control. This test exists so that property is visible and deliberate rather than an
    unstated consequence of the resolution order; see
    `docs/RUNTIME_CORRECTNESS_KERNEL/RUNTIME_SCOPE_PREFILTER_AND_ENVELOPE.md :: Activation in Production`.
    """
    monkeypatch.setenv("ASK_DOMAIN_SCOPE", "work")
    _seed_two_scopes()
    seen = _spy_partition(monkeypatch)

    monkeypatch.setattr(ask_graph, "retrieve_relevant_promoted", lambda *a, **k: [])
    monkeypatch.setattr(
        ask_graph, "llm_answer", lambda question, context, ask_settings: ("Bound.", {"provider": "mock"})
    )

    client = TestClient(app)
    response = client.post(
        "/api/ask", json={"question": "stateful workflow engine", "scope": "private"}
    )

    assert response.status_code == 200
    # The REQUEST scope wins outright; the ambient "work" never reaches the guard.
    assert set(seen) == {"private"}, f"request binding must override the ambient default, saw {seen}"
    source_paths = {source.get("path") for source in response.json()["sources"]}
    assert source_paths == {"private/journal.md"}, (
        "the request-bound partition is served, not the ambient one -- if this ever needs to be a "
        "ceiling instead of an override, make the precedence intersecting"
    )


def test_recall_node_uses_request_bound_scope(monkeypatch) -> None:
    """The recall leg of the no-divergence invariant.

    `_recall_node` must consume the SAME scope retrieval used, not re-resolve the ambient default.
    Without this, provisional memory from the ambient scope could be recalled into a turn the
    caller bound to a different scope.
    """
    monkeypatch.setenv("ASK_DOMAIN_SCOPE", "work")
    _seed_two_scopes()

    seen_scopes: list[str | None] = []

    def _spy_provisional(query, *, k, vault_root, receipt_store, active_scope_id):
        seen_scopes.append(active_scope_id)
        return None

    monkeypatch.setattr(ask_graph, "retrieve_relevant_promoted", lambda *a, **k: [])
    monkeypatch.setattr(ask_graph, "retrieve_relevant_provisional", _spy_provisional)
    monkeypatch.setattr(ask_graph, "_active_recall_vault_root", lambda: Path("/nonexistent-vault"))

    state = ask_graph._recall_node(  # noqa: SLF001 - production node proof
        AgentState(query="stateful workflow engine", active_scope="private"),
        ask_settings=object(),
    )

    assert state is not None
    assert seen_scopes == ["private"], (
        f"recall must use the turn's bound scope, not the ambient default, saw {seen_scopes}"
    )
