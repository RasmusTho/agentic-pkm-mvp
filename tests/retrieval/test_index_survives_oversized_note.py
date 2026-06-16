from __future__ import annotations

import numpy as np

import app.components.retrieval as retrieval_module
from app.components.embeddings import EmbeddingIdentity
from app.index import embeddings as index_emb
from app.llm import embeddings as emb
from app.retrieval.hybrid import MemoryHybridStore


def test_oversized_note_does_not_abort_index(monkeypatch) -> None:
    """An index build over a corpus containing one oversized note completes:
    the oversized note is chunked, the rest embed, and the whole build does not
    abort with the provider 500 (#2110).
    """
    dim = 8
    max_chars = 100
    monkeypatch.setenv("EMBED_MAX_INPUT_CHARS", str(max_chars))
    monkeypatch.setenv("LLM_TIMEOUT", "5")

    def fake_embed_api(text, model, d, timeout):
        # Mirror the real failure: a whole oversized note 500s; in-window
        # chunks succeed.
        if len(text) > max_chars:
            raise RuntimeError(
                "Ollama /api/embeddings returned HTTP 500: the input length exceeds the context length"
            )
        return tuple(0.1 for _ in range(d))

    monkeypatch.setattr(emb, "_ollama_embed_api", fake_embed_api)
    emb._embed_single.cache_clear()

    # Force the retrieval index build down the ollama embedding path without
    # depending on settings/profile resolution.
    identity = EmbeddingIdentity(provider="ollama", model="nomic-embed-text:latest", dim=dim, normalize=True)

    class _OllamaStubClient:
        def __init__(self) -> None:
            self.identity = identity

        def embed_text(self, text: str) -> list[float]:
            return index_emb.embed_text(
                text, provider="ollama", model=identity.model, dim=dim, normalize=True
            )

        def embed_texts(self, texts):
            return [self.embed_text(t) for t in texts]

        def embed_batches(self, texts, batch_size: int = 32):
            yield self.embed_texts(list(texts))

    monkeypatch.setattr(retrieval_module, "get_embedding_client", lambda *a, **k: _OllamaStubClient())

    store = MemoryHybridStore()
    store.set_documents(
        [
            {"doc_id": "apples", "text": "a short note about apples"},
            {"doc_id": "oversized", "text": "y" * 1000},  # 10x the window
            {"doc_id": "bananas", "text": "a short note about bananas"},
        ]
    )

    # _ensure_indexes() runs inside embedding_scores(); it must not raise.
    scores = store.embedding_scores(np.array([0.1] * dim, dtype=np.float32))

    assert store._embeddings is not None
    assert store._embeddings.shape[0] == 3, "all three docs (incl. the oversized one) embedded"
    assert scores.shape[0] == 3
    emb._embed_single.cache_clear()
