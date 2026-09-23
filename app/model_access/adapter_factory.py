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

from app.components.settings.providers_loader import ProviderCensus, load_provider_census
from app.model_access.codex_cli import CodexCliExecutor
from llm_contract import (
    ModelAccessAdapterDescriptor,
    ModelCapabilities,
    TrustedInstructionMapping,
)


DEFAULT_ADAPTERS_PATH = Path("docs/settings/models/adapters.yaml")
DEFAULT_PROVIDER_CENSUS_PATH = Path("docs/settings/models/providers.yaml")
SUPPORTED_ADAPTER_IDS = frozenset(
    {"codex_cli", "ollama_http", "openai_api", "anthropic_api", "deepseek_api", "mock"}
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


class _StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class _DeclaredCapabilities(_StrictConfig):
    structured_output: bool = False
    native_tools: bool = False
    system_prompt_channel: bool = False
    deterministic_execution: bool = False


class _AdapterDeclaration(_StrictConfig):
    id: Literal[
        "codex_cli",
        "ollama_http",
        "openai_api",
        "anthropic_api",
        "deepseek_api",
        "mock",
    ]
    provider: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    model_source: Literal["provider_census"]
    transport_id: str = Field(pattern=r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
    supported_capabilities: _DeclaredCapabilities
    execution_host_profile: str = Field(pattern=r"^profile\.[a-z][a-z0-9_]*$")
    execution_boundary: Literal[
        "in_process", "local_subprocess", "local_http", "provider_https"
    ]
    authentication_scheme: Literal[
        "none", "provider_credential_ref", "local_subscription_session"
    ]
    instruction_mapping_ref: str = Field(pattern=r"^profile\.[a-z][a-z0-9_]*$")

    @model_validator(mode="after")
    def _adapter_is_its_declared_transport(self) -> "_AdapterDeclaration":
        if self.transport_id != self.id:
            raise ValueError("adapter id and transport id must match")
        return self


class _AdapterDeclarations(_StrictConfig):
    version: Literal[1]
    adapters: list[_AdapterDeclaration] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_and_complete(self) -> "_AdapterDeclarations":
        identifiers = [adapter.id for adapter in self.adapters]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("adapter declarations contain duplicate ids")
        if set(identifiers) != SUPPORTED_ADAPTER_IDS:
            raise ValueError("adapter declarations must register exactly the supported ids")
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
        if declaration.provider != provider:
            raise AdapterRegistryError("selected adapter does not serve the resolved provider")
        try:
            census_provider = self._provider_census.provider(provider)
        except KeyError as exc:
            raise AdapterRegistryError("resolved provider is not in the provider census") from exc
        census_model = next((item for item in census_provider.models if item.id == model), None)
        if census_model is None or "chat" not in census_provider.kinds:
            raise AdapterRegistryError("resolved chat model is not declared for this provider")

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
                    if adapter_id == "codex_cli"
                    else True
                )
                for name in _CAPABILITY_FIELDS
            }
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
                trusted_channel="developer_instructions",
                untrusted_channel="user",
            ),
        )

    def create_codex_cli_executor(self, **kwargs: Any) -> CodexCliExecutor:
        """Construct the local Codex executor without selecting a model target."""
        return CodexCliExecutor(**kwargs)
