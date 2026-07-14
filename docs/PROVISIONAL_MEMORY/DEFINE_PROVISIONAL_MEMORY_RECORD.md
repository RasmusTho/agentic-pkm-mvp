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
- Defines a typed read model reconstructed from the Markdown artifact plus content-free lifecycle
  receipts; it does not create or prescribe a second durable content store.
- Uses the existing receipt architecture for transition semantics. Any backing-store change must
  stay content-free and follow the owning PDM/GOV contract in its implementation Issue.
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
- [ ] Lifecycle transitions use content-free receipts and distinguish terminal from retryable
  partial state. Verify: `tests/agent_memory/test_provisional_memory_record.py::test_lifecycle_receipts_are_content_free_and_distinguish_retryable_state`
- [ ] The read model follows edited Markdown and excludes a missing artifact without reconstructing
  claim content from receipts. Verify: `tests/agent_memory/test_provisional_memory_record.py::test_record_rebuild_follows_markdown_and_never_resurrects_missing_content`
- [ ] Existing promoted-memory and recall behavior is unchanged. Verify: `tests/agent_memory/test_memory_promotion.py::test_promoted_memory_preserves_provenance` and `tests/agent_memory/test_guarded_recall_activation.py::test_unreviewed_recall_cannot_authorize_writeback`

## How to Verify (Pre-Merge)

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q \
  tests/agent_memory/test_provisional_memory_record.py \
  tests/agent_memory/test_memory_promotion.py::test_promoted_memory_preserves_provenance \
  tests/agent_memory/test_guarded_recall_activation.py::test_unreviewed_recall_cannot_authorize_writeback
ruff check app tests
```

Inspect the persistence diff to confirm receipts are content-free and Markdown remains the only
claim-content source.

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
