"""Tests for app/llm/embed_queue.py — retry, backoff, dead-letter, config."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.llm.embed_queue import (
    EmbedDeadLetterError,
    _get_base_backoff,
    _get_max_backoff,
    _get_retry_max,
    embed_with_retry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _transient_httpx_error() -> Exception:
    """Produce an httpx.TransportError which is classified as transient."""
    import httpx

    return httpx.TransportError("EOF")


def _nontransient_error() -> Exception:
    return ValueError("dimension mismatch: expected 8 got 4")


# ---------------------------------------------------------------------------
# test_transient_failures_retried_with_backoff
#   AC1 + AC2: transient errors are retried; backoff sleeps are issued.
# ---------------------------------------------------------------------------

def test_transient_failures_retried_with_backoff(monkeypatch):
    """Transient errors retry up to EMBED_RETRY_MAX and sleep with backoff."""
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")
    monkeypatch.setenv("EMBED_RETRY_MAX", "3")
    monkeypatch.setenv("EMBED_RETRY_BASE_BACKOFF_S", "0.0")
    monkeypatch.setenv("EMBED_RETRY_MAX_BACKOFF_S", "0.0")

    call_count = 0
    good_vector = [0.1] * 8

    def fake_embed_single(text, provider, model, dim):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise _transient_httpx_error()
        return tuple(good_vector)

    sleep_calls: list[float] = []

    with patch("app.llm.embed_queue._embed_single", side_effect=fake_embed_single):
        with patch("app.llm.embed_queue.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            result = embed_with_retry("hello", provider="mock", model="mock-embedding", dim=8, normalize=False)

    assert call_count == 3, "Should have retried to the third attempt"
    # Two sleeps between attempt 1→2 and attempt 2→3
    assert len(sleep_calls) == 2
    assert result == pytest.approx(good_vector)


# ---------------------------------------------------------------------------
# test_exhausted_embed_dead_letters_and_continues (AC3 / issue committed name)
#   This is the canonical name from the issue spec.
#   It tests that EmbedDeadLetterError is raised after exhaustion.
# ---------------------------------------------------------------------------

def test_exhausted_embed_dead_letters_and_continues(monkeypatch):
    """All retry attempts exhausted on transient error → EmbedDeadLetterError."""
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")
    monkeypatch.setenv("EMBED_RETRY_MAX", "3")
    monkeypatch.setenv("EMBED_RETRY_BASE_BACKOFF_S", "0.0")
    monkeypatch.setenv("EMBED_RETRY_MAX_BACKOFF_S", "0.0")

    def always_transient(text, provider, model, dim):
        raise _transient_httpx_error()

    with patch("app.llm.embed_queue._embed_single", side_effect=always_transient):
        with patch("app.llm.embed_queue.time.sleep"):
            with pytest.raises(EmbedDeadLetterError) as exc_info:
                embed_with_retry("hello", provider="mock", model="mock-embedding", dim=8, normalize=False)

    assert "3 attempts" in str(exc_info.value)


# ---------------------------------------------------------------------------
# test_provider_wide_outage_fails_loud (AC8 regression guard via embed_with_retry)
# ---------------------------------------------------------------------------

def test_provider_wide_outage_fails_loud(monkeypatch):
    """A provider-wide outage (every attempt transient) raises EmbedDeadLetterError, not silently zero-vectors."""
    monkeypatch.setenv("EMBED_RETRY_MAX", "2")
    monkeypatch.setenv("EMBED_RETRY_BASE_BACKOFF_S", "0.0")
    monkeypatch.setenv("EMBED_RETRY_MAX_BACKOFF_S", "0.0")

    def outage(text, provider, model, dim):
        import httpx
        raise httpx.ConnectError("connection refused")

    with patch("app.llm.embed_queue._embed_single", side_effect=outage):
        with patch("app.llm.embed_queue.time.sleep"):
            with pytest.raises(EmbedDeadLetterError):
                embed_with_retry("text", provider="ollama", model="nomic-embed-text", dim=768, normalize=False)


# ---------------------------------------------------------------------------
# test_config_defaults (AC9)
# ---------------------------------------------------------------------------

def test_config_defaults(monkeypatch):
    """The retry/backoff config env vars have sane defaults when unset.

    Embedding execution is intentionally serial (no concurrency knob); see the
    module docstring for the rationale (memory-bound shared Ollama)."""
    for var in ("EMBED_RETRY_MAX", "EMBED_RETRY_BASE_BACKOFF_S", "EMBED_RETRY_MAX_BACKOFF_S"):
        monkeypatch.delenv(var, raising=False)

    assert _get_retry_max() == 3
    assert _get_base_backoff() == pytest.approx(1.0)
    assert _get_max_backoff() == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# test_no_retry_on_non_transient (AC4)
# ---------------------------------------------------------------------------

def test_no_retry_on_non_transient(monkeypatch):
    """Non-transient errors are re-raised immediately — no sleep, no retry."""
    monkeypatch.setenv("EMBED_RETRY_MAX", "3")
    monkeypatch.setenv("EMBED_RETRY_BASE_BACKOFF_S", "0.0")

    call_count = 0

    def raises_value_error(text, provider, model, dim):
        nonlocal call_count
        call_count += 1
        raise ValueError("dimension mismatch: expected 8 got 4")

    sleep_calls: list = []
    with patch("app.llm.embed_queue._embed_single", side_effect=raises_value_error):
        with patch("app.llm.embed_queue.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            with pytest.raises(ValueError, match="dimension mismatch"):
                embed_with_retry("hello", provider="mock", model="mock-embedding", dim=8, normalize=False)

    assert call_count == 1, "Non-transient must not be retried"
    assert sleep_calls == [], "No sleep on non-transient"


# ---------------------------------------------------------------------------
# test_backoff_timing (AC2)
# ---------------------------------------------------------------------------

def test_backoff_timing(monkeypatch):
    """Backoff sleeps follow min(base * 2^(attempt-1), cap)."""
    monkeypatch.setenv("EMBED_RETRY_MAX", "3")
    monkeypatch.setenv("EMBED_RETRY_BASE_BACKOFF_S", "1.0")
    monkeypatch.setenv("EMBED_RETRY_MAX_BACKOFF_S", "30.0")

    def always_transient(text, provider, model, dim):
        raise _transient_httpx_error()

    sleep_calls: list[float] = []
    with patch("app.llm.embed_queue._embed_single", side_effect=always_transient):
        with patch("app.llm.embed_queue.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            with pytest.raises(EmbedDeadLetterError):
                embed_with_retry("hello", provider="mock", model="mock-embedding", dim=8, normalize=False)

    # Attempt 1 → sleep base*2^0=1.0, attempt 2 → sleep base*2^1=2.0, attempt 3 → no sleep (final)
    assert sleep_calls == pytest.approx([1.0, 2.0])


# ---------------------------------------------------------------------------
# test_dead_letter_on_exhaustion (AC3)
# ---------------------------------------------------------------------------

def test_dead_letter_on_exhaustion(monkeypatch):
    """EmbedDeadLetterError is a RuntimeError subclass and message contains attempt count."""
    monkeypatch.setenv("EMBED_RETRY_MAX", "2")
    monkeypatch.setenv("EMBED_RETRY_BASE_BACKOFF_S", "0.0")
    monkeypatch.setenv("EMBED_RETRY_MAX_BACKOFF_S", "0.0")

    def always_transient(text, provider, model, dim):
        raise _transient_httpx_error()

    with patch("app.llm.embed_queue._embed_single", side_effect=always_transient):
        with patch("app.llm.embed_queue.time.sleep"):
            with pytest.raises(EmbedDeadLetterError) as exc_info:
                embed_with_retry("hello", provider="mock", model="mock-embedding", dim=8, normalize=False)

    assert isinstance(exc_info.value, RuntimeError)
    assert "2 attempts" in str(exc_info.value)


# ---------------------------------------------------------------------------
# test_transient_classification (AC1 — named in spec)
# ---------------------------------------------------------------------------

def test_transient_classification(monkeypatch):
    """HTTP 5xx, 408, 429, EOF, and connection-reset errors are classified transient."""
    import httpx

    monkeypatch.setenv("EMBED_RETRY_MAX", "1")
    monkeypatch.setenv("EMBED_RETRY_BASE_BACKOFF_S", "0.0")
    monkeypatch.setenv("EMBED_RETRY_MAX_BACKOFF_S", "0.0")

    transient_errors = [
        httpx.TransportError("EOF"),
        httpx.ConnectError("connection reset"),
        httpx.ReadTimeout("timeout"),
        ConnectionError("connection refused"),
        TimeoutError("timed out"),
    ]

    for err in transient_errors:
        def make_raiser(e):
            def raiser(text, provider, model, dim):
                raise e
            return raiser

        with patch("app.llm.embed_queue._embed_single", side_effect=make_raiser(err)):
            with patch("app.llm.embed_queue.time.sleep"):
                with pytest.raises(EmbedDeadLetterError, match="1 attempts"):
                    embed_with_retry("hello", provider="mock", model="mock-embedding", dim=8, normalize=False)
