"""Canonical semantic contracts for deterministic Builder System delivery.

The models in this module define evidence and orchestration messages only.
They do not persist records, compile live scope, execute effects, or grant
authority over an external system.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Annotated, Any, ClassVar, Final, Literal, TypeAlias, cast

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

DELIVERY_INITIATION_VERSION: Final[
    Literal["builderops.delivery-initiation.v1"]
] = "builderops.delivery-initiation.v1"
DELIVERY_PLAN_VERSION: Final[
    Literal["builderops.delivery-plan.v1"]
] = "builderops.delivery-plan.v1"
REDUCER_EVENT_VERSION: Final[
    Literal["builderops.delivery-reducer-event.v1"]
] = "builderops.delivery-reducer-event.v1"
REDUCER_EFFECT_VERSION: Final[
    Literal["builderops.delivery-reducer-effect.v1"]
] = "builderops.delivery-reducer-effect.v1"
WORKER_RESULT_VERSION: Final[
    Literal["builderops.delivery-worker-result.v1"]
] = "builderops.delivery-worker-result.v1"
REVIEW_RESULT_VERSION: Final[
    Literal["builderops.delivery-review-result.v1"]
] = "builderops.delivery-review-result.v1"
DELIVERY_RECEIPT_VERSION: Final[
    Literal["builderops.delivery-receipt.v1"]
] = "builderops.delivery-receipt.v1"

_UTC_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$"
)


def _validate_utc_timestamp(value: str) -> str:
    if not _UTC_TIMESTAMP.fullmatch(value):
        raise ValueError("timestamp must be an RFC 3339 UTC value ending in Z")
    return value


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
GitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40,64}$")]
UtcTimestamp = Annotated[str, AfterValidator(_validate_utc_timestamp)]
PositiveInt = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
ConfidenceBasisPoints = Annotated[int, Field(ge=0, le=10_000)]

EffectClass: TypeAlias = Literal[
    "claim_issue",
    "launch_worker",
    "await_ci",
    "request_review",
    "merge_pull_request",
    "close_issue",
    "record_known_defect",
    "record_delivery_receipt",
]
ExceptionKind: TypeAlias = Literal[
    "authority_conflict",
    "dependency_blocked",
    "malformed_result",
    "external_state_unknown",
    "budget_exhausted",
    "review_blocking",
    "execution_failed",
    "cancelled",
]


def canonical_json(value: Any) -> str:
    """Return the only JSON representation used for delivery contract hashes."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _require_unique(values: tuple[Any, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must not contain duplicates")


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        str_min_length=1,
    )


class CanonicalDeliveryContract(_StrictFrozenModel):
    """Base for top-level, hash-addressable delivery contracts."""

    contract_family: ClassVar[str]

    def canonical_json(self) -> str:
        return canonical_json(self)

    def canonical_bytes(self) -> bytes:
        return self.canonical_json().encode("utf-8")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


class ActorIdentity(_StrictFrozenModel):
    actor_type: Literal["human", "builder_agent", "service"]
    actor_id: NonEmptyStr
    authority_scope: NonEmptyStr


class SourceRef(_StrictFrozenModel):
    source_type: NonEmptyStr
    source_id: NonEmptyStr
    content_hash: Sha256


class Provenance(_StrictFrozenModel):
    created_at: UtcTimestamp
    created_by: ActorIdentity
    source_refs: tuple[SourceRef, ...]
    correlation_id: NonEmptyStr

    @model_validator(mode="after")
    def _validate_source_refs(self) -> Provenance:
        if not self.source_refs:
            raise ValueError("provenance must carry at least one source ref")
        _require_unique(
            tuple((item.source_type, item.source_id) for item in self.source_refs),
            "provenance source refs",
        )
        return self


class ContractRef(_StrictFrozenModel):
    schema_version: NonEmptyStr
    contract_id: NonEmptyStr
    content_hash: Sha256


class IssueScope(_StrictFrozenModel):
    repository: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$",
        ),
    ]
    issue_number: PositiveInt
    authority_id: NonEmptyStr
    contract_hash: Sha256

    @property
    def scope_key(self) -> tuple[str, int]:
        return (self.repository.casefold(), self.issue_number)


class ScopeExclusion(_StrictFrozenModel):
    scope_key: NonEmptyStr
    reason: NonEmptyStr


class AuthoritySnapshot(_StrictFrozenModel):
    authority_type: NonEmptyStr
    authority_id: NonEmptyStr
    content_hash: Sha256
    observed_state: NonEmptyStr
    observed_at: UtcTimestamp


class PolicyProfile(_StrictFrozenModel):
    profile_id: NonEmptyStr
    profile_version: NonEmptyStr
    profile_hash: Sha256


class DeliveryBudget(_StrictFrozenModel):
    max_parallel_workers: PositiveInt
    max_worker_starts: PositiveInt
    max_coordinator_turns: NonNegativeInt
    max_total_tokens: NonNegativeInt
    max_wall_time_seconds: PositiveInt

    @model_validator(mode="after")
    def _validate_worker_budget(self) -> DeliveryBudget:
        if self.max_worker_starts < self.max_parallel_workers:
            raise ValueError(
                "max_worker_starts must be at least max_parallel_workers"
            )
        return self


class ApprovalEvidence(_StrictFrozenModel):
    approval_id: NonEmptyStr
    approver: ActorIdentity
    approved_at: UtcTimestamp
    approved_payload_hash: Sha256
    source_refs: tuple[SourceRef, ...]
    immutable: Literal[True] = True
    effect_authority: Literal[False] = False

    @model_validator(mode="after")
    def _validate_sources(self) -> ApprovalEvidence:
        if not self.source_refs:
            raise ValueError("approval evidence must carry a source ref")
        _require_unique(
            tuple((item.source_type, item.source_id) for item in self.source_refs),
            "approval source refs",
        )
        return self


class DeliveryInitiation(CanonicalDeliveryContract):
    contract_family: ClassVar[str] = "initiation"
    schema_version: Literal[
        "builderops.delivery-initiation.v1"
    ] = DELIVERY_INITIATION_VERSION
    initiation_id: NonEmptyStr
    requested_scope: tuple[IssueScope, ...]
    exclusions: tuple[ScopeExclusion, ...]
    approval_evidence: ApprovalEvidence
    policy_profile: PolicyProfile
    budget: DeliveryBudget
    source_authorities: tuple[AuthoritySnapshot, ...]
    provenance: Provenance

    @model_validator(mode="after")
    def _validate_initiation(self) -> DeliveryInitiation:
        if not self.requested_scope:
            raise ValueError("requested scope must not be empty")
        _require_unique(
            tuple(item.scope_key for item in self.requested_scope),
            "requested scope",
        )
        _require_unique(
            tuple(item.scope_key for item in self.exclusions),
            "scope exclusions",
        )
        authorities = {
            (item.authority_id, item.content_hash) for item in self.source_authorities
        }
        missing = [
            item.authority_id
            for item in self.requested_scope
            if (item.authority_id, item.contract_hash) not in authorities
        ]
        if missing:
            raise ValueError(
                f"source authorities must bind every requested scope item: {missing}"
            )
        return self


class DependencyWave(_StrictFrozenModel):
    wave_index: NonNegativeInt
    issues: tuple[IssueScope, ...]

    @model_validator(mode="after")
    def _validate_issues(self) -> DependencyWave:
        if not self.issues:
            raise ValueError("dependency wave must not be empty")
        _require_unique(tuple(item.scope_key for item in self.issues), "wave issues")
        return self


class ExpectedAuthorityState(_StrictFrozenModel):
    issue: IssueScope
    issue_state: Literal["open", "closed"]
    required_labels: tuple[NonEmptyStr, ...]
    forbidden_labels: tuple[NonEmptyStr, ...]
    expected_contract_hash: Sha256

    @model_validator(mode="after")
    def _validate_state(self) -> ExpectedAuthorityState:
        _require_unique(self.required_labels, "required labels")
        _require_unique(self.forbidden_labels, "forbidden labels")
        overlap = set(self.required_labels) & set(self.forbidden_labels)
        if overlap:
            raise ValueError(
                f"labels cannot be both required and forbidden: {sorted(overlap)}"
            )
        if self.expected_contract_hash != self.issue.contract_hash:
            raise ValueError("expected contract hash must bind the issue contract")
        return self


class DeliveryPlan(CanonicalDeliveryContract):
    contract_family: ClassVar[str] = "plan"
    schema_version: Literal["builderops.delivery-plan.v1"] = DELIVERY_PLAN_VERSION
    plan_id: NonEmptyStr
    initiation_ref: ContractRef
    input_authorities: tuple[AuthoritySnapshot, ...]
    final_scope: tuple[IssueScope, ...]
    exclusions: tuple[ScopeExclusion, ...]
    dependency_waves: tuple[DependencyWave, ...]
    expected_states: tuple[ExpectedAuthorityState, ...]
    policy_profile: PolicyProfile
    budget: DeliveryBudget
    effect_allowlist: tuple[EffectClass, ...]
    provenance: Provenance

    @model_validator(mode="after")
    def _validate_plan(self) -> DeliveryPlan:
        if self.initiation_ref.schema_version != DELIVERY_INITIATION_VERSION:
            raise ValueError("plan initiation ref must bind DeliveryInitiation.v1")
        if not self.final_scope:
            raise ValueError("final scope must not be empty")
        scope_keys = tuple(item.scope_key for item in self.final_scope)
        _require_unique(scope_keys, "final scope")
        _require_unique(
            tuple(item.scope_key for item in self.exclusions),
            "scope exclusions",
        )
        if tuple(wave.wave_index for wave in self.dependency_waves) != tuple(
            range(len(self.dependency_waves))
        ):
            raise ValueError("dependency waves must use contiguous zero-based indices")
        wave_keys = tuple(
            item.scope_key
            for wave in self.dependency_waves
            for item in wave.issues
        )
        if len(wave_keys) != len(set(wave_keys)) or set(wave_keys) != set(scope_keys):
            raise ValueError("dependency waves must cover final scope exactly once")
        expected_keys = tuple(item.issue.scope_key for item in self.expected_states)
        if len(expected_keys) != len(set(expected_keys)) or set(expected_keys) != set(
            scope_keys
        ):
            raise ValueError("expected states must cover final scope exactly once")
        authority_bindings = {
            (item.authority_id, item.content_hash) for item in self.input_authorities
        }
        missing = [
            item.authority_id
            for item in self.final_scope
            if (item.authority_id, item.contract_hash) not in authority_bindings
        ]
        if missing:
            raise ValueError(
                f"input authorities must bind every final scope item: {missing}"
            )
        if not self.effect_allowlist:
            raise ValueError("effect allowlist must not be empty")
        _require_unique(self.effect_allowlist, "effect allowlist")
        return self


class DeliveryException(_StrictFrozenModel):
    kind: ExceptionKind
    code: NonEmptyStr
    message: NonEmptyStr
    retryable: bool
    evidence_refs: tuple[NonEmptyStr, ...]

    @model_validator(mode="after")
    def _validate_evidence(self) -> DeliveryException:
        if not self.evidence_refs:
            raise ValueError("delivery exception must carry evidence")
        _require_unique(self.evidence_refs, "exception evidence refs")
        return self


class ReducerEvent(CanonicalDeliveryContract):
    contract_family: ClassVar[str] = "reducer"
    schema_version: Literal[
        "builderops.delivery-reducer-event.v1"
    ] = REDUCER_EVENT_VERSION
    event_id: NonEmptyStr
    run_id: NonEmptyStr
    plan_ref: ContractRef
    sequence: NonNegativeInt
    event_type: Literal[
        "run_started",
        "effect_succeeded",
        "effect_failed",
        "authority_changed",
        "worker_result_recorded",
        "review_result_recorded",
        "timer_elapsed",
        "exception_recorded",
    ]
    subject_authority: AuthoritySnapshot | None
    effect_ref: ContractRef | None
    result_ref: ContractRef | None
    exception: DeliveryException | None
    provenance: Provenance

    @model_validator(mode="after")
    def _validate_event(self) -> ReducerEvent:
        if self.plan_ref.schema_version != DELIVERY_PLAN_VERSION:
            raise ValueError("reducer event must bind DeliveryPlan.v1")
        if self.event_type in {"effect_succeeded", "effect_failed"} and self.effect_ref is None:
            raise ValueError("effect result events require an effect ref")
        if self.event_type in {
            "worker_result_recorded",
            "review_result_recorded",
        } and self.result_ref is None:
            raise ValueError("structured-result events require a result ref")
        if self.event_type == "exception_recorded" and self.exception is None:
            raise ValueError("exception event requires a typed exception")
        return self


class ReducerEffect(CanonicalDeliveryContract):
    contract_family: ClassVar[str] = "reducer"
    schema_version: Literal[
        "builderops.delivery-reducer-effect.v1"
    ] = REDUCER_EFFECT_VERSION
    effect_id: NonEmptyStr
    run_id: NonEmptyStr
    plan_ref: ContractRef
    sequence: NonNegativeInt
    effect_class: EffectClass
    issue: IssueScope | None
    expected_authorities: tuple[AuthoritySnapshot, ...]
    idempotency_key: NonEmptyStr
    input_hash: Sha256
    requires_live_authority_check: Literal[True] = True
    authorized_by_plan_only: Literal[False] = False
    provenance: Provenance

    @model_validator(mode="after")
    def _validate_effect(self) -> ReducerEffect:
        if self.plan_ref.schema_version != DELIVERY_PLAN_VERSION:
            raise ValueError("reducer effect must bind DeliveryPlan.v1")
        if not self.expected_authorities:
            raise ValueError("reducer effect must bind expected live authority")
        if self.issue is not None and not any(
            authority.authority_id == self.issue.authority_id
            and authority.content_hash == self.issue.contract_hash
            for authority in self.expected_authorities
        ):
            raise ValueError("effect authority snapshots must bind the issue")
        return self


class ValidationEvidence(_StrictFrozenModel):
    name: NonEmptyStr
    status: Literal["passed", "failed", "skipped"]
    evidence_ref: NonEmptyStr
    exact_head_sha: GitSha | None


class StructuredWorkerResult(CanonicalDeliveryContract):
    contract_family: ClassVar[str] = "structured_result"
    schema_version: Literal[
        "builderops.delivery-worker-result.v1"
    ] = WORKER_RESULT_VERSION
    result_id: NonEmptyStr
    run_id: NonEmptyStr
    issue: IssueScope
    status: Literal["completed", "blocked", "failed", "cancelled"]
    exact_head_sha: GitSha | None
    pull_request_number: PositiveInt | None
    changed_files: tuple[NonEmptyStr, ...]
    validations: tuple[ValidationEvidence, ...]
    exceptions: tuple[DeliveryException, ...]
    summary: NonEmptyStr
    provenance: Provenance

    @model_validator(mode="after")
    def _validate_result(self) -> StructuredWorkerResult:
        _require_unique(self.changed_files, "changed files")
        _require_unique(
            tuple(item.name for item in self.validations),
            "validation evidence",
        )
        if self.status == "completed":
            if self.exact_head_sha is None or self.pull_request_number is None:
                raise ValueError(
                    "completed worker result requires exact head and pull request"
                )
            if any(item.status != "passed" for item in self.validations):
                raise ValueError(
                    "completed worker result cannot carry non-passing validation"
                )
            if any(
                item.exact_head_sha is not None
                and item.exact_head_sha != self.exact_head_sha
                for item in self.validations
            ):
                raise ValueError("worker validation must bind the exact result head")
        elif not self.exceptions:
            raise ValueError("non-completed worker result requires a typed exception")
        return self


class ReviewFinding(_StrictFrozenModel):
    finding_id: NonEmptyStr
    severity: Literal["P0", "P1", "P2", "P3"]
    summary: NonEmptyStr
    protected_risk: bool
    false_green: bool
    evidence_refs: tuple[NonEmptyStr, ...]

    @model_validator(mode="after")
    def _validate_evidence(self) -> ReviewFinding:
        if not self.evidence_refs:
            raise ValueError("review finding must carry evidence")
        _require_unique(self.evidence_refs, "review finding evidence refs")
        return self


class ReviewResult(CanonicalDeliveryContract):
    contract_family: ClassVar[str] = "structured_result"
    schema_version: Literal[
        "builderops.delivery-review-result.v1"
    ] = REVIEW_RESULT_VERSION
    result_id: NonEmptyStr
    run_id: NonEmptyStr
    issue: IssueScope
    pull_request_number: PositiveInt
    exact_head_sha: GitSha
    disposition: Literal["accept", "reject", "accept_with_risk"]
    confidence_basis_points: ConfidenceBasisPoints
    findings: tuple[ReviewFinding, ...]
    known_defect_refs: tuple[NonEmptyStr, ...]
    provenance: Provenance

    @model_validator(mode="after")
    def _validate_review(self) -> ReviewResult:
        _require_unique(
            tuple(item.finding_id for item in self.findings),
            "review finding IDs",
        )
        _require_unique(self.known_defect_refs, "known defect refs")
        has_blocker = any(
            finding.severity in {"P0", "P1"}
            or finding.protected_risk
            or finding.false_green
            for finding in self.findings
        )
        if has_blocker and self.disposition != "reject":
            raise ValueError("blocking review evidence requires reject disposition")
        if self.disposition == "accept" and self.findings:
            raise ValueError("accept disposition must not carry findings")
        if self.disposition == "accept_with_risk" and not self.findings:
            raise ValueError("accept_with_risk requires at least one finding")
        if self.disposition != "accept_with_risk" and self.known_defect_refs:
            raise ValueError(
                "known defect refs are only valid for accept_with_risk disposition"
            )
        return self


class CheckEvidence(_StrictFrozenModel):
    check_name: NonEmptyStr
    status: Literal["passed", "failed", "skipped"]
    exact_head_sha: GitSha
    evidence_ref: NonEmptyStr


class KnownDefectRef(_StrictFrozenModel):
    issue_number: PositiveInt
    severity: Literal["P2"]
    registry_ref: NonEmptyStr
    finding_hash: Sha256


class MergeIdentity(_StrictFrozenModel):
    pull_request_number: PositiveInt
    exact_head_sha: GitSha
    base_sha: GitSha
    merge_commit_sha: GitSha
    merged_at: UtcTimestamp
    merged_by: ActorIdentity


class ClosureEvidence(_StrictFrozenModel):
    issue_number: PositiveInt
    closed_at: UtcTimestamp
    closure_ref: NonEmptyStr


class IssueDeliveryProof(_StrictFrozenModel):
    issue: IssueScope
    worker_result_ref: ContractRef
    review_result_ref: ContractRef
    exact_head_sha: GitSha
    merge_identity: MergeIdentity | None
    check_evidence: tuple[CheckEvidence, ...]
    review_disposition: Literal["accept", "reject", "accept_with_risk"]
    known_defects: tuple[KnownDefectRef, ...]
    exceptions: tuple[DeliveryException, ...]
    closure: ClosureEvidence | None

    @model_validator(mode="after")
    def _validate_proof(self) -> IssueDeliveryProof:
        if self.worker_result_ref.schema_version != WORKER_RESULT_VERSION:
            raise ValueError("issue proof must bind a structured worker result")
        if self.review_result_ref.schema_version != REVIEW_RESULT_VERSION:
            raise ValueError("issue proof must bind a structured review result")
        _require_unique(
            tuple(item.check_name for item in self.check_evidence),
            "check evidence",
        )
        if any(item.exact_head_sha != self.exact_head_sha for item in self.check_evidence):
            raise ValueError("check evidence must bind the exact head")
        if self.merge_identity is not None:
            if self.merge_identity.exact_head_sha != self.exact_head_sha:
                raise ValueError("merge identity must bind the exact head")
            if self.merge_identity.pull_request_number < 1:
                raise ValueError("merge identity must bind a pull request")
        if self.closure is not None and self.closure.issue_number != self.issue.issue_number:
            raise ValueError("closure evidence must bind the proof issue")
        if self.review_disposition != "accept_with_risk" and self.known_defects:
            raise ValueError(
                "known defects require accept_with_risk review disposition"
            )
        return self


class RecoveryStep(_StrictFrozenModel):
    step_index: NonNegativeInt
    exception_kind: ExceptionKind
    action: NonEmptyStr
    authority_readback_refs: tuple[NonEmptyStr, ...]
    outcome: Literal["reconciled", "retry_scheduled", "blocked", "failed"]
    occurred_at: UtcTimestamp

    @model_validator(mode="after")
    def _validate_readbacks(self) -> RecoveryStep:
        if not self.authority_readback_refs:
            raise ValueError("recovery step must carry authority readback evidence")
        _require_unique(
            self.authority_readback_refs,
            "recovery authority readback refs",
        )
        return self


class TcdMetrics(_StrictFrozenModel):
    coordinator_model_turns: NonNegativeInt
    estimated_coordinator_tokens: NonNegativeInt
    worker_starts: NonNegativeInt
    human_interventions: NonNegativeInt
    deterministic_transitions: NonNegativeInt
    model_decided_exceptions: NonNegativeInt
    ci_wait_cycles: NonNegativeInt
    ci_wall_time_seconds: NonNegativeInt
    review_rounds: NonNegativeInt
    repair_rounds: NonNegativeInt
    duplicate_claim_attempts: NonNegativeInt
    duplicate_worker_attempts: NonNegativeInt
    duplicate_pull_request_attempts: NonNegativeInt
    duplicate_merge_attempts: NonNegativeInt
    duplicate_closure_attempts: NonNegativeInt
    known_p2_dispositions: NonNegativeInt
    escaped_p0_p1_defects: NonNegativeInt
    false_green_events: NonNegativeInt
    lead_time_seconds: NonNegativeInt


class DeliveryReceipt(CanonicalDeliveryContract):
    contract_family: ClassVar[str] = "receipt"
    schema_version: Literal[
        "builderops.delivery-receipt.v1"
    ] = DELIVERY_RECEIPT_VERSION
    receipt_id: NonEmptyStr
    run_id: NonEmptyStr
    initiation_ref: ContractRef
    plan_ref: ContractRef
    terminal_outcome: Literal[
        "delivered",
        "partially_delivered",
        "blocked",
        "failed",
        "cancelled",
    ]
    issue_proofs: tuple[IssueDeliveryProof, ...]
    exceptions: tuple[DeliveryException, ...]
    recovery_history: tuple[RecoveryStep, ...]
    tcd_metrics: TcdMetrics
    started_at: UtcTimestamp
    completed_at: UtcTimestamp
    provenance: Provenance

    @model_validator(mode="after")
    def _validate_receipt(self) -> DeliveryReceipt:
        if self.initiation_ref.schema_version != DELIVERY_INITIATION_VERSION:
            raise ValueError("receipt initiation ref must bind DeliveryInitiation.v1")
        if self.plan_ref.schema_version != DELIVERY_PLAN_VERSION:
            raise ValueError("receipt plan ref must bind DeliveryPlan.v1")
        if not self.issue_proofs:
            raise ValueError("delivery receipt must carry per-issue proof")
        _require_unique(
            tuple(item.issue.scope_key for item in self.issue_proofs),
            "receipt issue proofs",
        )
        if tuple(step.step_index for step in self.recovery_history) != tuple(
            range(len(self.recovery_history))
        ):
            raise ValueError(
                "recovery history must use contiguous zero-based step indices"
            )
        if self.terminal_outcome == "delivered":
            if any(
                proof.merge_identity is None
                or proof.closure is None
                or proof.review_disposition == "reject"
                or any(check.status != "passed" for check in proof.check_evidence)
                for proof in self.issue_proofs
            ):
                raise ValueError(
                    "delivered outcome requires merged, closed, accepted exact-head proof"
                )
        elif not self.exceptions:
            raise ValueError("non-delivered outcome requires a typed exception")
        return self


DeliveryContract = (
    DeliveryInitiation
    | DeliveryPlan
    | ReducerEvent
    | ReducerEffect
    | StructuredWorkerResult
    | ReviewResult
    | DeliveryReceipt
)

DELIVERY_CONTRACT_FAMILIES: dict[
    str, tuple[type[CanonicalDeliveryContract], ...]
] = {
    "initiation": (DeliveryInitiation,),
    "plan": (DeliveryPlan,),
    "reducer": (ReducerEvent, ReducerEffect),
    "structured_result": (StructuredWorkerResult, ReviewResult),
    "receipt": (DeliveryReceipt,),
}

_CONTRACT_TYPES: dict[str, type[CanonicalDeliveryContract]] = {
    contract.model_fields["schema_version"].default: contract
    for contracts in DELIVERY_CONTRACT_FAMILIES.values()
    for contract in contracts
}


def parse_delivery_contract(
    raw: str | bytes | bytearray | Mapping[str, Any],
) -> DeliveryContract:
    """Strictly validate one versioned contract from JSON or a JSON-like mapping."""

    try:
        if isinstance(raw, Mapping):
            encoded = canonical_json(dict(raw)).encode("utf-8")
            payload = dict(raw)
        else:
            encoded = bytes(raw) if not isinstance(raw, str) else raw.encode("utf-8")
            payload = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("delivery contract must be one JSON object") from exc
    if not isinstance(payload, dict):
        raise ValueError("delivery contract must be one JSON object")
    schema_version = payload.get("schema_version")
    if not isinstance(schema_version, str):
        raise ValueError("delivery contract schema_version must be a string")
    contract_type = _CONTRACT_TYPES.get(schema_version)
    if contract_type is None:
        raise ValueError(
            f"unsupported delivery contract schema_version: {schema_version!r}"
        )
    try:
        return cast(DeliveryContract, contract_type.model_validate_json(encoded))
    except ValidationError:
        raise


__all__ = [
    "ActorIdentity",
    "ApprovalEvidence",
    "AuthoritySnapshot",
    "CanonicalDeliveryContract",
    "CheckEvidence",
    "ClosureEvidence",
    "ContractRef",
    "DELIVERY_CONTRACT_FAMILIES",
    "DELIVERY_INITIATION_VERSION",
    "DELIVERY_PLAN_VERSION",
    "DELIVERY_RECEIPT_VERSION",
    "DeliveryBudget",
    "DeliveryContract",
    "DeliveryException",
    "DeliveryInitiation",
    "DeliveryPlan",
    "DeliveryReceipt",
    "DependencyWave",
    "ExpectedAuthorityState",
    "IssueDeliveryProof",
    "IssueScope",
    "KnownDefectRef",
    "MergeIdentity",
    "PolicyProfile",
    "Provenance",
    "REDUCER_EFFECT_VERSION",
    "REDUCER_EVENT_VERSION",
    "REVIEW_RESULT_VERSION",
    "RecoveryStep",
    "ReducerEffect",
    "ReducerEvent",
    "ReviewFinding",
    "ReviewResult",
    "ScopeExclusion",
    "SourceRef",
    "StructuredWorkerResult",
    "TcdMetrics",
    "ValidationEvidence",
    "WORKER_RESULT_VERSION",
    "canonical_hash",
    "canonical_json",
    "parse_delivery_contract",
]
