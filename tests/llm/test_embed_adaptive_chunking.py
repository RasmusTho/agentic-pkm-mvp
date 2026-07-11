"""Tests for adaptive chunk bisect on provider 5xx (#3045).

A char budget (``EMBED_MAX_INPUT_CHARS``) is a poor proxy for a model's
token/context window: table-heavy, code-heavy, or unicode-dense markdown can
exceed the context window well inside a "safe" char count, while a
same-length plain-prose chunk passes. When that happens the provider returns
a 5xx for that one chunk (e.g. Ollama's "HTTP 500: EOF" on nomic-embed-text).
Previously ``embed_with_retry`` would retry the *whole object* identically 3x
(same chunk, same failure) and then dead-letter it permanently. These tests
verify ``_embed_single`` instead bisects the offending chunk in place and
mean-pools the surviving sub-chunks, only surfacing the original error once
bisection reaches the floor.
"""
from __future__ import annotations

import httpx
import pytest

from app.llm import embeddings as emb


def _fake_5xx_response(status_code: int = 500) -> httpx.Response:
    request = httpx.Request("POST", "http://ollama.local/api/embeddings")
    return httpx.Response(status_code, request=request, json={"error": "EOF"})


class _TransientProviderError(RuntimeError):
    is_transient = True


@pytest.mark.parametrize(
    "error_factory",
    [
        lambda: httpx.ConnectError(
            "provider unavailable", request=httpx.Request("POST", "http://provider.invalid/embed")
        ),
        lambda: httpx.TimeoutException(
            "provider timed out", request=httpx.Request("POST", "http://provider.invalid/embed")
        ),
        lambda: _TransientProviderError("provider temporarily unavailable"),
    ],
)
def test_transport_failures_do_not_bisect(error_factory) -> None:
    """A transport outage reaches the normal retry boundary after one call."""
    calls: list[int] = []

    def unavailable(text, **kwargs):
        calls.append(len(text))
        raise error_factory()

    try:
        emb._embed_chunk_with_bisect(
            "x" * 2048,
            unavailable,
            model="test",
            dim=8,
            timeout=1,
            floor_chars=256,
        )
    except Exception:
        pass
    else:
        raise AssertionError("expected the original transport error to surface")

    assert calls == [2048]


def test_provider_5xx_chunk_bisects_and_completes(monkeypatch) -> None:
    """A chunk whose embed attempt fails with a provider 5xx is bisected and
    re-embedded; the object completes with a mean-pooled vector instead of
    dead-lettering.

    Simulates the real repro shape: a specific content-dense sub-slice of a
    chunk crashes the provider (HTTP 500) while shorter/neighboring slices
    succeed — content-dependent, not size-alone. This exercises
    ``_embed_single`` directly (the module under test for #3045), not the
    retry/dead-letter boundary in ``embed_queue.py`` — this mechanism must
    resolve the object *before* embed_with_retry would ever retry the whole
    object identically.
    """
    dim = 8
    max_chars = 2000
    monkeypatch.setenv("EMBED_MAX_INPUT_CHARS", str(max_chars))
    monkeypatch.setenv("EMBED_MIN_CHUNK_CHARS", "256")
    monkeypatch.setenv("LLM_TIMEOUT", "5")
    # _ollama_embed_one falls back to the OpenAI-shaped endpoint on
    # httpx.HTTPError, which resolves the base URL independently of the
    # patched _ollama_embed_api — set it so that fallback path (also patched
    # to raise below) does not fail on missing config before reaching the
    # fake's own logic.
    monkeypatch.setenv("OLLAMA_URL", "http://ollama.local:11434")

    # The "poison" region is a fixed byte range within the note that only
    # crashes when a request's text spans past a given offset (mimicking a
    # token-dense table/code block starting partway through the chunk).
    poison_start = 900
    calls: list[int] = []

    def _raise_5xx():
        request = httpx.Request("POST", "http://ollama.local/api/embeddings")
        response = _fake_5xx_response(500)
        raise httpx.HTTPStatusError(
            "Ollama /api/embeddings returned HTTP 500: EOF", request=request, response=response
        )

    def fake_embed_api(text, model, d, timeout):
        calls.append(len(text))
        if len(text) > poison_start:
            _raise_5xx()
        return tuple(0.25 for _ in range(d))

    def fake_fallback(text, model, d, timeout):
        # _ollama_embed_one always tries this fallback on a primary
        # httpx.HTTPError; keep it consistent with the primary so the net
        # effect (5xx on the poisoned length, success otherwise) is unchanged.
        if len(text) > poison_start:
            _raise_5xx()
        return tuple(0.25 for _ in range(d))

    monkeypatch.setattr(emb, "_ollama_embed_api", fake_embed_api)
    monkeypatch.setattr(emb, "_ollama_openai_fallback", fake_fallback)
    emb._embed_single.cache_clear()

    # A single chunk (< max_chars) whose full length crashes the provider.
    text = "x" * 1200
    vector = emb.embed_text(
        text, provider="ollama", model="nomic-embed-text:latest", dim=dim, normalize=False
    )

    assert len(vector) == dim
    # The object completed (mean-pooled), not dead-lettered.
    assert all(v == 0.25 for v in vector)
    # More than one call means bisection actually happened (not a single
    # lucky pass-through).
    assert len(calls) > 1, f"expected bisection to split the failing chunk, calls={calls}"
    emb._embed_single.cache_clear()


def test_floor_failure_still_dead_letters(monkeypatch) -> None:
    """A chunk that still fails at the floor size surfaces the original
    error (fail loud, dead-letter preserved).

    When every sub-chunk down to ``EMBED_MIN_CHUNK_CHARS`` still 5xxs, this is
    not a content-density problem the bisect mechanism can fix — the original
    provider error must propagate unchanged so the normal
    embed_with_retry/dead-letter path still applies (no silent skip, no
    swallowed failure).
    """
    dim = 8
    monkeypatch.setenv("EMBED_MAX_INPUT_CHARS", "2000")
    monkeypatch.setenv("EMBED_MIN_CHUNK_CHARS", "256")
    monkeypatch.setenv("LLM_TIMEOUT", "5")
    monkeypatch.setenv("OLLAMA_URL", "http://ollama.local:11434")

    def always_fails(text, model, d, timeout):
        request = httpx.Request("POST", "http://ollama.local/api/embeddings")
        response = _fake_5xx_response(500)
        raise httpx.HTTPStatusError(
            "Ollama /api/embeddings returned HTTP 500: EOF", request=request, response=response
        )

    # _ollama_embed_one always tries the openai-shaped fallback on a primary
    # httpx.HTTPError; make it fail identically so both endpoints are equally
    # "poisoned" at every size down to the floor.
    monkeypatch.setattr(emb, "_ollama_embed_api", always_fails)
    monkeypatch.setattr(emb, "_ollama_openai_fallback", always_fails)
    emb._embed_single.cache_clear()

    text = "y" * 1200
    try:
        emb.embed_text(
            text, provider="ollama", model="nomic-embed-text:latest", dim=dim, normalize=False
        )
        raised = False
    except RuntimeError as exc:
        raised = True
        # The original provider error detail must still be present (fail loud),
        # not replaced by a generic bisect-internal message.
        assert "500" in str(exc) or "EOF" in str(exc)

    assert raised, "expected the original provider error to surface at the bisect floor"
    emb._embed_single.cache_clear()


def test_bisection_is_deterministic(monkeypatch) -> None:
    """Same input plus the same sequence of provider failures always
    produces the same chunk decomposition (no randomness in the split
    point)."""
    dim = 8
    monkeypatch.setenv("EMBED_MAX_INPUT_CHARS", "2000")
    monkeypatch.setenv("EMBED_MIN_CHUNK_CHARS", "256")
    monkeypatch.setenv("LLM_TIMEOUT", "5")
    monkeypatch.setenv("OLLAMA_URL", "http://ollama.local:11434")

    poison_start = 900

    def make_fake(call_log):
        def fake_embed_api(text, model, d, timeout):
            call_log.append(len(text))
            if len(text) > poison_start:
                request = httpx.Request("POST", "http://ollama.local/api/embeddings")
                response = _fake_5xx_response(500)
                raise httpx.HTTPStatusError(
                    "Ollama /api/embeddings returned HTTP 500: EOF", request=request, response=response
                )
            return tuple(0.5 for _ in range(d))

        return fake_embed_api

    text = "z" * 1200

    calls_a: list[int] = []
    fake_a = make_fake(calls_a)
    monkeypatch.setattr(emb, "_ollama_embed_api", fake_a)
    monkeypatch.setattr(emb, "_ollama_openai_fallback", fake_a)
    emb._embed_single.cache_clear()
    emb.embed_text(text, provider="ollama", model="nomic-embed-text:latest", dim=dim, normalize=False)
    emb._embed_single.cache_clear()

    calls_b: list[int] = []
    fake_b = make_fake(calls_b)
    monkeypatch.setattr(emb, "_ollama_embed_api", fake_b)
    monkeypatch.setattr(emb, "_ollama_openai_fallback", fake_b)
    emb._embed_single.cache_clear()
    emb.embed_text(text, provider="ollama", model="nomic-embed-text:latest", dim=dim, normalize=False)
    emb._embed_single.cache_clear()

    assert calls_a == calls_b
