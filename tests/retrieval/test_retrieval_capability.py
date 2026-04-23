from __future__ import annotations

from app.retrieval.capability import RetrievalRequest, RetrievalSignalPayload, retrieve
from app.retrieval.hybrid import get_store, hybrid_search


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
    _patch_embeddings(monkeypatch)
    _seed_store()
    try:
        response = retrieve(
            RetrievalRequest(
                query="alpha retrieval",
                k=1,
                scope="operator",
                domain="core",
                trace_id="surface-neutral",
            )
        )

        assert response.query == "alpha retrieval"
        assert response.trace_id == "surface-neutral"
        assert response.diagnostics["scope"] == "operator"
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
                scope="operator",
                domain="core",
                trace_id="contract-1",
            )
        )

        assert response.query == "alpha retrieval"
        assert response.trace_id == "contract-1"
        assert response.metadata["provenance"]["capability"] == "retrieval"
        assert response.metadata["provenance"]["adapter"] == "hybrid_search"
        assert response.metadata["provenance"]["request"] == {"scope": "operator", "domain": "core"}
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
