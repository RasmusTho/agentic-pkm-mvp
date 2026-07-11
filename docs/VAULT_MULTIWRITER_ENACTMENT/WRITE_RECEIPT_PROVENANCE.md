---
name: Write receipt provenance and note classification
description: Centralize ADR-0055 note-class execution policy and enrich filesystem write receipts.
task_id: VMW-01
source_anchor: docs/adr/ADR-0055-vault-multiwriter-consistency-model.md :: items 1, 4, 6
parent_capability: VAULT_MULTIWRITER_ENACTMENT
prerequisites: []
depends_on: []
can_parallelize_with: [ICLOUD_CONFLICT_QUARANTINE]
---

# Write Receipt Provenance and Note Classification

## Purpose

Give the shared filesystem write seam one explicit execution representation of #3131's note classes and identify every write in its receipt.

## What This Task Does

Add a centralized note-class/operation classifier aligned with the committed Mimer client-contract table, and extend `WriteReceipt`/the filesystem adapter so write and append receipts carry writer identity and an UTC timestamp.

## Concretely

`_heimdal` full-note/frontmatter updates, prose, companion notes, and Episode notes are rewritten. Capture, event-log, Sources, and explicitly append-only control-note body operations remain append-only. The new classifier is consumed by the filesystem write path; it is not a second policy source.

## Why This Matters

VMW-02 cannot safely apply stale detection until it knows which operation is rewritten. Provenance lets a human understand the two sides of a staged conflict.

## Acceptance Criteria

- [ ] Runtime classification covers every decided #3131 row, including mixed control notes by operation. Verify: `tests/invariants/test_vault_multiwriter.py::test_runtime_note_classes_match_published_contract_rows`
- [ ] Filesystem write and append receipts carry a non-empty writer identity and UTC timestamp. Verify: `tests/invariants/test_vault_multiwriter.py::test_filesystem_write_receipt_carries_writer_provenance`
- [ ] Append-only classification is observable at the production filesystem write seam, not only in a helper test. Verify: `tests/invariants/test_vault_multiwriter.py::test_append_operation_uses_append_only_class_at_filesystem_seam`

## How to Verify (Pre-Merge)

`pytest -q tests/invariants/test_vault_multiwriter.py` and `ruff check app tests`.

## Out of Scope

Stale detection/conflict staging (VMW-02), watcher quarantine (VMW-03), and `append_note_relative` WriteGuard coverage (#3129).

## Related Docs

ADR-0055; `docs/contracts/MIMER_CLIENT_CONTRACT.md :: Note-classification contract`; `app/knowledge/adapters.py`; `app/knowledge/contracts.py`.

## Related GitHub Issues

Implements child of #3132; recommend medium/high reasoning because this changes the shared write receipt contract.

