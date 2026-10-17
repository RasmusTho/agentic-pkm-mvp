"""MVR-05B4a (#6160): the ask graph runs on the request's ActiveContextSet.

Drives the production ``/api/ask/scoped`` route with the real ask graph: the
selection carrier resolves one immutable context, ``run_ask_graph`` fixes the
turn's recall sources from it once, and no node resolves a vault globally. A
selection change while the graph runs does not move the turn to another binding.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agents.ask import graph as ask_graph
from app.api.app import app
from app.api.routes import active_context_selection as selection_routes
from app.api.routes import ask as ask_routes
from tests._mvr03_principal_harness import provisioned_instance

SELECTION_URL = "/api/companion/active-context/selection"


@pytest.fixture()
def instance(tmp_path, monkeypatch):
    runtime, first, extra, record = provisioned_instance(tmp_path, extra_roots=("two",))
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(runtime.layout.registry_path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(runtime.ledger.root))
    monkeypatch.setenv("RECALL_RECEIPTS_PATH", str(tmp_path / "recall.jsonl"))
    selection_routes.reset_selection_store_for_tests()
    import app.vault.manager as vault_manager_module

    monkeypatch.setattr(vault_manager_module, "_GLOBAL_MANAGER", None)
    return runtime, first, extra[0]


def test_ask_graph_uses_request_context_without_global_lookup(instance, monkeypatch) -> None:
    _runtime, first, second = instance
    client = TestClient(app)
    created = client.post(SELECTION_URL, json={"vault_binding_ids": [first.vault_binding_id]})
    assert created.status_code == 201, created.text
    bearer = created.json()["context_selection_id"]

    def _no_global_lookup(*_args, **_kwargs):
        raise AssertionError("a scoped ask turn consulted the process-global vault selection")

    # Every global resolver the graph module can reach is poisoned for this turn.
    monkeypatch.setattr(ask_graph, "get_vault_manager", _no_global_lookup)
    monkeypatch.setattr(ask_graph, "resolve_optional_vault_root", _no_global_lookup)
    monkeypatch.setattr(ask_graph, "compatibility_recall_sources", _no_global_lookup)

    retrieval_contexts: list[object] = []
    switched: list[int] = []

    def _retrieve(request):  # type: ignore[no-untyped-def]
        retrieval_contexts.append(request.active_context)
        # The human re-selects the session while this turn is in flight.
        switch = client.put(
            SELECTION_URL,
            json={"vault_binding_ids": [second.vault_binding_id]},
            headers={"X-Active-Context-Session": bearer},
        )
        assert switch.status_code == 200, switch.text
        switched.append(switch.json()["context"]["generation"])
        return SimpleNamespace(hits=[], metadata={}, denials=())

    recall_roots: list[tuple[Path | None, str | None]] = []

    def _recall(_query, *, k, vault_root, active_scope_id, active_vault_id):  # type: ignore[no-untyped-def]
        recall_roots.append((vault_root, active_vault_id))
        return []

    monkeypatch.setattr(ask_graph, "retrieve", _retrieve)
    monkeypatch.setattr(ask_graph, "retrieve_relevant_promoted", _recall)
    monkeypatch.setattr(ask_graph, "retrieve_relevant_provisional", lambda *_a, **_k: None)
    monkeypatch.setattr(
        ask_graph, "llm_answer", lambda *_a, **_k: ("answer", {"provider": "test"})
    )
    monkeypatch.setattr(ask_routes, "_ensure_hybrid_store_loaded", lambda: None)

    response = client.post(
        "/api/ask/scoped",
        json={"question": "which vault?"},
        headers={"X-Active-Context-Session": bearer},
    )

    assert response.status_code == 200, response.text
    assert switched == [2]
    # Retrieval received the request's context, generation 1 for the first binding.
    (context,) = retrieval_contexts
    assert context is not None
    assert context.binding_ids == (first.vault_binding_id,)
    assert context.generation == 1
    # Recall ran after the switch and still read the request's own binding root.
    assert recall_roots == [(Path(first.path).resolve(), first.vault_id)]

    # The switch is real: the next request on the same session resolves the new binding.
    retrieval_contexts.clear()
    recall_roots.clear()
    monkeypatch.setattr(
        ask_graph,
        "retrieve",
        lambda request: retrieval_contexts.append(request.active_context)
        or SimpleNamespace(hits=[], metadata={}, denials=()),
    )
    again = client.post(
        "/api/ask/scoped",
        json={"question": "which vault now?"},
        headers={"X-Active-Context-Session": bearer},
    )
    assert again.status_code == 200, again.text
    (later,) = retrieval_contexts
    assert later.binding_ids == (second.vault_binding_id,)
    assert later.generation == 2
    assert recall_roots == [(Path(second.path).resolve(), second.vault_id)]


def test_ask_graph_resolves_recall_sources_once_before_nodes_run(monkeypatch) -> None:
    """The carrier-free turn resolves its compatibility source once, before the graph."""

    calls: list[str | None] = []

    def _sources(scope):  # type: ignore[no-untyped-def]
        calls.append(scope)
        return (ask_graph.RecallSource(root=None, vault_id=None),)

    monkeypatch.setattr(ask_graph, "compatibility_recall_sources", _sources)
    monkeypatch.setattr(
        ask_graph, "retrieve", lambda _r: SimpleNamespace(hits=[], metadata={}, denials=())
    )
    monkeypatch.setattr(ask_graph, "retrieve_relevant_promoted", lambda *_a, **_k: [])
    monkeypatch.setattr(ask_graph, "llm_answer", lambda *_a, **_k: ("answer", {}))
    monkeypatch.setattr(
        ask_graph,
        "get_vault_manager",
        lambda: pytest.fail("a node resolved the vault after the turn's sources were fixed"),
    )

    ask_graph.run_ask_graph("anything", active_scope="scope-a")

    assert calls == ["scope-a"]
