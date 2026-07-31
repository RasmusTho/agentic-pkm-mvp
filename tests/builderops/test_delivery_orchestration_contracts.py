from __future__ import annotations

import json
from dataclasses import replace as dataclass_replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.builderops.delivery_orchestration_contracts import (
    ACCEPTANCE_EVIDENCE_BY_EFFECT_OUTCOME,
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
    WORKER_RESULT_VERSION,
    canonical_hash,
    delivery_event_id,
    delivery_event_input_hash,
    delivery_effect_idempotency_key,
    delivery_effect_expected_outcome_keys,
    delivery_effect_input_hash,
    delivery_initiation_approval_hash,
    parse_delivery_contract,
    resolve_current_authority,
    validate_delivery_plan_evidence,
    validate_delivery_receipt_evidence,
    validate_reducer_effect_evidence,
    validate_reducer_event_evidence,
)
from app.builderops.delivery_orchestration_contracts import (
    DELIVERY_ACCEPTANCE_PROFILE_VERSION,
    DeliveryAcceptanceProfile,
    DeliveryReceiptV2,
    OutstandingEffectObligation,
    WorkerCarrierEnvelope,
    WorkerContextPack,
    WorkerInvocation,
    WorkerResultV2,
    WorkerRuntimeObservation,
    normalized_worker_delivery_result,
    validate_delivery_receipt_v2_evidence,
    validate_worker_authority_chain,
    worker_conformance_key,
    worker_invocation_idempotency_key,
    worker_invocation_input_hash,
)
from app.builderops.delivery_reducer import (
    ACTIVE_PHASES,
    COMPENSATING_EFFECT_CLASSES,
    REDUCER_SIGNALS,
    REDUCER_TRANSITION_MATRIX,
    RUN_PHASES,
    TERMINAL_PHASES,
    AdmittedEvent,
    DeliveryRunState,
    EffectProposal,
    LifecycleCommand,
    ReducerAdmissionError,
    Reduction,
    admit_reducer_event,
    initial_delivery_run_state,
    materialize_effect,
    outstanding_effect_obligations,
    proposal_effect_identity,
    reduce_delivery_run,
    reduce_lifecycle_command,
    replay_delivery_sidecar,
    resolve_terminal_delivery,
)
from app.builderops.delivery_runner import (
    AUTHORITY_ENTRYPOINTS,
    START_ONCE_OPERATION_BY_STATE,
    WORKER_RUNTIME_OPERATIONS,
    WORKER_RUNTIME_STATES,
    WorkerRuntimeUnknownError,
    missing_authority_entrypoints,
    prepare_worker_execution,
    resolve_authority_invocation,
    resolve_worker_start,
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
        actor_type=(
            "builder_agent"
            if actor_id.startswith("builder:")
            else "human"
        ),
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


def _initiation(
    issue: IssueScope,
    *,
    source_authority: AuthoritySnapshot | None = None,
) -> DeliveryInitiation:
    exclusions = (
        ScopeExclusion(
            scope_key="durable-carrier-selection",
            reason="Deferred to the explicit carrier governance gate.",
        ),
    )
    requested_scope = (issue,)
    policy_profile = _policy()
    budget = _budget()
    source_authorities = (source_authority or _authority(issue),)
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
        input_authorities=initiation.source_authorities,
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
            "record_known_defect",
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


def _claim_effect(
    issue: IssueScope,
    plan: DeliveryPlan,
) -> ReducerEffect:
    plan_ref = ContractRef(
        schema_version=plan.schema_version,
        contract_id=plan.plan_id,
        content_hash=plan.content_hash,
    )
    authorities = plan.input_authorities
    expected_outcome_keys = delivery_effect_expected_outcome_keys(
        effect_class="claim_issue",
        run_id="run-4165",
        issue=issue,
        pull_request_number=None,
        required_check_names=plan.policy_profile.required_check_names,
    )
    input_hash = delivery_effect_input_hash(
        run_id="run-4165",
        plan_ref=plan_ref,
        effect_class="claim_issue",
        issue=issue,
        pull_request_number=None,
        exact_head_sha=None,
        expected_authorities=authorities,
        expected_outcome_keys=expected_outcome_keys,
    )
    idempotency_key = delivery_effect_idempotency_key(input_hash)
    return ReducerEffect(
        effect_id=idempotency_key,
        run_id="run-4165",
        plan_ref=plan_ref,
        causal_event=_run_started_event(plan),
        sequence=1,
        effect_class="claim_issue",
        issue=issue,
        pull_request_number=None,
        exact_head_sha=None,
        expected_authorities=authorities,
        expected_outcome_keys=expected_outcome_keys,
        idempotency_key=idempotency_key,
        input_hash=input_hash,
        provenance=_provenance("effect-claim-4165"),
    )


def _claim_recovery_receipt(
    issue: IssueScope,
    initiation: DeliveryInitiation,
    plan: DeliveryPlan,
    worker: StructuredWorkerResult,
    review: ReviewResult,
    claim_effect: ReducerEffect,
) -> DeliveryReceipt:
    receipt = _receipt(issue, initiation, plan, worker, review)
    exception = DeliveryException(
        kind="external_state_unknown",
        code="claim-timeout-reconciled",
        message="Claim call timed out and was reconciled from live authority.",
        retryable=False,
        evidence_refs=("github-issue:4165:claimed",),
    )
    payload = receipt.model_dump(mode="json")
    payload["exceptions"] = [exception.model_dump(mode="json")]
    payload["recovery_history"] = [
        RecoveryStep(
            step_index=0,
            exception_kind=exception.kind,
            exception_code=exception.code,
            exception_hash=canonical_hash(exception),
            effect_ref=ContractRef(
                schema_version=claim_effect.schema_version,
                contract_id=claim_effect.effect_id,
                content_hash=claim_effect.content_hash,
            ),
            effect_class="claim_issue",
            issue=issue,
            action="read_live_claim_authority",
            authority_readbacks=(
                RecoveryAuthorityReadback(
                    effect_idempotency_key=claim_effect.idempotency_key,
                    authority_id=issue.authority_id,
                    issue=issue,
                    pull_request_number=None,
                    exact_head_sha=None,
                    observed_state="open",
                    observed_labels=("type:task",),
                    observed_at=TS,
                    evidence_ref="github-issue:4165:claimed",
                ),
            ),
            outcome_evidence=EffectOutcomeEvidence(
                effect_class="claim_issue",
                effect_idempotency_key=claim_effect.idempotency_key,
                outcome_state="claimed",
                outcome_keys=claim_effect.expected_outcome_keys,
                observed_at=TS,
                evidence_refs=("github-issue:4165:claimed",),
            ),
            outcome="reconciled",
            occurred_at=TS,
        ).model_dump(mode="json")
    ]
    parsed = parse_delivery_contract(payload)
    assert isinstance(parsed, DeliveryReceipt)
    return parsed


def _known_defect_effect(
    issue: IssueScope,
    plan: DeliveryPlan,
    *,
    registry_ref: str,
    finding_hash: str,
    sequence: int,
    causal_event: ReducerEvent | None = None,
) -> ReducerEffect:
    plan_ref = ContractRef(
        schema_version=plan.schema_version,
        contract_id=plan.plan_id,
        content_hash=plan.content_hash,
    )
    authorities = (_authority(issue),)
    expected_outcome_keys = delivery_effect_expected_outcome_keys(
        effect_class="record_known_defect",
        run_id="run-4165",
        issue=issue,
        pull_request_number=4200,
        required_check_names=plan.policy_profile.required_check_names,
        known_defect_registry_ref=registry_ref,
        known_defect_finding_hash=finding_hash,
    )
    input_hash = delivery_effect_input_hash(
        run_id="run-4165",
        plan_ref=plan_ref,
        effect_class="record_known_defect",
        issue=issue,
        pull_request_number=4200,
        exact_head_sha=SHA_D,
        expected_authorities=authorities,
        expected_outcome_keys=expected_outcome_keys,
        known_defect_registry_ref=registry_ref,
        known_defect_finding_hash=finding_hash,
    )
    idempotency_key = delivery_effect_idempotency_key(input_hash)
    return ReducerEffect(
        effect_id=idempotency_key,
        run_id="run-4165",
        plan_ref=plan_ref,
        causal_event=causal_event or _run_started_event(plan),
        sequence=sequence,
        effect_class="record_known_defect",
        issue=issue,
        pull_request_number=4200,
        exact_head_sha=SHA_D,
        expected_authorities=authorities,
        expected_outcome_keys=expected_outcome_keys,
        known_defect_registry_ref=registry_ref,
        known_defect_finding_hash=finding_hash,
        idempotency_key=idempotency_key,
        input_hash=input_hash,
        provenance=_provenance(f"effect-known-defect-{sequence}"),
    )


def _effect_result_event(
    effect: ReducerEffect,
    *,
    subject: AuthoritySnapshot,
    outcome_state: str,
    correlation_id: str,
) -> ReducerEvent:
    effect_ref = ContractRef(
        schema_version=effect.schema_version,
        contract_id=effect.effect_id,
        content_hash=effect.content_hash,
    )
    outcome = EffectOutcomeEvidence(
        effect_class=effect.effect_class,
        effect_idempotency_key=effect.idempotency_key,
        outcome_state=outcome_state,
        outcome_keys=effect.expected_outcome_keys,
        observed_at=TS,
        evidence_refs=(f"effect-outcome:{correlation_id}",),
    )
    input_hash = delivery_event_input_hash(
        run_id=effect.run_id,
        plan_ref=effect.plan_ref,
        sequence=effect.sequence + 1,
        event_type="effect_succeeded",
        subject_authority=subject,
        effect_ref=effect_ref,
        result_ref=None,
        exception=None,
        effect_outcome=outcome,
    )
    return ReducerEvent(
        event_id=delivery_event_id(input_hash),
        input_hash=input_hash,
        run_id=effect.run_id,
        plan_ref=effect.plan_ref,
        sequence=effect.sequence + 1,
        event_type="effect_succeeded",
        subject_authority=subject,
        effect_ref=effect_ref,
        result_ref=None,
        exception=None,
        effect_outcome=outcome,
        provenance=_provenance(correlation_id),
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
            human_interventions=1,
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
    result_causal_effect = effect.model_copy(
        update={"causal_event": event}
    )
    with pytest.raises(
        ValueError,
        match="worker event requires supplied worker-result evidence",
    ):
        validate_reducer_effect_evidence(
            result_causal_effect,
            plan=plan,
        )
    assert (
        validate_reducer_effect_evidence(
            result_causal_effect,
            plan=plan,
            worker_results=(worker,),
        )
        is result_causal_effect
    )
    wrong_pr_worker = worker.model_copy(
        update={"pull_request_number": 9999}
    )
    wrong_pr_event_ref = ContractRef(
        schema_version=wrong_pr_worker.schema_version,
        contract_id=wrong_pr_worker.result_id,
        content_hash=wrong_pr_worker.content_hash,
    )
    wrong_pr_event_hash = delivery_event_input_hash(
        run_id=event.run_id,
        plan_ref=event.plan_ref,
        sequence=event.sequence,
        event_type=event.event_type,
        subject_authority=event.subject_authority,
        effect_ref=None,
        result_ref=wrong_pr_event_ref,
        exception=None,
    )
    wrong_pr_event = event.model_copy(
        update={
            "event_id": delivery_event_id(wrong_pr_event_hash),
            "input_hash": wrong_pr_event_hash,
            "result_ref": wrong_pr_event_ref,
        }
    )
    with pytest.raises(ValueError, match="PR and head"):
        validate_reducer_effect_evidence(
            effect.model_copy(update={"causal_event": wrong_pr_event}),
            plan=plan,
            worker_results=(wrong_pr_worker,),
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
    ready_authority = _authority(
        issue,
        labels=("agent:ready", "type:task"),
    )
    ready_plan_payload = plan.model_dump(mode="json")
    ready_plan_payload["input_authorities"] = [
        ready_authority.model_dump(mode="json")
    ]
    ready_plan = parse_delivery_contract(ready_plan_payload)
    assert isinstance(ready_plan, DeliveryPlan)
    ready_plan_ref = ContractRef(
        schema_version=ready_plan.schema_version,
        contract_id=ready_plan.plan_id,
        content_hash=ready_plan.content_hash,
    )
    claim_outcome_keys = delivery_effect_expected_outcome_keys(
        effect_class="claim_issue",
        run_id=effect.run_id,
        issue=issue,
        pull_request_number=None,
        required_check_names=plan.policy_profile.required_check_names,
    )
    claim_effect_hash = delivery_effect_input_hash(
        run_id=effect.run_id,
        plan_ref=ready_plan_ref,
        effect_class="claim_issue",
        issue=issue,
        pull_request_number=None,
        exact_head_sha=None,
        expected_authorities=(ready_authority,),
        expected_outcome_keys=claim_outcome_keys,
    )
    claim_effect_key = delivery_effect_idempotency_key(
        claim_effect_hash
    )
    claim_effect = ReducerEffect(
        effect_id=claim_effect_key,
        run_id=effect.run_id,
        plan_ref=ready_plan_ref,
        causal_event=_run_started_event(ready_plan),
        sequence=1,
        effect_class="claim_issue",
        issue=issue,
        pull_request_number=None,
        exact_head_sha=None,
        expected_authorities=(ready_authority,),
        expected_outcome_keys=claim_outcome_keys,
        idempotency_key=claim_effect_key,
        input_hash=claim_effect_hash,
        provenance=_provenance("effect-claim"),
    )
    contradictory_claim_event = _effect_result_event(
        claim_effect,
        subject=_authority(
            issue,
            labels=("agent:ready", "type:task"),
        ),
        outcome_state="claimed",
        correlation_id="event-claim-ready-retained",
    )
    with pytest.raises(ValueError, match="typed post-effect outcome"):
        validate_reducer_event_evidence(
            contradictory_claim_event,
            plan=ready_plan,
            effect=claim_effect,
        )
    valid_claim_event = _effect_result_event(
        claim_effect,
        subject=_authority(issue),
        outcome_state="claimed",
        correlation_id="event-claim-ready-removed",
    )
    assert validate_reducer_event_evidence(
        valid_claim_event,
        plan=ready_plan,
        effect=claim_effect,
    )
    unready_claim_hash = delivery_effect_input_hash(
        run_id=effect.run_id,
        plan_ref=effect.plan_ref,
        effect_class="claim_issue",
        issue=issue,
        pull_request_number=None,
        exact_head_sha=None,
        expected_authorities=(_authority(issue),),
        expected_outcome_keys=claim_outcome_keys,
    )
    unready_claim_key = delivery_effect_idempotency_key(
        unready_claim_hash
    )
    unready_claim_effect = claim_effect.model_copy(
        update={
            "effect_id": unready_claim_key,
            "plan_ref": effect.plan_ref,
            "causal_event": run_started_event,
            "expected_authorities": (_authority(issue),),
            "idempotency_key": unready_claim_key,
            "input_hash": unready_claim_hash,
        }
    )
    unchanged_claim_event = _effect_result_event(
        unready_claim_effect,
        subject=_authority(issue),
        outcome_state="claimed",
        correlation_id="event-claim-without-transition",
    )
    with pytest.raises(ValueError, match="typed post-effect outcome"):
        validate_reducer_event_evidence(
            unchanged_claim_event,
            plan=plan,
            effect=unready_claim_effect,
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

    first_defect_effect = _known_defect_effect(
        issue,
        plan,
        registry_ref=(
            "registry:rasmustho/agentic-pkm-mvp/issues/4300:"
            "KD-AAAAAAAAAAAA"
        ),
        finding_hash=canonical_hash(review.findings[0]),
        sequence=6,
    )
    second_defect_effect = _known_defect_effect(
        issue,
        plan,
        registry_ref=(
            "registry:rasmustho/agentic-pkm-mvp/issues/4301:"
            "KD-BBBBBBBBBBBB"
        ),
        finding_hash=SHA_C,
        sequence=7,
    )
    assert first_defect_effect.effect_id != second_defect_effect.effect_id
    assert (
        first_defect_effect.expected_outcome_keys
        != second_defect_effect.expected_outcome_keys
    )
    assert validate_reducer_effect_evidence(
        first_defect_effect,
        plan=plan,
    )
    missing_defect_target = first_defect_effect.model_dump(mode="json")
    missing_defect_target["known_defect_registry_ref"] = None
    with pytest.raises(ValidationError, match="exact defect target"):
        parse_delivery_contract(missing_defect_target)
    foreign_defect_target = first_defect_effect.model_dump(mode="json")
    foreign_defect_target["known_defect_registry_ref"] = (
        "registry:other/repository/issues/4300:KD-AAAAAAAAAAAA"
    )
    with pytest.raises(ValidationError, match="canonical repository"):
        parse_delivery_contract(foreign_defect_target)

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


def test_check_run_id_uses_canonical_github_identity() -> None:
    issue = _issue(4165, SHA_A)
    initiation = _initiation(issue)
    plan = _plan(issue, initiation)
    receipt = _receipt(
        issue,
        initiation,
        plan,
        _worker_result(issue, plan),
        _review_result(issue, plan),
    )
    evidence = receipt.issue_proofs[0].check_evidence[0]

    for check_run_id in ("09001", "not-a-run"):
        evidence_payload = evidence.model_dump(mode="json")
        evidence_payload["check_run_id"] = check_run_id
        evidence_payload["authority_id"] = (
            f"github:{issue.repository}/check-runs/{check_run_id}"
        )
        with pytest.raises(ValidationError, match="pattern"):
            CheckEvidence.model_validate(evidence_payload)

        receipt_payload = receipt.model_dump(mode="json")
        receipt_payload["issue_proofs"][0]["check_evidence"][0].update(
            evidence_payload
        )
        with pytest.raises(ValidationError, match="pattern"):
            parse_delivery_contract(receipt_payload)


def test_current_authority_resolution_is_order_independent() -> None:
    issue = _issue(4165, SHA_A)
    plan = _plan(issue, _initiation(issue))
    plan_ref = ContractRef(
        schema_version=plan.schema_version,
        contract_id=plan.plan_id,
        content_hash=plan.content_hash,
    )
    first_authority = _authority(
        issue,
        labels=("agent:in-progress", "type:task"),
    )
    second_authority = _authority(issue, labels=("type:task",))

    def authority_changed_event(
        subject: AuthoritySnapshot,
        correlation_id: str,
    ) -> ReducerEvent:
        input_hash = delivery_event_input_hash(
            run_id="run-4165",
            plan_ref=plan_ref,
            sequence=1,
            event_type="authority_changed",
            subject_authority=subject,
            effect_ref=None,
            result_ref=None,
            exception=None,
        )
        return ReducerEvent(
            event_id=delivery_event_id(input_hash),
            input_hash=input_hash,
            run_id="run-4165",
            plan_ref=plan_ref,
            sequence=1,
            event_type="authority_changed",
            subject_authority=subject,
            effect_ref=None,
            result_ref=None,
            exception=None,
            provenance=_provenance(correlation_id),
        )

    first_event = authority_changed_event(first_authority, "same-sequence-first")
    second_event = authority_changed_event(second_authority, "same-sequence-second")
    resolved = resolve_current_authority(
        authority_id=issue.authority_id,
        planned_authority=_authority(issue),
        run_id="run-4165",
        plan_ref=plan_ref,
        before_sequence=2,
        prior_events=(first_event, second_event),
    )
    reordered = resolve_current_authority(
        authority_id=issue.authority_id,
        planned_authority=_authority(issue),
        run_id="run-4165",
        plan_ref=plan_ref,
        before_sequence=2,
        prior_events=(second_event, first_event),
    )

    assert resolved == reordered
    assert resolved == second_authority


def test_claim_recovery_requires_ready_to_absent_transition() -> None:
    issue = _issue(4165, SHA_A)
    ready_authority = _authority(
        issue,
        labels=("agent:ready", "type:task"),
    )
    ready_initiation = _initiation(
        issue,
        source_authority=ready_authority,
    )
    ready_plan = _plan(issue, ready_initiation)
    ready_worker = _worker_result(issue, ready_plan)
    ready_review = _review_result(issue, ready_plan)
    ready_claim_effect = _claim_effect(issue, ready_plan)
    ready_receipt = _claim_recovery_receipt(
        issue,
        ready_initiation,
        ready_plan,
        ready_worker,
        ready_review,
        ready_claim_effect,
    )
    assert (
        validate_delivery_receipt_evidence(
            ready_receipt,
            initiation=ready_initiation,
            plan=ready_plan,
            worker_results=(ready_worker,),
            review_results=(ready_review,),
            reducer_effects=(ready_claim_effect,),
        )
        is ready_receipt
    )

    unready_initiation = _initiation(issue)
    unready_plan = _plan(issue, unready_initiation)
    unready_worker = _worker_result(issue, unready_plan)
    unready_review = _review_result(issue, unready_plan)
    unready_claim_effect = _claim_effect(issue, unready_plan)
    unready_receipt = _claim_recovery_receipt(
        issue,
        unready_initiation,
        unready_plan,
        unready_worker,
        unready_review,
        unready_claim_effect,
    )
    with pytest.raises(
        ValueError,
        match="effect-specific outcome",
    ):
        validate_delivery_receipt_evidence(
            unready_receipt,
            initiation=unready_initiation,
            plan=unready_plan,
            worker_results=(unready_worker,),
            review_results=(unready_review,),
            reducer_effects=(unready_claim_effect,),
        )


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
        "record_known_defect",
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
    assert receipt.tcd_metrics.human_interventions == 1
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
    payload["tcd_metrics"]["human_interventions"] = 0
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
    close_outcome_keys = (f"{issue.authority_id}#closed",)
    close_effect_hash = delivery_effect_input_hash(
        run_id="run-4165",
        plan_ref=recovery_effect.plan_ref,
        effect_class="close_issue",
        issue=issue,
        pull_request_number=4200,
        exact_head_sha=SHA_D,
        expected_authorities=(_authority(issue),),
        expected_outcome_keys=close_outcome_keys,
    )
    close_effect_key = delivery_effect_idempotency_key(close_effect_hash)
    close_effect = ReducerEffect(
        effect_id=close_effect_key,
        run_id="run-4165",
        plan_ref=recovery_effect.plan_ref,
        causal_event=_run_started_event(plan),
        sequence=9,
        effect_class="close_issue",
        issue=issue,
        pull_request_number=4200,
        exact_head_sha=SHA_D,
        expected_authorities=(_authority(issue),),
        expected_outcome_keys=close_outcome_keys,
        idempotency_key=close_effect_key,
        input_hash=close_effect_hash,
        provenance=_provenance("effect-close-failed"),
    )
    contradictory_close_event = _effect_result_event(
        close_effect,
        subject=_authority(issue),
        outcome_state="closed",
        correlation_id="event-close-still-open",
    )
    with pytest.raises(ValueError, match="typed post-effect outcome"):
        validate_reducer_event_evidence(
            contradictory_close_event,
            plan=plan,
            effect=close_effect,
        )
    valid_close_event = _effect_result_event(
        close_effect,
        subject=_authority(issue, "closed"),
        outcome_state="closed",
        correlation_id="event-close-confirmed",
    )
    assert validate_reducer_event_evidence(
        valid_close_event,
        plan=plan,
        effect=close_effect,
    )
    failed_close_recovery = RecoveryStep(
        step_index=0,
        exception_kind=closure_exception.kind,
        exception_code=closure_exception.code,
        exception_hash=canonical_hash(closure_exception),
        effect_ref=ContractRef(
            schema_version=close_effect.schema_version,
            contract_id=close_effect.effect_id,
            content_hash=close_effect.content_hash,
        ),
        effect_class="close_issue",
        issue=issue,
        action="preserve_failed_closure_readback",
        authority_readbacks=(
            RecoveryAuthorityReadback(
                effect_idempotency_key=close_effect.idempotency_key,
                authority_id=issue.authority_id,
                issue=issue,
                pull_request_number=4200,
                exact_head_sha=SHA_D,
                observed_state="unchanged",
                observed_labels=("type:task",),
                observed_at=TS,
                evidence_ref="github-issue:4165:still-open",
            ),
        ),
        outcome_evidence=EffectOutcomeEvidence(
            effect_class="close_issue",
            effect_idempotency_key=close_effect.idempotency_key,
            outcome_state="failed",
            outcome_keys=close_effect.expected_outcome_keys,
            observed_at=TS,
            evidence_refs=("github-issue:4165:still-open",),
        ),
        outcome="failed",
        occurred_at=TS,
    )
    partial_payload = receipt.model_dump(mode="json")
    partial_payload["terminal_outcome"] = "partially_delivered"
    partial_payload["exceptions"] = [
        closure_exception.model_dump(mode="json")
    ]
    partial_payload["recovery_history"] = [
        failed_close_recovery.model_dump(mode="json")
    ]
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
            reducer_effects=(close_effect,),
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
    pending_registry_review = parse_delivery_contract(payload)
    assert isinstance(pending_registry_review, ReviewResult)
    pending_review_ref = ContractRef(
        schema_version=pending_registry_review.schema_version,
        contract_id=pending_registry_review.result_id,
        content_hash=pending_registry_review.content_hash,
    )
    pending_review_event_hash = delivery_event_input_hash(
        run_id="run-4165",
        plan_ref=recovery_effect.plan_ref,
        sequence=5,
        event_type="review_result_recorded",
        subject_authority=_authority(issue),
        effect_ref=None,
        result_ref=pending_review_ref,
        exception=None,
    )
    pending_review_event = ReducerEvent(
        event_id=delivery_event_id(pending_review_event_hash),
        input_hash=pending_review_event_hash,
        run_id="run-4165",
        plan_ref=recovery_effect.plan_ref,
        sequence=5,
        event_type="review_result_recorded",
        subject_authority=_authority(issue),
        effect_ref=None,
        result_ref=pending_review_ref,
        exception=None,
        provenance=_provenance("event-pending-p2-review"),
    )
    pending_defect_ref = (
        "registry:rasmustho/agentic-pkm-mvp/issues/4300:"
        "KD-AAAAAAAAAAAA"
    )
    pending_defect_effect = _known_defect_effect(
        issue,
        plan,
        registry_ref=pending_defect_ref,
        finding_hash=canonical_hash(
            pending_registry_review.findings[0]
        ),
        sequence=6,
        causal_event=pending_review_event,
    )
    pending_defect_exception = DeliveryException(
        kind="execution_failed",
        code="known-defect-registry-unavailable",
        message="The exact P2 disposition could not be recorded.",
        retryable=True,
        evidence_refs=("known-defect-registry:unavailable",),
    )
    pending_defect_recovery = RecoveryStep(
        step_index=0,
        exception_kind=pending_defect_exception.kind,
        exception_code=pending_defect_exception.code,
        exception_hash=canonical_hash(pending_defect_exception),
        effect_ref=ContractRef(
            schema_version=pending_defect_effect.schema_version,
            contract_id=pending_defect_effect.effect_id,
            content_hash=pending_defect_effect.content_hash,
        ),
        effect_class="record_known_defect",
        issue=issue,
        action="preserve_pending_known_defect",
        authority_readbacks=(
            RecoveryAuthorityReadback(
                effect_idempotency_key=(
                    pending_defect_effect.idempotency_key
                ),
                authority_id=pending_defect_ref,
                issue=issue,
                pull_request_number=4200,
                exact_head_sha=SHA_D,
                observed_state="unchanged",
                observed_labels=(),
                observed_at=TS,
                evidence_ref="known-defect-registry:unavailable",
            ),
        ),
        outcome_evidence=EffectOutcomeEvidence(
            effect_class="record_known_defect",
            effect_idempotency_key=(
                pending_defect_effect.idempotency_key
            ),
            outcome_state="failed",
            outcome_keys=pending_defect_effect.expected_outcome_keys,
            observed_at=TS,
            evidence_refs=("known-defect-registry:unavailable",),
        ),
        outcome="retry_scheduled",
        occurred_at=TS,
    )
    pending_registry_payload = receipt.model_dump(mode="json")
    pending_registry_payload["terminal_outcome"] = "failed"
    pending_registry_payload["exceptions"] = [
        pending_defect_exception.model_dump(mode="json")
    ]
    pending_registry_payload["recovery_history"] = [
        pending_defect_recovery.model_dump(mode="json")
    ]
    pending_registry_payload["issue_proofs"][0]["delivery_stage"] = (
        "merge_ready"
    )
    pending_registry_payload["issue_proofs"][0]["merge_identity"] = None
    pending_registry_payload["issue_proofs"][0]["closure"] = None
    pending_registry_payload["issue_proofs"][0]["exceptions"] = [
        pending_defect_exception.model_dump(mode="json")
    ]
    pending_registry_payload["issue_proofs"][0]["review_result_ref"] = (
        pending_review_ref.model_dump(mode="json")
    )
    pending_registry_payload["issue_proofs"][0]["known_defects"] = []
    pending_registry_payload["tcd_metrics"]["known_p2_dispositions"] = 0
    pending_registry_receipt = parse_delivery_contract(
        pending_registry_payload
    )
    assert isinstance(pending_registry_receipt, DeliveryReceipt)
    assert (
        validate_delivery_receipt_evidence(
            pending_registry_receipt,
            initiation=initiation,
            plan=plan,
            worker_results=(worker,),
            review_results=(pending_registry_review,),
            reducer_effects=(pending_defect_effect,),
        )
        is pending_registry_receipt
    )
    arbitrary_pending_payload = pending_registry_receipt.model_dump(
        mode="json"
    )
    arbitrary_pending_payload["recovery_history"][0][
        "authority_readbacks"
    ][0]["authority_id"] = issue.authority_id
    arbitrary_pending_receipt = parse_delivery_contract(
        arbitrary_pending_payload
    )
    assert isinstance(arbitrary_pending_receipt, DeliveryReceipt)
    with pytest.raises(ValueError, match="exact registry authority"):
        validate_delivery_receipt_evidence(
            arbitrary_pending_receipt,
            initiation=initiation,
            plan=plan,
            worker_results=(worker,),
            review_results=(pending_registry_review,),
            reducer_effects=(pending_defect_effect,),
        )
    unrelated_pending_effect = _known_defect_effect(
        issue,
        plan,
        registry_ref=pending_defect_ref,
        finding_hash=SHA_C,
        sequence=6,
        causal_event=pending_review_event,
    )
    unrelated_pending_payload = pending_registry_receipt.model_dump(
        mode="json"
    )
    unrelated_pending_payload["recovery_history"][0]["effect_ref"] = (
        ContractRef(
            schema_version=unrelated_pending_effect.schema_version,
            contract_id=unrelated_pending_effect.effect_id,
            content_hash=unrelated_pending_effect.content_hash,
        ).model_dump(mode="json")
    )
    unrelated_pending_payload["recovery_history"][0][
        "authority_readbacks"
    ][0]["effect_idempotency_key"] = (
        unrelated_pending_effect.idempotency_key
    )
    unrelated_pending_payload["recovery_history"][0]["outcome_evidence"][
        "effect_idempotency_key"
    ] = unrelated_pending_effect.idempotency_key
    unrelated_pending_payload["recovery_history"][0]["outcome_evidence"][
        "outcome_keys"
    ] = list(unrelated_pending_effect.expected_outcome_keys)
    unrelated_pending_receipt = parse_delivery_contract(
        unrelated_pending_payload
    )
    assert isinstance(unrelated_pending_receipt, DeliveryReceipt)
    with pytest.raises(ValueError, match="exact P2 finding"):
        validate_delivery_receipt_evidence(
            unrelated_pending_receipt,
            initiation=initiation,
            plan=plan,
            worker_results=(worker,),
            review_results=(pending_registry_review,),
            reducer_effects=(unrelated_pending_effect,),
        )

    recorded_review_ref = ContractRef(
        schema_version=review.schema_version,
        contract_id=review.result_id,
        content_hash=review.content_hash,
    )
    recorded_review_event_hash = delivery_event_input_hash(
        run_id="run-4165",
        plan_ref=recovery_effect.plan_ref,
        sequence=5,
        event_type="review_result_recorded",
        subject_authority=_authority(issue),
        effect_ref=None,
        result_ref=recorded_review_ref,
        exception=None,
    )
    recorded_review_event = ReducerEvent(
        event_id=delivery_event_id(recorded_review_event_hash),
        input_hash=recorded_review_event_hash,
        run_id="run-4165",
        plan_ref=recovery_effect.plan_ref,
        sequence=5,
        event_type="review_result_recorded",
        subject_authority=_authority(issue),
        effect_ref=None,
        result_ref=recorded_review_ref,
        exception=None,
        provenance=_provenance("event-recorded-p2-review"),
    )
    recorded_defect_effect = _known_defect_effect(
        issue,
        plan,
        registry_ref=pending_defect_ref,
        finding_hash=canonical_hash(review.findings[0]),
        sequence=6,
        causal_event=recorded_review_event,
    )
    recorded_defect_exception = DeliveryException(
        kind="external_state_unknown",
        code="known-defect-timeout-reconciled",
        message="The exact P2 disposition was confirmed after timeout.",
        retryable=False,
        evidence_refs=("known-defect-registry:recorded",),
    )
    recorded_defect_recovery = RecoveryStep(
        step_index=0,
        exception_kind=recorded_defect_exception.kind,
        exception_code=recorded_defect_exception.code,
        exception_hash=canonical_hash(recorded_defect_exception),
        effect_ref=ContractRef(
            schema_version=recorded_defect_effect.schema_version,
            contract_id=recorded_defect_effect.effect_id,
            content_hash=recorded_defect_effect.content_hash,
        ),
        effect_class="record_known_defect",
        issue=issue,
        action="confirm_known_defect_registry",
        authority_readbacks=(
            RecoveryAuthorityReadback(
                effect_idempotency_key=(
                    recorded_defect_effect.idempotency_key
                ),
                authority_id=pending_defect_ref,
                issue=issue,
                pull_request_number=4200,
                exact_head_sha=SHA_D,
                observed_state="recorded",
                observed_labels=(),
                observed_at=TS,
                evidence_ref="known-defect-registry:recorded",
            ),
        ),
        outcome_evidence=EffectOutcomeEvidence(
            effect_class="record_known_defect",
            effect_idempotency_key=(
                recorded_defect_effect.idempotency_key
            ),
            outcome_state="known_defect_recorded",
            outcome_keys=recorded_defect_effect.expected_outcome_keys,
            observed_at=TS,
            evidence_refs=("known-defect-registry:recorded",),
        ),
        outcome="reconciled",
        occurred_at=TS,
    )
    recorded_registry_payload = receipt.model_dump(mode="json")
    recorded_registry_payload["exceptions"] = [
        recorded_defect_exception.model_dump(mode="json")
    ]
    recorded_registry_payload["recovery_history"] = [
        recorded_defect_recovery.model_dump(mode="json")
    ]
    recorded_registry_receipt = parse_delivery_contract(
        recorded_registry_payload
    )
    assert isinstance(recorded_registry_receipt, DeliveryReceipt)
    assert (
        validate_delivery_receipt_evidence(
            recorded_registry_receipt,
            initiation=initiation,
            plan=plan,
            worker_results=(worker,),
            review_results=(review,),
            reducer_effects=(recorded_defect_effect,),
        )
        is recorded_registry_receipt
    )
    unrecorded_registry_payload = recorded_registry_receipt.model_dump(
        mode="json"
    )
    unrecorded_registry_payload["recovery_history"][0][
        "authority_readbacks"
    ][0]["observed_state"] = "unchanged"
    unrecorded_registry_receipt = parse_delivery_contract(
        unrecorded_registry_payload
    )
    assert isinstance(unrecorded_registry_receipt, DeliveryReceipt)
    with pytest.raises(ValueError, match="exact registry authority"):
        validate_delivery_receipt_evidence(
            unrecorded_registry_receipt,
            initiation=initiation,
            plan=plan,
            worker_results=(worker,),
            review_results=(review,),
            reducer_effects=(recorded_defect_effect,),
        )

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


def _ready_authority(issue: IssueScope) -> AuthoritySnapshot:
    return _authority(issue, labels=("agent:ready", "type:task"))


def _claimed_authority(issue: IssueScope) -> AuthoritySnapshot:
    return _authority(issue, labels=("agent:in-progress", "type:task"))


def _claimed_run_context(
    issue: IssueScope,
) -> tuple[DeliveryPlan, ReducerEffect, ReducerEvent, AuthoritySnapshot]:
    """Build a run whose claim effect already moved authority past plan input."""

    initiation = _initiation(issue, source_authority=_ready_authority(issue))
    plan = _plan(issue, initiation)
    claim_effect = _claim_effect(issue, plan)
    claimed = _claimed_authority(issue)
    claim_succeeded = _effect_result_event(
        claim_effect,
        subject=claimed,
        outcome_state="claimed",
        correlation_id="event-claim-succeeded",
    )
    assert (
        validate_reducer_event_evidence(
            claim_succeeded,
            plan=plan,
            effect=claim_effect,
        )
        is claim_succeeded
    )
    return plan, claim_effect, claim_succeeded, claimed


def _structured_result_event(
    *,
    plan: DeliveryPlan,
    event_type: str,
    result_ref: ContractRef,
    subject: AuthoritySnapshot,
    sequence: int,
    correlation_id: str,
) -> ReducerEvent:
    plan_ref = ContractRef(
        schema_version=plan.schema_version,
        contract_id=plan.plan_id,
        content_hash=plan.content_hash,
    )
    input_hash = delivery_event_input_hash(
        run_id="run-4165",
        plan_ref=plan_ref,
        sequence=sequence,
        event_type=event_type,
        subject_authority=subject,
        effect_ref=None,
        result_ref=result_ref,
        exception=None,
    )
    return ReducerEvent(
        event_id=delivery_event_id(input_hash),
        input_hash=input_hash,
        run_id="run-4165",
        plan_ref=plan_ref,
        sequence=sequence,
        event_type=event_type,  # type: ignore[arg-type]
        subject_authority=subject,
        effect_ref=None,
        result_ref=result_ref,
        exception=None,
        provenance=_provenance(correlation_id),
    )


def test_structured_result_events_bind_resolved_current_authority() -> None:
    """A truthful post-claim worker/review result is not stale plan input."""

    issue = _issue(4165, SHA_A)
    plan, _unused_claim_effect, claim_succeeded, claimed = _claimed_run_context(
        issue
    )
    worker = _worker_result(issue, plan)
    review = _review_result(issue, plan)
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
    worker_event = _structured_result_event(
        plan=plan,
        event_type="worker_result_recorded",
        result_ref=worker_ref,
        subject=claimed,
        sequence=3,
        correlation_id="event-worker-post-claim",
    )
    review_event = _structured_result_event(
        plan=plan,
        event_type="review_result_recorded",
        result_ref=review_ref,
        subject=claimed,
        sequence=4,
        correlation_id="event-review-post-claim",
    )

    assert (
        validate_reducer_event_evidence(
            worker_event,
            plan=plan,
            worker_result=worker,
            prior_events=(claim_succeeded,),
        )
        is worker_event
    )
    assert (
        validate_reducer_event_evidence(
            review_event,
            plan=plan,
            review_result=review,
            prior_events=(claim_succeeded,),
        )
        is review_event
    )

    # Without a proven claim transition the pre-claim plan input remains the
    # resolved authority, so a post-claim subject stays fail-closed.
    with pytest.raises(ValueError, match="subject contradicts"):
        validate_reducer_event_evidence(
            worker_event,
            plan=plan,
            worker_result=worker,
        )

    # Resolution accepts only authority that the supplied event log proves.
    invented = _authority(issue, "closed", labels=("type:task",))
    invented_event = _structured_result_event(
        plan=plan,
        event_type="worker_result_recorded",
        result_ref=worker_ref,
        subject=invented,
        sequence=3,
        correlation_id="event-worker-invented",
    )
    with pytest.raises(ValueError, match="subject contradicts"):
        validate_reducer_event_evidence(
            invented_event,
            plan=plan,
            worker_result=worker,
            prior_events=(claim_succeeded,),
        )


def test_timer_events_can_cause_authority_bound_effects() -> None:
    """A subjectless timer must be able to cause the next await/retry effect."""

    issue = _issue(4165, SHA_A)
    plan, claim_effect, claim_succeeded, claimed = _claimed_run_context(issue)
    plan_ref = ContractRef(
        schema_version=plan.schema_version,
        contract_id=plan.plan_id,
        content_hash=plan.content_hash,
    )
    timer_input_hash = delivery_event_input_hash(
        run_id="run-4165",
        plan_ref=plan_ref,
        sequence=3,
        event_type="timer_elapsed",
        subject_authority=None,
        effect_ref=None,
        result_ref=None,
        exception=None,
    )
    timer_event = ReducerEvent(
        event_id=delivery_event_id(timer_input_hash),
        input_hash=timer_input_hash,
        run_id="run-4165",
        plan_ref=plan_ref,
        sequence=3,
        event_type="timer_elapsed",
        subject_authority=None,
        effect_ref=None,
        result_ref=None,
        exception=None,
        provenance=_provenance("event-ci-wait-timer"),
    )

    def _await_ci_effect(
        authorities: tuple[AuthoritySnapshot, ...],
    ) -> ReducerEffect:
        expected_outcome_keys = delivery_effect_expected_outcome_keys(
            effect_class="await_ci",
            run_id="run-4165",
            issue=issue,
            pull_request_number=4200,
            required_check_names=plan.policy_profile.required_check_names,
        )
        input_hash = delivery_effect_input_hash(
            run_id="run-4165",
            plan_ref=plan_ref,
            effect_class="await_ci",
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
            causal_event=timer_event,
            sequence=4,
            effect_class="await_ci",
            issue=issue,
            pull_request_number=4200,
            exact_head_sha=SHA_D,
            expected_authorities=authorities,
            expected_outcome_keys=expected_outcome_keys,
            idempotency_key=idempotency_key,
            input_hash=input_hash,
            provenance=_provenance("effect-await-ci-4165"),
        )

    timer_effect = _await_ci_effect((claimed,))
    assert (
        validate_reducer_effect_evidence(
            timer_effect,
            plan=plan,
            prior_effects=(claim_effect,),
            prior_events=(claim_succeeded,),
        )
        is timer_effect
    )

    # The timer carries no authority of its own, so the effect must still bind
    # the latest proven authority instead of a stale plan snapshot.
    stale_timer_effect = _await_ci_effect((_ready_authority(issue),))
    with pytest.raises(ValueError, match="expected live authority"):
        validate_reducer_effect_evidence(
            stale_timer_effect,
            plan=plan,
            prior_effects=(claim_effect,),
            prior_events=(claim_succeeded,),
        )


def test_check_evidence_requires_distinct_check_run_identity() -> None:
    """One reused check run cannot satisfy several required check names."""

    issue = _issue(4165, SHA_A)
    shared_check_run = {
        "repository": issue.repository,
        "check_run_id": "9001",
        "authority_id": f"github:{issue.repository}/check-runs/9001",
        "pull_request_number": 4200,
        "status": "passed",
        "exact_head_sha": SHA_D,
        "completed_at": TS,
        "evidence_ref": "github-check:9001",
    }
    with pytest.raises(
        ValidationError,
        match="check run authority identities must not contain duplicates",
    ):
        IssueDeliveryProof(
            issue=issue,
            worker_result_ref=ContractRef(
                schema_version=WORKER_RESULT_VERSION,
                contract_id="worker-result-4165",
                content_hash=SHA_B,
            ),
            review_result_ref=None,
            exact_head_sha=SHA_D,
            delivery_stage="worker_terminal",
            merge_identity=None,
            check_evidence=(
                CheckEvidence(
                    check_name="Contract validation",
                    **shared_check_run,  # type: ignore[arg-type]
                ),
                CheckEvidence(
                    check_name="Unit tests (not pg)",
                    **shared_check_run,  # type: ignore[arg-type]
                ),
            ),
            review_disposition=None,
            known_defects=(),
            exceptions=(),
            closure=None,
        )

    # The same false-green shape must also be rejected through deserialization.
    initiation = _initiation(issue)
    plan = _plan(issue, initiation)
    worker = _worker_result(issue, plan)
    review = _review_result(issue, plan)
    receipt = _receipt(issue, initiation, plan, worker, review)
    payload = receipt.model_dump(mode="json")
    original_check = payload["issue_proofs"][0]["check_evidence"][0]
    replayed_check = dict(original_check)
    replayed_check["check_name"] = "Contract validation"
    payload["issue_proofs"][0]["check_evidence"] = [
        replayed_check,
        original_check,
    ]
    with pytest.raises(
        ValidationError,
        match="check run authority identities must not contain duplicates",
    ):
        parse_delivery_contract(payload)


# ---------------------------------------------------------------------------
# DDO-04: deterministic reducer, worker seam, and bounded authority adapters.
#
# Every fixture below builds canonical delivered contracts. The reducer is only
# ever driven through admitted events, and every effect it proposes is
# materialized through the delivered identity derivations and re-validated by
# validate_reducer_effect_evidence, so a green assertion here cannot be green
# against a hand-rolled shadow model.
# ---------------------------------------------------------------------------

DDO4_RUN = "run-4167"
DDO4_PR = 4200
DDO4_BASE_HEAD = SHA_C
DDO4_HEAD = SHA_D
DDO4_REPAIRED_HEAD = SHA_E
DDO4_CONTROL_SCOPE = "rasmustho/agentic-pkm-mvp"
DDO4_DEFECT_REF = (
    "registry:rasmustho/agentic-pkm-mvp/issues/4300:KD-AAAAAAAAAAAA"
)


def _ddo4_ref(contract: object, contract_id: str) -> ContractRef:
    return ContractRef(
        schema_version=contract.schema_version,  # type: ignore[attr-defined]
        contract_id=contract_id,
        content_hash=contract.content_hash,  # type: ignore[attr-defined]
    )


def _ddo4_initiation(issues: tuple[IssueScope, ...]) -> DeliveryInitiation:
    exclusions = (
        ScopeExclusion(
            scope_key="durable-carrier-selection",
            reason="Deferred to the explicit carrier governance gate.",
        ),
    )
    requested_scope = tuple(sorted(issues, key=lambda item: item.scope_key))
    policy_profile = _policy()
    budget = _budget()
    source_authorities = tuple(
        sorted(
            (_ready_authority(issue) for issue in requested_scope),
            key=lambda item: item.authority_id,
        )
    )
    provenance = _provenance("initiation-4167")
    approval_id = "approval-4167"
    approver = _actor()
    approval_source_refs = (_source("rasmustho/agentic-pkm-mvp#4167", SHA_C),)
    return DeliveryInitiation(
        initiation_id="init-4167",
        requested_scope=requested_scope,
        exclusions=exclusions,
        approval_evidence=ApprovalEvidence(
            approval_id=approval_id,
            approver=approver,
            approved_at=TS,
            approved_payload_hash=delivery_initiation_approval_hash(
                initiation_id="init-4167",
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


def _ddo4_plan(waves: tuple[tuple[IssueScope, ...], ...]) -> DeliveryPlan:
    issues = tuple(
        sorted(
            (issue for wave in waves for issue in wave),
            key=lambda item: item.scope_key,
        )
    )
    initiation = _ddo4_initiation(issues)
    return DeliveryPlan(
        plan_id="plan-4167",
        initiation_ref=_ddo4_ref(initiation, initiation.initiation_id),
        input_authorities=initiation.source_authorities,
        final_scope=issues,
        exclusions=initiation.exclusions,
        dependency_waves=tuple(
            DependencyWave(
                wave_index=index,
                issues=tuple(sorted(wave, key=lambda item: item.scope_key)),
            )
            for index, wave in enumerate(waves)
        ),
        expected_states=tuple(
            ExpectedAuthorityState(
                issue=issue,
                issue_state="open",
                required_labels=("agent:ready", "type:task"),
                forbidden_labels=("agent:blocked",),
                expected_contract_hash=issue.contract_hash,
            )
            for issue in issues
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
            "record_known_defect",
            "request_review",
        ),
        provenance=_provenance("plan-4167"),
    )


def _ddo4_profile(
    required_evidence: tuple[str, ...] = (
        "issue_closed",
        "pull_request_merged",
        "required_checks_green",
        "review_accepted",
    ),
) -> DeliveryAcceptanceProfile:
    return DeliveryAcceptanceProfile(
        profile_id="acceptance-verified-delivery",
        required_evidence=required_evidence,  # type: ignore[arg-type]
        provenance=_provenance("acceptance-profile-4167"),
    )


def _ddo4_state(
    plan: DeliveryPlan,
    profile: DeliveryAcceptanceProfile,
) -> DeliveryRunState:
    return initial_delivery_run_state(
        run_id=DDO4_RUN,
        plan=plan,
        acceptance_profile=profile,
        authorized_control_scopes=(DDO4_CONTROL_SCOPE,),
    )


def _ddo4_event(
    plan: DeliveryPlan,
    *,
    sequence: int,
    event_type: str,
    subject: AuthoritySnapshot | None = None,
    effect_ref: ContractRef | None = None,
    result_ref: ContractRef | None = None,
    exception: DeliveryException | None = None,
    effect_outcome: EffectOutcomeEvidence | None = None,
    correlation_id: str,
) -> ReducerEvent:
    plan_ref = _ddo4_ref(plan, plan.plan_id)
    input_hash = delivery_event_input_hash(
        run_id=DDO4_RUN,
        plan_ref=plan_ref,
        sequence=sequence,
        event_type=event_type,
        subject_authority=subject,
        effect_ref=effect_ref,
        result_ref=result_ref,
        exception=exception,
        effect_outcome=effect_outcome,
    )
    return ReducerEvent(
        event_id=delivery_event_id(input_hash),
        input_hash=input_hash,
        run_id=DDO4_RUN,
        plan_ref=plan_ref,
        sequence=sequence,
        event_type=event_type,  # type: ignore[arg-type]
        subject_authority=subject,
        effect_ref=effect_ref,
        result_ref=result_ref,
        exception=exception,
        effect_outcome=effect_outcome,
        provenance=_provenance(correlation_id),
    )


def _ddo4_effect_outcome_event(
    plan: DeliveryPlan,
    effect: ReducerEffect,
    *,
    subject: AuthoritySnapshot,
    outcome_state: str,
    sequence: int,
    correlation_id: str,
    succeeded: bool = True,
    exception: DeliveryException | None = None,
) -> ReducerEvent:
    outcome = EffectOutcomeEvidence(
        effect_class=effect.effect_class,
        effect_idempotency_key=effect.idempotency_key,
        outcome_state=outcome_state,  # type: ignore[arg-type]
        outcome_keys=effect.expected_outcome_keys,
        observed_at=TS,
        evidence_refs=(f"effect-outcome:{correlation_id}",),
    )
    return _ddo4_event(
        plan,
        sequence=sequence,
        event_type="effect_succeeded" if succeeded else "effect_failed",
        subject=subject,
        effect_ref=_ddo4_ref(effect, effect.effect_id),
        effect_outcome=outcome,
        exception=exception,
        correlation_id=correlation_id,
    )


def _ddo4_closed_authority(issue: IssueScope) -> AuthoritySnapshot:
    return _authority(issue, "closed", labels=("type:task",))


def _ddo4_worker_domain_result(
    issue: IssueScope,
    plan: DeliveryPlan,
    *,
    result_id: str,
    head: str = DDO4_HEAD,
    pull_request_number: int = DDO4_PR,
    status: str = "completed",
) -> StructuredWorkerResult:
    completed = status == "completed"
    return StructuredWorkerResult(
        result_id=result_id,
        run_id=DDO4_RUN,
        plan_ref=_ddo4_ref(plan, plan.plan_id),
        issue=issue,
        status=status,  # type: ignore[arg-type]
        exact_head_sha=head if completed else None,
        pull_request_number=pull_request_number if completed else None,
        changed_files=("app/builderops/delivery_reducer.py",),
        validations=(
            ValidationEvidence(
                name="focused-reducer-tests",
                status="passed",
                evidence_ref="pytest:delivery-reducer",
                exact_head_sha=head,
            ),
        )
        if completed
        else (),
        exceptions=()
        if completed
        else (
            DeliveryException(
                kind="execution_failed",
                code="worker-execution-failed",
                message="The bounded worker could not finish the slice.",
                retryable=False,
                evidence_refs=("worker:4167:failed",),
            ),
        ),
        summary="Implemented the deterministic delivery-run reducer.",
        provenance=_provenance(result_id),
    )


def _ddo4_worker_bundle(
    issue: IssueScope,
    plan: DeliveryPlan,
    launch_effect: ReducerEffect,
    *,
    result_id: str = "worker-result-v2-4167",
    domain_result_id: str = "worker-result-4167",
    head: str = DDO4_HEAD,
    base_head: str | None = DDO4_BASE_HEAD,
    pull_request_number: int = DDO4_PR,
    status: str = "completed",
    carrier_id: str = "carrier-alpha",
    provider_id: str = "provider-alpha",
    worker_model_ref: str = "worker-model-alpha",
) -> tuple[WorkerContextPack, WorkerInvocation, WorkerResultV2]:
    plan_ref = _ddo4_ref(plan, plan.plan_id)
    effect_ref = _ddo4_ref(launch_effect, launch_effect.effect_id)
    pack = WorkerContextPack(
        context_pack_id=f"pack-{issue.issue_number}",
        run_id=DDO4_RUN,
        plan_ref=plan_ref,
        effect_ref=effect_ref,
        issue=issue,
        base_head_sha=base_head,
        required_skills=("issue-to-code",),
        verify_targets=(
            "tests/builderops/test_delivery_orchestration_contracts.py",
        ),
        context_refs=(_source(f"{issue.authority_id}", issue.contract_hash),),
        provenance=_provenance(f"pack-{issue.issue_number}"),
    )
    pack_ref = _ddo4_ref(pack, pack.context_pack_id)
    input_hash = worker_invocation_input_hash(
        run_id=DDO4_RUN,
        plan_ref=plan_ref,
        effect_ref=effect_ref,
        issue=issue,
        base_head_sha=base_head,
        context_pack_ref=pack_ref,
        runtime_target="bounded-worker-runtime",
    )
    invocation = WorkerInvocation(
        invocation_id=worker_invocation_idempotency_key(input_hash),
        run_id=DDO4_RUN,
        plan_ref=plan_ref,
        effect_ref=effect_ref,
        issue=issue,
        base_head_sha=base_head,
        context_pack_ref=pack_ref,
        context_pack_hash=pack.content_hash,
        runtime_target="bounded-worker-runtime",
        idempotency_key=worker_invocation_idempotency_key(input_hash),
        input_hash=input_hash,
        provenance=_provenance(f"invocation-{issue.issue_number}"),
    )
    domain = _ddo4_worker_domain_result(
        issue,
        plan,
        result_id=domain_result_id,
        head=head,
        pull_request_number=pull_request_number,
        status=status,
    )
    result = WorkerResultV2(
        result_id=result_id,
        run_id=DDO4_RUN,
        plan_ref=plan_ref,
        effect_ref=effect_ref,
        issue=issue,
        base_head_sha=base_head,
        exact_head_sha=domain.exact_head_sha,
        pull_request_number=domain.pull_request_number,
        context_pack_ref=pack_ref,
        context_pack_hash=pack.content_hash,
        invocation_ref=_ddo4_ref(invocation, invocation.invocation_id),
        invocation_idempotency_key=invocation.idempotency_key,
        delivery_result=domain,
        carrier=WorkerCarrierEnvelope(
            carrier_id=carrier_id,
            provider_id=provider_id,
            worker_model_ref=worker_model_ref,
            session_ref=f"session-{carrier_id}",
            usage_ref=f"usage-{carrier_id}",
            provenance_ref=f"provenance-{carrier_id}",
        ),
        provenance=_provenance(result_id),
    )
    return pack, invocation, result


def _ddo4_review(
    issue: IssueScope,
    plan: DeliveryPlan,
    *,
    result_id: str,
    disposition: str,
    findings: tuple[ReviewFinding, ...] = (),
    known_defect_refs: tuple[str, ...] = (),
    confidence_basis_points: int = 9_500,
    head: str = DDO4_HEAD,
) -> ReviewResult:
    return ReviewResult(
        result_id=result_id,
        run_id=DDO4_RUN,
        plan_ref=_ddo4_ref(plan, plan.plan_id),
        policy_profile=plan.policy_profile,
        issue=issue,
        pull_request_number=DDO4_PR,
        exact_head_sha=head,
        disposition=disposition,  # type: ignore[arg-type]
        confidence_basis_points=confidence_basis_points,
        findings=findings,
        known_defect_refs=known_defect_refs,
        provenance=_provenance(result_id),
    )


class _DdoRun:
    """A deterministic driver that only ever feeds admitted canonical events."""

    def __init__(
        self,
        plan: DeliveryPlan,
        profile: DeliveryAcceptanceProfile,
    ) -> None:
        self.plan = plan
        self.profile = profile
        self.state = _ddo4_state(plan, profile)
        self.sequence = 0
        self.events: list[ReducerEvent] = []
        self.effects: list[ReducerEffect] = []
        self.worker_results: list[StructuredWorkerResult] = []
        self.review_results: list[ReviewResult] = []
        self.last: Reduction | None = None

    def next_sequence(self) -> int:
        self.sequence += 1
        return self.sequence

    def apply(self, admitted: AdmittedEvent) -> Reduction:
        result = reduce_delivery_run(self.state, admitted)
        self.last = result
        if result.refusal is None:
            self.state = result.state
            self.events.append(admitted.event)
        return result

    def materialize(
        self,
        proposal: EffectProposal,
        causal_event: ReducerEvent,
    ) -> ReducerEffect:
        effect = materialize_effect(
            proposal,
            state=self.state,
            plan=self.plan,
            causal_event=causal_event,
            sequence=self.next_sequence(),
            provenance=_provenance(
                f"effect-{proposal.effect_class}-{proposal.issue.issue_number}"
            ),
            prior_effects=tuple(self.effects),
            prior_events=tuple(self.events),
            worker_results=tuple(self.worker_results),
            review_results=tuple(self.review_results),
        )
        self.effects.append(effect)
        return effect

    def admit(self, event: ReducerEvent, **kwargs: object) -> AdmittedEvent:
        return admit_reducer_event(
            event,
            plan=self.plan,
            prior_effects=tuple(self.effects),
            prior_events=tuple(self.events),
            worker_results=tuple(self.worker_results),
            review_results=tuple(self.review_results),
            **kwargs,  # type: ignore[arg-type]
        )

    def start(self) -> Reduction:
        event = _ddo4_event(
            self.plan,
            sequence=0,
            event_type="run_started",
            correlation_id="event-run-started-4167",
        )
        return self.apply(self.admit(event))

    def tick(self) -> Reduction:
        sequence = self.next_sequence()
        event = _ddo4_event(
            self.plan,
            sequence=sequence,
            event_type="timer_elapsed",
            correlation_id=f"event-timer-{sequence}",
        )
        return self.apply(self.admit(event))

    def succeed(
        self,
        proposal: EffectProposal,
        causal_event: ReducerEvent,
        *,
        subject: AuthoritySnapshot,
        outcome_state: str,
        label: str,
    ) -> Reduction:
        effect = self.materialize(proposal, causal_event)
        event = _ddo4_effect_outcome_event(
            self.plan,
            effect,
            subject=subject,
            outcome_state=outcome_state,
            sequence=self.next_sequence(),
            correlation_id=f"event-{label}",
        )
        return self.apply(self.admit(event, effect=effect))

    def fail(
        self,
        proposal: EffectProposal,
        causal_event: ReducerEvent,
        *,
        subject: AuthoritySnapshot,
        label: str,
    ) -> Reduction:
        effect = self.materialize(proposal, causal_event)
        event = _ddo4_effect_outcome_event(
            self.plan,
            effect,
            subject=subject,
            outcome_state="failed",
            sequence=self.next_sequence(),
            correlation_id=f"event-{label}",
            succeeded=False,
            exception=DeliveryException(
                kind="execution_failed",
                code=f"{label}-failed",
                message="The governed authority reported a failed effect.",
                retryable=True,
                evidence_refs=(f"effect-failure:{label}",),
            ),
        )
        return self.apply(self.admit(event, effect=effect))


def _command_for(
    state: DeliveryRunState,
    command: str,
    *,
    command_id: str,
) -> LifecycleCommand:
    return LifecycleCommand(
        command=command,  # type: ignore[arg-type]
        command_id=command_id,
        run_id=DDO4_RUN,
        expected_run_version=state.version,
        issued_by=_actor("owner:RasmusTho"),
        issued_at=TS,
    )


def _drive_to_launching(
    issue: IssueScope,
    *,
    plan: DeliveryPlan | None = None,
) -> tuple[_DdoRun, ReducerEvent, EffectProposal]:
    """Advance one Issue to launching, with its launch effect still in flight."""

    plan = plan or _ddo4_plan(((issue,),))
    run = _DdoRun(plan, _ddo4_profile())
    started = run.start()
    run.succeed(
        started.effects[0],
        run.events[-1],
        subject=_claimed_authority(issue),
        outcome_state="claimed",
        label="claim",
    )
    launch_proposal = run.last.effects[0]
    assert launch_proposal.effect_class == "launch_worker"
    return run, run.events[-1], launch_proposal


def _drive_to_awaiting_ci(
    issue: IssueScope,
    *,
    plan: DeliveryPlan | None = None,
    profile: DeliveryAcceptanceProfile | None = None,
) -> tuple[_DdoRun, ReducerEvent, ReducerEffect]:
    """Advance one Issue to awaiting_ci with only reducer decisions."""

    plan = plan or _ddo4_plan(((issue,),))
    run = _DdoRun(plan, profile or _ddo4_profile())
    claimed = _claimed_authority(issue)

    started = run.start()
    assert [item.effect_class for item in started.effects] == ["claim_issue"]
    run.succeed(
        started.effects[0],
        run.events[-1],
        subject=claimed,
        outcome_state="claimed",
        label="claim",
    )
    launch_proposal = run.last.effects[0]
    assert launch_proposal.effect_class == "launch_worker"
    run.succeed(
        launch_proposal,
        run.events[-1],
        subject=claimed,
        outcome_state="worker_launched",
        label="launch",
    )
    launch_effect = run.effects[-1]

    pack, invocation, result = _ddo4_worker_bundle(issue, plan, launch_effect)
    run.worker_results.append(result.delivery_result)
    worker_event = _ddo4_event(
        plan,
        sequence=run.next_sequence(),
        event_type="worker_result_recorded",
        subject=claimed,
        result_ref=_ddo4_ref(
            result.delivery_result, result.delivery_result.result_id
        ),
        correlation_id="event-worker-result",
    )
    worker_reduction = run.apply(
        run.admit(
            worker_event,
            worker_result=result,
            context_pack=pack,
            invocation=invocation,
            launch_effect=launch_effect,
        )
    )
    assert [item.effect_class for item in worker_reduction.effects] == ["await_ci"]
    return run, worker_event, launch_effect


def _drive_to_awaiting_review(
    issue: IssueScope,
    *,
    plan: DeliveryPlan | None = None,
    profile: DeliveryAcceptanceProfile | None = None,
) -> tuple[_DdoRun, ReducerEvent, ReducerEffect]:
    """Advance one Issue to awaiting_review with only reducer decisions."""

    run, worker_event, launch_effect = _drive_to_awaiting_ci(
        issue, plan=plan, profile=profile
    )
    claimed = _claimed_authority(issue)
    run.succeed(
        run.last.effects[0],
        run.events[-1],
        subject=claimed,
        outcome_state="checks_passed",
        label="await-ci",
    )
    review_proposal = run.last.effects[0]
    assert review_proposal.effect_class == "request_review"
    run.succeed(
        review_proposal,
        run.events[-1],
        subject=claimed,
        outcome_state="review_recorded",
        label="request-review",
    )
    return run, worker_event, launch_effect


def _record_review(
    run: _DdoRun,
    review: ReviewResult,
    *,
    subject: AuthoritySnapshot,
) -> Reduction:
    run.review_results.append(review)
    event = _ddo4_event(
        run.plan,
        sequence=run.next_sequence(),
        event_type="review_result_recorded",
        subject=subject,
        result_ref=_ddo4_ref(review, review.result_id),
        correlation_id=f"event-review-{review.result_id}",
    )
    return run.apply(run.admit(event, review_result=review))


def _drive_to_delivered(
    issue: IssueScope,
    *,
    profile: DeliveryAcceptanceProfile | None = None,
) -> _DdoRun:
    run, _worker_event, _launch = _drive_to_awaiting_review(issue, profile=profile)
    claimed = _claimed_authority(issue)
    accepted = _record_review(
        run,
        _ddo4_review(
            issue,
            run.plan,
            result_id="review-accept-4167",
            disposition="accept",
        ),
        subject=claimed,
    )
    assert [item.effect_class for item in accepted.effects] == [
        "merge_pull_request"
    ]
    run.succeed(
        accepted.effects[0],
        run.events[-1],
        subject=claimed,
        outcome_state="merged",
        label="merge",
    )
    close_proposal = run.last.effects[0]
    assert close_proposal.effect_class == "close_issue"
    run.succeed(
        close_proposal,
        run.events[-1],
        subject=_ddo4_closed_authority(issue),
        outcome_state="closed",
        label="close",
    )
    receipt_proposal = run.last.effects[0]
    assert receipt_proposal.effect_class == "record_delivery_receipt"
    run.succeed(
        receipt_proposal,
        run.events[-1],
        subject=_ddo4_closed_authority(issue),
        outcome_state="receipt_recorded",
        label="receipt",
    )
    return run


def test_reducer_transition_matrix_is_exhaustive() -> None:
    """The matrix is total, terminal-closed, and actually governs the reducer."""

    assert set(REDUCER_TRANSITION_MATRIX) == {
        (phase, signal) for phase in RUN_PHASES for signal in REDUCER_SIGNALS
    }
    assert len(REDUCER_TRANSITION_MATRIX) == len(RUN_PHASES) * len(
        REDUCER_SIGNALS
    )
    for phase in TERMINAL_PHASES:
        for signal in REDUCER_SIGNALS:
            assert not REDUCER_TRANSITION_MATRIX[(phase, signal)].legal, (
                f"terminal phase {phase} must refuse {signal}"
            )
    for (phase, signal), rule in REDUCER_TRANSITION_MATRIX.items():
        if rule.legal:
            assert rule.prerequisites, f"{phase}/{signal} names no prerequisite"
            assert phase in ACTIVE_PHASES
        else:
            assert rule.target_phase is None and not rule.emits

    # Every phase the happy path visits is reachable, and the matrix is what
    # refuses everything else from that phase.
    issue = _issue(4167, SHA_A)
    run = _drive_to_delivered(issue)
    assert run.state.issue_state(issue.scope_key).phase == "delivered"

    # The matrix is what refuses an otherwise well-formed event, and it is the
    # only thing that makes a terminal phase terminal for events. Prove that
    # with a genuinely FRESH event - a duplicate would be refused earlier and
    # would prove nothing about the matrix.
    merge_effect = next(
        effect
        for effect in run.effects
        if effect.effect_class == "merge_pull_request"
    )
    replayed_merge = _ddo4_effect_outcome_event(
        run.plan,
        merge_effect,
        subject=_claimed_authority(issue),
        outcome_state="merged",
        sequence=run.next_sequence(),
        correlation_id="event-merge-after-delivered",
    )
    assert replayed_merge.event_id not in run.state.seen_event_ids
    refused = reduce_delivery_run(
        run.state, run.admit(replayed_merge, effect=merge_effect)
    )
    assert refused.refusal == "illegal_transition"
    assert refused.state == run.state
    assert not refused.effects
    assert run.state.issue_state(issue.scope_key).phase == "delivered"

    # A refused pair leaves state byte-identical and reports a typed reason.
    fresh = _DdoRun(_ddo4_plan(((issue,),)), _ddo4_profile())
    fresh.start()
    assert not fresh.effects
    claim_effect = fresh.materialize(fresh.last.effects[0], fresh.events[-1])
    claimed_event = _ddo4_effect_outcome_event(
        fresh.plan,
        claim_effect,
        subject=_claimed_authority(issue),
        outcome_state="claimed",
        sequence=fresh.next_sequence(),
        correlation_id="event-claim-matrix",
    )
    admitted = fresh.admit(claimed_event, effect=claim_effect)
    before = fresh.state
    fresh.apply(admitted)
    repeat = reduce_delivery_run(fresh.state, admitted)
    assert repeat.refusal == "duplicate_event"
    assert repeat.state == fresh.state
    assert before.issue_state(issue.scope_key).phase == "claiming"


def test_duplicate_and_stale_events_cannot_advance() -> None:
    """Duplicate identities are no-ops; stale plan or head evidence fails closed."""

    issue = _issue(4167, SHA_A)
    run, _worker_event, _launch = _drive_to_awaiting_review(issue)
    claimed = _claimed_authority(issue)

    replayed = run.events[-1]
    duplicate = reduce_delivery_run(
        run.state, run.admit(replayed, effect=run.effects[-1])
    )
    assert duplicate.refusal == "duplicate_event"
    assert duplicate.state == run.state

    # A verdict for a different head cannot advance the reviewed head.
    stale_head_review = _ddo4_review(
        issue,
        run.plan,
        result_id="review-stale-head",
        disposition="accept",
        head=DDO4_REPAIRED_HEAD,
    )
    stale = _record_review(run, stale_head_review, subject=claimed)
    assert stale.refusal == "head_evidence_conflict"
    assert stale.state == run.state
    run.review_results.pop()

    # A verdict for a different pull request cannot advance the authorized one.
    other_pr_review = ReviewResult(
        result_id="review-other-pr",
        run_id=DDO4_RUN,
        plan_ref=_ddo4_ref(run.plan, run.plan.plan_id),
        policy_profile=run.plan.policy_profile,
        issue=issue,
        pull_request_number=DDO4_PR + 1,
        exact_head_sha=DDO4_HEAD,
        disposition="accept",
        confidence_basis_points=9_500,
        findings=(),
        known_defect_refs=(),
        provenance=_provenance("review-other-pr"),
    )
    other = _record_review(run, other_pr_review, subject=claimed)
    assert other.refusal == "pull_request_identity_conflict"
    run.review_results.pop()

    # An event bound to a different run never resolves against this state.
    foreign = dataclass_replace(run.state, run_id="run-other")
    assert (
        reduce_delivery_run(
            foreign, run.admit(run.events[-1], effect=run.effects[-1])
        ).refusal
        == "foreign_run"
    )

    # An event bound to a different plan cannot advance a run: the plan binding
    # is immutable initial state, so a stale run version fails closed.
    other_plan = _ddo4_plan(((_issue(4169, SHA_B),),))
    stale_plan = dataclass_replace(
        run.state, plan_ref=_ddo4_ref(other_plan, other_plan.plan_id)
    )
    fresh_tick = run.admit(
        _ddo4_event(
            run.plan,
            sequence=run.next_sequence(),
            event_type="timer_elapsed",
            correlation_id="event-timer-stale-plan",
        )
    )
    assert reduce_delivery_run(stale_plan, fresh_tick).refusal == (
        "stale_plan_binding"
    )
    assert reduce_delivery_run(stale_plan, fresh_tick).state == stale_plan

    # A lifecycle command carrying a stale run version is fenced the same way.
    stale_command = reduce_lifecycle_command(
        run.state,
        LifecycleCommand(
            command="pause",
            command_id="cmd-stale-version",
            run_id=DDO4_RUN,
            expected_run_version=run.state.version - 1,
            issued_by=_actor("owner:RasmusTho"),
            issued_at=TS,
        ),
    )
    assert stale_command.refusal == "stale_run_version"
    assert stale_command.state == run.state


def test_effects_require_exact_prerequisites() -> None:
    """No effect is proposed before the exact named prerequisite is proven."""

    issue = _issue(4167, SHA_A)
    plan = _ddo4_plan(((issue,),))
    run = _DdoRun(plan, _ddo4_profile())
    claimed = _claimed_authority(issue)

    started = run.start()
    assert [item.effect_class for item in started.effects] == ["claim_issue"]

    # An outcome event may only report on an effect this run authorized. With
    # the ledgered authorization removed, the identical event is refused, so a
    # foreign or fabricated effect identity cannot advance the run.
    claim_effect = run.materialize(started.effects[0], run.events[-1])
    claim_success = _ddo4_effect_outcome_event(
        plan,
        claim_effect,
        subject=claimed,
        outcome_state="claimed",
        sequence=run.next_sequence(),
        correlation_id="event-claim-authorization",
    )
    claim_admitted = run.admit(claim_success, effect=claim_effect)
    unledgered = dataclass_replace(
        run.state,
        issues=tuple(
            dataclass_replace(item, effect_ledger=())
            for item in run.state.issues
        ),
    )
    unauthorized = reduce_delivery_run(unledgered, claim_admitted)
    assert unauthorized.refusal == "unauthorized_effect"
    assert unauthorized.state == unledgered
    assert not unauthorized.effects

    # launch_worker is not proposed until a truthful claim readback exists.
    ordered: list[tuple[str, tuple[str, ...]]] = []
    run.apply(claim_admitted)
    ordered.append(("claim_succeeded", tuple(
        item.effect_class for item in run.last.effects
    )))
    run.succeed(
        run.last.effects[0],
        run.events[-1],
        subject=claimed,
        outcome_state="worker_launched",
        label="launch",
    )
    ordered.append(("worker_launched", tuple(
        item.effect_class for item in run.last.effects
    )))
    launch_effect = run.effects[-1]
    pack, invocation, result = _ddo4_worker_bundle(issue, plan, launch_effect)
    run.worker_results.append(result.delivery_result)
    worker_event = _ddo4_event(
        plan,
        sequence=run.next_sequence(),
        event_type="worker_result_recorded",
        subject=claimed,
        result_ref=_ddo4_ref(
            result.delivery_result, result.delivery_result.result_id
        ),
        correlation_id="event-worker-prereq",
    )
    run.apply(
        run.admit(
            worker_event,
            worker_result=result,
            context_pack=pack,
            invocation=invocation,
            launch_effect=launch_effect,
        )
    )
    ordered.append(("worker_result", tuple(
        item.effect_class for item in run.last.effects
    )))
    run.succeed(
        run.last.effects[0],
        run.events[-1],
        subject=claimed,
        outcome_state="checks_passed",
        label="await-ci",
    )
    ordered.append(("checks_passed", tuple(
        item.effect_class for item in run.last.effects
    )))

    assert ordered == [
        ("claim_succeeded", ("launch_worker",)),
        ("worker_launched", ()),
        ("worker_result", ("await_ci",)),
        ("checks_passed", ("request_review",)),
    ]

    # A merge cannot be proposed while the run is still awaiting its verdict.
    assert run.state.issue_state(issue.scope_key).phase == "awaiting_review"
    assert not any(
        proposal.effect_class in {"merge_pull_request", "close_issue"}
        for proposal in run.last.effects
    )

    # Every effect the reducer proposed materialized into a canonical effect
    # that the delivered validator independently accepted.
    assert [item.effect_class for item in run.effects] == [
        "claim_issue",
        "launch_worker",
        "await_ci",
    ]
    assert [item.effect_class for item in run.last.effects] == ["request_review"]

    # A red required check emits no retry. It routes to the typed terminal
    # repair deferral, because an autonomous retry needs the durable, replayable
    # effect and invocation identity that DDO-05 owns and #4466 delivers.
    failing_run, _event, _launch = _drive_to_awaiting_ci(_issue(4167, SHA_A))
    awaiting_ci = failing_run.state.issue_state(issue.scope_key)
    assert awaiting_ci.phase == "awaiting_ci"
    deferred = failing_run.fail(
        failing_run.last.effects[0],
        failing_run.events[-1],
        subject=claimed,
        label="await-ci-red",
    )
    deferred_state = deferred.state.issue_state(issue.scope_key)
    assert deferred_state.phase == "repairing"
    assert deferred_state.blocked_reason == "ci_failed_repair_deferred"
    assert deferred.effects == ()
    assert "repairing" in TERMINAL_PHASES
    for signal in REDUCER_SIGNALS:
        assert not REDUCER_TRANSITION_MATRIX[("repairing", signal)].legal

    for effect in run.effects:
        assert effect.effect_id == effect.idempotency_key
        assert effect.effect_class in run.plan.effect_allowlist


def test_review_severity_routes_fail_closed() -> None:
    """One valid P2 defers once; protected, P0, P1, and low confidence block."""

    issue = _issue(4167, SHA_A)
    claimed = _claimed_authority(issue)

    p2_finding = ReviewFinding(
        finding_id="finding-p2-1",
        severity="P2",
        summary="A bounded follow-up remains outside this slice.",
        protected_risk=False,
        false_green=False,
        evidence_refs=("review:4200:finding-p2-1",),
    )
    run, _worker_event, _launch = _drive_to_awaiting_review(issue)
    deferred = _record_review(
        run,
        _ddo4_review(
            issue,
            run.plan,
            result_id="review-p2-4167",
            disposition="accept_with_risk",
            findings=(p2_finding,),
            known_defect_refs=(DDO4_DEFECT_REF,),
        ),
        subject=claimed,
    )
    assert [item.effect_class for item in deferred.effects] == [
        "record_known_defect"
    ]
    assert deferred.effects[0].known_defect_registry_ref == DDO4_DEFECT_REF
    assert deferred.effects[0].known_defect_finding_hash == canonical_hash(
        p2_finding
    )
    # The merge is authorized only after the durable disposition is observed.
    assert run.state.issue_state(issue.scope_key).phase == "recording_defect"
    run.succeed(
        deferred.effects[0],
        run.events[-1],
        subject=claimed,
        outcome_state="known_defect_recorded",
        label="known-defect",
    )
    assert [item.effect_class for item in run.last.effects] == [
        "merge_pull_request"
    ]

    for label, finding in (
        (
            "protected",
            ReviewFinding(
                finding_id="finding-protected",
                severity="P2",
                summary="A protected authority path is affected.",
                protected_risk=True,
                false_green=False,
                evidence_refs=("review:4200:protected",),
            ),
        ),
        (
            "false-green",
            ReviewFinding(
                finding_id="finding-false-green",
                severity="P2",
                summary="A verify target passes without proving its claim.",
                protected_risk=False,
                false_green=True,
                evidence_refs=("review:4200:false-green",),
            ),
        ),
        (
            "p1",
            ReviewFinding(
                finding_id="finding-p1",
                severity="P1",
                summary="An authority-integrity defect remains.",
                protected_risk=False,
                false_green=False,
                evidence_refs=("review:4200:p1",),
            ),
        ),
        (
            "p0",
            ReviewFinding(
                finding_id="finding-p0",
                severity="P0",
                summary="A delivery-blocking defect remains.",
                protected_risk=False,
                false_green=False,
                evidence_refs=("review:4200:p0",),
            ),
        ),
    ):
        blocking_run, _event, _launch_effect = _drive_to_awaiting_review(issue)
        blocked = _record_review(
            blocking_run,
            _ddo4_review(
                issue,
                blocking_run.plan,
                result_id=f"review-{label}",
                disposition="reject",
                findings=(finding,),
            ),
            subject=claimed,
        )
        issue_state = blocked.state.issue_state(issue.scope_key)
        assert issue_state.phase == "blocked", label
        assert issue_state.blocked_reason == "review_blocking"
        assert not blocked.effects

    # Low confidence cannot be expressed as anything but a reject verdict, so
    # the contract layer itself refuses to produce a mergeable low-confidence
    # result and the reducer never sees one.
    with pytest.raises(ValidationError, match="low-confidence"):
        _ddo4_review(
            issue,
            run.plan,
            result_id="review-low-confidence",
            disposition="accept",
            confidence_basis_points=10,
        )

    # More than one deferred P2 is not a single deferred disposition.
    multi_run, _event, _launch_effect = _drive_to_awaiting_review(issue)
    second_p2 = ReviewFinding(
        finding_id="finding-p2-2",
        severity="P2",
        summary="A second unrelated deferral.",
        protected_risk=False,
        false_green=False,
        evidence_refs=("review:4200:finding-p2-2",),
    )
    multi = _record_review(
        multi_run,
        _ddo4_review(
            issue,
            multi_run.plan,
            result_id="review-two-p2",
            disposition="accept_with_risk",
            findings=(p2_finding, second_p2),
            known_defect_refs=(DDO4_DEFECT_REF,),
        ),
        subject=claimed,
    )
    assert multi.state.issue_state(issue.scope_key).phase == "blocked"
    assert not multi.effects


def test_runner_uses_existing_claim_wait_and_verified_closure_paths() -> None:
    """Adapters route to entrypoints that exist; nothing is reimplemented."""

    repo_root = Path(__file__).resolve().parents[2]
    assert missing_authority_entrypoints(repo_root) == ()
    assert AUTHORITY_ENTRYPOINTS["await_ci"] == "scripts/await_pr_checks.sh"
    assert AUTHORITY_ENTRYPOINTS["claim_issue"] == "scripts/issue_pickup_claim.sh"

    issue = _issue(4167, SHA_A)
    run = _drive_to_delivered(issue)
    by_class = {effect.effect_class: effect for effect in run.effects}

    claim = resolve_authority_invocation(
        by_class["claim_issue"], agent_id="builder:ddo04", session_id="session-1"
    )
    assert claim.handoff == "subprocess"
    assert claim.argv[0] == "scripts/issue_pickup_claim.sh"
    assert "--issue" in claim.argv and str(issue.issue_number) in claim.argv
    assert "--repo" in claim.argv and issue.repository in claim.argv

    ci = resolve_authority_invocation(
        by_class["await_ci"], agent_id="builder:ddo04", session_id="session-1"
    )
    assert ci.handoff == "subprocess"
    assert ci.argv[0] == "scripts/await_pr_checks.sh"
    assert str(DDO4_PR) in ci.argv

    for effect_class in ("merge_pull_request", "close_issue", "request_review"):
        governed = resolve_authority_invocation(
            by_class[effect_class],
            agent_id="builder:ddo04",
            session_id="session-1",
        )
        assert governed.handoff == "governed_skill"
        assert governed.entrypoint == (
            ".codex/skills/verification-and-closure/SKILL.md"
        )
        # A governed handoff never pretends to be a runnable command line.
        assert governed.argv == ()

    # Every entrypoint and planner the runner can name is one of the governing
    # paths, and every subprocess handoff is genuinely runnable.
    known = set(AUTHORITY_ENTRYPOINTS.values())
    for effect in run.effects:
        if effect.effect_class == "launch_worker":
            continue
        invocation = resolve_authority_invocation(
            effect, agent_id="builder:ddo04", session_id="session-1"
        )
        assert invocation.entrypoint in known
        assert set(invocation.planner_entrypoints) <= known
        if invocation.handoff == "subprocess":
            assert invocation.argv and invocation.argv[0] in known
        for argument in invocation.argv:
            if argument.startswith("scripts/") or argument.startswith(".codex/"):
                assert argument in known

    # Every advertised entrypoint is actually routed to by some effect class or
    # by the worker preflight, so the map cannot accumulate dead paths.
    routed = {AUTHORITY_ENTRYPOINTS["worktree_lifecycle"]}
    for effect in run.effects:
        if effect.effect_class == "launch_worker":
            continue
        invocation = resolve_authority_invocation(
            effect, agent_id="builder:ddo04", session_id="session-1"
        )
        routed.add(invocation.entrypoint)
        routed.update(invocation.planner_entrypoints)
        routed.update(
            argument for argument in invocation.argv if argument in known
        )
    assert routed == known

    # The worker launch is not a script: it goes through the runtime port.
    with pytest.raises(Exception, match="worker runtime port"):
        resolve_authority_invocation(
            by_class["launch_worker"],
            agent_id="builder:ddo04",
            session_id="session-1",
        )


def test_independent_waves_advance_without_model_coordination() -> None:
    """Wave two opens from the reducer alone once wave one is truly delivered."""

    first = _issue(4167, SHA_A)
    second = _issue(4168, SHA_B)
    plan = _ddo4_plan(((first,), (second,)))
    profile = _ddo4_profile()

    run, _worker_event, _launch = _drive_to_awaiting_review(
        first, plan=plan, profile=profile
    )
    claimed = _claimed_authority(first)

    # Wave two is untouched while wave one is still in flight, and a timer tick
    # cannot open it early.
    assert run.state.issue_state(second.scope_key).phase == "admitted"
    early = run.tick()
    assert not early.effects
    assert run.state.issue_state(second.scope_key).phase == "admitted"

    accepted = _record_review(
        run,
        _ddo4_review(
            first, plan, result_id="review-wave-one", disposition="accept"
        ),
        subject=claimed,
    )
    run.succeed(
        accepted.effects[0],
        run.events[-1],
        subject=claimed,
        outcome_state="merged",
        label="merge",
    )
    run.succeed(
        run.last.effects[0],
        run.events[-1],
        subject=_ddo4_closed_authority(first),
        outcome_state="closed",
        label="close",
    )
    receipt_proposal = run.last.effects[0]

    # The terminal receipt of wave one is the only delivery input. It opens the
    # next wave but proposes nothing, because a reducer effect must bind the
    # subject authority of its causal event and this event's subject is the
    # Issue that just closed.
    receipt = run.succeed(
        receipt_proposal,
        run.events[-1],
        subject=_ddo4_closed_authority(first),
        outcome_state="receipt_recorded",
        label="receipt",
    )
    assert run.state.issue_state(first.scope_key).phase == "delivered"
    assert receipt.effects == ()

    # The next deterministic tick alone opens wave two. Between the terminal
    # wave-one receipt and the wave-two claim there is no coordinator turn, no
    # model decision, and no external input other than the timer.
    events_before = len(run.events)
    opened = run.tick()
    assert len(run.events) == events_before + 1
    assert run.events[-1].event_type == "timer_elapsed"
    assert run.events[-1].subject_authority is None
    assert [
        (item.effect_class, item.issue.issue_number) for item in opened.effects
    ] == [("claim_issue", second.issue_number)]
    assert run.state.issue_state(second.scope_key).phase == "claiming"

    # The wave-two claim materializes into a canonical effect bound to the exact
    # planned authority of the second Issue, not the first.
    wave_two_claim = run.materialize(opened.effects[0], run.events[-1])
    assert wave_two_claim.issue == second
    assert wave_two_claim.expected_authorities == (_ready_authority(second),)
    assert wave_two_claim.causal_event.event_type == "timer_elapsed"


def test_worker_contracts_bind_one_authority_chain() -> None:
    """Pack, invocation, and result resolve one chain; envelopes may differ."""

    issue = _issue(4167, SHA_A)
    plan = _ddo4_plan(((issue,),))
    run = _DdoRun(plan, _ddo4_profile())
    claimed = _claimed_authority(issue)
    started = run.start()
    run.succeed(
        started.effects[0],
        run.events[-1],
        subject=claimed,
        outcome_state="claimed",
        label="claim",
    )
    run.succeed(
        run.last.effects[0],
        run.events[-1],
        subject=claimed,
        outcome_state="worker_launched",
        label="launch",
    )
    launch_effect = run.effects[-1]

    pack, invocation, result = _ddo4_worker_bundle(issue, plan, launch_effect)
    assert (
        validate_worker_authority_chain(
            result,
            context_pack=pack,
            invocation=invocation,
            effect=launch_effect,
            plan=plan,
        )
        is result
    )

    # Carrier conformance: a second carrier varies every envelope value and
    # still normalizes to the same delivery-domain result and authority chain.
    _pack_b, _invocation_b, other_carrier = _ddo4_worker_bundle(
        issue,
        plan,
        launch_effect,
        result_id="worker-result-v2-4167-b",
        carrier_id="carrier-beta",
        provider_id="provider-beta",
        worker_model_ref="worker-model-beta",
    )
    assert other_carrier.carrier != result.carrier
    assert other_carrier.carrier.session_ref != result.carrier.session_ref
    assert other_carrier.carrier.usage_ref != result.carrier.usage_ref
    assert other_carrier.carrier.provenance_ref != result.carrier.provenance_ref
    assert normalized_worker_delivery_result(
        other_carrier
    ) == normalized_worker_delivery_result(result)
    assert worker_conformance_key(other_carrier) == worker_conformance_key(result)
    assert other_carrier.canonical_bytes() != result.canonical_bytes()

    # A missing envelope field is rejected rather than normalized away.
    payload = result.model_dump(mode="json")
    del payload["carrier"]["usage_ref"]
    with pytest.raises(ValidationError):
        parse_delivery_contract(payload)

    # A cross-chain construction is rejected at every reference in the chain.
    other_issue = _issue(4169, SHA_B)
    other_plan = _ddo4_plan(((other_issue,),))
    foreign_pack, foreign_invocation, foreign_result = _ddo4_worker_bundle(
        issue,
        plan,
        launch_effect,
        result_id="worker-result-v2-foreign",
    )
    with pytest.raises(ValueError, match="does not bind the plan"):
        validate_worker_authority_chain(
            foreign_result,
            context_pack=foreign_pack,
            invocation=foreign_invocation,
            effect=launch_effect,
            plan=other_plan,
        )
    # A result asserting another run cannot ride an honest pack and invocation.
    hijacked = foreign_result.model_dump(mode="json")
    hijacked["run_id"] = "run-other"
    hijacked["result_id"] = "worker-result-v2-hijacked-run"
    with pytest.raises(ValidationError, match="one run, plan, Issue"):
        parse_delivery_contract(hijacked)

    mismatched_pack = WorkerContextPack(
        context_pack_id="pack-mismatched",
        run_id="run-other",
        plan_ref=_ddo4_ref(plan, plan.plan_id),
        effect_ref=_ddo4_ref(launch_effect, launch_effect.effect_id),
        issue=issue,
        base_head_sha=DDO4_BASE_HEAD,
        required_skills=("issue-to-code",),
        verify_targets=("tests/builderops/test_delivery_reducer.py",),
        context_refs=(),
        provenance=_provenance("pack-mismatched"),
    )
    with pytest.raises(ValueError, match="one context pack"):
        validate_worker_authority_chain(
            result,
            context_pack=mismatched_pack,
            invocation=invocation,
            effect=launch_effect,
            plan=plan,
        )

    # An invocation whose bound context-pack hash drifts cannot be built at all.
    with pytest.raises(ValidationError, match="exact context-pack hash"):
        WorkerInvocation(
            invocation_id="bad",
            run_id=DDO4_RUN,
            plan_ref=_ddo4_ref(plan, plan.plan_id),
            effect_ref=_ddo4_ref(launch_effect, launch_effect.effect_id),
            issue=issue,
            base_head_sha=DDO4_BASE_HEAD,
            context_pack_ref=_ddo4_ref(pack, pack.context_pack_id),
            context_pack_hash=SHA_A,
            runtime_target="bounded-worker-runtime",
            idempotency_key="bad",
            input_hash=SHA_A,
            provenance=_provenance("invocation-bad"),
        )

    # Every worker contract round-trips through strict canonical parsing.
    for contract in (pack, invocation, result):
        assert parse_delivery_contract(contract.canonical_bytes()) == contract


def test_worker_runtime_port_is_provider_neutral_and_exhaustive() -> None:
    """The port is exercised behaviorally, not by inspecting its namespace."""

    issue = _issue(4167, SHA_A)
    plan = _ddo4_plan(((issue,),))
    run = _DdoRun(plan, _ddo4_profile())
    claimed = _claimed_authority(issue)
    started = run.start()
    run.succeed(
        started.effects[0],
        run.events[-1],
        subject=claimed,
        outcome_state="claimed",
        label="claim",
    )
    run.succeed(
        run.last.effects[0],
        run.events[-1],
        subject=claimed,
        outcome_state="worker_launched",
        label="launch",
    )
    launch_effect = run.effects[-1]
    _pack, invocation, result = _ddo4_worker_bundle(issue, plan, launch_effect)

    def _observation(
        state: str,
        *,
        result_ref: ContractRef | None = None,
        key: str | None = None,
    ) -> WorkerRuntimeObservation:
        identity = key or invocation.idempotency_key
        return WorkerRuntimeObservation(
            observation_id=f"observation-{state}",
            run_id=DDO4_RUN,
            plan_ref=_ddo4_ref(plan, plan.plan_id),
            effect_ref=_ddo4_ref(launch_effect, launch_effect.effect_id),
            invocation_ref=ContractRef(
                schema_version=invocation.schema_version,
                contract_id=identity,
                content_hash=invocation.content_hash,
            ),
            invocation_idempotency_key=identity,
            runtime_state=state,  # type: ignore[arg-type]
            result_ref=result_ref,
            observed_at=TS,
            provenance=_provenance(f"observation-{state}"),
        )

    class _RecordingPort:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def _answer(self, name: str) -> WorkerRuntimeObservation:
            self.calls.append(name)
            return _observation("running")

        def start(self, invocation: WorkerInvocation) -> WorkerRuntimeObservation:
            return self._answer("start")

        def inspect(self, invocation: WorkerInvocation) -> WorkerRuntimeObservation:
            return self._answer("inspect")

        def heartbeat(
            self, invocation: WorkerInvocation
        ) -> WorkerRuntimeObservation:
            return self._answer("heartbeat")

        def interrupt(
            self, invocation: WorkerInvocation
        ) -> WorkerRuntimeObservation:
            return self._answer("interrupt")

        def reattach(
            self, invocation: WorkerInvocation
        ) -> WorkerRuntimeObservation:
            return self._answer("reattach")

        def await_terminal(
            self, invocation: WorkerInvocation
        ) -> WorkerRuntimeObservation:
            return self._answer("await_terminal")

        def cancel(self, invocation: WorkerInvocation) -> WorkerRuntimeObservation:
            return self._answer("cancel")

    assert set(START_ONCE_OPERATION_BY_STATE) == set(WORKER_RUNTIME_STATES)
    assert set(WORKER_RUNTIME_OPERATIONS) == {
        "start",
        "inspect",
        "heartbeat",
        "interrupt",
        "reattach",
        "await_terminal",
        "cancel",
    }

    # Only not_started may ever start; unknown starts reattach instead.
    port = _RecordingPort()
    resolve_worker_start(port, invocation, _observation("not_started"))
    resolve_worker_start(port, invocation, _observation("starting_unknown"))
    resolve_worker_start(port, invocation, _observation("running"))
    resolve_worker_start(port, invocation, _observation("idle"))
    assert port.calls == ["start", "reattach", "inspect", "inspect"]
    assert port.calls.count("start") == 1

    # A terminal readback returns the recorded result and never launches again.
    terminal_port = _RecordingPort()
    result_ref = _ddo4_ref(result, result.result_id)
    terminal = _observation("terminal", result_ref=result_ref)
    assert resolve_worker_start(terminal_port, invocation, terminal) is terminal
    assert terminal_port.calls == []
    assert terminal.result_ref == result_ref

    # Unreachable and cancelled cannot authorize any start.
    for unstartable in ("unreachable", "cancelled"):
        with pytest.raises(WorkerRuntimeUnknownError):
            resolve_worker_start(
                _RecordingPort(), invocation, _observation(unstartable)
            )

    # An observation for another invocation identity is refused outright.
    with pytest.raises(WorkerRuntimeUnknownError):
        resolve_worker_start(
            _RecordingPort(),
            invocation,
            _observation("not_started", key="builderops.worker-invocation.v1:other"),
        )

    # A non-terminal observation may not smuggle a recorded result, and a
    # terminal one must carry it.
    with pytest.raises(ValidationError, match="terminal runtime observation"):
        _observation("running", result_ref=result_ref)
    with pytest.raises(ValidationError, match="terminal runtime observation"):
        _observation("terminal")


def test_unstructured_worker_output_cannot_advance() -> None:
    """Prose, exit status, and session state have no path into the reducer."""

    issue = _issue(4167, SHA_A)
    plan = _ddo4_plan(((issue,),))
    run = _DdoRun(plan, _ddo4_profile())
    claimed = _claimed_authority(issue)
    started = run.start()
    run.succeed(
        started.effects[0],
        run.events[-1],
        subject=claimed,
        outcome_state="claimed",
        label="claim",
    )
    run.succeed(
        run.last.effects[0],
        run.events[-1],
        subject=claimed,
        outcome_state="worker_launched",
        label="launch",
    )
    launch_effect = run.effects[-1]
    pack, invocation, result = _ddo4_worker_bundle(issue, plan, launch_effect)

    # An admitted event cannot be forged: only admit_reducer_event may build one.
    with pytest.raises(ReducerAdmissionError, match="admit_reducer_event"):
        AdmittedEvent(
            event=run.events[-1],
            signal="worker_result_recorded",
            effect=None,
            worker_result=result,
            review_result=None,
            subject_issue=issue,
        )

    worker_event = _ddo4_event(
        plan,
        sequence=run.next_sequence(),
        event_type="worker_result_recorded",
        subject=claimed,
        result_ref=_ddo4_ref(
            result.delivery_result, result.delivery_result.result_id
        ),
        correlation_id="event-worker-unstructured",
    )

    # The delivery-domain bytes alone are not admissible: the carrier-neutral
    # envelope and its full authority chain are required.
    run.worker_results.append(result.delivery_result)
    with pytest.raises(ReducerAdmissionError, match="worker result envelope"):
        run.admit(worker_event)
    with pytest.raises(ReducerAdmissionError, match="context pack"):
        run.admit(worker_event, worker_result=result)

    # Two carriers whose prose, session, usage, and provenance envelopes differ
    # produce exactly the same reducer decision, so no envelope value is
    # delivery authority.
    admitted_a = run.admit(
        worker_event,
        worker_result=result,
        context_pack=pack,
        invocation=invocation,
        launch_effect=launch_effect,
    )
    _pack_b, _invocation_b, result_b = _ddo4_worker_bundle(
        issue,
        plan,
        launch_effect,
        result_id="worker-result-v2-prose",
        carrier_id="carrier-prose",
        provider_id="provider-prose",
        worker_model_ref="worker-model-prose",
    )
    admitted_b = run.admit(
        worker_event,
        worker_result=result_b,
        context_pack=pack,
        invocation=invocation,
        launch_effect=launch_effect,
    )
    reduction_a = reduce_delivery_run(run.state, admitted_a)
    reduction_b = reduce_delivery_run(run.state, admitted_b)
    assert reduction_a.state == reduction_b.state
    assert reduction_a.effects == reduction_b.effects

    # A non-completed worker result blocks instead of advancing to CI.
    _pack_f, _invocation_f, failed_result = _ddo4_worker_bundle(
        issue,
        plan,
        launch_effect,
        result_id="worker-result-v2-failed",
        domain_result_id="worker-result-failed",
        status="failed",
    )
    run.worker_results.append(failed_result.delivery_result)
    failed_event = _ddo4_event(
        plan,
        sequence=run.next_sequence(),
        event_type="worker_result_recorded",
        subject=claimed,
        result_ref=_ddo4_ref(
            failed_result.delivery_result,
            failed_result.delivery_result.result_id,
        ),
        correlation_id="event-worker-failed",
    )
    blocked = reduce_delivery_run(
        run.state,
        run.admit(
            failed_event,
            worker_result=failed_result,
            context_pack=pack,
            invocation=invocation,
            launch_effect=launch_effect,
        ),
    )
    assert blocked.state.issue_state(issue.scope_key).phase == "blocked"
    assert not blocked.effects


def test_lifecycle_controls_are_typed_fenced_and_effect_safe() -> None:
    """Pause, resume, cancel, and supersede never claim to undo a committed effect."""

    issue = _issue(4167, SHA_A)
    run, _worker_event, _launch = _drive_to_awaiting_review(issue)
    authorized = _actor("owner:RasmusTho")
    unauthorized = ActorIdentity(
        actor_type="service",
        actor_id="service:unbound",
        authority_scope="some/other-repo",
    )

    def _command(
        name: str,
        *,
        command_id: str,
        version: int | None = None,
        issued_by: ActorIdentity | None = None,
        superseding: ContractRef | None = None,
    ) -> LifecycleCommand:
        return LifecycleCommand(
            command=name,  # type: ignore[arg-type]
            command_id=command_id,
            run_id=DDO4_RUN,
            expected_run_version=(
                run.state.version if version is None else version
            ),
            issued_by=issued_by or authorized,
            issued_at=TS,
            superseding_initiation_ref=superseding,
        )

    # Authentication is an authority reference, never a self-asserted flag.
    denied = reduce_lifecycle_command(
        run.state, _command("pause", command_id="cmd-denied", issued_by=unauthorized)
    )
    assert denied.refusal == "unauthorized_command"
    assert denied.state == run.state

    # Version fencing rejects a stale command outright.
    stale = reduce_lifecycle_command(
        run.state, _command("pause", command_id="cmd-stale", version=0)
    )
    assert stale.refusal == "stale_run_version"

    paused = reduce_lifecycle_command(
        run.state, _command("pause", command_id="cmd-pause")
    )
    assert paused.state.lifecycle == "paused"
    assert not paused.effects
    # The paused phase is preserved verbatim.
    assert paused.state.issue_state(issue.scope_key).phase == "awaiting_review"

    # Pause is idempotent by command identity.
    repeat = reduce_lifecycle_command(
        paused.state, _command("pause", command_id="cmd-pause")
    )
    assert repeat.refusal == "duplicate_command"
    assert repeat.state == paused.state

    # A paused run admits no reducer event at all, and the proof must use a
    # genuinely FRESH event: a duplicate would be refused earlier and would say
    # nothing about the pause gate. Without it a paused run would accept this
    # verdict and authorize a merge.
    paused_verdict = _ddo4_review(
        issue,
        run.plan,
        result_id="review-while-paused",
        disposition="accept",
    )
    run.review_results.append(paused_verdict)
    paused_event = _ddo4_event(
        run.plan,
        sequence=run.next_sequence(),
        event_type="review_result_recorded",
        subject=_claimed_authority(issue),
        result_ref=_ddo4_ref(paused_verdict, paused_verdict.result_id),
        correlation_id="event-review-while-paused",
    )
    paused_admitted = run.admit(paused_event, review_result=paused_verdict)
    assert paused_event.event_id not in paused.state.seen_event_ids
    stalled = reduce_delivery_run(paused.state, paused_admitted)
    assert stalled.refusal == "paused_run"
    assert stalled.state == paused.state
    assert not stalled.effects
    # The identical event on the active run does authorize the merge, so the
    # pause gate is the only thing that stopped it.
    unpaused = reduce_delivery_run(run.state, paused_admitted)
    assert [item.effect_class for item in unpaused.effects] == [
        "merge_pull_request"
    ]
    run.review_results.pop()

    resumed = reduce_lifecycle_command(
        paused.state,
        LifecycleCommand(
            command="resume",
            command_id="cmd-resume",
            run_id=DDO4_RUN,
            expected_run_version=paused.state.version,
            issued_by=authorized,
            issued_at=TS,
        ),
    )
    assert resumed.state.lifecycle == "active"
    # Resume preserves the paused phase and re-proposes only effects that are
    # still unresolved. Here every authorized effect already succeeded and the
    # run waits on an external structured verdict, so resume emits nothing
    # rather than duplicating a committed request_review.
    assert resumed.effects == ()
    assert resumed.state.issue_state(issue.scope_key).phase == "awaiting_review"

    # An effect that really is still in flight is replayed exactly as it was
    # authorized, so it collapses to one logical effect.
    pending_run = _DdoRun(_ddo4_plan(((issue,),)), _ddo4_profile())
    pending_started = pending_run.start()
    authorized_claim = pending_run.materialize(
        pending_started.effects[0], pending_run.events[-1]
    )
    pending_paused = reduce_lifecycle_command(
        pending_run.state,
        _command_for(
            pending_run.state, "pause", command_id="cmd-pause-pending"
        ),
    )
    pending_resumed = reduce_lifecycle_command(
        pending_paused.state,
        _command_for(
            pending_paused.state, "resume", command_id="cmd-resume-pending"
        ),
    )
    assert [item.effect_class for item in pending_resumed.effects] == [
        "claim_issue"
    ]
    replayed = pending_resumed.effects[0]
    assert (
        proposal_effect_identity(
            pending_resumed.state, replayed
        ).idempotency_key
        == authorized_claim.idempotency_key
    )

    # A relabelled Issue does not split one authorized effect into two
    # identities: resume replays the authorization, not the current authority.
    relabelled_state = dataclass_replace(
        pending_paused.state,
        issues=tuple(
            dataclass_replace(
                item,
                current_authority=_authority(
                    issue, labels=("agent:ready", "prio:high", "type:task")
                ),
            )
            for item in pending_paused.state.issues
        ),
    )
    relabelled_resume = reduce_lifecycle_command(
        relabelled_state,
        _command_for(
            relabelled_state, "resume", command_id="cmd-resume-relabelled"
        ),
    )
    assert (
        proposal_effect_identity(
            relabelled_resume.state, relabelled_resume.effects[0]
        ).idempotency_key
        == authorized_claim.idempotency_key
    )

    # Resume never re-proposes a launch that is already in flight: a re-derived
    # launch would mint a second worker start-once identity for one Issue.
    launching_run, _worker_event, _launch = _drive_to_launching(issue)
    assert (
        launching_run.state.issue_state(issue.scope_key).phase == "launching"
    )
    launching_paused = reduce_lifecycle_command(
        launching_run.state,
        _command_for(
            launching_run.state, "pause", command_id="cmd-pause-launching"
        ),
    )
    launching_resumed = reduce_lifecycle_command(
        launching_paused.state,
        _command_for(
            launching_paused.state, "resume", command_id="cmd-resume-launching"
        ),
    )
    assert launching_resumed.effects == ()
    assert (
        launching_resumed.state.issue_state(issue.scope_key).phase == "launching"
    )

    # Cancellation records committed effects as obligations and emits nothing.
    committed = run.state.issue_state(issue.scope_key).unreconciled_effects
    assert {item.effect_class for item in committed} >= {
        "claim_issue",
        "launch_worker",
        "await_ci",
    }
    cancelled = reduce_lifecycle_command(
        run.state, _command("cancel", command_id="cmd-cancel")
    )
    assert cancelled.state.lifecycle == "cancelled"
    assert cancelled.effects == ()
    assert COMPENSATING_EFFECT_CLASSES == frozenset()
    assert cancelled.obligations == outstanding_effect_obligations(run.state)
    assert {item.effect_class for item in cancelled.obligations} >= {
        "claim_issue",
        "launch_worker",
        "await_ci",
    }
    for obligation in cancelled.obligations:
        assert obligation.reconciliation_owner == "builderops_reconciliation"
        assert obligation.effect_idempotency_key in {
            effect.idempotency_key for effect in run.effects
        }
        assert obligation.outcome_keys

    # A cancelled run is terminal for every further event and command.
    assert (
        reduce_delivery_run(
            cancelled.state, run.admit(run.events[-1], effect=run.effects[-1])
        ).refusal
        == "terminal_run"
    )
    assert (
        reduce_lifecycle_command(
            cancelled.state,
            _command(
                "cancel",
                command_id="cmd-cancel-2",
                version=cancelled.state.version,
            ),
        ).refusal
        == "terminal_run"
    )

    # Supersession requires the superseding initiation identity.
    assert (
        reduce_lifecycle_command(
            run.state, _command("supersede", command_id="cmd-supersede-bad")
        ).refusal
        == "unauthorized_command"
    )
    superseding_ref = ContractRef(
        schema_version="builderops.delivery-initiation.v1",
        contract_id="init-4167-next",
        content_hash=SHA_B,
    )
    superseded = reduce_lifecycle_command(
        run.state,
        _command(
            "supersede",
            command_id="cmd-supersede",
            superseding=superseding_ref,
        ),
    )
    assert superseded.state.lifecycle == "superseded"
    assert superseded.state.superseding_initiation_ref == superseding_ref
    assert superseded.effects == ()
    assert superseded.obligations == cancelled.obligations


def test_authority_ambiguity_and_system_blocks_are_distinct() -> None:
    """An owner decision is never collapsed into a missing-evidence block."""

    issue = _issue(4167, SHA_A)

    def _exception_reduction(kind: str, code: str) -> Reduction:
        run, _worker_event, _launch = _drive_to_awaiting_review(issue)
        event = _ddo4_event(
            run.plan,
            sequence=run.next_sequence(),
            event_type="exception_recorded",
            exception=DeliveryException(
                kind=kind,  # type: ignore[arg-type]
                code=code,
                message="A typed delivery exception was recorded.",
                retryable=False,
                evidence_refs=(f"exception:{code}",),
            ),
            correlation_id=f"event-exception-{code}",
        )
        return run.apply(run.admit(event))

    owner = _exception_reduction("authority_conflict", "authority-conflict")
    assert owner.state.issue_state(issue.scope_key).phase == "owner_decision"

    for kind, code in (
        ("dependency_blocked", "dependency-blocked"),
        ("external_state_unknown", "external-state-unknown"),
    ):
        system = _exception_reduction(kind, code)
        assert (
            system.state.issue_state(issue.scope_key).phase == "system_blocked"
        ), kind

    plain = _exception_reduction("execution_failed", "execution-failed")
    assert plain.state.issue_state(issue.scope_key).phase == "blocked"

    # Drift in the Issue contract itself is an owner decision, not a block.
    run, _worker_event, _launch = _drive_to_awaiting_review(issue)
    changed = AuthoritySnapshot(
        authority_type="github_issue",
        authority_id=issue.authority_id,
        content_hash=SHA_F,
        observed_state="open",
        observed_labels=("agent:in-progress", "type:task"),
        observed_at=TS,
    )
    change_event = _ddo4_event(
        run.plan,
        sequence=run.next_sequence(),
        event_type="authority_changed",
        subject=changed,
        correlation_id="event-authority-drift",
    )
    drift = run.apply(run.admit(change_event))
    drifted_state = drift.state.issue_state(issue.scope_key)
    assert drifted_state.phase == "owner_decision"
    assert drifted_state.blocked_reason == "authority_contract_drift"
    assert not drift.effects

    # Contract drift is an owner decision, never a system block, and never a
    # silent continuation on the drifted authority.
    assert drifted_state.current_authority != changed

    run, _worker_event, _launch = _drive_to_awaiting_review(issue)

    # An in-scope authority change that is genuinely new advances the resolved
    # authority without terminating the run.
    relabelled = _authority(
        issue, labels=("agent:in-progress", "prio:high", "type:task")
    )
    relabel_event = _ddo4_event(
        run.plan,
        sequence=run.next_sequence(),
        event_type="authority_changed",
        subject=relabelled,
        correlation_id="event-authority-relabelled",
    )
    advanced = run.apply(run.admit(relabel_event))
    assert advanced.refusal is None
    issue_state = advanced.state.issue_state(issue.scope_key)
    assert issue_state.phase == "awaiting_review"
    assert issue_state.current_authority == relabelled

    # The three outcomes are genuinely distinct reducer phases.
    assert len({"owner_decision", "system_blocked", "blocked"}) == 3


def test_acceptance_profile_is_canonical_and_evidence_bound() -> None:
    """Terminality follows the bound profile, not the shape of the last step."""

    profile = _ddo4_profile()
    assert profile.schema_version == DELIVERY_ACCEPTANCE_PROFILE_VERSION
    assert parse_delivery_contract(profile.canonical_bytes()) == profile
    with pytest.raises(ValidationError, match="canonical sorted order"):
        DeliveryAcceptanceProfile(
            profile_id="unsorted",
            required_evidence=("pull_request_merged", "issue_closed"),
            provenance=_provenance("acceptance-unsorted"),
        )
    with pytest.raises(ValidationError, match="explicit delivery evidence"):
        DeliveryAcceptanceProfile(
            profile_id="empty",
            required_evidence=(),
            provenance=_provenance("acceptance-empty"),
        )

    issue = _issue(4167, SHA_A)
    run = _drive_to_delivered(issue)
    profile_ref = run.state.acceptance_profile_ref
    assert profile_ref.content_hash == run.state.acceptance_profile_hash
    assert profile_ref.contract_id == profile.profile_id

    # The binding survives every transition and the plan bytes never change.
    assert run.state.plan_ref == _ddo4_ref(run.plan, run.plan.plan_id)
    assert run.state.acceptance_profile_ref == profile_ref
    for effect in run.effects:
        assert effect.plan_ref == run.state.plan_ref

    satisfied, unmet = resolve_terminal_delivery(run.state, issue, profile)
    assert satisfied and unmet == ()

    # Acceptance evidence is only ever derived from typed lower-level facts.
    observed = run.state.issue_state(issue.scope_key).acceptance_evidence
    assert set(observed) == {
        "issue_closed",
        "pull_request_merged",
        "required_checks_green",
        "review_accepted",
    }
    assert set(ACCEPTANCE_EVIDENCE_BY_EFFECT_OUTCOME.values()) >= {
        "issue_closed",
        "pull_request_merged",
        "required_checks_green",
    }

    # A stronger profile governs the same sequence of lower-level facts: the
    # identical run stops short of delivered instead of recording a clean
    # receipt, so terminality is not hard-coded to the closing transition.
    stronger = _ddo4_profile(
        (
            "issue_closed",
            "known_defect_recorded",
            "pull_request_merged",
            "required_checks_green",
            "review_accepted",
        )
    )
    assert stronger.content_hash != profile.content_hash
    stronger_run = _drive_to_delivered(issue, profile=stronger)
    stronger_state = stronger_run.state.issue_state(issue.scope_key)
    assert stronger_state.phase == "blocked"
    assert stronger_state.blocked_reason == (
        "acceptance_evidence_unmet:known_defect_recorded"
    )
    satisfied_strong, unmet_strong = resolve_terminal_delivery(
        stronger_run.state, issue, stronger
    )
    assert not satisfied_strong
    assert unmet_strong == ("known_defect_recorded",)

    # The two runs executed the same effects; only the bound profile differed.
    assert [item.effect_class for item in stronger_run.effects] == [
        item.effect_class for item in run.effects
    ]

    # A profile that does not match the immutable binding cannot resolve at all.
    with pytest.raises(ValueError, match="immutable run binding"):
        resolve_terminal_delivery(run.state, issue, stronger)


def test_delivery_receipt_v2_is_additive_and_version_bound() -> None:
    """v2 references v1 bytes; it never re-encodes or reinterprets them."""

    issue = _issue(4165, SHA_A)
    initiation = _initiation(issue)
    plan = _plan(issue, initiation)
    worker = _worker_result(issue, plan)
    review = _review_result(issue, plan)
    receipt_v1 = _receipt(issue, initiation, plan, worker, review)
    profile = _ddo4_profile()

    before = parse_delivery_contract(receipt_v1.canonical_bytes())
    receipt_v2 = DeliveryReceiptV2(
        receipt_id="delivery-receipt-4165-v2",
        run_id=receipt_v1.run_id,
        delivery_receipt_ref=_ddo4_ref(receipt_v1, receipt_v1.receipt_id),
        acceptance_profile_ref=_ddo4_ref(profile, profile.profile_id),
        acceptance_profile_hash=profile.content_hash,
        satisfied_evidence=(
            "issue_closed",
            "pull_request_merged",
            "required_checks_green",
            "review_accepted",
        ),
        terminal_outcome="delivered",
        provenance=_provenance("delivery-receipt-4165-v2"),
    )
    after = parse_delivery_contract(receipt_v1.canonical_bytes())
    assert before == after == receipt_v1
    assert receipt_v1.schema_version == "builderops.delivery-receipt.v1"
    assert receipt_v2.schema_version == "builderops.delivery-receipt.v2"
    assert parse_delivery_contract(receipt_v2.canonical_bytes()) == receipt_v2
    assert (
        validate_delivery_receipt_v2_evidence(
            receipt_v2, receipt=receipt_v1, acceptance_profile=profile
        )
        is receipt_v2
    )

    # v2 repeats the identical acceptance reference and hash.
    assert receipt_v2.acceptance_profile_hash == profile.content_hash
    with pytest.raises(ValidationError, match="exact acceptance profile hash"):
        DeliveryReceiptV2(
            receipt_id="drifted",
            run_id=receipt_v1.run_id,
            delivery_receipt_ref=_ddo4_ref(receipt_v1, receipt_v1.receipt_id),
            acceptance_profile_ref=_ddo4_ref(profile, profile.profile_id),
            acceptance_profile_hash=SHA_B,
            satisfied_evidence=("issue_closed",),
            terminal_outcome="delivered",
            provenance=_provenance("drifted"),
        )

    # A delivered v2 receipt cannot claim evidence the profile does not have.
    thin = DeliveryReceiptV2(
        receipt_id="thin",
        run_id=receipt_v1.run_id,
        delivery_receipt_ref=_ddo4_ref(receipt_v1, receipt_v1.receipt_id),
        acceptance_profile_ref=_ddo4_ref(profile, profile.profile_id),
        acceptance_profile_hash=profile.content_hash,
        satisfied_evidence=("issue_closed",),
        terminal_outcome="delivered",
        provenance=_provenance("thin"),
    )
    with pytest.raises(ValueError, match="every required acceptance evidence"):
        validate_delivery_receipt_v2_evidence(
            thin, receipt=receipt_v1, acceptance_profile=profile
        )

    # Supersession identities are recorded together and only when superseded.
    with pytest.raises(ValidationError, match="both supersession identities"):
        DeliveryReceiptV2(
            receipt_id="half-superseded",
            run_id=receipt_v1.run_id,
            delivery_receipt_ref=_ddo4_ref(receipt_v1, receipt_v1.receipt_id),
            acceptance_profile_ref=_ddo4_ref(profile, profile.profile_id),
            acceptance_profile_hash=profile.content_hash,
            satisfied_evidence=("issue_closed",),
            terminal_outcome="superseded",
            superseded_run_id=receipt_v1.run_id,
            provenance=_provenance("half-superseded"),
        )

    # A delivered receipt cannot hide unreconciled committed effects.
    obligation = OutstandingEffectObligation(
        effect_class="claim_issue",
        effect_idempotency_key="builderops.delivery-effect.v1:" + SHA_A,
        outcome_keys=(f"{issue.authority_id}#claimed",),
        last_observed_outcome_state="claimed",
    )
    with pytest.raises(ValidationError, match="unreconciled effect obligations"):
        DeliveryReceiptV2(
            receipt_id="dirty-delivered",
            run_id=receipt_v1.run_id,
            delivery_receipt_ref=_ddo4_ref(receipt_v1, receipt_v1.receipt_id),
            acceptance_profile_ref=_ddo4_ref(profile, profile.profile_id),
            acceptance_profile_hash=profile.content_hash,
            satisfied_evidence=(
                "issue_closed",
                "pull_request_merged",
                "required_checks_green",
                "review_accepted",
            ),
            terminal_outcome="delivered",
            outstanding_effect_obligations=(obligation,),
            provenance=_provenance("dirty-delivered"),
        )

    # v2 cannot contradict the delivered v1 terminal outcome.
    contradicting = DeliveryReceiptV2(
        receipt_id="contradicting",
        run_id=receipt_v1.run_id,
        delivery_receipt_ref=_ddo4_ref(receipt_v1, receipt_v1.receipt_id),
        acceptance_profile_ref=_ddo4_ref(profile, profile.profile_id),
        acceptance_profile_hash=profile.content_hash,
        satisfied_evidence=("issue_closed",),
        terminal_outcome="blocked",
        provenance=_provenance("contradicting"),
    )
    with pytest.raises(ValueError, match="agree with delivered v1 bytes"):
        validate_delivery_receipt_v2_evidence(
            contradicting, receipt=receipt_v1, acceptance_profile=profile
        )


# ---------------------------------------------------------------------------
# Regressions for the four protected authority-integrity findings.
# ---------------------------------------------------------------------------


def test_replayed_worker_sidecars_require_strict_canonical_revalidation() -> None:
    """Finding 1: a replayed sidecar is untrusted until it re-parses exactly."""

    issue = _issue(4167, SHA_A)
    plan = _ddo4_plan(((issue,),))
    run = _DdoRun(plan, _ddo4_profile())
    claimed = _claimed_authority(issue)
    started = run.start()
    run.succeed(
        started.effects[0],
        run.events[-1],
        subject=claimed,
        outcome_state="claimed",
        label="claim",
    )
    run.succeed(
        run.last.effects[0],
        run.events[-1],
        subject=claimed,
        outcome_state="worker_launched",
        label="launch",
    )
    launch_effect = run.effects[-1]
    pack, invocation, result = _ddo4_worker_bundle(issue, plan, launch_effect)
    pack_ref = _ddo4_ref(pack, pack.context_pack_id)
    invocation_ref = _ddo4_ref(invocation, invocation.invocation_id)

    # The honest replay resolves.
    assert (
        replay_delivery_sidecar(pack.canonical_bytes(), expected_ref=pack_ref)
        == pack
    )
    assert (
        replay_delivery_sidecar(
            invocation.canonical_bytes(), expected_ref=invocation_ref
        )
        == invocation
    )
    observation = WorkerRuntimeObservation(
        observation_id="observation-replay",
        run_id=DDO4_RUN,
        plan_ref=_ddo4_ref(plan, plan.plan_id),
        effect_ref=_ddo4_ref(launch_effect, launch_effect.effect_id),
        invocation_ref=invocation_ref,
        invocation_idempotency_key=invocation.idempotency_key,
        runtime_state="terminal",
        result_ref=_ddo4_ref(result, result.result_id),
        observed_at=TS,
        provenance=_provenance("observation-replay"),
    )
    assert (
        replay_delivery_sidecar(
            observation.canonical_bytes(),
            expected_ref=_ddo4_ref(observation, observation.observation_id),
        )
        == observation
    )

    # A mutated sidecar no longer matches the reference that claimed it.
    mutated = pack.model_dump(mode="json")
    mutated["verify_targets"] = ["tests/does_not_prove_anything.py"]
    with pytest.raises(ReducerAdmissionError, match="content hash"):
        replay_delivery_sidecar(mutated, expected_ref=pack_ref)

    # An identity swap is refused even when the hash reference is updated.
    renamed = pack.model_dump(mode="json")
    renamed["context_pack_id"] = "pack-substituted"
    renamed_pack = parse_delivery_contract(renamed)
    with pytest.raises(ReducerAdmissionError, match="identity"):
        replay_delivery_sidecar(
            renamed,
            expected_ref=ContractRef(
                schema_version=pack_ref.schema_version,
                contract_id=pack_ref.contract_id,
                content_hash=renamed_pack.content_hash,
            ),
        )

    # A different contract family cannot be replayed under this reference.
    with pytest.raises(ReducerAdmissionError, match="schema version"):
        replay_delivery_sidecar(
            invocation.canonical_bytes(), expected_ref=pack_ref
        )

    # Unknown fields, duplicate keys, and non-canonical bytes are all refused.
    extra = pack.model_dump(mode="json")
    extra["worker_notes"] = "the worker said it was fine"
    with pytest.raises(ValidationError):
        replay_delivery_sidecar(extra, expected_ref=pack_ref)
    duplicated = (
        '{"schema_version": "builderops.worker-context-pack.v1", '
        '"run_id": "a", "run_id": "b"}'
    )
    with pytest.raises(ValueError, match="duplicate"):
        replay_delivery_sidecar(duplicated, expected_ref=pack_ref)

    # Admission itself re-parses in-memory contracts, so a non-canonical object
    # cannot skip the strict path.
    worker_event = _ddo4_event(
        plan,
        sequence=run.next_sequence(),
        event_type="worker_result_recorded",
        subject=claimed,
        result_ref=_ddo4_ref(
            result.delivery_result, result.delivery_result.result_id
        ),
        correlation_id="event-worker-replay",
    )
    run.worker_results.append(result.delivery_result)
    admitted = run.admit(
        worker_event,
        worker_result=result,
        context_pack=pack,
        invocation=invocation,
        launch_effect=launch_effect,
    )
    assert admitted.worker_result == result
    assert admitted.worker_result is not result


def test_repair_cannot_change_the_reducer_authorized_pull_request() -> None:
    """Finding 2: the authorized PR identity binds once and is never rewritable."""

    issue = _issue(4167, SHA_A)
    plan = _ddo4_plan(((issue,),))
    run = _DdoRun(plan, _ddo4_profile())
    claimed = _claimed_authority(issue)
    started = run.start()
    run.succeed(
        started.effects[0],
        run.events[-1],
        subject=claimed,
        outcome_state="claimed",
        label="claim",
    )
    run.succeed(
        run.last.effects[0],
        run.events[-1],
        subject=claimed,
        outcome_state="worker_launched",
        label="launch",
    )
    launch_effect = run.effects[-1]
    pack, invocation, result = _ddo4_worker_bundle(issue, plan, launch_effect)
    run.worker_results.append(result.delivery_result)
    first_event = _ddo4_event(
        plan,
        sequence=run.next_sequence(),
        event_type="worker_result_recorded",
        subject=claimed,
        result_ref=_ddo4_ref(
            result.delivery_result, result.delivery_result.result_id
        ),
        correlation_id="event-worker-first",
    )
    first_admitted = run.admit(
        first_event,
        worker_result=result,
        context_pack=pack,
        invocation=invocation,
        launch_effect=launch_effect,
    )

    # A run state that has not recorded an authorized launch fails closed rather
    # than accepting a worker result on trust.
    unbound = dataclass_replace(
        run.state,
        issues=tuple(
            dataclass_replace(item, authorized_invocation_effect_key=None)
            for item in run.state.issues
        ),
    )
    assert (
        reduce_delivery_run(unbound, first_admitted).refusal
        == "illegal_transition"
    )

    first = run.apply(first_admitted)
    bound = run.state.issue_state(issue.scope_key)
    assert bound.authorized_pull_request == DDO4_PR
    assert bound.authorized_head_sha == DDO4_HEAD

    # The fence itself: with the pull request already bound, a worker result for
    # a different pull request is refused rather than allowed to move the run.
    _p, _i, hijacked = _ddo4_worker_bundle(
        issue,
        plan,
        launch_effect,
        result_id="worker-result-v2-hijack",
        domain_result_id="worker-result-hijack",
        head=DDO4_REPAIRED_HEAD,
        pull_request_number=DDO4_PR + 7,
    )
    run.worker_results.append(hijacked.delivery_result)
    hijack_event = _ddo4_event(
        plan,
        sequence=run.next_sequence(),
        event_type="worker_result_recorded",
        subject=claimed,
        result_ref=_ddo4_ref(
            hijacked.delivery_result, hijacked.delivery_result.result_id
        ),
        correlation_id="event-worker-hijack",
    )
    hijack_admitted = run.admit(
        hijack_event,
        worker_result=hijacked,
        context_pack=pack,
        invocation=invocation,
        launch_effect=launch_effect,
    )
    # Re-enter working with the pull request and launch already authorized, which
    # is the exact state any later result - repaired or replayed - arrives into.
    working_again = dataclass_replace(
        run.state,
        issues=tuple(
            dataclass_replace(item, phase="working") for item in run.state.issues
        ),
    )
    hijack = reduce_delivery_run(working_again, hijack_admitted)
    assert hijack.refusal == "pull_request_identity_conflict"
    assert hijack.state == working_again
    assert not hijack.effects
    run.worker_results.pop()

    # A red required check routes to the typed terminal repair deferral. The
    # autonomous retry loop needs a durable, replayable effect and invocation
    # identity, which is DDO-05 durable effect binding and Out of Scope here, so
    # this slice fails closed instead of starting a second worker.
    deferred = run.fail(
        first.effects[0], run.events[-1], subject=claimed, label="await-ci"
    )
    repairing = deferred.state.issue_state(issue.scope_key)
    assert repairing.phase == "repairing"
    assert repairing.blocked_reason == "ci_failed_repair_deferred"
    assert not deferred.effects
    # Head-bound acceptance evidence is invalidated by the failure.
    assert "required_checks_green" not in repairing.acceptance_evidence
    # The deferral is terminal, so no signal can restart a worker from it.
    assert "repairing" in TERMINAL_PHASES
    for signal in REDUCER_SIGNALS:
        assert not REDUCER_TRANSITION_MATRIX[("repairing", signal)].legal
    # The failed await_ci is still an obligation-free resolved entry: a truthful
    # failure proved the guarded authority never moved.
    failed_entry = next(
        entry
        for entry in repairing.effect_ledger
        if entry.effect_class == "await_ci"
    )
    assert failed_entry.outcome_state == "failed"
    assert failed_entry.is_resolved_uncommitted


def test_worktree_preparation_follows_the_full_worker_authority_chain() -> None:
    """Finding 3: no side effect happens before the chain is fully resolved."""

    issue = _issue(4167, SHA_A)
    plan = _ddo4_plan(((issue,),))
    run = _DdoRun(plan, _ddo4_profile())
    claimed = _claimed_authority(issue)
    started = run.start()
    run.succeed(
        started.effects[0],
        run.events[-1],
        subject=claimed,
        outcome_state="claimed",
        label="claim",
    )
    launch_proposal = run.last.effects[0]
    launch_effect = run.materialize(launch_proposal, run.events[-1])
    pack, invocation, _result = _ddo4_worker_bundle(issue, plan, launch_effect)
    pack_ref = _ddo4_ref(pack, pack.context_pack_id)
    invocation_ref = _ddo4_ref(invocation, invocation.invocation_id)

    # The reducer must have authorized a launch before any preparation runs.
    launching_state = run.state

    class _RecordingWorktree:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def register(self, *, worktree_path: str, owner: str) -> tuple[str, ...]:
            self.calls.append((worktree_path, owner))
            return ("python3", "scripts/agent_worktree.py", "register")

    def _prepare(
        adapter: _RecordingWorktree,
        *,
        raw_pack: object = None,
        raw_invocation: object = None,
        state: DeliveryRunState | None = None,
        effect: ReducerEffect | None = None,
        target_issue: IssueScope | None = None,
        pack_ref_override: ContractRef | None = None,
    ):
        return prepare_worker_execution(
            raw_context_pack=raw_pack
            if raw_pack is not None
            else pack.canonical_bytes(),
            raw_invocation=raw_invocation
            if raw_invocation is not None
            else invocation.canonical_bytes(),
            context_pack_ref=pack_ref_override or pack_ref,
            invocation_ref=invocation_ref,
            launch_effect=effect or launch_effect,
            plan=plan,
            state=state or launching_state,
            issue=target_issue or issue,
            worktree_path="/tmp/worktree-4167",
            owner_session_id="session-4167",
            worktree_adapter=adapter,
        )

    happy = _RecordingWorktree()
    prepared = _prepare(happy)
    assert happy.calls == [("/tmp/worktree-4167", "session-4167")]
    assert prepared.trace == (
        "context_pack_revalidated",
        "invocation_revalidated",
        "authority_chain_resolved",
        "reducer_authorization_resolved",
        "worktree_registered",
    )
    # The side effect is strictly last.
    assert prepared.trace[-1] == "worktree_registered"
    assert "worktree_registered" not in prepared.trace[:-1]

    # A mutated context pack stops before the worktree is touched.
    mutated = pack.model_dump(mode="json")
    mutated["required_skills"] = ["not-the-authorized-skill"]
    tampered = _RecordingWorktree()
    with pytest.raises(ReducerAdmissionError):
        _prepare(tampered, raw_pack=mutated)
    assert tampered.calls == []

    # An invocation that resolves a different context pack stops as well.
    other_pack = WorkerContextPack(
        context_pack_id="pack-other",
        run_id=DDO4_RUN,
        plan_ref=_ddo4_ref(plan, plan.plan_id),
        effect_ref=_ddo4_ref(launch_effect, launch_effect.effect_id),
        issue=issue,
        base_head_sha=DDO4_BASE_HEAD,
        required_skills=("issue-to-code",),
        verify_targets=("tests/builderops/test_other.py",),
        context_refs=(),
        provenance=_provenance("pack-other"),
    )
    crossed = _RecordingWorktree()
    with pytest.raises(
        ReducerAdmissionError, match="does not resolve this context pack"
    ):
        _prepare(
            crossed,
            raw_pack=other_pack.canonical_bytes(),
            pack_ref_override=_ddo4_ref(other_pack, other_pack.context_pack_id),
        )
    assert crossed.calls == []

    # A sidecar whose bytes drifted from the reference stops even earlier.
    drifted = _RecordingWorktree()
    with pytest.raises(ReducerAdmissionError, match="content hash"):
        _prepare(drifted, raw_pack=other_pack.canonical_bytes())
    assert drifted.calls == []

    # A run that has not authorized a launch cannot prepare a worktree.
    unauthorized = _RecordingWorktree()
    fresh_state = _ddo4_state(plan, _ddo4_profile())
    with pytest.raises(ReducerAdmissionError, match="has not authorized"):
        _prepare(unauthorized, state=fresh_state)
    assert unauthorized.calls == []

    # The phase alone is not authorization. With the ledgered launch removed,
    # the identical effect is refused, so a foreign or replayed launch cannot
    # register a worktree or mint a second worker start-once identity.
    unledgered_state = dataclass_replace(
        launching_state,
        issues=tuple(
            dataclass_replace(
                item,
                effect_ledger=tuple(
                    entry
                    for entry in item.effect_ledger
                    if entry.effect_class != "launch_worker"
                ),
            )
            for item in launching_state.issues
        ),
    )
    unledgered = _RecordingWorktree()
    with pytest.raises(ReducerAdmissionError, match="reducer authorized"):
        _prepare(unledgered, state=unledgered_state)
    assert unledgered.calls == []

    # A launch the reducer already saw acknowledged is likewise not preparable.
    resolved_state = dataclass_replace(
        launching_state,
        issues=tuple(
            dataclass_replace(
                item,
                effect_ledger=tuple(
                    dataclass_replace(entry, outcome_state="worker_launched")
                    if entry.effect_class == "launch_worker"
                    else entry
                    for entry in item.effect_ledger
                ),
            )
            for item in launching_state.issues
        ),
    )
    replayed = _RecordingWorktree()
    with pytest.raises(ReducerAdmissionError, match="reducer authorized"):
        _prepare(replayed, state=resolved_state)
    assert replayed.calls == []

    # A non-launch effect cannot be used to prepare a worker at all.
    claim_effect = next(
        effect for effect in run.effects if effect.effect_class == "claim_issue"
    )
    wrong_class = _RecordingWorktree()
    with pytest.raises(ReducerAdmissionError, match="launch-worker effect"):
        _prepare(wrong_class, effect=claim_effect)
    assert wrong_class.calls == []

    # An Issue outside the run's bound scope cannot prepare a worktree.
    foreign_issue = _issue(4169, SHA_B)
    foreign = _RecordingWorktree()
    with pytest.raises(ReducerAdmissionError):
        _prepare(foreign, target_issue=foreign_issue)
    assert foreign.calls == []


def test_cancellation_records_obligations_instead_of_claiming_compensation() -> None:
    """Finding 4: DDO-04 never partially compensates committed pickup authority."""

    issue = _issue(4167, SHA_A)
    run, _worker_event, _launch = _drive_to_awaiting_review(issue)
    authorized = _actor("owner:RasmusTho")

    cancelled = reduce_lifecycle_command(
        run.state,
        LifecycleCommand(
            command="cancel",
            command_id="cmd-cancel-compensation",
            run_id=DDO4_RUN,
            expected_run_version=run.state.version,
            issued_by=authorized,
            issued_at=TS,
        ),
    )

    # No effect at all is emitted, so no partial compensation can exist. The
    # delivered effect vocabulary has no compensating class, and DDO-04 does not
    # invent one: INV-DDO-15 forbids claiming to undo a committed effect.
    assert cancelled.effects == ()
    assert COMPENSATING_EFFECT_CLASSES == frozenset()

    # The committed claim - which really did remove agent:ready and take a
    # dispatcher lease - is handed to reconciliation as an explicit obligation
    # rather than silently half-reversed.
    claim_effect = next(
        effect for effect in run.effects if effect.effect_class == "claim_issue"
    )
    claim_obligation = next(
        item
        for item in cancelled.obligations
        if item.effect_class == "claim_issue"
    )
    assert claim_obligation.effect_idempotency_key == claim_effect.idempotency_key
    assert claim_obligation.outcome_keys == claim_effect.expected_outcome_keys
    assert claim_obligation.last_observed_outcome_state == "claimed"
    assert claim_obligation.reconciliation_owner == "builderops_reconciliation"

    # Every committed effect is represented exactly once, and nothing that was
    # never committed appears.
    committed_keys = {
        item.idempotency_key
        for item in run.state.issue_state(issue.scope_key).unreconciled_effects
    }
    assert {
        item.effect_idempotency_key for item in cancelled.obligations
    } == committed_keys
    assert len(cancelled.obligations) == len(committed_keys)

    # The reducer emits no further effect after cancellation, from any input.
    for admitted_event in (run.events[-1], run.events[0]):
        followup = reduce_delivery_run(
            cancelled.state,
            run.admit(admitted_event, effect=run.effects[-1])
            if admitted_event.event_type
            in {"effect_succeeded", "effect_failed"}
            else run.admit(admitted_event),
        )
        assert followup.refusal == "terminal_run"
        assert followup.effects == ()

    # An effect the reducer authorized but never saw acknowledged is an unknown
    # external state, not an absent one. Cancelling mid-claim must still report
    # it: the adapter may already have removed agent:ready and taken a lease.
    inflight_issue = _issue(4167, SHA_A)
    inflight_plan = _ddo4_plan(((inflight_issue,),))
    inflight = _DdoRun(inflight_plan, _ddo4_profile())
    started = inflight.start()
    assert [item.effect_class for item in started.effects] == ["claim_issue"]
    claiming_state = inflight.state.issue_state(inflight_issue.scope_key)
    assert claiming_state.phase == "claiming"
    assert [entry.outcome_state for entry in claiming_state.effect_ledger] == [None]

    authorized_claim = inflight.materialize(started.effects[0], inflight.events[-1])
    mid_claim = reduce_lifecycle_command(
        inflight.state,
        LifecycleCommand(
            command="cancel",
            command_id="cmd-cancel-mid-claim",
            run_id=DDO4_RUN,
            expected_run_version=inflight.state.version,
            issued_by=authorized,
            issued_at=TS,
        ),
    )
    assert mid_claim.effects == ()
    assert len(mid_claim.obligations) == 1
    orphaned = mid_claim.obligations[0]
    assert orphaned.effect_class == "claim_issue"
    assert orphaned.effect_idempotency_key == authorized_claim.idempotency_key
    assert orphaned.last_observed_outcome_state is None
    assert orphaned.outcome_keys == authorized_claim.expected_outcome_keys
    assert orphaned.reconciliation_owner == "builderops_reconciliation"

    # Resume is the one path that authorizes effects without reducing an event,
    # so it must ledger them too. Otherwise a pause/resume before the first tick
    # authorizes a claim that removes agent:ready and takes a lease, and the
    # following cancel reports nothing outstanding.
    resumable = _DdoRun(_ddo4_plan(((inflight_issue,),)), _ddo4_profile())
    paused_early = reduce_lifecycle_command(
        resumable.state,
        LifecycleCommand(
            command="pause",
            command_id="cmd-pause-early",
            run_id=DDO4_RUN,
            expected_run_version=resumable.state.version,
            issued_by=authorized,
            issued_at=TS,
        ),
    )
    resumed_early = reduce_lifecycle_command(
        paused_early.state,
        LifecycleCommand(
            command="resume",
            command_id="cmd-resume-early",
            run_id=DDO4_RUN,
            expected_run_version=paused_early.state.version,
            issued_by=authorized,
            issued_at=TS,
        ),
    )
    assert [item.effect_class for item in resumed_early.effects] == ["claim_issue"]
    resumed_ledger = resumed_early.state.issue_state(
        inflight_issue.scope_key
    ).effect_ledger
    assert [entry.effect_class for entry in resumed_ledger] == ["claim_issue"]
    assert resumed_ledger[0].outcome_state is None
    after_resume = reduce_lifecycle_command(
        resumed_early.state,
        LifecycleCommand(
            command="cancel",
            command_id="cmd-cancel-after-resume",
            run_id=DDO4_RUN,
            expected_run_version=resumed_early.state.version,
            issued_by=authorized,
            issued_at=TS,
        ),
    )
    assert [item.effect_class for item in after_resume.obligations] == [
        "claim_issue"
    ]
    assert after_resume.obligations[0].last_observed_outcome_state is None
    assert after_resume.effects == ()

    # A truthful failure proves the guarded authority never moved, so that one
    # effect is the only kind excluded from the obligation set.
    failing = _DdoRun(_ddo4_plan(((inflight_issue,),)), _ddo4_profile())
    failing_started = failing.start()
    failing.fail(
        failing_started.effects[0],
        failing.events[-1],
        subject=_ready_authority(inflight_issue),
        label="claim",
    )
    resolved = reduce_lifecycle_command(
        failing.state,
        LifecycleCommand(
            command="cancel",
            command_id="cmd-cancel-after-failure",
            run_id=DDO4_RUN,
            expected_run_version=failing.state.version,
            issued_by=authorized,
            issued_at=TS,
        ),
    )
    assert resolved.obligations == ()

    # A reported failure is not by itself proof of non-commitment. Only classes
    # whose truthful failure requires the guarded authority to be unchanged, or
    # that mutate nothing at all, are excluded. A merge GitHub may already have
    # completed stays an obligation.
    merging_run, _merge_event, _merge_launch = _drive_to_awaiting_review(issue)
    merge_accepted = _record_review(
        merging_run,
        _ddo4_review(
            issue,
            merging_run.plan,
            result_id="review-merge-failure",
            disposition="accept",
        ),
        subject=_claimed_authority(issue),
    )
    merging_run.fail(
        merge_accepted.effects[0],
        merging_run.events[-1],
        subject=_claimed_authority(issue),
        label="merge",
    )
    merge_cancelled = reduce_lifecycle_command(
        merging_run.state,
        LifecycleCommand(
            command="cancel",
            command_id="cmd-cancel-after-merge-failure",
            run_id=DDO4_RUN,
            expected_run_version=merging_run.state.version,
            issued_by=authorized,
            issued_at=TS,
        ),
    )
    merge_obligation = next(
        item
        for item in merge_cancelled.obligations
        if item.effect_class == "merge_pull_request"
    )
    assert merge_obligation.last_observed_outcome_state == "failed"
    # A failed await_ci mutates nothing external, so it is genuinely resolved.
    assert not any(
        item.effect_class == "await_ci" and item.last_observed_outcome_state == "failed"
        for item in resolved.obligations
    )

    # A cancelled run's obligations can only be carried by a receipt that is not
    # marked delivered, so a false clean receipt is unconstructable.
    initiation = _initiation(_issue(4165, SHA_A))
    plan_4165 = _plan(_issue(4165, SHA_A), initiation)
    receipt_v1 = _receipt(
        _issue(4165, SHA_A),
        initiation,
        plan_4165,
        _worker_result(_issue(4165, SHA_A), plan_4165),
        _review_result(_issue(4165, SHA_A), plan_4165),
    )
    profile = _ddo4_profile()
    with pytest.raises(ValidationError, match="unreconciled effect obligations"):
        DeliveryReceiptV2(
            receipt_id="false-clean",
            run_id=receipt_v1.run_id,
            delivery_receipt_ref=_ddo4_ref(receipt_v1, receipt_v1.receipt_id),
            acceptance_profile_ref=_ddo4_ref(profile, profile.profile_id),
            acceptance_profile_hash=profile.content_hash,
            satisfied_evidence=(
                "issue_closed",
                "pull_request_merged",
                "required_checks_green",
                "review_accepted",
            ),
            terminal_outcome="delivered",
            outstanding_effect_obligations=cancelled.obligations,
            provenance=_provenance("false-clean"),
        )
