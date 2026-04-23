from __future__ import annotations

from app.retrieval.capability import RetrievalRequest, RetrievalSignalPayload, retrieve
from app.retrieval.hybrid import get_store


def _patch_embeddings(monkeypatch) -> None:
    monkeypatch.setattr("app.retrieval.hybrid.embed_text", lambda text, language=None: [0.2, 0.2, 0.2])
    monkeypatch.setattr("app.retrieval.hybrid.embed_docs", lambda texts: ([[0.2, 0.2, 0.2] for _ in texts], {}))


def _seed_store() -> None:
    get_store().set_documents(
        [
            {
                "doc_id": "signal-a",
                "text": "signal seam note",
                "source_ref": "vault/signal-a.md",
                "payload": {
                    "title": "Signal A",
                    "origin": "vault",
                    "salience": "persisted-hot",
                    "staleness": "persisted-stale",
                    "review_state": "evergreen",
                    "maturity": "evergreen",
                },
            }
        ]
    )


def test_salience_signals_are_derived_not_persisted(monkeypatch) -> None:
    _patch_embeddings(monkeypatch)
    _seed_store()
    try:
        response = retrieve(
            RetrievalRequest(
                query="signal seam",
                k=1,
                include_signal_payload=True,
                signal_payload=RetrievalSignalPayload(
                    salience={"tier": "active", "reason": "runtime-derivation"},
                    staleness={"state": "fresh", "reason": "status-heartbeat"},
                    source="runtime",
                ),
            )
        )

        assert response.diagnostics["signal_payload"] == {
            "salience": {"tier": "active", "reason": "runtime-derivation"},
            "staleness": {"state": "fresh", "reason": "status-heartbeat"},
            "source": "runtime",
        }
        assert response.hits[0].payload["salience"] == "persisted-hot"
        assert response.hits[0].payload["staleness"] == "persisted-stale"
    finally:
        get_store().set_documents([])


def test_staleness_not_sourced_from_state_axes_labels(monkeypatch) -> None:
    _patch_embeddings(monkeypatch)
    _seed_store()
    try:
        response = retrieve(RetrievalRequest(query="signal seam", k=1))

        assert "signal_payload" not in response.diagnostics
        assert response.hits[0].payload["review_state"] == "evergreen"
        assert response.hits[0].payload["maturity"] == "evergreen"
    finally:
        get_store().set_documents([])
