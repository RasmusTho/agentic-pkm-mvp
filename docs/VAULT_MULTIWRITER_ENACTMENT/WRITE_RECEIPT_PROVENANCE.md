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

Add a centralized note-class/operation classifier aligned with the committed Mimer client-contract table, a shared rewritten-write request carrying the caller's expected content version, and one conflict-artifact grammar/classifier consumed by both staging and quarantine. Extend `WriteReceipt`/the filesystem adapter so write and append receipts carry writer identity and an UTC timestamp.

## Concretely

`_heimdal` full-note/frontmatter updates, prose, companion notes, and Episode notes are rewritten. Capture, event-log, Sources, and explicitly append-only control-note body operations remain append-only. The shared rewritten-write request carries the hash read by the caller through `write_note_relative`/`write_note_from_absolute` to `FsVaultAdapter`; a rewritten write without that version returns a structured non-write outcome rather than silently bypassing INV-VW1. The shared artifact helper owns the sibling filename grammar and `is_conflict_artifact` predicate.

## Why This Matters

VMW-02 cannot safely apply stale detection until it knows which operation is rewritten. Provenance lets a human understand the two sides of a staged conflict.

## Acceptance Criteria

- [ ] Runtime classification covers every decided #3131 row, including mixed control notes by operation. Verify: `tests/invariants/test_vault_multiwriter.py::test_runtime_note_classes_match_published_contract_rows`
- [ ] A rewritten write's expected hash is propagated through the public knowledge ports to the production filesystem seam; missing expected version does not silently overwrite. Verify: `tests/invariants/test_vault_multiwriter.py::test_rewritten_write_requires_expected_version_at_filesystem_seam`
- [ ] Filesystem write and append receipts carry a non-empty writer identity and UTC timestamp. Verify: `tests/invariants/test_vault_multiwriter.py::test_filesystem_write_receipt_carries_writer_provenance`
- [ ] Append-only classification is observable at the production filesystem write seam, not only in a helper test. Verify: `tests/invariants/test_vault_multiwriter.py::test_append_operation_uses_append_only_class_at_filesystem_seam`
- [ ] The shared conflict-artifact grammar identifies both VMW-02 staged artifacts and iCloud-style conflicted copies. Verify: `tests/invariants/test_vault_multiwriter.py::test_conflict_artifact_classifier_recognizes_staged_and_icloud_names`

## How to Verify (Pre-Merge)

`pytest -q tests/invariants/test_vault_multiwriter.py` and `ruff check app tests`.

## Out of Scope

Stale detection/conflict staging (VMW-02), watcher quarantine (VMW-03), migration of non-rewritten legacy writers, and `append_note_relative` WriteGuard coverage (#3129).

## Related Docs

ADR-0055; `docs/contracts/MIMER_CLIENT_CONTRACT.md :: Note-classification contract`; `app/knowledge/adapters.py`; `app/knowledge/contracts.py`.

## Related GitHub Issues

Implements child of #3132; recommend medium/high reasoning because this changes the shared write receipt contract.
