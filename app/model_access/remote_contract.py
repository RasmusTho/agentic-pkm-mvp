"""Small, strict request/response contract for the private model executor API."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CompletionRouteIdentity(_StrictModel):
    """The exact provider/model/transport already selected by Product policy."""

    provider: Literal["openai", "ollama"]
    model: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$",
    )
    transport_id: Literal["codex_cli", "ollama_http"]

    @model_validator(mode="after")
    def _provider_matches_transport(self) -> "CompletionRouteIdentity":
        expected_provider = {
            "codex_cli": "openai",
            "ollama_http": "ollama",
        }[self.transport_id]
        if self.provider != expected_provider:
            raise ValueError("provider and transport do not form an allowed route")
        return self


class CompletionCapabilityIntent(_StrictModel):
    """Capabilities required by this single completion request."""

    structured_output: bool = False
    native_tools: bool = False
    literal_system_role_required: bool = False


class CompletionRequest(_StrictModel):
    """A bounded completion request with no execution or credential controls."""

    route: CompletionRouteIdentity
    reasoning_effort: Literal[
        "minimal", "low", "medium", "high", "xhigh", "max", "ultra"
    ] | None = None
    capability_intent: CompletionCapabilityIntent = Field(
        default_factory=CompletionCapabilityIntent
    )
    trusted_instructions: str = Field(max_length=32_768)
    user_input: str = Field(min_length=1, max_length=96_000)
    output_schema: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _request_matches_declared_capabilities(self) -> "CompletionRequest":
        if self.route.transport_id == "codex_cli" and self.reasoning_effort is None:
            raise ValueError("Codex CLI routes require an explicit reasoning effort")
        if self.route.transport_id == "ollama_http" and self.reasoning_effort is not None:
            raise ValueError("Ollama routes do not accept Codex reasoning effort")
        if self.capability_intent.structured_output != (self.output_schema is not None):
            raise ValueError("structured output intent must match the supplied schema")
        return self


class CompletionResponse(_StrictModel):
    """The completion and the exact route that produced it."""

    route: CompletionRouteIdentity
    content: str = Field(min_length=1, max_length=512_000)


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
                if "$ref" in value:
                    raise ValueError("schema references are not supported")
                stack.extend((child, depth + 1) for child in value.values())
            elif isinstance(value, list):
                stack.extend((child, depth + 1) for child in value)

        Draft202012Validator.check_schema(schema)
    except (TypeError, ValueError, OverflowError, RecursionError, SchemaError) as exc:
        raise ValueError("output schema is invalid or outside the supported bounds") from exc
    return schema


__all__ = [
    "CompletionCapabilityIntent",
    "CompletionRequest",
    "CompletionResponse",
    "CompletionRouteIdentity",
    "validate_inline_schema",
]
