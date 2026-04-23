from __future__ import annotations

from app.retrieval.capability import RetrievalRequest, retrieve
from app.retrieval.hybrid import get_store


def _patch_embeddings(monkeypatch) -> None:
    monkeypatch.setattr("app.retrieval.hybrid.embed_text", lambda text, language=None: [0.2, 0.2, 0.2])
    monkeypatch.setattr("app.retrieval.hybrid.embed_docs", lambda texts: ([[0.2, 0.2, 0.2] for _ in texts], {}))


def _seed_store() -> None:
    get_store().set_documents(
        [
            {
                "doc_id": "first",
                "text": "relation provenance metadata first",
                "source_ref": "vault/first.md",
                "payload": {"title": "First", "origin": "vault"},
            },
            {
                "doc_id": "second",
                "text": "relation provenance metadata second",
                "source_ref": "vault/second.md",
                "payload": {"title": "Second", "origin": "vault"},
            },
        ]
    )


def test_retrieval_propagates_relation_and_provenance_metadata(monkeypatch) -> None:
    _patch_embeddings(monkeypatch)
    _seed_store()
    try:
        response = retrieve(
            RetrievalRequest(
                query="relation provenance",
                relation_metadata={"candidate_relation_ids": ["rel-1"], "source": "test"},
                provenance_metadata={"source_refs": ["vault/first.md"], "requested_by": "chat"},
            )
        )

        assert response.diagnostics["relation_metadata"] == {
            "candidate_relation_ids": ["rel-1"],
            "source": "test",
        }
        assert response.diagnostics["provenance_metadata"] == {
            "source_refs": ["vault/first.md"],
            "requested_by": "chat",
        }
    finally:
        get_store().set_documents([])


def test_relation_provenance_inputs_do_not_change_ranking(monkeypatch) -> None:
    _patch_embeddings(monkeypatch)
    _seed_store()
    try:
        baseline = retrieve(RetrievalRequest(query="relation provenance", k=2))
        with_metadata = retrieve(
            RetrievalRequest(
                query="relation provenance",
                k=2,
                relation_metadata={"prefer": ["second"]},
                provenance_metadata={"prefer": ["vault/second.md"]},
            )
        )

        assert [hit.doc_id for hit in with_metadata.hits] == [hit.doc_id for hit in baseline.hits]
    finally:
        get_store().set_documents([])


def test_missing_relation_provenance_metadata_preserves_current_behavior(monkeypatch) -> None:
    _patch_embeddings(monkeypatch)
    _seed_store()
    try:
        response = retrieve(RetrievalRequest(query="relation provenance", k=1))

        assert "relation_metadata" not in response.diagnostics
        assert "provenance_metadata" not in response.diagnostics
        assert response.hits
    finally:
        get_store().set_documents([])


def test_retrieval_response_contains_temporal_validity_flags(monkeypatch) -> None:
    _patch_embeddings(monkeypatch)
    _seed_store()
    try:
        stale = retrieve(
            RetrievalRequest(
                query="relation provenance",
                k=1,
                provenance_metadata={"requested_by": "ask"},
            )
        )
        assert stale.metadata["temporal_validity"] == {
            "state": "unknown",
            "is_fresh": False,
            "is_stale": False,
            "is_partial": False,
            "is_unknown": True,
        }
        assert stale.metadata["provenance"]["hints"] == {"requested_by": "ask"}
    finally:
        get_store().set_documents([])
