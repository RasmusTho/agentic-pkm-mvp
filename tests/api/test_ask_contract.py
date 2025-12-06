from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.app import app
from app.api.routes import ask as ask_module
from app.retrieval.hybrid import get_store


def test_ask_contract_structure(monkeypatch) -> None:
    # Minimal embeddings stub to keep determinism
    monkeypatch.setattr("app.retrieval.hybrid.embed_text", lambda text, language=None: [0.1, 0.1, 0.1])
    monkeypatch.setattr(
        "app.retrieval.hybrid.embed_batches",
        lambda texts, batch_size=32: ([[0.1, 0.1, 0.1] for _ in list(texts[:batch_size])],),
    )

    hybrid = get_store()
    hybrid.set_documents(
        [
            {
                "doc_id": "contract-1",
                "text": "Reality-MVP contract note for API structure testing.",
                "source_ref": "tests/fixtures/reality_mvp/demo_note.md",
                "payload": {"origin": "vault", "zone": "hot", "trust": "own_raw", "title": "Contract"},
            }
        ]
    )
    ask_module._HYBRID_WARMED = True
    client = TestClient(app)
    try:
        resp = client.post("/api/ask", json={"question": "contract structure"})
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data.get("answer"), str)
        assert data["answer"].strip() != ""
        sources = data.get("sources")
        assert isinstance(sources, list)
        assert sources, "Expected at least one source"
        hit = sources[0]
        assert isinstance(hit.get("uuid"), str)
        assert isinstance(hit.get("origin"), str)
        assert "path" in hit
        if hit.get("zone") is not None:
            assert isinstance(hit.get("zone"), str)
        if hit.get("title") is not None:
            assert isinstance(hit.get("title"), str)
    finally:
        hybrid.set_documents([])
        ask_module._HYBRID_WARMED = False
