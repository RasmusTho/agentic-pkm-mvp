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
from datetime import datetime
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

_UTC_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _validate_utc_timestamp(value: str) -> str:
    if not _UTC_TIMESTAMP.fullmatch(value):
        raise ValueError("timestamp must be second-precision RFC 3339 UTC ending in Z")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError("timestamp must be a real UTC calendar value") from exc
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
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _require_unique(values: tuple[Any, ...], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must not contain duplicates")


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError(f"duplicate delivery contract JSON key: {key}")
        payload[key] = value
    return payload


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
    omitted_issue: IssueScope | None = None

    @model_validator(mode="after")
    def _validate_scope_identity(self) -> ScopeExclusion:
        if self.omitted_issue is not None:
            expected_key = (
                f"{self.omitted_issue.repository.casefold()}"
                f"#{self.omitted_issue.issue_number}"
            )
            if self.scope_key != expected_key:
                raise ValueError(
                    "issue exclusion must bind its canonical omitted-Issue identity"
                )
        return self


class AuthoritySnapshot(_StrictFrozenModel):
    authority_type: NonEmptyStr
    authority_id: NonEmptyStr
    content_hash: Sha256
    observed_state: NonEmptyStr
    observed_labels: tuple[NonEmptyStr, ...]
    observed_at: UtcTimestamp

    @model_validator(mode="after")
    def _validate_labels(self) -> AuthoritySnapshot:
        _require_unique(self.observed_labels, "authority snapshot labels")
        if self.observed_labels != tuple(sorted(self.observed_labels)):
            raise ValueError(
                "authority snapshot labels must use canonical sorted order"
            )
        return self


def _same_authority_state(
    left: AuthoritySnapshot,
    right: AuthoritySnapshot,
) -> bool:
    """Compare authority semantics while allowing a fresh observation timestamp."""

    return (
        left.authority_type == right.authority_type
        and left.authority_id == right.authority_id
        and left.content_hash == right.content_hash
        and left.observed_state == right.observed_state
        and left.observed_labels == right.observed_labels
    )


class PolicyProfile(_StrictFrozenModel):
    profile_id: NonEmptyStr
    profile_version: NonEmptyStr
    profile_hash: Sha256
    minimum_review_confidence_basis_points: ConfidenceBasisPoints


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


def delivery_initiation_approval_hash(
    *,
    initiation_id: str,
    requested_scope: tuple[IssueScope, ...],
    exclusions: tuple[ScopeExclusion, ...],
    policy_profile: PolicyProfile,
    budget: DeliveryBudget,
    source_authorities: tuple[AuthoritySnapshot, ...],
    provenance: Provenance,
    approval_id: str,
    approver: ActorIdentity,
    approved_at: str,
    approval_source_refs: tuple[SourceRef, ...],
) -> str:
    """Hash the exact semantic initiation request that approval authenticates."""

    return canonical_hash(
        {
            "schema_version": DELIVERY_INITIATION_VERSION,
            "initiation_id": initiation_id,
            "requested_scope": [
                item.model_dump(mode="json") for item in requested_scope
            ],
            "exclusions": [item.model_dump(mode="json") for item in exclusions],
            "policy_profile": policy_profile.model_dump(mode="json"),
            "budget": budget.model_dump(mode="json"),
            "source_authorities": [
                item.model_dump(mode="json") for item in source_authorities
            ],
            "provenance": provenance.model_dump(mode="json"),
            "approval_context": {
                "approval_id": approval_id,
                "approver": approver.model_dump(mode="json"),
                "approved_at": approved_at,
                "source_refs": [
                    item.model_dump(mode="json")
                    for item in approval_source_refs
                ],
                "immutable": True,
                "effect_authority": False,
            },
        }
    )


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
        _require_unique(
            tuple(item.authority_id for item in self.source_authorities),
            "source authority IDs",
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
        expected_approval_hash = delivery_initiation_approval_hash(
            initiation_id=self.initiation_id,
            requested_scope=self.requested_scope,
            exclusions=self.exclusions,
            policy_profile=self.policy_profile,
            budget=self.budget,
            source_authorities=self.source_authorities,
            provenance=self.provenance,
            approval_id=self.approval_evidence.approval_id,
            approver=self.approval_evidence.approver,
            approved_at=self.approval_evidence.approved_at,
            approval_source_refs=self.approval_evidence.source_refs,
        )
        if self.approval_evidence.approved_payload_hash != expected_approval_hash:
            raise ValueError(
                "approval evidence must bind the exact canonical initiation payload"
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
        if self.required_labels != tuple(sorted(self.required_labels)):
            raise ValueError("required labels must use canonical sorted order")
        if self.forbidden_labels != tuple(sorted(self.forbidden_labels)):
            raise ValueError("forbidden labels must use canonical sorted order")
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
        _require_unique(
            tuple(item.authority_id for item in self.input_authorities),
            "input authority IDs",
        )
        if tuple(wave.wave_index for wave in self.dependency_waves) != tuple(
            range(len(self.dependency_waves))
        ):
            raise ValueError("dependency waves must use contiguous zero-based indices")
        wave_items = tuple(
            item
            for wave in self.dependency_waves
            for item in wave.issues
        )
        wave_keys = tuple(item.scope_key for item in wave_items)
        if len(wave_keys) != len(set(wave_keys)) or set(wave_keys) != set(scope_keys):
            raise ValueError("dependency waves must cover final scope exactly once")
        final_scope_by_key = {item.scope_key: item for item in self.final_scope}
        if any(final_scope_by_key[item.scope_key] != item for item in wave_items):
            raise ValueError(
                "dependency waves must preserve exact final-scope authority"
            )
        if any(
            len(wave.issues) > self.budget.max_parallel_workers
            for wave in self.dependency_waves
        ):
            raise ValueError(
                "dependency waves must not exceed max_parallel_workers"
            )
        expected_keys = tuple(item.issue.scope_key for item in self.expected_states)
        if len(expected_keys) != len(set(expected_keys)) or set(expected_keys) != set(
            scope_keys
        ):
            raise ValueError("expected states must cover final scope exactly once")
        if any(
            final_scope_by_key[item.issue.scope_key] != item.issue
            for item in self.expected_states
        ):
            raise ValueError(
                "expected states must preserve exact final-scope authority"
            )
        authority_bindings = {
            (item.authority_id, item.content_hash): item
            for item in self.input_authorities
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
        for expected_state in self.expected_states:
            snapshot = authority_bindings[
                (
                    expected_state.issue.authority_id,
                    expected_state.issue.contract_hash,
                )
            ]
            if (
                snapshot.observed_state != expected_state.issue_state
                or not set(expected_state.required_labels).issubset(
                    snapshot.observed_labels
                )
                or set(expected_state.forbidden_labels).intersection(
                    snapshot.observed_labels
                )
            ):
                raise ValueError(
                    "input authority snapshot contradicts expected state or labels"
                )
        if not self.effect_allowlist:
            raise ValueError("effect allowlist must not be empty")
        _require_unique(self.effect_allowlist, "effect allowlist")
        return self


def validate_delivery_plan_evidence(
    plan: DeliveryPlan,
    *,
    initiation: DeliveryInitiation,
) -> DeliveryPlan:
    """Resolve a plan against the exact approved initiation it claims to compile."""

    expected_initiation_ref = ContractRef(
        schema_version=initiation.schema_version,
        contract_id=initiation.initiation_id,
        content_hash=initiation.content_hash,
    )
    if plan.initiation_ref != expected_initiation_ref:
        raise ValueError("plan does not bind the supplied initiation")
    approved_scope = {item.scope_key: item for item in initiation.requested_scope}
    if any(
        approved_scope.get(item.scope_key) != item for item in plan.final_scope
    ):
        raise ValueError("plan final scope must be an exact subset of approved scope")
    final_scope_keys = {item.scope_key for item in plan.final_scope}
    final_scope_refs = {
        f"{item.repository.casefold()}#{item.issue_number}"
        for item in plan.final_scope
    }
    missing_scope_refs = {
        f"{item.repository.casefold()}#{item.issue_number}"
        for item in initiation.requested_scope
        if item.scope_key not in final_scope_keys
    }
    approved_scope_refs = {
        f"{item.repository.casefold()}#{item.issue_number}"
        for item in initiation.requested_scope
    }
    folded_exclusion_refs = tuple(
        item.scope_key.casefold() for item in plan.exclusions
    )
    if len(folded_exclusion_refs) != len(set(folded_exclusion_refs)):
        raise ValueError("plan exclusions must use unique canonical identities")
    issue_exclusions: dict[str, IssueScope] = {}
    for exclusion in plan.exclusions:
        folded_ref = exclusion.scope_key.casefold()
        omitted_issue = exclusion.omitted_issue
        if omitted_issue is None:
            if folded_ref in approved_scope_refs:
                raise ValueError(
                    "plan issue exclusions require typed omitted-Issue identity"
                )
            continue
        if folded_ref not in approved_scope_refs:
            raise ValueError(
                "plan issue exclusion is outside approved initiation scope"
            )
        if approved_scope[omitted_issue.scope_key] != omitted_issue:
            raise ValueError(
                "plan issue exclusion must preserve exact approved authority"
            )
        issue_exclusions[folded_ref] = omitted_issue
    issue_exclusion_refs = set(issue_exclusions)
    if final_scope_refs.intersection(issue_exclusion_refs):
        raise ValueError("plan final scope and issue exclusions must be disjoint")
    if issue_exclusion_refs != missing_scope_refs:
        raise ValueError(
            "plan issue exclusions must explain every omitted approved issue exactly"
        )
    if not set(initiation.exclusions).issubset(set(plan.exclusions)):
        raise ValueError("plan must preserve initiation exclusions")
    if plan.policy_profile != initiation.policy_profile:
        raise ValueError("plan policy profile must match approved initiation")
    if plan.budget != initiation.budget:
        raise ValueError("plan budget must match approved initiation")
    return plan


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
        expected: dict[
            str,
            tuple[
                bool,
                str | None,
                str | None,
                bool,
            ],
        ] = {
            "run_started": (False, None, None, False),
            "effect_succeeded": (True, REDUCER_EFFECT_VERSION, None, False),
            "effect_failed": (True, REDUCER_EFFECT_VERSION, None, True),
            "authority_changed": (True, None, None, False),
            "worker_result_recorded": (True, None, WORKER_RESULT_VERSION, False),
            "review_result_recorded": (True, None, REVIEW_RESULT_VERSION, False),
            "timer_elapsed": (False, None, None, False),
            "exception_recorded": (False, None, None, True),
        }
        (
            requires_subject,
            effect_version,
            result_version,
            requires_exception,
        ) = expected[self.event_type]
        if (self.subject_authority is not None) != requires_subject:
            raise ValueError(
                f"{self.event_type} subject authority does not match event contract"
            )
        if effect_version is None:
            if self.effect_ref is not None:
                raise ValueError(f"{self.event_type} must not carry an effect ref")
        elif (
            self.effect_ref is None
            or self.effect_ref.schema_version != effect_version
        ):
            raise ValueError(
                f"{self.event_type} requires a typed reducer-effect ref"
            )
        if result_version is None:
            if self.result_ref is not None:
                raise ValueError(f"{self.event_type} must not carry a result ref")
        elif (
            self.result_ref is None
            or self.result_ref.schema_version != result_version
        ):
            raise ValueError(
                f"{self.event_type} requires the matching structured-result ref"
            )
        if (self.exception is not None) != requires_exception:
            raise ValueError(
                f"{self.event_type} typed exception does not match event contract"
            )
        return self


def delivery_effect_input_hash(
    *,
    run_id: str,
    plan_ref: ContractRef,
    sequence: int,
    effect_class: EffectClass,
    issue: IssueScope,
    pull_request_number: int | None,
    exact_head_sha: str | None,
    expected_authorities: tuple[AuthoritySnapshot, ...],
) -> str:
    """Hash the complete semantic input to one proposed reducer effect."""

    authority_semantics = sorted(
        (
            {
                "authority_type": item.authority_type,
                "authority_id": item.authority_id,
                "content_hash": item.content_hash,
                "observed_state": item.observed_state,
                "observed_labels": list(item.observed_labels),
            }
            for item in expected_authorities
        ),
        key=canonical_json,
    )
    return canonical_hash(
        {
            "run_id": run_id,
            "plan_ref": plan_ref.model_dump(mode="json"),
            "sequence": sequence,
            "effect_class": effect_class,
            "issue": issue.model_dump(mode="json"),
            "pull_request_number": pull_request_number,
            "exact_head_sha": exact_head_sha,
            "expected_authorities": authority_semantics,
        }
    )


def delivery_effect_idempotency_key(input_hash: str) -> str:
    """Derive the sole idempotency identity from a validated semantic input hash."""

    return f"builderops.delivery-effect.v1:{input_hash}"


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
    issue: IssueScope
    pull_request_number: PositiveInt | None
    exact_head_sha: GitSha | None
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
        _require_unique(
            tuple(item.authority_id for item in self.expected_authorities),
            "effect expected authority IDs",
        )
        if not any(
            authority.authority_id == self.issue.authority_id
            and authority.content_hash == self.issue.contract_hash
            for authority in self.expected_authorities
        ):
            raise ValueError("effect authority snapshots must bind the issue")
        requires_pull_request = self.effect_class in {
            "await_ci",
            "request_review",
            "merge_pull_request",
            "close_issue",
            "record_known_defect",
            "record_delivery_receipt",
        }
        if requires_pull_request and (
            self.pull_request_number is None or self.exact_head_sha is None
        ):
            raise ValueError(
                f"{self.effect_class} requires pull request and exact head"
            )
        if not requires_pull_request and (
            self.pull_request_number is not None or self.exact_head_sha is not None
        ):
            raise ValueError(
                f"{self.effect_class} must not carry pull request or exact head"
            )
        expected_input_hash = delivery_effect_input_hash(
            run_id=self.run_id,
            plan_ref=self.plan_ref,
            sequence=self.sequence,
            effect_class=self.effect_class,
            issue=self.issue,
            pull_request_number=self.pull_request_number,
            exact_head_sha=self.exact_head_sha,
            expected_authorities=self.expected_authorities,
        )
        if self.input_hash != expected_input_hash:
            raise ValueError("reducer effect input hash must bind exact semantic input")
        if self.idempotency_key != delivery_effect_idempotency_key(
            expected_input_hash
        ):
            raise ValueError(
                "reducer effect idempotency key must derive from semantic input"
            )
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
    plan_ref: ContractRef
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
        if self.plan_ref.schema_version != DELIVERY_PLAN_VERSION:
            raise ValueError("worker result must bind DeliveryPlan.v1")
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
            if not self.validations:
                raise ValueError(
                    "completed worker result requires validation evidence"
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
        else:
            if not self.exceptions:
                raise ValueError(
                    "non-completed worker result requires a typed exception"
                )
            allowed_exception_kinds: dict[str, set[str]] = {
                "blocked": {
                    "authority_conflict",
                    "dependency_blocked",
                    "budget_exhausted",
                    "review_blocking",
                },
                "failed": {
                    "malformed_result",
                    "external_state_unknown",
                    "execution_failed",
                },
                "cancelled": {"cancelled"},
            }
            if any(
                item.kind not in allowed_exception_kinds[self.status]
                for item in self.exceptions
            ):
                raise ValueError(
                    "worker exception kinds must match terminal status"
                )
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
    plan_ref: ContractRef
    policy_profile: PolicyProfile
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
        if self.plan_ref.schema_version != DELIVERY_PLAN_VERSION:
            raise ValueError("review result must bind DeliveryPlan.v1")
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
        if (
            self.confidence_basis_points
            < self.policy_profile.minimum_review_confidence_basis_points
            and self.disposition != "reject"
        ):
            raise ValueError("low-confidence review evidence requires reject disposition")
        if self.disposition == "accept" and self.findings:
            raise ValueError("accept disposition must not carry findings")
        if self.disposition == "accept_with_risk" and not self.findings:
            raise ValueError("accept_with_risk requires at least one finding")
        if self.disposition != "accept_with_risk" and self.known_defect_refs:
            raise ValueError(
                "known defect refs are only valid for accept_with_risk disposition"
            )
        p2_findings = sum(
            finding.severity == "P2" for finding in self.findings
        )
        if (
            self.disposition == "accept_with_risk"
            and len(self.known_defect_refs) < p2_findings
        ):
            raise ValueError(
                "accept_with_risk requires durable known-defect refs for every P2"
            )
        return self


def validate_reducer_effect_evidence(
    effect: ReducerEffect,
    *,
    plan: DeliveryPlan,
) -> ReducerEffect:
    """Resolve an effect proposal against its immutable plan and exact scope."""

    expected_plan_ref = ContractRef(
        schema_version=plan.schema_version,
        contract_id=plan.plan_id,
        content_hash=plan.content_hash,
    )
    if effect.plan_ref != expected_plan_ref:
        raise ValueError("reducer effect does not bind the supplied plan")
    planned_scope = {item.scope_key: item for item in plan.final_scope}
    if planned_scope.get(effect.issue.scope_key) != effect.issue:
        raise ValueError("reducer effect issue is outside exact plan scope")
    if effect.effect_class not in plan.effect_allowlist:
        raise ValueError("reducer effect class is outside the plan allowlist")
    expected_state = next(
        (
            item
            for item in plan.expected_states
            if item.issue.scope_key == effect.issue.scope_key
        ),
        None,
    )
    matching_authorities = tuple(
        authority
        for authority in effect.expected_authorities
        if authority.authority_id == effect.issue.authority_id
    )
    planned_authorities = tuple(
        authority
        for authority in plan.input_authorities
        if authority.authority_id == effect.issue.authority_id
    )
    if (
        expected_state is None
        or len(matching_authorities) != 1
        or len(planned_authorities) != 1
        or not _same_authority_state(
            matching_authorities[0],
            planned_authorities[0],
        )
        or any(
            not any(
                _same_authority_state(authority, planned)
                for planned in plan.input_authorities
            )
            for authority in effect.expected_authorities
        )
    ):
        raise ValueError("reducer effect lacks the plan's expected live authority")
    return effect


def validate_reducer_event_evidence(
    event: ReducerEvent,
    *,
    plan: DeliveryPlan,
    effect: ReducerEffect | None = None,
    worker_result: StructuredWorkerResult | None = None,
    review_result: ReviewResult | None = None,
) -> ReducerEvent:
    """Resolve reducer-event references and subject authority against exact evidence."""

    expected_plan_ref = ContractRef(
        schema_version=plan.schema_version,
        contract_id=plan.plan_id,
        content_hash=plan.content_hash,
    )
    if event.plan_ref != expected_plan_ref:
        raise ValueError("reducer event does not bind the supplied plan")

    referenced_issue: IssueScope | None = None
    if event.event_type in {"effect_succeeded", "effect_failed"}:
        if effect is None:
            raise ValueError("effect event requires supplied reducer-effect evidence")
        expected_effect_ref = ContractRef(
            schema_version=effect.schema_version,
            contract_id=effect.effect_id,
            content_hash=effect.content_hash,
        )
        if event.effect_ref != expected_effect_ref:
            raise ValueError("reducer event effect ref does not resolve")
        validate_reducer_effect_evidence(effect, plan=plan)
        if effect.run_id != event.run_id:
            raise ValueError("reducer event and effect run IDs must match")
        referenced_issue = effect.issue
    elif event.event_type == "worker_result_recorded":
        if worker_result is None:
            raise ValueError("worker event requires supplied worker-result evidence")
        expected_result_ref = ContractRef(
            schema_version=worker_result.schema_version,
            contract_id=worker_result.result_id,
            content_hash=worker_result.content_hash,
        )
        if (
            event.result_ref != expected_result_ref
            or worker_result.plan_ref != expected_plan_ref
            or worker_result.run_id != event.run_id
        ):
            raise ValueError("reducer worker-result event does not resolve")
        referenced_issue = worker_result.issue
    elif event.event_type == "review_result_recorded":
        if review_result is None:
            raise ValueError("review event requires supplied review-result evidence")
        expected_result_ref = ContractRef(
            schema_version=review_result.schema_version,
            contract_id=review_result.result_id,
            content_hash=review_result.content_hash,
        )
        if (
            event.result_ref != expected_result_ref
            or review_result.plan_ref != expected_plan_ref
            or review_result.run_id != event.run_id
            or review_result.policy_profile != plan.policy_profile
        ):
            raise ValueError("reducer review-result event does not resolve")
        referenced_issue = review_result.issue
    elif event.event_type == "authority_changed":
        assert event.subject_authority is not None
        planned_issue = next(
            (
                item
                for item in plan.final_scope
                if item.authority_id == event.subject_authority.authority_id
            ),
            None,
        )
        expected_state = next(
            (
                item
                for item in plan.expected_states
                if item.issue.authority_id == event.subject_authority.authority_id
            ),
            None,
        )
        if planned_issue is None or expected_state is None:
            raise ValueError("authority-change event is outside exact plan scope")
        planned_authority = next(
            (
                item
                for item in plan.input_authorities
                if item.authority_id == planned_issue.authority_id
                and item.content_hash == planned_issue.contract_hash
            ),
            None,
        )
        if planned_authority is None:
            raise ValueError("authority-change event lacks planned authority")
        if (
            _same_authority_state(
                event.subject_authority,
                planned_authority,
            )
        ):
            raise ValueError("authority-change event must carry changed authority")

    if referenced_issue is not None:
        planned_issue = next(
            (
                item
                for item in plan.final_scope
                if item.scope_key == referenced_issue.scope_key
            ),
            None,
        )
        if planned_issue != referenced_issue:
            raise ValueError(
                "reducer event references evidence outside exact plan scope"
            )
        subject = event.subject_authority
        planned_authority = next(
            (
                item
                for item in plan.input_authorities
                if item.authority_id == referenced_issue.authority_id
                and item.content_hash == referenced_issue.contract_hash
            ),
            None,
        )
        if (
            subject is None
            or planned_authority is None
            or not _same_authority_state(subject, planned_authority)
        ):
            raise ValueError(
                "reducer event subject contradicts referenced evidence"
            )
    return event


class CheckEvidence(_StrictFrozenModel):
    check_name: NonEmptyStr
    status: Literal["passed", "failed", "skipped"]
    exact_head_sha: GitSha
    evidence_ref: NonEmptyStr


class KnownDefectRef(_StrictFrozenModel):
    issue_number: PositiveInt
    defect_id: Annotated[
        str,
        StringConstraints(pattern=r"^KD-[0-9A-F]{12}$"),
    ]
    severity: Literal["P2"]
    registry_ref: NonEmptyStr
    finding_hash: Sha256

    @model_validator(mode="after")
    def _validate_identity(self) -> KnownDefectRef:
        expected_ref = f"registry:{self.issue_number}:{self.defect_id}"
        if self.registry_ref != expected_ref:
            raise ValueError(
                "known defect registry ref must bind issue number and defect ID"
            )
        return self


class MergeIdentity(_StrictFrozenModel):
    pull_request_number: PositiveInt
    exact_head_sha: GitSha
    base_sha: GitSha
    merge_commit_sha: GitSha
    merged_at: UtcTimestamp
    merged_by: ActorIdentity


class ClosureEvidence(_StrictFrozenModel):
    repository: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$",
        ),
    ]
    issue_number: PositiveInt
    pull_request_number: PositiveInt
    exact_head_sha: GitSha
    closed_at: UtcTimestamp
    closure_ref: NonEmptyStr


class IssueDeliveryProof(_StrictFrozenModel):
    issue: IssueScope
    worker_result_ref: ContractRef
    review_result_ref: ContractRef | None
    exact_head_sha: GitSha | None
    merge_identity: MergeIdentity | None
    check_evidence: tuple[CheckEvidence, ...]
    review_disposition: Literal["accept", "reject", "accept_with_risk"] | None
    known_defects: tuple[KnownDefectRef, ...]
    exceptions: tuple[DeliveryException, ...]
    closure: ClosureEvidence | None

    @model_validator(mode="after")
    def _validate_proof(self) -> IssueDeliveryProof:
        if self.worker_result_ref.schema_version != WORKER_RESULT_VERSION:
            raise ValueError("issue proof must bind a structured worker result")
        if (
            self.review_result_ref is not None
            and self.review_result_ref.schema_version != REVIEW_RESULT_VERSION
        ):
            raise ValueError("issue proof must bind a structured review result")
        _require_unique(
            tuple(item.check_name for item in self.check_evidence),
            "check evidence",
        )
        if self.exact_head_sha is None and (
            self.check_evidence or self.merge_identity is not None
        ):
            raise ValueError("headless proof cannot carry checks or merge identity")
        if any(item.exact_head_sha != self.exact_head_sha for item in self.check_evidence):
            raise ValueError("check evidence must bind the exact head")
        if self.merge_identity is not None:
            if self.merge_identity.exact_head_sha != self.exact_head_sha:
                raise ValueError("merge identity must bind the exact head")
            if self.merge_identity.pull_request_number < 1:
                raise ValueError("merge identity must bind a pull request")
        if self.closure is not None and self.closure.issue_number != self.issue.issue_number:
            raise ValueError("closure evidence must bind the proof issue")
        if self.closure is not None:
            if self.closure.repository.casefold() != self.issue.repository.casefold():
                raise ValueError("closure evidence must bind the proof repository")
            if self.exact_head_sha != self.closure.exact_head_sha:
                raise ValueError("closure evidence must bind the exact head")
            if (
                self.merge_identity is not None
                and self.closure.pull_request_number
                != self.merge_identity.pull_request_number
            ):
                raise ValueError("closure evidence must bind the merged pull request")
        if (self.review_result_ref is None) != (self.review_disposition is None):
            raise ValueError(
                "review ref and disposition must be present or absent together"
            )
        if self.review_disposition != "accept_with_risk" and self.known_defects:
            raise ValueError(
                "known defects require accept_with_risk review disposition"
            )
        _require_unique(
            tuple(item.registry_ref for item in self.known_defects),
            "known defect registry refs",
        )
        _require_unique(
            tuple(item.finding_hash for item in self.known_defects),
            "known defect finding hashes",
        )
        return self


class RecoveryStep(_StrictFrozenModel):
    step_index: NonNegativeInt
    exception_kind: ExceptionKind
    exception_code: NonEmptyStr
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
    requested_scope: tuple[IssueScope, ...]
    final_scope: tuple[IssueScope, ...]
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
        if not self.requested_scope or not self.final_scope:
            raise ValueError("delivery receipt must preserve requested and final scope")
        _require_unique(
            tuple(item.scope_key for item in self.requested_scope),
            "receipt requested scope",
        )
        _require_unique(
            tuple(item.scope_key for item in self.final_scope),
            "receipt final scope",
        )
        _require_unique(
            tuple(item.issue.scope_key for item in self.issue_proofs),
            "receipt issue proofs",
        )
        proof_scope = {
            item.issue.scope_key: item.issue for item in self.issue_proofs
        }
        final_scope = {item.scope_key: item for item in self.final_scope}
        if proof_scope != final_scope:
            raise ValueError("receipt issue proofs must cover final scope exactly")
        if tuple(step.step_index for step in self.recovery_history) != tuple(
            range(len(self.recovery_history))
        ):
            raise ValueError(
                "recovery history must use contiguous zero-based step indices"
            )
        exception_codes = tuple(item.code for item in self.exceptions)
        exception_by_code = {item.code: item for item in self.exceptions}
        recovery_codes = tuple(item.exception_code for item in self.recovery_history)
        proof_exception_items = tuple(
            item
            for proof in self.issue_proofs
            for item in proof.exceptions
        )
        proof_exceptions = {item.code: item for item in proof_exception_items}
        if (
            len(exception_codes) != len(set(exception_codes))
            or len(recovery_codes) != len(set(recovery_codes))
            or not set(recovery_codes).issubset(set(exception_codes))
            or any(
                exception_by_code[step.exception_code].kind != step.exception_kind
                for step in self.recovery_history
            )
        ):
            raise ValueError("recovery history must bind typed receipt exceptions")
        delivered_proofs = tuple(
            proof.merge_identity is not None
            and proof.closure is not None
            and bool(proof.check_evidence)
            and proof.review_result_ref is not None
            and proof.review_disposition not in {None, "reject"}
            and all(check.status == "passed" for check in proof.check_evidence)
            and not proof.exceptions
            for proof in self.issue_proofs
        )
        if self.terminal_outcome == "delivered":
            if not all(delivered_proofs):
                raise ValueError(
                    "delivered outcome requires merged, closed, accepted exact-head proof"
                )
            if (
                set(exception_codes) != set(recovery_codes)
                or any(
                    step.outcome != "reconciled"
                    for step in self.recovery_history
                )
            ):
                raise ValueError(
                    "delivered outcome requires one reconciled recovery per exception"
                )
        else:
            if not self.exceptions:
                raise ValueError("non-delivered outcome requires a typed exception")
            if self.terminal_outcome == "partially_delivered":
                if not any(delivered_proofs) or all(delivered_proofs):
                    raise ValueError(
                        "partially delivered outcome requires mixed issue proof"
                    )
            elif any(
                proof.merge_identity is not None or proof.closure is not None
                for proof in self.issue_proofs
            ):
                raise ValueError(
                    "blocked, failed, or cancelled outcome cannot carry delivered proof"
                )
        recovery_only_exceptions = tuple(
            exception_by_code[code]
            for code in recovery_codes
            if code not in proof_exceptions
        )
        expected_receipt_exceptions = (
            proof_exception_items + recovery_only_exceptions
        )
        if (
            len(proof_exception_items) != len(proof_exceptions)
            or self.exceptions != expected_receipt_exceptions
        ):
            raise ValueError(
                "receipt exceptions must exactly project proof and recovery evidence"
            )
        known_defect_count = sum(
            len(proof.known_defects) for proof in self.issue_proofs
        )
        if self.tcd_metrics.known_p2_dispositions != known_defect_count:
            raise ValueError("TCD P2 dispositions must match receipt defect evidence")
        if self.started_at > self.completed_at:
            raise ValueError("receipt completion must not precede start")
        for proof in self.issue_proofs:
            merge_identity = proof.merge_identity
            closure = proof.closure
            if merge_identity is not None and not (
                self.started_at
                <= merge_identity.merged_at
                <= self.completed_at
            ):
                raise ValueError(
                    "merge evidence must fall within receipt lifecycle chronology"
                )
            if closure is not None and not (
                self.started_at <= closure.closed_at <= self.completed_at
            ):
                raise ValueError(
                    "closure evidence must fall within receipt lifecycle chronology"
                )
            if (
                merge_identity is not None
                and closure is not None
                and merge_identity.merged_at > closure.closed_at
            ):
                raise ValueError(
                    "closure evidence must not precede merge chronology"
                )
        return self


def validate_delivery_receipt_evidence(
    receipt: DeliveryReceipt,
    *,
    initiation: DeliveryInitiation,
    plan: DeliveryPlan,
    worker_results: tuple[StructuredWorkerResult, ...],
    review_results: tuple[ReviewResult, ...],
) -> DeliveryReceipt:
    """Resolve every receipt reference against immutable evidence and exact scope."""

    expected_initiation_ref = ContractRef(
        schema_version=initiation.schema_version,
        contract_id=initiation.initiation_id,
        content_hash=initiation.content_hash,
    )
    expected_plan_ref = ContractRef(
        schema_version=plan.schema_version,
        contract_id=plan.plan_id,
        content_hash=plan.content_hash,
    )
    if receipt.initiation_ref != expected_initiation_ref:
        raise ValueError("receipt initiation ref does not resolve to supplied evidence")
    if receipt.plan_ref != expected_plan_ref:
        raise ValueError("receipt plan ref does not resolve to supplied evidence")
    validate_delivery_plan_evidence(plan, initiation=initiation)
    if receipt.requested_scope != initiation.requested_scope:
        raise ValueError("receipt requested scope does not match initiation")
    if receipt.final_scope != plan.final_scope:
        raise ValueError("receipt final scope does not match plan")

    workers = {item.result_id: item for item in worker_results}
    reviews = {item.result_id: item for item in review_results}
    if len(workers) != len(worker_results) or len(reviews) != len(review_results):
        raise ValueError("structured result IDs must be unique")
    used_workers: set[str] = set()
    used_reviews: set[str] = set()
    proof_outcomes: list[
        Literal["delivered", "blocked", "failed", "cancelled"]
    ] = []
    planned_scope = {item.scope_key: item for item in plan.final_scope}
    for proof in receipt.issue_proofs:
        worker = workers.get(proof.worker_result_ref.contract_id)
        review = (
            reviews.get(proof.review_result_ref.contract_id)
            if proof.review_result_ref is not None
            else None
        )
        if worker is None or (
            proof.review_result_ref is not None and review is None
        ):
            raise ValueError("receipt proof references unresolved structured evidence")
        if proof.worker_result_ref != ContractRef(
            schema_version=worker.schema_version,
            contract_id=worker.result_id,
            content_hash=worker.content_hash,
        ):
            raise ValueError("worker result ref hash does not match supplied evidence")
        if review is not None:
            expected_review_ref = ContractRef(
                schema_version=review.schema_version,
                contract_id=review.result_id,
                content_hash=review.content_hash,
            )
            if proof.review_result_ref != expected_review_ref:
                raise ValueError(
                    "review result ref hash does not match supplied evidence"
                )
        pull_request_number = (
            proof.merge_identity.pull_request_number
            if proof.merge_identity is not None
            else worker.pull_request_number
        )
        if (
            worker.run_id != receipt.run_id
            or worker.plan_ref != expected_plan_ref
            or planned_scope.get(proof.issue.scope_key) != proof.issue
            or worker.issue != proof.issue
            or worker.exact_head_sha != proof.exact_head_sha
            or worker.pull_request_number != pull_request_number
            or worker.exceptions != proof.exceptions
            or (
                proof.closure is not None
                and (
                    proof.closure.repository.casefold()
                    != proof.issue.repository.casefold()
                    or proof.closure.pull_request_number
                    != pull_request_number
                    or proof.closure.exact_head_sha != proof.exact_head_sha
                )
            )
        ):
            raise ValueError(
                "receipt proof does not match worker run, plan, scope, PR, head, or exceptions"
            )
        if receipt.terminal_outcome == "delivered" and worker.status != "completed":
            raise ValueError("delivered receipt requires completed worker evidence")
        if review is not None:
            p2_finding_hashes = {
                canonical_hash(item)
                for item in review.findings
                if item.severity == "P2"
            }
            if (
                review.run_id != receipt.run_id
                or review.plan_ref != expected_plan_ref
                or review.issue != proof.issue
                or review.exact_head_sha != proof.exact_head_sha
                or review.pull_request_number != pull_request_number
                or review.disposition != proof.review_disposition
                or review.policy_profile != plan.policy_profile
                or set(review.known_defect_refs)
                != {item.registry_ref for item in proof.known_defects}
                or p2_finding_hashes
                != {item.finding_hash for item in proof.known_defects}
            ):
                raise ValueError(
                    "receipt proof does not match review, policy, or P2 evidence"
                )
            used_reviews.add(review.result_id)
        elif proof.review_disposition is not None or proof.known_defects:
            raise ValueError("receipt proof carries review evidence without a review")
        proof_is_delivered = (
            worker.status == "completed"
            and proof.merge_identity is not None
            and proof.closure is not None
            and bool(proof.check_evidence)
            and all(item.status == "passed" for item in proof.check_evidence)
            and proof.review_disposition not in {None, "reject"}
            and not proof.exceptions
        )
        if proof_is_delivered:
            proof_outcomes.append("delivered")
        elif worker.status != "completed":
            proof_outcomes.append(worker.status)
        else:
            exception_kinds = {item.kind for item in proof.exceptions}
            if not exception_kinds:
                raise ValueError(
                    "non-delivered completed worker proof requires a typed exception"
                )
            if exception_kinds.intersection(
                {"malformed_result", "external_state_unknown", "execution_failed"}
            ):
                proof_outcomes.append("failed")
            elif "cancelled" in exception_kinds:
                proof_outcomes.append("cancelled")
            else:
                proof_outcomes.append("blocked")
        used_workers.add(worker.result_id)
    if used_workers != set(workers) or used_reviews != set(reviews):
        raise ValueError("supplied structured evidence must be used exactly once")
    if all(outcome == "delivered" for outcome in proof_outcomes):
        expected_terminal_outcome = "delivered"
    elif "delivered" in proof_outcomes:
        expected_terminal_outcome = "partially_delivered"
    elif "failed" in proof_outcomes:
        expected_terminal_outcome = "failed"
    elif "cancelled" in proof_outcomes:
        expected_terminal_outcome = "cancelled"
    else:
        expected_terminal_outcome = "blocked"
    if receipt.terminal_outcome != expected_terminal_outcome:
        raise ValueError(
            "receipt terminal outcome contradicts resolved issue proofs"
        )
    return receipt


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
            source = bytes(raw) if not isinstance(raw, str) else raw.encode("utf-8")
            payload = json.loads(
                source,
                object_pairs_hook=_reject_duplicate_json_keys,
            )
            encoded = canonical_json(payload).encode("utf-8")
    except json.JSONDecodeError as exc:
        raise ValueError("delivery contract must be one JSON object") from exc
    except TypeError as exc:
        raise ValueError("delivery contract must be one JSON object") from exc
    except ValueError:
        raise
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
    "delivery_effect_input_hash",
    "delivery_initiation_approval_hash",
    "parse_delivery_contract",
    "validate_delivery_plan_evidence",
    "validate_delivery_receipt_evidence",
    "validate_reducer_effect_evidence",
    "validate_reducer_event_evidence",
]
