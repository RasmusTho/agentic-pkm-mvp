---
name: iCloud conflict quarantine
description: Exclude iCloud conflicted-copy Markdown files before ordinary vault ingest.
task_id: VMW-03
source_anchor: docs/adr/ADR-0055-vault-multiwriter-consistency-model.md :: item 3
parent_capability: VAULT_MULTIWRITER_ENACTMENT
prerequisites: [VMW-01]
depends_on: [WRITE_RECEIPT_PROVENANCE.md]
can_parallelize_with: [REWRITTEN_NOTE_CONFLICT_STAGING]
---

# iCloud Conflict Quarantine

## Purpose

Ensure iCloud conflict artifacts cannot silently become ordinary indexed notes.

## What This Task Does

Consume VMW-01's shared conflict-artifact classifier at the vault scan/ingest boundary. It must exclude both `* (conflicted copy).md`-style files and VMW-02 staged artifacts from ordinary iteration and provide a quarantine/surfacing path suitable for later human resolution.

## Concretely

The filter belongs in the production iterator used by watcher/ingest, before clients can parse or index the file. It does not delete, merge, or alter the artifact. Its only filename grammar is VMW-01's shared classifier.

## Why This Matters

A conflict copy is unresolved competing content, not a new canonical note. Indexing it would contaminate retrieval and obscure the collision.

## Acceptance Criteria

- [ ] Synthetic iCloud conflicted-copy filenames are absent from ordinary vault Markdown iteration. Verify: `tests/watcher/test_vault_conflict_quarantine.py::test_conflicted_copy_is_not_yielded_as_ordinary_note`
- [ ] A VMW-02-staged artifact is absent from ordinary iteration through the same shared classifier. Verify: `tests/watcher/test_vault_conflict_quarantine.py::test_staged_conflict_artifact_is_not_yielded_as_ordinary_note`
- [ ] Normal Markdown and non-conflict parent notes continue to be yielded. Verify: `tests/watcher/test_vault_conflict_quarantine.py::test_quarantine_preserves_normal_sibling_note`
- [ ] Quarantine preserves the artifact on disk and emits a legible classification/receipt rather than deleting it. Verify: `tests/watcher/test_vault_conflict_quarantine.py::test_quarantine_does_not_delete_conflict_artifact`

## How to Verify (Pre-Merge)

`pytest -q tests/watcher/test_vault_conflict_quarantine.py tests/watcher` and `ruff check app tests`.

## Out of Scope

Conflict staging for a runtime write (VMW-02), semantic merge, and any deletion/automatic resolution.

## Related Docs

ADR-0055 item 3; INV-VW3; `app/vault/manager.py`.

## Related GitHub Issues

Implements independent child of #3132; medium reasoning due to ingest/retrieval boundary impact.
