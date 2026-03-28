from __future__ import annotations

from app.llm.embeddings import embed_text


def test_mock_embeddings_do_not_require_model_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_EMBED_MODEL", raising=False)
    monkeypatch.setenv("EMBED_DIM", "4")

    vector = embed_text("mock input", normalize=False)

    assert len(vector) == 4
