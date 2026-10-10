"""Small, strict request/response contract for the private model executor API."""

from __future__ import annotations

import json
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.model_access.catalog import CatalogSnapshot


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


JudgmentOutcome = Literal[
    "unavailable_before_send", "outcome_unknown_after_dispatch",
    "provider_rejected", "response_invalid", "success",
]


class JudgmentUsage(_StrictModel):
    input_tokens: int | None = Field(default=None, ge=0, le=1_000_000)
    output_tokens: int | None = Field(default=None, ge=0, le=1_000_000)


class CompletionRouteIdentity(_StrictModel):
    """The exact provider/model/transport already selected by Product policy."""

    provider: Literal["openai", "anthropic", "deepseek", "ollama"]
    model: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$",
    )
    transport_id: Literal[
        "codex_cli", "ollama_http", "openai_api", "anthropic_api", "deepseek_api"
    ]
    catalog_snapshot_ref: str | None = Field(
        default=None, pattern=r"^catalog\.[a-z][a-z0-9_]*$"
    )
    catalog_snapshot_hash: str | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )

    @model_validator(mode="after")
    def _provider_matches_transport(self) -> "CompletionRouteIdentity":
        expected_provider = {
            "codex_cli": "openai",
            "ollama_http": "ollama",
            "openai_api": "openai",
            "anthropic_api": "anthropic",
            "deepseek_api": "deepseek",
        }[self.transport_id]
        if self.provider != expected_provider:
            raise ValueError("provider and transport do not form an allowed route")
        if (self.catalog_snapshot_ref is None) != (self.catalog_snapshot_hash is None):
            raise ValueError("catalog snapshot reference and hash must be supplied together")
        return self

    def same_execution_target(self, other: "CompletionRouteIdentity") -> bool:
        """Whether two receipts name the same provider/model/transport.

        Catalog snapshots are execution provenance, not caller-selected Product
        targets. The Mac may refresh a snapshot between its no-inference preflight
        and completion; the completion response then carries the actual snapshot.
        """
        return (self.provider, self.model, self.transport_id) == (
            other.provider,
            other.model,
            other.transport_id,
        )


class CompletionCapabilityIntent(_StrictModel):
    """Capabilities required by this single completion request."""

    structured_output: bool = False
    native_tools: bool = False
    literal_system_role_required: bool = False
    max_output_tokens_required: bool = False


class ProductModelTarget(_StrictModel):
    """Logical Product target; the Mac host resolves its adapter and transport."""

    provider: Literal["openai", "anthropic", "deepseek", "ollama"]
    model: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$",
    )


class ProductCompletionRequest(ProductModelTarget):
    """Bounded Product completion with no caller-selected harness or catalog proof."""

    reasoning_effort: Literal[
        "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"
    ] | None = None
    service_tier: Literal["default"] | None = None
    capability_intent: CompletionCapabilityIntent = Field(
        default_factory=CompletionCapabilityIntent
    )
    trusted_instructions: str = Field(max_length=32_768)
    user_input: str = Field(min_length=1, max_length=96_000)
    output_schema: dict[str, Any] | None = None
    max_output_tokens: int | None = Field(default=None, ge=1, le=1_000_000)

    @model_validator(mode="after")
    def _request_matches_declared_capabilities(self) -> "ProductCompletionRequest":
        if self.capability_intent.structured_output != (self.output_schema is not None):
            raise ValueError("structured output intent must match the supplied schema")
        if self.capability_intent.max_output_tokens_required != (
            self.max_output_tokens is not None
        ):
            raise ValueError("output token limit intent must match the supplied limit")
        return self


class ProductPreflightRequest(ProductModelTarget):
    """No-inference Product preflight; the host resolves transport and catalog."""

    reasoning_effort: Literal[
        "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"
    ] | None = None
    service_tier: Literal["default"] | None = None
    capability_intent: CompletionCapabilityIntent = Field(
        default_factory=CompletionCapabilityIntent
    )


class ProductCatalogRequest(_StrictModel):
    """Ask the host for the catalog bound to a logical Product target."""

    provider: Literal["openai", "anthropic", "deepseek", "gemini", "ollama", "mock"]
    model: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$",
    )


class EmbeddingRouteIdentity(_StrictModel):
    """The exact embedding route resolved by the Mac host."""

    provider: Literal["gemini", "ollama", "mock"]
    model: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$",
    )
    transport_id: Literal["gemini_api", "ollama_http", "mock"]
    catalog_snapshot_ref: str | None = Field(
        default=None, pattern=r"^catalog\.[a-z][a-z0-9_]*$"
    )
    catalog_snapshot_hash: str | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )

    @model_validator(mode="after")
    def _provider_matches_transport(self) -> "EmbeddingRouteIdentity":
        expected_provider = {
            "gemini_api": "gemini",
            "ollama_http": "ollama",
            "mock": "mock",
        }[self.transport_id]
        if self.provider != expected_provider:
            raise ValueError("provider and embedding transport do not form an allowed route")
        if (self.catalog_snapshot_ref is None) != (self.catalog_snapshot_hash is None):
            raise ValueError("catalog snapshot reference and hash must be supplied together")
        return self


class ProductEmbeddingRequest(_StrictModel):
    """One bounded logical Product embedding request; transport and credentials are host-owned."""

    provider: Literal["gemini", "ollama", "mock"]
    model: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$",
    )
    dimensions: int = Field(ge=1, le=4096)
    input_text: str = Field(min_length=1, max_length=64_000)


class ProductEmbeddingResponse(_StrictModel):
    """One exact host-resolved embedding route and its dimension-bounded vector."""

    route: EmbeddingRouteIdentity
    dimensions: int = Field(ge=1, le=4096)
    vector: tuple[float, ...] = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def _vector_matches_declared_dimensions(self) -> "ProductEmbeddingResponse":
        if self.route.catalog_snapshot_ref is None or self.route.catalog_snapshot_hash is None:
            raise ValueError("embedding response must include host catalog provenance")
        if len(self.vector) != self.dimensions:
            raise ValueError("embedding vector length must match declared dimensions")
        return self


class CompletionRequest(_StrictModel):
    """A bounded completion request with no execution or credential controls."""

    route: CompletionRouteIdentity
    reasoning_effort: Literal[
        "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"
    ] | None = None
    service_tier: Literal["default"] | None = None
    capability_intent: CompletionCapabilityIntent = Field(
        default_factory=CompletionCapabilityIntent
    )
    trusted_instructions: str = Field(max_length=32_768)
    user_input: str = Field(min_length=1, max_length=96_000)
    output_schema: dict[str, Any] | None = None
    max_output_tokens: int | None = Field(default=None, ge=1, le=1_000_000)

    @model_validator(mode="after")
    def _request_matches_declared_capabilities(self) -> "CompletionRequest":
        if self.route.transport_id == "codex_cli" and self.reasoning_effort is None:
            raise ValueError("Codex CLI routes require an explicit reasoning effort")
        if self.route.transport_id == "ollama_http" and self.reasoning_effort is not None:
            raise ValueError("Ollama routes do not accept Codex reasoning effort")
        if self.service_tier is not None and self.route.transport_id != "openai_api":
            raise ValueError("service tier is supported only by OpenAI API routes")
        if self.capability_intent.structured_output != (self.output_schema is not None):
            raise ValueError("structured output intent must match the supplied schema")
        if self.capability_intent.max_output_tokens_required != (
            self.max_output_tokens is not None
        ):
            raise ValueError("output token limit intent must match the supplied limit")
        return self


class PreflightRequest(_StrictModel):
    """A no-inference check for one exact route and capability intent."""

    route: CompletionRouteIdentity
    reasoning_effort: Literal[
        "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"
    ] | None = None
    service_tier: Literal["default"] | None = None
    capability_intent: CompletionCapabilityIntent = Field(
        default_factory=CompletionCapabilityIntent
    )

    @model_validator(mode="after")
    def _preflight_matches_route(self) -> "PreflightRequest":
        if self.route.transport_id == "codex_cli" and self.reasoning_effort is None:
            raise ValueError("Codex CLI preflight requires an explicit reasoning effort")
        if self.route.transport_id == "ollama_http" and self.reasoning_effort is not None:
            raise ValueError("Ollama preflight does not accept Codex reasoning effort")
        if self.service_tier is not None and self.route.transport_id != "openai_api":
            raise ValueError("service tier is supported only by OpenAI API routes")
        return self


class CompletionPromptTokenDetails(_StrictModel):
    """Whitelisted prompt-token details needed for usage evidence."""

    cached_tokens: int | None = Field(default=None, ge=0, le=1_000_000)
    audio_tokens: int | None = Field(default=None, ge=0, le=1_000_000)
    cache_write_tokens: int | None = Field(default=None, ge=0, le=1_000_000)
    cache_creation_tokens: int | None = Field(default=None, ge=0, le=1_000_000)


class CompletionTokenUsage(_StrictModel):
    """Bounded token counts; excludes provider request/response content."""

    prompt_tokens: int | None = Field(default=None, ge=0, le=1_000_000)
    completion_tokens: int | None = Field(default=None, ge=0, le=1_000_000)
    total_tokens: int | None = Field(default=None, ge=0, le=1_000_000)
    prompt_tokens_details: CompletionPromptTokenDetails | None = None


class CompletionUsageMetadata(_StrictModel):
    """Minimal provider billing evidence safe to cross the private portal."""

    model: str | None = Field(
        default=None,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$",
    )
    service_tier: str | None = Field(
        default=None,
        max_length=32,
        pattern=r"^[A-Za-z0-9_-]{1,32}$",
    )
    usage: CompletionTokenUsage | None = None


class CompletionResponse(_StrictModel):
    """The completion and the exact route that produced it."""

    route: CompletionRouteIdentity
    content: str = Field(min_length=1, max_length=512_000)
    dispatched_reasoning_effort: Literal[
        "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"
    ] | None = None
    usage: CompletionUsageMetadata | None = None


class PreflightResponse(_StrictModel):
    """Successful, route-bound result of a check that performed no inference."""

    route: CompletionRouteIdentity
    preflight_status: Literal["passed"]


class CatalogRequest(_StrictModel):
    """Select a catalog source on the executor; never accepts an endpoint or model call."""

    transport_id: Literal[
        "codex_cli", "ollama_http", "openai_api", "anthropic_api", "deepseek_api"
    ]


class CatalogResponse(_StrictModel):
    """Sanitized, content-hash-bound result of a read-only catalog operation."""

    snapshot: CatalogSnapshot


def validate_inline_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Validate a small inline JSON Schema without external reference resolution."""

    from jsonschema import Draft202012Validator
    from jsonschema.exceptions import SchemaError

    try:
        serialized = json.dumps(
            schema,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if len(serialized.encode("utf-8")) > 64_000:
            raise ValueError("schema too large")

        nodes = 0
        stack: list[tuple[Any, int]] = [(schema, 0)]
        while stack:
            value, depth = stack.pop()
            nodes += 1
            if nodes > 2_048 or depth > 32:
                raise ValueError("schema complexity limit exceeded")
            if isinstance(value, dict):
                if {"$ref", "$dynamicRef", "$recursiveRef"}.intersection(value):
                    raise ValueError("schema references are not supported")
                stack.extend((child, depth + 1) for child in value.values())
            elif isinstance(value, list):
                stack.extend((child, depth + 1) for child in value)

        Draft202012Validator.check_schema(schema)
    except (TypeError, ValueError, OverflowError, RecursionError, SchemaError) as exc:
        raise ValueError("output schema is invalid or outside the supported bounds") from exc
    return schema


def _reject_schema_retrieval(uri: Any) -> None:
    from referencing.exceptions import NoSuchResource

    raise NoSuchResource(uri)


def inline_schema_validator(schema: dict[str, Any]) -> Any:
    """Build a validator whose registry cannot retrieve caller-controlled resources."""

    from jsonschema import Draft202012Validator
    from referencing import Registry

    validate_inline_schema(schema)
    return Draft202012Validator(
        schema,
        registry=cast(Any, Registry)(retrieve=_reject_schema_retrieval),
    )


__all__ = [
    "CompletionCapabilityIntent",
    "CompletionRequest",
    "CompletionResponse",
    "CompletionRouteIdentity",
    "CatalogRequest",
    "CatalogResponse",
    "PreflightRequest",
    "PreflightResponse",
    "inline_schema_validator",
    "validate_inline_schema",
]
