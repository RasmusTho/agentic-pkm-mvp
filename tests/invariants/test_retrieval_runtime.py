"""Runtime conformance tests for the retrieval prefilter (#2582 / YRS1-04).

Complement the auto-converting skeletons (scope prefilter, similarity-not-permission, cross-scope,
private/general/RPG evals) by pinning that scope/policy eligibility is computed BEFORE ranking at the
``retrieve`` call site, and that cross_scope.evaluate denies without a flow / admits via one.

Invariant registry: docs/testing/invariant-tests.md :: retrieve_scope_prefilter, similarity_not_permission,
cross_scope_only_via_flow
Spec: docs/YGGDRASIL_RUNTIME_SLICE_1/RETRIEVAL_PREFILTER_BEFORE_RANKING.md
"""

from __future__ import annotations

from tests.invariants._helpers import assert_validates

from yggdrasil_runtime import cross_scope, retrieval

_ALPHA = "scope:work/project-alpha"

# Closed scope_denial shape — denial records must carry no identifying fields beyond these.
_SCOPE_DENIAL_KEYS = {"reason", "denial_class", "escalation_recommended", "required_flow_class", "audit_ref"}
_IDENTITY_LEAK_KEYS = {"object_id", "scope_id", "metadata_bundle", "content", "text", "provenance_event_ids"}


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


def test_retrieval_result_validates_against_schema() -> None:
    # The emitted RetrievalResult conforms to the contract schema (scope_policy_prefiltered const true,
    # candidate bundles, content-free denied list, required ids/timestamps).
    result = retrieval.retrieve(query="state machine event bus", active_scope_id=_ALPHA)
    assert_validates(result.to_dict(), "retrieval-result.schema.json")


def test_runtime_denied_list_is_content_free() -> None:
    # A query matching shared vocab surfaces relevant material in other scopes; the denial list must
    # record that material was withheld (not silently dropped) WITHOUT leaking object/scope identity,
    # content, or provenance.
    result = retrieval.retrieve(query="system agent rule state event workflow", active_scope_id=_ALPHA)
    payload = result.to_dict()
    denied = payload["denied_or_escalated_candidates"]
    assert denied, "relevant cross-scope material must be recorded as a content-free denial"
    for entry in denied:
        assert set(entry).issubset(_SCOPE_DENIAL_KEYS), f"unexpected key in denial: {set(entry)}"
        assert _IDENTITY_LEAK_KEYS.isdisjoint(entry), "denial must not leak identity/content"
        assert entry["reason"] and entry["denial_class"]
    # Confirm no out-of-scope scope_id leaked into the surfaced candidates either.
    assert all(c["metadata_bundle"]["scope_id"] == _ALPHA for c in payload["candidate_items"])


def test_candidate_identity_is_single_source() -> None:
    # Candidate identity comes only from the embedded bundle; no sibling object_id at item level.
    result = retrieval.retrieve(query="state machine", active_scope_id=_ALPHA)
    for item in result.to_dict()["candidate_items"]:
        assert "object_id" not in item
        assert item["metadata_bundle"]["object_id"]


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
