"""Pure compilation of approved delivery scope into immutable plans.

The compiler consumes already-captured evidence. It has no adapter access and
performs no GitHub, dispatcher, filesystem, BuilderOps, CKM, or provider
mutation.
"""

from __future__ import annotations

import posixpath
from collections import defaultdict
from typing import Final, Literal, Protocol, TypeAlias

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.builderops.delivery_orchestration_contracts import (
    ActorIdentity,
    AuthoritySnapshot,
    ContractRef,
    DeliveryInitiation,
    DeliveryPlan,
    DependencyWave,
    EffectClass,
    ExpectedAuthorityState,
    GitSha,
    IssueScope,
    Provenance,
    ScopeExclusion,
    Sha256,
    SourceRef,
    UtcTimestamp,
    canonical_hash,
    validate_delivery_plan_evidence,
)
from app.builderops.issue_contract_validation import (
    is_durable_repo_anchor,
    is_resolvable_verify_target,
)

COMPILER_VERSION: Final[
    Literal["builderops.delivery-plan-compiler.v1"]
] = "builderops.delivery-plan-compiler.v1"
PLANNING_SNAPSHOT_VERSION: Final[
    Literal["builderops.delivery-planning-snapshot.v1"]
] = "builderops.delivery-planning-snapshot.v1"

REQUIRED_SBS_IMPACT_FIELDS: Final[tuple[str, ...]] = (
    "Authority impact",
    "Boundary risk",
    "Derived/rebuildable impact",
    "External boundary impact",
    "Fitness rule impact",
    "Human knowledge impact",
    "Memory impact",
    "New or changed contract",
    "Owner-doc impact",
    "Persistence impact",
    "Primary subsystem",
    "Retrieval/context impact",
    "Secondary subsystem(s)",
    "Sync/deployment impact",
    "Transition debt impact",
    "Write class",
)

_EFFECT_ALLOWLIST: Final[tuple[EffectClass, ...]] = (
    "await_ci",
    "claim_issue",
    "close_issue",
    "launch_worker",
    "merge_pull_request",
    "record_delivery_receipt",
    "record_known_defect",
    "request_review",
)
Priority: TypeAlias = Literal["high", "medium", "low"]
RiskClass: TypeAlias = Literal["low", "medium", "high", "critical"]
DeliveryStatus: TypeAlias = Literal[
    "undelivered",
    "active",
    "delivered",
]
ScopeRole: TypeAlias = Literal["delivery", "validation_parent"]
RefusalCode: TypeAlias = Literal[
    "approved_exclusion",
    "authority_ambiguity",
    "budget_exceeded",
    "dependency_blocked",
    "dependency_cycle",
    "malformed_sbs_impact",
    "missing_source_anchors",
    "missing_verify_targets",
    "mutation_overlap",
    "not_ready",
    "outside_approved_scope",
    "parent_validation_only",
    "risk_policy_blocked",
    "stale_delivery",
]
_POLICY_RISK_ALLOWLIST: Final[
    dict[str, frozenset[RiskClass]]
] = {
    "delivery-low-risk": frozenset({"low", "medium"}),
}


class _Refuse(Protocol):
    def __call__(
        self,
        issue: IssueScope,
        code: RefusalCode,
        detail: str,
        *,
        related_issues: tuple[IssueScope, ...] = (),
    ) -> None: ...


class _CompilerModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
    )


class SbsImpactEntry(_CompilerModel):
    field_name: str
    value: str


class DeliveryDependency(_CompilerModel):
    issue: IssueScope
    satisfied: bool


class DeliveryIssuePlanningSnapshot(_CompilerModel):
    issue: IssueScope
    authority: AuthoritySnapshot
    priority: Priority
    risk_class: RiskClass
    source_anchors: tuple[str, ...]
    verify_targets: tuple[str, ...]
    sbs_impact: tuple[SbsImpactEntry, ...]
    dependencies: tuple[DeliveryDependency, ...] = ()
    likely_mutation_paths: tuple[str, ...] = ()
    delivery_status: DeliveryStatus = "undelivered"
    linked_pr_head: GitSha | None = None
    parent_issue: IssueScope | None = None
    scope_role: ScopeRole = "delivery"


class DeliveryPlanningSnapshot(_CompilerModel):
    schema_version: Literal[
        "builderops.delivery-planning-snapshot.v1"
    ]
    snapshot_id: str
    captured_at: UtcTimestamp
    issues: tuple[DeliveryIssuePlanningSnapshot, ...]

    @field_validator("snapshot_id")
    @classmethod
    def _validate_snapshot_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("snapshot_id must not be empty")
        return normalized


class PlanRefusal(_CompilerModel):
    code: RefusalCode
    issue: IssueScope
    detail: str
    related_issues: tuple[IssueScope, ...] = ()

    @model_validator(mode="after")
    def _validate_related_issues(self) -> PlanRefusal:
        if not self.detail.strip():
            raise ValueError("plan refusal detail must not be empty")
        if self.related_issues != tuple(
            sorted(
                self.related_issues,
                key=lambda item: item.scope_key,
            )
        ):
            raise ValueError(
                "plan refusal related issues must use canonical order"
            )
        if len({item.scope_key for item in self.related_issues}) != len(
            self.related_issues
        ):
            raise ValueError(
                "plan refusal related issues must not contain duplicates"
            )
        return self


class DeliveryPlanCompilation(_CompilerModel):
    compiler_version: Literal[
        "builderops.delivery-plan-compiler.v1"
    ] = COMPILER_VERSION
    input_hash: Sha256
    plan: DeliveryPlan | None
    refusals: tuple[PlanRefusal, ...]
    external_mutations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_result(self) -> DeliveryPlanCompilation:
        if self.external_mutations:
            raise ValueError(
                "pure delivery-plan compilation cannot report mutations"
            )
        if self.plan is None and not self.refusals:
            raise ValueError(
                "plan-less compilation must carry typed refusals"
            )
        if self.refusals != tuple(
            sorted(
                self.refusals,
                key=lambda item: (
                    item.issue.scope_key,
                    item.code,
                    item.detail,
                ),
            )
        ):
            raise ValueError(
                "plan refusals must use canonical order"
            )
        return self


def compile_delivery_plan(
    initiation: DeliveryInitiation,
    snapshot: DeliveryPlanningSnapshot,
) -> DeliveryPlanCompilation:
    """Compile immutable evidence into one plan plus typed exclusions."""

    canonical_snapshot = _canonical_snapshot_payload(snapshot)
    input_hash = canonical_hash(
        {
            "compiler_version": COMPILER_VERSION,
            "initiation": {
                "schema_version": initiation.schema_version,
                "contract_id": initiation.initiation_id,
                "content_hash": initiation.content_hash,
            },
            "snapshot": canonical_snapshot,
        }
    )
    approved = {
        item.scope_key: item for item in initiation.requested_scope
    }
    facts_by_scope: dict[
        tuple[str, int],
        list[DeliveryIssuePlanningSnapshot],
    ] = defaultdict(list)
    for fact in snapshot.issues:
        facts_by_scope[fact.issue.scope_key].append(fact)

    refusal_map: dict[
        tuple[tuple[str, int], RefusalCode, str],
        PlanRefusal,
    ] = {}

    def refuse(
        issue: IssueScope,
        code: RefusalCode,
        detail: str,
        *,
        related_issues: tuple[IssueScope, ...] = (),
    ) -> None:
        key = (issue.scope_key, code, detail)
        existing = refusal_map.get(key)
        related_candidates = (
            *(existing.related_issues if existing is not None else ()),
            *related_issues,
        )
        related_by_scope: dict[tuple[str, int], IssueScope] = {}
        for related_issue in sorted(
            related_candidates,
            key=lambda item: (
                item.scope_key,
                item.contract_hash,
                item.authority_id,
            ),
        ):
            related_by_scope.setdefault(
                related_issue.scope_key,
                related_issue,
            )
        refusal_map[key] = PlanRefusal(
            code=code,
            issue=issue,
            detail=detail,
            related_issues=tuple(related_by_scope.values()),
        )

    for scope_key, facts in facts_by_scope.items():
        if scope_key not in approved:
            for fact in facts:
                refuse(
                    fact.issue,
                    "outside_approved_scope",
                    "live snapshot issue is outside approved initiation scope",
                )

    accepted_facts: dict[
        tuple[str, int],
        DeliveryIssuePlanningSnapshot,
    ] = {}
    approved_issue_exclusions = {
        exclusion.omitted_issue.scope_key: exclusion
        for exclusion in initiation.exclusions
        if exclusion.omitted_issue is not None
    }
    for issue in initiation.requested_scope:
        facts = facts_by_scope.get(issue.scope_key, [])
        if len(facts) != 1:
            refuse(
                issue,
                "authority_ambiguity",
                (
                    "live snapshot must contain exactly one fact for the "
                    "approved issue"
                ),
            )
            continue
        fact = facts[0]
        if snapshot.captured_at < initiation.provenance.created_at:
            refuse(
                issue,
                "authority_ambiguity",
                "live authority snapshot predates the approved initiation",
            )
            continue
        if fact.issue != issue or not _authority_binds_issue(
            fact.authority,
            issue=issue,
            captured_at=snapshot.captured_at,
        ):
            refuse(
                issue,
                "authority_ambiguity",
                "live authority does not exactly bind the approved issue",
            )
            continue
        if issue.scope_key in approved_issue_exclusions:
            refuse(
                issue,
                "approved_exclusion",
                "approved initiation already excludes this issue",
            )
            continue
        if fact.scope_role == "validation_parent":
            refuse(
                issue,
                "parent_validation_only",
                "real parent validation hub is not delivery or closure scope",
            )
            continue
        if (
            fact.authority.observed_state != "open"
            or "agent:ready" not in fact.authority.observed_labels
            or {
                "agent:blocked",
                "agent:needs-human",
            }.intersection(fact.authority.observed_labels)
        ):
            refuse(
                issue,
                "not_ready",
                "live issue authority is not strictly ready",
            )
        if (
            fact.delivery_status != "undelivered"
            or fact.linked_pr_head is not None
        ):
            refuse(
                issue,
                "stale_delivery",
                "issue already has active or delivered PR evidence",
            )
        if not _verify_targets_are_concrete(fact.verify_targets):
            refuse(
                issue,
                "missing_verify_targets",
                "strict issue contract has no concrete Verify target",
            )
        if not _source_anchors_are_concrete(fact.source_anchors):
            refuse(
                issue,
                "missing_source_anchors",
                "strict issue contract has no source anchor",
            )
        if not _sbs_impact_is_complete(fact.sbs_impact):
            refuse(
                issue,
                "malformed_sbs_impact",
                "SBS Impact fields are missing, duplicated, or empty",
            )
        if not _risk_is_allowed(
            initiation.policy_profile.profile_id,
            fact.risk_class,
        ):
            refuse(
                issue,
                "risk_policy_blocked",
                (
                    "issue risk class is not admitted by the approved "
                    "policy profile"
                ),
            )
        if _dependencies_are_ambiguous(fact.dependencies):
            refuse(
                issue,
                "authority_ambiguity",
                "dependency evidence contains contradictory identities",
            )
        for dependency in fact.dependencies:
            approved_dependency = approved.get(
                dependency.issue.scope_key
            )
            if (
                approved_dependency is not None
                and dependency.issue != approved_dependency
            ):
                refuse(
                    issue,
                    "authority_ambiguity",
                    (
                        "dependency evidence does not exactly bind the "
                        "approved issue"
                    ),
                    related_issues=(dependency.issue,),
                )
            if (
                dependency.issue.scope_key not in approved
                and not dependency.satisfied
            ):
                refuse(
                    issue,
                    "dependency_blocked",
                    "external dependency is not delivered",
                    related_issues=(dependency.issue,),
                )
        accepted_facts[issue.scope_key] = fact

    _refuse_mutation_overlap(
        accepted_facts,
        refuse=refuse,
    )
    _propagate_dependency_refusals(
        approved=approved,
        facts=accepted_facts,
        refusal_map=refusal_map,
        refuse=refuse,
    )

    eligible = {
        scope_key: fact
        for scope_key, fact in accepted_facts.items()
        if not _issue_has_refusal(scope_key, refusal_map)
    }
    if len(eligible) > initiation.budget.max_worker_starts:
        for fact in eligible.values():
            refuse(
                fact.issue,
                "budget_exceeded",
                (
                    "eligible scope exceeds the approved worker-start "
                    "budget"
                ),
            )
        eligible = {}
    waves, cycle_keys = _build_dependency_waves(
        eligible,
        max_parallel=initiation.budget.max_parallel_workers,
    )
    for scope_key in cycle_keys:
        issue = approved[scope_key]
        refuse(
            issue,
            "dependency_cycle",
            "internal dependency graph contains a cycle",
        )
    if cycle_keys:
        eligible = {
            scope_key: fact
            for scope_key, fact in eligible.items()
            if scope_key not in cycle_keys
        }
        _propagate_dependency_refusals(
            approved=approved,
            facts=accepted_facts,
            refusal_map=refusal_map,
            refuse=refuse,
        )
        eligible = {
            scope_key: fact
            for scope_key, fact in accepted_facts.items()
            if not _issue_has_refusal(scope_key, refusal_map)
        }
        waves, unresolved = _build_dependency_waves(
            eligible,
            max_parallel=initiation.budget.max_parallel_workers,
        )
        for scope_key in unresolved:
            refuse(
                approved[scope_key],
                "dependency_cycle",
                "internal dependency graph remains unresolved",
            )
        if unresolved:
            eligible = {
                scope_key: fact
                for scope_key, fact in eligible.items()
                if scope_key not in unresolved
            }
            waves, _ = _build_dependency_waves(
                eligible,
                max_parallel=initiation.budget.max_parallel_workers,
            )

    refusals = tuple(
        sorted(
            refusal_map.values(),
            key=lambda item: (
                item.issue.scope_key,
                item.code,
                item.detail,
            ),
        )
    )
    if not eligible:
        return DeliveryPlanCompilation(
            input_hash=input_hash,
            plan=None,
            refusals=refusals,
        )

    final_scope = tuple(
        sorted(
            (fact.issue for fact in eligible.values()),
            key=lambda item: item.scope_key,
        )
    )
    exclusions = _compile_exclusions(
        initiation,
        final_scope=final_scope,
        refusals=refusals,
    )
    input_authorities = tuple(
        sorted(
            (fact.authority for fact in eligible.values()),
            key=lambda item: item.authority_id,
        )
    )
    expected_states = tuple(
        ExpectedAuthorityState(
            issue=fact.issue,
            issue_state="open",
            required_labels=tuple(
                sorted(fact.authority.observed_labels)
            ),
            forbidden_labels=(
                "agent:blocked",
                "agent:needs-human",
            ),
            expected_contract_hash=fact.issue.contract_hash,
        )
        for fact in sorted(
            eligible.values(),
            key=lambda item: item.issue.scope_key,
        )
    )
    source_refs = (
        SourceRef(
            source_type="delivery_initiation",
            source_id=initiation.initiation_id,
            content_hash=initiation.content_hash,
        ),
        SourceRef(
            source_type="delivery_planning_snapshot",
            source_id=snapshot.snapshot_id,
            content_hash=canonical_hash(canonical_snapshot),
        ),
    )
    created_at = max(
        initiation.provenance.created_at,
        snapshot.captured_at,
    )
    plan = DeliveryPlan(
        plan_id=f"delivery-plan:{input_hash}",
        initiation_ref=ContractRef(
            schema_version=initiation.schema_version,
            contract_id=initiation.initiation_id,
            content_hash=initiation.content_hash,
        ),
        input_authorities=input_authorities,
        final_scope=final_scope,
        exclusions=exclusions,
        dependency_waves=waves,
        expected_states=expected_states,
        policy_profile=initiation.policy_profile,
        budget=initiation.budget,
        effect_allowlist=_EFFECT_ALLOWLIST,
        provenance=Provenance(
            created_at=created_at,
            created_by=ActorIdentity(
                actor_type="service",
                actor_id="builderops:delivery-plan-compiler.v1",
                authority_scope=_authority_scope(final_scope),
            ),
            source_refs=source_refs,
            correlation_id=f"delivery-plan-compile:{input_hash}",
        ),
    )
    validate_delivery_plan_evidence(
        plan,
        initiation=initiation,
    )
    return DeliveryPlanCompilation(
        input_hash=input_hash,
        plan=plan,
        refusals=refusals,
    )


def _canonical_snapshot_payload(
    snapshot: DeliveryPlanningSnapshot,
) -> dict[str, object]:
    issue_payloads = [
        _canonical_issue_payload(fact)
        for fact in snapshot.issues
    ]
    return {
        "schema_version": snapshot.schema_version,
        "snapshot_id": snapshot.snapshot_id,
        "captured_at": snapshot.captured_at,
        "issues": sorted(issue_payloads, key=canonical_hash),
    }


def _canonical_issue_payload(
    fact: DeliveryIssuePlanningSnapshot,
) -> dict[str, object]:
    dependencies = [
        dependency.model_dump(mode="json")
        for dependency in fact.dependencies
    ]
    return {
        **fact.model_dump(
            mode="json",
            exclude={
                "source_anchors",
                "verify_targets",
                "sbs_impact",
                "dependencies",
                "likely_mutation_paths",
            },
        ),
        "source_anchors": sorted(
            value.strip() for value in fact.source_anchors
        ),
        "verify_targets": sorted(
            value.strip() for value in fact.verify_targets
        ),
        "sbs_impact": sorted(
            (
                {
                    "field_name": entry.field_name.strip(),
                    "value": entry.value.strip(),
                }
                for entry in fact.sbs_impact
            ),
            key=canonical_hash,
        ),
        "dependencies": sorted(dependencies, key=canonical_hash),
        "likely_mutation_paths": sorted(
            _normalize_path(value)
            for value in fact.likely_mutation_paths
        ),
    }


def _authority_binds_issue(
    authority: AuthoritySnapshot,
    *,
    issue: IssueScope,
    captured_at: str,
) -> bool:
    return (
        authority.authority_type == "github_issue"
        and authority.authority_id == issue.authority_id
        and authority.content_hash == issue.contract_hash
        and authority.observed_at <= captured_at
    )


def _clean_values(values: tuple[str, ...]) -> tuple[str, ...]:
    cleaned = tuple(value.strip() for value in values if value.strip())
    if len(cleaned) != len(values) or len(set(cleaned)) != len(cleaned):
        return ()
    return tuple(sorted(cleaned))


def _verify_targets_are_concrete(values: tuple[str, ...]) -> bool:
    cleaned = _clean_values(values)
    return bool(cleaned) and all(
        is_resolvable_verify_target(value)
        for value in cleaned
    )


def _source_anchors_are_concrete(values: tuple[str, ...]) -> bool:
    cleaned = _clean_values(values)
    return bool(cleaned) and all(
        is_durable_repo_anchor(value)
        for value in cleaned
    )


def _risk_is_allowed(
    profile_id: str,
    risk_class: RiskClass,
) -> bool:
    allowed = _POLICY_RISK_ALLOWLIST.get(profile_id)
    return allowed is not None and risk_class in allowed


def _sbs_impact_is_complete(
    entries: tuple[SbsImpactEntry, ...],
) -> bool:
    fields = tuple(entry.field_name.strip() for entry in entries)
    return (
        len(fields) == len(REQUIRED_SBS_IMPACT_FIELDS)
        and len(set(fields)) == len(fields)
        and set(fields) == set(REQUIRED_SBS_IMPACT_FIELDS)
        and all(entry.value.strip() for entry in entries)
    )


def _dependencies_are_ambiguous(
    dependencies: tuple[DeliveryDependency, ...],
) -> bool:
    identities: dict[tuple[str, int], DeliveryDependency] = {}
    for dependency in dependencies:
        existing = identities.get(dependency.issue.scope_key)
        if existing is not None and existing != dependency:
            return True
        if existing is not None:
            return True
        identities[dependency.issue.scope_key] = dependency
    return False


def _normalize_path(value: str) -> str:
    normalized = posixpath.normpath(
        value.strip().replace("\\", "/")
    )
    if normalized == ".":
        return ""
    return normalized.lstrip("/")


def _paths_overlap(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return (
        left == right
        or left.startswith(f"{right}/")
        or right.startswith(f"{left}/")
    )


def _refuse_mutation_overlap(
    facts: dict[tuple[str, int], DeliveryIssuePlanningSnapshot],
    *,
    refuse: _Refuse,
) -> None:
    items = sorted(
        facts.values(),
        key=lambda item: item.issue.scope_key,
    )
    for index, left in enumerate(items):
        left_paths = tuple(
            _normalize_path(value)
            for value in left.likely_mutation_paths
            if _normalize_path(value)
        )
        for right in items[index + 1 :]:
            right_paths = tuple(
                _normalize_path(value)
                for value in right.likely_mutation_paths
                if _normalize_path(value)
            )
            if not any(
                _paths_overlap(left_path, right_path)
                for left_path in left_paths
                for right_path in right_paths
            ):
                continue
            refuse(
                left.issue,
                "mutation_overlap",
                "likely mutation path overlaps approved peer",
                related_issues=(right.issue,),
            )
            refuse(
                right.issue,
                "mutation_overlap",
                "likely mutation path overlaps approved peer",
                related_issues=(left.issue,),
            )


def _issue_has_refusal(
    scope_key: tuple[str, int],
    refusal_map: dict[
        tuple[tuple[str, int], RefusalCode, str],
        PlanRefusal,
    ],
) -> bool:
    return any(key[0] == scope_key for key in refusal_map)


def _propagate_dependency_refusals(
    *,
    approved: dict[tuple[str, int], IssueScope],
    facts: dict[tuple[str, int], DeliveryIssuePlanningSnapshot],
    refusal_map: dict[
        tuple[tuple[str, int], RefusalCode, str],
        PlanRefusal,
    ],
    refuse: _Refuse,
) -> None:
    changed = True
    while changed:
        changed = False
        for scope_key, fact in sorted(facts.items()):
            if _issue_has_refusal(scope_key, refusal_map):
                continue
            blocked = tuple(
                dependency.issue
                for dependency in fact.dependencies
                if not dependency.satisfied
                and dependency.issue.scope_key in approved
                and _issue_has_refusal(
                    dependency.issue.scope_key,
                    refusal_map,
                )
            )
            if not blocked:
                continue
            refuse(
                fact.issue,
                "dependency_blocked",
                "internal dependency was excluded or refused",
                related_issues=blocked,
            )
            changed = True


def _build_dependency_waves(
    facts: dict[tuple[str, int], DeliveryIssuePlanningSnapshot],
    *,
    max_parallel: int,
) -> tuple[tuple[DependencyWave, ...], tuple[tuple[str, int], ...]]:
    remaining = set(facts)
    completed: set[tuple[str, int]] = set()
    waves: list[DependencyWave] = []
    priority_order = {"high": 0, "medium": 1, "low": 2}

    while remaining:
        ready = [
            scope_key
            for scope_key in remaining
            if all(
                dependency.satisfied
                or dependency.issue.scope_key in completed
                or dependency.issue.scope_key not in facts
                for dependency in facts[scope_key].dependencies
            )
        ]
        if not ready:
            return (
                tuple(waves),
                _dependency_cycle_keys(
                    facts,
                    candidates=remaining,
                ),
            )
        ready.sort(
            key=lambda scope_key: (
                priority_order[facts[scope_key].priority],
                scope_key,
            )
        )
        for offset in range(0, len(ready), max_parallel):
            chunk = ready[offset : offset + max_parallel]
            waves.append(
                DependencyWave(
                    wave_index=len(waves),
                    issues=tuple(
                        sorted(
                            (
                                facts[scope_key].issue
                                for scope_key in chunk
                            ),
                            key=lambda item: item.scope_key,
                        )
                    ),
                )
            )
        completed.update(ready)
        remaining.difference_update(ready)
    return tuple(waves), ()


def _dependency_cycle_keys(
    facts: dict[tuple[str, int], DeliveryIssuePlanningSnapshot],
    *,
    candidates: set[tuple[str, int]],
) -> tuple[tuple[str, int], ...]:
    cycle_keys: set[tuple[str, int]] = set()
    for start in candidates:
        pending = [start]
        visited: set[tuple[str, int]] = set()
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            for dependency in facts[current].dependencies:
                if dependency.satisfied:
                    continue
                dependency_key = dependency.issue.scope_key
                if dependency_key not in candidates:
                    continue
                if dependency_key == start:
                    cycle_keys.add(start)
                    pending.clear()
                    break
                pending.append(dependency_key)
    return tuple(sorted(cycle_keys))


def _compile_exclusions(
    initiation: DeliveryInitiation,
    *,
    final_scope: tuple[IssueScope, ...],
    refusals: tuple[PlanRefusal, ...],
) -> tuple[ScopeExclusion, ...]:
    included = {item.scope_key for item in final_scope}
    existing = {
        exclusion.scope_key.casefold(): exclusion
        for exclusion in initiation.exclusions
    }
    refusals_by_scope: dict[
        tuple[str, int],
        list[PlanRefusal],
    ] = defaultdict(list)
    for refusal in refusals:
        if refusal.issue.scope_key in {
            item.scope_key for item in initiation.requested_scope
        }:
            refusals_by_scope[refusal.issue.scope_key].append(refusal)

    for issue in initiation.requested_scope:
        if issue.scope_key in included:
            continue
        scope_ref = (
            f"{issue.repository.casefold()}#{issue.issue_number}"
        )
        if scope_ref.casefold() in existing:
            continue
        codes = sorted(
            {
                refusal.code
                for refusal in refusals_by_scope[issue.scope_key]
            }
        )
        existing[scope_ref.casefold()] = ScopeExclusion(
            scope_key=scope_ref,
            reason=(
                "delivery-plan-compiler:"
                + ",".join(codes or ["authority_ambiguity"])
            ),
            omitted_issue=issue,
        )
    return tuple(
        sorted(existing.values(), key=lambda item: item.scope_key)
    )


def _authority_scope(
    final_scope: tuple[IssueScope, ...],
) -> str:
    repositories = sorted(
        {issue.repository.casefold() for issue in final_scope}
    )
    return ",".join(repositories)


__all__ = [
    "COMPILER_VERSION",
    "PLANNING_SNAPSHOT_VERSION",
    "REQUIRED_SBS_IMPACT_FIELDS",
    "DeliveryDependency",
    "DeliveryIssuePlanningSnapshot",
    "DeliveryPlanCompilation",
    "DeliveryPlanningSnapshot",
    "PlanRefusal",
    "SbsImpactEntry",
    "compile_delivery_plan",
]
