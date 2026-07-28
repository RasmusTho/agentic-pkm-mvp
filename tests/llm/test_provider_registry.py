"""Tests for the pluggable embedding provider registry and primary/fallback
selection config (EMBEDREL-03, GitHub issue #2294).

Verify targets committed in the issue:
  - test_mock_and_ollama_unchanged_after_registry_refactor
  - test_register_and_resolve_provider
  - test_primary_fallback_selection_precedence
  - test_gemini_name_supported

Additional AC tests per PLUGGABLE_PROVIDER_REGISTRY.md spec:
  - test_registry_contains_mock_and_ollama
  - test_embed_single_dispatches_via_registry
  - test_embed_single_unknown_provider_raises
  - test_mock_provider_unchanged_after_registry_refactor
  - test_ollama_provider_unchanged_after_registry_refactor
  - test_embedding_profile_accepts_primary_and_fallback_provider_fields
  - test_get_primary_provider_falls_back_to_llm_provider
  - test_get_fallback_provider_returns_none_when_unset
  - test_resolve_embedding_identity_prefers_primary_provider_field
  - test_gemini_name_not_normalized_to_mock
  - test_dim_guardrail_fires_via_registry_dispatch
"""
from __future__ import annotations

import httpx
import pytest

from app.llm import embeddings
from app.llm.embeddings import (
    PROVIDER_REGISTRY,
    _mock_embed_one,
    _mock_vector,
    _ollama_embed_one,
    get_fallback_provider,
    get_primary_provider,
)
from app.settings.models import EmbeddingProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_payload_response(url: str, status_code: int, payload: dict) -> httpx.Response:
    return httpx.Response(status_code, json=payload, request=httpx.Request("POST", url))


def _set_ollama_base(monkeypatch: pytest.MonkeyPatch, url: str = "http://ollama.test:11434") -> None:
    for key in ("OLLAMA_BASE_URL", "OLLAMA_URL", "OLLAMA_HOST", "OPENAI_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OLLAMA_URL", url)
    embeddings._embed_single.cache_clear()


# ---------------------------------------------------------------------------
# Issue-required verify targets
# ---------------------------------------------------------------------------

def test_mock_and_ollama_unchanged_after_registry_refactor(monkeypatch) -> None:
    """Mock and Ollama adapters in the registry produce identical output to the
    pre-refactor hardcoded branches. Regression gate for the enabling refactor."""
    # --- Mock path ---
    monkeypatch.setenv("EMBED_DIM", "8")
    embeddings._embed_single.cache_clear()

    text = "regression-check"
    dim = 8
    expected_mock = tuple(_mock_vector(text, dim=dim))
    result_mock = embeddings.embed_text(text, provider="mock", dim=dim, normalize=False)
    assert tuple(result_mock) == expected_mock, (
        "Mock registry adapter returned different vector than _mock_vector"
    )

    # --- Ollama path ---
    _set_ollama_base(monkeypatch)
    raw_vec = [0.1, -0.2, 0.3, -0.4, 0.5, -0.6, 0.7, -0.8]

    def fake_post(url: str, **kwargs) -> httpx.Response:
        return _make_payload_response(url, 200, {"embeddings": [raw_vec]})

    monkeypatch.setattr(httpx, "post", fake_post)
    result_ollama = embeddings.embed_text(text, provider="ollama", model="test", dim=dim, normalize=False)
    assert result_ollama == raw_vec


def test_register_and_resolve_provider(monkeypatch) -> None:
    """A sentinel adapter registered in PROVIDER_REGISTRY is called by _embed_single
    with correct keyword arguments (model, dim, timeout)."""
    called: list[dict] = []

    def sentinel_adapter(text: str, *, model: str, dim: int, timeout: float) -> tuple[float, ...]:
        called.append({"text": text, "model": model, "dim": dim, "timeout": timeout})
        return tuple([0.5] * dim)

    original = dict(PROVIDER_REGISTRY)
    try:
        PROVIDER_REGISTRY["sentinel"] = sentinel_adapter
        embeddings._embed_single.cache_clear()
        monkeypatch.setenv("LLM_TIMEOUT", "30")

        result = embeddings._embed_single("hello-sentinel", "sentinel", "sent-model", 4)
        assert result == (0.5, 0.5, 0.5, 0.5)
        assert len(called) == 1
        assert called[0]["model"] == "sent-model"
        assert called[0]["dim"] == 4
        assert called[0]["timeout"] == 30.0
    finally:
        PROVIDER_REGISTRY.clear()
        PROVIDER_REGISTRY.update(original)
        embeddings._embed_single.cache_clear()


def test_primary_fallback_selection_precedence(monkeypatch) -> None:
    """EMBED_PRIMARY_PROVIDER env var takes precedence over LLM_PROVIDER.
    EMBED_FALLBACK_PROVIDER env var is returned by get_fallback_provider().
    When EMBED_PRIMARY_PROVIDER is unset, falls back to LLM_PROVIDER."""
    # env var wins
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_PRIMARY_PROVIDER", "ollama")
    monkeypatch.setenv("EMBED_FALLBACK_PROVIDER", "gemini")
    from app.config import llm as llm_config
    monkeypatch.setattr(llm_config, "_ACTIVE_PROVIDER", None)

    assert get_primary_provider() == "ollama"
    assert get_fallback_provider() == "gemini"

    # when EMBED_PRIMARY_PROVIDER unset, falls back to LLM_PROVIDER
    monkeypatch.delenv("EMBED_PRIMARY_PROVIDER")
    assert get_primary_provider() == "mock"

    # when EMBED_FALLBACK_PROVIDER unset, returns None
    monkeypatch.delenv("EMBED_FALLBACK_PROVIDER")
    assert get_fallback_provider() is None


def test_gemini_name_supported() -> None:
    """'gemini' is registered, so embedding resolution preserves it."""
    from app.components.embeddings.legacy import (
        _resolve_embedding_provider_name,
        _supported_embed_providers,
    )

    assert "gemini" in _supported_embed_providers()
    assert (
        _resolve_embedding_provider_name(
            "gemini",
            provider_source="override_provider",
        )
        == "gemini"
    )


# ---------------------------------------------------------------------------
# Additional AC tests from spec
# ---------------------------------------------------------------------------

def test_registry_contains_mock_and_ollama() -> None:
    """PROVIDER_REGISTRY is pre-populated with 'mock' and 'ollama' entries."""
    assert "mock" in PROVIDER_REGISTRY
    assert "ollama" in PROVIDER_REGISTRY
    assert callable(PROVIDER_REGISTRY["mock"])
    assert callable(PROVIDER_REGISTRY["ollama"])


def test_embed_single_dispatches_via_registry(monkeypatch) -> None:
    """_embed_single dispatches via PROVIDER_REGISTRY with correct kwargs;
    no remaining if/elif provider branches."""
    dispatched: list[dict] = []

    def spy_adapter(text: str, *, model: str, dim: int, timeout: float) -> tuple[float, ...]:
        dispatched.append({"model": model, "dim": dim, "timeout": timeout})
        return tuple([0.1] * dim)

    original = dict(PROVIDER_REGISTRY)
    try:
        PROVIDER_REGISTRY["spy"] = spy_adapter
        embeddings._embed_single.cache_clear()
        monkeypatch.setenv("LLM_TIMEOUT", "45")

        embeddings._embed_single("spy-text", "spy", "spy-model", 6)
        assert len(dispatched) == 1
        assert dispatched[0] == {"model": "spy-model", "dim": 6, "timeout": 45.0}
    finally:
        PROVIDER_REGISTRY.clear()
        PROVIDER_REGISTRY.update(original)
        embeddings._embed_single.cache_clear()


def test_embed_single_unknown_provider_raises() -> None:
    """_embed_single raises ValueError for unknown provider via registry miss."""
    embeddings._embed_single.cache_clear()
    with pytest.raises(ValueError, match="Unsupported embedding provider"):
        embeddings._embed_single("text", "nonexistent-provider", "model", 4)


def test_mock_provider_unchanged_after_registry_refactor() -> None:
    """Mock registry adapter produces the same deterministic hash-derived vector
    as the original _mock_vector helper."""
    text = "deterministic-text"
    dim = 16
    expected = tuple(_mock_vector(text, dim=dim))
    result = _mock_embed_one(text, model="mock-embedding", dim=dim, timeout=60.0)
    assert result == expected


def test_ollama_provider_unchanged_after_registry_refactor(monkeypatch) -> None:
    """Ollama registry adapter produces the same vector and call sequence as the
    original _ollama_embed_one implementation: primary /api/embeddings first,
    fallback /v1/embeddings on HTTP error."""
    _set_ollama_base(monkeypatch)
    raw_vec = [0.1, 0.2, 0.3, 0.4]

    # Primary path succeeds
    calls: list[str] = []

    def fake_post_primary(url: str, **kwargs) -> httpx.Response:
        calls.append(url)
        return _make_payload_response(url, 200, {"embeddings": [raw_vec]})

    monkeypatch.setattr(httpx, "post", fake_post_primary)
    result = _ollama_embed_one("text", model="m", dim=4, timeout=5.0)
    assert result == tuple(raw_vec)
    assert any("/api/embeddings" in u for u in calls)

    # Fallback path on primary error
    calls.clear()

    def fake_post_fallback(url: str, **kwargs) -> httpx.Response:
        if "/api/embeddings" in url:
            req = httpx.Request("POST", url)
            raise httpx.HTTPStatusError("500", request=req, response=httpx.Response(500, request=req))
        calls.append(url)
        return _make_payload_response(url, 200, {"data": [{"embedding": raw_vec}]})

    monkeypatch.setattr(httpx, "post", fake_post_fallback)
    embeddings._embed_single.cache_clear()
    result2 = _ollama_embed_one("text2", model="m", dim=4, timeout=5.0)
    assert result2 == tuple(raw_vec)
    assert any("/v1/embeddings" in u for u in calls)


def test_embedding_profile_accepts_primary_and_fallback_provider_fields() -> None:
    """EmbeddingProfile deserializes primary_provider and fallback_provider fields
    without breaking existing profile deserialization."""
    # Existing fields still work with defaults
    existing = EmbeddingProfile(provider="ollama", model="nomic-embed-text:latest", dim=768)
    assert existing.primary_provider is None
    assert existing.fallback_provider is None

    # New fields can be set
    full = EmbeddingProfile(
        provider="ollama",
        model="nomic-embed-text:latest",
        dim=768,
        normalize=True,
        primary_provider="ollama",
        fallback_provider="gemini",
    )
    assert full.primary_provider == "ollama"
    assert full.fallback_provider == "gemini"

    # Deserialize from dict (as settings bundle does)
    from_dict = EmbeddingProfile(
        **{"provider": "ollama", "model": "nomic", "dim": 768, "primary_provider": "ollama"}
    )
    assert from_dict.primary_provider == "ollama"
    assert from_dict.fallback_provider is None


def test_get_primary_provider_falls_back_to_llm_provider(monkeypatch) -> None:
    """get_primary_provider() returns EMBED_PRIMARY_PROVIDER when set, else LLM_PROVIDER."""
    from app.config import llm as llm_config

    monkeypatch.delenv("EMBED_PRIMARY_PROVIDER", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setattr(llm_config, "_ACTIVE_PROVIDER", None)
    assert get_primary_provider() == "mock"

    monkeypatch.setenv("EMBED_PRIMARY_PROVIDER", "ollama")
    assert get_primary_provider() == "ollama"


def test_get_fallback_provider_returns_none_when_unset(monkeypatch) -> None:
    """get_fallback_provider() returns None when EMBED_FALLBACK_PROVIDER is unset."""
    monkeypatch.delenv("EMBED_FALLBACK_PROVIDER", raising=False)
    assert get_fallback_provider() is None

    monkeypatch.setenv("EMBED_FALLBACK_PROVIDER", "gemini")
    assert get_fallback_provider() == "gemini"


def test_resolve_embedding_identity_prefers_primary_provider_field(monkeypatch) -> None:
    """resolve_embedding_identity() uses profile.primary_provider over profile.provider
    when both are present; override_provider wins over both."""
    from unittest.mock import MagicMock

    from app.components.embeddings import resolve_embedding_identity
    from app.settings.models import EmbeddingProfile, EmbeddingProfiles

    profile = EmbeddingProfile(
        provider="mock",
        primary_provider="ollama",
        model="nomic-embed-text:latest",
        dim=4,
    )
    profiles = EmbeddingProfiles(
        default_profile="default",
        profiles={"default": profile},
    )
    bundle = MagicMock()
    bundle.embedding_profiles = profiles
    bundle.global_ = MagicMock()
    bundle.global_.profile = None

    monkeypatch.setenv("EMBED_DIM", "4")
    monkeypatch.setenv("EMBED_MODEL", "nomic-embed-text:latest")
    monkeypatch.delenv("EMBED_PROFILE", raising=False)

    from app.settings import runtime as settings_runtime
    monkeypatch.setattr(settings_runtime, "_CURRENT", bundle)

    # primary_provider wins over provider
    identity = resolve_embedding_identity(profile="default")
    assert identity.provider == "ollama", (
        f"Expected 'ollama' (from primary_provider) but got {identity.provider!r}"
    )

    # override_provider wins over primary_provider
    identity2 = resolve_embedding_identity(profile="default", override_provider="mock")
    assert identity2.provider == "mock"


def test_embed_text_default_dispatch_honors_primary_provider(monkeypatch) -> None:
    """embed_text(provider=None) routes through EMBED_PRIMARY_PROVIDER, not just
    LLM_PROVIDER (Codex P2). With EMBED_PRIMARY_PROVIDER=mock and LLM_PROVIDER=ollama
    (no OLLAMA_URL), the default dispatch must embed via mock — if it fell through to
    LLM_PROVIDER=ollama it would raise for a missing base URL."""
    from app.config import llm as llm_config

    for key in ("OLLAMA_BASE_URL", "OLLAMA_URL", "OLLAMA_HOST", "OPENAI_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("EMBED_PRIMARY_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_DIM", "8")
    monkeypatch.setattr(llm_config, "_ACTIVE_PROVIDER", None)
    embeddings._embed_single.cache_clear()

    text = "primary-provider-default-dispatch"
    result = embeddings.embed_text(text, normalize=False)
    assert tuple(result) == tuple(_mock_vector(text, dim=8))


def test_resolve_identity_env_overrides_profiled_mock(monkeypatch) -> None:
    """EMBED_PRIMARY_PROVIDER (env) overrides a profiled client whose provider
    defaults to 'mock' and whose primary_provider is unset (Codex P2). Without the
    fix, profile.provider='mock' shadows the env and the override is inert."""
    from unittest.mock import MagicMock

    from app.components.embeddings import resolve_embedding_identity
    from app.settings import runtime as settings_runtime
    from app.settings.models import EmbeddingProfile, EmbeddingProfiles

    profile = EmbeddingProfile(provider="mock", model="nomic-embed-text:latest", dim=4)
    profiles = EmbeddingProfiles(default_profile="default", profiles={"default": profile})
    bundle = MagicMock()
    bundle.embedding_profiles = profiles
    bundle.global_ = MagicMock()
    bundle.global_.profile = None

    monkeypatch.setenv("EMBED_DIM", "4")
    monkeypatch.setenv("EMBED_MODEL", "nomic-embed-text:latest")
    monkeypatch.delenv("EMBED_PROFILE", raising=False)
    monkeypatch.setenv("EMBED_PRIMARY_PROVIDER", "ollama")
    monkeypatch.setattr(settings_runtime, "_CURRENT", bundle)

    identity = resolve_embedding_identity(profile="default")
    assert identity.provider == "ollama", (
        f"EMBED_PRIMARY_PROVIDER=ollama must override profiled provider='mock', got {identity.provider!r}"
    )


def test_gemini_name_not_normalized_to_mock() -> None:
    """_resolve_embedding_provider_name('gemini') returns 'gemini', not 'mock'."""
    from app.components.embeddings.legacy import _resolve_embedding_provider_name

    result = _resolve_embedding_provider_name(
        "gemini",
        provider_source="override_provider",
    )
    assert result == "gemini", (
        f"Expected 'gemini' to pass through but got {result!r} — "
        "'gemini' must be in the live provider registry"
    )


def test_dim_guardrail_fires_via_registry_dispatch(monkeypatch) -> None:
    """assert_embed_dim still fires when a registry-dispatched adapter returns a
    wrong-dim vector — CTI-1 is preserved after the refactor."""
    def wrong_dim_adapter(text: str, *, model: str, dim: int, timeout: float) -> tuple[float, ...]:
        # Returns dim=2 regardless of requested dim
        return (0.1, 0.2)

    original = dict(PROVIDER_REGISTRY)
    try:
        PROVIDER_REGISTRY["wrong-dim"] = wrong_dim_adapter
        embeddings._embed_single.cache_clear()

        with pytest.raises((ValueError, RuntimeError), match="expected_dim"):
            embeddings._embed_single("guardrail-text", "wrong-dim", "model", 4)
    finally:
        PROVIDER_REGISTRY.clear()
        PROVIDER_REGISTRY.update(original)
        embeddings._embed_single.cache_clear()


def test_dim_guardrail_fires_on_ollama_registry_path(monkeypatch) -> None:
    """A wrapper/replacement adapter registered under PROVIDER_REGISTRY['ollama']
    that returns the wrong dim must still trip assert_embed_dim — the ollama branch
    is no longer exempt from the CTI-1 guard (Codex review on PR #2299)."""
    def wrong_dim_ollama(text: str, *, model: str, dim: int, timeout: float) -> tuple[float, ...]:
        return (0.1, 0.2)  # dim=2 regardless of requested dim

    monkeypatch.setenv("EMBED_MAX_INPUT_CHARS", "0")  # force single-chunk path
    original = dict(PROVIDER_REGISTRY)
    try:
        PROVIDER_REGISTRY["ollama"] = wrong_dim_ollama
        embeddings._embed_single.cache_clear()

        with pytest.raises((ValueError, RuntimeError), match="expected_dim"):
            embeddings._embed_single("ollama-guard-text", "ollama", "model", 4)
    finally:
        PROVIDER_REGISTRY.clear()
        PROVIDER_REGISTRY.update(original)
        embeddings._embed_single.cache_clear()


# ---------------------------------------------------------------------------
# Provider-resolution posture (#4191)
# ---------------------------------------------------------------------------

def test_explicit_unservable_embed_provider_fails_loud(monkeypatch) -> None:
    """Every embedding-specific configuration source rejects an unservable name."""
    from unittest.mock import MagicMock

    from app.components.embeddings import resolve_embedding_identity
    from app.components.embeddings import legacy
    from app.settings.models import EmbeddingProfile, EmbeddingProfiles

    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_MODEL", "nomic-embed-text:latest")
    monkeypatch.delenv("EMBED_PRIMARY_PROVIDER", raising=False)

    with pytest.raises(ValueError, match=r"openai.*servable.*gemini.*mock.*ollama"):
        resolve_embedding_identity(
            override_provider="openai",
            use_implicit_profiles=False,
        )

    monkeypatch.setenv("EMBED_PRIMARY_PROVIDER", "deepseek")
    with pytest.raises(ValueError, match=r"deepseek.*EMBED_PRIMARY_PROVIDER"):
        resolve_embedding_identity(use_implicit_profiles=False)
    monkeypatch.delenv("EMBED_PRIMARY_PROVIDER")

    for field_name in ("primary_provider", "provider"):
        profile_kwargs = {
            "provider": "mock",
            "model": "nomic-embed-text:latest",
            "dim": 4,
            field_name: "openai",
        }
        profile = EmbeddingProfile(**profile_kwargs)
        bundle = MagicMock()
        bundle.embedding_profiles = EmbeddingProfiles(
            default_profile="default",
            profiles={"default": profile},
        )
        bundle.global_ = MagicMock()
        bundle.global_.profile = None
        monkeypatch.setattr(legacy, "get_settings_bundle", lambda: bundle)

        with pytest.raises(ValueError, match=rf"openai.*profile\.{field_name}"):
            resolve_embedding_identity(
                profile="default",
                use_implicit_profiles=False,
            )


def test_chat_provider_spillover_does_not_fail_embedding_resolution(monkeypatch) -> None:
    """A chat-only LLM_PROVIDER remains tolerant because it is not embed config."""
    from app.components.embeddings import resolve_embedding_identity
    from app.components.embeddings import legacy
    from app.config import llm as llm_config

    monkeypatch.setattr(legacy, "get_settings_bundle", lambda: None)
    monkeypatch.delenv("EMBED_PRIMARY_PROVIDER", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setattr(llm_config, "_ACTIVE_PROVIDER", None)

    identity = resolve_embedding_identity(use_implicit_profiles=False)

    assert identity.provider == "mock"
    assert identity.model == "mock-embedding"


def test_resolved_provider_name_is_always_servable() -> None:
    """Every non-error resolution result is executable by a live adapter/client."""
    from app.components.embeddings.legacy import (
        _resolve_embedding_provider_name,
        _supported_embed_providers,
    )

    for candidate in (None, "", "anthropic", "not-a-provider"):
        resolved = _resolve_embedding_provider_name(
            candidate,
            provider_source="LLM_PROVIDER",
        )
        assert resolved in _supported_embed_providers()

    for candidate in (*PROVIDER_REGISTRY, "deterministic", "llm", "fake"):
        resolved = _resolve_embedding_provider_name(
            candidate,
            provider_source="override_provider",
        )
        assert resolved in _supported_embed_providers()

    with pytest.raises(ValueError, match="not-a-provider"):
        _resolve_embedding_provider_name(
            "not-a-provider",
            provider_source="EMBED_PRIMARY_PROVIDER",
        )


def test_supported_embed_providers_derive_from_registry() -> None:
    """Registry mutation changes the accepted set without a copied literal edit."""
    from app.components.embeddings.legacy import _supported_embed_providers

    assert _supported_embed_providers() == frozenset(PROVIDER_REGISTRY) | {
        "deterministic"
    }
    assert "openai" not in _supported_embed_providers()
    assert "deepseek" not in _supported_embed_providers()

    original = dict(PROVIDER_REGISTRY)
    try:
        PROVIDER_REGISTRY["sentinel-live-provider"] = (
            lambda text, *, model, dim, timeout: tuple(0.0 for _ in range(dim))
        )
        assert "sentinel-live-provider" in _supported_embed_providers()
    finally:
        PROVIDER_REGISTRY.clear()
        PROVIDER_REGISTRY.update(original)


def test_misconfigured_provider_cannot_silently_write_mock_vectors(
    monkeypatch,
) -> None:
    """The production indexer path fails before adapter dispatch or vector writes."""
    from app.components.embeddings import legacy
    from app.services import indexer

    calls = {"embed": 0, "vector_index": 0}

    class _ObjectStore:
        def get_object(self, _object_id):
            return None

        def save_object(self, *_args, **_kwargs) -> None:
            return None

    def _unexpected_embed(*_args, **_kwargs):
        calls["embed"] += 1
        raise AssertionError("embedding adapter must not run")

    def _unexpected_vector_index():
        calls["vector_index"] += 1
        raise AssertionError("vector index must not be opened")

    monkeypatch.setattr(legacy, "get_settings_bundle", lambda: None)
    monkeypatch.setattr(indexer, "ObjectStore", _ObjectStore)
    monkeypatch.setattr(indexer, "embed_with_fallback", _unexpected_embed)
    monkeypatch.setattr(indexer, "get_vector_index", _unexpected_vector_index)
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("EMBED_PRIMARY_PROVIDER", "openai")
    monkeypatch.setenv("EMBED_MODEL", "nomic-embed-text:latest")

    with pytest.raises(ValueError, match=r"openai.*EMBED_PRIMARY_PROVIDER"):
        indexer.handle_ingest_object_created(
            {
                "object_id": "00000000-0000-0000-0000-000000004191",
                "kind": "note",
                "source_ref": "issue-4191",
                "content": "must not become a mock vector",
                "payload": {},
            }
        )

    assert calls == {"embed": 0, "vector_index": 0}
