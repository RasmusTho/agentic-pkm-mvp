---
name: Define Provisional Memory Record
description: Add the typed provisional-memory shape and receipt-bearing lifecycle without creating a producer or reader.
task_id: PROVISIONAL-MEMORY-01
source_anchor: docs/adr/ADR-0025-memory-authority-direct-write-policy.md :: Decision
parent_capability: Provisional Memory
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# DEFINE_PROVISIONAL_MEMORY_RECORD

## Purpose

Define the one typed record and lifecycle vocabulary that later producer and reader paths share,
without allowing record existence to imply authority or admission.

## What This Task Does

- Adds a provisional-memory record compatible with the canonical `MemoryItem` role constraints:
  `source_role=agent_memory`, `authority_state=noncanonical`, non-evidence role, explicit scope,
  provenance, review state, and lifecycle receipt references.
- Extends the existing review-decision/receipt storage rather than creating a second lifecycle
  ledger.
- Defines reconciliation states for incomplete artifact/receipt pairs.

## Concretely

The implementation can represent a direct-write candidate before any API or recall consumer exists.
Validation rejects action-authorizing roles, missing scope/provenance, and a terminal transition
without its required receipt/artifact reference.

## Why This Matters

Producer and reader code cannot safely share an untyped dict. The type must make the low-trust floor
and lifecycle-vs-claim-truth distinction structural before a live path is introduced.

## Acceptance Criteria

- [ ] A provisional record is always noncanonical, scoped, provenance-bearing, and restricted to
  non-authoritative evidence roles. Verify: `tests/agent_memory/test_provisional_memory_record.py::test_record_pins_noncanonical_low_trust_roles`
- [ ] Invalid action-authorizing or canonical values fail validation. Verify: `tests/agent_memory/test_provisional_memory_record.py::test_record_rejects_authority_escalation`
- [ ] Lifecycle transitions reuse the durable decision/receipt ledger and distinguish terminal from
  retryable partial state. Verify: `tests/agent_memory/test_provisional_memory_record.py::test_lifecycle_receipts_distinguish_terminal_and_retryable_state`
- [ ] Existing promoted-memory and recall behavior is unchanged. Verify: `tests/agent_memory/test_memory_promotion.py` and `tests/agent_memory/test_guarded_recall_activation.py`

## How to Verify (Pre-Merge)

Run the named record tests plus the existing promotion and guarded-recall suites. Inspect the store
schema/API to confirm there is one lifecycle receipt authority and no new claim-truth store.

## Out of Scope

- API routes or filesystem writes.
- Recall/admission of provisional memory.
- Promotion, UI, or production channel work.

## Related Docs

- `docs/architecture/memory-model.md`
- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`
- `docs/DURABLE_MEMORY_AND_RECALL/README.md`
- `docs/adr/ADR-0025-memory-authority-direct-write-policy.md`

## Related GitHub Issues

Create one implementation Issue under parent validation hub #2314. TCD hint: Sol/high because the
record spans memory authority and durable lifecycle semantics.

