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

---

## Payload contract

This section defines the canonical field names and semantics for runtime-facing context objects. Full definitions of each concept live in `docs/CONCEPTS/CONTEXT_TERMINOLOGY_CONTRACT.md` and `docs/CONCEPTS/COGNITIVE_AXES_AND_SPHERES.md`; this contract names the payload shape without repeating those definitions.

### `scope`

**Canonical name:** `scope`  
**Semantics:** A single active operational partition used by the runtime for retrieval, action gating, path defaults, and similar decisions. Corresponds to `operational scope` in the terminology contract.  
**Required/optional:** Required in all runtime context objects.  
**Nullability:** Non-null. Must be a non-empty string. When no explicit scope has been declared, use a designated default value (e.g. `"default"`) rather than null.  
**Cardinality:** Single-valued. Runtime components may assume exactly one active operational scope per invocation (see `docs/CONCEPTS/CONTEXT_MODEL_DECISION_FRAME.md` §"Current posture").

### `sphere_memberships`

**Canonical name:** `sphere_memberships`  
**Semantics:** The declared sphere memberships relevant to this context. Spheres are overlapping regions of human life, concern, or practice (work, private life, learning, creative practice, etc.). Non-MECE; an artifact or concern may legitimately belong to several spheres. Corresponds to `sphere` in the terminology contract.  
**Required/optional:** Optional at the artifact level; present in context payloads when sphere filtering or context-sensitive behavior is required.  
**Nullability:** If present, must be an array (may be empty). Null is not a legal value; use `[]` when membership is unknown or undeclared.  
**Cardinality:** Multi-valued. Do not enforce one-sphere-per-context assumptions.

### `situated_identity`

**Canonical name:** `situated_identity`  
**Semantics:** The active role identity mode — the mode of self, responsibility, tone, and judgment that is active in the current situation. Corresponds to `situated role identity` in the terminology contract.  
**Required/optional:** Optional.  
**Nullability:** May be null when no role identity has been declared or can be inferred. Null means "no active identity signal available" — not "default identity".  
**Cardinality:** Single-valued when present. If the system later needs to express multiple co-active role identities, that is a future extension and must not be introduced by collapsing situated identity into sphere memberships.

---

## Backward-compatible mapping rules

These mapping rules translate from the legacy vocabulary used in pre-v6.0 code and docs. They are additive and must not break current behavior.

| Legacy term | Canonical field | Rule |
|---|---|---|
| `domain` | `scope` | Read `domain` as `scope` when the context is retrieval, action gating, path defaults, or runtime partition decisions. When `domain` carries broader human meaning (lived belonging, life area), reread it as `sphere_memberships` instead. Do not use `domain` as a new field name in context payloads. |
| `bridge` | (not a payload field) | `bridge` describes a cross-scope permission object (`explicit cross-scope allowance`), not a context dimension. Do not map it into `scope`, `sphere_memberships`, or `situated_identity`. Handle bridge/cross-scope allowances as a separate concern. |
| `context` (flat single value) | `scope` + `sphere_memberships` + `situated_identity` | Older code that passes a single `context` or `domain` string for all context purposes should be migrated by: (1) identifying which part is the operational partition → `scope`; (2) identifying any sphere-membership signals → `sphere_memberships`; (3) identifying any role identity signals → `situated_identity`. |

**Example migration — legacy single-domain to separated dimensions:**

Before (legacy):
```json
{ "domain": "work" }
```

After (separated):
```json
{
  "scope": "work",
  "sphere_memberships": ["work"],
  "situated_identity": null
}
```

When the legacy `domain` value carries only operational scope meaning:
```json
{ "domain": "writing" }
```
Becomes:
```json
{
  "scope": "writing",
  "sphere_memberships": [],
  "situated_identity": null
}
```
The empty `sphere_memberships` signals that no explicit sphere has been declared; this is a legal state.

---

## Invariants

The following invariants must hold across all runtime context objects. Violating them reintroduces semantic collapse.

1. **Do not collapse `sphere_memberships` into `scope`.** A single-valued operational scope cannot carry the information that an artifact or concern belongs to multiple overlapping spheres. If you find yourself combining sphere membership with scope into one field, the invariant is violated.

2. **Do not collapse `situated_identity` into `scope`.** Role identity describes how the human is oriented — not what operational partition is active. They may correlate, but they must not be unified into one field.

3. **Do not collapse `sphere_memberships` and `situated_identity` together.** Sphere membership is about where something belongs; role identity is about how the human is showing up. They use different semantics and must remain distinct fields.

4. **`scope` must remain single-valued per invocation.** Multiple active operational scopes in one context payload violates the one-active-scope assumption the runtime may rely on. If overlap is needed, it must go through `sphere_memberships` and explicit cross-scope allowance, not through a multi-valued `scope` field.

5. **Partial context is a legal state.** `sphere_memberships: []` and `situated_identity: null` are both legal and explicitly mean "not declared / not available" — not "broken" or "missing data". Runtime code must not treat null `situated_identity` as an error or fall back to filling it with a scope value.
