from __future__ import annotations

import json

from pydantic import ValidationError
import pytest

from app.builderops.delivery_orchestration_contracts import canonical_hash
from app.builderops.execution_routing import (
    AllocationObservation,
    ExecutionRouteRequest,
    ResolvedExecutionTarget,
    admit_phase2_canary,
    build_execution_routing_canary_receipt,
    create_execution_attempt,
    resolve_bounded_fast_route,
)
from app.builderops.execution_routing_receipts import (
    CanaryReceiptEvidenceError,
    append_attempt_intent,
    append_attempt_outcome,
    bind_canary_receipt_to_verification_request,
    record_acceptance_observation,
)
from app.builderops.store import SqliteBuilderOpsStore


HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
REPOSITORY = "RasmusTho/agentic-pkm-mvp"
VERIFICATION_RUN_ID = (
    f"vrun-{canonical_hash([REPOSITORY.lower(), 5328, 'verification'])[:16]}"
)


def _request(**overrides: object) -> ExecutionRouteRequest:
    values: dict[str, object] = {
        "request_id": "route-request-5183",
        "repository": REPOSITORY,
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
        "terra": "gpt-5.6-terra",
        "sol": "gpt-5.6-sol",
    }[capability]
    return ResolvedExecutionTarget(
        capability=capability,
        provider="openai",
        model=model,
        reasoning_effort="low",
        configuration_ref="docs/settings/models/providers.yaml#builder_execution.dev",
    )


def _durable_canary(
    tmp_path, *, issue_number: int = 5183, outcome: str = "started"
):
    request = _request(issue_number=issue_number)
    decision = admit_phase2_canary(
        request, opt_in=True, sample_index=1, sample_limit=1
    )
    attempt = create_execution_attempt(
        request=request,
        decision=decision,
        target=_target("luna"),
        attempt_number=1,
        mode="canary",
        outcome=outcome,
        observed_at="2026-08-29T15:00:01Z",
    )
    store = SqliteBuilderOpsStore(tmp_path / f"builderops-{issue_number}.sqlite3")
    store.initialize()
    chain = append_attempt_intent(store, request, decision, attempt)
    append_attempt_outcome(store, chain, request, decision, attempt)
    receipt = build_execution_routing_canary_receipt(
        request=request,
        decision=decision,
        attempts=(attempt,),
        accepted_delivery_verification="not_run",
    )
    return store, receipt, request, decision, attempt


def _verification_request(
    receipt: dict[str, object],
    *,
    run_id: str,
    repository: str = REPOSITORY,
    issue_number: int = 5183,
    pr_number: int = 5328,
    head_sha: str = "a" * 40,
) -> dict[str, object]:
    assert run_id == VERIFICATION_RUN_ID
    return bind_canary_receipt_to_verification_request(
        {
            "repository": repository,
            "pr_number": pr_number,
            "linked_issue": issue_number,
            "current_head_sha": head_sha,
            "stage": "verification",
            "idempotency_key": "0" * 64,
        },
        receipt,
    )


def test_canary_acceptance_consumer_records_verified_delivery_once(tmp_path) -> None:
    store, receipt, _request_value, _decision, _attempt = _durable_canary(tmp_path)
    verification = {
        "contract": "verification_receipt.v1",
        "verdict": "verified",
        "repository": REPOSITORY,
        "pr_number": 5328,
        "head_sha": "a" * 40,
        "run_id": VERIFICATION_RUN_ID,
    }
    verification_request = _verification_request(
        receipt, run_id=VERIFICATION_RUN_ID
    )

    first = record_acceptance_observation(
        store,
        receipt,
        verification,
        repository="RasmusTho/agentic-pkm-mvp",
        pr_number=5328,
        head_sha="a" * 40,
        governing_issue=5183,
        run_id=VERIFICATION_RUN_ID,
        verification_request=verification_request,
    )
    replay = record_acceptance_observation(
        store,
        receipt,
        verification,
        repository="RasmusTho/agentic-pkm-mvp",
        pr_number=5328,
        head_sha="a" * 40,
        governing_issue=5183,
        run_id=VERIFICATION_RUN_ID,
        verification_request=verification_request,
    )

    assert first == replay
    body = json.loads(first["receipt_body"])
    assert body["acceptance"]["status"] == "passed"
    assert body["acceptance"]["verification"]["verdict"] == "verified"
    assert body["acceptance"]["verification"]["head_sha"] == "a" * 40
    assert len(store.list_records("BuilderOpsReceipt")) == 3


def test_canary_acceptance_rejects_unbound_verified_delivery(tmp_path) -> None:
    store, receipt, _request_value, _decision, _attempt = _durable_canary(tmp_path)
    verification_request = _verification_request(
        receipt, run_id=VERIFICATION_RUN_ID
    )

    observation = record_acceptance_observation(
        store,
        receipt,
        {"verdict": "verified", "head_sha": "a" * 40},
        repository="RasmusTho/agentic-pkm-mvp",
        pr_number=5328,
        head_sha="a" * 40,
        governing_issue=5183,
        run_id=VERIFICATION_RUN_ID,
        verification_request=verification_request,
    )

    body = json.loads(observation["receipt_body"])
    assert body["acceptance"]["status"] == "not_accepted"
    assert body["acceptance"]["reason"] == "verification_identity_mismatch"


def test_canary_acceptance_is_not_accepted_without_verification(tmp_path) -> None:
    store, receipt, _request_value, _decision, _attempt = _durable_canary(tmp_path)
    verification_request = _verification_request(
        receipt, run_id=VERIFICATION_RUN_ID
    )

    observation = record_acceptance_observation(
        store,
        receipt,
        None,
        repository="RasmusTho/agentic-pkm-mvp",
        pr_number=5328,
        head_sha="a" * 40,
        governing_issue=5183,
        run_id=VERIFICATION_RUN_ID,
        verification_request=verification_request,
    )

    body = json.loads(observation["receipt_body"])
    assert body["acceptance"]["status"] == "not_accepted"
    assert body["acceptance"]["reason"] == "verification_not_reached"
    assert body["acceptance"]["verification"]["verdict"] is None


def test_canary_acceptance_rejects_stale_and_cross_issue_receipts(tmp_path) -> None:
    store, receipt, _request_value, _decision, _attempt = _durable_canary(tmp_path)
    verified = {"verdict": "verified", "head_sha": "a" * 40}
    stale_request = _verification_request(
        receipt, run_id=VERIFICATION_RUN_ID, head_sha="b" * 40
    )

    stale = record_acceptance_observation(
        store,
        receipt,
        verified,
        repository="RasmusTho/agentic-pkm-mvp",
        pr_number=5328,
        head_sha="b" * 40,
        governing_issue=5183,
        run_id=VERIFICATION_RUN_ID,
        verification_request=stale_request,
    )
    stale_body = json.loads(stale["receipt_body"])
    assert stale_body["acceptance"]["status"] == "not_accepted"
    assert stale_body["acceptance"]["reason"] == "verification_head_mismatch"

    cross_issue = dict(receipt)
    cross_issue["candidate"] = {
        "repository": REPOSITORY,
        "issue_number": 9999,
        "work_class": "bounded_fast",
    }
    with pytest.raises(CanaryReceiptEvidenceError, match="verification request"):
        record_acceptance_observation(
            store,
            cross_issue,
            verified,
            repository="RasmusTho/agentic-pkm-mvp",
            pr_number=5328,
            head_sha="a" * 40,
            governing_issue=5183,
            run_id=VERIFICATION_RUN_ID,
            verification_request=_verification_request(
                cross_issue, run_id=VERIFICATION_RUN_ID
            ),
        )


def test_acceptance_requires_delivery_eligible_final_canary_outcome(tmp_path) -> None:
    store, receipt, _request_value, _decision, _attempt = _durable_canary(
        tmp_path, outcome="failed"
    )
    verification_request = _verification_request(
        receipt, run_id=VERIFICATION_RUN_ID
    )
    observation = record_acceptance_observation(
        store,
        receipt,
        {
            "verdict": "verified",
            "repository": REPOSITORY,
            "pr_number": 5328,
            "head_sha": "a" * 40,
            "run_id": VERIFICATION_RUN_ID,
        },
        repository=REPOSITORY,
        pr_number=5328,
        head_sha="a" * 40,
        governing_issue=5183,
        run_id=VERIFICATION_RUN_ID,
        verification_request=verification_request,
    )
    body = json.loads(observation["receipt_body"])
    assert body["acceptance"]["status"] == "not_accepted"
    assert body["acceptance"]["reason"] == "canary_attempt_failed"


def test_acceptance_rejects_cross_repository_canary_identity(tmp_path) -> None:
    store, receipt, _request_value, _decision, _attempt = _durable_canary(tmp_path)
    verification_request = _verification_request(
        receipt, run_id=VERIFICATION_RUN_ID
    )
    with pytest.raises(CanaryReceiptEvidenceError, match="repository"):
        record_acceptance_observation(
            store,
            receipt,
            None,
            repository="someone/unrelated",
            pr_number=5328,
            head_sha="a" * 40,
            governing_issue=5183,
            run_id=VERIFICATION_RUN_ID,
            verification_request=verification_request,
        )


def test_acceptance_rejects_noncanonical_fallback_sequence(tmp_path) -> None:
    store, receipt, _request_value, _decision, _attempt = _durable_canary(tmp_path)
    noncanonical = dict(receipt)
    attempts = [dict(item) for item in receipt["attempts"]]  # type: ignore[index]
    attempts[0]["attempt_number"] = 2
    noncanonical["attempts"] = attempts
    with pytest.raises(CanaryReceiptEvidenceError, match="canonical order"):
        record_acceptance_observation(
            store,
            noncanonical,
            None,
            repository=REPOSITORY,
            pr_number=5328,
            head_sha="a" * 40,
            governing_issue=5183,
            run_id=VERIFICATION_RUN_ID,
            verification_request=_verification_request(
                noncanonical, run_id=VERIFICATION_RUN_ID
            ),
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


def test_phase2_canary_admission_is_explicit_bounded_and_fail_closed() -> None:
    request = _request()

    with pytest.raises(ValueError, match="explicit opt-in"):
        admit_phase2_canary(request, opt_in=False, sample_index=1, sample_limit=1)
    with pytest.raises(ValueError, match="one candidate"):
        admit_phase2_canary(request, opt_in=True, sample_index=2, sample_limit=2)
    with pytest.raises(ValueError, match="bounded sample"):
        admit_phase2_canary(request, opt_in=True, sample_index=2, sample_limit=1)
    with pytest.raises(ValueError, match="bounded_fast route refused"):
        admit_phase2_canary(
            _request(protected_surface=True),
            opt_in=True,
            sample_index=1,
            sample_limit=1,
        )

    decision = admit_phase2_canary(
        request, opt_in=True, sample_index=1, sample_limit=1
    )
    assert decision.selected_capability == "luna"
    assert decision.delivery_blocked is False


def test_route_decision_deserialization_cannot_fabricate_spark_authority() -> None:
    missing = resolve_bounded_fast_route(_request())
    fabricated_spark = missing.model_dump(mode="json")
    fabricated_spark.update(
        selected_capability="spark",
        transition_kind="none",
    )
    with pytest.raises(
        ValidationError,
        match="Spark selection requires a bound fresh bonus observation",
    ):
        type(missing).model_validate(fabricated_spark)

    coherent_forgery = missing.model_dump(mode="json")
    coherent_forgery.update(
        selected_capability="spark",
        transition_kind="none",
        transition_reason="fresh_bonus_available",
        allocation_observation_id="forged-observation",
        allocation_observation_hash="d" * 64,
    )
    coherent_forgery["decision_id"] = (
        "execution-route-decision:"
        + canonical_hash(
            {
                "request_hash": coherent_forgery["request_hash"],
                "selected_capability": "spark",
                "transition_kind": "none",
                "transition_reason": "fresh_bonus_available",
                "allocation_observation_id": "forged-observation",
                "allocation_observation_hash": "d" * 64,
            }
        )
    )
    forged_decision = type(missing).model_validate(coherent_forgery)
    with pytest.raises(ValueError, match="exactly replay from its bound request"):
        create_execution_attempt(
            request=_request(),
            decision=forged_decision,
            target=_target("spark"),
            attempt_number=1,
            mode="shadow",
            outcome="not_invoked",
            observed_at="2026-08-29T15:00:00Z",
            transition_reason="shadow_route_not_invoked",
        )

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
    for field in ("allocation_observation_id", "allocation_observation_hash"):
        unbound_spark = spark.model_dump(mode="json")
        unbound_spark[field] = None
        with pytest.raises(ValidationError):
            type(spark).model_validate(unbound_spark)

    fabricated_missing = spark.model_dump(mode="json")
    fabricated_missing.update(
        selected_capability="luna",
        transition_kind="capacity_fallback",
        transition_reason="allocation_observation_missing",
    )
    with pytest.raises(
        ValidationError,
        match="represented without an observation",
    ):
        type(spark).model_validate(fabricated_missing)


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
    request = _request(allocation_observation=observation)
    decision = resolve_bounded_fast_route(request)
    first = create_execution_attempt(
        request=request,
        decision=decision,
        target=_target("spark"),
        attempt_number=1,
        mode="canary",
        outcome="allocation_unavailable",
        observed_at="2026-08-29T15:00:01Z",
    )
    fallback = create_execution_attempt(
        request=request,
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
        mismatched_trigger = first.model_copy(update={field: "d" * 64})
        with pytest.raises(
            ValueError,
            match="semantic hashes must match the route decision",
        ):
            create_execution_attempt(
                request=request,
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
            request=request,
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
            request=request,
            decision=decision,
            target=_target("spark"),
            attempt_number=1,
            mode="shadow",
            outcome="not_invoked",
            observed_at="2026-08-29T15:00:01Z",
            transition_reason="misspelled_reason",  # type: ignore[arg-type]
        )


def test_phase2_canary_spark_fallback_is_one_shot_and_semantically_identical() -> None:
    observation = AllocationObservation(
        observation_id="spark-observation-phase2",
        capability="spark",
        state="bonus_available",
        observed_at="2026-08-29T14:55:00Z",
        valid_until="2026-08-29T15:05:00Z",
        source_kind="operator",
        source_ref="operator-observation:codex-spark-bonus",
    )
    request = _request(allocation_observation=observation)
    decision = admit_phase2_canary(
        request, opt_in=True, sample_index=1, sample_limit=1
    )
    spark_attempt = create_execution_attempt(
        request=request,
        decision=decision,
        target=_target("spark"),
        attempt_number=1,
        mode="canary",
        outcome="allocation_unavailable",
        observed_at="2026-08-29T15:00:01Z",
    )
    luna_fallback = create_execution_attempt(
        request=request,
        decision=decision,
        target=_target("luna"),
        attempt_number=2,
        mode="canary",
        outcome="succeeded",
        observed_at="2026-08-29T15:00:02Z",
        transition_kind="capacity_fallback",
        transition_reason="spark_allocation_unavailable_at_launch",
        triggering_attempt=spark_attempt,
    )
    receipt = build_execution_routing_canary_receipt(
        request=request,
        decision=decision,
        attempts=(spark_attempt, luna_fallback),
        accepted_delivery_verification="passed",
    )

    assert luna_fallback.context_pack_hash == spark_attempt.context_pack_hash
    assert luna_fallback.authority_hash == spark_attempt.authority_hash
    assert (
        luna_fallback.verification_profile_hash
        == spark_attempt.verification_profile_hash
    )
    assert receipt["schema_version"] == "builder_execution_routing_canary.v1"
    assert receipt["attempt_count"] == 2
    assert receipt["lifecycle_authority"] == "none"
    assert receipt["merge_authority"] == "none"
    assert "source_ref" not in str(receipt)

    with pytest.raises(ValueError, match="one bounded Spark/Luna fallback"):
        build_execution_routing_canary_receipt(
            request=request,
            decision=decision,
            attempts=(spark_attempt, luna_fallback, luna_fallback),
            accepted_delivery_verification="passed",
        )


def test_shadow_evidence_cannot_trigger_fallback_or_fake_escalation() -> None:
    request = _request()
    decision = resolve_bounded_fast_route(request)
    with pytest.raises(ValidationError, match="shadow attempts are non-invoked"):
        create_execution_attempt(
            request=request,
            decision=decision,
            target=_target("luna"),
            attempt_number=1,
            mode="shadow",
            outcome="allocation_unavailable",
            observed_at="2026-08-29T15:00:01Z",
            transition_reason="shadow_route_not_invoked",
        )

    first = create_execution_attempt(
        request=request,
        decision=decision,
        target=_target("luna"),
        attempt_number=1,
        mode="canary",
        outcome="failed",
        observed_at="2026-08-29T15:00:01Z",
    )
    with pytest.raises(ValueError, match="not authorized by the Phase 1 contract"):
        create_execution_attempt(
            request=request,
            decision=decision,
            target=_target("spark"),
            attempt_number=2,
            mode="canary",
            outcome="started",
            observed_at="2026-08-29T15:00:02Z",
            transition_kind="capability_escalation",
            transition_reason="capability_insufficient",
            triggering_attempt=first,
        )
