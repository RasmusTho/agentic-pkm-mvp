from __future__ import annotations

import ast
import inspect
import json

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
    delivery_initiation_approval_hash,
)
from app.builderops.delivery_plan_compiler import (
    REQUIRED_SBS_IMPACT_FIELDS,
    DeliveryDependency,
    DeliveryIssuePlanningSnapshot,
    DeliveryPlanCompilation,
    DeliveryPlanningSnapshot,
    SbsImpactEntry,
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
        max_worker_starts=max(len(issues), max_parallel_workers),
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


def _fact(
    issue: IssueScope,
    *,
    authority: AuthoritySnapshot | None = None,
    dependencies: tuple[DeliveryDependency, ...] = (),
    mutation_paths: tuple[str, ...] = (),
    verify_targets: tuple[str, ...] = ("tests/example.py::test_contract",),
    sbs_impact: tuple[SbsImpactEntry, ...] | None = None,
    delivery_status: str = "undelivered",
    linked_pr_head: str | None = None,
    parent_issue: IssueScope | None = None,
    scope_role: str = "delivery",
) -> DeliveryIssuePlanningSnapshot:
    return DeliveryIssuePlanningSnapshot(
        issue=issue,
        authority=authority or _authority(issue),
        priority="high",
        risk_class="medium",
        source_anchors=(
            "docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/"
            "COMPILE_IMMUTABLE_DELIVERY_PLANS.md :: What This Task Does",
        ),
        verify_targets=verify_targets,
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
        "missing_verify_targets",
        "mutation_overlap",
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
