from __future__ import annotations

from app.llm.embeddings import embed_text


def test_mock_embeddings_respect_embed_dim(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "12")
    vec = embed_text("hello")
    assert len(vec) == 12
