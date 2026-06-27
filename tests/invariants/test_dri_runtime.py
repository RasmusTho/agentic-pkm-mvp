"""Runtime conformance tests for the DRI stage (#2581 / YRS1-03).

Complement the auto-converting skeleton ``test_metadata_bundle.py::test_provenance_survives_derivation``
by validating segment-bundle schema conformance, inheritance from the source, and the no-naked-segment
construction guarantee.

Invariant registry: docs/testing/invariant-tests.md :: provenance_survives_derivation, store_no_naked_vectors
Spec: docs/YGGDRASIL_RUNTIME_SLICE_1/DRI_SEGMENT_CARRIES_PROVENANCE.md
"""

from __future__ import annotations

import pytest

from tests.invariants._helpers import assert_validates

from yggdrasil_runtime import capture, dri
from yggdrasil_runtime.metadata import MetadataBundle


def test_segment_bundle_validates_against_schema() -> None:
    seg = dri.derive_segment(artifact_id="art-1")
    assert_validates(seg.metadata_bundle.to_dict(), "metadata-bundle.schema.json")
    assert seg.metadata_bundle.object_type == "segment"
    assert list(seg.metadata_bundle.derived_from) == ["art-1"]
    assert seg.metadata_bundle.provenance_event_ids  # >= 1 (preserved + derivation event)


def test_segment_inherits_source_scope_and_role() -> None:
    # Derive from a *captured* artifact and assert the segment inherits scope/source/authority/
    # evidence from it (not re-stamped fresh), and that lineage + provenance are preserved.
    src = capture.capture(text="a stateful idea", principal_id="p-1")
    src_bundle = src.metadata_bundle
    seg = dri.derive_segment(artifact_id=src_bundle.object_id)

    assert seg.metadata_bundle.scope_id == src_bundle.scope_id
    assert seg.metadata_bundle.source_role == src_bundle.source_role
    assert seg.metadata_bundle.authority_state == src_bundle.authority_state
    assert seg.metadata_bundle.evidence_role == src_bundle.evidence_role
    assert list(seg.metadata_bundle.derived_from) == [src_bundle.object_id]
    # provenance preserved: every source event is still present, plus a derivation event
    assert set(src_bundle.provenance_event_ids).issubset(set(seg.metadata_bundle.provenance_event_ids))
    assert len(seg.metadata_bundle.provenance_event_ids) > len(src_bundle.provenance_event_ids)


def test_segment_evidence_role_not_upgraded() -> None:
    # Inheritance must not upgrade the evidence role toward `evidence`.
    src = capture.capture(text="background note", principal_id="p-2")
    seg = dri.derive_segment(artifact_id=src.metadata_bundle.object_id)
    order = ["non_evidence", "inspiration", "analogy", "reference", "background", "evidence"]
    assert order.index(seg.metadata_bundle.evidence_role) <= order.index(src.metadata_bundle.evidence_role)


def test_segment_cannot_be_constructed_naked() -> None:
    # The Segment type itself rejects a missing/non-segment bundle at runtime (not just via the
    # annotation), and is frozen so the bundle cannot be nulled after construction.
    with pytest.raises((TypeError, ValueError)):
        dri.Segment(metadata_bundle=None, source_artifact_id="art")  # type: ignore[arg-type]
    seg = dri.derive_segment(artifact_id="art-1")
    with pytest.raises(Exception):
        seg.metadata_bundle = None  # type: ignore[misc]  # frozen -> FrozenInstanceError


def test_segment_bundle_lineage_is_immutable() -> None:
    # The shared bundle is frozen and its lineage collections are tuples, so a holder cannot null or
    # clear lineage after construction (shallow-frozen would still allow derived_from.clear()).
    seg = dri.derive_segment(artifact_id="art-1")
    assert isinstance(seg.metadata_bundle.derived_from, tuple)
    assert isinstance(seg.metadata_bundle.provenance_event_ids, tuple)
    with pytest.raises(Exception):
        seg.metadata_bundle.object_type = "artifact"  # type: ignore[misc]  # frozen
    with pytest.raises(AttributeError):
        seg.metadata_bundle.derived_from.clear()  # type: ignore[attr-defined]  # tuple has no clear


def test_segment_requires_bundle() -> None:
    # No naked segment: a segment-type MetadataBundle cannot exist without derived_from, so a segment
    # cannot be constructed bundle-less. derive_segment is the production call site that guarantees it.
    with pytest.raises(ValueError):
        MetadataBundle(
            object_id="segment:naked",
            object_type="segment",
            scope_id="scope:work/project-alpha",
            source_role="work_project",
            authority_state="derived",
            evidence_role="reference",
            sensitivity="internal",
            suppression_state="visible",
            created_by="system:dri",
            created_at="2026-06-27T00:00:00+00:00",
            provenance_event_ids=["prov:1"],
            # derived_from intentionally omitted -> must raise
        )
