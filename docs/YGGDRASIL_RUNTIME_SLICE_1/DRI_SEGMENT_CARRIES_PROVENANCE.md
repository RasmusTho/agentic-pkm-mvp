---
name: DRI Segment Carries Provenance
description: Derived segments carry an inherited MetadataBundle with derived_from, scope, and provenance — no naked representation
task_id: YRS1-03
source_anchor: docs/architecture/functional-ontology.md :: Segment
parent_capability: Yggdrasil Runtime Vertical Slice 1
prerequisites: [YRS1-02]
depends_on: [CAPTURE_EMITS_METADATA_BUNDLE.md]
can_parallelize_with: []
---

# DRI Segment Carries Provenance

## Purpose

Ensure the derived-representation stage (DRI) cannot produce a naked segment/chunk: every derived
object inherits a MetadataBundle and preserves lineage back to its source artifact.

## What This Task Does

- Adds `yggdrasil_runtime/dri.py` with `derive_segment(artifact_id: str)` returning a segment whose
  `.metadata_bundle` carries `object_type="segment"`, a non-empty `derived_from`, an inherited
  `scope_id`, inherited `source_role`/`authority_state`, and non-empty `provenance_event_ids`.
- Constructing a segment without a MetadataBundle is impossible by construction (the type requires it)
  — the runtime expression of "no naked vectors/chunks".

## Concretely

```python
from yggdrasil_runtime import dri
seg = dri.derive_segment(artifact_id="art-1")
assert seg.metadata_bundle.derived_from          # e.g. ["art-1"]
assert seg.metadata_bundle.scope_id              # inherited from the source artifact
assert seg.metadata_bundle.provenance_event_ids  # non-empty
```

This makes `tests/invariants/test_metadata_bundle.py::test_provenance_survives_derivation` pass.

## Why This Matters

A segment that drops `derived_from`, `scope_id`, or provenance becomes evidence with no traceable
origin — provenance must survive derivation (`metadata-bundle.md` rule 3; matrix #3/#16). A naked
chunk is the classic failure: a vector with no scope/authority/provenance that similarity search can
then treat as permission.

## Acceptance Criteria

- [ ] `yggdrasil_runtime.dri.derive_segment(artifact_id)` returns a segment whose bundle has truthy
  `derived_from`, `scope_id`, and `provenance_event_ids`.
  - Verify: `tests/invariants/test_metadata_bundle.py::test_provenance_survives_derivation` (xfail → passing)
- [ ] A derived segment's `scope_id`/`source_role` are inherited from the source artifact, not
  re-stamped fresh.
  - Verify: `tests/invariants/test_dri_runtime.py::test_segment_inherits_source_scope_and_role`
- [ ] A segment cannot be constructed without a MetadataBundle (enforcement: the segment factory is
  the production call site).
  - Verify: `tests/invariants/test_dri_runtime.py::test_segment_requires_bundle` asserts
    `derive_segment` is the call site that rejects a bundle-less segment.
- [ ] `store_no_naked_vectors` stays green.
  - Verify: `pytest -q tests/invariants/test_metadata_bundle.py`

## How to Verify (Pre-Merge)

- Local: `pytest -q tests/invariants/test_metadata_bundle.py tests/invariants/test_dri_runtime.py`.
- Confirm the segment bundle validates against `schemas/metadata-bundle.schema.json` for
  `object_type="segment"` (which requires `derived_from`).

## Out of Scope

- Embeddings/vector construction sophistication. A trivial chunk/segment representation is enough.
- Projection objects and `projection_not_evidence` (left xfail).
- Persistence of segments to a real index.

## Restart / Durability Posture

Segments are in-memory and rebuildable from their artifact; nothing persists across restart. Derived
representations are never source of truth (boundaries/README invariant), so non-durability is correct
by design.

## Related Docs

- `docs/architecture/functional-ontology.md` (Segment row), `docs/architecture/metadata-bundle.md`
- Boundaries: DRI (pending charter, referenced under epic #2533), SIP, PDM

## Related GitHub Issues

One issue, `agent:ready` once YRS1-02 merges.
