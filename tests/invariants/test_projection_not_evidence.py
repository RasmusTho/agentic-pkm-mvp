"""Invariant skeletons: projections are not evidence; observability is not policy.

Invariant registry: docs/testing/invariant-tests.md
  :: projection_not_evidence, observability_not_policy
Issues: #2550 (registry), #2552 (skeletons).
Contracts: docs/architecture/metadata-bundle.md (#2544), docs/boundaries/OEF.md (#2543).
"""

from __future__ import annotations

import json

import pytest

from tests.invariants._helpers import future_runtime, load_schema, read_doc


def test_projection_schema_defaults_non_evidence() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: projection_not_evidence
    # Static companion (schema_enforced): the metadata bundle conditionally requires an
    # authority_receipt_ref before a projection may hold an `evidence` role.
    schema = load_schema("metadata-bundle.schema.json")
    text = json.dumps(schema)
    assert "projection" in text
    assert "authority_receipt_ref" in text
    # The schema is conditional (a projection is not evidence unless promoted with a receipt).
    assert schema.get("allOf") or schema.get("if") or "if" in text


@pytest.mark.xfail(
    reason=(
        "Runtime projection/DRI path not implemented yet; this skeleton protects invariant "
        "projection_not_evidence (#2550). A projection defaults to non_evidence and gains evidence "
        "standing only through a provenance-backed promotion. Future vertical slice: DRI projection."
    ),
    strict=True,
)
def test_projection_not_evidence() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: projection_not_evidence
    dri = future_runtime("projection")  # raises until projection runtime exists
    projection = dri.build_projection(source_ids=["art-1", "art-2"])
    # Intended assertion: a freshly built projection is non-evidence until promoted.
    assert projection.metadata_bundle.evidence_role == "non_evidence"


def test_oef_charter_states_observability_not_policy() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: observability_not_policy
    # Static companion (doc_only): the OEF charter normatively states the separation rule.
    charter = read_doc("docs/boundaries/OEF.md")
    assert "observes and evaluates" in charter.lower() or "observability" in charter.lower()
    assert "gov" in charter.lower()


@pytest.mark.xfail(
    reason=(
        "Runtime observability/OEF path not implemented yet; this skeleton protects invariant "
        "observability_not_policy (#2550). OEF surfaces drift for a GOV decision and never closes the "
        "loop itself. Future vertical slice: OEF."
    ),
    strict=True,
)
def test_observability_not_policy() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: observability_not_policy
    oef = future_runtime("observability")  # raises until observability runtime exists
    report = oef.evaluate_fitness()
    # Intended assertion: an OEF report is a non-authoritative projection, never a policy mutation.
    assert report.mutated_policy is False
    assert report.authority_state in {"derived", "projection"}
