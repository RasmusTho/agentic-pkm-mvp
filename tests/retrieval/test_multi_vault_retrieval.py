from app.retrieval.capability import RetrievalRequest, retrieve
from tests.retrieval.test_retrieval_capability import _patch_embeddings, _scoped_context
from app.retrieval.hybrid import get_store


def test_production_retrieval_preserves_binding_provenance(monkeypatch) -> None:
    _patch_embeddings(monkeypatch)
    get_store().set_documents([{"doc_id": "a", "text": "a", "payload": {"domain": "core", "vault_binding_id": "binding-a"}}])
    try:
        response = retrieve(RetrievalRequest(query="a", k=1, scope="core", active_context=_scoped_context()))
        assert response.hits[0].payload["vault_binding_id"] == "binding-a"
        assert response.hits[0].payload["context_generation"] == 3
    finally:
        get_store().set_documents([])


def test_scoped_binding_eligibility_precedes_top_k(monkeypatch) -> None:
    _patch_embeddings(monkeypatch)
    get_store().set_documents(
        [
            {"doc_id": "foreign", "text": "needle needle", "payload": {"domain": "core", "vault_binding_id": "binding-b"}},
            {"doc_id": "selected", "text": "needle", "payload": {"domain": "core", "vault_binding_id": "binding-a"}},
        ]
    )
    try:
        response = retrieve(RetrievalRequest(query="needle", k=1, scope="core", active_context=_scoped_context()))
        assert [hit.doc_id for hit in response.hits] == ["selected"]
    finally:
        get_store().set_documents([])
