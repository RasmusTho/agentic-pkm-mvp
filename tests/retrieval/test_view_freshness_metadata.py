from __future__ import annotations

from app.retrieval.capability import RetrievalRequest, RetrievalViewFreshness, retrieve
from app.retrieval.hybrid import get_store


def _patch_embeddings(monkeypatch) -> None:
    monkeypatch.setattr("app.retrieval.hybrid.embed_text", lambda text, language=None: [0.3, 0.3, 0.3])
    monkeypatch.setattr("app.retrieval.hybrid.embed_docs", lambda texts: ([[0.3, 0.3, 0.3] for _ in texts], {}))


def _seed_store() -> None:
    get_store().set_documents(
        [
            {"doc_id": "a", "text": "freshness metadata alpha", "source_ref": "a.md", "payload": {}},
            {"doc_id": "b", "text": "freshness metadata beta", "source_ref": "b.md", "payload": {}},
        ]
    )


def test_retrieval_adds_view_freshness_without_reordering_results(monkeypatch) -> None:
    _patch_embeddings(monkeypatch)
    _seed_store()
    try:
        baseline = retrieve(RetrievalRequest(query="freshness metadata", k=2))
        with_freshness = retrieve(
            RetrievalRequest(
                query="freshness metadata",
                k=2,
                view_freshness=RetrievalViewFreshness(
                    state="partial",
                    reason="worker queue has pending runtime changes",
                    source="status",
                ),
            )
        )

        assert [hit.doc_id for hit in with_freshness.hits] == [hit.doc_id for hit in baseline.hits]
        assert with_freshness.diagnostics["view_freshness"] == {
            "state": "partial",
            "reason": "worker queue has pending runtime changes",
            "source": "status",
        }
    finally:
        get_store().set_documents([])


def test_missing_freshness_signal_reports_unknown_view(monkeypatch) -> None:
    _patch_embeddings(monkeypatch)
    _seed_store()
    try:
        response = retrieve(
            RetrievalRequest(
                query="freshness metadata",
                k=1,
                view_freshness=RetrievalViewFreshness(state="unknown", reason="no signal"),
            )
        )

        assert response.diagnostics["view_freshness"]["state"] == "unknown"
        assert response.hits
    finally:
        get_store().set_documents([])
