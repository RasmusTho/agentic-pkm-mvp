"""Tests for the Google Gemini embedding adapter (EMBEDREL-04, GitHub issue #2295).

All tests mock httpx.post — no real API key or network call is needed in CI.

Verify targets from the issue:
  - test_returns_768_dim_vector
  - test_request_payload_format
  - test_no_key_unavailable_no_network
  - test_error_classification
  - test_key_and_content_not_logged
  - test_wrong_dim_raises_value_error
  - test_gemini_registered_in_provider_registry
"""
from __future__ import annotations

import logging
import math

import httpx
import pytest

from app.llm.gemini_embeddings import (
    GeminiAuthError,
    GeminiTransientError,
    GeminiUnavailableError,
    _gemini_embed_one,
    embed_gemini_text,
)
from app.llm.embeddings import PROVIDER_REGISTRY

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_KEY = "FAKE_TEST_KEY_DO_NOT_LOG"
_MODEL = "gemini-embedding-001"
_DIM = 768
_TIMEOUT = 10.0


def _make_vec(n: int, value: float = 0.5) -> list[float]:
    """Return an *n*-element vector of *value*."""
    return [value] * n


def _make_ok_response(values: list[float], url: str = "https://example.com") -> httpx.Response:
    return httpx.Response(
        200,
        json={"embedding": {"values": values}},
        request=httpx.Request("POST", url),
    )


def _make_error_response(status: int, url: str = "https://example.com") -> httpx.Response:
    return httpx.Response(
        status,
        json={"error": {"message": f"HTTP {status} error", "status": "ERROR"}},
        request=httpx.Request("POST", url),
    )


def _set_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", _FAKE_KEY)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)


def _unset_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)


# ---------------------------------------------------------------------------
# test_returns_768_dim_vector
# ---------------------------------------------------------------------------


def test_returns_768_dim_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path: mock returns a 768-element response; assert len==768 and L2-normalized."""
    _set_key(monkeypatch)
    raw = _make_vec(_DIM, 0.5)
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _make_ok_response(raw))

    result = embed_gemini_text("Hello world", model=_MODEL, dim=_DIM, timeout=_TIMEOUT)

    assert isinstance(result, tuple)
    assert len(result) == _DIM
    norm = math.sqrt(sum(v * v for v in result))
    assert abs(norm - 1.0) < 1e-5, f"Expected L2-normalized vector (norm≈1.0), got norm={norm}"


# ---------------------------------------------------------------------------
# test_request_payload_format
# ---------------------------------------------------------------------------


def test_request_payload_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """Assert httpx.post is called with the correct REST payload.

    Specifically:
      - model field = "models/gemini-embedding-001"
      - embedContentConfig.outputDimensionality == 768 (camelCase, nested)
      - snake_case output_dimensionality is NOT present
    """
    _set_key(monkeypatch)
    raw = _make_vec(_DIM, 0.1)
    captured: list[dict] = []

    def fake_post(url: str, *, json: dict, headers: dict, timeout: float) -> httpx.Response:
        captured.append({"url": url, "json": json, "headers": headers})
        return _make_ok_response(raw, url)

    monkeypatch.setattr(httpx, "post", fake_post)

    embed_gemini_text("test text", model=_MODEL, dim=_DIM, timeout=_TIMEOUT)

    assert len(captured) == 1
    call = captured[0]
    body = call["json"]

    # Model field must use "models/" prefix
    assert body["model"] == f"models/{_MODEL}", (
        f"Expected model='models/{_MODEL}', got {body['model']!r}"
    )

    # Content structure
    assert body["content"] == {"parts": [{"text": "test text"}]}

    # embedContentConfig must be present with camelCase outputDimensionality
    cfg = body.get("embedContentConfig")
    assert isinstance(cfg, dict), f"embedContentConfig missing from payload: {body}"
    assert cfg.get("outputDimensionality") == _DIM, (
        f"outputDimensionality must be {_DIM} (camelCase), got {cfg!r}"
    )

    # snake_case must NOT be present (would be silently ignored by REST → returns 3072)
    assert "output_dimensionality" not in body, (
        "snake_case output_dimensionality must not appear in the REST payload"
    )

    # URL must include the model endpoint
    assert _MODEL in call["url"], f"Expected model name in URL, got {call['url']!r}"


# ---------------------------------------------------------------------------
# test_no_key_unavailable_no_network
# ---------------------------------------------------------------------------


def test_no_key_unavailable_no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """When both GEMINI_API_KEY and GOOGLE_API_KEY are unset, GeminiUnavailableError
    is raised before any network call (httpx.post must NOT be called)."""
    _unset_keys(monkeypatch)
    called: list[bool] = []

    def should_not_be_called(*args, **kwargs):
        called.append(True)
        return _make_ok_response(_make_vec(_DIM))

    monkeypatch.setattr(httpx, "post", should_not_be_called)

    with pytest.raises(GeminiUnavailableError, match="no API key configured"):
        embed_gemini_text("text", model=_MODEL, dim=_DIM, timeout=_TIMEOUT)

    assert not called, "httpx.post must NOT be called when no key is configured"


def test_no_key_fallback_to_google_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """GOOGLE_API_KEY is accepted as the fallback key source."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", _FAKE_KEY)
    raw = _make_vec(_DIM, 0.3)
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _make_ok_response(raw))

    result = embed_gemini_text("text", model=_MODEL, dim=_DIM, timeout=_TIMEOUT)
    assert len(result) == _DIM


# ---------------------------------------------------------------------------
# test_error_classification
# ---------------------------------------------------------------------------


def test_error_classification_429(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 429 → GeminiTransientError (retry-eligible)."""
    _set_key(monkeypatch)
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _make_error_response(429))
    with pytest.raises(GeminiTransientError):
        embed_gemini_text("text", model=_MODEL, dim=_DIM, timeout=_TIMEOUT)


def test_error_classification_500(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 500 → GeminiTransientError (retry-eligible)."""
    _set_key(monkeypatch)
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _make_error_response(500))
    with pytest.raises(GeminiTransientError):
        embed_gemini_text("text", model=_MODEL, dim=_DIM, timeout=_TIMEOUT)


def test_error_classification_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 503 → GeminiTransientError (retry-eligible)."""
    _set_key(monkeypatch)
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _make_error_response(503))
    with pytest.raises(GeminiTransientError):
        embed_gemini_text("text", model=_MODEL, dim=_DIM, timeout=_TIMEOUT)


def test_error_classification_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 401 → GeminiAuthError (non-transient)."""
    _set_key(monkeypatch)
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _make_error_response(401))
    with pytest.raises(GeminiAuthError):
        embed_gemini_text("text", model=_MODEL, dim=_DIM, timeout=_TIMEOUT)


def test_error_classification_403(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 403 → GeminiAuthError (non-transient)."""
    _set_key(monkeypatch)
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _make_error_response(403))
    with pytest.raises(GeminiAuthError):
        embed_gemini_text("text", model=_MODEL, dim=_DIM, timeout=_TIMEOUT)


def test_error_classification_400(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 400 (bad key / bad request) → GeminiAuthError (non-transient)."""
    _set_key(monkeypatch)
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _make_error_response(400))
    with pytest.raises(GeminiAuthError):
        embed_gemini_text("text", model=_MODEL, dim=_DIM, timeout=_TIMEOUT)


def test_error_classification_connect_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """httpx.ConnectError → GeminiTransientError (retry-eligible)."""
    _set_key(monkeypatch)

    def raise_connect(*a, **kw):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", raise_connect)
    with pytest.raises(GeminiTransientError):
        embed_gemini_text("text", model=_MODEL, dim=_DIM, timeout=_TIMEOUT)


def test_error_classification_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """httpx.TimeoutException → GeminiTransientError (retry-eligible)."""
    _set_key(monkeypatch)

    def raise_timeout(*a, **kw):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx, "post", raise_timeout)
    with pytest.raises(GeminiTransientError):
        embed_gemini_text("text", model=_MODEL, dim=_DIM, timeout=_TIMEOUT)


# ---------------------------------------------------------------------------
# test_key_and_content_not_logged
# ---------------------------------------------------------------------------


def test_key_and_content_not_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The API key value and note content (text) must never appear in any log output.

    Covers: happy path, transient error, auth error.
    """
    _set_key(monkeypatch)
    secret_text = "SUPER_SECRET_NOTE_CONTENT_DO_NOT_LOG"

    with caplog.at_level(logging.DEBUG, logger="app"):
        # Happy path
        raw = _make_vec(_DIM, 0.2)
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: _make_ok_response(raw))
        embed_gemini_text(secret_text, model=_MODEL, dim=_DIM, timeout=_TIMEOUT)

        # Transient error
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: _make_error_response(500))
        with pytest.raises(GeminiTransientError):
            embed_gemini_text(secret_text, model=_MODEL, dim=_DIM, timeout=_TIMEOUT)

        # Auth error
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: _make_error_response(401))
        with pytest.raises(GeminiAuthError):
            embed_gemini_text(secret_text, model=_MODEL, dim=_DIM, timeout=_TIMEOUT)

    all_logs = "\n".join(r.getMessage() for r in caplog.records)

    assert _FAKE_KEY not in all_logs, (
        f"API key value ({_FAKE_KEY!r}) must never appear in log output"
    )
    assert secret_text not in all_logs, (
        f"Note content ({secret_text!r}) must never appear in log output"
    )


# ---------------------------------------------------------------------------
# test_wrong_dim_raises_value_error
# ---------------------------------------------------------------------------


def test_wrong_dim_raises_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the API returns a vector of length != 768 (e.g., the default 3072 because
    outputDimensionality was ignored), assert_embed_dim raises ValueError.
    The index must never be silently corrupted with wrong-dim vectors (CTI-1)."""
    _set_key(monkeypatch)
    # Simulate the API ignoring outputDimensionality and returning its 3072 default
    wrong_dim_vec = _make_vec(3072, 0.1)
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _make_ok_response(wrong_dim_vec))

    with pytest.raises(ValueError, match="dim mismatch"):
        embed_gemini_text("text", model=_MODEL, dim=_DIM, timeout=_TIMEOUT)


# ---------------------------------------------------------------------------
# test_gemini_registered_in_provider_registry
# ---------------------------------------------------------------------------


def test_gemini_registered_in_provider_registry() -> None:
    """PROVIDER_REGISTRY['gemini'] is callable (EMBEDREL-04 registered the adapter)."""
    assert "gemini" in PROVIDER_REGISTRY, (
        "'gemini' must be registered in PROVIDER_REGISTRY"
    )
    assert callable(PROVIDER_REGISTRY["gemini"]), (
        "PROVIDER_REGISTRY['gemini'] must be a callable"
    )


# ---------------------------------------------------------------------------
# env var overrides: EMBED_GEMINI_MODEL and GEMINI_BASE_URL
# ---------------------------------------------------------------------------


def test_embed_gemini_model_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """EMBED_GEMINI_MODEL env var controls the model name sent in the request."""
    _set_key(monkeypatch)
    monkeypatch.setenv("EMBED_GEMINI_MODEL", "custom-model-x")
    raw = _make_vec(_DIM, 0.5)
    captured: list[dict] = []

    def fake_post(url: str, *, json: dict, **kw) -> httpx.Response:
        captured.append({"url": url, "json": json})
        return _make_ok_response(raw, url)

    monkeypatch.setattr(httpx, "post", fake_post)

    _gemini_embed_one("text", model="custom-model-x", dim=_DIM, timeout=_TIMEOUT)

    assert len(captured) == 1
    assert captured[0]["json"]["model"] == "models/custom-model-x", (
        f"Expected model 'models/custom-model-x', got {captured[0]['json']['model']!r}"
    )


def test_gemini_base_url_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """GEMINI_BASE_URL env var causes httpx.post to target that base URL."""
    _set_key(monkeypatch)
    monkeypatch.setenv("GEMINI_BASE_URL", "http://gemini.test:1234")
    raw = _make_vec(_DIM, 0.5)
    captured: list[str] = []

    def fake_post(url: str, **kw) -> httpx.Response:
        captured.append(url)
        return _make_ok_response(raw, url)

    monkeypatch.setattr(httpx, "post", fake_post)

    # Call via embed_gemini_text with explicit base_url
    embed_gemini_text(
        "text",
        model=_MODEL,
        dim=_DIM,
        timeout=_TIMEOUT,
        base_url="http://gemini.test:1234",
    )

    assert len(captured) == 1
    assert "gemini.test:1234" in captured[0], (
        f"Expected GEMINI_BASE_URL host in request URL, got {captured[0]!r}"
    )


# ---------------------------------------------------------------------------
# _gemini_embed_one wrapper (ProviderAdapter registration target)
# ---------------------------------------------------------------------------


def test_gemini_embed_one_wrapper_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """_gemini_embed_one matches ProviderAdapter signature and delegates correctly."""
    _set_key(monkeypatch)
    raw = _make_vec(_DIM, 0.4)
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _make_ok_response(raw))

    result = _gemini_embed_one("hello", model=_MODEL, dim=_DIM, timeout=_TIMEOUT)
    assert isinstance(result, tuple)
    assert len(result) == _DIM
    norm = math.sqrt(sum(v * v for v in result))
    assert abs(norm - 1.0) < 1e-5


def test_gemini_embed_one_no_key_raises_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """_gemini_embed_one propagates GeminiUnavailableError when no key is set."""
    _unset_keys(monkeypatch)
    with pytest.raises(GeminiUnavailableError):
        _gemini_embed_one("text", model=_MODEL, dim=_DIM, timeout=_TIMEOUT)


# ---------------------------------------------------------------------------
# Queue transient-classification integration (Codex review on PR #2302)
# ---------------------------------------------------------------------------

def test_gemini_transient_error_classified_transient_by_queue() -> None:
    """GeminiTransientError (HTTP 429/5xx — no httpx chain) must be recognized as
    transient by the embedding queue, so it is retried/backed-off rather than
    dead-lettered. Guards the adapter↔queue integration."""
    from app.llm.embed_queue import _is_transient_embed_error

    assert _is_transient_embed_error(GeminiTransientError("Gemini embedContent HTTP 503")) is True
    # Chained form (e.g. wrapped) is also recognized via __cause__.
    wrapped = RuntimeError("outer")
    wrapped.__cause__ = GeminiTransientError("HTTP 429")
    assert _is_transient_embed_error(wrapped) is True


def test_gemini_auth_and_unavailable_not_transient() -> None:
    """Auth/unavailable errors are non-transient — the queue must not retry them."""
    from app.llm.embed_queue import _is_transient_embed_error

    assert _is_transient_embed_error(GeminiAuthError("Gemini embedContent HTTP 403")) is False
    assert _is_transient_embed_error(GeminiUnavailableError("no key")) is False


def test_gemini_embed_one_ignores_non_gemini_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the registry passes the index's generic model (e.g. nomic-embed-text)
    because gemini was selected from a non-gemini profile, the adapter must still
    request a Gemini model, not /models/nomic-embed-text:latest (Codex P1, #2302)."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("EMBED_GEMINI_MODEL", raising=False)  # default gemini-embedding-001
    captured = {}

    def fake_embed(text, *, model, dim, timeout, base_url=None):
        captured["model"] = model
        return tuple([0.0] * dim)

    monkeypatch.setattr("app.llm.gemini_embeddings.embed_gemini_text", fake_embed)
    _gemini_embed_one("hello", model="nomic-embed-text:latest", dim=_DIM, timeout=_TIMEOUT)
    assert captured["model"] == "gemini-embedding-001"

    # An explicit gemini model IS honored:
    captured.clear()
    _gemini_embed_one("hello", model="gemini-embedding-2", dim=_DIM, timeout=_TIMEOUT)
    assert captured["model"] == "gemini-embedding-2"

    # EMBED_GEMINI_MODEL override is used when a non-gemini model is passed:
    captured.clear()
    monkeypatch.setenv("EMBED_GEMINI_MODEL", "gemini-embedding-001")
    _gemini_embed_one("hello", model="", dim=_DIM, timeout=_TIMEOUT)
    assert captured["model"] == "gemini-embedding-001"


def test_error_classification_408_is_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 408 (request timeout) is retryable, matching the shared transient
    classifier — not a non-transient auth error (Codex P2, #2302)."""
    _set_key(monkeypatch)
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _make_error_response(408))
    with pytest.raises(GeminiTransientError):
        embed_gemini_text("text", model=_MODEL, dim=_DIM, timeout=_TIMEOUT)


def test_gemini_provider_identity_uses_gemini_model() -> None:
    """When provider=gemini, the resolved embedding model is a Gemini model — never
    the index's generic EMBED_MODEL — so the persisted identity matches the vector
    actually produced (Codex P1 provenance, #2302)."""
    from app.components.embeddings.legacy import _resolve_embedding_model

    # generic/index model passed in → replaced with the Gemini default
    assert _resolve_embedding_model("gemini", None, "nomic-embed-text:latest") == "gemini-embedding-001"
    # explicit Gemini override honored
    assert _resolve_embedding_model("gemini", "gemini-embedding-2", None) == "gemini-embedding-2"


def test_gemini_provider_identity_respects_embed_gemini_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.components.embeddings.legacy import _resolve_embedding_model

    monkeypatch.setenv("EMBED_GEMINI_MODEL", "gemini-embedding-001")
    assert _resolve_embedding_model("gemini", None, "nomic-embed-text:latest") == "gemini-embedding-001"


def test_gemini_provider_identity_honors_profile_gemini_model() -> None:
    """A profile that selects a Gemini model (configured_model) is honored, while a
    non-Gemini configured model is still discarded (Codex P2, #2302)."""
    from app.components.embeddings.legacy import _resolve_embedding_model

    # profile-set Gemini model honored
    assert _resolve_embedding_model("gemini", None, "gemini-embedding-2") == "gemini-embedding-2"
    # non-gemini configured model discarded → default
    assert _resolve_embedding_model("gemini", None, "nomic-embed-text:latest") == "gemini-embedding-001"
    # override (gemini) still wins over a profile model
    assert _resolve_embedding_model("gemini", "gemini-embedding-001", "gemini-embedding-2") == "gemini-embedding-001"
