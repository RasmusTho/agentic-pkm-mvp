from __future__ import annotations

from pydantic import ValidationError
import pytest

from app.builderops.execution_routing import (
    AllocationObservation,
    ExecutionRouteRequest,
    ResolvedExecutionTarget,
    create_execution_attempt,
    resolve_bounded_fast_route,
)


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _request(**overrides: object) -> ExecutionRouteRequest:
    values: dict[str, object] = {
        "request_id": "route-request-5183",
        "issue_number": 5183,
        "work_class": "bounded_fast",
        "risk": "low",
        "ambiguity": "low",
        "protected_surface": False,
        "decision_at": "2026-08-29T15:00:00Z",
        "context_pack_hash": HASH_A,
        "authority_hash": HASH_B,
        "verification_profile_hash": HASH_C,
        "shadow_against_capability": "luna",
    }
    values.update(overrides)
    return ExecutionRouteRequest(**values)


def _target(capability: str) -> ResolvedExecutionTarget:
    model = {
        "spark": "gpt-5.3-codex-spark",
        "luna": "gpt-5.6-luna",
    }[capability]
    return ResolvedExecutionTarget(
        capability=capability,
        provider="openai",
        model=model,
        reasoning_effort="low",
        configuration_ref="docs/settings/models/providers.yaml#builder_execution.dev",
    )


def test_bounded_fast_resolver_is_provider_neutral_and_fail_closed() -> None:
    request = _request()
    decision = resolve_bounded_fast_route(request)

    assert decision.selected_capability == "luna"
    assert "provider" not in type(request).model_fields
    assert "model" not in type(request).model_fields
    assert "reasoning_effort" not in type(request).model_fields
    assert decision.context_pack_hash == request.context_pack_hash
    assert decision.verification_profile_hash == request.verification_profile_hash

    for forbidden in (
        {"work_class": "general_delivery"},
        {"risk": "high"},
        {"ambiguity": "high"},
        {"protected_surface": True},
    ):
        with pytest.raises(ValueError, match="bounded_fast route refused"):
            resolve_bounded_fast_route(_request(**forbidden))

    with pytest.raises(ValidationError):
        _request(provider="must-not-enter-policy")


def test_spark_requires_fresh_bonus_observation_otherwise_luna_fallback() -> None:
    fresh = AllocationObservation(
        observation_id="spark-observation-fresh",
        capability="spark",
        state="bonus_available",
        observed_at="2026-08-29T14:55:00Z",
        valid_until="2026-08-29T15:05:00Z",
        source_kind="operator",
        source_ref="operator-observation:codex-spark-bonus",
    )
    spark = resolve_bounded_fast_route(_request(allocation_observation=fresh))
    assert spark.selected_capability == "spark"
    assert spark.transition_kind == "none"
    assert spark.transition_reason == "fresh_bonus_available"

    unavailable = AllocationObservation(
        observation_id="spark-observation-unavailable",
        capability="spark",
        state="economically_unavailable",
        observed_at="2026-08-29T14:55:00Z",
        valid_until="2026-08-29T15:05:00Z",
        source_kind="provider",
        source_ref="provider-observation:spark-allocation",
    )
    unknown = unavailable.model_copy(
        update={
            "observation_id": "spark-observation-unknown",
            "state": "unknown",
        }
    )
    stale = fresh.model_copy(update={"valid_until": "2026-08-29T14:59:59Z"})
    cases = [
        (None, "allocation_observation_missing"),
        (unavailable, "allocation_economically_unavailable"),
        (unknown, "allocation_unknown"),
        (stale, "allocation_observation_stale"),
    ]
    for observation, reason in cases:
        decision = resolve_bounded_fast_route(
            _request(allocation_observation=observation)
        )
        assert decision.selected_capability == "luna"
        assert decision.transition_kind == "capacity_fallback"
        assert decision.transition_reason == reason
        assert decision.delivery_blocked is False


def test_fallback_preserves_semantic_hashes_and_changes_attempt_identity() -> None:
    observation = AllocationObservation(
        observation_id="spark-observation-fresh",
        capability="spark",
        state="bonus_available",
        observed_at="2026-08-29T14:55:00Z",
        valid_until="2026-08-29T15:05:00Z",
        source_kind="operator",
        source_ref="operator-observation:codex-spark-bonus",
    )
    decision = resolve_bounded_fast_route(
        _request(allocation_observation=observation)
    )
    first = create_execution_attempt(
        decision=decision,
        target=_target("spark"),
        attempt_number=1,
        mode="canary",
        outcome="allocation_unavailable",
        observed_at="2026-08-29T15:00:01Z",
    )
    fallback = create_execution_attempt(
        decision=decision,
        target=_target("luna"),
        attempt_number=2,
        mode="canary",
        outcome="started",
        observed_at="2026-08-29T15:00:02Z",
        transition_kind="capacity_fallback",
        transition_reason="spark_allocation_unavailable_at_launch",
        triggering_attempt=first,
    )

    assert first.attempt_id != fallback.attempt_id
    assert first.route_lineage_id == fallback.route_lineage_id
    assert first.context_pack_hash == fallback.context_pack_hash == HASH_A
    assert first.authority_hash == fallback.authority_hash == HASH_B
    assert first.verification_profile_hash == fallback.verification_profile_hash == HASH_C
    assert fallback.transition_kind == "capacity_fallback"
    assert fallback.actual_capability == "luna"
    assert fallback.triggering_attempt_id == first.attempt_id
    assert fallback.triggering_attempt_hash == first.content_hash

    for field in (
        "context_pack_hash",
        "authority_hash",
        "verification_profile_hash",
    ):
        mismatched_payload = first.model_dump(mode="json")
        mismatched_payload[field] = "d" * 64
        mismatched_trigger = type(first).model_validate(mismatched_payload)
        with pytest.raises(
            ValueError,
            match="semantic hashes must match the route decision",
        ):
            create_execution_attempt(
                decision=decision,
                target=_target("luna"),
                attempt_number=2,
                mode="canary",
                outcome="started",
                observed_at="2026-08-29T15:00:02Z",
                transition_kind="capacity_fallback",
                transition_reason="spark_allocation_unavailable_at_launch",
                triggering_attempt=mismatched_trigger,
            )

    with pytest.raises(ValueError, match="fallback target must be luna"):
        create_execution_attempt(
            decision=decision,
            target=_target("spark"),
            attempt_number=2,
            mode="canary",
            outcome="started",
            observed_at="2026-08-29T15:00:02Z",
            transition_kind="capacity_fallback",
            transition_reason="spark_allocation_unavailable_at_launch",
            triggering_attempt=first,
        )

    with pytest.raises(ValidationError):
        create_execution_attempt(
            decision=decision,
            target=_target("spark"),
            attempt_number=1,
            mode="shadow",
            outcome="not_invoked",
            observed_at="2026-08-29T15:00:01Z",
            transition_reason="misspelled_reason",  # type: ignore[arg-type]
        )
