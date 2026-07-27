from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.builderops.delivery_orchestration_contracts import (
    ActorIdentity,
    ApprovalEvidence,
    AuthoritySnapshot,
    CheckEvidence,
    ClosureEvidence,
    ContractRef,
    DeliveryBudget,
    DeliveryException,
    DeliveryInitiation,
    DeliveryPlan,
    DeliveryReceipt,
    DependencyWave,
    ExpectedAuthorityState,
    EffectOutcomeEvidence,
    IssueDeliveryProof,
    IssueScope,
    KnownDefectRef,
    MergeIdentity,
    PolicyProfile,
    Provenance,
    REDUCER_EFFECT_VERSION,
    RecoveryAuthorityReadback,
    RecoveryStep,
    ReducerEffect,
    ReducerEvent,
    ReviewFinding,
    ReviewResult,
    ScopeExclusion,
    SourceRef,
    StructuredWorkerResult,
    TcdMetrics,
    ValidationEvidence,
    canonical_hash,
    delivery_event_id,
    delivery_event_input_hash,
    delivery_effect_idempotency_key,
    delivery_effect_input_hash,
    delivery_initiation_approval_hash,
    parse_delivery_contract,
    validate_delivery_plan_evidence,
    validate_delivery_receipt_evidence,
    validate_reducer_effect_evidence,
    validate_reducer_event_evidence,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64
TS = "2026-07-27T10:00:00Z"


def _actor(actor_id: str = "owner:RasmusTho") -> ActorIdentity:
    return ActorIdentity(
        actor_type="human",
        actor_id=actor_id,
        authority_scope="rasmustho/agentic-pkm-mvp",
    )


def _source(source_id: str, content_hash: str = SHA_A) -> SourceRef:
    return SourceRef(
        source_type="github_issue",
        source_id=source_id,
        content_hash=content_hash,
    )


def _provenance(
    correlation_id: str,
    *,
    created_at: str = TS,
) -> Provenance:
    return Provenance(
        created_at=created_at,
        created_by=_actor("builder:codex-root-4165"),
        source_refs=(_source("rasmustho/agentic-pkm-mvp#4165"),),
        correlation_id=correlation_id,
    )


def _issue(number: int, content_hash: str) -> IssueScope:
    return IssueScope(
        repository="rasmustho/agentic-pkm-mvp",
        issue_number=number,
        authority_id=f"github:rasmustho/agentic-pkm-mvp/issues/{number}",
        contract_hash=content_hash,
    )


def _authority(
    issue: IssueScope,
    state: str = "open",
    labels: tuple[str, ...] = ("type:task",),
) -> AuthoritySnapshot:
    return AuthoritySnapshot(
        authority_type="github_issue",
        authority_id=issue.authority_id,
        content_hash=issue.contract_hash,
        observed_state=state,
        observed_labels=labels,
        observed_at=TS,
    )


def _policy() -> PolicyProfile:
    return PolicyProfile(
        profile_id="delivery-low-risk",
        profile_version="v1",
        profile_hash=SHA_B,
        minimum_review_confidence_basis_points=8_000,
        required_check_names=("Unit tests (not pg)",),
    )


def _budget() -> DeliveryBudget:
    return DeliveryBudget(
        max_parallel_workers=2,
        max_worker_starts=4,
        max_coordinator_turns=12,
        max_total_tokens=200_000,
        max_wall_time_seconds=7_200,
    )


def _initiation(issue: IssueScope) -> DeliveryInitiation:
    exclusions = (
        ScopeExclusion(
            scope_key="durable-carrier-selection",
            reason="Deferred to the explicit carrier governance gate.",
        ),
    )
    requested_scope = (issue,)
    policy_profile = _policy()
    budget = _budget()
    source_authorities = (_authority(issue),)
    provenance = _provenance("initiation-4165")
    approval_id = "approval-4165"
    approver = _actor()
    approval_source_refs = (
        _source("rasmustho/agentic-pkm-mvp#4165", SHA_C),
    )
    return DeliveryInitiation(
        initiation_id="init-4165",
        requested_scope=requested_scope,
        exclusions=exclusions,
        approval_evidence=ApprovalEvidence(
            approval_id=approval_id,
            approver=approver,
            approved_at=TS,
            approved_payload_hash=delivery_initiation_approval_hash(
                initiation_id="init-4165",
                requested_scope=requested_scope,
                exclusions=exclusions,
                policy_profile=policy_profile,
                budget=budget,
                source_authorities=source_authorities,
                provenance=provenance,
                approval_id=approval_id,
                approver=approver,
                approved_at=TS,
                approval_source_refs=approval_source_refs,
            ),
            source_refs=approval_source_refs,
        ),
        policy_profile=policy_profile,
        budget=budget,
        source_authorities=source_authorities,
        provenance=provenance,
    )


def _plan(issue: IssueScope, initiation: DeliveryInitiation) -> DeliveryPlan:
    return DeliveryPlan(
        plan_id="plan-4165",
        initiation_ref=ContractRef(
            schema_version=initiation.schema_version,
            contract_id=initiation.initiation_id,
            content_hash=initiation.content_hash,
        ),
        input_authorities=(_authority(issue),),
        final_scope=(issue,),
        exclusions=initiation.exclusions,
        dependency_waves=(DependencyWave(wave_index=0, issues=(issue,)),),
        expected_states=(
            ExpectedAuthorityState(
                issue=issue,
                issue_state="open",
                required_labels=("type:task",),
                forbidden_labels=("agent:blocked",),
                expected_contract_hash=issue.contract_hash,
            ),
        ),
        policy_profile=initiation.policy_profile,
        budget=initiation.budget,
        effect_allowlist=(
            "await_ci",
            "claim_issue",
            "close_issue",
            "launch_worker",
            "merge_pull_request",
            "record_delivery_receipt",
            "request_review",
        ),
        provenance=_provenance("plan-4165"),
    )


def _worker_result(
    issue: IssueScope,
    plan: DeliveryPlan,
) -> StructuredWorkerResult:
    return StructuredWorkerResult(
        result_id="worker-result-4165",
        run_id="run-4165",
        plan_ref=ContractRef(
            schema_version=plan.schema_version,
            contract_id=plan.plan_id,
            content_hash=plan.content_hash,
        ),
        issue=issue,
        status="completed",
        exact_head_sha=SHA_D,
        pull_request_number=4200,
        changed_files=("app/builderops/delivery_orchestration_contracts.py",),
        validations=(
            ValidationEvidence(
                name="focused-contract-tests",
                status="passed",
                evidence_ref="pytest:delivery-contracts",
                exact_head_sha=SHA_D,
            ),
        ),
        exceptions=(),
        summary="Defined and verified the delivery contract seam.",
        provenance=_provenance("worker-result-4165"),
    )


def _review_result(issue: IssueScope, plan: DeliveryPlan) -> ReviewResult:
    return ReviewResult(
        result_id="review-result-4165",
        run_id="run-4165",
        plan_ref=ContractRef(
            schema_version=plan.schema_version,
            contract_id=plan.plan_id,
            content_hash=plan.content_hash,
        ),
        policy_profile=plan.policy_profile,
        issue=issue,
        pull_request_number=4200,
        exact_head_sha=SHA_D,
        disposition="accept_with_risk",
        confidence_basis_points=9_500,
        findings=(
            ReviewFinding(
                finding_id="finding-p2-1",
                severity="P2",
                summary="Bounded follow-up remains outside this slice.",
                protected_risk=False,
                false_green=False,
                evidence_refs=("review:4200:finding-p2-1",),
            ),
        ),
        known_defect_refs=(
            "registry:rasmustho/agentic-pkm-mvp/issues/4300:"
            "KD-AAAAAAAAAAAA",
        ),
        provenance=_provenance("review-result-4165"),
    )


def _run_started_event(plan: DeliveryPlan) -> ReducerEvent:
    plan_ref = ContractRef(
        schema_version=plan.schema_version,
        contract_id=plan.plan_id,
        content_hash=plan.content_hash,
    )
    input_hash = delivery_event_input_hash(
        run_id="run-4165",
        plan_ref=plan_ref,
        sequence=0,
        event_type="run_started",
        subject_authority=None,
        effect_ref=None,
        result_ref=None,
        exception=None,
    )
    return ReducerEvent(
        event_id=delivery_event_id(input_hash),
        input_hash=input_hash,
        run_id="run-4165",
        plan_ref=plan_ref,
        sequence=0,
        event_type="run_started",
        subject_authority=None,
        effect_ref=None,
        result_ref=None,
        exception=None,
        provenance=_provenance("run-started-4165"),
    )


def _recovery_effect(
    issue: IssueScope,
    plan: DeliveryPlan,
) -> ReducerEffect:
    plan_ref = ContractRef(
        schema_version=plan.schema_version,
        contract_id=plan.plan_id,
        content_hash=plan.content_hash,
    )
    run_started_event = _run_started_event(plan)
    authorities = (_authority(issue),)
    expected_outcome_keys = (
        f"github:{issue.repository}/pulls/4200",
    )
    input_hash = delivery_effect_input_hash(
        run_id="run-4165",
        plan_ref=plan_ref,
        effect_class="merge_pull_request",
        issue=issue,
        pull_request_number=4200,
        exact_head_sha=SHA_D,
        expected_authorities=authorities,
        expected_outcome_keys=expected_outcome_keys,
    )
    idempotency_key = delivery_effect_idempotency_key(input_hash)
    return ReducerEffect(
        effect_id=idempotency_key,
        run_id="run-4165",
        plan_ref=plan_ref,
        causal_event=run_started_event,
        sequence=8,
        effect_class="merge_pull_request",
        issue=issue,
        pull_request_number=4200,
        exact_head_sha=SHA_D,
        expected_authorities=authorities,
        expected_outcome_keys=expected_outcome_keys,
        idempotency_key=idempotency_key,
        input_hash=input_hash,
        provenance=_provenance("effect-merge-4165"),
    )


def _receipt(
    issue: IssueScope,
    initiation: DeliveryInitiation,
    plan: DeliveryPlan,
    worker: StructuredWorkerResult,
    review: ReviewResult,
) -> DeliveryReceipt:
    recovery_effect = _recovery_effect(issue, plan)
    worker_ref = ContractRef(
        schema_version=worker.schema_version,
        contract_id=worker.result_id,
        content_hash=worker.content_hash,
    )
    review_ref = ContractRef(
        schema_version=review.schema_version,
        contract_id=review.result_id,
        content_hash=review.content_hash,
    )
    return DeliveryReceipt(
        receipt_id="delivery-receipt-4165",
        run_id="run-4165",
        initiation_ref=ContractRef(
            schema_version=initiation.schema_version,
            contract_id=initiation.initiation_id,
            content_hash=initiation.content_hash,
        ),
        plan_ref=ContractRef(
            schema_version=plan.schema_version,
            contract_id=plan.plan_id,
            content_hash=plan.content_hash,
        ),
        terminal_outcome="delivered",
        requested_scope=initiation.requested_scope,
        final_scope=plan.final_scope,
        issue_proofs=(
            IssueDeliveryProof(
                issue=issue,
                worker_result_ref=worker_ref,
                review_result_ref=review_ref,
                exact_head_sha=SHA_D,
                delivery_stage="closed",
                merge_identity=MergeIdentity(
                    repository=issue.repository,
                    authority_id=(
                        f"github:{issue.repository}/pulls/4200"
                    ),
                    pull_request_number=4200,
                    exact_head_sha=SHA_D,
                    base_sha=SHA_E,
                    merge_commit_sha=SHA_F,
                    merged_at=TS,
                    merged_by=_actor("github:RasmusTho"),
                ),
                check_evidence=(
                    CheckEvidence(
                        check_name="Unit tests (not pg)",
                        repository=issue.repository,
                        check_run_id="9001",
                        authority_id=(
                            f"github:{issue.repository}/check-runs/9001"
                        ),
                        pull_request_number=4200,
                        status="passed",
                        exact_head_sha=SHA_D,
                        completed_at=TS,
                        evidence_ref="github-check:9001",
                    ),
                ),
                review_disposition=review.disposition,
                known_defects=(
                    KnownDefectRef(
                        repository=issue.repository,
                        issue_number=4300,
                        defect_id="KD-AAAAAAAAAAAA",
                        severity="P2",
                        registry_ref=(
                            f"registry:{issue.repository}/issues/4300:"
                            "KD-AAAAAAAAAAAA"
                        ),
                        finding_hash=canonical_hash(review.findings[0]),
                    ),
                ),
                exceptions=(),
                closure=ClosureEvidence(
                    authority_id=issue.authority_id,
                    repository=issue.repository,
                    issue_number=issue.issue_number,
                    pull_request_number=4200,
                    exact_head_sha=SHA_D,
                    closed_at=TS,
                    closure_ref="github-issue-event:4165:closed",
                ),
            ),
        ),
        exceptions=(
            DeliveryException(
                kind="external_state_unknown",
                code="merge-timeout-reconciled",
                message="Merge call timed out and was reconciled from live authority.",
                retryable=False,
                evidence_refs=("github-pr:4200:merged",),
            ),
        ),
        recovery_history=(
            RecoveryStep(
                step_index=0,
                exception_kind="external_state_unknown",
                exception_code="merge-timeout-reconciled",
                exception_hash=canonical_hash(
                    DeliveryException(
                        kind="external_state_unknown",
                        code="merge-timeout-reconciled",
                        message=(
                            "Merge call timed out and was reconciled "
                            "from live authority."
                        ),
                        retryable=False,
                        evidence_refs=("github-pr:4200:merged",),
                    )
                ),
                effect_ref=ContractRef(
                    schema_version=recovery_effect.schema_version,
                    contract_id=recovery_effect.effect_id,
                    content_hash=recovery_effect.content_hash,
                ),
                effect_class="merge_pull_request",
                issue=issue,
                action="read_live_authority",
                authority_readbacks=(
                    RecoveryAuthorityReadback(
                        effect_idempotency_key=(
                            recovery_effect.idempotency_key
                        ),
                        authority_id=(
                            f"github:{issue.repository}/pulls/4200"
                        ),
                        issue=issue,
                        pull_request_number=4200,
                        exact_head_sha=SHA_D,
                        observed_state="merged",
                        observed_labels=("type:task",),
                        observed_at=TS,
                        evidence_ref="github-pr:4200:merged",
                    ),
                ),
                outcome_evidence=EffectOutcomeEvidence(
                    effect_class="merge_pull_request",
                    effect_idempotency_key=(
                        recovery_effect.idempotency_key
                    ),
                    outcome_state="merged",
                    outcome_keys=recovery_effect.expected_outcome_keys,
                    observed_at=TS,
                    evidence_refs=("github-pr:4200:merged",),
                ),
                outcome="reconciled",
                occurred_at=TS,
            ),
        ),
        tcd_metrics=TcdMetrics(
            coordinator_model_turns=3,
            estimated_coordinator_tokens=12_000,
            worker_starts=1,
            human_interventions=0,
            deterministic_transitions=9,
            model_decided_exceptions=0,
            ci_wait_cycles=2,
            ci_wall_time_seconds=310,
            review_rounds=1,
            repair_rounds=0,
            duplicate_claim_attempts=0,
            duplicate_worker_attempts=0,
            duplicate_pull_request_attempts=0,
            duplicate_merge_attempts=0,
            duplicate_closure_attempts=0,
            known_p2_dispositions=1,
            escaped_p0_p1_defects=0,
            false_green_events=0,
            lead_time_seconds=1_200,
        ),
        started_at=TS,
        completed_at="2026-07-27T10:20:00Z",
        provenance=_provenance(
            "receipt-4165",
            created_at="2026-07-27T10:20:00Z",
        ),
    )


def test_contracts_round_trip_canonically() -> None:
    issue = _issue(4165, SHA_A)
    case_alias_issue = IssueScope(
        repository="RasmusTho/Agentic-PKM-MVP",
        issue_number=issue.issue_number,
        authority_id=issue.authority_id,
        contract_hash=issue.contract_hash,
    )
    assert case_alias_issue == issue
    assert canonical_hash(case_alias_issue) == canonical_hash(issue)
    initiation = _initiation(issue)
    plan = _plan(issue, initiation)
    worker = _worker_result(issue, plan)
    review = _review_result(issue, plan)
    event_plan_ref = ContractRef(
        schema_version=plan.schema_version,
        contract_id=plan.plan_id,
        content_hash=plan.content_hash,
    )
    event_subject = _authority(issue)
    event_result_ref = ContractRef(
        schema_version=worker.schema_version,
        contract_id=worker.result_id,
        content_hash=worker.content_hash,
    )
    event_input_hash = delivery_event_input_hash(
        run_id="run-4165",
        plan_ref=event_plan_ref,
        sequence=1,
        event_type="worker_result_recorded",
        subject_authority=event_subject,
        effect_ref=None,
        result_ref=event_result_ref,
        exception=None,
    )
    event = ReducerEvent(
        event_id=delivery_event_id(event_input_hash),
        input_hash=event_input_hash,
        run_id="run-4165",
        plan_ref=event_plan_ref,
        sequence=1,
        event_type="worker_result_recorded",
        subject_authority=event_subject,
        effect_ref=None,
        result_ref=event_result_ref,
        exception=None,
        provenance=_provenance("event-1"),
    )
    effect_plan_ref = event.plan_ref
    run_started_event = _run_started_event(plan)
    effect_authorities = (_authority(issue),)
    effect_outcome_keys = ("check-name:Unit tests (not pg)",)
    effect_input_hash = delivery_effect_input_hash(
        run_id="run-4165",
        plan_ref=effect_plan_ref,
        effect_class="await_ci",
        issue=issue,
        pull_request_number=4200,
        exact_head_sha=SHA_D,
        expected_authorities=effect_authorities,
        expected_outcome_keys=effect_outcome_keys,
    )
    effect_idempotency_key = delivery_effect_idempotency_key(
        effect_input_hash
    )
    effect = ReducerEffect(
        effect_id=effect_idempotency_key,
        run_id="run-4165",
        plan_ref=effect_plan_ref,
        causal_event=run_started_event,
        sequence=2,
        effect_class="await_ci",
        issue=issue,
        pull_request_number=4200,
        exact_head_sha=SHA_D,
        expected_authorities=effect_authorities,
        expected_outcome_keys=effect_outcome_keys,
        idempotency_key=effect_idempotency_key,
        input_hash=effect_input_hash,
        provenance=_provenance("effect-1"),
    )
    receipt = _receipt(issue, initiation, plan, worker, review)

    contracts = (initiation, plan, event, effect, worker, review, receipt)
    assert {contract.contract_family for contract in contracts} == {
        "initiation",
        "plan",
        "reducer",
        "structured_result",
        "receipt",
    }

    for contract in contracts:
        canonical = contract.canonical_bytes()
        assert canonical == contract.canonical_json().encode("utf-8")
        assert b": " not in canonical
        assert b", " not in canonical
        assert len(contract.content_hash) == 64
        parsed = parse_delivery_contract(canonical)
        assert parsed == contract
        assert parsed.canonical_bytes() == canonical
        assert parsed.content_hash == contract.content_hash

        reordered = dict(reversed(list(json.loads(canonical).items())))
        assert parse_delivery_contract(reordered).canonical_bytes() == canonical

    assert validate_delivery_plan_evidence(plan, initiation=initiation) is plan
    assert validate_reducer_effect_evidence(effect, plan=plan) is effect
    assert (
        validate_reducer_event_evidence(
            event,
            plan=plan,
            worker_result=worker,
        )
        is event
    )

    effect_ref = ContractRef(
        schema_version=effect.schema_version,
        contract_id=effect.effect_id,
        content_hash=effect.content_hash,
    )
    effect_outcome = EffectOutcomeEvidence(
        effect_class=effect.effect_class,
        effect_idempotency_key=effect.idempotency_key,
        outcome_state="checks_passed",
        outcome_keys=effect.expected_outcome_keys,
        observed_at=TS,
        evidence_refs=("github-check:9001",),
    )
    effect_event_input_hash = delivery_event_input_hash(
        run_id=effect.run_id,
        plan_ref=effect.plan_ref,
        sequence=effect.sequence + 1,
        event_type="effect_succeeded",
        subject_authority=_authority(issue),
        effect_ref=effect_ref,
        result_ref=None,
        exception=None,
        effect_outcome=effect_outcome,
    )
    effect_event = ReducerEvent(
        event_id=delivery_event_id(effect_event_input_hash),
        input_hash=effect_event_input_hash,
        run_id=effect.run_id,
        plan_ref=effect.plan_ref,
        sequence=effect.sequence + 1,
        event_type="effect_succeeded",
        subject_authority=_authority(issue),
        effect_ref=effect_ref,
        result_ref=None,
        exception=None,
        effect_outcome=effect_outcome,
        provenance=_provenance("effect-event"),
    )
    assert (
        validate_reducer_event_evidence(
            effect_event,
            plan=plan,
            effect=effect,
        )
        is effect_event
    )
    wrong_outcome_payload = effect_event.model_dump(mode="json")
    wrong_outcome_payload["effect_outcome"]["outcome_state"] = "merged"
    wrong_outcome_hash = delivery_event_input_hash(
        run_id=effect_event.run_id,
        plan_ref=effect_event.plan_ref,
        sequence=effect_event.sequence,
        event_type=effect_event.event_type,
        subject_authority=effect_event.subject_authority,
        effect_ref=effect_event.effect_ref,
        result_ref=effect_event.result_ref,
        exception=effect_event.exception,
        effect_outcome=EffectOutcomeEvidence.model_validate_json(
            json.dumps(wrong_outcome_payload["effect_outcome"])
        ),
    )
    wrong_outcome_payload["input_hash"] = wrong_outcome_hash
    wrong_outcome_payload["event_id"] = delivery_event_id(
        wrong_outcome_hash
    )
    wrong_outcome_event = parse_delivery_contract(wrong_outcome_payload)
    assert isinstance(wrong_outcome_event, ReducerEvent)
    with pytest.raises(ValueError, match="typed post-effect outcome"):
        validate_reducer_event_evidence(
            wrong_outcome_event,
            plan=plan,
            effect=effect,
        )

    early_effect_event_hash = delivery_event_input_hash(
        run_id=effect.run_id,
        plan_ref=effect.plan_ref,
        sequence=effect.sequence,
        event_type="effect_succeeded",
        subject_authority=_authority(issue),
        effect_ref=effect_ref,
        result_ref=None,
        exception=None,
        effect_outcome=effect_outcome,
    )
    early_effect_event = effect_event.model_copy(
        update={
            "event_id": delivery_event_id(early_effect_event_hash),
            "input_hash": early_effect_event_hash,
            "sequence": effect.sequence,
        }
    )
    with pytest.raises(ValueError, match="post-effect outcome"):
        validate_reducer_event_evidence(
            early_effect_event,
            plan=plan,
            effect=effect,
        )

    stale_readback_effect_payload = effect.model_dump(mode="json")
    stale_readback_effect_payload["provenance"]["created_at"] = (
        "2026-07-27T10:00:01Z"
    )
    stale_readback_effect = parse_delivery_contract(
        stale_readback_effect_payload
    )
    assert isinstance(stale_readback_effect, ReducerEffect)
    stale_readback_ref = ContractRef(
        schema_version=stale_readback_effect.schema_version,
        contract_id=stale_readback_effect.effect_id,
        content_hash=stale_readback_effect.content_hash,
    )
    stale_readback_hash = delivery_event_input_hash(
        run_id=stale_readback_effect.run_id,
        plan_ref=stale_readback_effect.plan_ref,
        sequence=stale_readback_effect.sequence + 1,
        event_type="effect_succeeded",
        subject_authority=_authority(issue),
        effect_ref=stale_readback_ref,
        result_ref=None,
        exception=None,
        effect_outcome=effect_outcome.model_copy(
            update={
                "effect_idempotency_key": (
                    stale_readback_effect.idempotency_key
                )
            }
        ),
    )
    stale_readback_event = ReducerEvent(
        event_id=delivery_event_id(stale_readback_hash),
        input_hash=stale_readback_hash,
        run_id=stale_readback_effect.run_id,
        plan_ref=stale_readback_effect.plan_ref,
        sequence=stale_readback_effect.sequence + 1,
        event_type="effect_succeeded",
        subject_authority=_authority(issue),
        effect_ref=stale_readback_ref,
        result_ref=None,
        exception=None,
        effect_outcome=effect_outcome.model_copy(
            update={
                "effect_idempotency_key": (
                    stale_readback_effect.idempotency_key
                )
            }
        ),
        provenance=_provenance(
            "stale-effect-readback",
            created_at="2026-07-27T10:00:02Z",
        ),
    )
    with pytest.raises(ValueError, match="post-effect outcome"):
        validate_reducer_event_evidence(
            stale_readback_event,
            plan=plan,
            effect=stale_readback_effect,
        )

    invalid_event_identity = event.model_dump(mode="json")
    invalid_event_identity["event_id"] = "caller-selected-event"
    with pytest.raises(ValidationError, match="derive from semantic input"):
        parse_delivery_contract(invalid_event_identity)

    duplicate_key_json = initiation.canonical_json().replace(
        f'"schema_version":"{initiation.schema_version}"',
        (
            '"schema_version":"unsupported.delivery.v0",'
            f'"schema_version":"{initiation.schema_version}"'
        ),
        1,
    )
    with pytest.raises(ValueError, match="duplicate"):
        parse_delivery_contract(duplicate_key_json)

    invalid_event = event.model_dump(mode="json")
    invalid_event["event_type"] = "run_started"
    invalid_event["sequence"] = 0
    invalid_event["subject_authority"] = None
    with pytest.raises(ValidationError, match="result ref"):
        parse_delivery_contract(invalid_event)

    invalid_effect = effect.model_dump(mode="json")
    invalid_effect["pull_request_number"] = None
    invalid_effect["exact_head_sha"] = None
    with pytest.raises(ValidationError, match="pull request and exact head"):
        parse_delivery_contract(invalid_effect)

    invalid_effect = effect.model_dump(mode="json")
    invalid_effect["sequence"] += 1
    resequenced_effect = parse_delivery_contract(invalid_effect)
    assert isinstance(resequenced_effect, ReducerEffect)
    assert resequenced_effect.idempotency_key == effect.idempotency_key
    assert resequenced_effect.input_hash == effect.input_hash

    zero_sequence_effect = effect.model_dump(mode="json")
    zero_sequence_effect["sequence"] = 0
    with pytest.raises(ValidationError):
        parse_delivery_contract(zero_sequence_effect)

    invalid_effect = effect.model_dump(mode="json")
    invalid_effect["idempotency_key"] = "caller-selected-key"
    with pytest.raises(ValidationError, match="idempotency key"):
        parse_delivery_contract(invalid_effect)

    fresh_authority = _authority(issue).model_copy(
        update={"observed_at": "2026-07-27T10:00:01Z"}
    )
    fresh_input_hash = delivery_effect_input_hash(
        run_id=effect.run_id,
        plan_ref=effect.plan_ref,
        effect_class=effect.effect_class,
        issue=effect.issue,
        pull_request_number=effect.pull_request_number,
        exact_head_sha=effect.exact_head_sha,
        expected_authorities=(fresh_authority,),
        expected_outcome_keys=effect.expected_outcome_keys,
    )
    assert fresh_input_hash == effect.input_hash
    assert (
        delivery_effect_idempotency_key(fresh_input_hash)
        == effect.idempotency_key
    )
    fresh_effect_payload = effect.model_dump(mode="json")
    fresh_effect_payload["expected_authorities"] = [
        fresh_authority.model_dump(mode="json")
    ]
    fresh_effect_payload["provenance"]["created_at"] = (
        "2026-07-27T10:00:01Z"
    )
    fresh_effect = parse_delivery_contract(fresh_effect_payload)
    assert isinstance(fresh_effect, ReducerEffect)
    assert validate_reducer_effect_evidence(fresh_effect, plan=plan) is fresh_effect

    fresh_start_payload = run_started_event.model_dump(mode="json")
    fresh_start_payload["provenance"]["created_at"] = (
        "2026-07-27T10:00:01Z"
    )
    fresh_start_payload["provenance"]["correlation_id"] = (
        "fresh-run-start-provenance"
    )
    fresh_start = parse_delivery_contract(fresh_start_payload)
    assert isinstance(fresh_start, ReducerEvent)
    assert fresh_start.event_id == run_started_event.event_id
    reprovenanced_effect = effect.model_copy(
        update={
            "causal_event": fresh_start,
            "provenance": effect.provenance.model_copy(
                update={"created_at": "2026-07-27T10:00:01Z"}
            ),
        }
    )
    assert reprovenanced_effect.input_hash == effect.input_hash
    assert reprovenanced_effect.idempotency_key == effect.idempotency_key
    assert (
        validate_reducer_effect_evidence(reprovenanced_effect, plan=plan)
        is reprovenanced_effect
    )

    current_authority = _authority(
        issue,
        labels=("agent:in-progress", "type:task"),
    )
    causal_event_hash = delivery_event_input_hash(
        run_id=effect.run_id,
        plan_ref=effect.plan_ref,
        sequence=1,
        event_type="authority_changed",
        subject_authority=current_authority,
        effect_ref=None,
        result_ref=None,
        exception=None,
    )
    causal_event = ReducerEvent(
        event_id=delivery_event_id(causal_event_hash),
        input_hash=causal_event_hash,
        run_id=effect.run_id,
        plan_ref=effect.plan_ref,
        sequence=1,
        event_type="authority_changed",
        subject_authority=current_authority,
        effect_ref=None,
        result_ref=None,
        exception=None,
        provenance=_provenance("post-claim-authority"),
    )
    current_effect_hash = delivery_effect_input_hash(
        run_id=effect.run_id,
        plan_ref=effect.plan_ref,
        effect_class=effect.effect_class,
        issue=effect.issue,
        pull_request_number=effect.pull_request_number,
        exact_head_sha=effect.exact_head_sha,
        expected_authorities=(current_authority,),
        expected_outcome_keys=effect.expected_outcome_keys,
    )
    current_effect_key = delivery_effect_idempotency_key(
        current_effect_hash
    )
    current_effect = effect.model_copy(
        update={
            "effect_id": current_effect_key,
            "causal_event": causal_event,
            "sequence": 2,
            "expected_authorities": (current_authority,),
            "idempotency_key": current_effect_key,
            "input_hash": current_effect_hash,
        }
    )
    assert validate_reducer_effect_evidence(current_effect, plan=plan)
    stale_current_effect_payload = current_effect.model_dump(mode="json")
    stale_current_effect_payload["expected_authorities"] = [
        _authority(issue).model_dump(mode="json")
    ]
    with pytest.raises(ValidationError, match="current causal event"):
        parse_delivery_contract(stale_current_effect_payload)

    second_authority = _authority(_issue(4166, SHA_C))
    assert delivery_effect_input_hash(
        run_id=effect.run_id,
        plan_ref=effect.plan_ref,
        effect_class=effect.effect_class,
        issue=effect.issue,
        pull_request_number=effect.pull_request_number,
        exact_head_sha=effect.exact_head_sha,
        expected_authorities=(_authority(issue), second_authority),
        expected_outcome_keys=effect.expected_outcome_keys,
    ) == delivery_effect_input_hash(
        run_id=effect.run_id,
        plan_ref=effect.plan_ref,
        effect_class=effect.effect_class,
        issue=effect.issue,
        pull_request_number=effect.pull_request_number,
        exact_head_sha=effect.exact_head_sha,
        expected_authorities=(second_authority, _authority(issue)),
        expected_outcome_keys=effect.expected_outcome_keys,
    )
    reordered_authorities_payload = effect.model_dump(mode="json")
    reordered_authorities = (second_authority, _authority(issue))
    reordered_authorities_payload["expected_authorities"] = [
        item.model_dump(mode="json") for item in reordered_authorities
    ]
    reordered_authorities_payload["input_hash"] = delivery_effect_input_hash(
        run_id=effect.run_id,
        plan_ref=effect.plan_ref,
        effect_class=effect.effect_class,
        issue=effect.issue,
        pull_request_number=effect.pull_request_number,
        exact_head_sha=effect.exact_head_sha,
        expected_authorities=reordered_authorities,
        expected_outcome_keys=effect.expected_outcome_keys,
    )
    reordered_authorities_payload["idempotency_key"] = (
        delivery_effect_idempotency_key(
            reordered_authorities_payload["input_hash"]
        )
    )
    with pytest.raises(ValidationError, match="canonical sorted order"):
        parse_delivery_contract(reordered_authorities_payload)

    with pytest.raises(ValidationError, match="canonical sorted order"):
        _authority(issue, labels=("type:task", "agent:ready"))

    finding_payload = review.findings[0].model_dump(mode="json")
    finding_payload["evidence_refs"] = ("review:z", "review:a")
    with pytest.raises(ValidationError, match="canonical sorted order"):
        ReviewFinding.model_validate(finding_payload)

    foreign_event_payload = event.model_dump(mode="json")
    foreign_event_subject = _authority(_issue(9999, SHA_C))
    foreign_event_payload["subject_authority"] = (
        foreign_event_subject.model_dump(mode="json")
    )
    foreign_event_payload["input_hash"] = delivery_event_input_hash(
        run_id=event.run_id,
        plan_ref=event.plan_ref,
        sequence=event.sequence,
        event_type=event.event_type,
        subject_authority=foreign_event_subject,
        effect_ref=event.effect_ref,
        result_ref=event.result_ref,
        exception=event.exception,
    )
    foreign_event_payload["event_id"] = delivery_event_id(
        foreign_event_payload["input_hash"]
    )
    foreign_event = parse_delivery_contract(foreign_event_payload)
    assert isinstance(foreign_event, ReducerEvent)
    with pytest.raises(ValueError, match="subject contradicts"):
        validate_reducer_event_evidence(
            foreign_event,
            plan=plan,
            worker_result=worker,
        )

    foreign_worker_payload = worker.model_dump(mode="json")
    foreign_worker_payload["issue"] = _issue(9999, SHA_C).model_dump(mode="json")
    foreign_worker = parse_delivery_contract(foreign_worker_payload)
    assert isinstance(foreign_worker, StructuredWorkerResult)
    foreign_event_subject = _authority(foreign_worker.issue)
    foreign_result_ref = ContractRef(
        schema_version=foreign_worker.schema_version,
        contract_id=foreign_worker.result_id,
        content_hash=foreign_worker.content_hash,
    )
    foreign_event_input_hash = delivery_event_input_hash(
        run_id=foreign_worker.run_id,
        plan_ref=foreign_worker.plan_ref,
        sequence=3,
        event_type="worker_result_recorded",
        subject_authority=foreign_event_subject,
        effect_ref=None,
        result_ref=foreign_result_ref,
        exception=None,
    )
    foreign_result_event = ReducerEvent(
        event_id=delivery_event_id(foreign_event_input_hash),
        input_hash=foreign_event_input_hash,
        run_id=foreign_worker.run_id,
        plan_ref=foreign_worker.plan_ref,
        sequence=3,
        event_type="worker_result_recorded",
        subject_authority=foreign_event_subject,
        effect_ref=None,
        result_ref=foreign_result_ref,
        exception=None,
        provenance=_provenance("event-foreign-result"),
    )
    with pytest.raises(ValueError, match="outside exact plan scope"):
        validate_reducer_event_evidence(
            foreign_result_event,
            plan=plan,
            worker_result=foreign_worker,
        )

    stale_effect_payload = effect.model_dump(mode="json")
    stale_authority = _authority(issue, "closed")
    stale_effect_payload["expected_authorities"] = [
        stale_authority.model_dump(mode="json")
    ]
    stale_effect_payload["input_hash"] = delivery_effect_input_hash(
        run_id=effect.run_id,
        plan_ref=effect.plan_ref,
        effect_class=effect.effect_class,
        issue=effect.issue,
        pull_request_number=effect.pull_request_number,
        exact_head_sha=effect.exact_head_sha,
        expected_authorities=(stale_authority,),
        expected_outcome_keys=effect.expected_outcome_keys,
    )
    stale_effect_payload["idempotency_key"] = delivery_effect_idempotency_key(
        stale_effect_payload["input_hash"]
    )
    stale_effect_payload["effect_id"] = stale_effect_payload[
        "idempotency_key"
    ]
    stale_effect = parse_delivery_contract(stale_effect_payload)
    assert isinstance(stale_effect, ReducerEffect)
    with pytest.raises(ValueError, match="expected live authority"):
        validate_reducer_effect_evidence(stale_effect, plan=plan)

    missing_label_authority = _authority(issue, labels=())
    missing_label_effect_payload = effect.model_dump(mode="json")
    missing_label_effect_payload["expected_authorities"] = [
        missing_label_authority.model_dump(mode="json")
    ]
    missing_label_effect_payload["input_hash"] = delivery_effect_input_hash(
        run_id=effect.run_id,
        plan_ref=effect.plan_ref,
        effect_class=effect.effect_class,
        issue=effect.issue,
        pull_request_number=effect.pull_request_number,
        exact_head_sha=effect.exact_head_sha,
        expected_authorities=(missing_label_authority,),
        expected_outcome_keys=effect.expected_outcome_keys,
    )
    missing_label_effect_payload["idempotency_key"] = (
        delivery_effect_idempotency_key(
            missing_label_effect_payload["input_hash"]
        )
    )
    missing_label_effect_payload["effect_id"] = (
        missing_label_effect_payload["idempotency_key"]
    )
    missing_label_effect = parse_delivery_contract(
        missing_label_effect_payload
    )
    assert isinstance(missing_label_effect, ReducerEffect)
    with pytest.raises(ValueError, match="expected live authority"):
        validate_reducer_effect_evidence(missing_label_effect, plan=plan)

    missing_label_event_payload = event.model_dump(mode="json")
    missing_label_event_payload["subject_authority"] = (
        missing_label_authority.model_dump(mode="json")
    )
    missing_label_event_payload["input_hash"] = delivery_event_input_hash(
        run_id=event.run_id,
        plan_ref=event.plan_ref,
        sequence=event.sequence,
        event_type=event.event_type,
        subject_authority=missing_label_authority,
        effect_ref=event.effect_ref,
        result_ref=event.result_ref,
        exception=event.exception,
    )
    missing_label_event_payload["event_id"] = delivery_event_id(
        missing_label_event_payload["input_hash"]
    )
    missing_label_event = parse_delivery_contract(missing_label_event_payload)
    assert isinstance(missing_label_event, ReducerEvent)
    with pytest.raises(ValueError, match="subject contradicts"):
        validate_reducer_event_evidence(
            missing_label_event,
            plan=plan,
            worker_result=worker,
        )

    label_change_subject = _authority(
        issue,
        labels=("agent:ready", "type:task"),
    )
    label_change_input_hash = delivery_event_input_hash(
        run_id="run-4165",
        plan_ref=effect_plan_ref,
        sequence=3,
        event_type="authority_changed",
        subject_authority=label_change_subject,
        effect_ref=None,
        result_ref=None,
        exception=None,
    )
    label_change_event = ReducerEvent(
        event_id=delivery_event_id(label_change_input_hash),
        input_hash=label_change_input_hash,
        run_id="run-4165",
        plan_ref=effect_plan_ref,
        sequence=3,
        event_type="authority_changed",
        subject_authority=label_change_subject,
        effect_ref=None,
        result_ref=None,
        exception=None,
        provenance=_provenance("event-label-change"),
    )
    assert (
        validate_reducer_event_evidence(label_change_event, plan=plan)
        is label_change_event
    )

    invalid_timestamp = initiation.model_dump(mode="json")
    invalid_timestamp["provenance"]["created_at"] = "2026-99-99T99:99:99Z"
    with pytest.raises(ValidationError, match="real UTC calendar"):
        parse_delivery_contract(invalid_timestamp)


def test_initiation_is_evidence_not_execution_authority() -> None:
    issue = _issue(4165, SHA_A)
    initiation = _initiation(issue)

    assert initiation.requested_scope == (issue,)
    assert initiation.approval_evidence.immutable is True
    assert initiation.approval_evidence.effect_authority is False
    assert initiation.source_authorities[0].authority_id == issue.authority_id
    assert "effect_allowlist" not in DeliveryInitiation.model_fields
    assert "execution_authority" not in DeliveryInitiation.model_fields

    with pytest.raises(ValidationError):
        initiation.initiation_id = "mutated"  # type: ignore[misc]

    payload = initiation.model_dump(mode="json")
    payload["effect_allowlist"] = ["merge_pull_request"]
    with pytest.raises(ValidationError):
        parse_delivery_contract(payload)

    payload = initiation.model_dump(mode="json")
    payload["approval_evidence"]["effect_authority"] = True
    with pytest.raises(ValidationError):
        parse_delivery_contract(payload)

    payload = initiation.model_dump(mode="json")
    payload["budget"]["max_coordinator_turns"] += 1
    with pytest.raises(ValidationError, match="exact canonical initiation payload"):
        parse_delivery_contract(payload)

    payload = initiation.model_dump(mode="json")
    payload["provenance"]["correlation_id"] = "unapproved-provenance"
    with pytest.raises(ValidationError, match="exact canonical initiation payload"):
        parse_delivery_contract(payload)

    payload = initiation.model_dump(mode="json")
    payload["approval_evidence"]["approval_id"] = "substituted-approval"
    with pytest.raises(ValidationError, match="exact canonical initiation payload"):
        parse_delivery_contract(payload)

    payload = initiation.model_dump(mode="json")
    late_approval = "2026-07-27T10:00:01Z"
    payload["approval_evidence"]["approved_at"] = late_approval
    payload["approval_evidence"]["approved_payload_hash"] = (
        delivery_initiation_approval_hash(
            initiation_id=initiation.initiation_id,
            requested_scope=initiation.requested_scope,
            exclusions=initiation.exclusions,
            policy_profile=initiation.policy_profile,
            budget=initiation.budget,
            source_authorities=initiation.source_authorities,
            provenance=initiation.provenance,
            approval_id=initiation.approval_evidence.approval_id,
            approver=initiation.approval_evidence.approver,
            approved_at=late_approval,
            approval_source_refs=initiation.approval_evidence.source_refs,
        )
    )
    with pytest.raises(ValidationError, match="approval must precede"):
        parse_delivery_contract(payload)


def test_plan_binds_scope_and_expected_authority() -> None:
    issue = _issue(4165, SHA_A)
    initiation = _initiation(issue)
    plan = _plan(issue, initiation)

    assert plan.initiation_ref.content_hash == initiation.content_hash
    assert plan.input_authorities == (_authority(issue),)
    assert plan.final_scope == (issue,)
    assert plan.dependency_waves[0].issues == plan.final_scope
    assert plan.expected_states[0].expected_contract_hash == issue.contract_hash
    assert plan.effect_allowlist == (
        "await_ci",
        "claim_issue",
        "close_issue",
        "launch_worker",
        "merge_pull_request",
        "record_delivery_receipt",
        "request_review",
    )
    assert validate_delivery_plan_evidence(plan, initiation=initiation) is plan

    early_plan = plan.model_copy(
        update={
            "provenance": plan.provenance.model_copy(
                update={"created_at": "2026-07-27T09:59:59Z"}
            )
        }
    )
    with pytest.raises(ValueError, match="follow initiation"):
        validate_delivery_plan_evidence(early_plan, initiation=initiation)

    payload = plan.model_dump(mode="json")
    payload["effect_allowlist"] = list(reversed(payload["effect_allowlist"]))
    with pytest.raises(ValidationError, match="canonical sorted order"):
        parse_delivery_contract(payload)

    payload = plan.model_dump(mode="json")
    payload["input_authorities"] = []
    with pytest.raises(ValidationError, match="input authorities"):
        parse_delivery_contract(payload)

    payload = plan.model_dump(mode="json")
    payload["input_authorities"][0]["observed_labels"] = []
    with pytest.raises(ValidationError, match="expected state or labels"):
        parse_delivery_contract(payload)

    payload = plan.model_dump(mode="json")
    payload["dependency_waves"][0]["issues"] = []
    with pytest.raises(ValidationError, match="waves"):
        parse_delivery_contract(payload)

    second_issue = _issue(4166, SHA_C)
    payload = plan.model_dump(mode="json")
    payload["budget"]["max_parallel_workers"] = 1
    payload["final_scope"].append(second_issue.model_dump(mode="json"))
    payload["input_authorities"].append(
        _authority(second_issue).model_dump(mode="json")
    )
    payload["dependency_waves"][0]["issues"].append(
        second_issue.model_dump(mode="json")
    )
    payload["expected_states"].append(
        ExpectedAuthorityState(
            issue=second_issue,
            issue_state="open",
            required_labels=("type:task",),
            forbidden_labels=("agent:blocked",),
            expected_contract_hash=second_issue.contract_hash,
        ).model_dump(mode="json")
    )
    with pytest.raises(ValidationError, match="max_parallel_workers"):
        parse_delivery_contract(payload)

    payload = plan.model_dump(mode="json")
    substituted_issue = _issue(4165, SHA_C)
    payload["dependency_waves"][0]["issues"][0] = substituted_issue.model_dump(
        mode="json"
    )
    payload["expected_states"][0]["issue"] = substituted_issue.model_dump(mode="json")
    payload["expected_states"][0]["expected_contract_hash"] = SHA_C
    with pytest.raises(ValidationError, match="exact final-scope authority"):
        parse_delivery_contract(payload)

    payload = plan.model_dump(mode="json")
    foreign_issue = _issue(4166, SHA_C)
    payload["input_authorities"] = [
        _authority(foreign_issue).model_dump(mode="json")
    ]
    payload["final_scope"] = [foreign_issue.model_dump(mode="json")]
    payload["dependency_waves"][0]["issues"] = [
        foreign_issue.model_dump(mode="json")
    ]
    payload["expected_states"][0]["issue"] = foreign_issue.model_dump(mode="json")
    payload["expected_states"][0]["expected_contract_hash"] = SHA_C
    foreign_plan = parse_delivery_contract(payload)
    assert isinstance(foreign_plan, DeliveryPlan)
    with pytest.raises(ValueError, match="approved scope"):
        validate_delivery_plan_evidence(foreign_plan, initiation=initiation)

    expanded_issue = _issue(4166, SHA_C)
    expanded_scope = (issue, expanded_issue)
    expanded_authorities = (_authority(issue), _authority(expanded_issue))
    expanded_approval_hash = delivery_initiation_approval_hash(
        initiation_id=initiation.initiation_id,
        requested_scope=expanded_scope,
        exclusions=initiation.exclusions,
        policy_profile=initiation.policy_profile,
        budget=initiation.budget,
        source_authorities=expanded_authorities,
        provenance=initiation.provenance,
        approval_id=initiation.approval_evidence.approval_id,
        approver=initiation.approval_evidence.approver,
        approved_at=initiation.approval_evidence.approved_at,
        approval_source_refs=initiation.approval_evidence.source_refs,
    )
    expanded_initiation = initiation.model_copy(
        update={
            "requested_scope": expanded_scope,
            "source_authorities": expanded_authorities,
            "approval_evidence": initiation.approval_evidence.model_copy(
                update={"approved_payload_hash": expanded_approval_hash}
            ),
        }
    )
    narrowed_plan = plan.model_copy(
        update={
            "initiation_ref": ContractRef(
                schema_version=expanded_initiation.schema_version,
                contract_id=expanded_initiation.initiation_id,
                content_hash=expanded_initiation.content_hash,
            )
        }
    )
    with pytest.raises(ValueError, match="explain every omitted"):
        validate_delivery_plan_evidence(
            narrowed_plan,
            initiation=expanded_initiation,
        )

    contradictory_plan = plan.model_copy(
        update={
            "exclusions": plan.exclusions
            + (
                ScopeExclusion(
                    scope_key="rasmustho/agentic-pkm-mvp#4165",
                    reason="Contradicts the exact final scope.",
                    omitted_issue=issue,
                ),
            )
        }
    )
    with pytest.raises(ValueError, match="must be disjoint"):
        validate_delivery_plan_evidence(
            contradictory_plan,
            initiation=initiation,
        )

    with pytest.raises(
        ValidationError,
        match="canonical omitted-Issue identity",
    ):
        ScopeExclusion(
            scope_key="rasmustho/agentic-pkm-mvp#9999",
            reason="Uses a noncanonical identity.",
            omitted_issue=expanded_issue,
        )


def test_receipt_preserves_delivery_and_tcd_evidence() -> None:
    issue = _issue(4165, SHA_A)
    initiation = _initiation(issue)
    plan = _plan(issue, initiation)
    worker = _worker_result(issue, plan)
    review = _review_result(issue, plan)
    recovery_effect = _recovery_effect(issue, plan)
    receipt = _receipt(issue, initiation, plan, worker, review)

    proof = receipt.issue_proofs[0]
    assert receipt.initiation_ref.content_hash == initiation.content_hash
    assert receipt.plan_ref.content_hash == plan.content_hash
    assert proof.worker_result_ref.content_hash == worker.content_hash
    assert proof.review_result_ref.content_hash == review.content_hash
    assert proof.merge_identity is not None
    assert proof.merge_identity.exact_head_sha == proof.exact_head_sha
    assert proof.merge_identity.merge_commit_sha == SHA_F
    assert proof.review_disposition == "accept_with_risk"
    assert proof.known_defects[0].severity == "P2"
    assert receipt.exceptions[0].kind == "external_state_unknown"
    assert receipt.recovery_history[0].outcome == "reconciled"
    assert receipt.tcd_metrics.deterministic_transitions == 9
    assert receipt.tcd_metrics.human_interventions == 0
    assert (
        validate_delivery_receipt_evidence(
            receipt,
            initiation=initiation,
            plan=plan,
            worker_results=(worker,),
            review_results=(review,),
            reducer_effects=(recovery_effect,),
        )
        is receipt
    )

    payload = receipt.model_dump(mode="json")
    payload["issue_proofs"][0]["merge_identity"]["exact_head_sha"] = SHA_C
    with pytest.raises(ValidationError, match="exact head"):
        parse_delivery_contract(payload)

    payload = receipt.model_dump(mode="json")
    payload["issue_proofs"][0]["closure"]["exact_head_sha"] = SHA_C
    with pytest.raises(ValidationError, match="closure evidence"):
        parse_delivery_contract(payload)

    payload = receipt.model_dump(mode="json")
    payload["issue_proofs"][0]["closure"]["repository"] = "other/repository"
    with pytest.raises(ValidationError, match="proof repository"):
        parse_delivery_contract(payload)

    payload = receipt.model_dump(mode="json")
    payload["issue_proofs"][0]["merge_identity"]["merged_at"] = (
        "2026-07-27T10:10:00Z"
    )
    payload["issue_proofs"][0]["closure"]["closed_at"] = (
        "2026-07-27T09:00:00Z"
    )
    with pytest.raises(ValidationError, match="lifecycle chronology"):
        parse_delivery_contract(payload)

    payload = receipt.model_dump(mode="json")
    payload["issue_proofs"][0]["merge_identity"]["merged_at"] = (
        "2026-07-27T10:10:00Z"
    )
    payload["issue_proofs"][0]["closure"]["closed_at"] = (
        "2026-07-27T10:11:00Z"
    )
    payload["recovery_history"][0]["occurred_at"] = (
        "2026-07-27T10:05:00Z"
    )
    with pytest.raises(ValidationError, match="bind observed merge"):
        parse_delivery_contract(payload)

    payload = receipt.model_dump(mode="json")
    payload["issue_proofs"][0]["merge_identity"] = None
    with pytest.raises(ValidationError, match="requires merge and closure"):
        parse_delivery_contract(payload)

    for occurred_at in (
        "2026-07-27T09:59:59Z",
        "2026-07-27T10:20:01Z",
    ):
        payload = receipt.model_dump(mode="json")
        payload["recovery_history"][0]["occurred_at"] = occurred_at
        payload["recovery_history"][0]["authority_readbacks"][0][
            "observed_at"
        ] = occurred_at
        payload["recovery_history"][0]["outcome_evidence"][
            "observed_at"
        ] = occurred_at
        with pytest.raises(ValidationError, match="lifecycle chronology"):
            parse_delivery_contract(payload)

    payload = receipt.model_dump(mode="json")
    payload["provenance"]["created_at"] = "2026-07-27T10:19:59Z"
    with pytest.raises(ValidationError, match="terminal completion"):
        parse_delivery_contract(payload)

    payload = receipt.model_dump(mode="json")
    payload["tcd_metrics"]["lead_time_seconds"] = 1_199
    with pytest.raises(ValidationError, match="lead time"):
        parse_delivery_contract(payload)

    second_recovery_exception = DeliveryException(
        kind="external_state_unknown",
        code="closure-timeout-reconciled",
        message="Closure call timed out and was reconciled.",
        retryable=False,
        evidence_refs=("github-issue:4165:closed",),
    )
    payload = receipt.model_dump(mode="json")
    payload["exceptions"].append(
        second_recovery_exception.model_dump(mode="json")
    )
    payload["recovery_history"][0]["occurred_at"] = (
        "2026-07-27T10:10:00Z"
    )
    payload["recovery_history"].append(
        RecoveryStep(
            step_index=1,
            exception_kind=second_recovery_exception.kind,
            exception_code=second_recovery_exception.code,
            exception_hash=canonical_hash(second_recovery_exception),
            effect_ref=ContractRef(
                schema_version=REDUCER_EFFECT_VERSION,
                contract_id="effect-close-4165",
                content_hash=SHA_B,
            ),
            effect_class="close_issue",
            issue=issue,
            action="read_live_closure_authority",
            authority_readbacks=(
                RecoveryAuthorityReadback(
                    effect_idempotency_key=(
                        "builderops.delivery-effect.v1:" + SHA_B
                    ),
                    authority_id=issue.authority_id,
                    issue=issue,
                    pull_request_number=4200,
                    exact_head_sha=SHA_D,
                    observed_state="closed",
                    observed_labels=("type:task",),
                    observed_at="2026-07-27T10:05:00Z",
                    evidence_ref="github-issue:4165:closed",
                ),
            ),
            outcome_evidence=EffectOutcomeEvidence(
                effect_class="close_issue",
                effect_idempotency_key=(
                    "builderops.delivery-effect.v1:" + SHA_B
                ),
                outcome_state="closed",
                outcome_keys=(f"{issue.authority_id}#closed",),
                observed_at="2026-07-27T10:05:00Z",
                evidence_refs=("github-issue:4165:closed",),
            ),
            outcome="reconciled",
            occurred_at="2026-07-27T10:05:00Z",
        ).model_dump(mode="json")
    )
    with pytest.raises(ValidationError, match="monotonic"):
        parse_delivery_contract(payload)

    payload = receipt.model_dump(mode="json")
    payload["issue_proofs"][0]["check_evidence"] = []
    with pytest.raises(ValidationError, match="accepted exact-head proof"):
        parse_delivery_contract(payload)

    headless_worker_payload = worker.model_dump(mode="json")
    headless_worker_payload["validations"][0]["exact_head_sha"] = None
    with pytest.raises(ValidationError, match="exact result head"):
        parse_delivery_contract(headless_worker_payload)

    with pytest.raises(ValidationError):
        CheckEvidence(
            check_name="Unit tests (not pg)",
            repository=issue.repository,
            check_run_id="invalid-sha",
            authority_id=(
                f"github:{issue.repository}/check-runs/invalid-sha"
            ),
            pull_request_number=4200,
            status="passed",
            exact_head_sha="a" * 41,
            completed_at=TS,
            evidence_ref="github-check:invalid-sha",
        )

    payload = receipt.model_dump(mode="json")
    payload["issue_proofs"][0]["check_evidence"][0]["check_name"] = (
        "unrelated-advisory-check"
    )
    substituted_check_receipt = parse_delivery_contract(payload)
    assert isinstance(substituted_check_receipt, DeliveryReceipt)
    with pytest.raises(ValueError, match="required checks"):
        validate_delivery_receipt_evidence(
            substituted_check_receipt,
            initiation=initiation,
            plan=plan,
            worker_results=(worker,),
            review_results=(review,),
            reducer_effects=(recovery_effect,),
        )

    payload = receipt.model_dump(mode="json")
    payload["issue_proofs"][0]["check_evidence"][0][
        "pull_request_number"
    ] = 9999
    wrong_pr_check_receipt = parse_delivery_contract(payload)
    assert isinstance(wrong_pr_check_receipt, DeliveryReceipt)
    with pytest.raises(ValueError, match="exact PR"):
        validate_delivery_receipt_evidence(
            wrong_pr_check_receipt,
            initiation=initiation,
            plan=plan,
            worker_results=(worker,),
            review_results=(review,),
            reducer_effects=(recovery_effect,),
        )

    payload = receipt.model_dump(mode="json")
    payload["issue_proofs"][0]["check_evidence"][0][
        "authority_id"
    ] = "arbitrary:unresolved"
    with pytest.raises(ValidationError, match="check authority ID"):
        parse_delivery_contract(payload)

    payload = receipt.model_dump(mode="json")
    payload["issue_proofs"][0]["closure"][
        "authority_id"
    ] = "arbitrary:issue-authority"
    with pytest.raises(ValidationError, match="issue authority"):
        parse_delivery_contract(payload)

    payload = receipt.model_dump(mode="json")
    payload["issue_proofs"][0]["merge_identity"][
        "authority_id"
    ] = "arbitrary:pr-authority"
    with pytest.raises(ValidationError, match="merge authority ID"):
        parse_delivery_contract(payload)

    payload = receipt.model_dump(mode="json")
    payload["issue_proofs"][0]["known_defects"][0][
        "repository"
    ] = "otherorg/other-repo"
    payload["issue_proofs"][0]["known_defects"][0]["registry_ref"] = (
        "registry:otherorg/other-repo/issues/4300:KD-AAAAAAAAAAAA"
    )
    with pytest.raises(ValidationError, match="proof repository"):
        parse_delivery_contract(payload)

    payload = receipt.model_dump(mode="json")
    payload["recovery_history"][0]["authority_readbacks"][0][
        "authority_id"
    ] = "github:rasmustho/agentic-pkm-mvp/pulls/9999"
    with pytest.raises(ValidationError, match="bind observed merge"):
        parse_delivery_contract(payload)

    payload = receipt.model_dump(mode="json")
    payload["recovery_history"][0]["authority_readbacks"][0][
        "effect_idempotency_key"
    ] = "builderops.delivery-effect.v1:" + SHA_C
    wrong_effect_readback_receipt = parse_delivery_contract(payload)
    assert isinstance(wrong_effect_readback_receipt, DeliveryReceipt)
    with pytest.raises(ValueError, match="exact effect"):
        validate_delivery_receipt_evidence(
            wrong_effect_readback_receipt,
            initiation=initiation,
            plan=plan,
            worker_results=(worker,),
            review_results=(review,),
            reducer_effects=(recovery_effect,),
        )

    payload = receipt.model_dump(mode="json")
    payload["recovery_history"][0]["outcome_evidence"][
        "outcome_keys"
    ] = ["github:rasmustho/agentic-pkm-mvp/pulls/9999"]
    wrong_outcome_coverage_receipt = parse_delivery_contract(payload)
    assert isinstance(wrong_outcome_coverage_receipt, DeliveryReceipt)
    with pytest.raises(ValueError, match="exactly cover"):
        validate_delivery_receipt_evidence(
            wrong_outcome_coverage_receipt,
            initiation=initiation,
            plan=plan,
            worker_results=(worker,),
            review_results=(review,),
            reducer_effects=(recovery_effect,),
        )

    with pytest.raises(ValueError, match="IDs must be unique"):
        validate_delivery_receipt_evidence(
            receipt,
            initiation=initiation,
            plan=plan,
            worker_results=(worker,),
            review_results=(review,),
            reducer_effects=(recovery_effect, recovery_effect),
        )

    unordered_exception_a = DeliveryException(
        kind="execution_failed",
        code="a-exception",
        message="First exception.",
        retryable=False,
        evidence_refs=("evidence:a",),
    )
    unordered_exception_z = DeliveryException(
        kind="execution_failed",
        code="z-exception",
        message="Second exception.",
        retryable=False,
        evidence_refs=("evidence:z",),
    )
    payload = receipt.model_dump(mode="json")
    payload["issue_proofs"][0]["exceptions"] = [
        unordered_exception_z.model_dump(mode="json"),
        unordered_exception_a.model_dump(mode="json"),
    ]
    with pytest.raises(ValidationError, match="canonical sorted order"):
        parse_delivery_contract(payload)

    payload = receipt.model_dump(mode="json")
    payload["issue_proofs"][0]["check_evidence"][0]["completed_at"] = (
        "2026-07-27T10:00:01Z"
    )
    late_check_receipt = parse_delivery_contract(payload)
    assert isinstance(late_check_receipt, DeliveryReceipt)
    with pytest.raises(ValueError, match="precede review"):
        validate_delivery_receipt_evidence(
            late_check_receipt,
            initiation=initiation,
            plan=plan,
            worker_results=(worker,),
            review_results=(review,),
            reducer_effects=(recovery_effect,),
        )

    payload = receipt.model_dump(mode="json")
    payload["issue_proofs"][0]["check_evidence"][0]["completed_at"] = (
        "2026-07-27T10:05:00Z"
    )
    payload["issue_proofs"][0]["merge_identity"]["merged_at"] = (
        "2026-07-27T10:10:00Z"
    )
    payload["issue_proofs"][0]["closure"]["closed_at"] = (
        "2026-07-27T10:11:00Z"
    )
    payload["recovery_history"][0]["authority_readbacks"][0][
        "observed_at"
    ] = "2026-07-27T10:10:00Z"
    payload["recovery_history"][0]["occurred_at"] = (
        "2026-07-27T10:10:00Z"
    )
    post_review_check_receipt = parse_delivery_contract(payload)
    assert isinstance(post_review_check_receipt, DeliveryReceipt)
    with pytest.raises(ValueError, match="precede review"):
        validate_delivery_receipt_evidence(
            post_review_check_receipt,
            initiation=initiation,
            plan=plan,
            worker_results=(worker,),
            review_results=(review,),
            reducer_effects=(recovery_effect,),
        )

    payload = receipt.model_dump(mode="json")
    payload["recovery_history"][0]["effect_ref"]["contract_id"] = (
        "foreign-effect"
    )
    payload["recovery_history"][0]["effect_ref"]["content_hash"] = SHA_C
    foreign_effect_receipt = parse_delivery_contract(payload)
    assert isinstance(foreign_effect_receipt, DeliveryReceipt)
    with pytest.raises(ValueError, match="effect ref does not resolve"):
        validate_delivery_receipt_evidence(
            foreign_effect_receipt,
            initiation=initiation,
            plan=plan,
            worker_results=(worker,),
            review_results=(review,),
            reducer_effects=(recovery_effect,),
        )

    payload = receipt.model_dump(mode="json")
    payload["tcd_metrics"]["worker_starts"] = 0
    payload["tcd_metrics"]["review_rounds"] = 0
    payload["tcd_metrics"]["ci_wait_cycles"] = 0
    payload["tcd_metrics"]["deterministic_transitions"] = 0
    contradictory_tcd_receipt = parse_delivery_contract(payload)
    assert isinstance(contradictory_tcd_receipt, DeliveryReceipt)
    with pytest.raises(ValueError, match="TCD counters"):
        validate_delivery_receipt_evidence(
            contradictory_tcd_receipt,
            initiation=initiation,
            plan=plan,
            worker_results=(worker,),
            review_results=(review,),
            reducer_effects=(recovery_effect,),
        )

    payload = receipt.model_dump(mode="json")
    payload["recovery_history"][0]["effect_class"] = "close_issue"
    with pytest.raises(ValidationError, match="typed effect outcome"):
        parse_delivery_contract(payload)

    payload = receipt.model_dump(mode="json")
    payload["recovery_history"][0]["authority_readbacks"][0][
        "authority_id"
    ] = "github:pull-request:9999"
    with pytest.raises(ValidationError, match="bind observed merge"):
        parse_delivery_contract(payload)

    payload = receipt.model_dump(mode="json")
    payload["recovery_history"][0]["authority_readbacks"][0][
        "observed_at"
    ] = "2026-07-27T10:00:01Z"
    with pytest.raises(ValidationError, match="must not follow"):
        parse_delivery_contract(payload)

    payload = receipt.model_dump(mode="json")
    payload["recovery_history"][0]["exception_hash"] = SHA_C
    with pytest.raises(ValidationError, match="typed receipt exceptions"):
        parse_delivery_contract(payload)

    late_worker_payload = worker.model_dump(mode="json")
    late_worker_payload["provenance"]["created_at"] = (
        "2026-07-27T10:21:00Z"
    )
    late_worker = parse_delivery_contract(late_worker_payload)
    assert isinstance(late_worker, StructuredWorkerResult)
    late_review_payload = review.model_dump(mode="json")
    late_review_payload["provenance"]["created_at"] = (
        "2026-07-27T10:22:00Z"
    )
    late_review = parse_delivery_contract(late_review_payload)
    assert isinstance(late_review, ReviewResult)
    late_receipt = _receipt(
        issue,
        initiation,
        plan,
        late_worker,
        late_review,
    )
    with pytest.raises(ValueError, match="worker evidence"):
        validate_delivery_receipt_evidence(
            late_receipt,
            initiation=initiation,
            plan=plan,
            worker_results=(late_worker,),
            review_results=(late_review,),
            reducer_effects=(recovery_effect,),
        )

    closure_exception = DeliveryException(
        kind="execution_failed",
        code="closure-failed-after-merge",
        message="The issue closure effect failed after merge was observed.",
        retryable=False,
        evidence_refs=("github-issue:4165:still-open",),
    )
    partial_payload = receipt.model_dump(mode="json")
    partial_payload["terminal_outcome"] = "partially_delivered"
    partial_payload["exceptions"] = [
        closure_exception.model_dump(mode="json")
    ]
    partial_payload["recovery_history"] = []
    partial_payload["issue_proofs"][0]["delivery_stage"] = "merged"
    partial_payload["issue_proofs"][0]["closure"] = None
    partial_payload["issue_proofs"][0]["exceptions"] = [
        closure_exception.model_dump(mode="json")
    ]
    partial_receipt = parse_delivery_contract(partial_payload)
    assert isinstance(partial_receipt, DeliveryReceipt)
    assert (
        validate_delivery_receipt_evidence(
            partial_receipt,
            initiation=initiation,
            plan=plan,
            worker_results=(worker,),
            review_results=(review,),
            reducer_effects=(),
        )
        is partial_receipt
    )

    payload = receipt.model_dump(mode="json")
    payload["recovery_history"] = []
    with pytest.raises(ValidationError, match="reconciled recovery"):
        parse_delivery_contract(payload)

    payload = receipt.model_dump(mode="json")
    payload["recovery_history"][0]["exception_kind"] = "execution_failed"
    with pytest.raises(ValidationError, match="typed receipt exceptions"):
        parse_delivery_contract(payload)

    payload = review.model_dump(mode="json")
    payload["confidence_basis_points"] = 0
    with pytest.raises(ValidationError, match="low-confidence"):
        parse_delivery_contract(payload)

    payload = review.model_dump(mode="json")
    payload["known_defect_refs"] = []
    with pytest.raises(ValidationError, match="known-defect refs"):
        parse_delivery_contract(payload)

    payload = receipt.model_dump(mode="json")
    payload["issue_proofs"][0]["known_defects"][0]["finding_hash"] = SHA_C
    unbound_defect_receipt = parse_delivery_contract(payload)
    assert isinstance(unbound_defect_receipt, DeliveryReceipt)
    with pytest.raises(ValueError, match="P2 evidence"):
        validate_delivery_receipt_evidence(
            unbound_defect_receipt,
            initiation=initiation,
            plan=plan,
            worker_results=(worker,),
            review_results=(review,),
            reducer_effects=(recovery_effect,),
        )

    payload = receipt.model_dump(mode="json")
    payload["issue_proofs"][0]["known_defects"][0]["issue_number"] = 9999
    with pytest.raises(ValidationError, match="registry ref"):
        parse_delivery_contract(payload)

    p3_review_payload = review.model_dump(mode="json")
    p3_review_payload.update(
        {
            "result_id": "review-result-p3",
            "findings": [
                ReviewFinding(
                    finding_id="finding-p3-1",
                    severity="P3",
                    summary="Informational advice does not require defect intake.",
                    protected_risk=False,
                    false_green=False,
                    evidence_refs=("review:4200:finding-p3-1",),
                ).model_dump(mode="json")
            ],
            "known_defect_refs": [],
        }
    )
    p3_review = parse_delivery_contract(p3_review_payload)
    assert isinstance(p3_review, ReviewResult)
    p3_receipt_payload = receipt.model_dump(mode="json")
    p3_receipt_payload["issue_proofs"][0]["review_result_ref"] = (
        ContractRef(
            schema_version=p3_review.schema_version,
            contract_id=p3_review.result_id,
            content_hash=p3_review.content_hash,
        ).model_dump(mode="json")
    )
    p3_receipt_payload["issue_proofs"][0]["known_defects"] = []
    p3_receipt_payload["tcd_metrics"]["known_p2_dispositions"] = 0
    p3_receipt = parse_delivery_contract(p3_receipt_payload)
    assert isinstance(p3_receipt, DeliveryReceipt)
    assert (
        validate_delivery_receipt_evidence(
            p3_receipt,
            initiation=initiation,
            plan=plan,
            worker_results=(worker,),
            review_results=(p3_review,),
            reducer_effects=(recovery_effect,),
        )
        is p3_receipt
    )

    wrong_closure_pr_proof = proof.model_copy(
        update={
            "merge_identity": None,
            "closure": proof.closure.model_copy(
                update={"pull_request_number": 9999}
            )
            if proof.closure is not None
            else None,
        }
    )
    wrong_closure_pr_receipt = receipt.model_copy(
        update={"issue_proofs": (wrong_closure_pr_proof,)}
    )
    with pytest.raises(ValueError, match="PR, head, or exceptions"):
        validate_delivery_receipt_evidence(
            wrong_closure_pr_receipt,
            initiation=initiation,
            plan=plan,
            worker_results=(worker,),
            review_results=(review,),
            reducer_effects=(recovery_effect,),
        )

    substituted_issue = _issue(issue.issue_number, SHA_C)
    substituted_worker_payload = worker.model_dump(mode="json")
    substituted_worker_payload["issue"] = substituted_issue.model_dump(mode="json")
    substituted_worker = parse_delivery_contract(substituted_worker_payload)
    assert isinstance(substituted_worker, StructuredWorkerResult)
    substituted_review_payload = review.model_dump(mode="json")
    substituted_review_payload["issue"] = substituted_issue.model_dump(mode="json")
    substituted_review = parse_delivery_contract(substituted_review_payload)
    assert isinstance(substituted_review, ReviewResult)
    substituted_receipt_payload = receipt.model_dump(mode="json")
    substituted_proof = substituted_receipt_payload["issue_proofs"][0]
    substituted_proof["issue"] = substituted_issue.model_dump(mode="json")
    substituted_proof["worker_result_ref"] = ContractRef(
        schema_version=substituted_worker.schema_version,
        contract_id=substituted_worker.result_id,
        content_hash=substituted_worker.content_hash,
    ).model_dump(mode="json")
    substituted_proof["review_result_ref"] = ContractRef(
        schema_version=substituted_review.schema_version,
        contract_id=substituted_review.result_id,
        content_hash=substituted_review.content_hash,
    ).model_dump(mode="json")
    with pytest.raises(ValidationError, match="cover final scope exactly"):
        parse_delivery_contract(substituted_receipt_payload)

    worker_exception = DeliveryException(
        kind="execution_failed",
        code="worker-failed",
        message="Worker failed before producing a pull request.",
        retryable=False,
        evidence_refs=("worker:failed",),
    )
    failed_worker_payload = worker.model_dump(mode="json")
    failed_worker_payload.update(
        {
            "status": "failed",
            "exact_head_sha": None,
            "pull_request_number": None,
            "validations": [],
            "exceptions": [worker_exception.model_dump(mode="json")],
        }
    )
    failed_worker = parse_delivery_contract(failed_worker_payload)
    assert isinstance(failed_worker, StructuredWorkerResult)
    unordered_worker_payload = failed_worker.model_dump(mode="json")
    unordered_worker_payload["exceptions"] = [
        DeliveryException(
            kind="execution_failed",
            code="z-worker-error",
            message="Second worker failure.",
            retryable=False,
            evidence_refs=("worker:z",),
        ).model_dump(mode="json"),
        DeliveryException(
            kind="execution_failed",
            code="a-worker-error",
            message="First worker failure.",
            retryable=False,
            evidence_refs=("worker:a",),
        ).model_dump(mode="json"),
    ]
    with pytest.raises(ValidationError, match="canonical sorted order"):
        parse_delivery_contract(unordered_worker_payload)

    failed_receipt_payload = receipt.model_dump(mode="json")
    failed_receipt_payload["terminal_outcome"] = "failed"
    failed_receipt_payload["exceptions"] = [
        worker_exception.model_dump(mode="json")
    ]
    failed_receipt_payload["recovery_history"] = []
    failed_receipt_payload["tcd_metrics"]["known_p2_dispositions"] = 0
    failed_proof = failed_receipt_payload["issue_proofs"][0]
    failed_proof.update(
        {
            "worker_result_ref": ContractRef(
                schema_version=failed_worker.schema_version,
                contract_id=failed_worker.result_id,
                content_hash=failed_worker.content_hash,
            ).model_dump(mode="json"),
            "review_result_ref": None,
            "exact_head_sha": None,
            "delivery_stage": "worker_terminal",
            "merge_identity": None,
            "check_evidence": [],
            "review_disposition": None,
            "known_defects": [],
            "exceptions": [worker_exception.model_dump(mode="json")],
            "closure": None,
        }
    )
    failed_receipt = parse_delivery_contract(failed_receipt_payload)
    assert isinstance(failed_receipt, DeliveryReceipt)
    assert (
        validate_delivery_receipt_evidence(
            failed_receipt,
            initiation=initiation,
            plan=plan,
            worker_results=(failed_worker,),
            review_results=(),
            reducer_effects=(),
        )
        is failed_receipt
    )
    unrelated_exception_payload = failed_receipt.model_dump(mode="json")
    unrelated_exception_payload["exceptions"] = [
        DeliveryException(
            kind="authority_conflict",
            code="unrelated-authority-conflict",
            message="This does not resolve the worker failure.",
            retryable=False,
            evidence_refs=("authority:unrelated",),
        ).model_dump(mode="json")
    ]
    with pytest.raises(ValidationError, match="exactly project"):
        parse_delivery_contract(unrelated_exception_payload)

    for contradictory_outcome in ("blocked", "cancelled"):
        contradictory_payload = failed_receipt.model_dump(mode="json")
        contradictory_payload["terminal_outcome"] = contradictory_outcome
        contradictory_receipt = parse_delivery_contract(contradictory_payload)
        assert isinstance(contradictory_receipt, DeliveryReceipt)
        with pytest.raises(ValueError, match="terminal outcome contradicts"):
            validate_delivery_receipt_evidence(
                contradictory_receipt,
                initiation=initiation,
                plan=plan,
                worker_results=(failed_worker,),
                review_results=(),
                reducer_effects=(),
            )

    terminal_fixtures = (
        (
            "blocked",
            DeliveryException(
                kind="dependency_blocked",
                code="worker-blocked",
                message="Dependency remains blocked.",
                retryable=True,
                evidence_refs=("worker:blocked",),
            ),
        ),
        (
            "cancelled",
            DeliveryException(
                kind="cancelled",
                code="worker-cancelled",
                message="Run was explicitly cancelled.",
                retryable=False,
                evidence_refs=("worker:cancelled",),
            ),
        ),
    )
    for worker_status, terminal_exception in terminal_fixtures:
        terminal_worker_payload = failed_worker.model_dump(mode="json")
        terminal_worker_payload["status"] = worker_status
        terminal_worker_payload["exceptions"] = [
            terminal_exception.model_dump(mode="json")
        ]
        terminal_worker = parse_delivery_contract(terminal_worker_payload)
        assert isinstance(terminal_worker, StructuredWorkerResult)
        for contradictory_outcome in {
            "blocked",
            "failed",
            "cancelled",
        } - {worker_status}:
            contradictory_payload = failed_receipt.model_dump(mode="json")
            contradictory_payload["terminal_outcome"] = contradictory_outcome
            contradictory_payload["exceptions"] = [
                terminal_exception.model_dump(mode="json")
            ]
            contradictory_payload["issue_proofs"][0]["worker_result_ref"] = (
                ContractRef(
                    schema_version=terminal_worker.schema_version,
                    contract_id=terminal_worker.result_id,
                    content_hash=terminal_worker.content_hash,
                ).model_dump(mode="json")
            )
            contradictory_payload["issue_proofs"][0]["exceptions"] = [
                terminal_exception.model_dump(mode="json")
            ]
            contradictory_receipt = parse_delivery_contract(contradictory_payload)
            assert isinstance(contradictory_receipt, DeliveryReceipt)
            with pytest.raises(ValueError, match="terminal outcome contradicts"):
                validate_delivery_receipt_evidence(
                    contradictory_receipt,
                    initiation=initiation,
                    plan=plan,
                    worker_results=(terminal_worker,),
                    review_results=(),
                    reducer_effects=(),
                )

    mismatched_plan_payload = plan.model_dump(mode="json")
    mismatched_plan_payload["plan_id"] = "other-plan"
    mismatched_plan = DeliveryPlan.model_validate_json(
        json.dumps(mismatched_plan_payload)
    )
    with pytest.raises(ValueError, match="plan ref"):
        validate_delivery_receipt_evidence(
            receipt,
            initiation=initiation,
            plan=mismatched_plan,
            worker_results=(worker,),
            review_results=(review,),
            reducer_effects=(recovery_effect,),
        )
