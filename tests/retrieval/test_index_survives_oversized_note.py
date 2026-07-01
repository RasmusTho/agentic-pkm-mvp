from __future__ import annotations

import httpx
import numpy as np
import pytest

import app.components.retrieval as retrieval_module
import app.llm.embeddings as emb
from app.components.embeddings import EmbeddingIdentity
from app.index import embeddings as index_emb
from app.ingest.chunk_policy import build_structural_chunks
from app.llm.embeddings import embed_texts
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


def test_failing_note_degraded_to_zero_vector(monkeypatch) -> None:
    """A note that still trips the provider's context limit on every chunk/endpoint
    is degraded (skipped with a warning, substituted with a zero vector) rather
    than aborting the whole batch (#2110).

    This guards the ``embed_texts`` safety net that backstops chunking: even when
    a note cannot be embedded at all, the surrounding index build completes.
    """
    for key in ("OLLAMA_BASE_URL", "OLLAMA_URL", "OLLAMA_HOST", "OPENAI_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_HOST", "https://ollama.local:11434/")
    monkeypatch.setenv("EMBED_DIM", "3")
    monkeypatch.setenv("EMBED_MODEL", "nomic-embed-text:latest")
    # Disable chunking so the poison note reaches the provider whole and triggers
    # the per-item degradation path rather than being split.
    monkeypatch.setenv("EMBED_MAX_INPUT_CHARS", "0")

    poison = "POISON-NOTE"

    def fake_post(url: str, json: dict[str, object], timeout: float):
        prompt = json.get("prompt") or json.get("input")
        if isinstance(prompt, str) and poison in prompt:
            # Both the native and the OpenAI-fallback endpoint 500 for this note.
            raise httpx.HTTPStatusError(
                "input length exceeds the context length",
                request=httpx.Request("POST", url),
                response=httpx.Response(500, request=httpx.Request("POST", url)),
            )

        class DummyResponse:
            is_error = False
            status_code = 200

            def json(self) -> dict[str, object]:
                return {"embeddings": [[1, 2, 3]]}

        return DummyResponse()

    monkeypatch.setattr("app.llm.embeddings.httpx.post", fake_post)
    emb._embed_single.cache_clear()

    corpus = ["healthy note one", poison, "healthy note two"]
    vectors = embed_texts(corpus, provider="ollama", normalize=False)

    assert len(vectors) == len(corpus)
    # Healthy notes embed normally.
    assert vectors[0] == [1.0, 2.0, 3.0]
    assert vectors[2] == [1.0, 2.0, 3.0]
    # The poison note is degraded to a zero vector of the correct dimension,
    # not an exception that aborts the build.
    assert vectors[1] == [0.0, 0.0, 0.0]
    emb._embed_single.cache_clear()


def test_oversized_note_chunks(monkeypatch) -> None:
    """The structural chunker's chunk boundaries (issue #2323) reconcile
    cleanly with the independent oversized-input mean-pooling defense in
    ``app.llm.embeddings._embed_single`` (#2110): a structural chunk that is
    itself still over the embedding provider's window is mean-pooled the same
    way a whole oversized note is, and every structural chunk keeps a valid,
    reconstructible char-offset span regardless of how the embedding layer
    internally sub-splits it for the provider call.
    """
    dim = 4
    max_chars = 3000  # structural chunker's section budget
    embed_window = 50  # provider embedding window (independent from chunker)

    # A note with two headed sections; the second section is itself oversized
    # relative to the *embedding* window (though under the chunker's section
    # budget), so it must be mean-pooled by _embed_single, not aborted.
    text = (
        "# Title\n\n"
        "Short intro.\n\n"
        "## Big Section\n\n" + ("z" * (embed_window * 4)) + "\n"
    )

    structural_chunks = build_structural_chunks(text, max_chars=max_chars)
    assert len(structural_chunks) == 2
    # Every structural chunk keeps valid, reconstructible offsets independent
    # of what the embedding layer does internally with the chunk's text.
    for chunk in structural_chunks:
        assert text[chunk["char_start"] : chunk["char_end"]] == chunk["text"]

    monkeypatch.setenv("EMBED_MAX_INPUT_CHARS", str(embed_window))
    monkeypatch.setenv("LLM_TIMEOUT", "5")
    monkeypatch.setenv("EMBED_MODEL", "nomic-embed-text:latest")
    monkeypatch.setenv("EMBED_DIM", str(dim))

    def fake_embed_api(embed_text, model, d, timeout):
        if len(embed_text) > embed_window:
            raise RuntimeError(
                "Ollama /api/embeddings returned HTTP 500: the input length exceeds the context length"
            )
        return tuple(0.1 for _ in range(d))

    monkeypatch.setattr(emb, "_ollama_embed_api", fake_embed_api)
    emb._embed_single.cache_clear()

    vectors = embed_texts(
        [chunk["text"] for chunk in structural_chunks],
        provider="ollama",
        dim=dim,
        normalize=False,
    )

    assert len(vectors) == len(structural_chunks)
    # The short intro chunk is under the embedding window: embeds directly.
    assert vectors[0] == [0.1, 0.1, 0.1, 0.1]
    # The oversized structural section chunk is mean-pooled rather than
    # aborting the build; mean of constant 0.1 sub-vectors is still 0.1.
    assert vectors[1] == pytest.approx([0.1, 0.1, 0.1, 0.1])
    emb._embed_single.cache_clear()
