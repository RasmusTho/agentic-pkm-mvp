---
name: Enforce Owned Effect Boundaries
description: Enforce that durable and external effects cross named owner ports while pure internal functions avoid generic wrappers.
task_id: DSP-04
github_issue:
source_anchor: "docs/DESIGN_PRINCIPLES.md :: Change Classification Rules"
parent_capability: Whole-System Design Principle Routing
prerequisites: [DSP-01]
depends_on: [ESTABLISH_PRINCIPLE_KERNEL.md]
can_parallelize_with: []
---

# Enforce Owned Effect Boundaries

## Purpose

Make effect ownership reviewable at architecture boundaries without turning every function into an
interface or creating a universal port framework.

## What This Task Does

Extend the existing fitness registry and targeted architecture tests with an explicit effect
classification: authority-bearing durable, mechanical durable, derived/rebuildable, external, or
none. Effectful capabilities name their owner contract and port; pure internal functions are exempt
unless a real substitution, policy, or lifecycle boundary exists.

## Concretely

Focused fixtures include one compliant StorePort write, one compliant egress boundary, one hidden
direct effect that must fail, and one pure computation that must not be required to add a wrapper.

## Why This Matters

Hidden effects blur authority; indiscriminate wrappers add indirection without adding safety.

## Acceptance Criteria

- [ ] New durable or external capability declarations name effect class, owner contract, and port,
  and targeted violations fail at the existing fitness boundary.
  - Verify: `tests/architecture/test_owned_effect_boundaries.py::test_durable_and_external_effects_require_named_owner_ports`
- [ ] Pure internal computation is not rejected for lacking a port when no durable, external,
  policy, substitution, or lifecycle boundary exists.
  - Verify: `tests/architecture/test_owned_effect_boundaries.py::test_pure_internal_functions_do_not_require_generic_wrappers`
- [ ] Enforcement is registered in the existing invariant/fitness owners with an honest blocking or
  advisory posture.
  - Verify: doc writeback at `docs/architecture/SBS_FITNESS_RULES.md :: Seed Rules`

## How To Verify Pre-Merge

- `pytest -q tests/architecture/test_owned_effect_boundaries.py`
- `pytest -q tests/architecture`

## Out Of Scope

- Retrofitting every historical module, creating a universal port base class, or changing an owner
  contract solely to satisfy naming uniformity.

## Related Docs

- `docs/contracts/STORE_PORT.md`
- `docs/architecture/SBS_OPERATING_MODEL.md`
- `docs/testing/invariant-tests.md`

## Related GitHub Issues

Issue #3553 retains Governed Knowledge Effect Spine authority.
