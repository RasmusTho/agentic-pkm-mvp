---
name: Runtime Inventory and Integration Map
description: Inspect existing capture/index/retrieval/context code and produce the yggdrasil_runtime integration map
task_id: YRS1-01
source_anchor: docs/YGGDRASIL_RUNTIME_SLICE_1/README.md :: Foundational design decision
parent_capability: Yggdrasil Runtime Vertical Slice 1
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Runtime Inventory and Integration Map

## Purpose

Before any runtime code is written, produce the authoritative map of what exists and exactly which
modules the new `yggdrasil_runtime` package will introduce, reuse, or deliberately leave untouched.
This task changes no behavior; it removes ambiguity for tasks 2–8.

## What This Task Does

- Inventories the legacy `app/` capture/index/retrieval/context code (the real entry points,
  data shapes, and where naked vectors / unbounded context exist today).
- Confirms the `yggdrasil_runtime` package does not yet exist and pins its planned module layout to
  the exact entry points the xfail skeletons call (`tests/invariants/_helpers.py`,
  `tests/evals/_helpers.py`).
- Decides, per module, build-new vs reuse-from-`app/` (e.g. an embedding/similarity helper), and
  records the corpus-as-runtime-store decision (`tests/evals/fixtures/`).
- Lists which xfail tests each later task will convert, and which static invariants must stay green.

## Concretely

Produce `docs/YGGDRASIL_RUNTIME_SLICE_1/INTEGRATION_MAP.md` containing:

- A table: each `yggdrasil_runtime` module → its test-pinned entry point → reuse/new decision →
  `app/` references (if any).
- The corpus loader plan: how `retrieve()` reads the five fixture groups and their frontmatter
  metadata (reuse `tests/evals/_helpers.py::load_corpus` semantics or a runtime equivalent).
- A short "naked-vector / unbounded-context gap" note for the legacy `app/` pipeline, marked
  explicitly out of scope for this slice.

Expected: a reviewer can read INTEGRATION_MAP.md and implement tasks 2–6 without re-deriving the
package shape.

## Why This Matters

If the package layout or the corpus-store decision drifts between tasks, the shared MetadataBundle
type and the prefilter-before-ranking invariant fracture across PRs (see README Cross-Task
Invariants). The map is the contract that keeps four+ child PRs coherent.

## Acceptance Criteria

- [ ] `docs/YGGDRASIL_RUNTIME_SLICE_1/INTEGRATION_MAP.md` exists with the module→entry-point→decision
  table covering `capture`, `dri`, `retrieval`, `cross_scope`, `context`, `metadata`.
  - Verify: doc writeback at `docs/YGGDRASIL_RUNTIME_SLICE_1/INTEGRATION_MAP.md :: Module map`
- [ ] The map names, for each later task, the exact xfail test(s) it converts and the static tests it
  must keep green (cross-checked against `docs/testing/invariant-tests.md`).
  - Verify: doc writeback at `docs/YGGDRASIL_RUNTIME_SLICE_1/INTEGRATION_MAP.md :: Test conversion plan`
- [ ] The corpus-as-runtime-store decision and the "legacy `app/` pipeline untouched" boundary are
  stated explicitly.
  - Verify: doc writeback at `docs/YGGDRASIL_RUNTIME_SLICE_1/INTEGRATION_MAP.md :: Runtime store`

## How to Verify (Pre-Merge)

- Local: `pytest -q tests/invariants tests/evals` is unchanged (still the same xfail set) — this task
  adds no code.
- Review: the INTEGRATION_MAP entry points match `tests/invariants/_helpers.py` and
  `tests/evals/_helpers.py` verbatim (module suffix strings and called attributes).

## Out of Scope

- Any runtime code or test change. No behavior change.
- Rewiring or refactoring the legacy `app/` pipeline.

## Related Docs

- Parent: `docs/YGGDRASIL_RUNTIME_SLICE_1/README.md`
- `tests/invariants/_helpers.py`, `tests/evals/_helpers.py`
- `docs/testing/invariant-tests.md`

## Related GitHub Issues

One issue, `agent:ready`. This is the first pickup; it unblocks all others. No PR-side runtime risk.
