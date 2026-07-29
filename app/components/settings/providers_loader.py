"""Strict loader for the declared model-provider census.

The running Product paths deliberately retain their compiled local provider
sets, so for Product this module remains an authoring and verification surface
rather than a routing dependency.  The Builder Model Access resolver
(`app/builderops/model_access_resolver.py`, ADR-0064 / MAS-05) is the one
runtime consumer: it selects provider, model, effective identity, and the
declared credential identifier from these exact mappings.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


DEFAULT_PROVIDER_CENSUS_PATH = Path("docs/settings/models/providers.yaml")


class ProviderCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    structured_output: bool = False
    native_tools: bool = False
    system_prompt_channel: bool = False
    deterministic_execution: bool = False
    embedding_dimensions: int | None = None


class DeclaredModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    effective_identity: str = Field(min_length=1)
    capabilities: ProviderCapabilities


class ProviderEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    kinds: set[Literal["chat", "embedding"]] = Field(min_length=1)
    tier: Literal["local", "paid", "test"]
    capabilities: ProviderCapabilities
    # Declared provider API endpoint. It is provider-owned census data, never
    # caller configuration; a runtime resolver reads it and no caller may supply
    # or override it.
    api_endpoint: str | None = None
    paid_eligible_task_kinds: list[str] = Field(default_factory=list)
    credential_identifiers: list[str] = Field(default_factory=list)
    excluded_model_families: list[str] = Field(default_factory=list)
    models: list[DeclaredModel] = Field(default_factory=list)


class ProviderProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site: str = Field(min_length=1)
    providers: set[str] = Field(default_factory=set)


class KnownDivergence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site: str = Field(min_length=1)
    divergent_members: set[str] = Field(min_length=1)
    declared_on: str = Field(min_length=1)
    issue: str = Field(pattern=r"^https://github\.com/[^/]+/[^/]+/issues/\d+$")


class TierMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    requires: set[Literal["structured_output", "native_tools", "system_prompt_channel", "deterministic_execution"]] = Field(default_factory=set)


class RoleProfile(TierMapping):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1)
    capability_tier: str = Field(min_length=1)
    credential_identifier: str = Field(min_length=1)
    resolution_group: str = Field(min_length=1)


class ResolutionGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    independence: Literal["distinct_effective_target"]


class RuntimeChannelMappings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: dict[str, dict[str, TierMapping]] = Field(default_factory=dict)
    builder: dict[str, dict[str, TierMapping]] = Field(default_factory=dict)
    model_inquiry_profiles: dict[str, list[RoleProfile]] = Field(default_factory=dict)
    resolution_groups: list[ResolutionGroup] = Field(default_factory=list)


class ProviderCensus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    providers: list[ProviderEntry] = Field(min_length=1)
    projections: list[ProviderProjection] = Field(default_factory=list)
    known_divergences: list[KnownDivergence] = Field(default_factory=list)
    runtime_channels: RuntimeChannelMappings

    @model_validator(mode="after")
    def _validate_unique_provider_and_model_ids(self) -> "ProviderCensus":
        provider_ids = [provider.id for provider in self.providers]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("Provider census contains duplicate provider ids")
        for provider in self.providers:
            model_ids = [model.id for model in provider.models]
            if len(model_ids) != len(set(model_ids)):
                raise ValueError(f"Provider census contains duplicate models for {provider.id}")
        mappings: list[TierMapping] = []
        for runtime in (self.runtime_channels.product, self.runtime_channels.builder):
            mappings.extend(mapping for channel in runtime.values() for mapping in channel.values())
        mappings.extend(
            profile
            for profiles in self.runtime_channels.model_inquiry_profiles.values()
            for profile in profiles
        )
        for mapping in mappings:
            provider = self.provider(mapping.provider)
            model = next((item for item in provider.models if item.id == mapping.model), None)
            if model is None:
                raise ValueError(f"Provider census mapping references undeclared model {mapping.provider}/{mapping.model}")
            for capability in mapping.requires:
                if not getattr(model.capabilities, capability) and not getattr(provider.capabilities, capability):
                    raise ValueError(
                        f"Provider census mapping {mapping.provider}/{mapping.model} lacks {capability}"
                    )
            if isinstance(mapping, RoleProfile) and mapping.credential_identifier not in provider.credential_identifiers:
                raise ValueError(
                    f"Provider census role profile {mapping.role} uses undeclared credential "
                    f"{mapping.credential_identifier}"
                )
        groups = {group.id: group for group in self.runtime_channels.resolution_groups}
        if set(groups) != {"model-inquiry-independent-review"}:
            raise ValueError("Provider census must define exactly model-inquiry-independent-review")
        if groups["model-inquiry-independent-review"].independence != "distinct_effective_target":
            raise ValueError("Model Inquiry review group must require distinct_effective_target")
        for profiles in self.runtime_channels.model_inquiry_profiles.values():
            if {profile.resolution_group for profile in profiles} != {"model-inquiry-independent-review"}:
                raise ValueError("Model Inquiry profiles must reference the independent-review group")
        return self

    def provider(self, provider_id: str) -> ProviderEntry:
        for provider in self.providers:
            if provider.id == provider_id:
                return provider
        raise KeyError(provider_id)

    def projection(self, site: str) -> set[str]:
        for projection in self.projections:
            if projection.site == site:
                return set(projection.providers)
        raise KeyError(site)


class ProviderProjectionDriftError(ValueError):
    """A live allowlist differs from its census projection without a receipt."""


def assert_provider_projection(census: ProviderCensus, site: str, actual: set[str]) -> None:
    """Fail closed unless the exact projection difference has a dated issue receipt."""
    expected = census.projection(site)
    difference = actual ^ expected
    if not difference:
        return
    declared = set().union(
        *(item.divergent_members for item in census.known_divergences if item.site == site)
    )
    if difference <= declared:
        return
    raise ProviderProjectionDriftError(
        f"provider allowlist drift at {site}: actual={actual}, expected={expected}, "
        f"undeclared={difference - declared}"
    )


def _read_yaml(path: Path) -> dict[str, object]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Provider census at {path} must be a mapping")
    return payload


def load_provider_census(path: Path | None = None) -> ProviderCensus:
    raw_path = os.getenv("PROVIDER_CENSUS_PATH")
    census_path = Path(raw_path) if raw_path else (path or DEFAULT_PROVIDER_CENSUS_PATH)
    try:
        return ProviderCensus(**_read_yaml(census_path))
    except ValidationError as exc:
        raise ValueError(f"Invalid provider census at {census_path}: {exc}") from exc
