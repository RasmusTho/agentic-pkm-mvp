---
name: Validate Scope, Sphere, and Identity Separation
description: Specify cross-surface validation scenarios proving context dimensions stay distinct.
task_id: SSI-04
source_anchor: docs/plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md :: Priority 2b — Scope, sphere, and situated identity as distinct properties (v6.0 enabling)
parent_capability: Scope, sphere, and situated identity as distinct properties
prerequisites: [SSI-01, SSI-02, SSI-03]
depends_on: [DEFINE_CONTEXT_DIMENSION_PAYLOAD_CONTRACT.md, THREAD_SCOPE_SPHERE_IDENTITY_THROUGH_RUNTIME_PATHS.md, EXPOSE_CONTEXT_DIMENSIONS_IN_STATUS_AND_RECEIPTS.md]
can_parallelize_with: []
---

# Validate Scope, Sphere, and Identity Separation

## Purpose

Define validation scenarios and acceptance receipts that prove separated context dimensions remain distinct across implemented runtime surfaces.

## What This Task Does

- Defines scenario matrix that would catch dimension collapse.
- Defines expected outputs per scenario in status/receipt/runtime surfaces.
- Defines parent-issue acceptance evidence requirements.

## Concretely

- Add at least three scenario classes: scope-only change, sphere-only change, identity-only change.
- Add failure signatures indicating collapse into one field.
- Add receipt checklist for parent feature issue closure.

## Why This Matters

Capability acceptance requires proof of separation under realistic scenarios, not just contract text.

## Acceptance Criteria

- [ ] Validation scenarios cover independent variation of scope, sphere, and identity.  
  Verify: doc writeback at `docs/SCOPE_SPHERE_SITUATED_IDENTITY/VALIDATE_SCOPE_SPHERE_IDENTITY_SEPARATION.md`.
- [ ] Expected outputs and collapse failure signatures are specified.  
  Verify: doc writeback at `docs/SCOPE_SPHERE_SITUATED_IDENTITY/VALIDATE_SCOPE_SPHERE_IDENTITY_SEPARATION.md`.
- [ ] Parent feature acceptance receipt checklist is defined.  
  Verify: doc writeback at `docs/SCOPE_SPHERE_SITUATED_IDENTITY/VALIDATE_SCOPE_SPHERE_IDENTITY_SEPARATION.md`.

## How to Verify (Pre-Merge)

- `rg -n "scenario|scope-only|sphere-only|identity-only|failure signature|receipt checklist" docs/SCOPE_SPHERE_SITUATED_IDENTITY/VALIDATE_SCOPE_SPHERE_IDENTITY_SEPARATION.md`
- Reviewer confirms all scenario classes map to acceptance criteria.

## Out of Scope

- Running implementation validation itself.
- Closing the parent feature issue in this docs-only slice.

## Related Docs

- `docs/TESTING.md`
- `docs/plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md`
- `docs/SCOPE_SPHERE_SITUATED_IDENTITY/README.md`

## Related GitHub Issues

- Parent: `docs/SCOPE_SPHERE_SITUATED_IDENTITY/PARENT_FEATURE_ISSUE.md`
- Follow-up implementation issue: to be created from this task spec.
