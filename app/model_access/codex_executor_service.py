"""Private, bounded preflight/completion API for the Mac model executor."""

from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path
import re
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from jsonschema.exceptions import SchemaError
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse

from app.model_access.adapter_factory import ModelAccessAdapterFactory
from app.model_access.catalog import CatalogError
from app.model_access.catalog_discovery import OllamaCatalogDiscovery, codex_catalog_snapshot
from app.model_access.codex_cli import CodexCliError, CodexCliExecutor
from app.model_access.ollama_http import OllamaHttpAdapter, OllamaHttpError
from app.model_access.remote_contract import (
    CompletionCapabilityIntent,
    CompletionRequest,
    CompletionResponse,
    CompletionRouteIdentity,
    CatalogRequest,
    CatalogResponse,
    PreflightRequest,
    PreflightResponse,
    validate_inline_schema,
)


MAX_REQUEST_BYTES = 256_000
MAX_CAPABILITY_HEADER_BYTES = 8_192
MAX_OUTPUT_BYTES = 512_000
MAX_CATALOG_RESPONSE_BYTES = 2_000_000
DEFAULT_CONCURRENCY = 2
_CAPABILITY_NAME = re.compile(r"^[a-z0-9.-]+/[a-z0-9._/-]{1,160}$")
_CONTENT_LENGTH = re.compile(r"^[0-9]{1,12}$")


class _RequestFailure(RuntimeError):
    def __init__(self, status_code: int, code: str) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(code)


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"unsupported JSON constant: {value}")


def _decode_json_object(raw: bytes) -> dict[str, Any]:
    try:
        decoded = raw.decode("utf-8", errors="strict")
        parsed = json.loads(
            decoded,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError) as exc:
        raise _RequestFailure(400, "invalid_json") from exc
    if not isinstance(parsed, dict):
        raise _RequestFailure(400, "request_must_be_object")
    return parsed


def _require_loopback_peer(request: Request) -> None:
    client_host = request.client.host if request.client is not None else None
    try:
        if client_host is None or not ipaddress.ip_address(client_host).is_loopback:
            raise _RequestFailure(403, "loopback_only")
    except ValueError as exc:
        raise _RequestFailure(403, "loopback_only") from exc


def _require_serve_capability(
    request: Request,
    capability_name: str,
    *,
    action: str,
) -> None:
    value = request.headers.get("tailscale-app-capabilities")
    if value is None or len(value.encode("utf-8")) > MAX_CAPABILITY_HEADER_BYTES:
        raise _RequestFailure(403, "serve_capability_required")
    try:
        claims = json.loads(
            value,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (ValueError, json.JSONDecodeError, RecursionError) as exc:
        raise _RequestFailure(403, "serve_capability_invalid") from exc
    if not isinstance(claims, dict) or set(claims) != {capability_name}:
        raise _RequestFailure(403, "serve_capability_invalid")
    grants = claims.get(capability_name)
    if not isinstance(grants, list):
        raise _RequestFailure(403, "serve_capability_invalid")
    for grant in grants:
        if not isinstance(grant, dict) or set(grant) != {"channel", "actions"}:
            continue
        actions = grant.get("actions")
        if not isinstance(actions, list) or any(
            not isinstance(value, str) or value not in {"complete", "preflight", "catalog"}
            for value in actions
        ):
            continue
        if (
            grant.get("channel") == "product"
            and bool(actions)
            and len(actions) == len(set(actions))
            and action in actions
        ):
            return
    raise _RequestFailure(403, "serve_capability_invalid")


async def _read_bounded_body(request: Request, *, max_bytes: int) -> bytes:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise _RequestFailure(415, "json_content_type_required")

    content_length = request.headers.get("content-length")
    if content_length is None or not _CONTENT_LENGTH.fullmatch(content_length):
        raise _RequestFailure(411, "content_length_required")
    expected_length = int(content_length)
    if expected_length > max_bytes:
        raise _RequestFailure(413, "request_too_large")

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > max_bytes:
            raise _RequestFailure(413, "request_too_large")
        body.extend(chunk)
    if len(body) != expected_length:
        raise _RequestFailure(400, "content_length_mismatch")
    return bytes(body)


def _validate_capability_intent(
    *,
    route: CompletionRouteIdentity,
    intent: CompletionCapabilityIntent,
    adapter_factory: ModelAccessAdapterFactory,
    output_schema: dict[str, Any] | None = None,
    require_output_schema: bool,
) -> None:
    try:
        descriptor = adapter_factory.describe(
            route.transport_id,
            provider=route.provider,
            model=route.model,
        )
    except (ValueError, KeyError) as exc:
        raise _RequestFailure(422, "route_not_declared") from exc

    capabilities = descriptor.supported_capabilities
    if intent.native_tools and not capabilities.native_tools:
        raise _RequestFailure(422, "native_tools_unavailable")
    if intent.structured_output:
        if not capabilities.structured_output or (
            require_output_schema and output_schema is None
        ):
            raise _RequestFailure(422, "structured_output_unavailable")
    if output_schema is not None:
        try:
            validate_inline_schema(output_schema)
        except ValueError as exc:
            raise _RequestFailure(422, "output_schema_invalid") from exc
    mapping = descriptor.trusted_instruction_mapping
    if mapping is None:
        raise _RequestFailure(422, "trusted_instruction_mapping_unavailable")
    if intent.literal_system_role_required:
        if mapping.trusted_channel != "system":
            raise _RequestFailure(422, "literal_system_role_unavailable")


def _codex_complete(
    executor: CodexCliExecutor,
    request: CompletionRequest,
) -> str:
    result = executor.execute(
        model=request.route.model,
        reasoning_effort=request.reasoning_effort or "",
        developer_instructions=request.trusted_instructions,
        user_prompt=request.user_input,
        output_schema_ref=(
            "model-access.complete.inline.v1"
            if request.output_schema is not None
            else None
        ),
        output_schema=request.output_schema,
        literal_system_role_required=request.capability_intent.literal_system_role_required,
    )
    return result.response_text


def _codex_preflight(
    executor: CodexCliExecutor,
    request: PreflightRequest,
) -> None:
    executor.preflight(
        model=request.route.model,
        reasoning_effort=request.reasoning_effort,
    )


def _ollama_preflight(
    adapter: OllamaHttpAdapter,
    request: PreflightRequest,
) -> None:
    adapter.preflight(model=request.route.model)


def _ollama_complete(
    adapter: OllamaHttpAdapter,
    request: CompletionRequest,
) -> str:
    return adapter.complete(
        model=request.route.model,
        trusted_instructions=request.trusted_instructions,
        user_input=request.user_input,
        output_schema=request.output_schema,
        literal_system_role_required=request.capability_intent.literal_system_role_required,
    )


def _adapter_failure(exc: Exception) -> _RequestFailure:
    if isinstance(exc, CodexCliError):
        if exc.failure_code == "command_timeout":
            return _RequestFailure(504, exc.failure_code)
        if exc.failure_code in {"input_oversize", "stdout_oversize"}:
            return _RequestFailure(413 if exc.failure_code == "input_oversize" else 502, exc.failure_code)
        if exc.failure_code in {"model_unavailable", "schema_violation", "unsupported_profile"}:
            return _RequestFailure(422, exc.failure_code)
        return _RequestFailure(503, exc.failure_code)
    if isinstance(exc, OllamaHttpError):
        if exc.failure_code == "ollama_schema_violation":
            return _RequestFailure(422, exc.failure_code)
        if exc.failure_code == "ollama_output_too_large":
            return _RequestFailure(502, exc.failure_code)
        return _RequestFailure(503, exc.failure_code)
    if isinstance(exc, CatalogError):
        return _RequestFailure(503, exc.code)
    if isinstance(exc, (SchemaError, ValidationError)):
        return _RequestFailure(422, "adapter_validation_failed")
    return _RequestFailure(502, "adapter_execution_failed")


def create_codex_executor_app(
    *,
    codex_executor: CodexCliExecutor,
    ollama_adapter: OllamaHttpAdapter,
    adapter_factory: ModelAccessAdapterFactory,
    serve_capability_name: str,
    max_request_bytes: int = MAX_REQUEST_BYTES,
    max_output_bytes: int = MAX_OUTPUT_BYTES,
    max_concurrency: int = DEFAULT_CONCURRENCY,
) -> FastAPI:
    """Build bounded preflight/completion operations; route policy stays with callers."""

    normalized_capability = serve_capability_name.lower()
    if (
        not _CAPABILITY_NAME.fullmatch(serve_capability_name)
        or normalized_capability.startswith(("tailscale.com/", "tailscale.io/"))
    ):
        raise ValueError("Serve capability name is invalid")
    if min(max_request_bytes, max_output_bytes, max_concurrency) <= 0:
        raise ValueError("executor service bounds must be positive")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        close = getattr(ollama_adapter, "close", None)
        if callable(close):
            close()

    app = FastAPI(
        title="Private Model Executor",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    slots = threading.BoundedSemaphore(max_concurrency)

    @app.post("/v1/preflight", response_model=PreflightResponse)
    async def preflight(request: Request) -> JSONResponse:
        try:
            _require_loopback_peer(request)
            _require_serve_capability(
                request, serve_capability_name, action="preflight"
            )
            body = await _read_bounded_body(request, max_bytes=max_request_bytes)
            try:
                preflight_request = PreflightRequest.model_validate(
                    _decode_json_object(body)
                )
            except ValidationError as exc:
                raise _RequestFailure(422, "invalid_request") from exc

            _validate_capability_intent(
                route=preflight_request.route,
                intent=preflight_request.capability_intent,
                adapter_factory=adapter_factory,
                require_output_schema=False,
            )
            if not slots.acquire(blocking=False):
                raise _RequestFailure(429, "executor_busy")
            try:
                if preflight_request.route.transport_id == "codex_cli":
                    await run_in_threadpool(
                        _codex_preflight, codex_executor, preflight_request
                    )
                else:
                    await run_in_threadpool(
                        _ollama_preflight, ollama_adapter, preflight_request
                    )
            except Exception as exc:
                raise _adapter_failure(exc) from exc
            finally:
                slots.release()

            response = PreflightResponse(
                route=preflight_request.route,
                preflight_status="passed",
            )
            return JSONResponse(content=response.model_dump(mode="json"))
        except _RequestFailure as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": {"code": exc.code}},
            )

    @app.post("/v1/catalog", response_model=CatalogResponse)
    async def catalog(request: Request) -> JSONResponse:
        try:
            _require_loopback_peer(request)
            _require_serve_capability(request, serve_capability_name, action="catalog")
            body = await _read_bounded_body(request, max_bytes=max_request_bytes)
            try:
                catalog_request = CatalogRequest.model_validate(_decode_json_object(body))
            except ValidationError as exc:
                raise _RequestFailure(422, "invalid_request") from exc

            if not slots.acquire(blocking=False):
                raise _RequestFailure(429, "executor_busy")
            try:
                if catalog_request.transport_id == "codex_cli":
                    raw_models = await run_in_threadpool(codex_executor.list_catalog_models)
                    snapshot = codex_catalog_snapshot(
                        raw_models,
                        fetched_at=datetime.now(timezone.utc),
                    )
                else:
                    snapshot = await run_in_threadpool(
                        OllamaCatalogDiscovery(ollama_adapter).discover
                    )
            except Exception as exc:
                raise _adapter_failure(exc) from exc
            finally:
                slots.release()

            response = CatalogResponse(snapshot=snapshot)
            response_json = response.model_dump(mode="json")
            encoded = json.dumps(
                response_json,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            if len(encoded) > MAX_CATALOG_RESPONSE_BYTES:
                raise _RequestFailure(502, "catalog_response_too_large")
            return JSONResponse(content=response_json)
        except _RequestFailure as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": {"code": exc.code}},
            )

    @app.post("/v1/complete", response_model=CompletionResponse)
    async def complete(request: Request) -> JSONResponse:
        try:
            _require_loopback_peer(request)
            _require_serve_capability(
                request, serve_capability_name, action="complete"
            )
            body = await _read_bounded_body(request, max_bytes=max_request_bytes)
            try:
                completion_request = CompletionRequest.model_validate(
                    _decode_json_object(body)
                )
            except ValidationError as exc:
                raise _RequestFailure(422, "invalid_request") from exc

            if completion_request.capability_intent.native_tools:
                # The current safe Codex profile and declared Ollama profile expose no tools.
                raise _RequestFailure(422, "native_tools_unavailable")
            _validate_capability_intent(
                route=completion_request.route,
                intent=completion_request.capability_intent,
                adapter_factory=adapter_factory,
                output_schema=completion_request.output_schema,
                require_output_schema=True,
            )

            if not slots.acquire(blocking=False):
                raise _RequestFailure(429, "executor_busy")
            try:
                if completion_request.route.transport_id == "codex_cli":
                    content = await run_in_threadpool(
                        _codex_complete, codex_executor, completion_request
                    )
                else:
                    content = await run_in_threadpool(
                        _ollama_complete, ollama_adapter, completion_request
                    )
            except Exception as exc:
                raise _adapter_failure(exc) from exc
            finally:
                slots.release()

            if not isinstance(content, str) or not content:
                raise _RequestFailure(502, "empty_completion")
            if len(content.encode("utf-8")) > max_output_bytes:
                raise _RequestFailure(502, "completion_too_large")
            response = CompletionResponse(route=completion_request.route, content=content)
            return JSONResponse(content=response.model_dump(mode="json"))
        except _RequestFailure as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": {"code": exc.code}},
            )

    return app


def require_loopback_bind_host(host: str) -> str:
    """Return a normalized loopback host or refuse to start the executor."""

    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        if host != "localhost":
            raise ValueError("model executor must bind to a loopback address") from exc
        return host
    if not address.is_loopback:
        raise ValueError("model executor must bind to a loopback address")
    return str(address)


def serve_executor(app: FastAPI, *, host: str = "127.0.0.1", port: int = 8787) -> None:
    """Start uvicorn only after enforcing the loopback listener boundary."""

    bind_host = require_loopback_bind_host(host)
    if type(port) is not int or not 1 <= port <= 65_535:
        raise ValueError("model executor port is invalid")
    import uvicorn

    # Tailscale Serve forwards the original peer in X-Forwarded-For. Keep the
    # ASGI client address bound to the actual loopback connection: the app's
    # loopback guard must not be rewritten to the remote tailnet peer.
    uvicorn.run(
        app,
        host=bind_host,
        port=port,
        proxy_headers=False,
        access_log=False,
        log_level="warning",
    )


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main() -> None:
    """Host-local entry point. All deployment configuration stays outside Git."""

    root = _repository_root()
    factory = ModelAccessAdapterFactory.from_declared_sources(
        adapters_path=root / "docs/settings/models/adapters.yaml",
        provider_census_path=root / "docs/settings/models/providers.yaml",
    )
    profile_path = os.environ.get("CODEX_CLI_SAFE_PROFILE_PATH", "")
    capability_name = os.environ.get("MODEL_ACCESS_SERVE_CAPABILITY_NAME", "")
    if not profile_path or not Path(profile_path).is_absolute():
        raise SystemExit("CODEX_CLI_SAFE_PROFILE_PATH must name a host-local absolute profile")
    if not capability_name:
        raise SystemExit("MODEL_ACCESS_SERVE_CAPABILITY_NAME is required")

    ollama_base_url = os.environ.get("MODEL_ACCESS_OLLAMA_BASE_URL", "")
    if not ollama_base_url:
        raise SystemExit("MODEL_ACCESS_OLLAMA_BASE_URL is required")
    try:
        port = int(os.environ.get("MODEL_ACCESS_EXECUTOR_PORT", "8787"))
    except ValueError as exc:
        raise SystemExit("MODEL_ACCESS_EXECUTOR_PORT must be an integer") from exc

    codex_executor = factory.create_codex_cli_executor(
        safe_profile_path=Path(profile_path),
        execution_timeout_seconds=1_200,
        max_input_bytes=MAX_REQUEST_BYTES,
        max_output_bytes=MAX_OUTPUT_BYTES,
    )
    ollama_adapter = OllamaHttpAdapter(
        base_url=ollama_base_url,
        timeout_seconds=120,
        max_output_bytes=MAX_OUTPUT_BYTES,
    )
    app = create_codex_executor_app(
        codex_executor=codex_executor,
        ollama_adapter=ollama_adapter,
        adapter_factory=factory,
        serve_capability_name=capability_name,
    )
    serve_executor(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()


__all__ = [
    "MAX_CAPABILITY_HEADER_BYTES",
    "MAX_OUTPUT_BYTES",
    "MAX_REQUEST_BYTES",
    "create_codex_executor_app",
    "main",
    "require_loopback_bind_host",
    "serve_executor",
]
