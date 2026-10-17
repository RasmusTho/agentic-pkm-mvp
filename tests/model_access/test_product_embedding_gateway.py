from __future__ import annotations

import asyncio
import json
from pathlib import Path
import threading
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.model_access.adapter_factory import ModelAccessAdapterFactory
from app.model_access.codex_executor_service import create_codex_executor_app
from app.model_access.ollama_http import OllamaHttpAdapter, OllamaHttpCatalogModel
from app.model_access.provider_api import ProductProviderApiAdapter
from app.model_access.codex_remote_transport import CodexRemoteTransport, RemoteEmbeddingError
from app.model_access.remote_contract import ProductEmbeddingRequest


GEMINI_KEY = "synthetic-gemini-key-never-return"
_INPUT = "synthetic embedding request text"


class _Codex:
    def execute(self, **_kwargs: Any) -> Any:
        raise AssertionError("embedding routes must not reach Codex CLI")

    def preflight(self, **_kwargs: Any) -> Any:
        raise AssertionError("embedding routes must not reach Codex CLI")

    def list_catalog_models(self) -> list[dict[str, Any]]:
        raise AssertionError("embedding routes must not reach Codex CLI")


def _factory() -> ModelAccessAdapterFactory:
    root = Path(__file__).resolve().parents[2]
    return ModelAccessAdapterFactory.from_declared_sources(
        adapters_path=root / "docs/settings/models/adapters.yaml",
        provider_census_path=root / "docs/settings/models/providers.yaml",
    )


def _client(app: Any) -> TestClient:
    return TestClient(app, client=("127.0.0.1", 12345))


def _gemini_adapter(transport: httpx.BaseTransport) -> ProductProviderApiAdapter:
    return ProductProviderApiAdapter(
        adapter_factory=_factory(),
        credential_resolver=lambda name: GEMINI_KEY if name == "GEMINI_API_KEY" else None,
        transport=transport,
    )


def _request(
    *, provider: str = "gemini", model: str = "gemini-embedding-001", dimensions: int = 768
) -> dict[str, Any]:
    return {
        "provider": provider,
        "model": model,
        "dimensions": dimensions,
        "input_text": _INPUT,
    }


def test_product_api_dispatches_declared_embedding_once_with_host_provenance() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"embedding": {"values": [0.25] * 768}},
            request=request,
        )

    adapter = _gemini_adapter(httpx.MockTransport(handler))
    app = create_codex_executor_app(
        codex_executor=_Codex(),  # type: ignore[arg-type]
        provider_api_adapter=adapter,
        adapter_factory=_factory(),
    )
    with _client(app) as client:
        catalog = client.post(
            "/v1/product/catalog",
            json={"provider": "gemini", "model": "gemini-embedding-001"},
        )
        response = client.post("/v1/product/embed", json=_request())

    assert catalog.status_code == 200
    assert catalog.json()["snapshot"]["transport_id"] == "gemini_api"
    assert response.status_code == 200
    body = response.json()
    assert body["route"]["provider"] == "gemini"
    assert body["route"]["model"] == "gemini-embedding-001"
    assert body["route"]["transport_id"] == "gemini_api"
    assert body["route"]["catalog_snapshot_ref"] == "catalog.gemini_gemini_api"
    assert body["route"]["catalog_snapshot_hash"].startswith("sha256:")
    assert body["dimensions"] == 768
    assert len(body["vector"]) == 768
    assert len(requests) == 1
    outbound = requests[0]
    assert outbound.method == "POST"
    assert str(outbound.url) == (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-embedding-001:embedContent"
    )
    assert outbound.headers["x-goog-api-key"] == GEMINI_KEY
    outbound_json = json.loads(outbound.content)
    assert outbound_json["embedContentConfig"]["outputDimensionality"] == 768
    assert _INPUT in outbound.content.decode("utf-8")
    assert "transport_id" not in outbound_json
    assert "api_key" not in outbound_json
    assert _INPUT not in response.text
    assert GEMINI_KEY not in response.text


def test_dimension_mismatch_fails_before_embedding_dispatch() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise AssertionError("dimension mismatch must fail before provider access")

    adapter = _gemini_adapter(httpx.MockTransport(handler))
    app = create_codex_executor_app(
        codex_executor=_Codex(),  # type: ignore[arg-type]
        provider_api_adapter=adapter,
        adapter_factory=_factory(),
    )
    with _client(app) as client:
        response = client.post(
            "/v1/product/embed", json=_request(dimensions=384)
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "embedding_dimension_unavailable"
    assert requests == []


def test_ollama_embedding_uses_one_api_embed_request_without_legacy_fallback() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET" and request.url.path.endswith("/api/tags"):
            return httpx.Response(
                200,
                json={"models": [{"name": "nomic-embed-text:latest"}]},
                request=request,
            )
        if request.method == "POST" and request.url.path.endswith("/api/show"):
            return httpx.Response(
                200, json={"capabilities": ["embedding"]}, request=request
            )
        if request.method == "POST" and request.url.path.endswith("/api/embed"):
            body = json.loads(request.content)
            assert body["model"] == "nomic-embed-text:latest"
            assert body["dimensions"] == 768
            assert body["truncate"] is False
            return httpx.Response(
                200,
                json={
                    "model": "nomic-embed-text:latest",
                    "embeddings": [[0.5] * 768],
                },
                request=request,
            )
        raise AssertionError(f"unexpected Ollama request: {request.method} {request.url}")

    ollama = OllamaHttpAdapter(
        base_url="http://127.0.0.1:11434",
        transport=httpx.MockTransport(handler),
    )
    app = create_codex_executor_app(
        codex_executor=_Codex(),  # type: ignore[arg-type]
        ollama_adapter=ollama,
        adapter_factory=_factory(),
    )
    with _client(app) as client:
        response = client.post(
            "/v1/product/embed",
            json=_request(
                provider="ollama", model="nomic-embed-text:latest"
            ),
        )

    assert response.status_code == 200
    assert response.json()["route"]["transport_id"] == "ollama_http"
    assert response.json()["dimensions"] == 768
    assert len(response.json()["vector"]) == 768
    embed_requests = [request for request in requests if request.url.path.endswith("/api/embed")]
    assert len(embed_requests) == 1
    assert not any(request.url.path.endswith("/api/embeddings") for request in requests)
    assert not any(request.url.path.endswith("/v1/embeddings") for request in requests)


@pytest.mark.parametrize("failure", [httpx.ReadTimeout, httpx.ReadError])
def test_ollama_embedding_timeout_is_single_dispatch_and_terminal(
    failure: type[httpx.TransportError],
) -> None:
    requests: list[httpx.Request] = []
    product_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "nomic-embed-text:latest"}]}
            )
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["embedding"]})
        assert request.url.path == "/api/embed"
        raise failure("synthetic private provider failure", request=request)

    ollama = OllamaHttpAdapter(
        base_url="http://127.0.0.1:11434", transport=httpx.MockTransport(handler)
    )
    # Any attempt to switch provider fails loudly through the same production app.
    fallback = _gemini_adapter(httpx.MockTransport(
        lambda request: pytest.fail("provider switch after dispatch")
    ))
    app = create_codex_executor_app(
        codex_executor=_Codex(),  # type: ignore[arg-type]
        ollama_adapter=ollama,
        provider_api_adapter=fallback,
        adapter_factory=_factory(),
    )
    with _client(app) as client:
        def portal(request: httpx.Request) -> httpx.Response:
            product_requests.append(request)
            assert request.url.path == "/v1/product/embed"
            response = client.post(
                request.url.path, content=request.content,
                headers={"Content-Type": request.headers["Content-Type"]},
            )
            assert _INPUT not in response.text
            assert "synthetic private provider failure" not in response.text
            assert response.json() == {"error": {"code": (
                "ollama_timeout" if failure is httpx.ReadTimeout else "ollama_unavailable"
            )}}
            return httpx.Response(response.status_code, content=response.content)

        remote = CodexRemoteTransport(
            endpoint="https://synthetic-executor.test.ts.net",
            transport=httpx.MockTransport(portal),
        )
        try:
            with pytest.raises(RemoteEmbeddingError) as caught:
                remote.embed_product(ProductEmbeddingRequest.model_validate(
                    _request(provider="ollama", model="nomic-embed-text:latest")
                ))
            assert caught.value.indeterminate is True
            assert caught.value.code == "embedding_http_503"
            assert str(caught.value) == "embedding_http_503"
        finally:
            remote.close()

    assert len(product_requests) == 1
    assert [request.url.path for request in requests] == [
        "/api/tags", "/api/tags", "/api/show", "/api/embed"
    ]


def test_product_catalog_refresh_obeys_executor_concurrency_bound() -> None:
    started = threading.Event()
    release = threading.Event()

    class BlockingOllama:
        def list_models(self) -> tuple[OllamaHttpCatalogModel, ...]:
            started.set()
            if not release.wait(timeout=3):
                raise TimeoutError("test release timed out")
            return (OllamaHttpCatalogModel("nomic-embed-text:latest", None),)

        def close(self) -> None:
            return None

    app = create_codex_executor_app(
        codex_executor=_Codex(),  # type: ignore[arg-type]
        ollama_adapter=BlockingOllama(),  # type: ignore[arg-type]
        adapter_factory=_factory(),
        max_concurrency=1,
    )

    async def exercise() -> tuple[httpx.Response, httpx.Response]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            first_request = asyncio.create_task(
                client.post("/v1/product/catalog", json={"provider": "ollama"})
            )
            try:
                assert await asyncio.to_thread(started.wait, 2)
                second_response = await client.post(
                    "/v1/product/catalog", json={"provider": "gemini"}
                )
            finally:
                release.set()
            first_response = await first_request
            return first_response, second_response

    first_response, second_response = asyncio.run(exercise())
    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert second_response.json()["error"]["code"] == "executor_busy"
