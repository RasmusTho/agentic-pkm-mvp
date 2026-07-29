from __future__ import annotations

from pydantic import ValidationError
import pytest

from app.llm_contract import (
    ModelAccessIntent,
    ModelCapabilities,
    ModelCapabilityRequirements,
    ModelResolutionRequest,
    ResolvedModelAccess,
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
) -> ModelResolutionRequest:
    return ModelResolutionRequest(
        intent=_intent(independence=independence),
        role_profile=role_profile,
        resolution_group_id="independent-review",
        requirements=ModelCapabilityRequirements(
            structured_output=True,
            system_prompt_channel=True,
        ),
    )


def _resolved(
    request: ModelResolutionRequest,
    *,
    provider: str,
    model: str,
    effective_identity: str,
    capabilities: ModelCapabilities | None = None,
    degraded: bool = False,
    degradation_reason: str | None = None,
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
