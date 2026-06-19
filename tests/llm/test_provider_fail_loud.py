"""Provider fail-loud regressions (#2190).

Two residuals from the 2026-06-18 terminal review-thread audit (#2148):

1. ``embed_texts`` degraded provider-wide outages to per-item zero vectors, so a
   global embedding-provider outage silently produced an all-zero semantic
   index. It must instead fail loud when the whole batch degrades.
2. Real-provider chat branches returned empty ``response_text`` on an HTTP 200
   with no content instead of raising ``LLMError``. A blank successful response
   must fail loud rather than manufacture a false-green synthesis receipt.
"""

from __future__ import annotations

import http.client

import pytest

from app.llm import embeddings as emb
from app.services.llm import LLMError, call_llm


# --- Anchor 1: app/llm/embeddings.py embed_texts ---------------------------


def test_provider_outage_does_not_degrade_whole_batch_to_zero(monkeypatch) -> None:
    """A provider-wide outage must raise, not return an all-zero batch.

    Pre-fix, every per-item failure was caught and substituted with a zero
    vector, so an outage that fails every note yielded a semantically dead
    index with no batch-wide failure signal. Now the production path raises when
    every embeddable item degrades.
    """
    dim = 8
    monkeypatch.setenv("LLM_TIMEOUT", "5")

    def fake_embed_api(text, model, d, timeout):
        # Simulate a provider-wide outage: every request fails the same way the
        # fallback path collapses to (RuntimeError) when Ollama is unreachable.
        raise RuntimeError("Ollama embedding requests failed: provider unreachable")

    monkeypatch.setattr(emb, "_ollama_embed_api", fake_embed_api)
    monkeypatch.setattr(emb, "_ollama_openai_fallback", fake_embed_api)
    emb._embed_single.cache_clear()

    with pytest.raises(RuntimeError, match="all-zero semantic index|degraded every embeddable"):
        emb.embed_texts(
            ["note one", "note two", "note three"],
            provider="ollama",
            model="nomic-embed-text:latest",
            dim=dim,
            normalize=False,
        )
    emb._embed_single.cache_clear()


def test_single_bad_note_still_degrades_to_zero(monkeypatch) -> None:
    """A single un-embeddable note among healthy ones still degrades to a zero
    vector — the per-item tolerance from #2110 is preserved, not weakened."""
    dim = 8
    monkeypatch.setenv("LLM_TIMEOUT", "5")

    def fake_embed_api(text, model, d, timeout):
        if "BAD" in text:
            raise RuntimeError(
                "Ollama /api/embeddings returned HTTP 500: the input length exceeds the context length"
            )
        return tuple(0.3 for _ in range(d))

    monkeypatch.setattr(emb, "_ollama_embed_api", fake_embed_api)
    emb._embed_single.cache_clear()

    vectors = emb.embed_texts(
        ["healthy one", "BAD note", "healthy two"],
        provider="ollama",
        model="nomic-embed-text:latest",
        dim=dim,
        normalize=False,
    )

    assert len(vectors) == 3
    assert vectors[1] == [0.0] * dim  # the bad note degraded
    assert vectors[0] != [0.0] * dim and vectors[2] != [0.0] * dim  # healthy ones embedded
    emb._embed_single.cache_clear()


# --- Anchor 2: app/services/llm.py real-provider branches ------------------


class _FakeOllamaResponse:
    status = 200

    def __init__(self, body: bytes) -> None:
        self._body = body
        self._read = False

    def read(self, _size: int) -> bytes:
        if self._read:
            return b""
        self._read = True
        return self._body


class _FakeConn:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def request(self, *args, **kwargs) -> None:  # noqa: D401 - stub
        return None

    def getresponse(self) -> _FakeOllamaResponse:
        return _FakeOllamaResponse(self._body)

    def close(self) -> None:
        return None


def test_empty_ollama_response_raises(monkeypatch) -> None:
    """An HTTP 200 with no message content must raise LLMError on the ollama
    production path, not return an empty answer."""
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("LLM_MAX_RETRIES", "0")

    # A 200 streaming-chat body with an empty content payload.
    body = b'{"message": {"role": "assistant", "content": ""}, "done": true}\n'
    monkeypatch.setattr(http.client, "HTTPConnection", lambda *a, **k: _FakeConn(body))

    with pytest.raises(LLMError, match="empty response|blank completion"):
        call_llm("qa", {"system": "", "user": "hi"}, kind="qa.draft")


def test_empty_http_chat_response_raises(monkeypatch) -> None:
    """An HTTP 200 with no choices/content on the openai/deepseek path
    (_http_chat) must raise LLMError, not return empty text."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9/v1")

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"choices": [{"message": {"content": ""}}]}

    import app.services.llm as llm_mod

    monkeypatch.setattr(llm_mod.requests, "post", lambda *a, **k: _Resp())

    with pytest.raises(LLMError, match="empty response|blank completion"):
        call_llm("qa", {"system": "", "user": "hi"}, kind="qa.draft")
