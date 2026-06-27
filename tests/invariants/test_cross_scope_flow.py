"""Invariant skeletons: similarity is not permission; crossing scopes needs a typed flow.

Invariant registry: docs/testing/invariant-tests.md
  :: similarity_not_permission, cross_scope_only_via_flow, retrieve_scope_prefilter,
     parent_aggregation_not_sibling_sharing, sync_preserves_boundaries
Issues: #2550 (registry), #2552 (skeletons).
Contracts: docs/architecture/cross-scope-flow.md (#2539), docs/architecture/retrieval-contract.md (#2548).
"""

from __future__ import annotations

import pytest

from tests.invariants._helpers import future_runtime, load_schema


def test_scope_prefilter_asserted_in_schema() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: retrieve_scope_prefilter
    # Static companion (schema_enforced): a RetrievalResult pins scope_policy_prefiltered=true, so
    # eligibility-before-ranking is asserted in the data shape itself.
    rr = load_schema("retrieval-result.schema.json")
    flag = rr["properties"]["scope_policy_prefiltered"]
    assert flag.get("const") is True
    assert "scope_policy_prefiltered" in rr.get("required", [])


@pytest.mark.xfail(
    reason=(
        "Runtime retrieval prefilter not implemented yet; this skeleton protects invariant "
        "retrieve_scope_prefilter (#2550). Future vertical slice: retrieval prefilter -> RCA result."
    ),
    strict=True,
)
def test_retrieve_scope_prefilter() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: retrieve_scope_prefilter
    rca = future_runtime("retrieval")  # raises until retrieval runtime exists
    result = rca.retrieve(query="state machine", active_scope_id="scope:work/project-alpha")
    # Intended assertion: out-of-scope material is excluded before ranking, not merely ranked lower.
    for candidate in result.candidate_items:
        assert candidate.metadata_bundle.scope_id == "scope:work/project-alpha"


@pytest.mark.xfail(
    reason=(
        "Runtime ranking/admission not implemented yet; this skeleton protects invariant "
        "similarity_is_not_permission (#2550). Ranking surfaces candidates; admission is a GOV "
        "decision. Future vertical slice: RCA result admission."
    ),
    strict=True,
)
def test_similarity_is_not_permission() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: similarity_not_permission
    rca = future_runtime("retrieval")  # raises until retrieval runtime exists
    # A Project Beta doc is highly similar to a Project Alpha query, but similarity must not admit it.
    result = rca.retrieve(query="telemetry state machine", active_scope_id="scope:work/project-alpha")
    admitted = [c for c in result.candidate_items if c.admissibility_status == "admitted"]
    assert all(c.metadata_bundle.scope_id == "scope:work/project-alpha" for c in admitted)


@pytest.mark.xfail(
    reason=(
        "Runtime CrossScopeFlow enforcement not implemented yet; this skeleton protects invariant "
        "cross_scope_only_via_flow (#2550). Cross-scope use requires a typed, directional, "
        "operation-specific flow. Future vertical slice: GOV cross-scope evaluation."
    ),
    strict=True,
)
def test_cross_scope_only_via_flow() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: cross_scope_only_via_flow
    gov = future_runtime("cross_scope")  # raises until cross-scope runtime exists
    # With no flow, a cross-scope operation must be denied.
    decision = gov.evaluate(
        source_scope="scope:general/programming",
        target_scope="scope:work/project-alpha",
        operation="cite",
        flow=None,
    )
    assert decision.allowed is False


@pytest.mark.xfail(
    reason=(
        "Runtime scope/sync aggregation not implemented yet; this skeleton protects invariant "
        "parent_aggregation_not_sibling_sharing (#2550). A parent aggregation does not imply sibling "
        "sharing. Future vertical slice: WSP/SFC aggregation."
    ),
    strict=True,
)
def test_parent_aggregation_not_sibling_sharing() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: parent_aggregation_not_sibling_sharing
    wsp = future_runtime("scope")  # raises until scope/aggregation runtime exists
    # Alpha and Beta share a parent, but Alpha must not reach Beta without an Alpha->Beta flow.
    visible = wsp.aggregated_scopes(active_scope_id="scope:work/project-alpha")
    assert "scope:work/project-beta" not in visible


@pytest.mark.xfail(
    reason=(
        "Runtime sync/federation not implemented yet; this skeleton protects invariant "
        "sync_preserves_boundaries (#2550). Sync never promotes/rescopes; a semantic conflict is a "
        "governed AuthorityTransition. Future vertical slice: SFC."
    ),
    strict=True,
)
def test_sync_preserves_boundaries() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: sync_preserves_boundaries
    sfc = future_runtime("sync")  # raises until sync runtime exists
    merged = sfc.merge_replica(object_id="obj-1")
    # Intended assertion: a replica merge never changes scope/authority by last-writer-wins.
    assert merged.scope_id_unchanged
    assert merged.authority_state_unchanged
