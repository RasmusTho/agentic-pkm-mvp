"""Runtime conformance tests for the retrieval prefilter (#2582 / YRS1-04).

Complement the auto-converting skeletons (scope prefilter, similarity-not-permission, cross-scope,
private/general/RPG evals) by pinning that scope/policy eligibility is computed BEFORE ranking at the
``retrieve`` call site, and that cross_scope.evaluate denies without a flow / admits via one.

Invariant registry: docs/testing/invariant-tests.md :: retrieve_scope_prefilter, similarity_not_permission,
cross_scope_only_via_flow
Spec: docs/YGGDRASIL_RUNTIME_SLICE_1/RETRIEVAL_PREFILTER_BEFORE_RANKING.md
"""

from __future__ import annotations

from yggdrasil_runtime import cross_scope, retrieval

_ALPHA = "scope:work/project-alpha"


def test_prefilter_runs_before_ranking() -> None:
    # The eligible set is computed by scope/policy eligibility (not similarity), and ranking only
    # orders that set. A query crafted to be highly similar to a *Beta* doc must still admit no Beta
    # candidate — exclusion happens before ranking, never "ranked lower".
    result = retrieval.retrieve(query="telemetry state machine event bus", active_scope_id=_ALPHA)
    assert result.scope_policy_prefiltered is True
    assert result.candidate_items, "expected in-scope Alpha candidates"
    for c in result.candidate_items:
        assert c.metadata_bundle.scope_id == _ALPHA
    # The eligible set (computed before scoring) is exactly the active-scope, visible docs.
    eligible = retrieval.eligible_candidates("telemetry state machine event bus", _ALPHA)
    assert eligible, "prefilter produced an eligible set before ranking"
    assert all(d.metadata_bundle.scope_id == _ALPHA for d in eligible)
    # No out-of-scope scope leaks into the ranked candidates.
    leaked = {c.metadata_bundle.scope_id for c in result.candidate_items} - {_ALPHA}
    assert leaked == set(), f"out-of-scope material must be excluded before ranking, leaked: {leaked}"


def test_evidence_role_in_context_not_upgraded() -> None:
    # Import-gate: retrieval.py auto-enables the monotonicity skeleton. Each candidate's in-context
    # role must never exceed its intrinsic role.
    order = ["non_evidence", "inspiration", "analogy", "reference", "background", "evidence"]
    result = retrieval.retrieve(query="anything", active_scope_id=_ALPHA)
    for c in result.candidate_items:
        assert order.index(c.evidence_role_in_context) <= order.index(c.metadata_bundle.evidence_role)


def test_cross_scope_denied_without_flow() -> None:
    decision = cross_scope.evaluate("scope:general/programming", _ALPHA, "cite", flow=None)
    assert decision.allowed is False


def test_cross_scope_allows_via_flow_as_conservative_role() -> None:
    decision = cross_scope.evaluate(
        "scope:general/programming", _ALPHA, "cite",
        flow={"allowed_operations": ["retrieve", "surface", "cite"], "evidence_roles_allowed": ["background"]},
    )
    assert decision.allowed is True
    assert decision.evidence_role_in_target == "background"


def test_cross_scope_flow_direction_is_enforced() -> None:
    # A flow that declares its own scopes must match this crossing; a reversed flow is denied even
    # if it allows the operation (grants are directional).
    reversed_flow = {
        "source_scope": _ALPHA, "target_scope": "scope:general/programming",
        "allowed_operations": ["cite"], "evidence_roles_allowed": ["background"],
    }
    decision = cross_scope.evaluate("scope:general/programming", _ALPHA, "cite", flow=reversed_flow)
    assert decision.allowed is False


def test_cross_scope_denies_flow_without_target_role() -> None:
    # A flow with no recognized target evidence role cannot admit (no role to downgrade/bound to).
    decision = cross_scope.evaluate(
        "scope:general/programming", _ALPHA, "cite",
        flow={"allowed_operations": ["cite"], "evidence_roles_allowed": []},
    )
    assert decision.allowed is False


def test_cross_scope_denies_ungranted_operation() -> None:
    # A flow that allows cite must not implicitly grant import/mutate.
    decision = cross_scope.evaluate(
        "scope:general/programming", _ALPHA, "import",
        flow={"allowed_operations": ["retrieve", "surface", "cite"], "evidence_roles_allowed": ["background"]},
    )
    assert decision.allowed is False
