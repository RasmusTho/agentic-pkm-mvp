from __future__ import annotations

import httpx

import app.llm.embeddings as emb
from app.llm.embeddings import embed_text


def _clear_cache() -> None:
    emb._embed_single.cache_clear()


def test_oversized_text_is_chunked_not_raised(monkeypatch) -> None:
    """A note longer than the model context window must not raise.

    Regression for #2110: previously the whole note text was sent to the
    embeddings provider with no length check, so an oversized note returned
    HTTP 500 ("input length exceeds the context length") and aborted the
    entire embed batch. The embedding path must truncate/chunk the input
    down to a bounded budget before calling the provider.
    """
    for key in ("OLLAMA_BASE_URL", "OLLAMA_URL", "OLLAMA_HOST", "OPENAI_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_HOST", "https://ollama.local:11434/")
    monkeypatch.setenv("EMBED_DIM", "3")
    monkeypatch.setenv("EMBED_MODEL", "nomic-embed-text:latest")
    # Small, explicit budget so the test is deterministic and fast.
    monkeypatch.setenv("EMBED_MAX_INPUT_CHARS", "100")

    captured: dict[str, object] = {}

    class DummyResponse:
        is_error = False
        status_code = 200

        def json(self) -> dict[str, object]:
            return {"embeddings": [[1, 2, 3]]}

    def fake_post(url: str, json: dict[str, object], timeout: float) -> DummyResponse:
        # The model would 500 on an over-budget prompt; assert we never send one.
        prompt = json.get("prompt") or json.get("input")
        assert isinstance(prompt, str)
        if len(prompt) > 100:
            raise httpx.HTTPStatusError(
                "input length exceeds the context length",
                request=httpx.Request("POST", url),
                response=httpx.Response(500, request=httpx.Request("POST", url)),
            )
        captured["prompt_len"] = len(prompt)
        return DummyResponse()

    monkeypatch.setattr("app.llm.embeddings.httpx.post", fake_post)
    _clear_cache()

    oversized = "word " * 5000  # ~25k chars, far over the 100-char budget
    vector = embed_text(oversized, provider="ollama", normalize=False)

    assert vector == [1.0, 2.0, 3.0]
    assert captured["prompt_len"] <= 100
