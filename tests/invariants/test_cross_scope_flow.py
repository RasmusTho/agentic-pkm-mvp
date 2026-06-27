"""Invariant skeletons: similarity is not permission; crossing scopes needs a typed flow.

Invariant registry: docs/testing/invariant-tests.md
  :: similarity_not_permission, cross_scope_only_via_flow, retrieve_scope_prefilter,
     parent_aggregation_not_sibling_sharing, sync_preserves_boundaries
Issues: #2550 (registry), #2552 (skeletons).
Contracts: docs/architecture/cross-scope-flow.md (#2539), docs/architecture/retrieval-contract.md (#2548).

Runtime skeletons xfail *only* on the missing runtime import (require_future_runtime); their
assertions run for real once the runtime exists.
"""

from __future__ import annotations

from tests.invariants._helpers import load_schema, require_future_runtime


def test_scope_prefilter_asserted_in_schema() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: retrieve_scope_prefilter
    # Static companion (schema_enforced): a RetrievalResult pins scope_policy_prefiltered=true, so
    # eligibility-before-ranking is asserted in the data shape itself.
    rr = load_schema("retrieval-result.schema.json")
    flag = rr["properties"]["scope_policy_prefiltered"]
    assert flag.get("const") is True
    assert "scope_policy_prefiltered" in rr.get("required", [])


def test_retrieve_scope_prefilter() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: retrieve_scope_prefilter
    rca = require_future_runtime(
        "retrieval",
        "Runtime retrieval prefilter not implemented yet; protects retrieve_scope_prefilter (#2550).",
    )
    result = rca.retrieve(query="state machine", active_scope_id="scope:work/project-alpha")
    # Out-of-scope material is excluded before ranking, not merely ranked lower.
    for candidate in result.candidate_items:
        assert candidate.metadata_bundle.scope_id == "scope:work/project-alpha"


def test_similarity_is_not_permission() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: similarity_not_permission
    rca = require_future_runtime(
        "retrieval",
        "Runtime ranking/admission not implemented yet; protects similarity_not_permission (#2550).",
    )
    # A Project Beta doc is highly similar to a Project Alpha query, but similarity must not admit it.
    result = rca.retrieve(query="telemetry state machine", active_scope_id="scope:work/project-alpha")
    admitted = [c for c in result.candidate_items if c.admissibility_status == "admitted"]
    assert all(c.metadata_bundle.scope_id == "scope:work/project-alpha" for c in admitted)


def test_cross_scope_only_via_flow() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: cross_scope_only_via_flow
    gov = require_future_runtime(
        "cross_scope",
        "Runtime CrossScopeFlow enforcement not implemented yet; protects cross_scope_only_via_flow (#2550).",
    )
    # With no flow, a cross-scope operation must be denied.
    decision = gov.evaluate(
        source_scope="scope:general/programming",
        target_scope="scope:work/project-alpha",
        operation="cite",
        flow=None,
    )
    assert decision.allowed is False


def test_parent_aggregation_not_sibling_sharing() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: parent_aggregation_not_sibling_sharing
    wsp = require_future_runtime(
        "scope",
        "Runtime scope/aggregation not implemented yet; protects parent_aggregation_not_sibling_sharing (#2550).",
    )
    # Alpha and Beta share a parent, but Alpha must not reach Beta without an Alpha->Beta flow.
    visible = wsp.aggregated_scopes(active_scope_id="scope:work/project-alpha")
    assert "scope:work/project-beta" not in visible


def test_sync_preserves_boundaries() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: sync_preserves_boundaries
    sfc = require_future_runtime(
        "sync",
        "Runtime sync/federation not implemented yet; protects sync_preserves_boundaries (#2550).",
    )
    merged = sfc.merge_replica(object_id="obj-1")
    # A replica merge never changes scope/authority by last-writer-wins.
    assert merged.scope_id_unchanged
    assert merged.authority_state_unchanged
