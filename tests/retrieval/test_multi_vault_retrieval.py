from app.retrieval.capability import RetrievalRequest, retrieve
from tests.retrieval.test_retrieval_capability import _patch_embeddings, _scoped_context
from app.retrieval.hybrid import get_store


def test_production_retrieval_preserves_binding_provenance(monkeypatch) -> None:
    _patch_embeddings(monkeypatch)
    get_store().set_documents(
        [
            {
                "doc_id": "wrong-binding",
                "text": "needle needle needle needle",
                "payload": {
                    "domain": "core",
                    "vault_binding_id": "binding-b",
                },
            },
            {
                "doc_id": "legacy-unbound",
                "text": "needle needle",
                "payload": {"domain": "core"},
            },
            {
                "doc_id": "a",
                "text": "needle",
                "payload": {
                    "domain": "core",
                    "vault_binding_id": "binding-a",
                    "settings_bundle": "vault-a",
                },
            },
        ]
    )
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
