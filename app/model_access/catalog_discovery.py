"""Read-only catalog discovery for Codex, Ollama, OpenAI, and Anthropic."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import ipaddress
import json
import re
from typing import Any

import httpx
from pydantic import ValidationError

from app.model_access.catalog import CatalogError, CatalogModelDescriptor, CatalogSnapshot
from app.model_access.ollama_http import OllamaHttpAdapter, OllamaHttpError
from llm_contract import ModelCapabilities


MAX_CATALOG_RESPONSE_BYTES = 256_000
MAX_CATALOG_MODELS = 4_096
MAX_ANTHROPIC_PAGES = 32
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,255}$")
_SECRET_MARKER = re.compile(
    r"(?:https?://|@|\bsk-(?:ant-)?[a-z0-9_-]{8,}\b|\b(?:bearer|api[_-]?key|token|secret)\s*[:=])",
    re.IGNORECASE,
)


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant {value}")


def _fetched_time(value: datetime | None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None or result.utcoffset() is None:
        raise CatalogError("catalog_invalid")
    return result.astimezone(timezone.utc)


def _descriptor(**values: Any) -> CatalogModelDescriptor:
    try:
        return CatalogModelDescriptor(**values)
    except (TypeError, ValueError, ValidationError):
        raise CatalogError("catalog_invalid") from None


def _snapshot(**values: Any) -> CatalogSnapshot:
    try:
        return CatalogSnapshot.create(**values)
    except (TypeError, ValueError, ValidationError):
        raise CatalogError("catalog_invalid") from None


def _json_object(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError):
        raise CatalogError("catalog_invalid") from None
    if not isinstance(value, dict):
        raise CatalogError("catalog_invalid")
    return value


def _valid_model_id(value: Any) -> str:
    if not isinstance(value, str) or not _MODEL_ID.fullmatch(value) or _SECRET_MARKER.search(value):
        raise CatalogError("catalog_invalid")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return value
    raise CatalogError("catalog_invalid")


def _timestamp(value: Any, *, epoch: bool = False) -> datetime | None:
    if epoch:
        if type(value) is not int or value < 0:
            raise CatalogError("catalog_invalid")
        if value == 0:
            return None
        try:
            return datetime.fromtimestamp(value, timezone.utc)
        except (OverflowError, OSError, ValueError):
            raise CatalogError("catalog_invalid") from None
    if not isinstance(value, str) or not value:
        raise CatalogError("catalog_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise CatalogError("catalog_invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CatalogError("catalog_invalid")
    # Anthropic documents an epoch date as "unknown" rather than a release date.
    if parsed.year <= 1970:
        return None
    return parsed.astimezone(timezone.utc)


def _bounded_get(
    client: httpx.Client,
    url: str,
    *,
    headers: Mapping[str, str],
    params: Mapping[str, str | int] | None = None,
) -> dict[str, Any]:
    body = bytearray()
    try:
        with client.stream("GET", url, headers=dict(headers), params=params) as response:
            if response.status_code != 200:
                if response.status_code in {401, 403}:
                    raise CatalogError("catalog_auth_failed")
                if (
                    response.status_code in {408, 429}
                    or response.status_code >= 500
                ):
                    raise CatalogError("catalog_unavailable")
                raise CatalogError("catalog_invalid")
            for chunk in response.iter_bytes():
                if len(body) + len(chunk) > MAX_CATALOG_RESPONSE_BYTES:
                    raise CatalogError("catalog_invalid")
                body.extend(chunk)
    except CatalogError:
        raise
    except (httpx.HTTPError, OSError):
        raise CatalogError("catalog_unavailable") from None
    return _json_object(bytes(body))


def _new_client(transport: httpx.BaseTransport | None) -> httpx.Client:
    return httpx.Client(
        transport=transport or httpx.HTTPTransport(retries=0),
        timeout=httpx.Timeout(10.0, connect=5.0),
        follow_redirects=False,
        trust_env=False,
    )


class OpenAICatalogDiscovery:
    """Read OpenAI model IDs/creation times using an explicitly injected key."""

    def __init__(
        self,
        *,
        api_key: str | None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._client = _new_client(transport)

    def discover(self, *, fetched_at: datetime | None = None) -> CatalogSnapshot:
        if not self._api_key:
            raise CatalogError("catalog_auth_failed")
        now = _fetched_time(fetched_at)
        page = _bounded_get(
            self._client,
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        raw_models = page.get("data")
        if not isinstance(raw_models, list) or not 1 <= len(raw_models) <= MAX_CATALOG_MODELS:
            raise CatalogError("catalog_invalid")
        models: list[CatalogModelDescriptor] = []
        for raw in raw_models:
            if not isinstance(raw, dict):
                raise CatalogError("catalog_invalid")
            model_id = _valid_model_id(raw.get("id"))
            release_at = _timestamp(raw.get("created"), epoch=True)
            if release_at is not None and release_at > now:
                release_at = None
            # The OpenAI list endpoint does not attest per-model capabilities or
            # reasoning levels. Keep those unknown instead of inheriting provider-wide
            # claims; Product policy can continue using a pinned approved descriptor.
            models.append(
                _descriptor(
                    provider="openai",
                    model=model_id,
                    transports=("openai_api",),
                    capabilities=ModelCapabilities(),
                    release_at=release_at,
                )
            )
        return _snapshot(
            provider="openai",
            transport_id="openai_api",
            source_id="openai_models_v1",
            fetched_at=now,
            models=models,
        )

    def close(self) -> None:
        self._client.close()


class AnthropicCatalogDiscovery:
    """Read Anthropic model capabilities and release times with an injected key."""

    def __init__(
        self,
        *,
        api_key: str | None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._client = _new_client(transport)

    def discover(self, *, fetched_at: datetime | None = None) -> CatalogSnapshot:
        if not self._api_key:
            raise CatalogError("catalog_auth_failed")
        now = _fetched_time(fetched_at)
        models: list[CatalogModelDescriptor] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _ in range(MAX_ANTHROPIC_PAGES):
            params: dict[str, str | int] = {"limit": 1000}
            if cursor is not None:
                params["after_id"] = cursor
            page = _bounded_get(
                self._client,
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                },
                params=params,
            )
            raw_models = page.get("data")
            if not isinstance(raw_models, list) or len(raw_models) > 1000:
                raise CatalogError("catalog_invalid")
            for raw in raw_models:
                if not isinstance(raw, dict):
                    raise CatalogError("catalog_invalid")
                if raw.get("type", "model") != "model":
                    raise CatalogError("catalog_invalid")
                models.append(self._descriptor(raw, now))
                if len(models) > MAX_CATALOG_MODELS:
                    raise CatalogError("catalog_invalid")
            has_more = page.get("has_more", False)
            if type(has_more) is not bool:
                raise CatalogError("catalog_invalid")
            if not has_more:
                break
            next_cursor = page.get("last_id")
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
                raise CatalogError("catalog_invalid")
            seen_cursors.add(next_cursor)
            cursor = _valid_model_id(next_cursor)
        else:
            raise CatalogError("catalog_invalid")
        if not models or len({model.model for model in models}) != len(models):
            raise CatalogError("catalog_invalid")
        return _snapshot(
            provider="anthropic",
            transport_id="anthropic_api",
            source_id="anthropic_models_v1",
            fetched_at=now,
            models=models,
        )

    @staticmethod
    def _descriptor(raw: dict[str, Any], now: datetime) -> CatalogModelDescriptor:
        model_id = _valid_model_id(raw.get("id"))
        created_at = _timestamp(raw.get("created_at"))
        if created_at is not None and created_at > now:
            created_at = None
        capabilities = raw.get("capabilities")
        if capabilities is not None and not isinstance(capabilities, dict):
            raise CatalogError("catalog_invalid")
        capabilities = capabilities if isinstance(capabilities, dict) else {}
        structured = capabilities.get("structured_outputs")
        structured_output = (
            structured.get("supported", False) if isinstance(structured, dict) else False
        )
        if type(structured_output) is not bool:
            raise CatalogError("catalog_invalid")
        effort = capabilities.get("effort")
        efforts: list[str] = []
        if isinstance(effort, dict):
            effort_supported = effort.get("supported", False)
            if type(effort_supported) is not bool:
                raise CatalogError("catalog_invalid")
            for name, support in effort.items():
                if name == "supported":
                    continue
                if not isinstance(support, dict) or type(support.get("supported")) is not bool:
                    raise CatalogError("catalog_invalid")
                if effort_supported and support["supported"]:
                    efforts.append(name)
        elif effort is not None:
            raise CatalogError("catalog_invalid")
        input_tokens = raw.get("max_input_tokens")
        output_tokens = raw.get("max_tokens")
        for limit in (input_tokens, output_tokens):
            if limit is not None and (type(limit) is not int or limit < 0):
                raise CatalogError("catalog_invalid")
        return _descriptor(
            provider="anthropic",
            model=model_id,
            transports=("anthropic_api",),
            capabilities=ModelCapabilities(
                structured_output=structured_output,
                native_tools=False,
                system_prompt_channel=False,
            ),
            reasoning_efforts=tuple(sorted(set(efforts))),
            release_at=created_at,
            context_window=input_tokens or None,
            max_output_tokens=output_tokens or None,
        )

    def close(self) -> None:
        self._client.close()


class OllamaCatalogDiscovery:
    """Expose installed local models; local pull times are never release times."""

    def __init__(self, adapter: OllamaHttpAdapter) -> None:
        self._adapter = adapter

    def discover(self, *, fetched_at: datetime | None = None) -> CatalogSnapshot:
        now = _fetched_time(fetched_at)
        try:
            local_models = self._adapter.list_models()
        except OllamaHttpError as exc:
            if exc.failure_code in {"ollama_unavailable", "ollama_timeout"}:
                raise CatalogError("catalog_unavailable") from None
            raise CatalogError("catalog_invalid") from None
        descriptors = [
            _descriptor(
                provider="ollama",
                model=entry.model,
                transports=("ollama_http",),
                capabilities=ModelCapabilities(
                    structured_output=True,
                    system_prompt_channel=True,
                ),
                literal_system_role_supported=True,
                local_modified_at=entry.local_modified_at,
            )
            for entry in local_models
        ]
        if not descriptors:
            raise CatalogError("catalog_unavailable")
        return _snapshot(
            provider="ollama",
            transport_id="ollama_http",
            source_id="ollama_api_tags",
            fetched_at=now,
            models=descriptors,
        )


def codex_catalog_snapshot(
    raw_models: Sequence[Mapping[str, Any]], *, fetched_at: datetime
) -> CatalogSnapshot:
    """Sanitize app-server model/list entries without trusting list order."""

    now = _fetched_time(fetched_at)
    models: list[CatalogModelDescriptor] = []
    for raw in raw_models:
        model_id = _valid_model_id(raw.get("model", raw.get("id")))
        hidden = raw.get("hidden", False)
        if type(hidden) is not bool:
            raise CatalogError("catalog_invalid")
        if hidden:
            continue
        raw_efforts = raw.get("supportedReasoningEfforts", [])
        if not isinstance(raw_efforts, list) or len(raw_efforts) > 32:
            raise CatalogError("catalog_invalid")
        efforts: list[str] = []
        for item in raw_efforts:
            if not isinstance(item, dict) or not isinstance(item.get("reasoningEffort"), str):
                raise CatalogError("catalog_invalid")
            effort = item["reasoningEffort"]
            if not re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", effort):
                raise CatalogError("catalog_invalid")
            efforts.append(effort)
        if len(efforts) != len(set(efforts)):
            raise CatalogError("catalog_invalid")
        replacement = raw.get("upgrade")
        if replacement is not None:
            replacement = _valid_model_id(replacement)
            if replacement == model_id:
                raise CatalogError("catalog_invalid")
        upgrade_info = raw.get("upgradeInfo")
        sunset_at = None
        if upgrade_info is not None:
            if not isinstance(upgrade_info, dict):
                raise CatalogError("catalog_invalid")
            retirement = upgrade_info.get("retirementAt")
            if retirement is not None:
                if type(retirement) is not int or retirement < 0:
                    raise CatalogError("catalog_invalid")
                try:
                    sunset_at = datetime.fromtimestamp(retirement, timezone.utc)
                except (OverflowError, OSError, ValueError):
                    raise CatalogError("catalog_invalid") from None
        context = raw.get("contextWindow")
        if context is not None and (type(context) is not int or context < 1):
            raise CatalogError("catalog_invalid")
        structured_output = raw.get("structuredOutputSupported", False)
        if type(structured_output) is not bool:
            raise CatalogError("catalog_invalid")
        models.append(
            _descriptor(
                provider="openai",
                model=model_id,
                transports=("codex_cli",),
                capabilities=ModelCapabilities(
                    structured_output=structured_output,
                    native_tools=False,
                    system_prompt_channel=True,
                ),
                reasoning_efforts=tuple(sorted(set(efforts))),
                replacement_model=replacement,
                literal_system_role_supported=False,
                sunset_at=sunset_at,
                deprecated=sunset_at is not None and sunset_at <= now,
                context_window=context,
            )
        )
    if not models:
        raise CatalogError("catalog_invalid")
    return _snapshot(
        provider="openai",
        transport_id="codex_cli",
        source_id="codex_app_server_model_list",
        fetched_at=now,
        models=models,
    )


__all__ = [
    "AnthropicCatalogDiscovery",
    "MAX_CATALOG_MODELS",
    "MAX_CATALOG_RESPONSE_BYTES",
    "OllamaCatalogDiscovery",
    "OpenAICatalogDiscovery",
    "codex_catalog_snapshot",
]
