"""Invariant skeletons: the metadata bundle is required and storage keeps no naked vectors.

Invariant registry: docs/testing/invariant-tests.md
  :: metadata_bundle_required, store_no_naked_vectors, provenance_survives_derivation,
     capture_stamps_scope
Issues: #2550 (registry), #2552 (skeletons). Contract: docs/architecture/metadata-bundle.md (#2544).

Runtime skeletons xfail *only* on the missing runtime import (require_future_runtime); once the
runtime exists their assertions run for real, so a wrong implementation fails rather than being
masked.
"""

from __future__ import annotations

from tests.invariants._helpers import load_schema, require_future_runtime

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


def test_provenance_survives_derivation() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: provenance_survives_derivation
    # The schema already requires derived_from for derived types; this asserts the DRI runtime
    # preserves lineage when it produces a segment. Future vertical slice: Capture -> DRI segment.
    dri = require_future_runtime(
        "dri",
        "Runtime derivation (DRI) not implemented yet; protects provenance_survives_derivation (#2550).",
    )
    segment = dri.derive_segment(artifact_id="art-1")
    assert segment.metadata_bundle.derived_from
    assert segment.metadata_bundle.scope_id
    assert segment.metadata_bundle.provenance_event_ids


def test_capture_stamps_scope() -> None:
    # Invariant registry: docs/testing/invariant-tests.md :: capture_stamps_scope
    # The schema already requires scope_id on every bundle; this asserts the capture runtime stamps
    # it at capture time. Future vertical slice: Capture -> MetadataBundle.
    capture = require_future_runtime(
        "capture",
        "Runtime capture not implemented yet; protects capture_stamps_scope (#2550).",
    )
    obj = capture.capture(text="a thought", principal_id="p-1")
    assert obj.metadata_bundle.scope_id
    assert obj.metadata_bundle.source_role
