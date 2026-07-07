---
name: Thread episode_ref into Metadata Bundle
description: Add episode_ref to the metadata-bundle schema + derivation-survival rule; create the invariant probe and flip observation_episode_binding_survives off future_runtime
task_id: ERE-03
source_anchor: docs/architecture/semantic-dimensions.md :: episode_ref
parent_capability: Episode Resolution Engine
prerequisites: []
depends_on: []
can_parallelize_with: [Stream Registry and Signal Contract, Episode Note Store and Projection]
---

# Thread episode_ref into Metadata Bundle

## Purpose

`episode_ref` exists in the semantic-dimensions doctrine (SIP-owned; values `unbound | pending | episode_id[]`; must survive derivation) but **not** in the metadata-bundle schema — the schema is closed (`additionalProperties: false`), so no artifact can carry the dimension today. The invariant `observation_episode_binding_survives` sits at `future_runtime` with a named-but-nonexistent test file. This task closes both gaps.

## What This Task Does

1. **Schema**: adds `episode_ref` to `schemas/metadata-bundle.schema.json` in the location/context family (structurally parallel to `scope_binding`): either the string `"unbound"`, the string `"pending"`, or a non-empty array of `episode_id` strings. Added to `required` (every bundle carries it; `"unbound"` is the honest default — mirrors how scope is always stamped).
2. **Derivation survival**: an `allOf` conditional mirroring the existing derived-types rule (`object_type ∈ [segment, projection, retrieval_result, context_item]` requires `derived_from`, schema lines 106–123): derived types must also carry `episode_ref`, and the runtime derivation paths must propagate the parent's binding (correctable, per ADR-0051 — propagated, not frozen).
3. **Prose mirror**: extends `docs/architecture/metadata-bundle.md` §field families with `episode_ref` (owner SIP; orthogonal to `evidence_role` — never an admissibility upgrade; `pending` is not authority).
4. **Invariant flip**: creates `tests/invariants/test_episode_binding.py::test_observation_episode_binding_survives` (house convention: probe function name = registry invariant id) modeled on `test_metadata_bundle.py::test_provenance_survives_derivation`, and updates the registry entry (`docs/testing/invariant-tests.md` lines 774–791 + coverage row 875) from `future_runtime` → `schema_enforced` + `runtime_test`.
5. **Default stamping**: capture/ingest paths that mint bundles stamp `episode_ref: unbound` (extends the `capture_stamps_scope` posture — the field is always present, assignment upgrades it later in ERE-05).

## Concretely

```
$ pytest -q tests/invariants/test_episode_binding.py
1 passed
# a derived segment whose parent had episode_ref [ep-x] but which drops it → schema/test failure
```

## Why This Matters

Without the schema field there is nothing for assignment (ERE-05) to write to; without the derivation rule, bindings silently vanish at the first chunk/projection and closure-driven decay (ERE-06) can never reach derived retrieval items — the exact failure the invariant exists to prevent.

## Acceptance Criteria

- [ ] AC1: bundle schema accepts `unbound`, `pending`, and `["ep-..."]`; rejects a bundle with no `episode_ref` and rejects an empty array. Verify: `tests/invariants/test_episode_binding.py::test_episode_ref_schema_shapes`
- [ ] AC2 (enforcement): `episode_ref` survives segment/projection/retrieval derivation on the production derivation path (call-site assertion, modeled on `test_provenance_survives_derivation`), not merely in schema validation. Verify: `tests/invariants/test_episode_binding.py::test_observation_episode_binding_survives`
- [ ] AC3: bundle-minting capture/ingest paths stamp `episode_ref: unbound` by default (production call site). Verify: `tests/invariants/test_episode_binding.py::test_capture_stamps_episode_ref_unbound`
- [ ] AC4: `episode_ref` never feeds `evidence_role` — the existing no-upgrade probe extended to assert an `episode_ref`-bearing item cannot gain admissibility from its binding. Verify: `tests/invariants/test_episode_binding.py::test_episode_ref_never_upgrades_evidence_role`
- [ ] AC5: invariant registry updated (enforcement class + test path now real; coverage-map row updated). Verify: doc writeback at `docs/testing/invariant-tests.md :: observation_episode_binding_survives`
- [ ] AC6: prose mirror updated. Verify: doc writeback at `docs/architecture/metadata-bundle.md :: What it carries (field families)`

## How to Verify (Pre-Merge)

```
ruff check app tests && mypy app
pytest -q tests/invariants/test_episode_binding.py tests/invariants/test_metadata_bundle.py
pytest -q -m "not pg"
```

Bundle schema is hot-path shared state — per house rule this child runs the FULL `not pg` suite before PR, not targeted tests only.

## Out of Scope

Setting `episode_ref` to real episode ids (ERE-05 assignment); the Episode note itself (ERE-02); retrieval consumption of the binding (ERE-06).

## Related Docs

- `docs/architecture/semantic-dimensions.md` §episode_ref (lines 119–133) — the doctrine this implements
- `schemas/metadata-bundle.schema.json` (closed schema + derived-types conditional precedent)
- `docs/testing/invariant-tests.md` §observation_episode_binding_survives
- [ADR-0051](../adr/ADR-0051-episode-as-ontological-primitive.md) §4, [ADR-0029] orthogonal roles

## Related GitHub Issues

One issue: `[Episode Resolution Engine] episode-ref-threading: bundle schema field + derivation-survival invariant`. Ready immediately.
