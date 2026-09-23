from __future__ import annotations

from pydantic import ValidationError
import pytest

from llm_contract import (
    CapabilityProvenance,
    FallbackProvenance,
    ModelAccessReceipt,
    ModelAccessRoute,
    ModelAccessIntent,
    ModelCapabilities,
    ModelCapabilityRequirements,
    ModelResolutionRequest,
    ResolvedModelAccess,
    TrustedInstructionMapping,
    validate_resolved_group,
)


def _intent(**overrides: object) -> ModelAccessIntent:
    values: dict[str, object] = {
        "capability_tier": "frontier",
        "reasoning_effort": "high",
        "determinism_required": False,
        "output_schema_ref": "model-inquiry-response.v1",
        "independence": "distinct_effective_target",
        "fallback_requirement": "fallback_forbidden",
        "side_effect_class": "none",
    }
    values.update(overrides)
    return ModelAccessIntent(**values)


def _request(
    role_profile: str,
    *,
    independence: str = "distinct_effective_target",
    fallback_requirement: str = "fallback_forbidden",
) -> ModelResolutionRequest:
    return ModelResolutionRequest(
        intent=_intent(
            independence=independence,
            fallback_requirement=fallback_requirement,
        ),
        role_profile=role_profile,
        resolution_group_id="independent-review",
        requirements=ModelCapabilityRequirements(
            structured_output=True,
            system_prompt_channel=True,
        ),
    )


def _route(
    *,
    request: ModelResolutionRequest | None = None,
    **overrides: object,
) -> ModelAccessRoute:
    resolved = _resolved(
        request or _request("product.chat", independence="none"),
        provider="openai",
        model="gpt-5.6-sol",
        effective_identity="openai/gpt-5.6-sol",
    )
    values: dict[str, object] = {
        **resolved.model_dump(),
        "policy_profile": "profile.product_general",
        "transport_id": "openai_api",
        "catalog_snapshot_ref": "catalog.openai_public",
        "catalog_snapshot_hash": "sha256:" + "a" * 64,
        "preflight_status": "passed",
        "execution_host_profile": "profile.provider_openai",
        "execution_boundary": "provider_https",
        "authentication_scheme": "provider_credential_ref",
        "caller_profile": "profile.product_runtime",
        "capability_provenance": CapabilityProvenance(
            source="catalog_snapshot",
            source_ref="catalog.openai_public",
        ),
        "trusted_instruction_mapping": TrustedInstructionMapping(
            mapping_ref="profile.instructions_openai_v1",
            trusted_channel="system",
            untrusted_channel="user",
        ),
    }
    values.update(overrides)
    return ModelAccessRoute(**values)


def _resolved(
    request: ModelResolutionRequest,
    *,
    provider: str,
    model: str,
    effective_identity: str,
    capabilities: ModelCapabilities | None = None,
    degraded: bool = False,
    degradation_reason: str | None = None,
    fallback_provenance: FallbackProvenance | None = None,
) -> ResolvedModelAccess:
    return ResolvedModelAccess(
        request=request,
        provider=provider,
        model=model,
        adapter_id=f"{provider}-adapter",
        effective_identity=effective_identity,
        capabilities=capabilities
        or ModelCapabilities(
            structured_output=True,
            system_prompt_channel=True,
        ),
        credential_identity_ref=f"{provider}.api-key",
        degraded=degraded,
        degradation_reason=degradation_reason,
        fallback_provenance=fallback_provenance or FallbackProvenance(),
    )


def test_model_access_intent_is_provider_free_and_closed() -> None:
    intent = _intent()

    assert set(type(intent).model_fields) == {
        "capability_tier",
        "reasoning_effort",
        "determinism_required",
        "output_schema_ref",
        "independence",
        "fallback_requirement",
        "side_effect_class",
    }
    assert intent.capability_tier == "frontier"

    for forbidden in ("provider", "model", "credential", "endpoint", "adapter_id"):
        with pytest.raises(ValidationError):
            _intent(**{forbidden: "must-not-enter-neutral-intent"})

    with pytest.raises(ValidationError):
        intent.capability_tier = "economy"  # type: ignore[misc]


def test_resolved_access_validates_capabilities_and_visible_degradation() -> None:
    request = _request("review.fable")

    with pytest.raises(ValidationError, match="structured_output"):
        _resolved(
            request,
            provider="anthropic",
            model="claude-fable",
            effective_identity="anthropic:claude-fable",
            capabilities=ModelCapabilities(system_prompt_channel=True),
        )

    with pytest.raises(ValidationError, match="degradation_reason"):
        _resolved(
            request,
            provider="anthropic",
            model="claude-fable",
            effective_identity="anthropic:claude-fable",
            degraded=True,
        )

    with pytest.raises(ValidationError, match="degradation_reason"):
        _resolved(
            request,
            provider="anthropic",
            model="claude-fable",
            effective_identity="anthropic:claude-fable",
            degradation_reason="must not be present on a non-degraded result",
        )

    degraded = _resolved(
        request,
        provider="anthropic",
        model="claude-fable",
        effective_identity="anthropic:claude-fable",
        degraded=True,
        degradation_reason="runtime policy selected an allowed compatible identity",
    )
    assert degraded.degraded is True
    assert degraded.degradation_reason

    with pytest.raises(ValidationError):
        ResolvedModelAccess(
            **degraded.model_dump(),
            credential_value="must-not-enter-neutral-provenance",
        )


def test_resolved_fallback_obeys_declared_requirement_and_identity() -> None:
    fallback = FallbackProvenance(
        used=True,
        phase="preflight",
        reason_code="executor_unreachable",
        source_transport_id="codex_cli",
        selected_transport_id="openai_api",
        policy_authority="profile.product_general",
        source_effective_identity="codex/gpt-5.6-sol",
        selected_effective_identity="openai/gpt-5.6-sol",
    )
    target = {
        "provider": "openai",
        "model": "gpt-5.6-sol",
        "effective_identity": "openai/gpt-5.6-sol",
        "degraded": True,
        "degradation_reason": "preflight_fallback",
        "fallback_provenance": fallback,
    }

    with pytest.raises(ValidationError, match="human_decision_required"):
        _resolved(
            _request(
                "product.chat",
                independence="none",
                fallback_requirement="human_decision_required",
            ),
            **target,
        )
    with pytest.raises(ValidationError, match="human_decision_required"):
        _route(
            request=_request(
                "product.chat",
                independence="none",
                fallback_requirement="human_decision_required",
            ),
            degraded=True,
            degradation_reason="preflight_fallback",
            fallback_provenance=fallback,
        )

    with pytest.raises(ValidationError, match="fallback_same_identity"):
        _resolved(
            _request(
                "product.chat",
                independence="none",
                fallback_requirement="fallback_same_identity",
            ),
            **target,
        )
    with pytest.raises(ValidationError, match="fallback_same_identity"):
        _route(
            request=_request(
                "product.chat",
                independence="none",
                fallback_requirement="fallback_same_identity",
            ),
            degraded=True,
            degradation_reason="preflight_fallback",
            fallback_provenance=fallback,
        )

    same_identity = fallback.model_copy(
        update={
            "source_effective_identity": "openai/gpt-5.6-sol",
        }
    )
    same_identity_result = _resolved(
        _request(
            "product.chat",
            independence="none",
            fallback_requirement="fallback_same_identity",
        ),
        **{**target, "fallback_provenance": same_identity},
    )
    assert same_identity_result.fallback_provenance.source_effective_identity == (
        same_identity_result.fallback_provenance.selected_effective_identity
    )

    compatible_result = _resolved(
        _request(
            "product.chat",
            independence="none",
            fallback_requirement="fallback_compatible_identity",
        ),
        **target,
    )
    assert compatible_result.fallback_provenance == fallback


def test_group_resolution_enforces_distinct_effective_targets() -> None:
    fable_request = _request("review.fable")
    codex_request = _request("review.gpt_codex")
    fable = _resolved(
        fable_request,
        provider="shared",
        model="same-model",
        effective_identity="same-effective-identity",
    )
    codex = _resolved(
        codex_request,
        provider="shared",
        model="same-model",
        effective_identity="same-effective-identity",
    )
    adapter_calls: list[str] = []

    with pytest.raises(ValueError, match="distinct_effective_target"):
        validate_resolved_group(
            (fable_request, codex_request),
            (fable, codex),
        )

    assert adapter_calls == []

    distinct = codex.model_copy(
        update={
            "provider": "openai",
            "model": "gpt-sol",
            "effective_identity": "openai:gpt-sol",
        }
    )
    assert validate_resolved_group(
        (fable_request, codex_request),
        (fable, distinct),
    ) == (fable, distinct)


def test_route_contract_carries_transport_catalog_preflight_host_and_fallback_provenance() -> None:
    request = _request(
        "product.agent",
        independence="none",
        fallback_requirement="fallback_policy_selected",
    )
    route = _route(
        request=request,
        provider="ollama",
        model="llama3.1:8b",
        adapter_id="ollama-adapter",
        effective_identity="ollama/llama3.1:8b",
        degraded=True,
        degradation_reason="preflight_fallback",
        transport_id="ollama_http",
        catalog_snapshot_ref="catalog.ollama_local",
        catalog_snapshot_hash="sha256:" + "b" * 64,
        execution_host_profile="profile.macos_ollama",
        execution_boundary="private_tailnet_serve_https",
        authentication_scheme="tailscale_app_capability",
        caller_profile="profile.product_runtime",
        capability_provenance=CapabilityProvenance(
            source="catalog_snapshot",
            source_ref="catalog.ollama_local",
        ),
        fallback_provenance=FallbackProvenance(
            used=True,
            phase="preflight",
            reason_code="executor_unreachable",
            source_transport_id="codex_cli_tailscale",
            selected_transport_id="ollama_http",
            policy_authority="profile.product_general",
            source_effective_identity="openai/gpt-5.6-sol",
            selected_effective_identity="ollama/llama3.1:8b",
        ),
    )
    receipt = ModelAccessReceipt(route=route)

    assert route.transport_id == "ollama_http"
    assert route.catalog_snapshot_ref == "catalog.ollama_local"
    assert route.catalog_snapshot_hash == "sha256:" + "b" * 64
    assert route.preflight_status == "passed"
    assert route.execution_host_profile == "profile.macos_ollama"
    assert route.execution_boundary == "private_tailnet_serve_https"
    assert route.caller_profile == "profile.product_runtime"
    assert route.request.requirements.structured_output is True
    assert route.capabilities.structured_output is True
    assert route.requested_capabilities == request.requirements
    assert route.resolved_capabilities == route.capabilities
    assert route.trusted_instruction_mapping.untrusted_channel == "user"
    assert route.fallback_provenance.phase == "preflight"
    assert route.fallback_provenance.source_effective_identity == "openai/gpt-5.6-sol"
    assert route.fallback_provenance.selected_effective_identity == route.effective_identity
    assert route.fallback_provenance.policy_authority == route.policy_profile
    assert receipt.route.model == "llama3.1:8b"
    assert receipt.model_dump(mode="json")["route"]["transport_id"] == "ollama_http"

    with pytest.raises(ValidationError, match="fallback_forbidden"):
        _route(
            request=_request("model-inquiry", independence="none"),
            fallback_provenance=FallbackProvenance(
                used=True,
                phase="preflight",
                reason_code="executor_unreachable",
                source_transport_id="codex_cli",
                selected_transport_id="openai_api",
                policy_authority="profile.product_general",
                source_effective_identity="codex/gpt-5.6-sol",
                selected_effective_identity="openai/gpt-5.6-sol",
            ),
        )
    with pytest.raises(ValidationError, match="policy authority"):
        _route(
            request=_request(
                "product.chat",
                independence="none",
                fallback_requirement="fallback_policy_selected",
            ),
            degraded=True,
            degradation_reason="preflight_fallback",
            fallback_provenance=FallbackProvenance(
                used=True,
                phase="preflight",
                reason_code="cli_missing",
                source_transport_id="codex_cli",
                selected_transport_id="openai_api",
                policy_authority="profile.builder_inquiry",
                source_effective_identity="codex/gpt-5.6-sol",
                selected_effective_identity="openai/gpt-5.6-sol",
            ),
        )

    with pytest.raises(ValidationError, match="visibly degraded"):
        _route(
            request=request,
            provider="ollama",
            model="llama3.1:8b",
            adapter_id="ollama-adapter",
            effective_identity="ollama/llama3.1:8b",
            transport_id="ollama_http",
            fallback_provenance=FallbackProvenance(
                used=True,
                phase="preflight",
                reason_code="executor_unreachable",
                source_transport_id="codex_cli_tailscale",
                selected_transport_id="ollama_http",
                policy_authority="profile.product_general",
                source_effective_identity="openai/gpt-5.6-sol",
                selected_effective_identity="ollama/llama3.1:8b",
            ),
        )


def test_adapter_attestation_capability_provenance_uses_adapter_identifier() -> None:
    route = _route(
        capability_provenance=CapabilityProvenance(
            source="adapter_attestation",
            source_ref="openai-adapter",
        )
    )
    assert route.capability_provenance.source_ref == route.adapter_id

    with pytest.raises(ValidationError, match="selected adapter"):
        _route(
            capability_provenance=CapabilityProvenance(
                source="adapter_attestation",
                source_ref="another-adapter",
            )
        )


def test_route_provenance_rejects_secret_bearing_fields() -> None:
    route = _route()
    forbidden_fields = {
        "credential_value": "sk-test-not-a-secret",
        "endpoint_url": "https://host.invalid/private?token=not-a-secret",
        "prompt": "trusted instructions must not enter receipts",
        "raw_tailscale_identity": "100.64.0.7",
        "tailscale_capability": "tscap-test-not-a-secret",
        "cli_environment": {"CODEX_HOME": "/private/path"},
    }

    for field, value in forbidden_fields.items():
        with pytest.raises(ValidationError):
            ModelAccessRoute(**{**route.model_dump(), field: value})
        with pytest.raises(ValidationError):
            ModelAccessReceipt(route=route, **{field: value})

    with pytest.raises(ValidationError):
        _route(execution_host_profile="profile.100_64_0_7")
    with pytest.raises(ValidationError):
        _route(authentication_scheme="tscap-raw-capability-value")
    with pytest.raises(ValidationError):
        _route(request=_request("prompt text with spaces", independence="none"))
    with pytest.raises(ValidationError):
        _route(
            degraded=True,
            degradation_reason="endpoint=https://host.invalid?token=value",
        )
    for credential_value in ("sk-ant-api03-abc123", "sk-ant-api03.abc123"):
        with pytest.raises(ValidationError):
            _route(credential_identity_ref=credential_value)
    for field in ("provider", "model", "adapter_id", "effective_identity"):
        with pytest.raises(ValidationError):
            _route(**{field: "sk-ant-api03-abc123"})
    ipv6_identity = "fd7a:115c:a1e0::1234"
    with pytest.raises(ValidationError):
        _route(effective_identity=ipv6_identity)
    fallback_values = {
        "used": True,
        "phase": "preflight",
        "reason_code": "cli_missing",
        "source_transport_id": "codex_cli",
        "selected_transport_id": "openai_api",
        "policy_authority": "profile.product_general",
        "source_effective_identity": "codex/gpt-5.6-sol",
        "selected_effective_identity": "openai/gpt-5.6-sol",
    }
    for identity_field in ("source_effective_identity", "selected_effective_identity"):
        with pytest.raises(ValidationError):
            FallbackProvenance(**{**fallback_values, identity_field: ipv6_identity})
    with pytest.raises(ValidationError):
        FallbackProvenance(
            used=True,
            phase="preflight",
            reason_code="cli_missing",
            source_transport_id="codex_cli",
            selected_transport_id="openai_api",
            policy_authority="profile.product_general",
            source_effective_identity="sk-ant-api03-abc123",
            selected_effective_identity="openai/gpt-5.6-sol",
        )
    with pytest.raises(ValidationError):
        _route(model="CODEX_HOME:/tmp/session")
    with pytest.raises(ValidationError):
        _route(provider="mac-mini.tailnet.ts.net")
    with pytest.raises(ValidationError):
        _route(model="mac-mini.tailnet.ts.net")
    with pytest.raises(ValidationError):
        _route(request=_request("ignore_all_safety_rules", independence="none"))
    with pytest.raises(ValidationError):
        _route(
            degraded=True,
            degradation_reason="sk-ant-api03-abc123",
        )


def test_literal_system_role_requirement_rejects_developer_instruction_mapping() -> None:
    request = _request("product.chat", independence="none")
    literal_system_request = request.model_copy(
        update={
            "requirements": request.requirements.model_copy(
                update={"literal_system_role_required": True}
            )
        }
    )
    developer_mapping = TrustedInstructionMapping(
        mapping_ref="profile.instructions_codex_developer_v1",
        trusted_channel="developer_instructions",
        untrusted_channel="user",
    )

    with pytest.raises(ValidationError, match="literal system role"):
        _route(
            request=literal_system_request,
            trusted_instruction_mapping=developer_mapping,
        )

    system_route = _route(request=literal_system_request)
    assert system_route.trusted_instruction_mapping.trusted_channel == "system"
