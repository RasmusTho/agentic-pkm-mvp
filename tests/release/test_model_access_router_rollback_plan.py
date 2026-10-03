from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.components.embeddings.legacy import EmbeddingIdentity
from app.release_channels.model_access_rollback import (
    ModelAccessRollbackError,
    PinnedRouteVerification,
    plan_model_access_rollback,
)
from llm_contract import (
    CapabilityProvenance,
    ModelAccessIntent,
    ModelAccessRoute,
    ModelCapabilities,
    ModelCapabilityRequirements,
    ModelResolutionRequest,
    ResolvedModelAccess,
    TrustedInstructionMapping,
)


NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)


def _request(
    requirements: ModelCapabilityRequirements,
    *,
    output_schema_ref: str | None = None,
    determinism_required: bool = False,
    capability_tier: str = "frontier",
    reasoning_effort: str = "high",
    independence: str = "none",
) -> ModelResolutionRequest:
    return ModelResolutionRequest(
        intent=ModelAccessIntent(
            capability_tier=capability_tier,
            reasoning_effort=reasoning_effort,
            determinism_required=determinism_required,
            output_schema_ref=output_schema_ref,
            independence=independence,
            fallback_requirement="fallback_forbidden",
            side_effect_class="none",
        ),
        role_profile="product.chat",
        resolution_group_id="product-chat",
        requirements=requirements,
    )


def _route(
    model: str,
    *,
    request: ModelResolutionRequest | None = None,
    structured_output: bool = True,
    native_tools: bool = True,
    system_prompt_channel: bool = True,
    deterministic_execution: bool = False,
    embedding_dimension: int | None = None,
    preflight_status: str = "passed",
) -> ModelAccessRoute:
    resolved = ResolvedModelAccess(
        request=request or _request(ModelCapabilityRequirements()),
        provider="openai",
        model=model,
        adapter_id="codex_cli",
        effective_identity=f"openai/{model}",
        capabilities=ModelCapabilities(
            structured_output=structured_output,
            native_tools=native_tools,
            system_prompt_channel=system_prompt_channel,
            deterministic_execution=deterministic_execution,
            embedding_dimension=embedding_dimension,
        ),
        credential_identity_ref="codex.subscription-session",
    )
    return ModelAccessRoute(
        **resolved.model_dump(),
        policy_profile="profile.product_general",
        transport_id="codex_cli",
        preflight_status=preflight_status,
        execution_host_profile="profile.ygg_macmini",
        execution_boundary="private_network_https",
        authentication_scheme="executor_path_authentication",
        caller_profile="profile.product_runtime",
        capability_provenance=CapabilityProvenance(
            source="policy_registry",
            source_ref="profile.product_general",
        ),
        trusted_instruction_mapping=TrustedInstructionMapping(
            mapping_ref="profile.instructions_v1",
            trusted_channel="developer_instructions",
            untrusted_channel="user",
        ),
    )


def _candidate(
    model: str,
    *,
    verified_minutes_ago: int,
    preflight_seconds_ago: int = 5,
    structured_output: bool = True,
    native_tools: bool = True,
    system_prompt_channel: bool = True,
    deterministic_execution: bool = False,
    embedding_dimension: int | None = None,
    pinned: bool = True,
    path_policy_ref: str = "path.ygg_vlan_primary",
    verified_request: ModelResolutionRequest | None = None,
    preflight_status: str = "passed",
) -> PinnedRouteVerification:
    return PinnedRouteVerification(
        route=_route(
            model,
            request=verified_request,
            structured_output=structured_output,
            native_tools=native_tools,
            system_prompt_channel=system_prompt_channel,
            deterministic_execution=deterministic_execution,
            embedding_dimension=embedding_dimension,
            preflight_status=preflight_status,
        ),
        path_policy_ref=path_policy_ref,
        verification_receipt_ref=f"receipt.{model}",
        verified_at=NOW - timedelta(minutes=verified_minutes_ago),
        preflight_at=NOW - timedelta(seconds=preflight_seconds_ago),
        pinned=pinned,
    )


def test_rollback_restores_last_pinned_capability_compatible_route() -> None:
    identity = EmbeddingIdentity(
        provider="ollama", model="nomic-embed-text", dim=768, normalize=True
    )
    current_request = _request(ModelCapabilityRequirements(native_tools=True))
    latest = _candidate("luna-current", verified_minutes_ago=1, verified_request=current_request)
    plan = plan_model_access_rollback(
        [
            _candidate("luna-older", verified_minutes_ago=10, verified_request=current_request),
            latest,
            _candidate(
                "not-pinned",
                verified_minutes_ago=0,
                pinned=False,
                verified_request=current_request,
            ),
        ],
        current_request=current_request,
        embedding_identity=identity,
        now=NOW,
    )

    assert plan.route.model_dump(exclude={"request"}) == latest.route.model_dump(
        exclude={"request"}
    )
    assert plan.route.request == _request(ModelCapabilityRequirements(native_tools=True))
    assert plan.path_policy_ref == latest.path_policy_ref
    assert plan.verification_receipt_ref == latest.verification_receipt_ref
    assert plan.embedding_identity is identity


def test_rollback_fails_closed_without_a_fresh_compatible_preflight() -> None:
    candidate = _candidate("stale-preflight", verified_minutes_ago=1, preflight_seconds_ago=31)

    with pytest.raises(ModelAccessRollbackError, match="no fresh"):
        plan_model_access_rollback(
            [candidate],
            current_request=candidate.route.request,
            embedding_identity=EmbeddingIdentity(
                provider="ollama", model="nomic-embed-text", dim=768
            ),
            now=NOW,
        )


def test_rollback_fails_closed_when_fresh_preflight_did_not_pass() -> None:
    candidate = _candidate(
        "preflight-not-run",
        verified_minutes_ago=1,
        preflight_status="not_run",
    )

    with pytest.raises(ModelAccessRollbackError, match="no fresh"):
        plan_model_access_rollback(
            [candidate],
            current_request=_request(ModelCapabilityRequirements()),
            embedding_identity=EmbeddingIdentity(
                provider="ollama", model="nomic-embed-text", dim=768
            ),
            now=NOW,
        )


def test_rollback_fails_closed_for_ambiguous_latest_candidates() -> None:
    candidates = [
        _candidate("latest-a", verified_minutes_ago=1),
        _candidate("latest-b", verified_minutes_ago=1),
    ]

    with pytest.raises(ModelAccessRollbackError, match="ambiguous"):
        plan_model_access_rollback(
            candidates,
            current_request=_request(ModelCapabilityRequirements()),
            embedding_identity=EmbeddingIdentity(
                provider="ollama", model="nomic-embed-text", dim=768
            ),
            now=NOW,
        )


def test_rollback_rejects_preflight_from_a_different_capability_intent() -> None:
    verified_request = _request(ModelCapabilityRequirements())
    current_request = _request(ModelCapabilityRequirements(), output_schema_ref="schema.reply.v1")
    candidate = _candidate(
        "preflighted-without-structured-output",
        verified_minutes_ago=1,
        verified_request=verified_request,
    )

    with pytest.raises(ModelAccessRollbackError, match="no fresh"):
        plan_model_access_rollback(
            [candidate],
            current_request=current_request,
            embedding_identity=EmbeddingIdentity(
                provider="ollama", model="nomic-embed-text", dim=768
            ),
            now=NOW,
        )


def test_rollback_keeps_a_preflight_bound_to_the_exact_current_request() -> None:
    current_request = _request(ModelCapabilityRequirements(), output_schema_ref="schema.reply.v1")
    candidate = _candidate(
        "structured-output-current",
        verified_minutes_ago=1,
        verified_request=current_request,
    )

    plan = plan_model_access_rollback(
        [candidate],
        current_request=current_request,
        embedding_identity=EmbeddingIdentity(provider="ollama", model="nomic-embed-text", dim=768),
        now=NOW,
    )

    assert plan.route.request == current_request
    assert plan.route.request.intent.output_schema_ref == "schema.reply.v1"


def test_rollback_rejects_a_request_requiring_a_distinct_effective_target() -> None:
    current_request = _request(
        ModelCapabilityRequirements(), independence="distinct_effective_target"
    )
    candidate = _candidate(
        "single-candidate",
        verified_minutes_ago=1,
        verified_request=current_request,
    )

    with pytest.raises(ModelAccessRollbackError, match="no fresh"):
        plan_model_access_rollback(
            [candidate],
            current_request=current_request,
            embedding_identity=EmbeddingIdentity(
                provider="ollama", model="nomic-embed-text", dim=768
            ),
            now=NOW,
        )


def test_rollback_rejects_a_route_verified_for_lower_capability_tier() -> None:
    candidate = _candidate(
        "economy-low",
        verified_minutes_ago=1,
        verified_request=_request(
            ModelCapabilityRequirements(),
            capability_tier="economy",
            reasoning_effort="high",
        ),
    )

    with pytest.raises(ModelAccessRollbackError, match="no fresh"):
        plan_model_access_rollback(
            [candidate],
            current_request=_request(ModelCapabilityRequirements()),
            embedding_identity=EmbeddingIdentity(
                provider="ollama", model="nomic-embed-text", dim=768
            ),
            now=NOW,
        )


def test_rollback_rejects_an_unverified_reasoning_effort() -> None:
    candidate = _candidate("verified-high-effort", verified_minutes_ago=1)

    with pytest.raises(ModelAccessRollbackError, match="no fresh"):
        plan_model_access_rollback(
            [candidate],
            current_request=_request(ModelCapabilityRequirements(), reasoning_effort="minimal"),
            embedding_identity=EmbeddingIdentity(
                provider="ollama", model="nomic-embed-text", dim=768
            ),
            now=NOW,
        )


def test_rollback_rejects_developer_mapping_for_literal_system_requirement() -> None:
    current_request = _request(ModelCapabilityRequirements(literal_system_role_required=True))
    candidate = _candidate("developer-channel", verified_minutes_ago=1)
    candidate = replace(
        candidate,
        route=candidate.route.model_copy(update={"request": current_request}),
    )

    with pytest.raises(ModelAccessRollbackError, match="no fresh"):
        plan_model_access_rollback(
            [candidate],
            current_request=current_request,
            embedding_identity=EmbeddingIdentity(
                provider="ollama", model="nomic-embed-text", dim=768
            ),
            now=NOW,
        )


@pytest.mark.parametrize(
    ("current_request", "route_options"),
    [
        (
            _request(ModelCapabilityRequirements(), output_schema_ref="schema.reply.v1"),
            {"structured_output": False},
        ),
        (
            _request(ModelCapabilityRequirements(native_tools=True)),
            {"native_tools": False},
        ),
        (
            _request(ModelCapabilityRequirements(system_prompt_channel=True)),
            {"system_prompt_channel": False},
        ),
        (
            _request(ModelCapabilityRequirements(), determinism_required=True),
            {"deterministic_execution": False},
        ),
        (
            _request(ModelCapabilityRequirements(embedding_dimension=768)),
            {"embedding_dimension": 1536},
        ),
    ],
)
def test_rollback_fails_closed_when_a_required_capability_is_missing(
    current_request: ModelResolutionRequest,
    route_options: dict[str, object],
) -> None:
    # Bypass the route model's construction validator to exercise the planner's
    # fail-closed guard against an inconsistent persisted candidate record.
    route = _route("incompatible", **route_options).model_copy(update={"request": current_request})
    candidate = PinnedRouteVerification(
        route=route,
        path_policy_ref="path.ygg_vlan_primary",
        verification_receipt_ref="receipt.incompatible",
        verified_at=NOW - timedelta(minutes=1),
        preflight_at=NOW - timedelta(seconds=5),
    )

    with pytest.raises(ModelAccessRollbackError, match="no fresh"):
        plan_model_access_rollback(
            [candidate],
            current_request=current_request,
            embedding_identity=EmbeddingIdentity(
                provider="ollama", model="nomic-embed-text", dim=768
            ),
            now=NOW,
        )


def test_prod_transition_requires_operator_acknowledged_release_plan() -> None:
    root = Path(__file__).resolve().parents[2]
    execute_skill = (root / ".codex/skills/execute-promotion/SKILL.md").read_text(encoding="utf-8")
    test_to_prod_skill = (root / ".codex/skills/promote-test-to-prod/SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "all operator acknowledgment checkboxes ticked" in execute_skill
    assert (
        "If the plan is incomplete or has un-ticked acknowledgment checkboxes, abort."
        in execute_skill
    )
    assert "operator reviews and ticks all checkboxes" in test_to_prod_skill
    assert "does not auto-proceed past the plan review gate" in test_to_prod_skill
