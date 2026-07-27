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
    IssueDeliveryProof,
    IssueScope,
    KnownDefectRef,
    MergeIdentity,
    PolicyProfile,
    Provenance,
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
    delivery_initiation_approval_hash,
    parse_delivery_contract,
    validate_delivery_receipt_evidence,
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
        authority_scope="RasmusTho/agentic-pkm-mvp",
    )


def _source(source_id: str, content_hash: str = SHA_A) -> SourceRef:
    return SourceRef(
        source_type="github_issue",
        source_id=source_id,
        content_hash=content_hash,
    )


def _provenance(correlation_id: str) -> Provenance:
    return Provenance(
        created_at=TS,
        created_by=_actor("builder:codex-root-4165"),
        source_refs=(_source("RasmusTho/agentic-pkm-mvp#4165"),),
        correlation_id=correlation_id,
    )


def _issue(number: int, content_hash: str) -> IssueScope:
    return IssueScope(
        repository="RasmusTho/agentic-pkm-mvp",
        issue_number=number,
        authority_id=f"github:RasmusTho/agentic-pkm-mvp/issues/{number}",
        contract_hash=content_hash,
    )


def _authority(issue: IssueScope, state: str = "open") -> AuthoritySnapshot:
    return AuthoritySnapshot(
        authority_type="github_issue",
        authority_id=issue.authority_id,
        content_hash=issue.contract_hash,
        observed_state=state,
        observed_at=TS,
    )


def _policy() -> PolicyProfile:
    return PolicyProfile(
        profile_id="delivery-low-risk",
        profile_version="v1",
        profile_hash=SHA_B,
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
    return DeliveryInitiation(
        initiation_id="init-4165",
        requested_scope=requested_scope,
        exclusions=exclusions,
        approval_evidence=ApprovalEvidence(
            approval_id="approval-4165",
            approver=_actor(),
            approved_at=TS,
            approved_payload_hash=delivery_initiation_approval_hash(
                initiation_id="init-4165",
                requested_scope=requested_scope,
                exclusions=exclusions,
                policy_profile=policy_profile,
                budget=budget,
                source_authorities=source_authorities,
            ),
            source_refs=(_source("RasmusTho/agentic-pkm-mvp#4165", SHA_C),),
        ),
        policy_profile=policy_profile,
        budget=budget,
        source_authorities=source_authorities,
        provenance=_provenance("initiation-4165"),
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
            "claim_issue",
            "launch_worker",
            "await_ci",
            "request_review",
            "merge_pull_request",
            "close_issue",
            "record_delivery_receipt",
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
        minimum_confidence_basis_points=8_000,
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
        known_defect_refs=("known-defect:4300",),
        provenance=_provenance("review-result-4165"),
    )


def _receipt(
    issue: IssueScope,
    initiation: DeliveryInitiation,
    plan: DeliveryPlan,
    worker: StructuredWorkerResult,
    review: ReviewResult,
) -> DeliveryReceipt:
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
                merge_identity=MergeIdentity(
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
                        status="passed",
                        exact_head_sha=SHA_D,
                        evidence_ref="github-check:9001",
                    ),
                ),
                review_disposition=review.disposition,
                known_defects=(
                    KnownDefectRef(
                        issue_number=4300,
                        severity="P2",
                        registry_ref="known-defect:4300",
                        finding_hash=SHA_A,
                    ),
                ),
                exceptions=(),
                closure=ClosureEvidence(
                    issue_number=issue.issue_number,
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
                action="read_live_authority",
                authority_readback_refs=("github-pr:4200:merged",),
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
        provenance=_provenance("receipt-4165"),
    )


def test_contracts_round_trip_canonically() -> None:
    issue = _issue(4165, SHA_A)
    initiation = _initiation(issue)
    plan = _plan(issue, initiation)
    worker = _worker_result(issue, plan)
    review = _review_result(issue, plan)
    event = ReducerEvent(
        event_id="event-1",
        run_id="run-4165",
        plan_ref=ContractRef(
            schema_version=plan.schema_version,
            contract_id=plan.plan_id,
            content_hash=plan.content_hash,
        ),
        sequence=1,
        event_type="worker_result_recorded",
        subject_authority=_authority(issue),
        effect_ref=None,
        result_ref=ContractRef(
            schema_version=worker.schema_version,
            contract_id=worker.result_id,
            content_hash=worker.content_hash,
        ),
        exception=None,
        provenance=_provenance("event-1"),
    )
    effect = ReducerEffect(
        effect_id="effect-1",
        run_id="run-4165",
        plan_ref=event.plan_ref,
        sequence=2,
        effect_class="await_ci",
        issue=issue,
        pull_request_number=4200,
        exact_head_sha=SHA_D,
        expected_authorities=(_authority(issue),),
        idempotency_key="run-4165:await-ci:4165:2",
        input_hash=SHA_B,
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
    invalid_event["subject_authority"] = None
    with pytest.raises(ValidationError, match="result ref"):
        parse_delivery_contract(invalid_event)

    invalid_effect = effect.model_dump(mode="json")
    invalid_effect["pull_request_number"] = None
    invalid_effect["exact_head_sha"] = None
    with pytest.raises(ValidationError, match="pull request and exact head"):
        parse_delivery_contract(invalid_effect)

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
        "claim_issue",
        "launch_worker",
        "await_ci",
        "request_review",
        "merge_pull_request",
        "close_issue",
        "record_delivery_receipt",
    )

    payload = plan.model_dump(mode="json")
    payload["input_authorities"] = []
    with pytest.raises(ValidationError, match="input authorities"):
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


def test_receipt_preserves_delivery_and_tcd_evidence() -> None:
    issue = _issue(4165, SHA_A)
    initiation = _initiation(issue)
    plan = _plan(issue, initiation)
    worker = _worker_result(issue, plan)
    review = _review_result(issue, plan)
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
        )
        is receipt
    )

    payload = receipt.model_dump(mode="json")
    payload["issue_proofs"][0]["merge_identity"]["exact_head_sha"] = SHA_C
    with pytest.raises(ValidationError, match="exact head"):
        parse_delivery_contract(payload)

    payload = receipt.model_dump(mode="json")
    payload["issue_proofs"][0]["check_evidence"] = []
    with pytest.raises(ValidationError, match="accepted exact-head proof"):
        parse_delivery_contract(payload)

    payload = receipt.model_dump(mode="json")
    payload["recovery_history"] = []
    with pytest.raises(ValidationError, match="reconciled recovery"):
        parse_delivery_contract(payload)

    payload = review.model_dump(mode="json")
    payload["confidence_basis_points"] = 0
    with pytest.raises(ValidationError, match="low-confidence"):
        parse_delivery_contract(payload)

    payload = review.model_dump(mode="json")
    payload["known_defect_refs"] = []
    with pytest.raises(ValidationError, match="known-defect refs"):
        parse_delivery_contract(payload)

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
        )
