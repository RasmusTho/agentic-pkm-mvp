from __future__ import annotations

import ast
from pathlib import Path
from typing import Sequence

from pydantic import ValidationError
import pytest

from app.model_access import ModelAccessRouter
from llm_contract import (
    CapabilityProvenance,
    FallbackProvenance,
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
    def __init__(
        self,
        *,
        provider: str,
        model: str,
        adapter_id: str,
        capabilities: ModelCapabilities | None = None,
        degraded: bool = False,
        degradation_reason: str | None = None,
        fallback_provenance: FallbackProvenance | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.adapter_id = adapter_id
        self.capabilities = capabilities or ModelCapabilities(
            structured_output=True,
            system_prompt_channel=True,
        )
        self.degraded = degraded
        self.degradation_reason = degradation_reason
        self.fallback_provenance = fallback_provenance or FallbackProvenance()
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
            capabilities=self.capabilities,
            credential_identity_ref=f"{self.provider}.api-key",
            degraded=self.degraded,
            degradation_reason=self.degradation_reason,
            fallback_provenance=self.fallback_provenance,
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
        self.lookups: list[tuple[str, str, str]] = []

    def describe(
        self,
        adapter_id: str,
        *,
        provider: str,
        model: str,
    ) -> ModelAccessAdapterDescriptor:
        self.lookups.append((adapter_id, provider, model))
        return self.descriptors[adapter_id]


def _profile(
    *,
    profile_id: str,
    runtime: str,
    channel: str,
    consumer: str,
    caller_profile: str,
    capability_provenance: CapabilityProvenance | None = None,
) -> ModelAccessProfile:
    return ModelAccessProfile(
        profile_id=profile_id,
        runtime=runtime,
        channel=channel,
        consumer=consumer,
        caller_profile=caller_profile,
        catalog_snapshot_ref="catalog.openai_public",
        catalog_snapshot_hash="sha256:" + "c" * 64,
        capability_provenance=capability_provenance
        or CapabilityProvenance(source="policy_registry", source_ref=profile_id),
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
    supported_capabilities: ModelCapabilities | None = None,
    trusted_instruction_mapping: TrustedInstructionMapping | None = None,
) -> ModelAccessAdapterDescriptor:
    return ModelAccessAdapterDescriptor(
        adapter_id=adapter_id,
        provider=provider,
        model=model,
        transport_id=transport_id,
        supported_capabilities=supported_capabilities
        or ModelCapabilities(structured_output=True, system_prompt_channel=True),
        execution_host_profile=execution_host_profile,
        execution_boundary=execution_boundary,
        authentication_scheme=authentication_scheme,
        trusted_instruction_mapping=trusted_instruction_mapping
        or TrustedInstructionMapping(
            mapping_ref="profile.instructions_separate_v1",
            trusted_channel="developer_instructions",
            untrusted_channel="user",
        ),
    )


def _request(
    *, fallback_requirement: str = "fallback_forbidden"
) -> ModelResolutionRequest:
    return ModelResolutionRequest(
        intent=ModelAccessIntent(
            capability_tier="standard",
            reasoning_effort="medium",
            determinism_required=False,
            output_schema_ref="agent-response.v1",
            independence="none",
            fallback_requirement=fallback_requirement,
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
    assert registry.lookups == [
        ("product-openai", "openai", "gpt-5.6-sol"),
        ("builder-codex-subscription", "openai", "gpt-5.6-sol"),
    ]
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


def test_facade_accepts_model_specific_adapter_id_from_builder_resolver() -> None:
    profile = _profile(
        profile_id="profile.builder_inquiry",
        runtime="builder",
        channel="builder.model_inquiry",
        consumer="builder.model_inquiry",
        caller_profile="profile.builder_inquiry",
    )
    adapter_id = "ollama-llama3.1:8b"
    resolver = _Resolver(
        provider="ollama",
        model="llama3.1:8b",
        adapter_id=adapter_id,
    )
    registry = _Registry(
        {
            adapter_id: _descriptor(
                adapter_id=adapter_id,
                provider="ollama",
                model="llama3.1:8b",
                transport_id="ollama_http",
                execution_host_profile="profile.macos_ollama",
                execution_boundary="local_http",
                authentication_scheme="none",
            )
        }
    )

    route = ModelAccessRouter(adapter_registry=registry).resolve(
        _request(), resolver=resolver, profile=profile
    )

    assert route.adapter_id == adapter_id
    assert route.model == "llama3.1:8b"


def test_facade_revalidates_resolver_result_before_adapter_lookup() -> None:
    profile = _profile(
        profile_id="profile.product_general",
        runtime="product",
        channel="product.chat",
        consumer="product.agent",
        caller_profile="profile.product_runtime",
    )

    class ResolverUsingUncheckedCopy(_Resolver):
        def resolve(
            self,
            request: ModelResolutionRequest,
            *,
            runtime: str,
            channel: str,
            consumer: str,
        ) -> ResolvedModelAccess:
            result = super().resolve(
                request,
                runtime=runtime,
                channel=channel,
                consumer=consumer,
            )
            return result.model_copy(
                update={"credential_identity_ref": "sk-proj-1234567890abcdefgh"}
            )

    resolver = ResolverUsingUncheckedCopy(
        provider="openai",
        model="gpt-5.6-sol",
        adapter_id="selected-adapter",
    )
    registry = _Registry(
        {
            "selected-adapter": _descriptor(
                adapter_id="selected-adapter",
                provider="openai",
                model="gpt-5.6-sol",
                transport_id="openai_api",
                execution_host_profile="profile.provider_openai",
                execution_boundary="provider_https",
                authentication_scheme="provider_credential_ref",
            )
        }
    )

    with pytest.raises(ValidationError, match="credential_identity_ref"):
        ModelAccessRouter(adapter_registry=registry).resolve(
            _request(), resolver=resolver, profile=profile
        )

    assert registry.lookups == []


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


def test_facade_preserves_and_binds_resolver_fallback_provenance() -> None:
    profile = _profile(
        profile_id="profile.product_general",
        runtime="product",
        channel="product.chat",
        consumer="product.agent",
        caller_profile="profile.product_runtime",
    )
    request = _request(fallback_requirement="fallback_policy_selected")
    provenance = FallbackProvenance(
        used=True,
        phase="preflight",
        reason_code="executor_unreachable",
        source_transport_id="codex_cli",
        selected_transport_id="openai_api",
        policy_authority=profile.profile_id,
        source_effective_identity="codex/gpt-5.6-sol",
        selected_effective_identity="openai/gpt-5.6-sol",
    )
    resolver = _Resolver(
        provider="openai",
        model="gpt-5.6-sol",
        adapter_id="selected-adapter",
        degraded=True,
        degradation_reason="preflight_fallback",
        fallback_provenance=provenance,
    )
    registry = _Registry(
        {
            "selected-adapter": _descriptor(
                adapter_id="selected-adapter",
                provider="openai",
                model="gpt-5.6-sol",
                transport_id="openai_api",
                execution_host_profile="profile.provider_openai",
                execution_boundary="provider_https",
                authentication_scheme="provider_credential_ref",
            )
        }
    )

    route = ModelAccessRouter(adapter_registry=registry).resolve(
        request, resolver=resolver, profile=profile
    )

    assert route.fallback_provenance == provenance
    assert route.fallback_provenance.policy_authority == profile.profile_id
    assert route.fallback_provenance.selected_transport_id == route.transport_id
    assert route.fallback_provenance.selected_effective_identity == route.effective_identity
    assert route.degraded is True
    assert route.preflight_status == "not_run"


@pytest.mark.parametrize(
    ("mismatch", "expected_error"),
    [
        ("identity", "fallback selected identity"),
        ("transport", "fallback selected transport"),
        ("policy", "fallback policy authority"),
        ("degradation", "visibly degraded"),
    ],
)
def test_facade_rejects_fallback_provenance_that_mismatches_selected_route(
    mismatch: str,
    expected_error: str,
) -> None:
    profile = _profile(
        profile_id="profile.product_general",
        runtime="product",
        channel="product.chat",
        consumer="product.agent",
        caller_profile="profile.product_runtime",
    )
    provenance_values = {
        "used": True,
        "phase": "preflight",
        "reason_code": "executor_unreachable",
        "source_transport_id": "codex_cli",
        "selected_transport_id": "openai_api",
        "policy_authority": profile.profile_id,
        "source_effective_identity": "codex/gpt-5.6-sol",
        "selected_effective_identity": "openai/gpt-5.6-sol",
    }
    if mismatch == "identity":
        provenance_values["selected_effective_identity"] = "anthropic/claude-fable"
    elif mismatch == "transport":
        provenance_values["selected_transport_id"] = "anthropic_api"
    elif mismatch == "policy":
        provenance_values["policy_authority"] = "profile.other_policy"
    provenance = FallbackProvenance(**provenance_values)
    resolver = _Resolver(
        provider="openai",
        model="gpt-5.6-sol",
        adapter_id="selected-adapter",
        degraded=mismatch != "degradation",
        degradation_reason=(
            "preflight_fallback" if mismatch != "degradation" else None
        ),
        fallback_provenance=provenance,
    )
    registry = _Registry(
        {
            "selected-adapter": _descriptor(
                adapter_id="selected-adapter",
                provider="openai",
                model="gpt-5.6-sol",
                transport_id="openai_api",
                execution_host_profile="profile.provider_openai",
                execution_boundary="provider_https",
                authentication_scheme="provider_credential_ref",
            )
        }
    )

    with pytest.raises(ValueError, match=expected_error):
        ModelAccessRouter(adapter_registry=registry).resolve(
            _request(fallback_requirement="fallback_policy_selected"),
            resolver=resolver,
            profile=profile,
        )

    if mismatch in {"identity", "degradation"}:
        assert registry.lookups == []
    else:
        assert registry.lookups == [
            ("selected-adapter", "openai", "gpt-5.6-sol")
        ]


def test_facade_rejects_capabilities_not_attested_by_adapter() -> None:
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
        capabilities=ModelCapabilities(
            structured_output=True,
            system_prompt_channel=True,
            native_tools=True,
        ),
    )
    registry = _Registry(
        {
            "selected-adapter": _descriptor(
                adapter_id="selected-adapter",
                provider="openai",
                model="gpt-5.6-sol",
                transport_id="openai_api",
                execution_host_profile="profile.provider_openai",
                execution_boundary="provider_https",
                authentication_scheme="provider_credential_ref",
            )
        }
    )

    with pytest.raises(ValueError, match="native_tools"):
        ModelAccessRouter(adapter_registry=registry).resolve(
            _request(), resolver=resolver, profile=profile
        )


def test_facade_enforces_literal_system_role_mapping() -> None:
    profile = _profile(
        profile_id="profile.product_general",
        runtime="product",
        channel="product.chat",
        consumer="product.agent",
        caller_profile="profile.product_runtime",
    )
    base_request = _request()
    request = base_request.model_copy(
        update={
            "requirements": base_request.requirements.model_copy(
                update={"literal_system_role_required": True}
            )
        }
    )
    resolver = _Resolver(
        provider="openai",
        model="gpt-5.6-sol",
        adapter_id="selected-adapter",
    )
    descriptor_values = {
        "adapter_id": "selected-adapter",
        "provider": "openai",
        "model": "gpt-5.6-sol",
        "transport_id": "openai_api",
        "execution_host_profile": "profile.provider_openai",
        "execution_boundary": "provider_https",
        "authentication_scheme": "provider_credential_ref",
    }
    with pytest.raises(ValidationError, match="literal system role"):
        ModelAccessRouter(
            adapter_registry=_Registry(
                {"selected-adapter": _descriptor(**descriptor_values)}
            )
        ).resolve(request, resolver=resolver, profile=profile)

    system_mapping = TrustedInstructionMapping(
        mapping_ref="profile.instructions_openai_system_v1",
        trusted_channel="system",
        untrusted_channel="user",
    )
    route = ModelAccessRouter(
        adapter_registry=_Registry(
            {
                "selected-adapter": _descriptor(
                    **descriptor_values,
                    trusted_instruction_mapping=system_mapping,
                )
            }
        )
    ).resolve(request, resolver=resolver, profile=profile)
    assert route.trusted_instruction_mapping == system_mapping


def test_adapter_attestation_provenance_must_match_selected_adapter() -> None:
    profile = _profile(
        profile_id="profile.product_general",
        runtime="product",
        channel="product.chat",
        consumer="product.agent",
        caller_profile="profile.product_runtime",
        capability_provenance=CapabilityProvenance(
            source="adapter_attestation",
            source_ref="different-adapter",
        ),
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
                provider="openai",
                model="gpt-5.6-sol",
                transport_id="openai_api",
                execution_host_profile="profile.provider_openai",
                execution_boundary="provider_https",
                authentication_scheme="provider_credential_ref",
            )
        }
    )

    with pytest.raises(ValueError, match="selected adapter"):
        ModelAccessRouter(adapter_registry=registry).resolve(
            _request(), resolver=resolver, profile=profile
        )
