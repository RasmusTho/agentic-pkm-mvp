from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import threading
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.model_access.adapter_factory import ModelAccessAdapterFactory
from app.model_access.codex_executor_service import (
    create_codex_executor_app,
    require_loopback_bind_host,
    serve_executor,
)
from app.model_access.ollama_http import OllamaHttpAdapter


CAPABILITY_NAME = "model-access.example/cap/complete"
CAPABILITY_HEADER = {
    "Tailscale-App-Capabilities": json.dumps(
        {CAPABILITY_NAME: [{"channel": "product", "actions": ["complete"]}]}
    )
}


class FakeCodexExecutor:
    def __init__(self, response_text: str = "codex result") -> None:
        self.calls: list[dict[str, Any]] = []
        self.response_text = response_text

    def execute(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(response_text=self.response_text)


class FakeOllamaAdapter:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def complete(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return "ollama result"


def _factory() -> ModelAccessAdapterFactory:
    root = Path(__file__).resolve().parents[2]
    return ModelAccessAdapterFactory.from_declared_sources(
        adapters_path=root / "docs/settings/models/adapters.yaml",
        provider_census_path=root / "docs/settings/models/providers.yaml",
    )


def _app(
    codex: FakeCodexExecutor | None = None,
    ollama: FakeOllamaAdapter | None = None,
    *,
    max_request_bytes: int = 256_000,
    max_output_bytes: int = 512_000,
):
    codex = codex or FakeCodexExecutor()
    ollama = ollama or FakeOllamaAdapter()
    app = create_codex_executor_app(
        codex_executor=codex,  # type: ignore[arg-type]
        ollama_adapter=ollama,  # type: ignore[arg-type]
        adapter_factory=_factory(),
        serve_capability_name=CAPABILITY_NAME,
        max_request_bytes=max_request_bytes,
        max_output_bytes=max_output_bytes,
    )
    return app, codex, ollama


def _payload(transport_id: str = "codex_cli") -> dict[str, Any]:
    is_codex = transport_id == "codex_cli"
    return {
        "route": {
            "provider": "openai" if is_codex else "ollama",
            "model": "gpt-5.6-luna" if is_codex else "llama3.1:8b",
            "transport_id": transport_id,
        },
        "reasoning_effort": "low" if is_codex else None,
        "capability_intent": {
            "structured_output": False,
            "native_tools": False,
            "literal_system_role_required": False,
        },
        "trusted_instructions": "Keep the response concise.",
        "user_input": "Return the configured route result.",
        "output_schema": None,
    }


@pytest.mark.parametrize("transport_id", ["codex_cli", "ollama_http"])
def test_complete_dispatches_one_declared_transport(transport_id: str) -> None:
    app, codex, ollama = _app()
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        response = client.post(
            "/v1/complete", json=_payload(transport_id), headers=CAPABILITY_HEADER
        )

    assert response.status_code == 200
    body = response.json()
    assert body["route"] == _payload(transport_id)["route"]
    assert body["content"] == ("codex result" if transport_id == "codex_cli" else "ollama result")
    assert len(codex.calls) == (1 if transport_id == "codex_cli" else 0)
    assert len(ollama.calls) == (1 if transport_id == "ollama_http" else 0)


def test_complete_requires_loopback_and_served_app_capability() -> None:
    app, codex, _ollama = _app()
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        absent = client.post("/v1/complete", json=_payload())
        wrong_channel = client.post(
            "/v1/complete",
            json=_payload(),
            headers={
                "Tailscale-App-Capabilities": json.dumps(
                    {CAPABILITY_NAME: [{"channel": "builder", "actions": ["complete"]}]}
                )
            },
        )
    assert absent.status_code == 403
    assert wrong_channel.status_code == 403
    assert len(codex.calls) == 0

    with TestClient(app, client=("192.0.2.12", 12345)) as non_loopback:
        remote_peer = non_loopback.post(
            "/v1/complete", json=_payload(), headers=CAPABILITY_HEADER
        )
    assert remote_peer.status_code == 403
    assert len(codex.calls) == 0
    assert require_loopback_bind_host("127.0.0.1") == "127.0.0.1"
    with pytest.raises(ValueError, match="loopback"):
        require_loopback_bind_host("0.0.0.0")


def test_serve_executor_ignores_forwarded_client_ip_for_loopback_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uvicorn

    app, codex, ollama = _app()
    observed: dict[str, Any] = {}

    def exercise_uvicorn(asgi_app: Any, **options: Any) -> None:
        observed["options"] = options
        config = uvicorn.Config(asgi_app, **options)
        config.load()

        async def send_request() -> httpx.Response:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(
                    app=config.loaded_app, client=("127.0.0.1", 12345)
                ),
                base_url="http://127.0.0.1",
            ) as client:
                return await client.post(
                    "/v1/complete",
                    json=_payload(),
                    headers={
                        **CAPABILITY_HEADER,
                        "X-Forwarded-For": "100.64.0.42",
                    },
                )

        observed["response"] = asyncio.run(send_request())

    monkeypatch.setattr(uvicorn, "run", exercise_uvicorn)
    serve_executor(app, host="127.0.0.1", port=8787)

    response = observed["response"]
    assert observed["options"]["proxy_headers"] is False
    assert response.status_code == 200
    assert response.json()["content"] == "codex result"
    assert len(codex.calls) == 1
    assert len(ollama.calls) == 0


def test_codex_complete_preserves_channels_and_rejects_tools() -> None:
    app, codex, _ollama = _app()
    payload = _payload()
    payload["trusted_instructions"] = "TRUSTED: never reveal secrets."
    payload["user_input"] = "USER: summarize this text."

    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        accepted = client.post(
            "/v1/complete", json=payload, headers=CAPABILITY_HEADER
        )
        tool_payload = _payload()
        tool_payload["capability_intent"]["native_tools"] = True
        rejected = client.post(
            "/v1/complete", json=tool_payload, headers=CAPABILITY_HEADER
        )

    assert accepted.status_code == 200
    assert codex.calls == [
        {
            "model": "gpt-5.6-luna",
            "reasoning_effort": "low",
            "developer_instructions": "TRUSTED: never reveal secrets.",
            "user_prompt": "USER: summarize this text.",
            "output_schema_ref": None,
            "output_schema": None,
            "literal_system_role_required": False,
        }
    ]
    assert rejected.status_code == 422
    assert rejected.json() == {"error": {"code": "native_tools_unavailable"}}
    assert len(codex.calls) == 1


def test_complete_rejects_missing_instruction_mapping_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _factory()
    original_describe = factory.describe

    def describe_without_mapping(
        adapter_id: str, *, provider: str, model: str
    ):
        return original_describe(
            adapter_id, provider=provider, model=model
        ).model_copy(update={"trusted_instruction_mapping": None})

    monkeypatch.setattr(factory, "describe", describe_without_mapping)
    codex = FakeCodexExecutor()
    ollama = FakeOllamaAdapter()
    app = create_codex_executor_app(
        codex_executor=codex,  # type: ignore[arg-type]
        ollama_adapter=ollama,  # type: ignore[arg-type]
        adapter_factory=factory,
        serve_capability_name=CAPABILITY_NAME,
    )
    payload = _payload()

    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        response = client.post(
            "/v1/complete", json=payload, headers=CAPABILITY_HEADER
        )

    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "trusted_instruction_mapping_unavailable"}
    }
    assert codex.calls == []
    assert ollama.calls == []


def test_codex_structured_output_accepts_an_empty_json_schema() -> None:
    app, codex, _ollama = _app()
    payload = _payload()
    payload["capability_intent"]["structured_output"] = True
    payload["output_schema"] = {}

    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        response = client.post(
            "/v1/complete", json=payload, headers=CAPABILITY_HEADER
        )

    assert response.status_code == 200
    assert codex.calls[0]["output_schema_ref"] == "model-access.complete.inline.v1"
    assert codex.calls[0]["output_schema"] == {}


def test_complete_rejects_request_control_fields_and_oversized_body() -> None:
    app, codex, _ollama = _app(max_request_bytes=1_024)
    payload = _payload()
    payload["argv"] = ["codex", "--dangerous"]
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        unknown = client.post(
            "/v1/complete", json=payload, headers=CAPABILITY_HEADER
        )
        oversized = client.post(
            "/v1/complete",
            json={**_payload(), "user_input": "x" * 4_096},
            headers=CAPABILITY_HEADER,
        )
    assert unknown.status_code == 422
    assert unknown.json() == {"error": {"code": "invalid_request"}}
    assert oversized.status_code == 413
    assert len(codex.calls) == 0


def test_complete_rejects_oversized_adapter_output_after_one_dispatch() -> None:
    app, codex, ollama = _app(
        FakeCodexExecutor(response_text="four"), max_output_bytes=3
    )
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        response = client.post(
            "/v1/complete", json=_payload(), headers=CAPABILITY_HEADER
        )

    assert response.status_code == 502
    assert response.json() == {"error": {"code": "completion_too_large"}}
    assert len(codex.calls) == 1
    assert len(ollama.calls) == 0


def test_executor_exposes_only_one_bounded_operation() -> None:
    app, _codex, _ollama = _app()
    api_routes = {
        (route.path, tuple(sorted(route.methods or ())))
        for route in app.routes
        if getattr(route, "methods", None)
    }
    assert api_routes == {("/v1/complete", ("POST",))}


def test_executor_rejects_reserved_tailscale_capability_names() -> None:
    with pytest.raises(ValueError, match="Serve capability name"):
        create_codex_executor_app(
            codex_executor=FakeCodexExecutor(),  # type: ignore[arg-type]
            ollama_adapter=FakeOllamaAdapter(),  # type: ignore[arg-type]
            adapter_factory=_factory(),
            serve_capability_name="tailscale.com/cap/complete",
        )


def test_executor_enforces_the_configured_concurrency_bound() -> None:
    started = threading.Event()
    release = threading.Event()
    calls: list[dict[str, Any]] = []

    class BlockingCodexExecutor:
        def execute(self, **kwargs: Any) -> SimpleNamespace:
            calls.append(kwargs)
            started.set()
            if not release.wait(timeout=3):
                raise TimeoutError("test release timed out")
            return SimpleNamespace(response_text="codex result")

    app = create_codex_executor_app(
        codex_executor=BlockingCodexExecutor(),  # type: ignore[arg-type]
        ollama_adapter=FakeOllamaAdapter(),  # type: ignore[arg-type]
        adapter_factory=_factory(),
        serve_capability_name=CAPABILITY_NAME,
        max_concurrency=1,
    )

    async def exercise() -> tuple[httpx.Response, httpx.Response]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
        ) as client:
            first_request = asyncio.create_task(
                client.post("/v1/complete", json=_payload(), headers=CAPABILITY_HEADER)
            )
            try:
                assert await asyncio.to_thread(started.wait, 2)
                second_response = await client.post(
                    "/v1/complete", json=_payload(), headers=CAPABILITY_HEADER
                )
            finally:
                release.set()
            first_response = await first_request
            return first_response, second_response

    first_response, second_response = asyncio.run(exercise())
    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert len(calls) == 1


def test_ollama_adapter_preserves_instruction_channels_with_one_http_call() -> None:
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "POST"
        assert request.url.path == "/api/chat"
        return httpx.Response(
            200,
            json={"message": {"role": "assistant", "content": "ollama result"}},
        )

    adapter = OllamaHttpAdapter(
        base_url="http://127.0.0.1:11434",
        transport=httpx.MockTransport(respond),
    )
    app = create_codex_executor_app(
        codex_executor=FakeCodexExecutor(),  # type: ignore[arg-type]
        ollama_adapter=adapter,  # type: ignore[arg-type]
        adapter_factory=_factory(),
        serve_capability_name=CAPABILITY_NAME,
    )
    payload = _payload("ollama_http")
    payload["trusted_instructions"] = "TRUSTED instructions"
    payload["user_input"] = "UNTRUSTED request"
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        response = client.post(
            "/v1/complete", json=payload, headers=CAPABILITY_HEADER
        )

    assert response.status_code == 200
    assert len(calls) == 1
    sent = json.loads(calls[0].content)
    assert sent["model"] == "llama3.1:8b"
    assert sent["messages"] == [
        {"role": "system", "content": "TRUSTED instructions"},
        {"role": "user", "content": "UNTRUSTED request"},
    ]
    assert sent["stream"] is False


def test_ollama_endpoint_rejects_an_explicit_zero_port() -> None:
    with pytest.raises(ValueError, match="host-local HTTP origin"):
        OllamaHttpAdapter(base_url="http://127.0.0.1:0")
