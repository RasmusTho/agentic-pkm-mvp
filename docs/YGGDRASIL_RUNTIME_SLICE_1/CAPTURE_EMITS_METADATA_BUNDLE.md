---
name: Capture Emits MetadataBundle
description: Capture boundary produces an object carrying a schema-conformant MetadataBundle with stamped scope and source role
task_id: YRS1-02
source_anchor: docs/architecture/metadata-bundle.md :: required fields
parent_capability: Yggdrasil Runtime Vertical Slice 1
prerequisites: [YRS1-01]
depends_on: [RUNTIME_INVENTORY_AND_INTEGRATION_MAP.md]
can_parallelize_with: []
---

# Capture Emits MetadataBundle

## Purpose

Make capture the first stage that stamps a complete MetadataBundle, so every downstream runtime object
inherits identity, scope, the three orthogonal role dimensions, and provenance. This is the
foundation type for the whole slice.

## What This Task Does

- Adds `yggdrasil_runtime/metadata.py` with a `MetadataBundle` type conformant to
  `schemas/metadata-bundle.schema.json` (the single shared bundle type for tasks 2–6).
- Adds `yggdrasil_runtime/capture.py` with `capture(text: str, principal_id: str)` returning an object
  exposing `.metadata_bundle`.
- The emitted bundle carries `object_id`, `object_type="artifact"`, `scope_id`, `source_role`,
  `authority_state`, `evidence_role`, `sensitivity`, `suppression_state`, `created_by`, `created_at`,
  and a non-empty `provenance_event_ids`.
- `scope_id` is stamped from the active scope binding (WSP) — and is **not** equal to `vault_id`
  (vault is storage topology; scope is the cognitive/policy/provenance frame).

## Concretely

```python
from yggdrasil_runtime import capture
obj = capture.capture(text="a thought", principal_id="p-1")
assert obj.metadata_bundle.scope_id        # stamped, e.g. "scope:work/project-alpha"
assert obj.metadata_bundle.source_role     # e.g. "human_capture"
# vault_id (if present) is a distinct field, never equal to scope_id
```

`capture.capture(...)` makes `tests/invariants/test_metadata_bundle.py::test_capture_stamps_scope`
import successfully and its assertions pass.

## Why This Matters

Without a stamped bundle at capture, every later object is a "naked" object: scope, authority, and
provenance cannot be enforced anywhere downstream (`metadata_bundle.md :: §0`). Collapsing
`scope_id` into `vault_id` would let storage topology silently define policy frame — the exact error
the architecture forbids.

## Acceptance Criteria

- [ ] `yggdrasil_runtime.metadata.MetadataBundle` exists and a constructed bundle validates against
  `schemas/metadata-bundle.schema.json` (required core set + three separate role fields).
  - Verify: `tests/invariants/test_metadata_bundle_runtime.py::test_capture_bundle_validates_against_schema`
- [ ] `yggdrasil_runtime.capture.capture(text, principal_id)` returns an object whose
  `.metadata_bundle` has truthy `scope_id` and `source_role`.
  - Verify: `tests/invariants/test_metadata_bundle.py::test_capture_stamps_scope` (xfail → passing)
- [ ] `scope_id` and `vault_id` are not treated as equivalent.
  - Verify: `tests/invariants/test_metadata_bundle_runtime.py::test_capture_scope_id_is_not_vault_id`
- [ ] `metadata_bundle_required` and `store_no_naked_vectors` stay green.
  - Verify: `pytest -q tests/invariants/test_metadata_bundle.py`

## How to Verify (Pre-Merge)

- Local: `pytest -q tests/invariants/test_metadata_bundle.py` — `test_capture_stamps_scope` now
  passes; the two static tests stay green.
- Local: the new `test_metadata_bundle_runtime.py` validates the runtime bundle against the JSON
  schema with `jsonschema`.

## Out of Scope

- Persistence to any real store (in-memory only). No WriteGuard, no durable mutation.
- DRI derivation, retrieval, envelope assembly.

## Restart / Durability Posture

Captured objects live in-memory for the slice; nothing survives a process restart. This surface is
not user-facing (it is exercised by tests over the fixture corpus), so there is no end-user trust
consequence — but the spec is explicit that capture here does **not** persist durably.

## Related Docs

- `docs/architecture/metadata-bundle.md`, `docs/architecture/semantic-dimensions.md`
- `schemas/metadata-bundle.schema.json`, `schemas/_defs.schema.json`
- Boundaries: WSP, SIP, HKA, PDM

## Related GitHub Issues

One issue, `agent:ready` once YRS1-01 merges. Defines the shared bundle type — review the type
carefully; later tasks import it.
