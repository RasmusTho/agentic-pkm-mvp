from __future__ import annotations

from app.llm import embeddings as emb


def test_oversized_text_is_chunked_not_raised(monkeypatch) -> None:
    """A text longer than the embedding model's context window is chunked into
    in-window requests, not sent whole.

    Sending the whole note returns HTTP 500 ("input length exceeds the context
    length") and aborts the entire embed batch / index build (#2110). With
    chunking, each request stays in window so the call never raises.
    """
    dim = 8
    max_chars = 100
    monkeypatch.setenv("EMBED_MAX_INPUT_CHARS", str(max_chars))
    monkeypatch.setenv("LLM_TIMEOUT", "5")

    calls: list[int] = []

    def fake_embed_api(text, model, d, timeout):
        calls.append(len(text))
        if len(text) > max_chars:
            raise RuntimeError(
                "Ollama /api/embeddings returned HTTP 500: the input length exceeds the context length"
            )
        return tuple(0.1 for _ in range(d))

    monkeypatch.setattr(emb, "_ollama_embed_api", fake_embed_api)
    emb._embed_single.cache_clear()

    oversized = "x" * 1000  # 10x the configured window
    vector = emb.embed_text(
        oversized, provider="ollama", model="nomic-embed-text:latest", dim=dim, normalize=False
    )

    assert len(vector) == dim
    assert len(calls) > 1, "oversized text should be chunked into multiple in-window requests"
    assert all(n <= max_chars for n in calls), f"a chunk exceeded the window: {calls}"
    emb._embed_single.cache_clear()


def test_in_window_text_is_unchanged(monkeypatch) -> None:
    """A note within the window is sent as a single request (deterministic
    vault-test behavior is unchanged — no spurious chunking)."""
    dim = 8
    monkeypatch.setenv("EMBED_MAX_INPUT_CHARS", "6000")
    monkeypatch.setenv("LLM_TIMEOUT", "5")

    calls: list[int] = []

    def fake_embed_api(text, model, d, timeout):
        calls.append(len(text))
        return tuple(0.2 for _ in range(d))

    monkeypatch.setattr(emb, "_ollama_embed_api", fake_embed_api)
    emb._embed_single.cache_clear()

    emb.embed_text("a short vault note", provider="ollama", model="nomic-embed-text:latest", dim=dim)

    assert len(calls) == 1
    emb._embed_single.cache_clear()
