"""Strict, configuration-backed provider adapter descriptor registry.

The factory is metadata-only except for the explicitly constructed Codex CLI
executor. Provider/model authority remains with each runtime resolver and the
provider census; this module never selects a target or reads credentials.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.components.settings.providers_loader import (
    ProviderCensus,
    ProviderEntry,
    load_provider_census,
)
from app.model_access.codex_cli import CodexCliExecutor
from llm_contract import (
    ModelAccessAdapterDescriptor,
    ModelCapabilities,
    TrustedInstructionMapping,
)


DEFAULT_ADAPTERS_PATH = Path("docs/settings/models/adapters.yaml")
DEFAULT_PROVIDER_CENSUS_PATH = Path("docs/settings/models/providers.yaml")
SUPPORTED_ADAPTER_IDS = frozenset(
    {
        "codex_cli_tailscale",
        "ollama_http_tailscale",
        "codex_cli",
        "ollama_http",
        "openai_api",
        "anthropic_api",
        "deepseek_api",
        "gemini_api",
        "mock",
    }
)
_CAPABILITY_FIELDS = (
    "structured_output",
    "native_tools",
    "system_prompt_channel",
    "deterministic_execution",
)
_CODEX_CLI_CAPABILITY_CEILING = {
    "structured_output": True,
    "native_tools": False,
    "system_prompt_channel": True,
    "deterministic_execution": False,
}
_CODEX_ADAPTERS = frozenset({"codex_cli", "codex_cli_tailscale"})


def _default_model_kinds() -> list[Literal["chat", "embedding"]]:
    return ["chat"]


_TRUSTED_INSTRUCTION_CHANNELS: dict[
    str, Literal["system", "developer_instructions"]
] = {
    "profile.codex_developer_prompt_v1": "developer_instructions",
    "profile.instructions_separate_v1": "system",
}


class _StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class _DeclaredCapabilities(_StrictConfig):
    structured_output: bool = False
    native_tools: bool = False
    system_prompt_channel: bool = False
    deterministic_execution: bool = False


class _AdapterDeclaration(_StrictConfig):
    id: Literal[
        "codex_cli_tailscale",
        "ollama_http_tailscale",
        "codex_cli",
        "ollama_http",
        "openai_api",
        "anthropic_api",
        "deepseek_api",
        "gemini_api",
        "mock",
    ]
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    model_source: Literal["provider_census"]
    transport_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
    model_kinds: list[Literal["chat", "embedding"]] = Field(
        default_factory=_default_model_kinds, min_length=1
    )
    default_for_provider: bool = False
    supported_capabilities: _DeclaredCapabilities
    execution_host_profile: str = Field(pattern=r"^profile\.[a-z][a-z0-9_]*$")
    execution_boundary: Literal[
        "in_process",
        "local_subprocess",
        "local_http",
        "provider_https",
        "private_network_https",
        "private_tailnet_serve_https",
    ]
    authentication_scheme: Literal[
        "none",
        "provider_credential_ref",
        "local_subscription_session",
        "executor_path_authentication",
        "tailscale_app_capability",
    ]
    instruction_mapping_ref: str = Field(pattern=r"^profile\.[a-z][a-z0-9_]*$")

    @model_validator(mode="after")
    def _adapter_is_its_declared_transport(self) -> "_AdapterDeclaration":
        if self.transport_id != self.id:
            raise ValueError("adapter id and transport id must match")
        if len(self.model_kinds) != len(set(self.model_kinds)):
            raise ValueError("adapter model kinds must be unique")
        return self


class _ModelRouteBinding(_StrictConfig):
    """A host-local adapter rule for a logical Product model family."""

    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    model_kind: Literal["chat", "embedding"]
    model_prefix: str = Field(min_length=1, max_length=64)
    model_suffix: str = Field(min_length=1, max_length=64)
    adapter_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")

    def matches(self, model: str) -> bool:
        return (
            model.startswith(self.model_prefix)
            and model.endswith(self.model_suffix)
            and len(model) > len(self.model_prefix) + len(self.model_suffix)
        )


class _AdapterDeclarations(_StrictConfig):
    version: Literal[1]
    adapters: list[_AdapterDeclaration] = Field(min_length=1)
    model_routes: list[_ModelRouteBinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_and_complete(self) -> "_AdapterDeclarations":
        identifiers = [adapter.id for adapter in self.adapters]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("adapter declarations contain duplicate ids")
        if set(identifiers) != SUPPORTED_ADAPTER_IDS:
            raise ValueError("adapter declarations must register exactly the supported ids")
        defaults = [
            adapter.provider for adapter in self.adapters if adapter.default_for_provider
        ]
        providers = {adapter.provider for adapter in self.adapters}
        if set(defaults) != providers or len(defaults) != len(set(defaults)):
            raise ValueError("each adapter provider must declare exactly one default transport")
        route_keys = [
            (
                route.provider,
                route.model_kind,
                route.model_prefix,
                route.model_suffix,
            )
            for route in self.model_routes
        ]
        if len(route_keys) != len(set(route_keys)):
            raise ValueError("model route declarations contain duplicate rules")
        return self


class AdapterRegistryError(ValueError):
    """The selected adapter or its declared provider/model binding is invalid."""


class ModelAccessAdapterFactory:
    """Resolve one already-selected target to its declared adapter metadata."""

    def __init__(
        self,
        *,
        declarations: _AdapterDeclarations,
        provider_census: ProviderCensus,
    ) -> None:
        self._declarations: dict[str, _AdapterDeclaration] = {
            adapter.id: adapter for adapter in declarations.adapters
        }
        self._provider_census = provider_census
        self._model_routes = tuple(declarations.model_routes)
        self._validate_model_routes()

    def _validate_model_routes(self) -> None:
        """Fail closed on invalid or ambiguous model-family adapter rules."""
        for route in self._model_routes:
            adapter = self._declarations.get(route.adapter_id)
            if (
                adapter is None
                or adapter.provider != route.provider
                or route.model_kind not in adapter.model_kinds
            ):
                raise AdapterRegistryError(
                    "model route adapter does not serve its declared provider and kind"
                )
            try:
                provider_entry = self._provider_census.provider(route.provider)
            except KeyError as exc:
                raise AdapterRegistryError(
                    "model route provider is not in the provider census"
                ) from exc
            if route.model_kind not in provider_entry.kinds:
                raise AdapterRegistryError(
                    "model route kind is not declared for its provider"
                )
            if not any(
                route.matches(model.id)
                and self.model_kind_for(route.provider, model.id) == route.model_kind
                for model in provider_entry.models
            ):
                raise AdapterRegistryError(
                    "model route rule does not match a provider-census model"
                )

        for provider in {route.provider for route in self._model_routes}:
            provider_entry = self._provider_census.provider(provider)
            for model in provider_entry.models:
                model_kind = self.model_kind_for(provider, model.id)
                matches = [
                    route
                    for route in self._model_routes
                    if route.provider == provider
                    and route.model_kind == model_kind
                    and route.matches(model.id)
                ]
                if len(matches) > 1:
                    raise AdapterRegistryError(
                        "model route rules overlap for a provider-census model"
                    )

    @classmethod
    def from_declared_sources(
        cls,
        *,
        adapters_path: Path | None = None,
        provider_census_path: Path | None = None,
    ) -> "ModelAccessAdapterFactory":
        adapters_source = adapters_path or DEFAULT_ADAPTERS_PATH
        census_source = provider_census_path or DEFAULT_PROVIDER_CENSUS_PATH
        try:
            raw = yaml.safe_load(adapters_source.read_text(encoding="utf-8"))
            declarations = _AdapterDeclarations.model_validate(raw)
            census = load_provider_census(census_source)
        except (OSError, yaml.YAMLError, ValidationError, ValueError) as exc:
            raise AdapterRegistryError("declared model adapter sources are invalid") from exc
        return cls(declarations=declarations, provider_census=census)

    def describe(
        self,
        adapter_id: str,
        *,
        provider: str,
        model: str,
        model_kind: Literal["chat", "embedding"] = "chat",
    ) -> ModelAccessAdapterDescriptor:
        declaration = self._declarations.get(adapter_id)
        if declaration is None:
            raise AdapterRegistryError("selected adapter is not declared")
        if adapter_id == "codex_cli":
            if (
                declaration.provider != "openai"
                or declaration.transport_id != "codex_cli"
                or declaration.execution_host_profile != "profile.codex_local_cli"
                or declaration.execution_boundary != "local_subprocess"
                or declaration.authentication_scheme != "local_subscription_session"
                or declaration.instruction_mapping_ref
                != "profile.codex_developer_prompt_v1"
            ):
                raise AdapterRegistryError(
                    "Codex CLI declaration exceeds its reviewed execution boundary"
                )
        if adapter_id == "codex_cli_tailscale":
            if (
                declaration.provider != "openai"
                or declaration.transport_id != "codex_cli_tailscale"
                or declaration.execution_host_profile != "profile.codex_remote_host"
                or declaration.execution_boundary != "private_network_https"
                or declaration.authentication_scheme != "executor_path_authentication"
                or declaration.instruction_mapping_ref
                != "profile.codex_developer_prompt_v1"
            ):
                raise AdapterRegistryError(
                    "Tailscale Codex declaration exceeds its reviewed execution boundary"
                )
        if adapter_id == "ollama_http_tailscale":
            if (
                declaration.provider != "ollama"
                or declaration.transport_id != "ollama_http_tailscale"
                or declaration.execution_host_profile != "profile.codex_remote_host"
                or declaration.execution_boundary != "private_network_https"
                or declaration.authentication_scheme != "executor_path_authentication"
                or declaration.instruction_mapping_ref
                != "profile.instructions_separate_v1"
            ):
                raise AdapterRegistryError(
                    "Tailscale Ollama declaration exceeds its reviewed execution boundary"
                )
        if declaration.provider != provider:
            raise AdapterRegistryError("selected adapter does not serve the resolved provider")
        try:
            census_provider = self._provider_census.provider(provider)
        except KeyError as exc:
            raise AdapterRegistryError("resolved provider is not in the provider census") from exc
        census_model = next((item for item in census_provider.models if item.id == model), None)
        if adapter_id == "mock" and provider == "mock" and census_model is None:
            # Mock execution is model-agnostic; keep chat and embedding descriptors
            # separate so their capability surfaces cannot be conflated.
            census_model = next(
                (
                    item
                    for item in census_provider.models
                    if item.id == ("mock-chat" if model_kind == "chat" else "mock-embed")
                ),
                None,
            )
        if (
            census_model is None
            or model_kind not in census_provider.kinds
            or model_kind not in declaration.model_kinds
        ):
            raise AdapterRegistryError(
                f"resolved {model_kind} model is not declared for this provider or adapter"
            )
        embedding_dimension = None
        if model_kind == "embedding":
            embedding_dimension = (
                census_model.capabilities.embedding_dimensions
                or census_provider.capabilities.embedding_dimensions
            )
            if embedding_dimension is None:
                raise AdapterRegistryError(
                    "resolved embedding model has no declared dimensions"
                )
        trusted_channel = _TRUSTED_INSTRUCTION_CHANNELS.get(
            declaration.instruction_mapping_ref
        )
        if trusted_channel is None:
            raise AdapterRegistryError("adapter instruction-channel mapping is unsupported")

        declared = {
            name: bool(
                getattr(census_model.capabilities, name)
                or getattr(census_provider.capabilities, name)
            )
            for name in _CAPABILITY_FIELDS
        }
        capabilities = ModelCapabilities(
            **{
                name: declared[name]
                and getattr(declaration.supported_capabilities, name)
                and (
                    _CODEX_CLI_CAPABILITY_CEILING[name]
                    if adapter_id in _CODEX_ADAPTERS
                    else True
                )
                for name in _CAPABILITY_FIELDS
            },
            embedding_dimension=embedding_dimension,
        )
        return ModelAccessAdapterDescriptor(
            adapter_id=declaration.id,
            provider=provider,
            model=model,
            transport_id=declaration.transport_id,
            supported_capabilities=capabilities,
            execution_host_profile=declaration.execution_host_profile,
            execution_boundary=declaration.execution_boundary,
            authentication_scheme=declaration.authentication_scheme,
            trusted_instruction_mapping=TrustedInstructionMapping(
                mapping_ref=declaration.instruction_mapping_ref,
                trusted_channel=trusted_channel,
                untrusted_channel="user",
            ),
        )

    def create_codex_cli_executor(self, **kwargs: Any) -> CodexCliExecutor:
        """Construct the local Codex executor without selecting a model target."""
        return CodexCliExecutor(**kwargs)

    def default_adapter_id(self, provider: str) -> str:
        """Return the one config-declared default transport for a provider."""
        matches = [
            declaration
            for declaration in self._declarations.values()
            if declaration.provider == provider and declaration.default_for_provider
        ]
        if len(matches) != 1:
            raise AdapterRegistryError("provider has no unique default transport")
        return matches[0].id

    def adapter_id_for(
        self,
        provider: str,
        model: str,
        *,
        model_kind: Literal["chat", "embedding"] = "chat",
    ) -> str:
        """Resolve a host adapter by model family, then by provider default."""
        matches = [
            route
            for route in self._model_routes
            if route.provider == provider
            and route.model_kind == model_kind
            and route.matches(model)
        ]
        if len(matches) > 1:
            raise AdapterRegistryError("model has ambiguous host adapter bindings")
        return matches[0].adapter_id if matches else self.default_adapter_id(provider)

    def model_kind_for(self, provider: str, model: str) -> Literal["chat", "embedding"]:
        """Infer a census model kind for model-bound catalog lookup."""
        provider_entry = self.provider_entry(provider)
        census_model = next(
            (item for item in provider_entry.models if item.id == model), None
        )
        if census_model is None:
            raise AdapterRegistryError("resolved model is not in the provider census")
        if provider_entry.kinds == {"embedding"}:
            return "embedding"
        if (
            "embedding" in provider_entry.kinds
            and census_model.capabilities.embedding_dimensions is not None
        ):
            return "embedding"
        if "chat" in provider_entry.kinds:
            return "chat"
        if "embedding" in provider_entry.kinds:
            return "embedding"
        raise AdapterRegistryError("resolved model has no declared kind")

    def provider_entry(self, provider: str) -> ProviderEntry:
        """Return declared provider metadata without exposing credentials."""
        try:
            return self._provider_census.provider(provider)
        except KeyError as exc:
            raise AdapterRegistryError("provider is not in the provider census") from exc

    def provider_api_endpoint(self, provider: str) -> str | None:
        """Return a provider-owned endpoint from the checked-in census."""
        return self.provider_entry(provider).api_endpoint

    def model_reasoning_efforts(
        self, provider: str, model: str
    ) -> frozenset[str] | None:
        """Return a model's declared effort allowlist; None means unknown."""
        provider_entry = self.provider_entry(provider)
        census_model = next(
            (item for item in provider_entry.models if item.id == model), None
        )
        if census_model is None or "chat" not in provider_entry.kinds:
            raise AdapterRegistryError("resolved chat model is not declared for this provider")
        if census_model.reasoning_efforts is None:
            return None
        return frozenset(census_model.reasoning_efforts)
