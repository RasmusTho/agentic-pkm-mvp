from __future__ import annotations

import ast
from pathlib import Path
from typing import Sequence

import pytest

from app.model_access import ModelAccessRouter
from llm_contract import (
    CapabilityProvenance,
    ModelAccessAdapterDescriptor,
    ModelAccessIntent,
    ModelAccessProfile,
    ModelCapabilities,
    ModelCapabilityRequirements,
    ModelResolutionRequest,
    ResolvedModelAccess,
    TrustedInstructionMapping,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


class _Resolver:
    def __init__(self, *, provider: str, model: str, adapter_id: str) -> None:
        self.provider = provider
        self.model = model
        self.adapter_id = adapter_id
        self.calls: list[tuple[str, str, str]] = []

    def resolve(
        self,
        request: ModelResolutionRequest,
        *,
        runtime: str,
        channel: str,
        consumer: str,
    ) -> ResolvedModelAccess:
        self.calls.append((runtime, channel, consumer))
        return ResolvedModelAccess(
            request=request,
            provider=self.provider,
            model=self.model,
            adapter_id=self.adapter_id,
            effective_identity=f"{self.provider}/{self.model}",
            capabilities=ModelCapabilities(
                structured_output=True,
                system_prompt_channel=True,
            ),
            credential_identity_ref=f"{self.provider}.api-key",
        )

    def resolve_group(
        self,
        requests: Sequence[ModelResolutionRequest],
        *,
        runtime: str,
        channel: str,
        consumer: str,
    ) -> tuple[ResolvedModelAccess, ...]:
        return tuple(
            self.resolve(
                request,
                runtime=runtime,
                channel=channel,
                consumer=consumer,
            )
            for request in requests
        )


class _Registry:
    def __init__(self, descriptors: dict[str, ModelAccessAdapterDescriptor]) -> None:
        self.descriptors = descriptors
        self.lookups: list[str] = []

    def describe(self, adapter_id: str) -> ModelAccessAdapterDescriptor:
        self.lookups.append(adapter_id)
        return self.descriptors[adapter_id]


def _profile(
    *,
    profile_id: str,
    runtime: str,
    channel: str,
    consumer: str,
    caller_profile: str,
) -> ModelAccessProfile:
    return ModelAccessProfile(
        profile_id=profile_id,
        runtime=runtime,
        channel=channel,
        consumer=consumer,
        caller_profile=caller_profile,
        catalog_snapshot_ref="catalog.openai_public",
        catalog_snapshot_hash="sha256:" + "c" * 64,
        capability_provenance=CapabilityProvenance(
            source="policy_registry",
            source_ref=profile_id,
        ),
    )


def _descriptor(
    *,
    adapter_id: str,
    provider: str,
    model: str,
    transport_id: str,
    execution_host_profile: str,
    execution_boundary: str,
    authentication_scheme: str,
) -> ModelAccessAdapterDescriptor:
    return ModelAccessAdapterDescriptor(
        adapter_id=adapter_id,
        provider=provider,
        model=model,
        transport_id=transport_id,
        execution_host_profile=execution_host_profile,
        execution_boundary=execution_boundary,
        authentication_scheme=authentication_scheme,
        trusted_instruction_mapping=TrustedInstructionMapping(
            mapping_ref="profile.instructions_separate_v1",
            trusted_channel="developer_instructions",
            untrusted_channel="user",
        ),
    )


def _request() -> ModelResolutionRequest:
    return ModelResolutionRequest(
        intent=ModelAccessIntent(
            capability_tier="standard",
            reasoning_effort="medium",
            determinism_required=False,
            output_schema_ref="agent-response.v1",
            independence="none",
            fallback_requirement="fallback_forbidden",
            side_effect_class="none",
        ),
        role_profile="general-agent",
        resolution_group_id="one-turn",
        requirements=ModelCapabilityRequirements(
            structured_output=True,
            system_prompt_channel=True,
        ),
    )


def test_product_and_builder_profiles_resolve_without_policy_leakage() -> None:
    product_profile = _profile(
        profile_id="profile.product_general",
        runtime="product",
        channel="product.chat",
        consumer="product.agent",
        caller_profile="profile.product_runtime",
    )
    builder_profile = _profile(
        profile_id="profile.builder_inquiry",
        runtime="builder",
        channel="builder.model_inquiry",
        consumer="builder.model_inquiry",
        caller_profile="profile.builder_inquiry",
    )
    product_resolver = _Resolver(
        provider="openai",
        model="gpt-5.6-sol",
        adapter_id="product-openai",
    )
    builder_resolver = _Resolver(
        provider="openai",
        model="gpt-5.6-sol",
        adapter_id="builder-codex-subscription",
    )
    registry = _Registry(
        {
            "product-openai": _descriptor(
                adapter_id="product-openai",
                provider="openai",
                model="gpt-5.6-sol",
                transport_id="openai_api",
                execution_host_profile="profile.provider_openai",
                execution_boundary="provider_https",
                authentication_scheme="provider_credential_ref",
            ),
            "builder-codex-subscription": _descriptor(
                adapter_id="builder-codex-subscription",
                provider="openai",
                model="gpt-5.6-sol",
                transport_id="codex_cli",
                execution_host_profile="profile.builder_host_local",
                execution_boundary="local_subprocess",
                authentication_scheme="local_subscription_session",
            ),
        }
    )
    router = ModelAccessRouter(adapter_registry=registry)

    product_route = router.resolve(
        _request(), resolver=product_resolver, profile=product_profile
    )
    builder_route = router.resolve(
        _request(), resolver=builder_resolver, profile=builder_profile
    )

    assert product_resolver.calls == [("product", "product.chat", "product.agent")]
    assert builder_resolver.calls == [
        ("builder", "builder.model_inquiry", "builder.model_inquiry")
    ]
    assert registry.lookups == ["product-openai", "builder-codex-subscription"]
    assert product_route.transport_id == "openai_api"
    assert product_route.caller_profile == "profile.product_runtime"
    assert product_route.preflight_status == "not_run"
    assert builder_route.transport_id == "codex_cli"
    assert builder_route.execution_host_profile == "profile.builder_host_local"
    assert builder_route.preflight_status == "not_run"
    assert builder_route.request.intent.fallback_requirement == "fallback_forbidden"

    source = (REPO_ROOT / "app/model_access/router.py").read_text(encoding="utf-8")
    imports = {
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any(
        module == "app.builderops"
        or module.startswith("app.builderops.")
        or module.startswith("app.components.llm")
        or module.startswith("app.services.llm")
        for module in imports
    )


def test_facade_rejects_registry_identity_drift_before_execution() -> None:
    profile = _profile(
        profile_id="profile.product_general",
        runtime="product",
        channel="product.chat",
        consumer="product.agent",
        caller_profile="profile.product_runtime",
    )
    resolver = _Resolver(
        provider="openai",
        model="gpt-5.6-sol",
        adapter_id="selected-adapter",
    )
    registry = _Registry(
        {
            "selected-adapter": _descriptor(
                adapter_id="selected-adapter",
                provider="anthropic",
                model="claude-fable-5",
                transport_id="anthropic_api",
                execution_host_profile="profile.provider_anthropic",
                execution_boundary="provider_https",
                authentication_scheme="provider_credential_ref",
            )
        }
    )

    with pytest.raises(ValueError, match="does not match resolved target"):
        ModelAccessRouter(adapter_registry=registry).resolve(
            _request(), resolver=resolver, profile=profile
        )
