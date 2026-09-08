from app.retrieval import hybrid
from app.retrieval.capability import RetrievalRequest, retrieve
from tests.retrieval.test_retrieval_capability import _patch_embeddings, _scoped_context
from app.retrieval.hybrid import get_store


def test_production_retrieval_preserves_binding_provenance(monkeypatch) -> None:
    _patch_embeddings(monkeypatch)
    class DurableIndex:
        def generation_for_bindings(self, _binding_ids=None):
            return "durable-generation-1"

        def all_rows_for_bindings(self, _binding_ids=None):
            return [
                {
                    "object_id": "wrong-binding",
                    "text": "needle needle needle needle",
                    "payload": {"domain": "core", "text": "needle needle needle needle"},
                    "vault_binding_id": "binding-b",
                    "embedding": [0.1, 0.1, 0.1],
                },
                {
                    "object_id": "legacy-unbound",
                    "text": "needle needle",
                    "payload": {"domain": "core", "text": "needle needle"},
                    "vault_binding_id": None,
                    "embedding": [0.1, 0.1, 0.1],
                },
                {
                    "object_id": "a",
                    "text": "needle",
                    "payload": {
                        "domain": "core",
                        "text": "needle",
                        "settings_bundle": "vault-a",
                    },
                    "vault_binding_id": "binding-a",
                    "embedding": [0.1, 0.1, 0.1],
                },
            ]

    monkeypatch.setattr("app.stores.get_vector_index", lambda: DurableIndex())
    hybrid.reset_durable_rebuild_state()
    hybrid.rebuild_from_durable_index(force=True)
    try:
        response = retrieve(
            RetrievalRequest(
                query="needle",
                k=1,
                scope="core",
                active_context=_scoped_context(),
                settings_bundle_digest="effective-vault-a",
            )
        )
        # Binding eligibility is applied before ranking/top-k: the high-scoring
        # other-binding and legacy rows cannot evict the selected row.
        assert [hit.doc_id for hit in response.hits] == ["a"]
        assert response.hits[0].payload["vault_binding_id"] == "binding-a"
        assert response.hits[0].payload["context_generation"] == 3
        assert response.metadata["provenance"]["active_context"]["rejected_unbound_hits"] == 2
        assert (
            response.metadata["provenance"]["active_context"]["cache_key"]
            != retrieve(
                RetrievalRequest(
                    query="needle",
                    k=1,
                    scope="core",
                    active_context=_scoped_context(),
                    settings_bundle_digest="effective-vault-b",
                )
            ).metadata["provenance"]["active_context"]["cache_key"]
        )
    finally:
        get_store().set_documents([])
