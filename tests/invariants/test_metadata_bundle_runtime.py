"""Runtime conformance tests for the capture stage (#2580 / YRS1-02).

These complement the auto-converting skeleton ``test_metadata_bundle.py::test_capture_stamps_scope``
by validating the *runtime-built* bundle against the JSON schema and pinning the scope!=vault rule.

Invariant registry: docs/testing/invariant-tests.md :: metadata_bundle_required, store_no_naked_vectors
Contract: docs/architecture/metadata-bundle.md (#2544). Spec: docs/YGGDRASIL_RUNTIME_SLICE_1/CAPTURE_EMITS_METADATA_BUNDLE.md
"""

from __future__ import annotations

import pytest

from tests.invariants._helpers import assert_validates

from yggdrasil_runtime import capture
from yggdrasil_runtime.metadata import MetadataBundle


def test_capture_bundle_validates_against_schema() -> None:
    # The runtime bundle emitted at capture must satisfy schemas/metadata-bundle.schema.json
    # (required core set + the three separate role fields), not merely expose truthy attributes.
    obj = capture.capture(text="a thought", principal_id="p-1")
    assert_validates(obj.metadata_bundle.to_dict(), "metadata-bundle.schema.json")


def test_capture_stamps_required_dimensions() -> None:
    # capture stamps identity, scope, and the three orthogonal role dimensions at capture time.
    bundle = capture.capture(text="another thought", principal_id="p-2").metadata_bundle
    assert bundle.object_id
    assert bundle.object_type == "artifact"
    assert bundle.scope_id
    assert bundle.source_role  # origin
    assert bundle.authority_state  # standing
    assert bundle.evidence_role  # reasoning-use
    assert bundle.provenance_event_ids  # >= 1 provenance event (no naked object)


def test_capture_scope_id_is_not_vault_id() -> None:
    # scope_id (cognitive/policy/provenance frame) must never be collapsed into vault_id (storage).
    bundle = capture.capture(text="a third thought", principal_id="p-3").metadata_bundle
    assert bundle.vault_id, "capture should record a vault_id distinct from scope_id"
    assert bundle.scope_id != bundle.vault_id


def test_capture_registers_artifact_for_derivation() -> None:
    # The captured artifact is retrievable from the in-memory store so DRI (#2581) can inherit it.
    obj = capture.capture(text="store me", principal_id="p-4")
    fetched = capture.get_captured(obj.metadata_bundle.object_id)
    assert fetched is not None
    assert fetched.metadata_bundle.scope_id == obj.metadata_bundle.scope_id


def _accepted_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = dict(
        object_id="artifact:acc-1",
        object_type="artifact",
        scope_id="scope:work/project-alpha",
        source_role="work_project",
        authority_state="accepted",
        evidence_role="evidence",
        sensitivity="internal",
        suppression_state="visible",
        created_by="p-1",
        created_at="2026-06-27T00:00:00+00:00",
        provenance_event_ids=["prov:1"],
        vault_id="vault:local",
    )
    base.update(overrides)
    return base


def test_accepted_bundle_requires_receipt() -> None:
    # Canonical standing (accepted/canonical) comes only from a governed AuthorityTransition; the
    # shared type fails loud at construction rather than emitting a schema-invalid payload downstream.
    with pytest.raises(ValueError):
        MetadataBundle(**_accepted_kwargs())  # type: ignore[arg-type]


def test_accepted_bundle_with_receipt_validates() -> None:
    bundle = MetadataBundle(**_accepted_kwargs(authority_receipt_ref="receipt:abc"))  # type: ignore[arg-type]
    assert_validates(bundle.to_dict(), "metadata-bundle.schema.json")


def test_lineage_str_is_rejected_not_split() -> None:
    # A single str for a lineage field must fail loud, not be split into characters by tuple().
    with pytest.raises(TypeError):
        MetadataBundle(**_accepted_kwargs(authority_receipt_ref="r:1", provenance_event_ids="prov:1"))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        MetadataBundle(
            **_accepted_kwargs(
                object_type="segment", authority_state="derived", derived_from="art-1",
            )  # type: ignore[arg-type]
        )


def test_evidence_projection_requires_receipt() -> None:
    # Projection is not evidence by default; an evidence projection needs a promotion receipt even
    # when authority_state is non-canonical (e.g. derived) — fail loud at construction.
    with pytest.raises(ValueError):
        MetadataBundle(
            **_accepted_kwargs(
                object_type="projection",
                authority_state="derived",
                evidence_role="evidence",
                derived_from=["artifact:src"],
            )  # type: ignore[arg-type]
        )
