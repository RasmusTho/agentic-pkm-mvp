---
name: Rewritten note conflict staging
description: Atomically detect stale rewritten writes and preserve losing content as a conflict artifact.
task_id: VMW-02
source_anchor: docs/adr/ADR-0055-vault-multiwriter-consistency-model.md :: items 1-2, 6
parent_capability: VAULT_MULTIWRITER_ENACTMENT
prerequisites: [VMW-01]
depends_on: [WRITE_RECEIPT_PROVENANCE.md]
can_parallelize_with: [ICLOUD_CONFLICT_QUARANTINE]
---

# Rewritten Note Conflict Staging

## Purpose

Replace silent overwrite of rewritten notes with atomic compare-and-stage behavior while retaining successful atomic writes.

## What This Task Does

Consume VMW-01's SHA-256 expected-version request at the shared rewritten-note filesystem write path. When current content differs, preserve the caller's proposed content as a sibling conflict artifact using VMW-01's shared grammar and return a legible staged-conflict outcome with provenance.

## Concretely

The production `FsVaultAdapter.write_note` path writes through temp-file-plus-`os.replace`. A stale rewritten write must never replace the current file and must never lose the proposed bytes. Append-only operations bypass this path. The integration fixture hands the staged artifact to the VMW-01 classifier, proving VMW-03 can quarantine it without inferring a second filename convention.

## Why This Matters

Human prose and control notes are canonical vault material. Refusing or overwriting the losing version would still lose human meaning.

## Acceptance Criteria

- [ ] Successful rewritten writes are atomic at the shared filesystem adapter. Verify: `tests/invariants/test_vault_multiwriter.py::test_rewritten_write_uses_atomic_replace_at_filesystem_seam`
- [ ] A stale rewritten write stages the losing content beside the current note using the shared artifact grammar and reports both the artifact and writer provenance. Verify: `tests/invariants/test_vault_multiwriter.py::test_stale_rewritten_write_stages_conflict_artifact_at_filesystem_seam`
- [ ] A staged artifact is recognized by the shared quarantine classifier before watcher work begins. Verify: `tests/invariants/test_vault_multiwriter.py::test_staged_conflict_artifact_matches_quarantine_classifier`
- [ ] An append-only operation does not invoke rewritten-note stale detection. Verify: `tests/invariants/test_vault_multiwriter.py::test_append_only_write_does_not_stage_stale_conflict`

## How to Verify (Pre-Merge)

`pytest -q tests/invariants/test_vault_multiwriter.py tests/knowledge` and `ruff check app tests`.

## Out of Scope

Semantic merge/AI resolution, iCloud ingest quarantine (VMW-03), and #3129.

## Related Docs

ADR-0055; `docs/contracts/MIMER_CLIENT_CONTRACT.md`; `app/components/concurrency.py`; `app/knowledge/adapters.py`.

## Related GitHub Issues

Implements child of #3132 after VMW-01; high reasoning due to concurrent filesystem behavior.
