from __future__ import annotations

import httpx

import app.llm.embeddings as emb
from app.llm.embeddings import embed_texts


def _clear_cache() -> None:
    emb._embed_single.cache_clear()


def test_oversized_note_does_not_abort_index(monkeypatch) -> None:
    """An index build over a corpus with one pathological note must complete.

    Regression for #2110: a single note that still trips the provider's
    context-length limit (HTTP 500) must be degraded (skipped with a warning,
    substituted with a zero vector) rather than aborting the whole batch and
    taking down the entire retrieval index build. The remaining notes embed.
    """
    for key in ("OLLAMA_BASE_URL", "OLLAMA_URL", "OLLAMA_HOST", "OPENAI_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_HOST", "https://ollama.local:11434/")
    monkeypatch.setenv("EMBED_DIM", "3")
    monkeypatch.setenv("EMBED_MODEL", "nomic-embed-text:latest")
    # Disable truncation so the oversized note actually reaches the provider
    # and triggers the per-item degradation path (not the truncation path).
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
    _clear_cache()

    corpus = ["healthy note one", poison, "healthy note two"]
    vectors = embed_texts(corpus, provider="ollama", normalize=False)

    assert len(vectors) == len(corpus)
    # Healthy notes embed normally.
    assert vectors[0] == [1.0, 2.0, 3.0]
    assert vectors[2] == [1.0, 2.0, 3.0]
    # The poison note is degraded to a zero vector of the correct dimension,
    # not an exception that aborts the build.
    assert vectors[1] == [0.0, 0.0, 0.0]
