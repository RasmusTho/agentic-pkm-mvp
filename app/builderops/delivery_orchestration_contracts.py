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
    BeforeValidator,
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


def _normalize_repository_id(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().casefold()
    return value


RepositoryId = Annotated[
    str,
    BeforeValidator(_normalize_repository_id),
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[a-z0-9_.-]+/[a-z0-9_.-]+$",
    ),
]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
GitSha = Annotated[
    str,
    StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$"),
]
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
EffectOutcomeState: TypeAlias = Literal[
    "claimed",
    "worker_launched",
    "checks_passed",
    "review_recorded",
    "merged",
    "closed",
    "known_defect_recorded",
    "receipt_recorded",
    "failed",
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
        if self.source_refs != tuple(
            sorted(
                self.source_refs,
                key=lambda item: (item.source_type, item.source_id),
            )
        ):
            raise ValueError(
                "provenance source refs must use canonical sorted order"
            )
        return self


class ContractRef(_StrictFrozenModel):
    schema_version: NonEmptyStr
    contract_id: NonEmptyStr
    content_hash: Sha256


class IssueScope(_StrictFrozenModel):
    repository: RepositoryId
    issue_number: PositiveInt
    authority_id: NonEmptyStr
    contract_hash: Sha256

    @model_validator(mode="after")
    def _validate_authority_id(self) -> IssueScope:
        expected = f"github:{self.repository}/issues/{self.issue_number}"
        if self.authority_id != expected:
            raise ValueError(
                "issue scope authority ID must bind repository and issue"
            )
        return self

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
    required_check_names: tuple[NonEmptyStr, ...]

    @model_validator(mode="after")
    def _validate_required_checks(self) -> PolicyProfile:
        if not self.required_check_names:
            raise ValueError("policy profile must name required delivery checks")
        _require_unique(self.required_check_names, "required check names")
        if self.required_check_names != tuple(
            sorted(self.required_check_names)
        ):
            raise ValueError(
                "required check names must use canonical sorted order"
            )
        return self


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
        if self.source_refs != tuple(
            sorted(
                self.source_refs,
                key=lambda item: (item.source_type, item.source_id),
            )
        ):
            raise ValueError(
                "approval source refs must use canonical sorted order"
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
        if self.approval_evidence.approved_at > self.provenance.created_at:
            raise ValueError(
                "initiation approval must precede initiation provenance"
            )
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
        if self.requested_scope != tuple(
            sorted(self.requested_scope, key=lambda item: item.scope_key)
        ):
            raise ValueError("requested scope must use canonical sorted order")
        if self.exclusions != tuple(
            sorted(self.exclusions, key=lambda item: item.scope_key)
        ):
            raise ValueError("scope exclusions must use canonical sorted order")
        if self.source_authorities != tuple(
            sorted(
                self.source_authorities,
                key=lambda item: item.authority_id,
            )
        ):
            raise ValueError(
                "source authorities must use canonical sorted order"
            )
        if any(
            item.observed_at > self.approval_evidence.approved_at
            for item in self.source_authorities
        ):
            raise ValueError(
                "source authority observations must precede approval"
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
        if self.issues != tuple(
            sorted(self.issues, key=lambda item: item.scope_key)
        ):
            raise ValueError("wave issues must use canonical sorted order")
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
        if self.final_scope != tuple(
            sorted(self.final_scope, key=lambda item: item.scope_key)
        ):
            raise ValueError("final scope must use canonical sorted order")
        if self.exclusions != tuple(
            sorted(self.exclusions, key=lambda item: item.scope_key)
        ):
            raise ValueError("scope exclusions must use canonical sorted order")
        if self.input_authorities != tuple(
            sorted(
                self.input_authorities,
                key=lambda item: item.authority_id,
            )
        ):
            raise ValueError(
                "input authorities must use canonical sorted order"
            )
        if self.expected_states != tuple(
            sorted(
                self.expected_states,
                key=lambda item: item.issue.scope_key,
            )
        ):
            raise ValueError(
                "expected states must use canonical sorted order"
            )
        if any(
            item.observed_at > self.provenance.created_at
            for item in self.input_authorities
        ):
            raise ValueError(
                "input authority observations must precede plan provenance"
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
        if self.effect_allowlist != tuple(sorted(self.effect_allowlist)):
            raise ValueError(
                "effect allowlist must use canonical sorted order"
            )
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
    if initiation.provenance.created_at > plan.provenance.created_at:
        raise ValueError("plan provenance must follow initiation provenance")
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
        if self.evidence_refs != tuple(sorted(self.evidence_refs)):
            raise ValueError(
                "exception evidence refs must use canonical sorted order"
            )
        return self


_SUCCESS_OUTCOME_BY_EFFECT: dict[EffectClass, EffectOutcomeState] = {
    "claim_issue": "claimed",
    "launch_worker": "worker_launched",
    "await_ci": "checks_passed",
    "request_review": "review_recorded",
    "merge_pull_request": "merged",
    "close_issue": "closed",
    "record_known_defect": "known_defect_recorded",
    "record_delivery_receipt": "receipt_recorded",
}


class EffectOutcomeEvidence(_StrictFrozenModel):
    effect_class: EffectClass
    effect_idempotency_key: NonEmptyStr
    outcome_state: EffectOutcomeState
    outcome_keys: tuple[NonEmptyStr, ...]
    observed_at: UtcTimestamp
    evidence_refs: tuple[NonEmptyStr, ...]

    @model_validator(mode="after")
    def _validate_outcome(self) -> EffectOutcomeEvidence:
        if not self.outcome_keys or not self.evidence_refs:
            raise ValueError("effect outcome must carry keys and evidence")
        _require_unique(self.outcome_keys, "effect outcome keys")
        _require_unique(self.evidence_refs, "effect outcome evidence refs")
        if self.outcome_keys != tuple(sorted(self.outcome_keys)):
            raise ValueError(
                "effect outcome keys must use canonical sorted order"
            )
        if self.evidence_refs != tuple(sorted(self.evidence_refs)):
            raise ValueError(
                "effect outcome evidence refs must use canonical sorted order"
            )
        return self


def delivery_event_input_hash(
    *,
    run_id: str,
    plan_ref: ContractRef,
    sequence: int,
    event_type: str,
    subject_authority: AuthoritySnapshot | None,
    effect_ref: ContractRef | None,
    result_ref: ContractRef | None,
    exception: DeliveryException | None,
    effect_outcome: EffectOutcomeEvidence | None = None,
) -> str:
    """Hash the complete semantic input to one reducer event."""

    authority_semantics = (
        {
            "authority_type": subject_authority.authority_type,
            "authority_id": subject_authority.authority_id,
            "content_hash": subject_authority.content_hash,
            "observed_state": subject_authority.observed_state,
            "observed_labels": list(subject_authority.observed_labels),
        }
        if subject_authority is not None
        else None
    )
    return canonical_hash(
        {
            "run_id": run_id,
            "plan_ref": plan_ref.model_dump(mode="json"),
            "sequence": sequence,
            "event_type": event_type,
            "subject_authority": authority_semantics,
            "effect_ref": (
                effect_ref.model_dump(mode="json")
                if effect_ref is not None
                else None
            ),
            "result_ref": (
                result_ref.model_dump(mode="json")
                if result_ref is not None
                else None
            ),
            "exception": (
                exception.model_dump(mode="json")
                if exception is not None
                else None
            ),
            "effect_outcome": (
                effect_outcome.model_dump(mode="json")
                if effect_outcome is not None
                else None
            ),
        }
    )


def delivery_event_id(input_hash: str) -> str:
    """Derive the sole event identity from validated semantic input."""

    return f"builderops.delivery-event.v1:{input_hash}"


class ReducerEvent(CanonicalDeliveryContract):
    contract_family: ClassVar[str] = "reducer"
    schema_version: Literal[
        "builderops.delivery-reducer-event.v1"
    ] = REDUCER_EVENT_VERSION
    event_id: NonEmptyStr
    input_hash: Sha256
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
    effect_outcome: EffectOutcomeEvidence | None = None
    provenance: Provenance

    @model_validator(mode="after")
    def _validate_event(self) -> ReducerEvent:
        if self.plan_ref.schema_version != DELIVERY_PLAN_VERSION:
            raise ValueError("reducer event must bind DeliveryPlan.v1")
        if (self.event_type == "run_started") != (self.sequence == 0):
            raise ValueError(
                "run-started must be sequence zero and later events must not"
            )
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
        is_effect_result = self.event_type in {
            "effect_succeeded",
            "effect_failed",
        }
        if (self.effect_outcome is not None) != is_effect_result:
            raise ValueError(
                "effect result events must carry typed outcome evidence"
            )
        if (
            self.subject_authority is not None
            and self.subject_authority.observed_at
            > self.provenance.created_at
        ):
            raise ValueError(
                "event authority observation must precede event provenance"
            )
        expected_input_hash = delivery_event_input_hash(
            run_id=self.run_id,
            plan_ref=self.plan_ref,
            sequence=self.sequence,
            event_type=self.event_type,
            subject_authority=self.subject_authority,
            effect_ref=self.effect_ref,
            result_ref=self.result_ref,
            exception=self.exception,
            effect_outcome=self.effect_outcome,
        )
        if self.input_hash != expected_input_hash:
            raise ValueError("reducer event input hash must bind semantic input")
        if self.event_id != delivery_event_id(expected_input_hash):
            raise ValueError(
                "reducer event identity must derive from semantic input"
            )
        return self


def delivery_effect_input_hash(
    *,
    run_id: str,
    plan_ref: ContractRef,
    effect_class: EffectClass,
    issue: IssueScope,
    pull_request_number: int | None,
    exact_head_sha: str | None,
    expected_authorities: tuple[AuthoritySnapshot, ...],
    expected_outcome_keys: tuple[str, ...],
    known_defect_registry_ref: str | None = None,
    known_defect_finding_hash: str | None = None,
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
            "effect_class": effect_class,
            "issue": issue.model_dump(mode="json"),
            "pull_request_number": pull_request_number,
            "exact_head_sha": exact_head_sha,
            "expected_authorities": authority_semantics,
            "expected_outcome_keys": list(expected_outcome_keys),
            "known_defect_registry_ref": known_defect_registry_ref,
            "known_defect_finding_hash": known_defect_finding_hash,
        }
    )


def delivery_effect_idempotency_key(input_hash: str) -> str:
    """Derive the sole idempotency identity from a validated semantic input hash."""

    return f"builderops.delivery-effect.v1:{input_hash}"


def delivery_effect_expected_outcome_keys(
    *,
    effect_class: EffectClass,
    run_id: str,
    issue: IssueScope,
    pull_request_number: int | None,
    required_check_names: tuple[str, ...],
    known_defect_registry_ref: str | None = None,
    known_defect_finding_hash: str | None = None,
) -> tuple[str, ...]:
    """Derive carrier-neutral logical outcome identities for an effect."""

    if effect_class == "claim_issue":
        return (f"{issue.authority_id}#claimed",)
    if effect_class == "launch_worker":
        return (f"builderops:worker:{run_id}:{issue.authority_id}",)
    if effect_class == "await_ci":
        return tuple(
            f"check-name:{name}" for name in sorted(required_check_names)
        )
    if effect_class == "request_review":
        return (f"builderops:review:{run_id}:{issue.authority_id}",)
    if effect_class == "merge_pull_request":
        return (
            f"github:{issue.repository}/pulls/{pull_request_number}",
        )
    if effect_class == "close_issue":
        return (f"{issue.authority_id}#closed",)
    if effect_class == "record_known_defect":
        if (
            known_defect_registry_ref is None
            or known_defect_finding_hash is None
        ):
            raise ValueError(
                "known-defect effect requires exact registry and finding identity"
            )
        return (
            "builderops:known-defect:"
            f"{known_defect_registry_ref}:{known_defect_finding_hash}",
        )
    return (f"builderops:receipt:{run_id}:{issue.authority_id}",)


class ReducerEffect(CanonicalDeliveryContract):
    contract_family: ClassVar[str] = "reducer"
    schema_version: Literal[
        "builderops.delivery-reducer-effect.v1"
    ] = REDUCER_EFFECT_VERSION
    effect_id: NonEmptyStr
    run_id: NonEmptyStr
    plan_ref: ContractRef
    causal_event: ReducerEvent
    sequence: PositiveInt
    effect_class: EffectClass
    issue: IssueScope
    pull_request_number: PositiveInt | None
    exact_head_sha: GitSha | None
    expected_authorities: tuple[AuthoritySnapshot, ...]
    expected_outcome_keys: tuple[NonEmptyStr, ...]
    known_defect_registry_ref: NonEmptyStr | None = None
    known_defect_finding_hash: Sha256 | None = None
    idempotency_key: NonEmptyStr
    input_hash: Sha256
    requires_live_authority_check: Literal[True] = True
    authorized_by_plan_only: Literal[False] = False
    provenance: Provenance

    @model_validator(mode="after")
    def _validate_effect(self) -> ReducerEffect:
        if self.plan_ref.schema_version != DELIVERY_PLAN_VERSION:
            raise ValueError("reducer effect must bind DeliveryPlan.v1")
        if (
            self.causal_event.run_id != self.run_id
            or self.causal_event.plan_ref != self.plan_ref
            or self.causal_event.sequence >= self.sequence
        ):
            raise ValueError("reducer effect must embed an earlier causal event")
        if not self.expected_authorities:
            raise ValueError("reducer effect must bind expected live authority")
        if any(
            item.observed_at > self.provenance.created_at
            for item in self.expected_authorities
        ):
            raise ValueError(
                "effect authority observations must precede effect provenance"
            )
        _require_unique(
            tuple(item.authority_id for item in self.expected_authorities),
            "effect expected authority IDs",
        )
        _require_unique(
            self.expected_outcome_keys,
            "effect expected outcome keys",
        )
        if tuple(
            item.authority_id for item in self.expected_authorities
        ) != tuple(
            sorted(item.authority_id for item in self.expected_authorities)
        ):
            raise ValueError(
                "effect expected authorities must use canonical sorted order"
            )
        if self.expected_outcome_keys != tuple(
            sorted(self.expected_outcome_keys)
        ):
            raise ValueError(
                "effect expected outcome keys must use canonical sorted order"
            )
        if not any(
            authority.authority_id == self.issue.authority_id
            and authority.content_hash == self.issue.contract_hash
            for authority in self.expected_authorities
        ):
            raise ValueError("effect authority snapshots must bind the issue")
        causal_subject = self.causal_event.subject_authority
        if causal_subject is None:
            if self.causal_event.event_type != "run_started":
                raise ValueError(
                    "subjectless effect cause must be the run-started event"
                )
        elif self.expected_authorities != (causal_subject,):
            raise ValueError(
                "effect authority must bind the current causal event state"
            )
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
        known_defect_target_fields = (
            self.known_defect_registry_ref is not None,
            self.known_defect_finding_hash is not None,
        )
        if (
            self.effect_class == "record_known_defect"
            and known_defect_target_fields != (True, True)
        ) or (
            self.effect_class != "record_known_defect"
            and known_defect_target_fields != (False, False)
        ):
            raise ValueError(
                "only known-defect effects require an exact defect target"
            )
        if (
            self.effect_class == "record_known_defect"
            and self.known_defect_registry_ref is not None
            and re.fullmatch(
                (
                    rf"registry:{re.escape(self.issue.repository)}/issues/"
                    r"[1-9][0-9]*:KD-[0-9A-F]{12}"
                ),
                self.known_defect_registry_ref,
            )
            is None
        ):
            raise ValueError(
                "known-defect target must use canonical repository registry identity"
            )
        expected_input_hash = delivery_effect_input_hash(
            run_id=self.run_id,
            plan_ref=self.plan_ref,
            effect_class=self.effect_class,
            issue=self.issue,
            pull_request_number=self.pull_request_number,
            exact_head_sha=self.exact_head_sha,
            expected_authorities=self.expected_authorities,
            expected_outcome_keys=self.expected_outcome_keys,
            known_defect_registry_ref=self.known_defect_registry_ref,
            known_defect_finding_hash=self.known_defect_finding_hash,
        )
        if self.input_hash != expected_input_hash:
            raise ValueError("reducer effect input hash must bind exact semantic input")
        if self.idempotency_key != delivery_effect_idempotency_key(
            expected_input_hash
        ):
            raise ValueError(
                "reducer effect idempotency key must derive from semantic input"
            )
        if self.effect_id != self.idempotency_key:
            raise ValueError(
                "reducer effect identity must equal its logical idempotency key"
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
        _require_unique(
            tuple(item.code for item in self.exceptions),
            "worker exceptions",
        )
        if self.changed_files != tuple(sorted(self.changed_files)):
            raise ValueError("changed files must use canonical sorted order")
        if self.validations != tuple(
            sorted(self.validations, key=lambda item: item.name)
        ):
            raise ValueError(
                "validation evidence must use canonical sorted order"
            )
        if self.exceptions != tuple(
            sorted(self.exceptions, key=lambda item: item.code)
        ):
            raise ValueError(
                "worker exceptions must use canonical sorted order"
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
                item.exact_head_sha != self.exact_head_sha
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
        if self.evidence_refs != tuple(sorted(self.evidence_refs)):
            raise ValueError(
                "review finding evidence refs must use canonical sorted order"
            )
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
        if self.findings != tuple(
            sorted(self.findings, key=lambda item: item.finding_id)
        ):
            raise ValueError(
                "review findings must use canonical sorted order"
            )
        if self.known_defect_refs != tuple(sorted(self.known_defect_refs)):
            raise ValueError(
                "known defect refs must use canonical sorted order"
            )
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
        if len(self.known_defect_refs) > p2_findings:
            raise ValueError(
                "review cannot carry more known-defect refs than P2 findings"
            )
        return self


def validate_reducer_effect_evidence(
    effect: ReducerEffect,
    *,
    plan: DeliveryPlan,
    prior_effects: tuple[ReducerEffect, ...] = (),
    worker_results: tuple[StructuredWorkerResult, ...] = (),
    review_results: tuple[ReviewResult, ...] = (),
) -> ReducerEffect:
    """Resolve an effect proposal against its immutable plan and exact scope."""

    expected_plan_ref = ContractRef(
        schema_version=plan.schema_version,
        contract_id=plan.plan_id,
        content_hash=plan.content_hash,
    )
    if effect.plan_ref != expected_plan_ref:
        raise ValueError("reducer effect does not bind the supplied plan")
    if (
        effect.causal_event.run_id != effect.run_id
        or effect.causal_event.plan_ref != expected_plan_ref
    ):
        raise ValueError(
            "reducer effect must resolve the exact run-started event"
        )
    causal_event = effect.causal_event
    causal_effect = (
        next(
            (
                item
                for item in prior_effects
                if causal_event.effect_ref is not None
                and item.effect_id == causal_event.effect_ref.contract_id
            ),
            None,
        )
        if causal_event.effect_ref is not None
        else None
    )
    causal_worker = (
        next(
            (
                item
                for item in worker_results
                if causal_event.result_ref is not None
                and item.result_id == causal_event.result_ref.contract_id
            ),
            None,
        )
        if causal_event.result_ref is not None
        and causal_event.result_ref.schema_version == WORKER_RESULT_VERSION
        else None
    )
    causal_review = (
        next(
            (
                item
                for item in review_results
                if causal_event.result_ref is not None
                and item.result_id == causal_event.result_ref.contract_id
            ),
            None,
        )
        if causal_event.result_ref is not None
        and causal_event.result_ref.schema_version == REVIEW_RESULT_VERSION
        else None
    )
    validate_reducer_event_evidence(
        causal_event,
        plan=plan,
        effect=causal_effect,
        worker_result=causal_worker,
        review_result=causal_review,
        prior_effects=prior_effects,
        worker_results=worker_results,
        review_results=review_results,
    )
    causal_pr_and_head: tuple[int | None, str | None] | None = None
    if causal_effect is not None:
        causal_pr_and_head = (
            causal_effect.pull_request_number,
            causal_effect.exact_head_sha,
        )
    elif causal_worker is not None:
        causal_pr_and_head = (
            causal_worker.pull_request_number,
            causal_worker.exact_head_sha,
        )
    elif causal_review is not None:
        causal_pr_and_head = (
            causal_review.pull_request_number,
            causal_review.exact_head_sha,
        )
    if causal_pr_and_head is not None and causal_pr_and_head != (
        effect.pull_request_number,
        effect.exact_head_sha,
    ):
        raise ValueError(
            "reducer effect PR and head must match its causal evidence"
        )
    if effect.provenance.created_at < plan.provenance.created_at:
        raise ValueError("reducer effect must follow plan provenance")
    if (
        effect.provenance.created_at
        < effect.causal_event.provenance.created_at
    ):
        raise ValueError("reducer effect must follow the run-started event")
    planned_scope = {item.scope_key: item for item in plan.final_scope}
    if planned_scope.get(effect.issue.scope_key) != effect.issue:
        raise ValueError("reducer effect issue is outside exact plan scope")
    if effect.effect_class not in plan.effect_allowlist:
        raise ValueError("reducer effect class is outside the plan allowlist")
    expected_outcome_keys = delivery_effect_expected_outcome_keys(
        effect_class=effect.effect_class,
        run_id=effect.run_id,
        issue=effect.issue,
        pull_request_number=effect.pull_request_number,
        required_check_names=plan.policy_profile.required_check_names,
        known_defect_registry_ref=effect.known_defect_registry_ref,
        known_defect_finding_hash=effect.known_defect_finding_hash,
    )
    if effect.expected_outcome_keys != expected_outcome_keys:
        raise ValueError(
            "reducer effect outcome keys must match effect-class semantics"
        )
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
    causal_subject = effect.causal_event.subject_authority
    planned_authorities = tuple(
        authority
        for authority in plan.input_authorities
        if authority.authority_id == effect.issue.authority_id
    )
    if (
        expected_state is None
        or len(matching_authorities) != 1
        or len(planned_authorities) != 1
        or (
            causal_subject is None
            and (
                len(planned_authorities) != 1
                or not _same_authority_state(
                    matching_authorities[0],
                    planned_authorities[0],
                )
            )
        )
        or (
            causal_subject is not None
            and not _same_authority_state(
                matching_authorities[0],
                causal_subject,
            )
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
    prior_effects: tuple[ReducerEffect, ...] = (),
    worker_results: tuple[StructuredWorkerResult, ...] = (),
    review_results: tuple[ReviewResult, ...] = (),
) -> ReducerEvent:
    """Resolve reducer-event references and subject authority against exact evidence."""

    expected_plan_ref = ContractRef(
        schema_version=plan.schema_version,
        contract_id=plan.plan_id,
        content_hash=plan.content_hash,
    )
    if event.plan_ref != expected_plan_ref:
        raise ValueError("reducer event does not bind the supplied plan")
    if event.provenance.created_at < plan.provenance.created_at:
        raise ValueError("reducer event must follow plan provenance")

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
        validate_reducer_effect_evidence(
            effect,
            plan=plan,
            prior_effects=tuple(
                item
                for item in prior_effects
                if item.sequence < effect.sequence
            ),
            worker_results=worker_results,
            review_results=review_results,
        )
        outcome = event.effect_outcome
        assert outcome is not None
        expected_outcome_state = (
            _SUCCESS_OUTCOME_BY_EFFECT[effect.effect_class]
            if event.event_type == "effect_succeeded"
            else "failed"
        )
        if (
            effect.run_id != event.run_id
            or event.sequence <= effect.sequence
            or event.provenance.created_at < effect.provenance.created_at
            or event.subject_authority is None
            or event.subject_authority.authority_id
            != effect.issue.authority_id
            or event.subject_authority.content_hash
            != effect.issue.contract_hash
            or event.subject_authority.observed_at
            < effect.provenance.created_at
            or outcome.effect_class != effect.effect_class
            or outcome.effect_idempotency_key != effect.idempotency_key
            or outcome.outcome_state != expected_outcome_state
            or outcome.outcome_keys != effect.expected_outcome_keys
            or outcome.observed_at < effect.provenance.created_at
            or outcome.observed_at > event.provenance.created_at
        ):
            raise ValueError(
                "reducer effect-result event must match run and carry "
                "exact typed post-effect outcome evidence"
            )
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
            or event.provenance.created_at
            < worker_result.provenance.created_at
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
            or event.provenance.created_at
            < review_result.provenance.created_at
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
        subject_matches = (
            subject is not None
            and planned_authority is not None
            and (
                event.event_type in {"effect_succeeded", "effect_failed"}
                or _same_authority_state(subject, planned_authority)
            )
        )
        if not subject_matches:
            raise ValueError(
                "reducer event subject contradicts referenced evidence"
            )
    return event


class CheckEvidence(_StrictFrozenModel):
    check_name: NonEmptyStr
    repository: RepositoryId
    check_run_id: NonEmptyStr
    authority_id: NonEmptyStr
    pull_request_number: PositiveInt
    status: Literal["passed", "failed", "skipped"]
    exact_head_sha: GitSha
    completed_at: UtcTimestamp
    evidence_ref: NonEmptyStr

    @model_validator(mode="after")
    def _validate_authority_id(self) -> CheckEvidence:
        expected = (
            f"github:{self.repository}/check-runs/{self.check_run_id}"
        )
        if self.authority_id != expected:
            raise ValueError(
                "check authority ID must bind repository and check run"
            )
        return self


class KnownDefectRef(_StrictFrozenModel):
    repository: RepositoryId
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
        expected_ref = (
            f"registry:{self.repository}/issues/{self.issue_number}:"
            f"{self.defect_id}"
        )
        if self.registry_ref != expected_ref:
            raise ValueError(
                "known defect registry ref must bind issue number and defect ID"
            )
        return self


class MergeIdentity(_StrictFrozenModel):
    repository: RepositoryId
    authority_id: NonEmptyStr
    pull_request_number: PositiveInt
    exact_head_sha: GitSha
    base_sha: GitSha
    merge_commit_sha: GitSha
    merged_at: UtcTimestamp
    merged_by: ActorIdentity

    @model_validator(mode="after")
    def _validate_authority_id(self) -> MergeIdentity:
        expected = (
            f"github:{self.repository}/pulls/{self.pull_request_number}"
        )
        if self.authority_id != expected:
            raise ValueError(
                "merge authority ID must bind repository and pull request"
            )
        return self


class ClosureEvidence(_StrictFrozenModel):
    authority_id: NonEmptyStr
    repository: RepositoryId
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
    delivery_stage: Literal[
        "worker_terminal",
        "merge_ready",
        "merged",
        "closed",
    ]
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
        if self.check_evidence != tuple(
            sorted(self.check_evidence, key=lambda item: item.check_name)
        ):
            raise ValueError(
                "check evidence must use canonical sorted order"
            )
        if self.exact_head_sha is None and (
            self.check_evidence or self.merge_identity is not None
        ):
            raise ValueError("headless proof cannot carry checks or merge identity")
        if any(item.exact_head_sha != self.exact_head_sha for item in self.check_evidence):
            raise ValueError("check evidence must bind the exact head")
        if any(
            item.repository.casefold() != self.issue.repository.casefold()
            for item in self.check_evidence
        ):
            raise ValueError("check evidence must bind the proof repository")
        if self.merge_identity is not None:
            if self.merge_identity.exact_head_sha != self.exact_head_sha:
                raise ValueError("merge identity must bind the exact head")
            if (
                self.merge_identity.repository.casefold()
                != self.issue.repository.casefold()
            ):
                raise ValueError("merge identity must bind the proof repository")
            if self.merge_identity.pull_request_number < 1:
                raise ValueError("merge identity must bind a pull request")
        if self.delivery_stage == "closed":
            if self.merge_identity is None or self.closure is None:
                raise ValueError(
                    "closed delivery stage requires merge and closure evidence"
                )
        elif self.delivery_stage == "merged":
            if self.merge_identity is None or self.closure is not None:
                raise ValueError(
                    "merged delivery stage requires merge without closure"
                )
        elif self.delivery_stage == "merge_ready":
            if (
                self.exact_head_sha is None
                or self.merge_identity is not None
                or self.closure is not None
                or not self.check_evidence
                or self.review_result_ref is None
            ):
                raise ValueError(
                    "merge-ready delivery stage requires head, checks, and review "
                    "without merge or closure"
                )
        elif self.merge_identity is not None or self.closure is not None:
            raise ValueError(
                "worker-terminal delivery stage cannot carry merge or closure"
            )
        if self.closure is not None and self.closure.issue_number != self.issue.issue_number:
            raise ValueError("closure evidence must bind the proof issue")
        if self.closure is not None:
            if self.merge_identity is None:
                raise ValueError(
                    "closure evidence requires matching merge evidence"
                )
            if self.closure.repository.casefold() != self.issue.repository.casefold():
                raise ValueError("closure evidence must bind the proof repository")
            if self.closure.authority_id != self.issue.authority_id:
                raise ValueError("closure evidence must bind the issue authority")
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
        _require_unique(
            tuple(item.code for item in self.exceptions),
            "proof exceptions",
        )
        if self.known_defects != tuple(
            sorted(self.known_defects, key=lambda item: item.registry_ref)
        ):
            raise ValueError(
                "known defect evidence must use canonical sorted order"
            )
        if self.exceptions != tuple(
            sorted(self.exceptions, key=lambda item: item.code)
        ):
            raise ValueError(
                "proof exceptions must use canonical sorted order"
            )
        if any(
            item.repository.casefold() != self.issue.repository.casefold()
            for item in self.known_defects
        ):
            raise ValueError(
                "known defect evidence must bind the proof repository"
            )
        return self


class RecoveryAuthorityReadback(_StrictFrozenModel):
    effect_idempotency_key: NonEmptyStr
    authority_id: NonEmptyStr
    issue: IssueScope
    pull_request_number: PositiveInt | None
    exact_head_sha: GitSha | None
    observed_state: Literal["merged", "closed", "unchanged", "unknown"]
    observed_labels: tuple[NonEmptyStr, ...]
    observed_at: UtcTimestamp
    evidence_ref: NonEmptyStr

    @model_validator(mode="after")
    def _validate_labels(self) -> RecoveryAuthorityReadback:
        _require_unique(self.observed_labels, "recovery observed labels")
        if self.observed_labels != tuple(sorted(self.observed_labels)):
            raise ValueError(
                "recovery observed labels must use canonical sorted order"
            )
        return self


class RecoveryStep(_StrictFrozenModel):
    step_index: NonNegativeInt
    exception_kind: ExceptionKind
    exception_code: NonEmptyStr
    exception_hash: Sha256
    effect_ref: ContractRef
    effect_class: EffectClass
    issue: IssueScope
    action: NonEmptyStr
    authority_readbacks: tuple[RecoveryAuthorityReadback, ...]
    outcome_evidence: EffectOutcomeEvidence
    outcome: Literal["reconciled", "retry_scheduled", "blocked", "failed"]
    occurred_at: UtcTimestamp

    @model_validator(mode="after")
    def _validate_readbacks(self) -> RecoveryStep:
        if self.effect_ref.schema_version != REDUCER_EFFECT_VERSION:
            raise ValueError("recovery step must bind a reducer effect")
        expected_outcome_state = (
            _SUCCESS_OUTCOME_BY_EFFECT[self.effect_class]
            if self.outcome == "reconciled"
            else "failed"
        )
        if (
            self.outcome_evidence.effect_class != self.effect_class
            or self.outcome_evidence.outcome_state
            != expected_outcome_state
            or self.outcome_evidence.observed_at > self.occurred_at
        ):
            raise ValueError(
                "recovery step must carry typed effect outcome evidence"
            )
        if not self.authority_readbacks:
            raise ValueError("recovery step must carry authority readback evidence")
        _require_unique(
            tuple(item.evidence_ref for item in self.authority_readbacks),
            "recovery authority readback evidence refs",
        )
        if self.authority_readbacks != tuple(
            sorted(
                self.authority_readbacks,
                key=lambda item: item.evidence_ref,
            )
        ):
            raise ValueError(
                "recovery readbacks must use canonical sorted order"
            )
        if any(item.issue != self.issue for item in self.authority_readbacks):
            raise ValueError("recovery readbacks must bind the exact step issue")
        if any(
            item.observed_at > self.occurred_at
            for item in self.authority_readbacks
        ):
            raise ValueError("recovery readback must not follow the recovery step")
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
        if self.requested_scope != tuple(
            sorted(self.requested_scope, key=lambda item: item.scope_key)
        ):
            raise ValueError(
                "receipt requested scope must use canonical sorted order"
            )
        if self.final_scope != tuple(
            sorted(self.final_scope, key=lambda item: item.scope_key)
        ):
            raise ValueError(
                "receipt final scope must use canonical sorted order"
            )
        if self.issue_proofs != tuple(
            sorted(
                self.issue_proofs,
                key=lambda item: item.issue.scope_key,
            )
        ):
            raise ValueError(
                "receipt issue proofs must use canonical sorted order"
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
                exception_by_code[step.exception_code].kind
                != step.exception_kind
                or canonical_hash(exception_by_code[step.exception_code])
                != step.exception_hash
                for step in self.recovery_history
            )
        ):
            raise ValueError("recovery history must bind typed receipt exceptions")
        delivered_proofs = tuple(
            proof.merge_identity is not None
            and proof.closure is not None
            and proof.delivery_stage == "closed"
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
                if (
                    not any(
                        proof.merge_identity is not None
                        for proof in self.issue_proofs
                    )
                    or all(delivered_proofs)
                ):
                    raise ValueError(
                        "partially delivered outcome requires incomplete merged proof"
                    )
            elif any(
                proof.merge_identity is not None or proof.closure is not None
                for proof in self.issue_proofs
            ):
                raise ValueError(
                    "blocked, failed, or cancelled outcome cannot carry merged proof"
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
        if self.completed_at > self.provenance.created_at:
            raise ValueError(
                "receipt provenance must not precede terminal completion"
            )
        elapsed_seconds = int(
            (
                datetime.strptime(self.completed_at, "%Y-%m-%dT%H:%M:%SZ")
                - datetime.strptime(self.started_at, "%Y-%m-%dT%H:%M:%SZ")
            ).total_seconds()
        )
        if self.tcd_metrics.lead_time_seconds != elapsed_seconds:
            raise ValueError(
                "TCD lead time must match receipt lifecycle chronology"
            )
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
        recovery_times = tuple(
            step.occurred_at for step in self.recovery_history
        )
        if any(
            occurred_at < self.started_at or occurred_at > self.completed_at
            for occurred_at in recovery_times
        ):
            raise ValueError(
                "recovery evidence must fall within receipt lifecycle chronology"
            )
        if recovery_times != tuple(sorted(recovery_times)):
            raise ValueError(
                "recovery evidence must use monotonic lifecycle chronology"
            )
        proof_by_scope = {
            proof.issue.scope_key: proof for proof in self.issue_proofs
        }
        for step in self.recovery_history:
            recovery_proof = proof_by_scope.get(step.issue.scope_key)
            if recovery_proof is None or recovery_proof.issue != step.issue:
                raise ValueError(
                    "recovery evidence must bind exact receipt scope"
                )
            matching_readbacks = tuple(
                readback
                for readback in step.authority_readbacks
                if readback.issue == step.issue
            )
            if (
                step.outcome != "reconciled"
                and any(
                    readback.observed_state in {"merged", "closed"}
                    for readback in matching_readbacks
                )
            ):
                raise ValueError(
                    "failed recovery cannot claim a successful authority outcome"
                )
            if (
                step.outcome == "reconciled"
                and step.effect_class == "merge_pull_request"
            ):
                if (
                    recovery_proof.merge_identity is None
                    or step.occurred_at
                    < recovery_proof.merge_identity.merged_at
                    or not any(
                        readback.observed_state == "merged"
                        and readback.authority_id
                        == recovery_proof.merge_identity.authority_id
                        and readback.pull_request_number
                        == recovery_proof.merge_identity.pull_request_number
                        and readback.exact_head_sha
                        == recovery_proof.merge_identity.exact_head_sha
                        and readback.observed_at
                        >= recovery_proof.merge_identity.merged_at
                        for readback in matching_readbacks
                    )
                ):
                    raise ValueError(
                        "merge recovery evidence must bind observed merge"
                    )
            if (
                step.outcome == "reconciled"
                and step.effect_class == "close_issue"
            ):
                if (
                    recovery_proof.closure is None
                    or step.occurred_at < recovery_proof.closure.closed_at
                    or not any(
                        readback.observed_state == "closed"
                        and readback.authority_id
                        == recovery_proof.closure.authority_id
                        and readback.pull_request_number
                        == recovery_proof.closure.pull_request_number
                        and readback.exact_head_sha
                        == recovery_proof.closure.exact_head_sha
                        and readback.observed_at
                        >= recovery_proof.closure.closed_at
                        for readback in matching_readbacks
                    )
                ):
                    raise ValueError(
                        "closure recovery evidence must bind observed closure"
                    )
        return self


def validate_delivery_receipt_evidence(
    receipt: DeliveryReceipt,
    *,
    initiation: DeliveryInitiation,
    plan: DeliveryPlan,
    worker_results: tuple[StructuredWorkerResult, ...],
    review_results: tuple[ReviewResult, ...],
    reducer_effects: tuple[ReducerEffect, ...],
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
    if not (
        initiation.approval_evidence.approved_at
        <= initiation.provenance.created_at
        <= plan.provenance.created_at
        <= receipt.started_at
    ):
        raise ValueError(
            "approval, initiation, plan, and receipt must use causal chronology"
        )

    workers = {item.result_id: item for item in worker_results}
    reviews = {item.result_id: item for item in review_results}
    effects = {item.effect_id: item for item in reducer_effects}
    effect_keys = {item.idempotency_key for item in reducer_effects}
    if (
        len(workers) != len(worker_results)
        or len(reviews) != len(review_results)
        or len(effects) != len(reducer_effects)
        or len(effect_keys) != len(reducer_effects)
    ):
        raise ValueError("structured result and effect IDs must be unique")
    proof_by_scope = {
        proof.issue.scope_key: proof for proof in receipt.issue_proofs
    }
    used_effects: set[str] = set()
    pr_bound_effect_classes = {
        "await_ci",
        "request_review",
        "merge_pull_request",
        "close_issue",
        "record_known_defect",
        "record_delivery_receipt",
    }
    for step in receipt.recovery_history:
        effect = effects.get(step.effect_ref.contract_id)
        proof = proof_by_scope[step.issue.scope_key]
        if effect is None or step.effect_ref != ContractRef(
            schema_version=effect.schema_version,
            contract_id=effect.effect_id,
            content_hash=effect.content_hash,
        ):
            raise ValueError("recovery effect ref does not resolve")
        validate_reducer_effect_evidence(
            effect,
            plan=plan,
            prior_effects=reducer_effects,
            worker_results=worker_results,
            review_results=review_results,
        )
        expected_pr: int | None = None
        if proof.merge_identity is not None:
            expected_pr = proof.merge_identity.pull_request_number
        else:
            for readback in step.authority_readbacks:
                if readback.pull_request_number is not None:
                    expected_pr = readback.pull_request_number
                    break
        if (
            effect.run_id != receipt.run_id
            or effect.plan_ref != expected_plan_ref
            or effect.effect_class != step.effect_class
            or effect.issue != step.issue
            or effect.provenance.created_at > step.occurred_at
            or (
                effect.effect_class in pr_bound_effect_classes
                and (
                    effect.pull_request_number != expected_pr
                    or effect.exact_head_sha != proof.exact_head_sha
                )
            )
        ):
            raise ValueError(
                "recovery effect must bind run, plan, class, issue, PR, head, "
                "and chronology"
            )
        if any(
            readback.effect_idempotency_key != effect.idempotency_key
            or readback.observed_at < effect.provenance.created_at
            or readback.pull_request_number != effect.pull_request_number
            or readback.exact_head_sha != effect.exact_head_sha
            for readback in step.authority_readbacks
        ):
            raise ValueError(
                "recovery readbacks must bind the exact effect and follow it"
            )
        if (
            step.outcome_evidence.effect_idempotency_key
            != effect.idempotency_key
            or step.outcome_evidence.outcome_keys
            != effect.expected_outcome_keys
            or step.outcome_evidence.observed_at
            < effect.provenance.created_at
        ):
            raise ValueError(
                "recovery outcome must exactly cover the logical effect"
            )
        used_effects.add(effect.effect_id)
    if used_effects != set(effects):
        raise ValueError("every supplied recovery effect must be referenced")
    used_workers: set[str] = set()
    used_reviews: set[str] = set()
    proof_outcomes: list[
        Literal[
            "delivered",
            "partially_delivered",
            "blocked",
            "failed",
            "cancelled",
        ]
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
            or not set(worker.exceptions).issubset(set(proof.exceptions))
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
        if not (
            receipt.started_at
            <= worker.provenance.created_at
            <= receipt.completed_at
        ):
            raise ValueError(
                "worker evidence must fall within receipt lifecycle chronology"
            )
        if receipt.terminal_outcome == "delivered" and worker.status != "completed":
            raise ValueError("delivered receipt requires completed worker evidence")
        if review is not None:
            p2_finding_hashes = {
                canonical_hash(item)
                for item in review.findings
                if item.severity == "P2"
            }
            registered_finding_hashes = {
                item.finding_hash for item in proof.known_defects
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
                or not registered_finding_hashes.issubset(
                    p2_finding_hashes
                )
                or len(registered_finding_hashes)
                != len(proof.known_defects)
            ):
                raise ValueError(
                    "receipt proof does not match review, policy, or P2 evidence"
                )
            used_reviews.add(review.result_id)
            if not (
                worker.provenance.created_at
                <= review.provenance.created_at
                <= receipt.completed_at
            ):
                raise ValueError(
                    "review evidence must follow worker within receipt chronology"
                )
            if any(
                item.completed_at > review.provenance.created_at
                for item in proof.check_evidence
            ):
                raise ValueError(
                    "required check evidence must precede review evidence"
                )
        elif proof.review_disposition is not None or proof.known_defects:
            raise ValueError("receipt proof carries review evidence without a review")
        required_checks = set(plan.policy_profile.required_check_names)
        passing_checks = {
            item.check_name
            for item in proof.check_evidence
            if item.status == "passed"
        }
        logical_outcome_keys = {
            effect_class: set(
                delivery_effect_expected_outcome_keys(
                    effect_class=cast(EffectClass, effect_class),
                    run_id=receipt.run_id,
                    issue=proof.issue,
                    pull_request_number=pull_request_number,
                    required_check_names=(
                        plan.policy_profile.required_check_names
                    ),
                )
            )
            for effect_class in _SUCCESS_OUTCOME_BY_EFFECT
            if effect_class != "record_known_defect"
        }
        effect_outcome_keys: dict[str, set[str]] = {
            "claim_issue": {f"{proof.issue.authority_id}#claimed"},
            "launch_worker": logical_outcome_keys["launch_worker"],
            "await_ci": (
                logical_outcome_keys["await_ci"]
                if required_checks.issubset(passing_checks)
                else set()
            ),
            "request_review": (
                logical_outcome_keys["request_review"]
                if review is not None
                else set()
            ),
            "merge_pull_request": (
                {proof.merge_identity.authority_id}
                if proof.merge_identity is not None
                else set()
            ),
            "close_issue": (
                {f"{proof.closure.authority_id}#closed"}
                if proof.closure is not None
                else set()
            ),
            "record_delivery_receipt": logical_outcome_keys[
                "record_delivery_receipt"
            ],
        }
        for recovery_step in (
            item
            for item in receipt.recovery_history
            if item.issue == proof.issue
        ):
            recovery_effect = effects[
                recovery_step.effect_ref.contract_id
            ]
            if recovery_step.effect_class == "record_known_defect" and (
                review is None
                or recovery_effect.known_defect_finding_hash
                not in {
                    canonical_hash(item)
                    for item in review.findings
                    if item.severity == "P2"
                }
            ):
                raise ValueError(
                    "known-defect recovery target must bind an exact P2 finding"
                )
            if recovery_step.outcome != "reconciled":
                continue
            if recovery_step.effect_class == "record_known_defect":
                matching_defect = any(
                    item.registry_ref
                    == recovery_effect.known_defect_registry_ref
                    and item.finding_hash
                    == recovery_effect.known_defect_finding_hash
                    for item in proof.known_defects
                )
                expected_outcome_keys = set(
                    recovery_effect.expected_outcome_keys
                )
            else:
                matching_defect = True
                expected_outcome_keys = effect_outcome_keys[
                    recovery_step.effect_class
                ]
            if (
                not matching_defect
                or not expected_outcome_keys
                or set(recovery_step.outcome_evidence.outcome_keys)
                != expected_outcome_keys
                or (
                    recovery_step.effect_class == "claim_issue"
                    and any(
                        "agent:ready" in readback.observed_labels
                        for readback in recovery_step.authority_readbacks
                    )
                )
            ):
                raise ValueError(
                    "recovery readback does not prove the effect-specific outcome"
                )
        if any(
            item.pull_request_number != pull_request_number
            or item.exact_head_sha != proof.exact_head_sha
            or not (
                receipt.started_at
                <= item.completed_at
                <= receipt.completed_at
            )
            for item in proof.check_evidence
        ):
            raise ValueError(
                "check evidence must bind exact PR, head, and receipt chronology"
            )
        if proof.merge_identity is not None:
            if (
                worker.status != "completed"
                or review is None
                or proof.review_disposition in {None, "reject"}
                or not required_checks.issubset(passing_checks)
                or any(
                    item.completed_at > proof.merge_identity.merged_at
                    for item in proof.check_evidence
                )
                or review.provenance.created_at
                > proof.merge_identity.merged_at
                or worker.provenance.created_at
                > proof.merge_identity.merged_at
            ):
                raise ValueError(
                    "merge evidence requires completed worker, required checks, "
                    "accepted review, and ordered chronology"
                )
        proof_is_delivered = (
            worker.status == "completed"
            and proof.delivery_stage == "closed"
            and proof.merge_identity is not None
            and proof.closure is not None
            and bool(proof.check_evidence)
            and all(item.status == "passed" for item in proof.check_evidence)
            and required_checks.issubset(passing_checks)
            and proof.review_disposition not in {None, "reject"}
            and (
                review is None
                or len(proof.known_defects)
                == sum(
                    item.severity == "P2"
                    for item in review.findings
                )
            )
            and not proof.exceptions
        )
        if proof_is_delivered:
            proof_outcomes.append("delivered")
        elif worker.status != "completed":
            proof_outcomes.append(worker.status)
        elif proof.merge_identity is not None:
            proof_outcomes.append("partially_delivered")
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
    all_proofs_delivered = all(
        outcome == "delivered"
        and proof.delivery_stage == "closed"
        for outcome, proof in zip(
            proof_outcomes,
            receipt.issue_proofs,
            strict=True,
        )
    )
    if all_proofs_delivered:
        expected_terminal_outcome = "delivered"
    elif any(
        proof.merge_identity is not None for proof in receipt.issue_proofs
    ):
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
    checked_proofs = sum(bool(proof.check_evidence) for proof in receipt.issue_proofs)
    evidenced_human_interventions = sum(
        actor.actor_type == "human"
        for actor in (
            receipt.provenance.created_by,
            *(item.provenance.created_by for item in worker_results),
            *(item.provenance.created_by for item in review_results),
            *(item.provenance.created_by for item in reducer_effects),
            *(
                proof.merge_identity.merged_by
                for proof in receipt.issue_proofs
                if proof.merge_identity is not None
            ),
        )
    )
    if (
        receipt.tcd_metrics.worker_starts < len(worker_results)
        or receipt.tcd_metrics.review_rounds < len(review_results)
        or receipt.tcd_metrics.ci_wait_cycles < checked_proofs
        or receipt.tcd_metrics.human_interventions
        < evidenced_human_interventions
        or receipt.tcd_metrics.deterministic_transitions
        < len(receipt.issue_proofs) + len(receipt.recovery_history)
    ):
        raise ValueError(
            "TCD counters must not contradict receipt evidence"
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
    "EffectOutcomeEvidence",
    "IssueDeliveryProof",
    "IssueScope",
    "KnownDefectRef",
    "MergeIdentity",
    "PolicyProfile",
    "Provenance",
    "REDUCER_EFFECT_VERSION",
    "REDUCER_EVENT_VERSION",
    "REVIEW_RESULT_VERSION",
    "RecoveryAuthorityReadback",
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
    "delivery_event_id",
    "delivery_event_input_hash",
    "delivery_effect_idempotency_key",
    "delivery_effect_expected_outcome_keys",
    "delivery_effect_input_hash",
    "delivery_initiation_approval_hash",
    "parse_delivery_contract",
    "validate_delivery_plan_evidence",
    "validate_delivery_receipt_evidence",
    "validate_reducer_effect_evidence",
    "validate_reducer_event_evidence",
]
