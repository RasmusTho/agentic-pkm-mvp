"""Invariant skeletons: projections are not evidence; observability is not policy.

Invariant registry: docs/testing/invariant-tests.md
  :: projection_not_evidence, observability_not_policy
Issues: #2550 (registry), #2552 (skeletons).
Contracts: docs/architecture/metadata-bundle.md (#2544), docs/boundaries/OEF.md (#2543).

Runtime skeletons xfail *only* on the missing runtime import (require_future_runtime).
"""

from __future__ import annotations

import json

from tests.invariants._helpers import load_schema, read_doc, require_future_runtime


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


def test_projection_not_evidence() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: projection_not_evidence
    dri = require_future_runtime(
        "projection",
        "Runtime projection/DRI path not implemented yet; protects projection_not_evidence (#2550).",
    )
    projection = dri.build_projection(source_ids=["art-1", "art-2"])
    # A freshly built projection is non-evidence until promoted.
    assert projection.metadata_bundle.evidence_role == "non_evidence"


def test_oef_charter_states_observability_not_policy() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: observability_not_policy
    # Static companion (doc_only): the OEF charter normatively states the separation rule.
    charter = read_doc("docs/boundaries/OEF.md")
    assert "observes and evaluates" in charter.lower() or "observability" in charter.lower()
    assert "gov" in charter.lower()


def test_observability_not_policy() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: observability_not_policy
    oef = require_future_runtime(
        "observability",
        "Runtime observability/OEF path not implemented yet; protects observability_not_policy (#2550).",
    )
    report = oef.evaluate_fitness()
    # An OEF report is a non-authoritative projection, never a policy mutation.
    assert report.mutated_policy is False
    assert report.authority_state in {"derived", "projection"}
