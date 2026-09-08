from __future__ import annotations

from app.retrieval.capability import RetrievalRequest, RetrievalSignalPayload, retrieve
from app.retrieval.hybrid import get_store, hybrid_search
from app.vault.active_context_v1 import (
    ActiveContextBinding,
    ActiveContextSetV1,
    PrincipalContext,
    WorkspaceState,
)


def _scoped_context() -> ActiveContextSetV1:
    return ActiveContextSetV1(
        context_id="ctx-test",
        generation=3,
        workspace=WorkspaceState.none(),
        scope="core",
        sphere_memberships=(),
        situated_identity=None,
        principal_context=PrincipalContext("operator", "human", "trusted_loopback"),
        instance_identity="instance-test",
        source_bindings=(ActiveContextBinding("binding-a", 1, "epoch-a"),),
        registry_revision=1,
        authorization_epoch="epoch-a",
        selection_provenance="session_selection",
    )


def _patch_embeddings(monkeypatch) -> None:
    monkeypatch.setattr("app.retrieval.hybrid.embed_text", lambda text, language=None: [0.1, 0.1, 0.1])
    monkeypatch.setattr("app.retrieval.hybrid.embed_docs", lambda texts: ([[0.1, 0.1, 0.1] for _ in texts], {}))


def _seed_store() -> None:
    store = get_store()
    store.set_documents(
        [
            {
                "doc_id": "alpha",
                "text": "alpha retrieval capability current hybrid result",
                "source_ref": "vault/alpha.md",
                "payload": {"title": "Alpha", "origin": "vault", "domain": "core"},
            },
            {
                "doc_id": "beta",
                "text": "beta unrelated note",
                "source_ref": "vault/beta.md",
                "payload": {"title": "Beta", "origin": "vault", "domain": "core"},
            },
        ]
    )


def test_retrieval_capability_preserves_current_hybrid_results(monkeypatch) -> None:
    _patch_embeddings(monkeypatch)
    _seed_store()
    try:
        current = hybrid_search("alpha retrieval", k=2)
        response = retrieve(RetrievalRequest(query="alpha retrieval", k=2))

        assert [hit.doc_id for hit in response.hits] == [hit["doc_id"] for hit in current]
        assert [hit.score for hit in response.hits] == [hit["score"] for hit in current]
        assert response.hits[0].payload["title"] == current[0]["payload"]["title"]
    finally:
        get_store().set_documents([])


def test_scoped_retrieval_rejects_unbound_rows_and_preserves_binding_provenance(monkeypatch) -> None:
    _patch_embeddings(monkeypatch)
    store = get_store()
    store.set_documents(
        [
            {"doc_id": "a", "text": "bound", "payload": {"domain": "core", "vault_binding_id": "binding-a"}},
            {"doc_id": "b", "text": "unbound", "payload": {"domain": "core", "vault_binding_id": "binding-b"}},
            {"doc_id": "legacy", "text": "legacy", "payload": {"domain": "core"}},
        ]
    )
    try:
        response = retrieve(RetrievalRequest(query="bound", k=3, scope="core", active_context=_scoped_context()))
        assert [hit.doc_id for hit in response.hits] == ["a"]
        assert response.hits[0].payload["vault_binding_id"] == "binding-a"
        assert response.hits[0].payload["context_generation"] == 3
        assert response.metadata["provenance"]["active_context"]["rejected_unbound_hits"] == 2
    finally:
        store.set_documents([])


def test_ask_compatibility_metadata_survives_capability_adapter(monkeypatch) -> None:
    _patch_embeddings(monkeypatch)
    _seed_store()
    try:
        response = retrieve(RetrievalRequest(query="alpha retrieval", k=1, trace_id="trace-1"))

        hit = response.hits[0].to_hybrid_dict()
        assert hit["doc_id"] == "alpha"
        assert hit["id"] == "alpha"
        assert hit["source_ref"] == "vault/alpha.md"
        assert hit["payload"]["origin"] == "vault"
        assert response.diagnostics["trace_id"] == "trace-1"
    finally:
        get_store().set_documents([])


def test_retrieval_capability_accepts_surface_neutral_request(monkeypatch) -> None:
    # Since #2921 `RetrievalRequest.scope` is load-bearing at the prefilter rather than diagnostic
    # metadata, so it must name a scope the seeded corpus actually contains.
    _patch_embeddings(monkeypatch)
    _seed_store()
    try:
        response = retrieve(
            RetrievalRequest(
                query="alpha retrieval",
                k=1,
                scope="core",
                domain="core",
                trace_id="surface-neutral",
            )
        )

        assert response.query == "alpha retrieval"
        assert response.trace_id == "surface-neutral"
        assert response.diagnostics["scope"] == "core"
        assert response.diagnostics["active_scope"] == "core"
        assert response.diagnostics["domain"] == "core"
        assert response.hits
    finally:
        get_store().set_documents([])


def test_retrieval_contract_objects_are_surface_independent(monkeypatch) -> None:
    _patch_embeddings(monkeypatch)
    _seed_store()
    try:
        response = retrieve(
            RetrievalRequest(
                query="alpha retrieval",
                k=1,
                scope="core",
                domain="core",
                trace_id="contract-1",
            )
        )

        assert response.query == "alpha retrieval"
        assert response.trace_id == "contract-1"
        assert response.metadata["provenance"]["capability"] == "retrieval"
        assert response.metadata["provenance"]["adapter"] == "hybrid_search"
        assert response.metadata["provenance"]["request"] == {"scope": "core", "domain": "core"}
        assert response.hits
        assert response.hits[0].doc_id == "alpha"
    finally:
        get_store().set_documents([])


def test_retrieval_signal_payload_opt_in(monkeypatch) -> None:
    _patch_embeddings(monkeypatch)
    _seed_store()
    try:
        without_opt_in = retrieve(
            RetrievalRequest(
                query="alpha retrieval",
                k=1,
                signal_payload=RetrievalSignalPayload(
                    salience={"tier": "active"},
                    staleness={"state": "fresh"},
                    source="runtime",
                ),
            )
        )
        with_opt_in = retrieve(
            RetrievalRequest(
                query="alpha retrieval",
                k=1,
                include_signal_payload=True,
                signal_payload=RetrievalSignalPayload(
                    salience={"tier": "active"},
                    staleness={"state": "fresh"},
                    source="runtime",
                ),
            )
        )

        assert "signal_payload" not in without_opt_in.diagnostics
        assert with_opt_in.diagnostics["signal_payload"] == {
            "salience": {"tier": "active"},
            "staleness": {"state": "fresh"},
            "source": "runtime",
        }
    finally:
        get_store().set_documents([])
