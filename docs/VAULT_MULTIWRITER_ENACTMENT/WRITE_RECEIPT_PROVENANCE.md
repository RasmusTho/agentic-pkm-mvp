---
name: Write receipt provenance and note classification
description: Centralize ADR-0055 note-class execution policy and enrich filesystem write receipts.
task_id: VMW-01
source_anchor: "docs/adr/ADR-0055-vault-multiwriter-consistency-model.md :: items 1, 4, 6"
parent_capability: VAULT_MULTIWRITER_ENACTMENT
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Write Receipt Provenance and Note Classification

## Purpose

Give the shared filesystem write seam one explicit execution representation of #3131's note classes and identify every write in its receipt.

## What This Task Does

Add a centralized note-class/operation classifier aligned with the committed Mimer client-contract table, a shared rewritten-write request carrying the caller's expected content version, and one conflict-artifact grammar/classifier consumed by both staging and quarantine. Extend `WriteReceipt`/the filesystem adapter so write and append receipts carry writer identity and an UTC timestamp.

## Concretely

`_heimdal` full-note/frontmatter updates, prose, companion notes, and Episode notes are rewritten. Capture, event-log, Sources, and explicitly append-only control-note body operations remain append-only. The shared rewritten-write request carries the hash read by the caller through `write_note_relative`/`write_note_from_absolute` to `FsVaultAdapter`.

**Enforcement is opt-in during the enactment gap (owner decision 2026-07-13).** Version enforcement applies ONLY to callers that opt in by passing `expected_version`. This avoids breaking the many versionless legacy writers at once while they are migrated progressively (tracked in #3570):

- `expected_version` omitted → the write is performed normally (enforcement deferred). The `WriteReceipt` still records the structured `note_class` outcome, so the classification is observable even before a caller opts in.
- `expected_version` provided and matching the current on-disk hash → the write proceeds.
- `expected_version` provided and stale at the first comparison (mismatched) → with VMW-02 composed with this request contract, the seam preserves the caller's proposal under the shared sibling conflict-artifact grammar, leaves the canonical note unchanged, and returns a `conflict_staged` receipt. Missing targets and races after the first comparison still fail closed with `KnowledgeWriteConflict`.

This resolves the earlier "structured non-write outcome vs. hard raise" tension in favour of the opt-in model: a versionless rewrite is a normal write plus a classified receipt, an initially stale opted-in rewrite has the structured staged-conflict outcome supplied by VMW-02, and an in-flight race remains a hard failure. The shared artifact helper owns the sibling filename grammar and `is_conflict_artifact` predicate.

## Why This Matters

VMW-02 relies on this classification to apply stale detection only to rewritten operations. Provenance lets a human understand the two sides of a staged conflict, while VMW-03 consumes the same artifact grammar to quarantine that sibling before ordinary ingest.

## Acceptance Criteria

- [ ] Runtime classification covers every decided #3131 row, including mixed control notes by operation. Verify: `tests/invariants/test_vault_multiwriter.py::test_runtime_note_classes_match_published_contract_rows`
- [ ] A rewritten write's expected hash is propagated through the public knowledge ports to the production filesystem seam; enforcement is opt-in (a versionless rewrite writes and records its `note_class`; after VMW-02 composition, an initially stale opted-in rewrite stages the proposal without overwriting canonical content). Verify: `tests/invariants/test_vault_multiwriter.py::test_rewritten_write_enforces_only_on_opt_in_expected_version_at_filesystem_seam`
- [ ] Filesystem write and append receipts carry a non-empty writer identity and UTC timestamp. Verify: `tests/invariants/test_vault_multiwriter.py::test_filesystem_write_receipt_carries_writer_provenance`
- [ ] Append-only classification is observable at the production filesystem write seam, not only in a helper test. Verify: `tests/invariants/test_vault_multiwriter.py::test_append_operation_uses_append_only_class_at_filesystem_seam`
- [ ] The shared conflict-artifact grammar identifies both VMW-02 staged artifacts and iCloud-style conflicted copies. Verify: `tests/invariants/test_vault_multiwriter.py::test_conflict_artifact_classifier_recognizes_staged_and_icloud_names`

## How to Verify (Pre-Merge)

`pytest -q tests/invariants/test_vault_multiwriter.py` and `ruff check app tests`.

## Out of Scope

VMW-01 does not itself own stale detection/conflict staging (VMW-02) or watcher quarantine (VMW-03), although both are now composed with its shared contract. Migration of remaining versionless rewritten writers, VMW-04 registry reconciliation, and `append_note_relative` WriteGuard coverage (#3129) remain out of scope.

## Related Docs

ADR-0055; `docs/contracts/MIMER_CLIENT_CONTRACT.md :: Note-classification contract`; `app/knowledge/adapters.py`; `app/knowledge/contracts.py`.

## Related GitHub Issues

Implements child of #3132; recommend medium/high reasoning because this changes the shared write receipt contract.
