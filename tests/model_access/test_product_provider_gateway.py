from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.model_access.adapter_factory import ModelAccessAdapterFactory
from app.model_access.catalog import CatalogCache, CatalogSnapshot
from app.model_access.codex_executor_service import create_codex_executor_app
from app.model_access.provider_api import ProductProviderApiAdapter
import app.model_access.remote_contract as remote_contract


KEY = "synthetic-provider-key-never-return"
SNAPSHOT_HASH = "sha256:" + "a" * 64
_ROUTES = {
    "openai_api": ("openai", "gpt-4.1"),
    "anthropic_api": ("anthropic", "claude-fable-5"),
    "deepseek_api": ("deepseek", "deepseek-chat"),
}


class _Codex:
    def execute(self, **_kwargs: Any) -> Any:
        raise AssertionError("Codex CLI must not receive API-provider routes")

    def preflight(self, **_kwargs: Any) -> Any:
        raise AssertionError("Codex CLI must not receive API-provider routes")

    def list_catalog_models(self) -> list[dict[str, Any]]:
        raise AssertionError("Codex CLI must not receive API-provider routes")


class _Ollama:
    def complete(self, **_kwargs: Any) -> str:
        raise AssertionError("Ollama must not receive API-provider routes")

    def preflight(self, **_kwargs: Any) -> Any:
        raise AssertionError("Ollama must not receive API-provider routes")


def _factory() -> ModelAccessAdapterFactory:
    root = Path(__file__).resolve().parents[2]
    return ModelAccessAdapterFactory.from_declared_sources(
        adapters_path=root / "docs/settings/models/adapters.yaml",
        provider_census_path=root / "docs/settings/models/providers.yaml",
    )


def _local_test_client(app: Any) -> TestClient:
    return TestClient(
        app,
        client=("127.0.0.1", 12345),
    )


def _catalog_payload(provider: str) -> dict[str, Any]:
    if provider == "openai":
        return {
            "data": [
                {"id": "gpt-4.1", "created": 1_760_000_000},
                {"id": "gpt-4.1-mini", "created": 1_760_000_001},
                {"id": "gpt-6-luna", "created": 1_760_000_002},
                {"id": "gpt-5.3-codex-spark", "created": 1_760_000_003},
                {"id": "gpt-5.6-sol", "created": 1_760_000_004},
            ]
        }
    if provider == "anthropic":
        return {
            "data": [
                {
                    "type": "model",
                    "id": "claude-fable-5",
                    "created_at": "2026-09-01T00:00:00Z",
                    "max_input_tokens": 200_000,
                    "max_tokens": 64_000,
                    "capabilities": {
                        "structured_outputs": {"supported": True},
                        "effort": {
                            "supported": True,
                            "low": {"supported": True},
                            "high": {"supported": True},
                        },
                    },
                }
            ],
            "has_more": False,
        }
    return {
        "object": "list",
        "data": [
            {
                "object": "model",
                "id": "deepseek-chat",
                "context_window": 128_000,
                "max_output_tokens": 8_000,
                "effort": {"supported_levels": ["low", "high"]},
            }
        ],
    }


def _api_response(provider: str) -> dict[str, Any]:
    if provider == "anthropic":
        return {
            "type": "message",
            "content": [{"type": "text", "text": "exact Anthropic route"}],
        }
    return {
        "choices": [
            {"message": {"role": "assistant", "content": f"exact {provider} route"}}
        ]
    }


def _payload(transport_id: str) -> dict[str, Any]:
    provider, model = _ROUTES[transport_id]
    return {
        "provider": provider,
        "model": model,
        "reasoning_effort": None,
        "capability_intent": {
            "structured_output": False,
            "native_tools": False,
            "literal_system_role_required": False,
            "max_output_tokens_required": False,
        },
        "trusted_instructions": "Trusted system instructions.",
        "user_input": "Untrusted user request.",
        "output_schema": None,
        "max_output_tokens": None,
    }


def _gateway(
    responder,
    *,
    credential_resolver=None,
    catalog_cache=None,
):
    factory = _factory()
    provider_adapter = ProductProviderApiAdapter(
        adapter_factory=factory,
        credential_resolver=credential_resolver or (lambda _name: KEY),
        transport=httpx.MockTransport(responder),
        catalog_cache=catalog_cache,
    )
    return create_codex_executor_app(
        codex_executor=_Codex(),  # type: ignore[arg-type]
        ollama_adapter=_Ollama(),  # type: ignore[arg-type]
        provider_api_adapter=provider_adapter,
        adapter_factory=factory,
    )


def _bind_catalog_snapshot(client: TestClient, payload: dict[str, Any]) -> None:
    # Prime the host cache; provenance is generated and bound on the Mac and
    # is deliberately absent from Product requests.
    response = client.post("/v1/product/catalog", json={"provider": payload["provider"]})
    assert response.status_code == 200


def _preflight_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": payload["provider"],
        "model": payload["model"],
        "reasoning_effort": payload["reasoning_effort"],
        "capability_intent": payload["capability_intent"],
    }


def test_dispatches_exact_declared_route_without_caller_credentials() -> None:
    sent: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        provider = next(name for name, host in {
            "openai": "api.openai.com",
            "anthropic": "api.anthropic.com",
            "deepseek": "api.deepseek.com",
        }.items() if request.url.host == host)
        transport_id = {
            "api.openai.com": "openai_api",
            "api.anthropic.com": "anthropic_api",
            "api.deepseek.com": "deepseek_api",
        }[request.url.host]
        if request.method == "GET":
            return httpx.Response(200, json=_catalog_payload(provider))
        assert request.method == "POST"
        assert json.loads(request.content)["model"] == _ROUTES[transport_id][1]
        return httpx.Response(200, json=_api_response(provider))

    app = _gateway(respond)
    with _local_test_client(app) as client:
        for transport_id, (provider, _) in _ROUTES.items():
            payload = _payload(transport_id)
            _bind_catalog_snapshot(client, payload)
            preflight = client.post("/v1/product/preflight", json=_preflight_payload(payload))
            assert preflight.status_code == 200
            resolved_route = preflight.json()["route"]
            assert resolved_route["provider"] == provider
            assert resolved_route["model"] == payload["model"]
            assert resolved_route["transport_id"] == transport_id
            assert resolved_route["catalog_snapshot_hash"].startswith("sha256:")
            response = client.post("/v1/product/complete", json=payload)
            with_secret_field = client.post(
                "/v1/product/complete", json={**payload, "api_key": KEY}
            )
            assert response.status_code == 200
            assert response.json()["route"] == resolved_route
            expected_content = (
                "exact Anthropic route" if provider == "anthropic" else f"exact {provider} route"
            )
            assert response.json()["content"] == expected_content
            assert KEY not in response.text
            assert with_secret_field.status_code == 422
    dispatched = [request for request in sent if request.method == "POST"]
    assert len(dispatched) == len(_ROUTES)
    assert all(
        request.headers.get("authorization") or request.headers.get("x-api-key")
        for request in dispatched
    )


def test_provider_native_json_schema_is_sent_and_validated() -> None:
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    for transport_id, (provider, _) in _ROUTES.items():
        if provider == "deepseek":
            continue
        sent: list[httpx.Request] = []

        def respond(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            if request.method == "GET":
                return httpx.Response(200, json=_catalog_payload(provider))
            body = json.loads(request.content)
            if provider == "openai":
                assert body["response_format"]["json_schema"]["schema"] == schema
                return httpx.Response(
                    200,
                    json={"choices": [{"message": {"content": '{"ok":true}'}}]},
                )
            assert body["output_config"]["format"]["schema"] == schema
            return httpx.Response(
                200,
                json={"content": [{"type": "text", "text": '{"ok":true}'}]},
            )

        app = _gateway(respond)
        payload = _payload(transport_id)
        payload["capability_intent"]["structured_output"] = True
        payload["output_schema"] = schema
        with _local_test_client(app) as client:
            _bind_catalog_snapshot(client, payload)
            preflight = client.post("/v1/product/preflight", json=_preflight_payload(payload))
            assert preflight.status_code == 200
            response = client.post("/v1/product/complete", json=payload)
        assert response.status_code == 200
        assert response.json()["content"] == '{"ok":true}'
        assert len([request for request in sent if request.method == "POST"]) == 1


def test_invalid_provider_schema_output_is_terminal_after_one_dispatch() -> None:
    sent: list[httpx.Request] = []
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=_catalog_payload("openai"))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"ok":"not-a-bool"}'}}]},
        )

    app = _gateway(respond)
    payload = _payload("openai_api")
    payload["capability_intent"]["structured_output"] = True
    payload["output_schema"] = schema
    with _local_test_client(app) as client:
        _bind_catalog_snapshot(client, payload)
        response = client.post("/v1/product/complete", json=payload)

    assert response.status_code == 502
    assert response.json() == {"error": {"code": "provider_schema_violation"}}
    assert len([request for request in sent if request.method == "POST"]) == 1


def test_reference_schema_is_rejected_before_provider_or_schema_egress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[httpx.Request] = []
    retrievals: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        raise AssertionError("invalid schema must be rejected before provider access")

    reject_schema_retrieval = remote_contract._reject_schema_retrieval

    def record_schema_retrieval(uri: Any) -> None:
        retrievals.append(str(uri))
        reject_schema_retrieval(uri)

    monkeypatch.setattr(remote_contract, "_reject_schema_retrieval", record_schema_retrieval)
    app = _gateway(respond)
    payload = _payload("openai_api")
    payload["capability_intent"]["structured_output"] = True
    payload["output_schema"] = {
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "$dynamicRef": "https://caller.example/schema.json#answer",
            }
        },
    }

    with _local_test_client(app) as client:
        response = client.post("/v1/product/complete", json=payload)

    assert response.status_code == 422
    assert response.json() == {"error": {"code": "output_schema_invalid"}}
    assert sent == []
    assert retrievals == []


def test_catalog_refresh_uses_verifiable_provider_metadata() -> None:
    requested: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requested.append(f"{request.url.host}{request.url.path}")
        provider_by_host = {
            "api.openai.com": "openai",
            "api.anthropic.com": "anthropic",
            "api.deepseek.com": "deepseek",
        }
        provider = provider_by_host[request.url.host]
        assert request.method == "GET"
        return httpx.Response(200, json=_catalog_payload(provider))

    app = _gateway(respond)
    snapshots = {}
    with _local_test_client(app) as client:
        for transport_id, (provider, _) in _ROUTES.items():
            response = client.post("/v1/product/catalog", json={"provider": provider})
            assert response.status_code == 200
            snapshot = response.json()["snapshot"]
            assert snapshot["provider"] == provider
            assert snapshot["transport_id"] == transport_id
            assert snapshot["snapshot_hash"].startswith("sha256:")
            snapshots[provider] = snapshot

    openai_models = {item["model"]: item for item in snapshots["openai"]["models"]}
    assert openai_models["gpt-4.1"]["release_at"] is not None
    assert openai_models["gpt-4.1"]["capabilities"] == {
        "structured_output": False,
        "native_tools": False,
        "system_prompt_channel": False,
        "deterministic_execution": False,
        "embedding_dimension": None,
    }
    assert openai_models["gpt-4.1"]["structured_output_attested"] is False
    anthropic_model = snapshots["anthropic"]["models"][0]
    assert anthropic_model["capabilities"]["structured_output"] is True
    assert anthropic_model["structured_output_attested"] is True
    assert anthropic_model["reasoning_effort_attested"] is True
    assert anthropic_model["reasoning_efforts"] == ["high", "low"]
    deepseek_model = snapshots["deepseek"]["models"][0]
    assert deepseek_model["release_at"] is None
    assert deepseek_model["reasoning_efforts"] == ["high", "low"]
    assert requested == [
        "api.openai.com/v1/models",
        "api.anthropic.com/v1/models",
        "api.deepseek.com/models",
    ]


def test_catalog_capability_contradiction_blocks_preflight_and_completion() -> None:
    sent: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.method == "GET":
            catalog = _catalog_payload("anthropic")
            catalog["data"][0]["capabilities"]["structured_outputs"]["supported"] = False
            return httpx.Response(200, json=catalog)
        raise AssertionError("capability mismatch must be rejected before inference")

    app = _gateway(respond)
    payload = _payload("anthropic_api")
    payload["capability_intent"]["structured_output"] = True
    payload["output_schema"] = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }
    with _local_test_client(app) as client:
        _bind_catalog_snapshot(client, payload)
        preflight = client.post("/v1/product/preflight", json=_preflight_payload(payload))
        completion = client.post("/v1/product/complete", json=payload)

    assert preflight.status_code == 422
    assert preflight.json() == {"error": {"code": "structured_output_unavailable"}}
    assert completion.status_code == 422
    assert completion.json() == {"error": {"code": "structured_output_unavailable"}}
    assert all(request.method == "GET" for request in sent)


def test_provider_explicitly_disabling_reasoning_blocks_inference() -> None:
    sent: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.method == "GET":
            catalog = _catalog_payload("anthropic")
            catalog["data"][0]["capabilities"]["effort"] = {"supported": False}
            return httpx.Response(200, json=catalog)
        raise AssertionError("unsupported reasoning must be rejected before inference")

    app = _gateway(respond)
    payload = _payload("anthropic_api")
    payload["reasoning_effort"] = "high"
    with _local_test_client(app) as client:
        _bind_catalog_snapshot(client, payload)
        preflight = client.post("/v1/product/preflight", json=_preflight_payload(payload))
        completion = client.post("/v1/product/complete", json=payload)

    expected = {"error": {"code": "reasoning_effort_unavailable"}}
    assert preflight.status_code == 422
    assert preflight.json() == expected
    assert completion.status_code == 422
    assert completion.json() == expected
    assert all(request.method == "GET" for request in sent)


@pytest.mark.parametrize(
    ("transport_id", "model_id"),
    [
        ("openai_api", "gpt-4.1"),
        ("openai_api", "gpt-5.3-codex-spark"),
        # Live provider catalogs attest these efforts, but the static census is
        # intentionally unknown; provider data cannot grant the missing authority.
        ("anthropic_api", "claude-fable-5"),
        ("deepseek_api", "deepseek-chat"),
    ],
)
def test_reasoning_requires_static_model_declared_efforts(
    transport_id: str, model_id: str
) -> None:
    sent: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.method == "GET":
            provider = _ROUTES[transport_id][0]
            return httpx.Response(200, json=_catalog_payload(provider))
        return httpx.Response(200, json=_api_response(_ROUTES[transport_id][0]))

    app = _gateway(respond)
    payload = _payload(transport_id)
    payload["model"] = model_id
    payload["reasoning_effort"] = "high"
    with _local_test_client(app) as client:
        _bind_catalog_snapshot(client, payload)
        preflight = client.post("/v1/product/preflight", json=_preflight_payload(payload))
        completion = client.post("/v1/product/complete", json=payload)

    expected = {"error": {"code": "reasoning_effort_unavailable"}}
    assert preflight.status_code == 422
    assert preflight.json() == expected
    assert completion.status_code == 422
    assert completion.json() == expected
    assert all(request.method == "GET" for request in sent)


@pytest.mark.parametrize("effort", ["high", "none"])
def test_declared_openai_api_reasoning_effort_passes_preflight_and_dispatch(
    effort: str,
) -> None:
    sent: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=_catalog_payload("openai"))
        return httpx.Response(200, json=_api_response("openai"))

    app = _gateway(respond)
    payload = _payload("openai_api")
    payload["model"] = "gpt-5.6-sol"
    payload["reasoning_effort"] = effort
    with _local_test_client(app) as client:
        _bind_catalog_snapshot(client, payload)
        preflight = client.post("/v1/product/preflight", json=_preflight_payload(payload))
        completion = client.post("/v1/product/complete", json=payload)

    assert preflight.status_code == 200
    assert completion.status_code == 200
    dispatched = [request for request in sent if request.method == "POST"]
    assert len(dispatched) == 1
    assert json.loads(dispatched[0].content)["reasoning_effort"] == effort


def test_default_output_limit_is_checked_against_provider_catalog() -> None:
    sent: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.method == "GET":
            catalog = _catalog_payload("anthropic")
            catalog["data"][0]["max_tokens"] = 2048
            return httpx.Response(200, json=catalog)
        raise AssertionError("an over-limit default must be rejected before inference")

    app = _gateway(respond)
    payload = _payload("anthropic_api")
    with _local_test_client(app) as client:
        _bind_catalog_snapshot(client, payload)
        response = client.post("/v1/product/complete", json=payload)

    assert response.status_code == 422
    assert response.json() == {"error": {"code": "max_output_tokens_unavailable"}}
    assert all(request.method == "GET" for request in sent)


def test_model_missing_from_provider_catalog_is_rejected_before_inference() -> None:
    sent: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.method == "GET":
            catalog = _catalog_payload("anthropic")
            catalog["data"][0]["id"] = "claude-unlisted-model"
            return httpx.Response(200, json=catalog)
        raise AssertionError("an unlisted model must be rejected before inference")

    app = _gateway(respond)
    payload = _payload("anthropic_api")
    with _local_test_client(app) as client:
        _bind_catalog_snapshot(client, payload)
        response = client.post("/v1/product/preflight", json=_preflight_payload(payload))

    assert response.status_code == 422
    assert response.json() == {"error": {"code": "provider_model_unavailable"}}
    assert all(request.method == "GET" for request in sent)


class _RefreshOnFourthCatalogRead(CatalogCache):
    """Advance only the completion read past TTL to exercise gateway drift handling."""

    def __init__(self) -> None:
        super().__init__()
        self._reads = 0
        self._base_time = datetime.now(timezone.utc)

    def get(
        self,
        *,
        provider: str,
        transport_id: str,
        loader: Callable[[datetime], CatalogSnapshot],
        now: datetime | None = None,
    ) -> CatalogSnapshot:
        self._reads += 1
        now = self._base_time + (
            timedelta(minutes=6) if self._reads >= 4 else timedelta(0)
        )
        return super().get(
            provider=provider,
            transport_id=transport_id,
            loader=loader,
            now=now,
        )


class _StaleOnSecondCatalogRead(CatalogCache):
    """Serve a cached snapshot as stale after a simulated six-minute outage."""

    def __init__(self) -> None:
        super().__init__()
        self._reads = 0
        self._base_time = datetime.now(timezone.utc)

    def get(
        self,
        *,
        provider: str,
        transport_id: str,
        loader: Callable[[datetime], CatalogSnapshot],
        now: datetime | None = None,
    ) -> CatalogSnapshot:
        self._reads += 1
        fixed_time = self._base_time
        if self._reads >= 2:
            fixed_time += timedelta(minutes=6)
        return super().get(
            provider=provider,
            transport_id=transport_id,
            loader=loader,
            now=fixed_time,
        )


def test_stale_catalog_cannot_authorize_preflight_or_inference() -> None:
    sent: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.method == "GET" and len([item for item in sent if item.method == "GET"]) == 1:
            return httpx.Response(200, json=_catalog_payload("openai"))
        if request.method == "GET":
            return httpx.Response(503)
        raise AssertionError("stale catalog must reject before inference")

    app = _gateway(respond, catalog_cache=_StaleOnSecondCatalogRead())
    payload = _payload("openai_api")
    with _local_test_client(app) as client:
        _bind_catalog_snapshot(client, payload)
        preflight = client.post("/v1/product/preflight", json=_preflight_payload(payload))
        completion = client.post("/v1/product/complete", json=payload)

    expected = {"error": {"code": "catalog_stale"}}
    assert preflight.status_code == 503
    assert preflight.json() == expected
    assert completion.status_code == 503
    assert completion.json() == expected
    assert all(request.method == "GET" for request in sent)


def test_completion_receipt_binds_the_catalog_snapshot_used_for_that_request() -> None:
    sent: list[httpx.Request] = []
    catalog_reads = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal catalog_reads
        sent.append(request)
        if request.method == "GET":
            catalog_reads += 1
            payload = _catalog_payload("openai")
            if catalog_reads > 1:
                payload["data"][0]["created"] += 1
            return httpx.Response(200, json=payload)
        if request.method == "POST":
            return httpx.Response(200, json=_api_response("openai"))
        raise AssertionError("unexpected request")

    app = _gateway(respond, catalog_cache=_RefreshOnFourthCatalogRead())
    payload = _payload("openai_api")
    with _local_test_client(app) as client:
        _bind_catalog_snapshot(client, payload)
        preflight = client.post("/v1/product/preflight", json=_preflight_payload(payload))
        completion = client.post("/v1/product/complete", json=payload)

    assert preflight.status_code == 200
    assert completion.status_code == 200
    assert completion.json()["route"]["catalog_snapshot_hash"] != preflight.json()["route"]["catalog_snapshot_hash"]
    assert completion.json()["content"] == "exact openai route"
    assert catalog_reads == 2
    assert len([request for request in sent if request.method == "POST"]) == 1


def test_dispatch_failure_is_terminal_and_receipt_is_secret_free() -> None:
    sent: list[httpx.Request] = []

    def fail(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=_catalog_payload("openai"))
        return httpx.Response(503, json={"error": {"message": KEY}})

    app = _gateway(fail)
    payload = _payload("openai_api")
    with _local_test_client(app) as client:
        _bind_catalog_snapshot(client, payload)
        preflight = client.post("/v1/product/preflight", json=_preflight_payload(payload))
        assert preflight.status_code == 200
        response = client.post("/v1/product/complete", json=payload)

    assert response.status_code == 503
    assert response.json() == {"error": {"code": "provider_unavailable"}}
    assert len([request for request in sent if request.method == "POST"]) == 1
    assert KEY not in response.text
    assert response.json().get("route") is None


def test_preflight_requires_host_credential_and_exact_provider_model() -> None:
    sent: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json=_catalog_payload("openai"))

    app = _gateway(respond, credential_resolver=lambda _name: None)
    payload = _payload("openai_api")
    preflight = {
        "provider": payload["provider"],
        "model": payload["model"],
        "reasoning_effort": None,
        "capability_intent": payload["capability_intent"],
    }
    with _local_test_client(app) as client:
        response = client.post("/v1/product/preflight", json=preflight)

    assert response.status_code == 503
    assert response.json() == {"error": {"code": "credential_unavailable"}}
    assert sent == []


def test_preflight_rejects_caller_selected_transport_and_catalog_provenance() -> None:
    sent: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json=_catalog_payload("openai"))

    app = _gateway(respond)
    payload = _payload("openai_api")
    with _local_test_client(app) as client:
        _bind_catalog_snapshot(client, payload)
        response = client.post(
            "/v1/product/preflight",
            json={**_preflight_payload(payload), "transport_id": "codex_cli", "catalog_snapshot_hash": "sha256:" + "f" * 64},
        )

    assert response.status_code == 422
    assert response.json() == {"error": {"code": "invalid_request"}}
    assert len([request for request in sent if request.method == "POST"]) == 0


def test_completion_rejects_caller_supplied_catalog_provenance() -> None:
    payload = _payload("openai_api")
    app = _gateway(lambda _request: httpx.Response(500))
    with _local_test_client(app) as client:
        response = client.post(
            "/v1/product/complete",
            json={**payload, "catalog_snapshot_ref": "catalog.unrelated", "catalog_snapshot_hash": SNAPSHOT_HASH},
        )
    assert response.status_code == 422
    assert response.json() == {"error": {"code": "invalid_request"}}
