from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import httpx
import pytest

from app.model_access.catalog import (
    CATALOG_REFRESH_TTL,
    CatalogError,
    CatalogCache,
    CatalogSelectionPolicy,
    select_latest_compatible,
)
from app.model_access.catalog_discovery import (
    AnthropicCatalogDiscovery,
    OllamaCatalogDiscovery,
    OpenAICatalogDiscovery,
    codex_catalog_snapshot,
)
from app.model_access.ollama_http import OllamaHttpAdapter, OllamaHttpError
from llm_contract import ModelCapabilityRequirements


FETCHED_AT = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
OPENAI_KEY = "sk-openai-catalog-test-secret"
ANTHROPIC_KEY = "sk-ant-catalog-test-secret"


def _json_response(payload: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json=payload)


def test_api_catalogs_fail_closed_without_declared_credentials(monkeypatch) -> None:
    requests: list[httpx.Request] = []
    monkeypatch.setenv("OPENAI_API_KEY", OPENAI_KEY)
    monkeypatch.setenv("ANTHROPIC_API_KEY", ANTHROPIC_KEY)

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise AssertionError("no request should be made without an injected key")

    openai = OpenAICatalogDiscovery(api_key=None, transport=httpx.MockTransport(transport))
    anthropic = AnthropicCatalogDiscovery(api_key=None, transport=httpx.MockTransport(transport))
    try:
        with pytest.raises(CatalogError, match="catalog_auth_failed"):
            openai.discover(fetched_at=FETCHED_AT)
        with pytest.raises(CatalogError, match="catalog_auth_failed"):
            anthropic.discover(fetched_at=FETCHED_AT)
    finally:
        openai.close()
        anthropic.close()

    assert requests == []


@pytest.mark.parametrize("status_code", [401, 403])
def test_provider_auth_failure_does_not_use_stale_snapshot(status_code: int) -> None:
    requests: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return _json_response(
                {"data": [{"id": "gpt-luna", "created": 1_700_000_000}]}
            )
        return httpx.Response(status_code, json={"error": {"message": "redacted"}})

    discovery = OpenAICatalogDiscovery(
        api_key=OPENAI_KEY, transport=httpx.MockTransport(transport)
    )
    cache = CatalogCache()
    try:
        cache.get(
            provider="openai",
            transport_id="openai_api",
            loader=lambda now: discovery.discover(fetched_at=now),
            now=FETCHED_AT,
        )
        with pytest.raises(CatalogError, match="catalog_auth_failed"):
            cache.get(
                provider="openai",
                transport_id="openai_api",
                loader=lambda now: discovery.discover(fetched_at=now),
                now=FETCHED_AT + CATALOG_REFRESH_TTL + timedelta(seconds=1),
            )
    finally:
        discovery.close()

    assert len(requests) == 2


def test_openai_discovery_uses_created_timestamp_not_list_order() -> None:
    requested: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return _json_response(
            {
                "data": [
                    {"id": "gpt-new", "created": 1_790_000_000},
                    {"id": "gpt-old", "created": 1_700_000_000},
                ]
            }
        )

    discovery = OpenAICatalogDiscovery(
        api_key=OPENAI_KEY, transport=httpx.MockTransport(transport)
    )
    try:
        snapshot = discovery.discover(fetched_at=FETCHED_AT)
    finally:
        discovery.close()

    assert len(requested) == 1
    assert requested[0].method == "GET"
    assert requested[0].url.path == "/v1/models"
    assert requested[0].headers["authorization"] == f"Bearer {OPENAI_KEY}"
    assert [item.model for item in snapshot.models] == ["gpt-new", "gpt-old"]
    assert snapshot.models[0].release_at > snapshot.models[1].release_at
    assert not snapshot.models[0].capabilities.structured_output


def test_anthropic_discovery_reads_paged_capability_and_release_metadata() -> None:
    requested: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        if request.url.params.get("after_id") == "claude-a":
            return _json_response(
                {
                    "data": [
                        {
                            "type": "model",
                            "id": "claude-b",
                            "created_at": "2026-08-01T00:00:00Z",
                            "capabilities": {
                                "structured_outputs": {"supported": False},
                                "effort": {
                                    "supported": True,
                                    "low": {"supported": True},
                                },
                            },
                            "max_input_tokens": 100_000,
                            "max_tokens": 8_000,
                        }
                    ],
                    "has_more": False,
                    "last_id": "claude-b",
                }
            )
        return _json_response(
            {
                "data": [
                    {
                        "type": "model",
                        "id": "claude-a",
                        "created_at": "2026-07-01T00:00:00Z",
                        "capabilities": {
                            "structured_outputs": {"supported": True},
                            "effort": {
                                "supported": True,
                                "high": {"supported": True},
                                "low": {"supported": False},
                            },
                        },
                        "max_input_tokens": 200_000,
                        "max_tokens": 16_000,
                        "display_name": "ignored display metadata",
                    }
                ],
                "has_more": True,
                "last_id": "claude-a",
            }
        )

    discovery = AnthropicCatalogDiscovery(
        api_key=ANTHROPIC_KEY, transport=httpx.MockTransport(transport)
    )
    try:
        snapshot = discovery.discover(fetched_at=FETCHED_AT)
    finally:
        discovery.close()

    assert [request.method for request in requested] == ["GET", "GET"]
    assert requested[0].headers["x-api-key"] == ANTHROPIC_KEY
    assert requested[1].url.params["after_id"] == "claude-a"
    by_id = {item.model: item for item in snapshot.models}
    assert by_id["claude-a"].release_at < by_id["claude-b"].release_at
    assert by_id["claude-a"].capabilities.structured_output
    assert by_id["claude-a"].reasoning_efforts == ("high",)
    assert by_id["claude-b"].context_window == 100_000
    assert not by_id["claude-b"].capabilities.native_tools
    assert "display_name" not in json.dumps(snapshot.model_dump(mode="json"))


def test_codex_model_list_order_does_not_auto_promote() -> None:
    models = [
        {
            "model": "gpt-luna",
            "structuredOutputSupported": True,
            "supportedReasoningEfforts": [{"reasoningEffort": "low"}],
        },
        {
            "model": "gpt-nova",
            "structuredOutputSupported": True,
            "supportedReasoningEfforts": [{"reasoningEffort": "low"}],
        },
    ]
    snapshot = codex_catalog_snapshot(models, fetched_at=FETCHED_AT)
    reversed_snapshot = codex_catalog_snapshot(
        list(reversed(models)), fetched_at=FETCHED_AT
    )
    policy = CatalogSelectionPolicy(
        provider="openai",
        accepted_models=("gpt-luna", "gpt-nova"),
        accepted_transports=("codex_cli",),
        required_capabilities=ModelCapabilityRequirements(structured_output=True),
        reasoning_effort="low",
        pinned_model="gpt-luna",
    )

    target = select_latest_compatible(snapshot, policy, now=FETCHED_AT)

    assert target.model == "gpt-luna"
    assert snapshot.snapshot_hash == reversed_snapshot.snapshot_hash


def test_catalog_refresh_is_read_only_and_secret_free() -> None:
    requests: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _json_response(
            {
                "data": [
                    {
                        "id": "gpt-safe",
                        "created": 1_700_000_000,
                        "display_name": "PRIVATE_USER_PROMPT must be discarded",
                    }
                ]
            }
        )

    discovery = OpenAICatalogDiscovery(
        api_key=OPENAI_KEY, transport=httpx.MockTransport(transport)
    )
    try:
        snapshot = discovery.discover(fetched_at=FETCHED_AT)
    finally:
        discovery.close()

    assert [request.method for request in requests] == ["GET"]
    serialized = json.dumps(snapshot.model_dump(mode="json"))
    assert OPENAI_KEY not in serialized
    assert "PRIVATE_USER_PROMPT" not in serialized
    assert "endpoint" not in serialized.lower()


def test_ollama_catalog_uses_local_modified_time_without_calling_inference() -> None:
    requests: list[httpx.Request] = []

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.url.path == "/api/tags"
        return _json_response(
            {
                "models": [
                    {
                        "name": "llama3.1:8b",
                        "model": "llama3.1:8b",
                        "modified_at": "2026-09-22T09:00:00Z",
                        "size": 1,
                        "digest": "not-retained",
                    }
                ]
            }
        )

    adapter = OllamaHttpAdapter(
        base_url="http://127.0.0.1:11434",
        transport=httpx.MockTransport(transport),
    )
    try:
        snapshot = OllamaCatalogDiscovery(adapter).discover(fetched_at=FETCHED_AT)
    finally:
        adapter.close()

    assert len(requests) == 1
    assert snapshot.models[0].local_modified_at is not None
    assert snapshot.models[0].release_at is None
    assert "not-retained" not in json.dumps(snapshot.model_dump(mode="json"))


@pytest.mark.parametrize(
    ("ollama_failure", "catalog_failure"),
    [
        ("ollama_unavailable", "catalog_unavailable"),
        ("ollama_timeout", "catalog_unavailable"),
        ("ollama_response_invalid", "catalog_invalid"),
        ("ollama_response_too_large", "catalog_invalid"),
    ],
)
def test_ollama_catalog_does_not_hide_invalid_metadata_as_an_outage(
    ollama_failure: str,
    catalog_failure: str,
) -> None:
    class FailingAdapter:
        def list_models(self):
            raise OllamaHttpError(ollama_failure)

    with pytest.raises(CatalogError, match=catalog_failure):
        OllamaCatalogDiscovery(FailingAdapter()).discover(fetched_at=FETCHED_AT)  # type: ignore[arg-type]
