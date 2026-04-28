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

---

## Scenario Matrix

Each scenario class independently varies one context dimension while holding the others fixed. Pass = each field in runtime payloads, status, and receipts is populated from the right source and the other two dimensions are unaffected.

### Scenario Class 1: scope-only change

**Setup:** Runtime receives two sequential requests. Between them, only `scope` changes (e.g. `"work"` → `"writing"`). `sphere_memberships` and `situated_identity` are identical in both.

**Expected outputs:**

| Surface | Field | Expected value (request 1) | Expected value (request 2) |
|---|---|---|---|
| Runtime payload | `scope` | `"work"` | `"writing"` |
| Runtime payload | `sphere_memberships` | `["work"]` | `["work"]` |
| Runtime payload | `situated_identity` | `"professional"` | `"professional"` |
| Status surface | `context.scope` | `"work"` | `"writing"` |
| Receipt metadata | `scope` | `"work"` | `"writing"` |

**Failure signatures — dimension collapse:**
- `sphere_memberships` changes when only `scope` changed → scope-to-sphere collapse.
- `situated_identity` changes when only `scope` changed → scope-to-identity collapse.
- Status or receipt omits `scope` or conflates it with `sphere_memberships` → reporting collapse.

---

### Scenario Class 2: sphere-only change

**Setup:** Runtime receives two sequential requests. Between them, only `sphere_memberships` changes (e.g. `["work"]` → `["work", "learning"]`). `scope` and `situated_identity` are identical in both.

**Expected outputs:**

| Surface | Field | Expected value (request 1) | Expected value (request 2) |
|---|---|---|---|
| Runtime payload | `scope` | `"work"` | `"work"` |
| Runtime payload | `sphere_memberships` | `["work"]` | `["work", "learning"]` |
| Runtime payload | `situated_identity` | `"professional"` | `"professional"` |
| Status surface | `context.sphere_memberships` | `["work"]` | `["work", "learning"]` |
| Receipt metadata | `sphere_memberships` | `["work"]` | `["work", "learning"]` |

**Failure signatures — dimension collapse:**
- `scope` changes when only `sphere_memberships` changed → sphere-to-scope collapse.
- `situated_identity` changes when only `sphere_memberships` changed → sphere-to-identity collapse.
- Receipt uses a single `domain` field that merges scope + sphere → legacy collapse (invariant violation, see SSI-01).

---

### Scenario Class 3: identity-only change

**Setup:** Runtime receives two sequential requests. Between them, only `situated_identity` changes (e.g. `"professional"` → `null`). `scope` and `sphere_memberships` are identical in both.

**Expected outputs:**

| Surface | Field | Expected value (request 1) | Expected value (request 2) |
|---|---|---|---|
| Runtime payload | `scope` | `"work"` | `"work"` |
| Runtime payload | `sphere_memberships` | `["work"]` | `["work"]` |
| Runtime payload | `situated_identity` | `"professional"` | `null` |
| Status surface | `context.situated_identity` | `"professional"` | `null` (not omitted — must be present as null) |
| Receipt metadata | `situated_identity` | `"professional"` | `null` |

**Failure signatures — dimension collapse:**
- `scope` changes when only `situated_identity` changed → identity-to-scope collapse.
- `sphere_memberships` changes when only `situated_identity` changed → identity-to-sphere collapse.
- `situated_identity: null` causes runtime to fill a scope value into identity field → null-to-scope fallback (SSI-01 invariant 5 violation).
- Status surface omits `situated_identity` when it is null instead of reporting it explicitly → silent collapse.

---

## Collapse Failure Signatures (Summary)

The following signatures indicate that at least one invariant from SSI-01 has been violated:

| Signature | Violated invariant |
|---|---|
| One field change causes another to change unexpectedly | Dimensions are entangled in code or schema |
| `domain` or `context` single-key appears in payloads instead of three distinct keys | Legacy collapse not yet migrated |
| `situated_identity: null` is replaced by a scope value | Null-to-scope fallback (forbidden by SSI-01 §Invariant 5) |
| Status surface omits any of the three fields when they are `null` or `[]` | Reporting collapse — must report explicit null/empty |
| Receipt uses `sphere_memberships` with a single-value assumption | Multi-valued sphere semantics not yet implemented |
| `scope` is multi-valued in any payload | Single-scope-per-invocation invariant violated (SSI-01 §Invariant 4) |

---

## Parent Feature Acceptance Receipt Checklist

Use this checklist to verify that parent feature issue #645 is ready for closure. Each item must be confirmed by the reviewer/human, not asserted by the implementing agent.

- [ ] SSI-01 merged and verified: payload contract doc contains canonical field names, mapping rules, and invariants.
- [ ] SSI-02 merged and verified: thread-through doc specifies how each runtime path receives and propagates the three dimensions.
- [ ] SSI-03 merged and verified: status/receipt doc specifies operator-visible representation, required fields, and guardrail notes.
- [ ] SSI-04 merged and verified (this doc): scenario matrix covers all three scenario classes, expected outputs are specified, and collapse failure signatures are enumerated.
- [ ] Cross-surface validation scenario results recorded: for each of the three scenario classes, a reviewer or CI run has confirmed that expected outputs match actual outputs in staging/test.
- [ ] No open `agent:blocked` or `agent:needs-human` labels remain on any SSI child issue.
- [ ] Owner-doc promotion language reviewed: no roadmap/plan docs still read SSI capability as pending after the above is complete.
- [ ] Human reviewer has signed off on parent issue #645 closure (closure is not agent-unilateral).
