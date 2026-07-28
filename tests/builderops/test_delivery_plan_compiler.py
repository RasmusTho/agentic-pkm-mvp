from __future__ import annotations

import ast
import inspect
import json

import pytest
from pydantic import ValidationError

from app.builderops.delivery_orchestration_contracts import (
    ActorIdentity,
    ApprovalEvidence,
    AuthoritySnapshot,
    DeliveryBudget,
    DeliveryInitiation,
    IssueScope,
    PolicyProfile,
    Provenance,
    ScopeExclusion,
    SourceRef,
    canonical_hash,
    delivery_initiation_approval_hash,
)
from app.builderops.delivery_plan_compiler import (
    COMPILER_VERSION,
    PLANNING_SNAPSHOT_VERSION,
    REQUIRED_SBS_IMPACT_FIELDS,
    DeliveryDependency,
    DeliveryDependencySatisfactionEvidence,
    DeliveryIssuePlanningSnapshot,
    DeliveryPlanCompilation,
    DeliveryPlanningSnapshot,
    IssueContractResolutionEvidence,
    SbsImpactEntry,
    _canonical_snapshot_payload,
    compile_delivery_plan,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
OBSERVED_AT = "2026-07-28T07:00:00Z"
APPROVED_AT = "2026-07-28T07:01:00Z"
CREATED_AT = "2026-07-28T07:02:00Z"
SNAPSHOT_AT = "2026-07-28T07:03:00Z"
RESOLVED_AT = "2026-07-28T07:02:30Z"


def _issue(number: int, content_hash: str = SHA_A) -> IssueScope:
    return IssueScope(
        repository="rasmustho/agentic-pkm-mvp",
        issue_number=number,
        authority_id=(
            f"github:rasmustho/agentic-pkm-mvp/issues/{number}"
        ),
        contract_hash=content_hash,
    )


def _authority(
    issue: IssueScope,
    *,
    state: str = "open",
    labels: tuple[str, ...] = (
        "agent:ready",
        "prio:high",
        "type:task",
    ),
) -> AuthoritySnapshot:
    return AuthoritySnapshot(
        authority_type="github_issue",
        authority_id=issue.authority_id,
        content_hash=issue.contract_hash,
        observed_state=state,
        observed_labels=labels,
        observed_at=OBSERVED_AT,
    )


def _initiation(
    issues: tuple[IssueScope, ...],
    *,
    max_parallel_workers: int = 2,
    max_worker_starts: int | None = None,
) -> DeliveryInitiation:
    issues = tuple(sorted(issues, key=lambda item: item.scope_key))
    authorities = tuple(_authority(issue) for issue in issues)
    policy = PolicyProfile(
        profile_id="delivery-low-risk",
        profile_version="v1",
        profile_hash=SHA_B,
        minimum_review_confidence_basis_points=8_000,
        required_check_names=("Unit tests (not pg)",),
    )
    budget = DeliveryBudget(
        max_parallel_workers=max_parallel_workers,
        max_worker_starts=(
            max_worker_starts
            if max_worker_starts is not None
            else max(len(issues), max_parallel_workers)
        ),
        max_coordinator_turns=12,
        max_total_tokens=200_000,
        max_wall_time_seconds=7_200,
    )
    exclusions = (
        ScopeExclusion(
            scope_key="durable-carrier-selection",
            reason="Deferred to the explicit carrier governance gate.",
        ),
    )
    actor = ActorIdentity(
        actor_type="human",
        actor_id="owner:RasmusTho",
        authority_scope="rasmustho/agentic-pkm-mvp",
    )
    source_refs = (
        SourceRef(
            source_type="github_issue",
            source_id="rasmustho/agentic-pkm-mvp#4166",
            content_hash=SHA_C,
        ),
    )
    provenance = Provenance(
        created_at=CREATED_AT,
        created_by=ActorIdentity(
            actor_type="service",
            actor_id="builderops:delivery-initiation-boundary",
            authority_scope="rasmustho/agentic-pkm-mvp",
        ),
        source_refs=source_refs,
        correlation_id="initiation-4166",
    )
    approval_hash = delivery_initiation_approval_hash(
        initiation_id="init-4166",
        requested_scope=issues,
        exclusions=exclusions,
        policy_profile=policy,
        budget=budget,
        source_authorities=authorities,
        provenance=provenance,
        approval_id="approval-4166",
        approver=actor,
        approved_at=APPROVED_AT,
        approval_source_refs=source_refs,
    )
    return DeliveryInitiation(
        initiation_id="init-4166",
        requested_scope=issues,
        exclusions=exclusions,
        approval_evidence=ApprovalEvidence(
            approval_id="approval-4166",
            approver=actor,
            approved_at=APPROVED_AT,
            approved_payload_hash=approval_hash,
            source_refs=source_refs,
        ),
        policy_profile=policy,
        budget=budget,
        source_authorities=authorities,
        provenance=provenance,
    )


def _sbs_impact(
    *,
    omit: str | None = None,
) -> tuple[SbsImpactEntry, ...]:
    return tuple(
        SbsImpactEntry(field_name=field_name, value=f"value:{field_name}")
        for field_name in REQUIRED_SBS_IMPACT_FIELDS
        if field_name != omit
    )


def _unquote(value: str) -> str:
    if value.startswith("`") and value.endswith("`"):
        return value[1:-1]
    return value


def _resolution_evidence(
    issue: IssueScope,
    *,
    source_anchors: tuple[str, ...],
    verify_targets: tuple[str, ...],
    observed_at: str = RESOLVED_AT,
    resolved_content_hash: str = SHA_D,
) -> tuple[IssueContractResolutionEvidence, ...]:
    evidence: list[IssueContractResolutionEvidence] = []
    for source_anchor in source_anchors:
        target = source_anchor.strip()
        path = target.split(" :: ", maxsplit=1)[0]
        evidence.append(
            IssueContractResolutionEvidence(
                schema_version=(
                    "builderops.issue-contract-resolution-evidence.v1"
                ),
                issue_authority_id=issue.authority_id,
                issue_contract_hash=issue.contract_hash,
                target_kind="source_anchor",
                target=target,
                resolver_id="builderops.repo-anchor-resolver",
                resolver_version="v1",
                resolved_authority_id=(
                    f"git:{issue.repository}:{path}"
                ),
                resolved_content_hash=resolved_content_hash,
                observed_at=observed_at,
            )
        )
    for verify_target in verify_targets:
        target = verify_target.strip()
        unquoted = _unquote(target)
        if unquoted.startswith("runtime receipt: "):
            identity = unquoted.removeprefix("runtime receipt: ")
            resolver_id = "builderops.runtime-receipt-resolver"
            resolved_authority_id = (
                f"builderops:runtime-receipt-registry:{identity}"
            )
        else:
            resolver_id = "builderops.repo-verify-target-resolver"
            if unquoted.startswith("doc writeback at "):
                repo_target = _unquote(
                    unquoted.removeprefix("doc writeback at ")
                )
                path = repo_target.split(" :: ", maxsplit=1)[0]
            elif unquoted.startswith("roadmap diff: "):
                repo_target = _unquote(
                    unquoted.removeprefix("roadmap diff: ")
                )
                path = repo_target.split(" :: ", maxsplit=1)[0]
            else:
                path = unquoted.split("::", maxsplit=1)[0]
            resolved_authority_id = (
                f"git:{issue.repository}:{path}"
            )
        evidence.append(
            IssueContractResolutionEvidence(
                schema_version=(
                    "builderops.issue-contract-resolution-evidence.v1"
                ),
                issue_authority_id=issue.authority_id,
                issue_contract_hash=issue.contract_hash,
                target_kind="verify_target",
                target=target,
                resolver_id=resolver_id,
                resolver_version="v1",
                resolved_authority_id=resolved_authority_id,
                resolved_content_hash=resolved_content_hash,
                observed_at=observed_at,
            )
        )
    return tuple(evidence)


def _fact(
    issue: IssueScope,
    *,
    authority: AuthoritySnapshot | None = None,
    risk_class: str = "medium",
    source_anchors: tuple[str, ...] | None = None,
    dependencies: tuple[DeliveryDependency, ...] = (),
    mutation_paths: tuple[str, ...] = (),
    verify_targets: tuple[str, ...] = ("tests/example.py::test_contract",),
    sbs_impact: tuple[SbsImpactEntry, ...] | None = None,
    delivery_status: str = "undelivered",
    linked_pr_head: str | None = None,
    parent_issue: IssueScope | None = None,
    scope_role: str = "delivery",
    resolution_evidence: (
        tuple[IssueContractResolutionEvidence, ...] | None
    ) = None,
) -> DeliveryIssuePlanningSnapshot:
    resolved_source_anchors = (
        source_anchors
        if source_anchors is not None
        else (
            "docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/"
            "COMPILE_IMMUTABLE_DELIVERY_PLANS.md"
            " :: What This Task Does",
        )
    )
    return DeliveryIssuePlanningSnapshot(
        issue=issue,
        authority=authority or _authority(issue),
        priority="high",
        risk_class=risk_class,
        source_anchors=resolved_source_anchors,
        verify_targets=verify_targets,
        resolution_evidence=(
            resolution_evidence
            if resolution_evidence is not None
            else _resolution_evidence(
                issue,
                source_anchors=resolved_source_anchors,
                verify_targets=verify_targets,
            )
        ),
        sbs_impact=sbs_impact or _sbs_impact(),
        dependencies=dependencies,
        likely_mutation_paths=mutation_paths,
        delivery_status=delivery_status,
        linked_pr_head=linked_pr_head,
        parent_issue=parent_issue,
        scope_role=scope_role,
    )


def _snapshot(
    *facts: DeliveryIssuePlanningSnapshot,
) -> DeliveryPlanningSnapshot:
    return DeliveryPlanningSnapshot(
        schema_version="builderops.delivery-planning-snapshot.v2",
        snapshot_id="snapshot-4166",
        captured_at=SNAPSHOT_AT,
        issues=tuple(facts),
    )


def test_compiler_is_deterministic() -> None:
    issue_a = _issue(5101, SHA_A)
    issue_b = _issue(5102, SHA_B)
    initiation = _initiation((issue_a, issue_b))
    facts = (
        _fact(issue_a, mutation_paths=("app/a.py",)),
        _fact(issue_b, mutation_paths=("app/b.py",)),
    )

    first = compile_delivery_plan(initiation, _snapshot(*facts))
    second = compile_delivery_plan(initiation, _snapshot(*reversed(facts)))

    assert first.refusals == ()
    assert first.external_mutations == ()
    assert first.plan is not None
    assert second.plan is not None
    assert first.input_hash == second.input_hash
    assert first.plan.canonical_bytes() == second.plan.canonical_bytes()
    assert first.plan.content_hash == second.plan.content_hash
    assert first.plan.plan_id == second.plan.plan_id

    changed_evidence = tuple(
        item.model_copy(update={"resolved_content_hash": SHA_C})
        for item in facts[0].resolution_evidence
    )
    changed = compile_delivery_plan(
        initiation,
        _snapshot(
            facts[0].model_copy(
                update={"resolution_evidence": changed_evidence}
            ),
            facts[1],
        ),
    )
    assert changed.plan is not None
    assert changed.input_hash != first.input_hash
    assert changed.plan.plan_id != first.plan.plan_id

    duplicate_first = compile_delivery_plan(
        _initiation((issue_a,)),
        _snapshot(
            _fact(issue_a),
            _fact(issue_a, verify_targets=()),
        ),
    )
    duplicate_second = compile_delivery_plan(
        _initiation((issue_a,)),
        _snapshot(
            _fact(issue_a, verify_targets=()),
            _fact(issue_a),
        ),
    )
    assert duplicate_first.input_hash == duplicate_second.input_hash
    assert duplicate_first.refusals == duplicate_second.refusals

    serialized = first_snapshot = _snapshot(*facts)
    assert (
        DeliveryPlanningSnapshot.model_validate_json(
            serialized.model_dump_json()
        )
        == first_snapshot
    )
    unversioned = first_snapshot.model_dump()
    unversioned.pop("schema_version")
    with pytest.raises(ValidationError):
        DeliveryPlanningSnapshot.model_validate(unversioned)


def test_compiler_refuses_unexecutable_scope_with_typed_reasons() -> None:
    missing_verify = _issue(5201, "1" * 64)
    stale_delivery = _issue(5202, "2" * 64)
    dependency_blocked = _issue(5203, "3" * 64)
    overlap_a = _issue(5204, "4" * 64)
    overlap_b = _issue(5205, "5" * 64)
    overlap_c = _issue(5209, "f" * 64)
    missing_authority = _issue(5206, "6" * 64)
    malformed_sbs = _issue(5207, "7" * 64)
    mismatched_dependency = _issue(5208, "8" * 64)
    placeholder_verify = _issue(5213, "d" * 64)
    high_risk = _issue(5214, "e" * 64)
    malformed_receipt = _issue(5215, "f" * 64)
    malformed_roadmap = _issue(5216, "0" * 64)
    malformed_source = _issue(5217, "1" * 64)
    cycle_a = _issue(5210, "a" * 64)
    cycle_b = _issue(5211, "b" * 64)
    cycle_downstream = _issue(5212, "c" * 64)
    external_dependency = _issue(9999, "9" * 64)
    initiation = _initiation(
        (
            missing_verify,
            stale_delivery,
            dependency_blocked,
            overlap_a,
            overlap_b,
            overlap_c,
            missing_authority,
            malformed_sbs,
            mismatched_dependency,
            placeholder_verify,
            high_risk,
            malformed_receipt,
            malformed_roadmap,
            malformed_source,
            cycle_a,
            cycle_b,
            cycle_downstream,
        )
    )

    result = compile_delivery_plan(
        initiation,
        _snapshot(
            _fact(missing_verify, verify_targets=()),
            _fact(
                stale_delivery,
                delivery_status="delivered",
                linked_pr_head=SHA_D,
            ),
            _fact(
                dependency_blocked,
                dependencies=(
                    DeliveryDependency(
                        issue=external_dependency,
                        satisfied=False,
                    ),
                ),
            ),
            _fact(overlap_a, mutation_paths=("app/shared",)),
            _fact(overlap_b, mutation_paths=("app/shared/file.py",)),
            _fact(overlap_c, mutation_paths=("app/shared/other.py",)),
            _fact(
                malformed_sbs,
                sbs_impact=_sbs_impact(omit="Boundary risk"),
            ),
            _fact(
                mismatched_dependency,
                dependencies=(
                    DeliveryDependency(
                        issue=_issue(5201, "e" * 64),
                        satisfied=False,
                    ),
                ),
            ),
            _fact(placeholder_verify, verify_targets=("TBD",)),
            _fact(high_risk, risk_class="high"),
            _fact(
                malformed_receipt,
                verify_targets=("runtime receipt: looks plausible",),
            ),
            _fact(
                malformed_roadmap,
                verify_targets=("roadmap diff: TBD",),
            ),
            _fact(
                malformed_source,
                source_anchors=("TBD",),
            ),
            _fact(
                cycle_a,
                dependencies=(
                    DeliveryDependency(
                        issue=cycle_b,
                        satisfied=False,
                    ),
                ),
            ),
            _fact(
                cycle_b,
                dependencies=(
                    DeliveryDependency(
                        issue=cycle_a,
                        satisfied=False,
                    ),
                ),
            ),
            _fact(
                cycle_downstream,
                dependencies=(
                    DeliveryDependency(
                        issue=cycle_a,
                        satisfied=False,
                    ),
                ),
            ),
        ),
    )

    assert result.plan is None
    assert {
        refusal.code for refusal in result.refusals
    } == {
        "authority_ambiguity",
        "dependency_blocked",
        "dependency_cycle",
        "malformed_sbs_impact",
        "missing_source_anchors",
        "missing_verify_targets",
        "mutation_overlap",
        "risk_policy_blocked",
        "stale_delivery",
    }
    assert any(
        refusal.code == "authority_ambiguity"
        and refusal.issue == mismatched_dependency
        for refusal in result.refusals
    )
    overlap_refusal = next(
        refusal
        for refusal in result.refusals
        if refusal.code == "mutation_overlap"
        and refusal.issue == overlap_a
    )
    assert overlap_refusal.related_issues == (overlap_b, overlap_c)
    assert any(
        refusal.code == "dependency_cycle"
        and refusal.issue == cycle_a
        for refusal in result.refusals
    )
    assert any(
        refusal.code == "dependency_cycle"
        and refusal.issue == cycle_b
        for refusal in result.refusals
    )
    assert any(
        refusal.code == "dependency_blocked"
        and refusal.issue == cycle_downstream
        for refusal in result.refusals
    )

    stale_snapshot = DeliveryPlanningSnapshot(
        schema_version="builderops.delivery-planning-snapshot.v2",
        snapshot_id="snapshot-before-initiation",
        captured_at=OBSERVED_AT,
        issues=(_fact(missing_verify),),
    )
    stale_snapshot_result = compile_delivery_plan(
        _initiation((missing_verify,)),
        stale_snapshot,
    )
    assert stale_snapshot_result.plan is None
    assert {
        refusal.code for refusal in stale_snapshot_result.refusals
    } == {"authority_ambiguity"}


def test_compiler_accepts_concrete_non_test_verify_targets() -> None:
    doc_issue = _issue(5241, "1" * 64)
    receipt_issue = _issue(5242, "2" * 64)
    result = compile_delivery_plan(
        _initiation((doc_issue, receipt_issue)),
        _snapshot(
            _fact(
                doc_issue,
                verify_targets=(
                    "doc writeback at docs/STATUS.md :: Delivery status",
                    "roadmap diff: docs/ROADMAP.md :: DDO-03",
                ),
            ),
            _fact(
                receipt_issue,
                verify_targets=(
                    "runtime receipt: delivery_receipt.v1",
                ),
            ),
        ),
    )

    assert result.plan is not None
    assert result.refusals == ()


def test_compiler_refuses_unresolved_or_invalid_resolution_evidence() -> None:
    missing_source = _issue(5245, "1" * 64)
    missing_receipt = _issue(5246, "2" * 64)
    duplicate = _issue(5247, "3" * 64)
    mismatched = _issue(5248, "4" * 64)
    stale = _issue(5249, "5" * 64)

    missing_source_fact = _fact(
        missing_source,
        source_anchors=(
            "docs/DOES_NOT_EXIST.md :: Plausible contract",
        ),
    )
    missing_receipt_fact = _fact(
        missing_receipt,
        verify_targets=(
            "runtime receipt: unregistered_delivery_receipt.v1",
        ),
    )
    duplicate_fact = _fact(duplicate)
    mismatched_fact = _fact(mismatched)
    stale_fact = _fact(stale)
    result = compile_delivery_plan(
        _initiation(
            (
                missing_source,
                missing_receipt,
                duplicate,
                mismatched,
                stale,
            )
        ),
        _snapshot(
            missing_source_fact.model_copy(
                update={
                    "resolution_evidence": tuple(
                        item
                        for item in missing_source_fact.resolution_evidence
                        if item.target_kind != "source_anchor"
                    )
                }
            ),
            missing_receipt_fact.model_copy(
                update={
                    "resolution_evidence": tuple(
                        item
                        for item in missing_receipt_fact.resolution_evidence
                        if item.target_kind != "verify_target"
                    )
                }
            ),
            duplicate_fact.model_copy(
                update={
                    "resolution_evidence": (
                        *duplicate_fact.resolution_evidence,
                        duplicate_fact.resolution_evidence[0],
                    )
                }
            ),
            mismatched_fact.model_copy(
                update={
                    "resolution_evidence": (
                        mismatched_fact.resolution_evidence[0].model_copy(
                            update={
                                "issue_contract_hash": SHA_A,
                            }
                        ),
                        *mismatched_fact.resolution_evidence[1:],
                    )
                }
            ),
            stale_fact.model_copy(
                update={
                    "resolution_evidence": tuple(
                        item.model_copy(
                            update={
                                "observed_at": "2026-07-28T06:59:59Z",
                            }
                        )
                        for item in stale_fact.resolution_evidence
                    )
                }
            ),
        ),
    )

    assert result.plan is None
    codes_by_issue = {
        refusal.issue.issue_number: refusal.code
        for refusal in result.refusals
    }
    assert codes_by_issue == {
        5245: "missing_resolution_evidence",
        5246: "missing_resolution_evidence",
        5247: "duplicate_resolution_evidence",
        5248: "mismatched_resolution_evidence",
        5249: "stale_resolution_evidence",
    }


def test_compiler_accepts_complete_canonical_resolution_evidence() -> None:
    issue = _issue(5250)
    result = compile_delivery_plan(
        _initiation((issue,)),
        _snapshot(
            _fact(
                issue,
                verify_targets=(
                    "tests/example.py::test_contract",
                    "doc writeback at "
                    "docs/STATUS.md :: Delivery status",
                    "runtime receipt: delivery_receipt.v1",
                ),
            )
        ),
    )

    assert result.plan is not None
    assert result.refusals == ()


@pytest.mark.parametrize(
    "source_anchor",
    [
        "TBD",
        "docs/../STATUS.md :: Delivery status",
        "./docs/STATUS.md :: Delivery status",
        "docs//STATUS.md :: Delivery status",
        "<path> :: <anchor>",
        "docs/later.md :: Delivery status",
        "docs/STATUS.md :: Delivery later",
        "docs/later.md :: later",
    ],
)
def test_compiler_rejects_noncanonical_source_anchor_parity_cases(
    source_anchor: str,
) -> None:
    issue = _issue(5243)

    result = compile_delivery_plan(
        _initiation((issue,)),
        _snapshot(_fact(issue, source_anchors=(source_anchor,))),
    )

    assert result.plan is None
    assert {refusal.code for refusal in result.refusals} == {
        "missing_source_anchors"
    }


@pytest.mark.parametrize(
    "verify_target",
    [
        "TBD",
        "`tests/../x.py::test_x`",
        "doc writeback at `docs/../STATUS.md :: Delivery status`",
        "doc writeback at `./docs/STATUS.md :: Delivery status`",
        "doc writeback at `<path> :: <anchor>`",
        "doc writeback at `docs/STATUS.md :: Delivery later`",
        (
            "`doc writeback at "
            "`docs/STATUS.md :: Delivery status``"
        ),
        "roadmap diff: `docs//ROADMAP.md :: DDO-03`",
        "runtime receipt: later",
        "runtime receipt: later.v1",
        "runtime receipt: delivery_receipt",
    ],
)
def test_compiler_rejects_unresolvable_verify_target_parity_cases(
    verify_target: str,
) -> None:
    issue = _issue(5244)

    result = compile_delivery_plan(
        _initiation((issue,)),
        _snapshot(_fact(issue, verify_targets=(verify_target,))),
    )

    assert result.plan is None
    assert {refusal.code for refusal in result.refusals} == {
        "missing_verify_targets"
    }


def test_compiler_honors_satisfied_internal_dependencies() -> None:
    dependency = _issue(5251, "1" * 64)
    dependent = _issue(5252, "2" * 64)
    result = compile_delivery_plan(
        _initiation((dependency, dependent)),
        _snapshot(
            _fact(
                dependency,
                authority=_authority(
                    dependency,
                    state="closed",
                    labels=("prio:high", "type:task"),
                ),
                delivery_status="delivered",
            ),
            _fact(
                dependent,
                dependencies=(
                    DeliveryDependency(
                        issue=dependency,
                        satisfied=True,
                    ),
                ),
            ),
        ),
    )

    assert result.plan is not None
    assert result.plan.final_scope == (dependent,)
    assert any(
        item.issue == dependency
        and item.code == "stale_delivery"
        for item in result.refusals
    )
    assert not any(
        item.issue == dependent
        for item in result.refusals
    )


@pytest.mark.parametrize(
    "agent_labels",
    [
        (),
        ("agent:blocked",),
        ("agent:unknown",),
        ("agent:blocked", "agent:ready"),
    ],
)
def test_compiler_refuses_conflicting_agent_labels(
    agent_labels: tuple[str, ...],
) -> None:
    issue = _issue(5253, "3" * 64)
    fact = _fact(
        issue,
        authority=_authority(
            issue,
            labels=tuple(
                sorted(
                    (
                        *agent_labels,
                        "prio:high",
                        "type:task",
                    )
                )
            ),
        ),
    )

    result = compile_delivery_plan(
        _initiation((issue,)),
        _snapshot(fact),
    )

    assert result.plan is None
    assert {item.code for item in result.refusals} == {
        "invalid_agent_state_labels"
    }


@pytest.mark.parametrize(
    ("labels", "expected_code"),
    [
        (
            ("agent:ready", "prio:high"),
            "invalid_type_labels",
        ),
        (
            (
                "agent:ready",
                "prio:high",
                "type:bug",
                "type:task",
            ),
            "invalid_type_labels",
        ),
        (
            (
                "agent:ready",
                "prio:high",
                "type:feature",
                "type:task",
            ),
            "invalid_type_labels",
        ),
        (
            ("agent:ready", "type:task"),
            "invalid_priority_labels",
        ),
        (
            (
                "agent:ready",
                "prio:high",
                "prio:med",
                "type:task",
            ),
            "invalid_priority_labels",
        ),
        (
            (
                "agent:ready",
                "prio:high",
                "prio:urgent",
                "type:task",
            ),
            "invalid_priority_labels",
        ),
    ],
)
def test_compiler_refuses_missing_or_duplicate_type_and_priority_labels(
    labels: tuple[str, ...],
    expected_code: str,
) -> None:
    issue = _issue(5254, "4" * 64)

    result = compile_delivery_plan(
        _initiation((issue,)),
        _snapshot(
            _fact(
                issue,
                authority=_authority(
                    issue,
                    labels=tuple(sorted(labels)),
                ),
            )
        ),
    )

    assert result.plan is None
    assert {item.code for item in result.refusals} == {expected_code}


def test_compiler_refuses_priority_snapshot_label_mismatch() -> None:
    issue = _issue(5255, "5" * 64)

    result = compile_delivery_plan(
        _initiation((issue,)),
        _snapshot(
            _fact(issue).model_copy(update={"priority": "medium"})
        ),
    )

    assert result.plan is None
    assert {item.code for item in result.refusals} == {
        "priority_label_mismatch"
    }


@pytest.mark.parametrize(
    ("state", "labels", "delivery_status"),
    [
        (
            "open",
            ("agent:ready", "prio:high", "type:task"),
            "undelivered",
        ),
        (
            "open",
            ("prio:high", "type:task"),
            "active",
        ),
        (
            "closed",
            ("prio:high", "type:task"),
            "undelivered",
        ),
    ],
)
def test_compiler_refuses_contradictory_internal_dependency_satisfaction(
    state: str,
    labels: tuple[str, ...],
    delivery_status: str,
) -> None:
    dependency = _issue(5256, "6" * 64)
    dependent = _issue(5257, "7" * 64)

    result = compile_delivery_plan(
        _initiation((dependency, dependent)),
        _snapshot(
            _fact(
                dependency,
                authority=_authority(
                    dependency,
                    state=state,
                    labels=tuple(sorted(labels)),
                ),
                delivery_status=delivery_status,
            ),
            _fact(
                dependent,
                dependencies=(
                    DeliveryDependency(
                        issue=dependency,
                        satisfied=True,
                    ),
                ),
            ),
        ),
    )

    assert any(
        item.issue == dependent
        and item.code == "contradictory_dependency_satisfaction"
        for item in result.refusals
    )
    assert result.plan is None or dependent not in result.plan.final_scope


def test_compiler_rejects_ambiguous_internal_dependency_facts() -> None:
    dependency = _issue(5260, "a" * 64)
    mismatched_dependency = _issue(5260, "b" * 64)
    dependent = _issue(5261, "c" * 64)
    dependency_ref = DeliveryDependency(
        issue=dependency,
        satisfied=True,
    )

    duplicate = compile_delivery_plan(
        _initiation((dependency, dependent)),
        _snapshot(
            _fact(
                dependency,
                authority=_authority(
                    dependency,
                    state="closed",
                    labels=("prio:high", "type:task"),
                ),
                delivery_status="delivered",
            ),
            _fact(
                dependency,
                authority=_authority(
                    dependency,
                    state="closed",
                    labels=("prio:high", "type:task"),
                ),
                delivery_status="delivered",
            ),
            _fact(dependent, dependencies=(dependency_ref,)),
        ),
    )
    mismatched = compile_delivery_plan(
        _initiation((dependency, dependent)),
        _snapshot(
            _fact(
                mismatched_dependency,
                authority=_authority(
                    mismatched_dependency,
                    state="closed",
                    labels=("prio:high", "type:task"),
                ),
                delivery_status="delivered",
            ),
            _fact(dependent, dependencies=(dependency_ref,)),
        ),
    )

    for result in (duplicate, mismatched):
        assert any(
            item.issue == dependent
            and item.code
            == "contradictory_dependency_satisfaction"
            for item in result.refusals
        )


def test_compiler_rejects_same_snapshot_external_dependency_evidence() -> None:
    dependency = _issue(5262, "d" * 64)
    dependent = _issue(5263, "e" * 64)
    evidence = DeliveryDependencySatisfactionEvidence(
        schema_version=(
            "builderops.delivery-dependency-satisfaction-evidence.v1"
        ),
        dependency_authority_id=dependency.authority_id,
        dependency_contract_hash=dependency.contract_hash,
        delivered_state="closed",
        evidence_authority_id=(
            "github:rasmustho/agentic-pkm-mvp/issues/5262/"
            "closed-event:123"
        ),
        evidence_content_hash="f" * 64,
        observed_at=RESOLVED_AT,
    )

    result = compile_delivery_plan(
        _initiation((dependency, dependent)),
        _snapshot(
            _fact(
                dependency,
                authority=_authority(
                    dependency,
                    state="closed",
                    labels=("prio:high", "type:task"),
                ),
                delivery_status="delivered",
            ),
            _fact(
                dependent,
                dependencies=(
                    DeliveryDependency(
                        issue=dependency,
                        satisfied=True,
                        satisfaction_evidence=evidence,
                    ),
                ),
            ),
        ),
    )

    assert any(
        item.issue == dependent
        and item.code == "contradictory_dependency_satisfaction"
        for item in result.refusals
    )


def test_compiler_refuses_unproven_external_dependency_satisfaction() -> None:
    external_dependency = _issue(5258, "8" * 64)
    dependent = _issue(5259, "9" * 64)

    result = compile_delivery_plan(
        _initiation((dependent,)),
        _snapshot(
            _fact(
                dependent,
                dependencies=(
                    DeliveryDependency(
                        issue=external_dependency,
                        satisfied=True,
                    ),
                ),
            )
        ),
    )

    assert result.plan is None
    assert {item.code for item in result.refusals} == {
        "unproven_dependency_satisfaction"
    }

    mismatched_evidence = DeliveryDependencySatisfactionEvidence(
        schema_version=(
            "builderops.delivery-dependency-satisfaction-evidence.v1"
        ),
        dependency_authority_id=external_dependency.authority_id,
        dependency_contract_hash="f" * 64,
        delivered_state="closed",
        evidence_authority_id=(
            "github:rasmustho/agentic-pkm-mvp/issues/5258/"
            "closed-event:123"
        ),
        evidence_content_hash="e" * 64,
        observed_at=RESOLVED_AT,
    )
    mismatched = compile_delivery_plan(
        _initiation((dependent,)),
        _snapshot(
            _fact(
                dependent,
                dependencies=(
                    DeliveryDependency(
                        issue=external_dependency,
                        satisfied=True,
                        satisfaction_evidence=mismatched_evidence,
                    ),
                ),
            )
        ),
    )
    assert mismatched.plan is None
    assert {item.code for item in mismatched.refusals} == {
        "contradictory_dependency_satisfaction"
    }


@pytest.mark.parametrize(
    "evidence_update",
    [
        {"dependency_authority_id": "github:other/issues/5258"},
        {"observed_at": "2026-07-28T07:03:01Z"},
    ],
)
def test_compiler_rejects_contradictory_external_dependency_evidence(
    evidence_update: dict[str, str],
) -> None:
    external_dependency = _issue(5258, "8" * 64)
    dependent = _issue(5259, "9" * 64)
    evidence = DeliveryDependencySatisfactionEvidence(
        schema_version=(
            "builderops.delivery-dependency-satisfaction-evidence.v1"
        ),
        dependency_authority_id=external_dependency.authority_id,
        dependency_contract_hash=external_dependency.contract_hash,
        delivered_state="closed",
        evidence_authority_id=(
            "github:rasmustho/agentic-pkm-mvp/issues/5258/"
            "closed-event:123"
        ),
        evidence_content_hash="e" * 64,
        observed_at=RESOLVED_AT,
    ).model_copy(update=evidence_update)

    result = compile_delivery_plan(
        _initiation((dependent,)),
        _snapshot(
            _fact(
                dependent,
                dependencies=(
                    DeliveryDependency(
                        issue=external_dependency,
                        satisfied=True,
                        satisfaction_evidence=evidence,
                    ),
                ),
            )
        ),
    )

    assert result.plan is None
    assert {item.code for item in result.refusals} == {
        "contradictory_dependency_satisfaction"
    }


def test_compiler_rejects_unsatisfied_dependency_evidence() -> None:
    external_dependency = _issue(5264, "1" * 64)
    dependent = _issue(5265, "2" * 64)
    evidence = DeliveryDependencySatisfactionEvidence(
        schema_version=(
            "builderops.delivery-dependency-satisfaction-evidence.v1"
        ),
        dependency_authority_id=external_dependency.authority_id,
        dependency_contract_hash=external_dependency.contract_hash,
        delivered_state="closed",
        evidence_authority_id=(
            "github:rasmustho/agentic-pkm-mvp/issues/5264/"
            "closed-event:123"
        ),
        evidence_content_hash="3" * 64,
        observed_at=RESOLVED_AT,
    )

    result = compile_delivery_plan(
        _initiation((dependent,)),
        _snapshot(
            _fact(
                dependent,
                dependencies=(
                    DeliveryDependency(
                        issue=external_dependency,
                        satisfied=False,
                        satisfaction_evidence=evidence,
                    ),
                ),
            )
        ),
    )

    assert result.plan is None
    assert any(
        item.issue == dependent
        and item.code == "contradictory_dependency_satisfaction"
        for item in result.refusals
    )


def test_compiler_v2_versions_prevent_v1_identity_reuse() -> None:
    issue = _issue(5266, "4" * 64)
    initiation = _initiation((issue,))
    snapshot = _snapshot(_fact(issue))
    result = compile_delivery_plan(initiation, snapshot)

    assert COMPILER_VERSION == "builderops.delivery-plan-compiler.v2"
    assert (
        PLANNING_SNAPSHOT_VERSION
        == "builderops.delivery-planning-snapshot.v2"
    )
    assert result.compiler_version == COMPILER_VERSION
    assert result.plan is not None
    assert (
        result.plan.provenance.created_by.actor_id
        == "builderops:delivery-plan-compiler.v2"
    )

    v1_snapshot = snapshot.model_dump(mode="json")
    v1_snapshot["schema_version"] = (
        "builderops.delivery-planning-snapshot.v1"
    )
    with pytest.raises(ValidationError):
        DeliveryPlanningSnapshot.model_validate(v1_snapshot)

    old_identity = canonical_hash(
        {
            "compiler_version": (
                "builderops.delivery-plan-compiler.v1"
            ),
            "initiation": {
                "schema_version": initiation.schema_version,
                "contract_id": initiation.initiation_id,
                "content_hash": initiation.content_hash,
            },
            "snapshot": _canonical_snapshot_payload(snapshot),
        }
    )
    assert result.input_hash != old_identity
    assert result.plan.plan_id != f"delivery-plan:{old_identity}"


def test_compiler_accepts_proven_dependency_satisfaction() -> None:
    internal_dependency = _issue(5270, "a" * 64)
    external_dependency = _issue(5271, "b" * 64)
    dependent = _issue(5272, "c" * 64)
    external_evidence = DeliveryDependencySatisfactionEvidence(
        schema_version=(
            "builderops.delivery-dependency-satisfaction-evidence.v1"
        ),
        dependency_authority_id=external_dependency.authority_id,
        dependency_contract_hash=external_dependency.contract_hash,
        delivered_state="closed",
        evidence_authority_id=(
            "github:rasmustho/agentic-pkm-mvp/issues/5271/"
            "closed-event:123"
        ),
        evidence_content_hash="d" * 64,
        observed_at=RESOLVED_AT,
    )

    result = compile_delivery_plan(
        _initiation((internal_dependency, dependent)),
        _snapshot(
            _fact(
                internal_dependency,
                authority=_authority(
                    internal_dependency,
                    state="closed",
                    labels=("prio:high", "type:task"),
                ),
                delivery_status="delivered",
            ),
            _fact(
                dependent,
                dependencies=(
                    DeliveryDependency(
                        issue=internal_dependency,
                        satisfied=True,
                    ),
                    DeliveryDependency(
                        issue=external_dependency,
                        satisfied=True,
                        satisfaction_evidence=external_evidence,
                    ),
                ),
            ),
        ),
    )

    assert result.plan is not None
    assert result.plan.final_scope == (dependent,)
    assert not any(
        item.issue == dependent for item in result.refusals
    )

    changed_evidence = external_evidence.model_copy(
        update={"evidence_content_hash": "e" * 64}
    )
    changed = compile_delivery_plan(
        _initiation((internal_dependency, dependent)),
        _snapshot(
            _fact(
                internal_dependency,
                authority=_authority(
                    internal_dependency,
                    state="closed",
                    labels=("prio:high", "type:task"),
                ),
                delivery_status="delivered",
            ),
            _fact(
                dependent,
                dependencies=(
                    DeliveryDependency(
                        issue=internal_dependency,
                        satisfied=True,
                    ),
                    DeliveryDependency(
                        issue=external_dependency,
                        satisfied=True,
                        satisfaction_evidence=changed_evidence,
                    ),
                ),
            ),
        ),
    )
    assert changed.plan is not None
    assert changed.input_hash != result.input_hash
    assert changed.plan.plan_id != result.plan.plan_id


def test_compiler_refuses_scope_over_worker_start_budget() -> None:
    issues = tuple(
        _issue(5260 + index, f"{index + 1:064x}")
        for index in range(3)
    )
    result = compile_delivery_plan(
        _initiation(
            issues,
            max_parallel_workers=1,
            max_worker_starts=2,
        ),
        _snapshot(*(_fact(issue) for issue in issues)),
    )

    assert result.plan is None
    assert {
        refusal.code for refusal in result.refusals
    } == {"budget_exceeded"}


def test_compiler_separates_exact_set_from_parent_closure() -> None:
    parent = _issue(5300, "0" * 64)
    child_a = _issue(5301, "1" * 64)
    child_b = _issue(5302, "2" * 64)

    exact_result = compile_delivery_plan(
        _initiation((child_a, child_b)),
        _snapshot(_fact(child_a), _fact(child_b)),
    )
    parent_result = compile_delivery_plan(
        _initiation((parent, child_a, child_b)),
        _snapshot(
            _fact(
                parent,
                scope_role="validation_parent",
            ),
            _fact(child_a, parent_issue=parent),
            _fact(child_b, parent_issue=parent),
        ),
    )

    assert exact_result.plan is not None
    assert parent_result.plan is not None
    assert exact_result.plan.final_scope == (child_a, child_b)
    assert parent_result.plan.final_scope == (child_a, child_b)
    assert parent not in {
        issue
        for wave in parent_result.plan.dependency_waves
        for issue in wave.issues
    }
    assert any(
        refusal.code == "parent_validation_only"
        and refusal.issue == parent
        for refusal in parent_result.refusals
    )
    assert any(
        exclusion.omitted_issue == parent
        for exclusion in parent_result.plan.exclusions
    )


def test_compiler_has_no_effect_adapter_access() -> None:
    import app.builderops.delivery_plan_compiler as compiler_module

    module = ast.parse(inspect.getsource(compiler_module))
    imported_modules = {
        alias.name
        for node in ast.walk(module)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(module)
        if isinstance(node, ast.ImportFrom)
    }
    forbidden_prefixes = (
        "app.builderops.ckm",
        "app.builderops.store",
        "app.dispatcher",
        "github",
        "requests",
        "subprocess",
    )

    assert not any(
        module_name.startswith(forbidden_prefixes)
        for module_name in imported_modules
    )
    encoded_schema = json.dumps(
        {
            "input": DeliveryPlanningSnapshot.model_json_schema(),
            "output": DeliveryPlanCompilation.model_json_schema(),
        },
        sort_keys=True,
    ).casefold()
    for forbidden_contract_term in (
        "durable_carrier",
        "ckm_renderer",
        "model_provider",
        "provider_name",
        "model_name",
    ):
        assert forbidden_contract_term not in encoded_schema

    issue = _issue(5401)
    result = compile_delivery_plan(
        _initiation((issue,)),
        _snapshot(_fact(issue)),
    )
    assert result.plan is not None
    assert result.external_mutations == ()
