---
name: Define Context Dimension Payload Contract
description: Specify explicit runtime payload fields that separate scope, sphere, and situated identity.
task_id: SSI-01
source_anchor: docs/plans/V60_COGNITIVE_SUPPORT_PRIORITIES.md :: Priority 2b — Scope, sphere, and situated identity as distinct properties (v6.0 enabling)
parent_capability: Scope, sphere, and situated identity as distinct properties
prerequisites: []
depends_on: []
can_parallelize_with: [THREAD_SCOPE_SPHERE_IDENTITY_THROUGH_RUNTIME_PATHS, EXPOSE_CONTEXT_DIMENSIONS_IN_STATUS_AND_RECEIPTS]
---

# Define Context Dimension Payload Contract

## Purpose

Define one explicit payload contract that keeps scope, sphere, and situated identity distinct in runtime-facing context objects.

## What This Task Does

- Defines canonical field names and semantics for scope, sphere membership, and situated identity.
- Defines required/optional rules and nullability semantics.
- Defines backward-compatible mapping rules from existing context/domain surfaces.

## Concretely

- Add contract doc section and examples for payloads with separated dimensions.
- Provide one migration mapping example from legacy single-domain context to separated dimensions.
- Define invariant statements forbidding collapse of sphere/identity into scope.

## Why This Matters

Without an explicit payload contract, downstream implementation tasks will encode incompatible context shapes and reintroduce semantic collapse.

## Acceptance Criteria

- [ ] Canonical payload contract names and semantics are specified for scope, sphere, and situated identity.  
  Verify: doc writeback at `docs/SCOPE_SPHERE_SITUATED_IDENTITY/DEFINE_CONTEXT_DIMENSION_PAYLOAD_CONTRACT.md`.
- [ ] Nullability/optionality and backward-compatible mapping rules are specified.  
  Verify: doc writeback at `docs/SCOPE_SPHERE_SITUATED_IDENTITY/DEFINE_CONTEXT_DIMENSION_PAYLOAD_CONTRACT.md`.
- [ ] Invariants explicitly forbid collapsing these dimensions into one field.  
  Verify: doc writeback at `docs/SCOPE_SPHERE_SITUATED_IDENTITY/DEFINE_CONTEXT_DIMENSION_PAYLOAD_CONTRACT.md`.

## How to Verify (Pre-Merge)

- `rg -n "scope|sphere|situated identity|invariant|backward" docs/SCOPE_SPHERE_SITUATED_IDENTITY/DEFINE_CONTEXT_DIMENSION_PAYLOAD_CONTRACT.md`
- Reviewer confirms each AC has a concrete matching section in this doc.

## Out of Scope

- Runtime code changes.
- Database schema changes.

## Related Docs

- `docs/CONCEPTS/CONTEXT_MODEL_DECISION_FRAME.md`
- `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md`
- `docs/CONCEPTS/COGNITIVE_AXES_AND_SPHERES.md`

## Related GitHub Issues

- Parent: `docs/SCOPE_SPHERE_SITUATED_IDENTITY/PARENT_FEATURE_ISSUE.md`
- Follow-up implementation issue: to be created from this task spec.
