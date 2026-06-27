"""Invariant skeletons: the metadata bundle is required and storage keeps no naked vectors.

Invariant registry: docs/testing/invariant-tests.md
  :: metadata_bundle_required, store_no_naked_vectors, provenance_survives_derivation,
     capture_stamps_scope
Issues: #2550 (registry), #2552 (skeletons). Contract: docs/architecture/metadata-bundle.md (#2544).
"""

from __future__ import annotations

import pytest

from tests.invariants._helpers import future_runtime, load_schema

# Core semantics + provenance every usable object must carry — a "naked vector" has none of these.
_CORE_SEMANTIC_PROVENANCE = {
    "object_id",
    "object_type",
    "scope_id",
    "source_role",
    "authority_state",
    "evidence_role",
    "provenance_event_ids",
}


def test_metadata_bundle_required() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: metadata_bundle_required
    # Static (schema_enforced): the bundle requires identity, scope, the three orthogonal role
    # dimensions, and provenance — there is no usable object without the core set.
    schema = load_schema("metadata-bundle.schema.json")
    required = set(schema.get("required", []))
    missing = _CORE_SEMANTIC_PROVENANCE - required
    assert not missing, f"metadata bundle must require {sorted(missing)}"
    # The three role dimensions are three separate required fields (non-collapse rule).
    props = schema.get("properties", {})
    for dim in ("source_role", "authority_state", "evidence_role"):
        assert dim in props, f"{dim} must be its own field"


def test_store_no_naked_vectors() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: store_no_naked_vectors
    # Static (schema_enforced): a chunk/embedding cannot validate without its metadata bundle.
    bundle = load_schema("metadata-bundle.schema.json")
    assert bundle.get("additionalProperties") is False, "bundle must be a closed object"
    assert _CORE_SEMANTIC_PROVENANCE <= set(bundle.get("required", []))
    # Every retrieval candidate carries a metadata bundle (no separate naked content shape).
    rr = load_schema("retrieval-result.schema.json")
    item = rr["properties"]["candidate_items"]["items"]
    assert "metadata_bundle" in item.get("properties", {}), "candidate must carry a metadata bundle"
    assert "metadata_bundle" in item.get("required", []), "metadata_bundle must be required per candidate"


@pytest.mark.xfail(
    reason=(
        "Runtime derivation (DRI) not implemented yet; this skeleton protects invariant "
        "provenance_survives_derivation (#2550). The schema already requires derived_from for "
        "derived types; the runtime that produces segments/projections must preserve lineage. "
        "Future vertical slice: Capture -> MetadataBundle -> DRI segment."
    ),
    strict=True,
)
def test_provenance_survives_derivation() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: provenance_survives_derivation
    dri = future_runtime("dri")  # raises until the DRI runtime exists
    segment = dri.derive_segment(artifact_id="art-1")
    # Intended assertion once runtime lands: a derived segment keeps its source's provenance/scope.
    assert segment.metadata_bundle.derived_from
    assert segment.metadata_bundle.scope_id
    assert segment.metadata_bundle.provenance_event_ids


@pytest.mark.xfail(
    reason=(
        "Runtime capture not implemented yet; this skeleton protects invariant capture_stamps_scope "
        "(#2550). The schema already requires scope_id on every bundle; the capture runtime must "
        "stamp it at capture time. Future vertical slice: Capture -> MetadataBundle."
    ),
    strict=True,
)
def test_capture_stamps_scope() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: capture_stamps_scope
    capture = future_runtime("capture")  # raises until the capture runtime exists
    obj = capture.capture(text="a thought", principal_id="p-1")
    # Intended assertion once runtime lands: nothing enters the system scope-less.
    assert obj.metadata_bundle.scope_id
    assert obj.metadata_bundle.source_role
