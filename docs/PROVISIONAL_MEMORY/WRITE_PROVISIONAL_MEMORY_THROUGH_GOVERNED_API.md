---
name: Write Provisional Memory Through Governed API
description: Create provenance-bound provisional Markdown through a production API while enforcing the trust ceiling and receipt atomicity.
task_id: PROVISIONAL-MEMORY-02
source_anchor: docs/adr/ADR-0025-memory-authority-direct-write-policy.md :: Provisional memory persists through a human-readable, provenance-bound provisional memory note
parent_capability: Provisional Memory
prerequisites: [PROVISIONAL-MEMORY-01]
depends_on: [DEFINE_PROVISIONAL_MEMORY_RECORD.md]
can_parallelize_with: []
---

# WRITE_PROVISIONAL_MEMORY_THROUGH_GOVERNED_API

## Purpose

Introduce the first direct-write producer without letting that producer promote memory, bypass
WriteGuard, or turn sync into an execution trigger.

## What This Task Does

- Adds one authenticated/local product API operation for a direct provisional-memory write.
- Creates a human-readable, editable, provenance-bound Markdown note as the primary provisional
  artifact through the normal vault write port and WriteGuard.
- Invokes the trust-tier guard at the production call site before persistence.
- Records lifecycle receipts and implements fail-closed reconciliation for partial failures.

## Concretely

A successful request returns the provisional record, artifact reference, and lifecycle receipt.
It never calls the promoted-memory materializer and never emits an accepted/canonical authority
transition. A file arriving via sync does nothing.

## Why This Matters

ADR-0025 explicitly requires the guard before the first producer lands. A safe data type without a
live call-site check would leave the highest-risk boundary unenforced.

## Acceptance Criteria

- [ ] The production API calls the trust-tier guard and creates a provisional artifact plus receipt
  only when WriteGuard allows the write. Verify: `tests/agent_memory/test_provisional_memory_api.py::test_direct_write_creates_provisional_artifact_and_receipt`
- [ ] The artifact preserves provenance/review state and cannot be mistaken for a promoted semantic
  memory note. Verify: `tests/agent_memory/test_provisional_memory_api.py::test_provisional_artifact_is_visibly_distinct_from_promoted_memory`
- [ ] Blocked writes and receipt/artifact partial failures fail closed, remain retryable, and are
  reconciled without an admitted orphan. Verify: `tests/agent_memory/test_provisional_memory_failures.py::test_partial_write_fails_closed_and_reconciles`
- [ ] The production call site never invokes promotion/materialization or grants mutation authority.
  Verify: `tests/agent_memory/test_provisional_memory_call_sites.py::test_write_endpoint_cannot_promote_or_authorize_apply`
- [ ] Filesystem/sync appearance does not trigger a transition. Verify: `tests/agent_memory/test_provisional_memory_call_sites.py::test_sync_is_not_an_execution_bus`

## How to Verify (Pre-Merge)

Run the named API, failure, and call-site tests against a temporary vault. Run existing WriteGuard,
memory-materialization, and review-decision-store suites. Assert artifact/receipt pairing after a
simulated failure and restart.

## Out of Scope

- Reading provisional memory into answers or proposals.
- Promotion or review UI changes.
- Any prod/test deployment or vault migration.

## Restart / Durability Posture

The Markdown artifact and lifecycle receipts survive restart. Runtime request state does not. An
incomplete pair remains excluded from recall until reconciliation resolves or surfaces it.

## Related Docs

- `docs/adr/ADR-0025-memory-authority-direct-write-policy.md`
- `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md`
- `docs/SEPARATING_PERSISTENCE_SURFACES/DEFINE_WRITING_SURFACE_CONTRACT.md`
- `docs/DURABLE_MEMORY_AND_RECALL/MATERIALIZE_PROMOTED_MEMORY_TO_VAULT.md`

## Related GitHub Issues

Create after PROVISIONAL-MEMORY-01 merges. TCD hint: Sol/high-xhigh due to authority, filesystem,
partial-failure, and production API risk.

