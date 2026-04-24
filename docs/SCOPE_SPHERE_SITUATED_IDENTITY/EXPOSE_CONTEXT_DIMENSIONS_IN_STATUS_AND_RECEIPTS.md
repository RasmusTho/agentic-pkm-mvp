---
name: Expose Context Dimensions in Status and Receipts
description: Specify operator-visible reporting for separated scope/sphere/identity context dimensions.
task_id: SSI-03
source_anchor: docs/plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md :: Priority 2b — Scope, sphere, and situated identity as distinct properties (v6.0 enabling)
parent_capability: Scope, sphere, and situated identity as distinct properties
prerequisites: [SSI-01]
depends_on: [DEFINE_CONTEXT_DIMENSION_PAYLOAD_CONTRACT.md]
can_parallelize_with: [THREAD_SCOPE_SPHERE_IDENTITY_THROUGH_RUNTIME_PATHS]
---

# Expose Context Dimensions in Status and Receipts

## Purpose

Define how separated context dimensions become operator-visible in receipts/status surfaces without mutating user artifacts.

## What This Task Does

- Specifies status surface fields for context-dimension visibility.
- Specifies receipt/event metadata representation for scope/sphere/identity.
- Defines redaction/safety posture for operator-facing outputs.

## Concretely

- Add one status payload example and one receipt payload example.
- Define required reporting fields and allowed omissions.
- Define privacy/guardrail notes for identity-related outputs.

## Why This Matters

If context dimensions are not visible in operator surfaces, drift cannot be detected and downstream priorities lose auditability.

## Acceptance Criteria

- [ ] Status/receipt representation of scope/sphere/identity is explicitly specified.  
  Verify: doc writeback at `docs/SCOPE_SPHERE_SITUATED_IDENTITY/EXPOSE_CONTEXT_DIMENSIONS_IN_STATUS_AND_RECEIPTS.md`.
- [ ] Required fields and allowed omissions are defined.  
  Verify: doc writeback at `docs/SCOPE_SPHERE_SITUATED_IDENTITY/EXPOSE_CONTEXT_DIMENSIONS_IN_STATUS_AND_RECEIPTS.md`.
- [ ] Guardrail notes for operator-visible identity semantics are documented.  
  Verify: doc writeback at `docs/SCOPE_SPHERE_SITUATED_IDENTITY/EXPOSE_CONTEXT_DIMENSIONS_IN_STATUS_AND_RECEIPTS.md`.

## How to Verify (Pre-Merge)

- `rg -n "status|receipt|required|omission|guardrail|identity" docs/SCOPE_SPHERE_SITUATED_IDENTITY/EXPOSE_CONTEXT_DIMENSIONS_IN_STATUS_AND_RECEIPTS.md`
- Reviewer confirms examples match SSI-01 contract semantics.

## Out of Scope

- Building UI/UX surfaces.
- Runtime telemetry implementation.

## Related Docs

- `docs/OBSERVABILITY.md`
- `docs/OPERATIONS.md`
- `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md`

## Related GitHub Issues

- Parent: `docs/SCOPE_SPHERE_SITUATED_IDENTITY/PARENT_FEATURE_ISSUE.md`
- Follow-up implementation issue: to be created from this task spec.
