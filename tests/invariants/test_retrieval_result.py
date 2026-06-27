"""Invariant skeletons: candidate identity has one source; retrieval cannot upgrade evidence.

Invariant registry: docs/testing/invariant-tests.md
  :: retrieval_candidate_identity_single_source, retrieval_cannot_upgrade_intrinsic_non_evidence,
     denied_scope_does_not_leak_identity (retrieval side)
Issues: #2550 (registry), #2552 (skeletons). Contract: docs/architecture/retrieval-contract.md (#2548).
See schemas/README.md :: Known JSON Schema limits for the deferred cross-field monotonicity check.
"""

from __future__ import annotations

import json

import pytest

from tests.invariants._helpers import future_runtime, load_schema


def test_retrieval_candidate_identity_single_source() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: retrieval_candidate_identity_single_source
    # Static (schema_enforced): a candidate carries its identity only via its embedded metadata bundle;
    # there is no parallel top-level object_id to drift from it.
    item = load_schema("retrieval-result.schema.json")["properties"]["candidate_items"]["items"]
    props = item.get("properties", {})
    assert "metadata_bundle" in props
    assert "metadata_bundle" in item.get("required", [])
    assert "object_id" not in props, "candidate must not carry a sibling object_id (single source of truth)"


def test_retrieval_cannot_upgrade_intrinsic_non_evidence() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: retrieval_cannot_upgrade_intrinsic_non_evidence
    # Static (schema_enforced): the dangerous non-evidence -> `evidence` upgrade is blocked
    # structurally in the candidate item (an intrinsic non-authoritative role forces a
    # non-authoritative in-context role). The full ordinal "in-context <= intrinsic" rule is a
    # cross-field check pinned by the runtime skeleton below.
    item = load_schema("retrieval-result.schema.json")["properties"]["candidate_items"]["items"]
    assert item.get("allOf"), "candidate item must carry conditional constraints"
    text = json.dumps(item["allOf"])
    assert "non_authoritative_evidence_role" in text
    assert "evidence_role_in_context" in json.dumps(item["properties"])


def test_retrieval_denied_candidates_are_content_free() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: denied_scope_does_not_leak_identity
    # Static (schema_enforced): denied/escalated cross-scope material is recorded only in the
    # content-free denied_or_escalated_candidates list (the closed scope_denial record).
    rr = load_schema("retrieval-result.schema.json")
    denied = rr["properties"]["denied_or_escalated_candidates"]["items"]
    assert "scope_denial" in str(denied)


@pytest.mark.xfail(
    reason=(
        "Runtime retrieval not implemented yet; this skeleton protects the full cross-field rule for "
        "retrieval_cannot_upgrade_intrinsic_non_evidence (#2550): in-context evidence role must be "
        "ordinally <= the intrinsic role for every candidate. JSON Schema cannot express the general "
        "ordinal comparison (schemas/README.md :: Known JSON Schema limits). Future vertical slice: RCA result."
    ),
    strict=True,
)
def test_retrieval_full_evidence_monotonicity_runtime() -> None:
    rca = future_runtime("retrieval")  # raises until retrieval runtime exists
    result = rca.retrieve(query="anything", active_scope_id="scope:work/project-alpha")
    order = ["non_evidence", "inspiration", "analogy", "reference", "background", "evidence"]
    for candidate in result.candidate_items:
        intrinsic = candidate.metadata_bundle.evidence_role
        in_context = candidate.evidence_role_in_context
        assert order.index(in_context) <= order.index(intrinsic)
