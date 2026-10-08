"""Bounded Product provider API adapter for the Mac model-access portal."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
import json
import math
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from pydantic import ValidationError

from app.model_access.adapter_factory import AdapterRegistryError, ModelAccessAdapterFactory
from app.model_access.catalog import (
    CatalogCache,
    CatalogError,
    CatalogModelDescriptor,
    CatalogSnapshot,
)
from app.model_access.catalog_discovery import (
    AnthropicCatalogDiscovery,
    DeepSeekCatalogDiscovery,
    OpenAICatalogDiscovery,
)
from app.model_access.remote_contract import (
    CompletionCapabilityIntent,
    CompletionRequest,
    CompletionUsageMetadata,
    PreflightRequest,
    ProductEmbeddingRequest,
    inline_schema_validator,
)


DEFAULT_MAX_OUTPUT_TOKENS = 4096
MAX_PROVIDER_RESPONSE_BYTES = 512_000
_TRANSPORT_PROVIDER = {
    "openai_api": "openai",
    "anthropic_api": "anthropic",
    "deepseek_api": "deepseek",
}
_CREDENTIAL_ENV: dict[str, tuple[str, ...]] = {
    "openai.api-key": ("OPENAI_API_KEY",),
    "anthropic.api-key": ("ANTHROPIC_API_KEY",),
    "deepseek.api-key": ("DEEPSEEK_API_KEY",),
    "gemini.api-key": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}
_OFFICIAL_HOSTS = {
    "openai": "api.openai.com",
    "anthropic": "api.anthropic.com",
    "deepseek": "api.deepseek.com",
    "gemini": "generativelanguage.googleapis.com",
}
_OPENAI_EFFORTS = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh", "max"}
)
_ANTHROPIC_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})


class ProviderApiError(RuntimeError):
    """Sanitized provider failure; response bodies and credentials are never retained."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"unsupported JSON constant: {value}")


def _json_object(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError):
        raise ProviderApiError("provider_response_invalid") from None
    if not isinstance(value, dict):
        raise ProviderApiError("provider_response_invalid")
    return value


def _bounded_body(response: httpx.Response) -> bytes:
    body = bytearray()
    try:
        for chunk in response.iter_bytes():
            if len(body) + len(chunk) > MAX_PROVIDER_RESPONSE_BYTES:
                raise ProviderApiError("provider_response_too_large")
            body.extend(chunk)
    except ProviderApiError:
        raise
    except httpx.HTTPError:
        raise ProviderApiError("provider_unavailable") from None
    return bytes(body)


class ProductProviderApiAdapter:
    """Dispatch one exact route using host-resolved credentials and fixed provider APIs."""

    def __init__(
        self,
        *,
        adapter_factory: ModelAccessAdapterFactory,
        credential_resolver: Callable[[str], str | None],
        transport: httpx.BaseTransport | None = None,
        catalog_cache: CatalogCache | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("provider timeout must be positive")
        self._factory = adapter_factory
        self._credential_resolver = credential_resolver
        self._transport = transport
        self._catalog_cache = catalog_cache or CatalogCache()
        self._client = httpx.Client(
            transport=transport or httpx.HTTPTransport(retries=0),
            timeout=httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 10.0)),
            follow_redirects=False,
            trust_env=False,
        )

    def _provider(self, transport_id: str) -> str:
        provider = _TRANSPORT_PROVIDER.get(transport_id)
        if provider is None:
            raise ProviderApiError("route_not_declared")
        return provider

    def _endpoint(self, provider: str) -> str:
        endpoint = self._factory.provider_api_endpoint(provider)
        expected_host = _OFFICIAL_HOSTS[provider]
        try:
            if not endpoint:
                raise ValueError
            parsed = urlsplit(endpoint or "")
            if (
                parsed.scheme != "https"
                or parsed.hostname != expected_host
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or parsed.port not in {None, 443}
            ):
                raise ValueError
            if provider == "openai" and parsed.path != "/v1/chat/completions":
                raise ValueError
            if provider == "anthropic" and parsed.path != "/v1/messages":
                raise ValueError
            if provider == "deepseek" and parsed.path != "/chat/completions":
                raise ValueError
            if provider == "gemini" and parsed.path != "/v1beta/models":
                raise ValueError
        except (TypeError, ValueError):
            raise ProviderApiError("provider_endpoint_not_declared") from None
        return endpoint

    def _api_key(self, provider: str) -> str:
        try:
            provider_entry = self._factory.provider_entry(provider)
        except (KeyError, ValueError):
            raise ProviderApiError("route_not_declared") from None
        if len(provider_entry.credential_identifiers) != 1:
            raise ProviderApiError("credential_unavailable")
        credential_id = provider_entry.credential_identifiers[0]
        environment_names = _CREDENTIAL_ENV.get(credential_id)
        if environment_names is None:
            raise ProviderApiError("credential_unavailable")
        # Only the host process can resolve these environment references; no value
        # is accepted from a request or included in errors, logs, or receipts.
        for environment_name in environment_names:
            value = self._credential_resolver(environment_name)
            if isinstance(value, str) and value.strip():
                return value.strip()
        raise ProviderApiError("credential_unavailable")

    def _catalog(
        self, provider: str, api_key: str, fetched_at: datetime
    ) -> CatalogSnapshot:
        discovery: OpenAICatalogDiscovery | AnthropicCatalogDiscovery | DeepSeekCatalogDiscovery
        if provider == "openai":
            discovery = OpenAICatalogDiscovery(api_key=api_key, transport=self._transport)
        elif provider == "anthropic":
            discovery = AnthropicCatalogDiscovery(api_key=api_key, transport=self._transport)
        else:
            discovery = DeepSeekCatalogDiscovery(api_key=api_key, transport=self._transport)
        try:
            return discovery.discover(fetched_at=fetched_at)
        finally:
            discovery.close()

    def _catalog_snapshot(
        self, provider: str, transport_id: str, api_key: str
    ) -> CatalogSnapshot:
        try:
            return self._catalog_cache.get(
                provider=provider,
                transport_id=transport_id,
                loader=lambda fetched_at: self._catalog(provider, api_key, fetched_at),
            )
        except CatalogError as exc:
            raise ProviderApiError(exc.code) from None

    @staticmethod
    def _require_snapshot_match(route: Any, snapshot: CatalogSnapshot) -> None:
        if snapshot.freshness != "fresh":
            raise ProviderApiError("catalog_stale")
        if (
            route.catalog_snapshot_ref != snapshot.snapshot_ref
            or route.catalog_snapshot_hash != snapshot.snapshot_hash
        ):
            raise ProviderApiError("catalog_snapshot_mismatch")

    @staticmethod
    def _validated_model(
        provider: str,
        snapshot: CatalogSnapshot,
        model_id: str,
        reasoning_effort: str | None,
        declared_reasoning_efforts: frozenset[str] | None,
    ) -> CatalogModelDescriptor:
        model = next((item for item in snapshot.models if item.model == model_id), None)
        if model is None:
            raise ProviderApiError("provider_model_unavailable")
        if reasoning_effort is None:
            return model
        if provider == "openai" and reasoning_effort not in _OPENAI_EFFORTS:
            raise ProviderApiError("reasoning_effort_unavailable")
        if provider == "anthropic" and reasoning_effort not in _ANTHROPIC_EFFORTS:
            raise ProviderApiError("reasoning_effort_unavailable")
        if provider == "deepseek" and reasoning_effort not in model.reasoning_efforts:
            raise ProviderApiError("reasoning_effort_unavailable")
        if (
            model.reasoning_effort_attested
            and reasoning_effort not in model.reasoning_efforts
        ):
            raise ProviderApiError("reasoning_effort_unavailable")
        # The checked-in per-model census is the authority. Provider metadata may
        # veto a declared effort, but it cannot fill an unknown allowlist or widen it.
        if (
            declared_reasoning_efforts is None
            or reasoning_effort not in declared_reasoning_efforts
        ):
            raise ProviderApiError("reasoning_effort_unavailable")
        return model

    def _model_reasoning_efforts(
        self, provider: str, model: str
    ) -> frozenset[str] | None:
        try:
            return self._factory.model_reasoning_efforts(provider, model)
        except AdapterRegistryError:
            raise ProviderApiError("provider_model_unavailable") from None

    @staticmethod
    def _require_catalog_capabilities(
        model: CatalogModelDescriptor,
        intent: CompletionCapabilityIntent,
        *,
        max_output_tokens: int | None = None,
    ) -> None:
        # Product policy/census remains the allowlist. When the live provider
        # catalog explicitly attests structured-output support, however, a
        # contradictory value must veto the route rather than be overridden by
        # the static descriptor. An absent capability field means "unknown";
        # OpenAI's models endpoint currently does not expose it.
        if (
            intent.structured_output
            and model.structured_output_attested
            and not model.capabilities.structured_output
        ):
            raise ProviderApiError("structured_output_unavailable")
        if (
            max_output_tokens is not None
            and model.max_output_tokens is not None
            and max_output_tokens > model.max_output_tokens
        ):
            raise ProviderApiError("max_output_tokens_unavailable")

    def discover_catalog(self, transport_id: str) -> CatalogSnapshot:
        provider = self._provider(transport_id)
        api_key = self._api_key(provider)
        self._endpoint(provider)
        return self._catalog_snapshot(provider, transport_id, api_key)

    def preflight(self, request: PreflightRequest) -> None:
        provider = self._provider(request.route.transport_id)
        api_key = self._api_key(provider)
        self._endpoint(provider)
        snapshot = self._catalog_snapshot(provider, request.route.transport_id, api_key)
        self._require_snapshot_match(request.route, snapshot)
        declared_reasoning_efforts = self._model_reasoning_efforts(
            provider, request.route.model
        )
        model = self._validated_model(
            provider,
            snapshot,
            request.route.model,
            request.reasoning_effort,
            declared_reasoning_efforts,
        )
        self._require_catalog_capabilities(model, request.capability_intent)

    def complete(self, request: CompletionRequest) -> str:
        content, _usage = self.complete_with_usage(request)
        return content

    def complete_with_usage(
        self, request: CompletionRequest
    ) -> tuple[str, CompletionUsageMetadata | None]:
        """Complete once and return only bounded OpenAI billing metadata."""
        schema_validator = None
        if request.output_schema is not None:
            try:
                schema_validator = inline_schema_validator(request.output_schema)
            except ValueError:
                raise ProviderApiError("provider_schema_invalid") from None

        provider = self._provider(request.route.transport_id)
        api_key = self._api_key(provider)
        endpoint = self._endpoint(provider)
        snapshot = self._catalog_snapshot(provider, request.route.transport_id, api_key)
        self._require_snapshot_match(request.route, snapshot)
        declared_reasoning_efforts = self._model_reasoning_efforts(
            provider, request.route.model
        )
        model = self._validated_model(
            provider,
            snapshot,
            request.route.model,
            request.reasoning_effort,
            declared_reasoning_efforts,
        )
        self._require_catalog_capabilities(
            model,
            request.capability_intent,
            max_output_tokens=(
                request.max_output_tokens or DEFAULT_MAX_OUTPUT_TOKENS
            ),
        )
        body = self._request_body(provider, request)
        headers = {"Content-Type": "application/json"}
        if provider == "anthropic":
            headers.update({"x-api-key": api_key, "anthropic-version": "2023-06-01"})
        else:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            with self._client.stream("POST", endpoint, json=body, headers=headers) as response:
                status = response.status_code
                raw = _bounded_body(response)
        except ProviderApiError:
            raise
        except (httpx.HTTPError, OSError):
            raise ProviderApiError("provider_unavailable") from None

        if status != 200:
            if status in {401, 403}:
                raise ProviderApiError("provider_auth_failed")
            if status == 404:
                raise ProviderApiError("provider_model_unavailable")
            if status in {408, 429} or status >= 500:
                raise ProviderApiError("provider_unavailable")
            raise ProviderApiError("provider_request_rejected")

        payload = _json_object(raw)
        content = self._extract_content(provider, payload)
        if request.output_schema is not None:
            try:
                structured = json.loads(
                    content,
                    object_pairs_hook=_unique_pairs,
                    parse_constant=_reject_constant,
                )
                if schema_validator is None:
                    raise ValueError("structured-output validator is unavailable")
                schema_validator.validate(structured)
            except Exception:
                raise ProviderApiError("provider_schema_violation") from None
        usage = _openai_usage_metadata(provider, payload)
        return content, usage
    def preflight_embedding(self, request: ProductEmbeddingRequest) -> None:
        """Check census binding, endpoint, and host credential without inference."""
        if request.provider != "gemini":
            raise ProviderApiError("route_not_declared")
        try:
            descriptor = self._factory.describe(
                "gemini_api",
                provider="gemini",
                model=request.model,
                model_kind="embedding",
            )
        except (AdapterRegistryError, KeyError, ValueError):
            raise ProviderApiError("provider_model_unavailable") from None
        if descriptor.supported_capabilities.embedding_dimension != request.dimensions:
            raise ProviderApiError("embedding_dimension_unavailable")
        self._api_key("gemini")
        self._endpoint("gemini")

    def embed_product(self, request: ProductEmbeddingRequest) -> tuple[float, ...]:
        """Send one Gemini embedding request using only Mac-resolved host credentials."""
        if request.provider != "gemini":
            raise ProviderApiError("route_not_declared")
        try:
            descriptor = self._factory.describe(
                "gemini_api",
                provider="gemini",
                model=request.model,
                model_kind="embedding",
            )
        except (AdapterRegistryError, KeyError, ValueError):
            raise ProviderApiError("provider_model_unavailable") from None
        if descriptor.supported_capabilities.embedding_dimension != request.dimensions:
            raise ProviderApiError("embedding_dimension_unavailable")

        api_key = self._api_key("gemini")
        endpoint = self._endpoint("gemini")
        model_path = quote(request.model, safe="-_.")
        body = {
            "model": f"models/{request.model}",
            "content": {"parts": [{"text": request.input_text}]},
            "embedContentConfig": {"outputDimensionality": request.dimensions},
        }
        try:
            with self._client.stream(
                "POST",
                f"{endpoint}/{model_path}:embedContent",
                json=body,
                headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            ) as response:
                status = response.status_code
                raw = _bounded_body(response)
        except ProviderApiError:
            raise
        except (httpx.HTTPError, OSError):
            raise ProviderApiError("provider_unavailable") from None

        if status != 200:
            if status in {401, 403}:
                raise ProviderApiError("provider_auth_failed")
            if status == 404:
                raise ProviderApiError("provider_model_unavailable")
            if status in {408, 429} or status >= 500:
                raise ProviderApiError("provider_unavailable")
            raise ProviderApiError("provider_request_rejected")

        payload = _json_object(raw)
        embedding = payload.get("embedding")
        values = embedding.get("values") if isinstance(embedding, dict) else None
        if not isinstance(values, list) or not values:
            raise ProviderApiError("provider_response_invalid")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            for value in values
        ):
            raise ProviderApiError("provider_response_invalid")
        vector = tuple(float(value) for value in values)
        if len(vector) != request.dimensions:
            raise ProviderApiError("provider_embedding_dimension_mismatch")
        return vector

    @staticmethod
    def _request_body(provider: str, request: CompletionRequest) -> dict[str, Any]:
        effort = request.reasoning_effort
        output_limit = request.max_output_tokens or DEFAULT_MAX_OUTPUT_TOKENS
        if provider == "anthropic":
            body: dict[str, Any] = {
                "model": request.route.model,
                "max_tokens": output_limit,
                "messages": [{"role": "user", "content": request.user_input}],
            }
            if request.trusted_instructions:
                body["system"] = request.trusted_instructions
            if effort is not None:
                body["output_config"] = {"effort": effort}
            if request.output_schema is not None:
                body.setdefault("output_config", {})["format"] = {
                    "type": "json_schema",
                    "schema": request.output_schema,
                }
            return body

        messages: list[dict[str, str]] = []
        if request.trusted_instructions:
            messages.append({"role": "system", "content": request.trusted_instructions})
        messages.append({"role": "user", "content": request.user_input})
        body = {"model": request.route.model, "messages": messages, "stream": False}
        if provider == "openai":
            body["max_completion_tokens"] = output_limit
            if effort is not None:
                body["reasoning_effort"] = effort
            if request.service_tier is not None:
                body["service_tier"] = request.service_tier
            if request.output_schema is not None:
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "model_access_result",
                        "strict": True,
                        "schema": request.output_schema,
                    },
                }
        else:
            body["max_tokens"] = output_limit
            if effort is not None:
                body["reasoning_effort"] = effort
        return body

    @staticmethod
    def _extract_content(provider: str, payload: dict[str, Any]) -> str:
        if provider == "anthropic":
            blocks = payload.get("content")
            if not isinstance(blocks, list) or not blocks:
                raise ProviderApiError("provider_response_invalid")
            parts: list[str] = []
            for block in blocks:
                if not isinstance(block, dict):
                    raise ProviderApiError("provider_response_invalid")
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    parts.append(block["text"])
                elif block.get("type") in {"tool_use", "server_tool_use"}:
                    raise ProviderApiError("provider_tools_unavailable")
            content = "".join(parts)
        else:
            choices = payload.get("choices")
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                raise ProviderApiError("provider_response_invalid")
            message = choices[0].get("message")
            if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                raise ProviderApiError("provider_response_invalid")
            content = message["content"]
        if not content:
            raise ProviderApiError("provider_response_invalid")
        return content

    def close(self) -> None:
        self._client.close()


def _openai_usage_metadata(
    provider: str, payload: dict[str, Any]
) -> CompletionUsageMetadata | None:
    """Project billing-only OpenAI fields; never forward the provider payload."""
    if provider != "openai":
        return None
    raw_usage = payload.get("usage")
    if not isinstance(raw_usage, dict):
        return None
    usage: dict[str, Any] = {
        key: raw_usage[key]
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        if key in raw_usage
    }
    raw_details = raw_usage.get("prompt_tokens_details")
    if isinstance(raw_details, dict):
        usage["prompt_tokens_details"] = {
            key: raw_details[key]
            for key in (
                "cached_tokens",
                "audio_tokens",
                "cache_write_tokens",
                "cache_creation_tokens",
            )
            if key in raw_details
        }
    candidate = {
        "model": payload.get("model"),
        "service_tier": payload.get("service_tier"),
        "usage": usage,
    }
    try:
        return CompletionUsageMetadata.model_validate(candidate)
    except ValidationError:
        # Usage is observational. A malformed optional field must not discard a
        # valid completion; downstream evaluation will mark its receipt unpriced.
        return None


__all__ = ["ProductProviderApiAdapter", "ProviderApiError"]
