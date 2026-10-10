from __future__ import annotations

import pytest
import httpx

from app.components.embeddings import EmbeddingIdentity
from app.llm.embed_queue import EmbedDeadLetterError
from app.llm.fallback_orchestrator import FallbackGateResult
from app.llm import fallback_orchestrator
from app.model_access.codex_remote_transport import CodexRemoteTransport
from app.model_access.remote_contract import ProductEmbeddingRequest


def test_dim_mismatch_refuses_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBED_FALLBACK_PROVIDER", "gemini")

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


def test_client_provider_key_is_not_required_for_portal_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMBED_FALLBACK_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    primary_identity = EmbeddingIdentity(provider="ollama", model="nomic-embed-text", dim=768)
    fallback_identity = EmbeddingIdentity(
        provider="gemini", model="gemini-embedding-001", dim=768
    )
    monkeypatch.setattr(
        fallback_orchestrator,
        "_resolve_fallback_identity",
        lambda _provider: fallback_identity,
    )
    fallback_client = type(
        "FallbackClient",
        (),
        {
            "identity": fallback_identity,
            "embed_text": lambda _self, _text: [0.5] * fallback_identity.dim,
        },
    )()
    fallback_clients: list[EmbeddingIdentity] = []
    monkeypatch.setattr(
        fallback_orchestrator,
        "get_product_embedding_client_for_identity",
        lambda identity: fallback_clients.append(identity) or fallback_client,
    )

    calls: list[str] = []

    def fake_embed_with_retry(*args, embed_callable=None, **kwargs):
        del args, kwargs
        calls.append("attempt")
        if len(calls) == 1:
            raise EmbedDeadLetterError("primary exhausted")
        assert embed_callable is not None
        return list(embed_callable())

    monkeypatch.setattr(fallback_orchestrator, "embed_with_retry", fake_embed_with_retry)

    assert fallback_orchestrator.evaluate_fallback_gate(primary_identity.dim) == FallbackGateResult.AVAILABLE
    vector, identity, is_fallback = fallback_orchestrator.embed_with_fallback(
        "text",
        primary_identity=primary_identity,
        primary_embed_callable=lambda: (_ for _ in ()).throw(
            EmbedDeadLetterError("primary exhausted")
        ),
    )

    assert len(calls) == 2
    assert fallback_clients == [fallback_identity]
    assert (vector, identity, is_fallback) == (
        [0.5] * fallback_identity.dim,
        fallback_identity,
        True,
    )


def test_no_fallback_provider_configured_dead_letters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EMBED_FALLBACK_PROVIDER", raising=False)

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


def test_indeterminate_remote_embedding_is_neither_retried_nor_fallbacked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EMBED_FALLBACK_PROVIDER", "gemini")
    primary_identity = EmbeddingIdentity(
        provider="ollama", model="nomic-embed-text:latest", dim=768
    )
    fallback_identity = EmbeddingIdentity(
        provider="gemini", model="gemini-embedding-001", dim=768
    )
    monkeypatch.setattr(
        fallback_orchestrator,
        "_resolve_fallback_identity",
        lambda _provider: fallback_identity,
    )
    fallback_calls: list[str] = []
    monkeypatch.setattr(
        fallback_orchestrator,
        "get_product_embedding_client_for_identity",
        lambda _identity: fallback_calls.append("fallback"),
    )

    requests: list[httpx.Request] = []

    def timeout_after_dispatch(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise httpx.ReadTimeout("synthetic response loss after dispatch")

    transport = CodexRemoteTransport(
        endpoint="https://mac-mini.example-tailnet.ts.net",
        transport=httpx.MockTransport(timeout_after_dispatch),
    )
    try:
        request = ProductEmbeddingRequest(
            provider=primary_identity.provider,
            model=primary_identity.model,
            dimensions=primary_identity.dim,
            input_text="one dispatched request",
        )
        with pytest.raises(EmbedDeadLetterError) as error:
            fallback_orchestrator.embed_with_fallback(
                "one dispatched request",
                primary_identity=primary_identity,
                primary_embed_callable=lambda: list(
                    transport.embed_product(request).vector
                ),
            )
    finally:
        transport.close()

    assert error.value.indeterminate is True
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    assert len(requests) == 1
    assert requests[0].url.path == "/v1/product/embed"
    assert fallback_calls == []
