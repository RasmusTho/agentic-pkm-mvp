---
name: Establish the Principle Kernel
description: Give existing whole-system principles stable identities and exact routing metadata without creating a second authority.
task_id: DSP-01
github_issue:
source_anchor: "docs/DESIGN_PRINCIPLES.md :: System Design Principles"
parent_capability: Whole-System Design Principle Routing
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Establish the Principle Kernel

## Purpose

Make the existing canonical principles addressable by deterministic routing and tests while keeping
their prose and ownership in current owner documents.

## What This Task Does

Assign stable principle IDs and compact selection metadata for applicability, owner, required
reading, and enforcement posture. Align the product-kernel and modular-architecture projections by
pointer instead of copying the full principle text. Register the mapping in the existing invariant
and fitness owners.

## Concretely

`tests/architecture/test_design_principle_routing.py` parses the canonical kernel and proves every
ID is unique, points to a resolvable owner section, and has one declared enforcement posture.

## Why This Matters

Without stable identities, agents either load broad documents or silently choose rules from prose;
both make design behavior hard to verify and easy to drift.

## Acceptance Criteria

- [ ] Canonical principles have stable unique IDs plus applicability, owner, required-read, and
  enforcement metadata without changing current runtime claims.
  - Verify: `tests/architecture/test_design_principle_routing.py::test_canonical_principles_have_unique_resolvable_routing_metadata`
- [ ] `PROJECT_KERNEL.md` and `MODULAR_ARCHITECTURE.md` point to the canonical IDs and contain no
  competing full-text principle registry.
  - Verify: `tests/architecture/test_design_principle_routing.py::test_principle_projections_reference_canonical_ids_without_redefining_them`
- [ ] The existing invariant and fitness documents name the kernel and distinguish blocking,
  advisory, and manual-review posture.
  - Verify: doc writeback at `docs/testing/invariant-tests.md :: Design principle routing`

## How To Verify Pre-Merge

- `pytest -q tests/architecture/test_design_principle_routing.py`
- `git diff --check`

## Out Of Scope

- A packet resolver, Builder instruction routing, runtime behavior, new SBS subsystems, or generic
  wrappers around internal functions.

## Related Docs

- `docs/WHOLE_SYSTEM_DESIGN_PRINCIPLES/README.md`
- `docs/DESIGN_PRINCIPLES.md`
- `docs/PROJECT_KERNEL.md`
- `docs/MODULAR_ARCHITECTURE.md`

## Related GitHub Issues

Shared parent epic: pending filing.
