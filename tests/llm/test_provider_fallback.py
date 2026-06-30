from __future__ import annotations

import pytest

from app.components.embeddings import EmbeddingIdentity
from app.llm.embed_queue import EmbedDeadLetterError
from app.llm.fallback_orchestrator import FallbackGateResult
from app.llm import fallback_orchestrator


def test_dim_mismatch_refuses_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBED_FALLBACK_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    primary_identity = EmbeddingIdentity(provider="ollama", model="nomic-embed-text", dim=768)
    fallback_identity = EmbeddingIdentity(provider="gemini", model="gemini-embedding-001", dim=3072)
    monkeypatch.setattr(fallback_orchestrator, "_resolve_fallback_identity", lambda provider: fallback_identity)

    calls: list[str] = []

    def fake_embed_with_retry(*args, **kwargs):
        calls.append("attempt")
        if len(calls) == 1:
            raise EmbedDeadLetterError("primary exhausted")
        raise AssertionError("fallback should not be attempted on dim mismatch")

    monkeypatch.setattr(fallback_orchestrator, "embed_with_retry", fake_embed_with_retry)

    assert fallback_orchestrator.evaluate_fallback_gate(primary_identity.dim) == FallbackGateResult.DIM_MISMATCH
    with pytest.raises(EmbedDeadLetterError, match="DIM_MISMATCH"):
        fallback_orchestrator.embed_with_fallback(
            "text",
            primary_identity=primary_identity,
            primary_embed_callable=lambda: [0.0] * primary_identity.dim,
        )

    assert len(calls) == 1


def test_no_key_dead_letters_object(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBED_FALLBACK_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    primary_identity = EmbeddingIdentity(provider="ollama", model="nomic-embed-text", dim=768)
    monkeypatch.setattr(
        fallback_orchestrator,
        "_resolve_fallback_identity",
        lambda provider: (_ for _ in ()).throw(AssertionError("fallback identity should not resolve without a key")),
    )

    calls: list[str] = []

    def fake_embed_with_retry(*args, **kwargs):
        calls.append("attempt")
        if len(calls) == 1:
            raise EmbedDeadLetterError("primary exhausted")
        raise AssertionError("fallback should not be attempted without a key")

    monkeypatch.setattr(fallback_orchestrator, "embed_with_retry", fake_embed_with_retry)

    assert fallback_orchestrator.evaluate_fallback_gate(primary_identity.dim) == FallbackGateResult.NO_KEY
    with pytest.raises(EmbedDeadLetterError, match="NO_KEY"):
        fallback_orchestrator.embed_with_fallback(
            "text",
            primary_identity=primary_identity,
            primary_embed_callable=lambda: [0.0] * primary_identity.dim,
        )

    assert len(calls) == 1


def test_no_fallback_provider_configured_dead_letters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EMBED_FALLBACK_PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    primary_identity = EmbeddingIdentity(provider="ollama", model="nomic-embed-text", dim=768)
    monkeypatch.setattr(
        fallback_orchestrator,
        "_resolve_fallback_identity",
        lambda provider: (_ for _ in ()).throw(AssertionError("fallback identity should not resolve without fallback config")),
    )

    calls: list[str] = []

    def fake_embed_with_retry(*args, **kwargs):
        calls.append("attempt")
        if len(calls) == 1:
            raise EmbedDeadLetterError("primary exhausted")
        raise AssertionError("fallback should not be attempted without fallback config")

    monkeypatch.setattr(fallback_orchestrator, "embed_with_retry", fake_embed_with_retry)

    assert fallback_orchestrator.evaluate_fallback_gate(primary_identity.dim) == FallbackGateResult.NO_FALLBACK_CONFIGURED
    with pytest.raises(EmbedDeadLetterError, match="NO_FALLBACK_CONFIGURED"):
        fallback_orchestrator.embed_with_fallback(
            "text",
            primary_identity=primary_identity,
            primary_embed_callable=lambda: [0.0] * primary_identity.dim,
        )

    assert len(calls) == 1


def test_primary_success_never_consults_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBED_FALLBACK_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    primary_identity = EmbeddingIdentity(provider="ollama", model="nomic-embed-text", dim=768)
    monkeypatch.setattr(
        fallback_orchestrator,
        "_resolve_fallback_identity",
        lambda provider: (_ for _ in ()).throw(AssertionError("fallback should not be consulted before primary exhaustion")),
    )

    calls: list[str] = []

    def fake_embed_with_retry(*args, embed_callable=None, **kwargs):
        del args, kwargs
        calls.append("primary")
        assert embed_callable is not None
        return list(embed_callable())

    monkeypatch.setattr(fallback_orchestrator, "embed_with_retry", fake_embed_with_retry)

    vector, identity, is_fallback = fallback_orchestrator.embed_with_fallback(
        "text",
        primary_identity=primary_identity,
        primary_embed_callable=lambda: [0.25] * primary_identity.dim,
    )

    assert len(calls) == 1
    assert vector == [0.25] * primary_identity.dim
    assert identity == primary_identity
    assert is_fallback is False
