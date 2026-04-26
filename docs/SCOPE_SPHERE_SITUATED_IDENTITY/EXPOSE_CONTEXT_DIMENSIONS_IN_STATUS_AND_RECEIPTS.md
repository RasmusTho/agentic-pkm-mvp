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

---

## Status surface representation

The runtime status snapshot (`app.observability.status_service.get_system_status()`) must include a `context_dimensions` block when a context payload with separated dimensions is active. This block uses the canonical field names from the SSI-01 payload contract (`docs/SCOPE_SPHERE_SITUATED_IDENTITY/DEFINE_CONTEXT_DIMENSION_PAYLOAD_CONTRACT.md`).

### Status payload example

```json
{
  "sot_baseline_version": "v5.5",
  "sot_forward_line_version": "v6.0",
  "context_dimensions": {
    "scope": "work",
    "sphere_memberships": ["work", "learning"],
    "situated_identity": "senior-engineer"
  },
  "view_freshness": "fresh"
}
```

When no context payload with separated dimensions is active, the `context_dimensions` block is omitted entirely — it must not appear as a block of nulls, as that would create ambiguity between "no context" and "context with all-null fields."

### Required fields in status output

| Field | Required? | Allowed omissions |
|---|---|---|
| `context_dimensions.scope` | Required when `context_dimensions` block is present | May not be omitted if the block is present; use `"default"` if no explicit scope is declared |
| `context_dimensions.sphere_memberships` | Required when `context_dimensions` block is present | May be `[]` (empty array) to signal undeclared sphere memberships; must not be null |
| `context_dimensions.situated_identity` | Required key when `context_dimensions` block is present | May be `null` to signal no active role identity; null is a legal and explicit value |
| `context_dimensions` (the block itself) | Omit entirely when no separated-dimension context is active | Omitting the block is correct; a block of all-null values is not permitted |

---

## Receipt and event metadata representation

Runtime events (JSONL outbox, DB outbox) that carry a context payload must embed the separated dimensions as a nested `context_dimensions` object under the event envelope. The field names match the SSI-01 contract exactly.

### Receipt payload example

```json
{
  "event_id": "evt-7d3a9b12",
  "trace_id": "trc-00abc4",
  "timestamp": "2026-04-26T10:30:00Z",
  "version": "v6.0",
  "source": {
    "component": "watcher",
    "trigger": "registry:default-watcher",
    "sot": "v6.0"
  },
  "context_dimensions": {
    "scope": "writing",
    "sphere_memberships": ["creative-practice"],
    "situated_identity": null
  },
  "changed": 3,
  "ingested": 3,
  "panel_runs": 1
}
```

A `situated_identity` of `null` in the receipt is a valid and meaningful signal — it means no role identity was declared for this invocation, not that the field is missing or errored.

### Required fields in receipt output

| Field | Required? | Allowed omissions |
|---|---|---|
| `context_dimensions.scope` | Required when `context_dimensions` block is present | Non-null; use `"default"` if no scope was declared explicitly |
| `context_dimensions.sphere_memberships` | Required when `context_dimensions` block is present | Array; may be `[]`; must not be null |
| `context_dimensions.situated_identity` | Required key when `context_dimensions` block is present | May be `null` |
| `context_dimensions` (the block itself) | Omit entirely when the invocation had no separated-dimension context | Omitting is correct; do not emit an all-null block |

Events emitted by runtime paths that have not yet been threaded with separated-dimension context (pre-SSI-02 code paths) must omit the `context_dimensions` block entirely rather than emitting a placeholder.

---

## Guardrail notes for operator-visible identity semantics

The `situated_identity` field names an active role mode and may carry sensitive user-facing signals about how a person is showing up. Operators reading status or receipt surfaces must treat this field with care.

**Redaction posture:**
- `situated_identity` values must not be logged at debug verbosity without operator opt-in. At default log levels, treat the value as opaque and do not echo it in structured logs that may be forwarded to third-party aggregators.
- If an operator-facing API response is served over an unauthenticated surface and `situated_identity` must be redacted, use one of these two schema-preserving strategies — do **not** omit only the field while retaining the block, as that violates the required-fields contract and breaks schema validation for consumers:
  1. **Set `situated_identity: null`** (preferred). `null` already carries the explicit semantic of "no active identity declared" per the payload contract, so clients cannot distinguish redaction from a legitimately absent identity signal.
  2. **Omit the entire `context_dimensions` block** if all three dimensions are sensitive for the response context.
- `sphere_memberships` values may name personal life areas (e.g., `"health"`, `"private-life"`). Apply the same caution as for `situated_identity` in unauthenticated or externally-shared outputs.

**Interpretation rules for operators:**
- A `situated_identity` of `null` is a legal runtime state and must not be presented to operators as an error or anomaly. Present it as "no identity declared" in UI or CLI summaries.
- An empty `sphere_memberships` (`[]`) similarly means undeclared, not broken. Do not surface it as a warning.
- Never infer or backfill `situated_identity` from `scope` or `sphere_memberships` in status or receipt outputs. If the originating context had no identity signal, the receipt must reflect that absence faithfully.

**No PII in these fields:**
- These fields carry semantic role/context labels (e.g., `"senior-engineer"`, `"creative-practice"`), not personal identifiers. If an implementation ever produces values that look like personal identifiers (names, email addresses, user IDs), that is a violation of the contract and must be treated as a bug.

**Downstream use:**
- Status and receipt surfaces are read-only observability outputs. They must not be used to drive runtime behavior (e.g., access gating, retrieval filtering). Behavioral decisions must be driven by the upstream context payload, not by reading back from status or receipt fields.
