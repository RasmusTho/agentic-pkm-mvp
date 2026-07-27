---
name: Rewritten note conflict staging
description: Atomically detect stale rewritten writes and preserve losing content as a conflict artifact.
task_id: VMW-02
source_anchor: "docs/adr/ADR-0055-vault-multiwriter-consistency-model.md :: items 1-2, 6"
parent_capability: VAULT_MULTIWRITER_ENACTMENT
prerequisites: [VMW-01]
depends_on: [WRITE_RECEIPT_PROVENANCE.md]
can_parallelize_with: [ICLOUD_CONFLICT_QUARANTINE]
---

# Rewritten Note Conflict Staging

## Purpose

Replace silent overwrite of rewritten notes with atomic compare-and-stage behavior while retaining successful atomic writes.

## What This Task Does

Consume VMW-01's SHA-256 expected-version request at the shared rewritten-note filesystem write path. When current content differs, preserve the caller's proposed content as a sibling conflict artifact using VMW-01's shared grammar and produce a legible staged-conflict outcome with provenance. The low-level adapter returns that receipt; shared production helpers raise with the receipt attached unless a conflict-aware caller explicitly opts into consuming the non-canonical outcome.

## Concretely

The production `FsVaultAdapter.write_note` path uses a descriptor-anchored same-filesystem atomic exchange for matching rewritten writes and retains the displaced inode as a non-indexed safety artifact. A stale rewritten write must never replace the current file and must never lose the proposed bytes. Initial-stale publication keeps a trusted candidate link through final public-artifact verification; a public-name replacement before that receipt fence fails without a receipt and leaves the exact candidate recoverable. Each exclusive staging open records its controlled inode before write, flush, or `fsync`, so pre-publication I/O failures identity-clean partial hidden entries. During initial-stale candidate publication, the full proposal remains on the prior trusted rewrite-staging path. Direct text read/transform/write producers bind decoded UTF-8 content and the SHA-256 of the exact raw bytes in one `read_note_text_with_version` call, so CRLF input is not falsely declared stale through newline normalization. Production consumers treat canonical write completion as their acknowledgement fence: the note-update service and both direct watcher paths prepare without executed-ID, dispatch/emission, or snapshot effects, and those effects occur only after the version-checked hardened knowledge write succeeds. Before either watcher can prepare a mutation, it resolves the candidate against the canonical vault root, rejects symlink aliases, and requires the authoritative classifier to admit the path as `REWRITTEN`; `CREATE_ONCE` Sources and append-only paths are rejected before UUID healing, writeback, ID persistence, or event emission even when AI-fenced. As defense-in-depth, the absolute helper preserves the authorized lexical locator; the adapter rejects an existing alias, classifies the canonical vault-relative target rather than the lexical locator, and rejects any expected-version write for a non-rewritten class before mutation. A root-anchored no-follow component walk binds that locator through linearization and rejects leaf or ancestor redirects after caller policy checks. An immediate post-exchange displaced-inode check atomically restores a leaf replacement introduced in the final check/exchange gap before retaining the proposal and raising. The watchers do not use the non-atomic check-then-write `OptimisticWriteGuard.write_if_unchanged` utility for rewritten notes. Only an attached `conflict_staged` receipt maps to stale/deferred; receiptless/other conflicts propagate as indeterminate errors. Append-only operations bypass this path. The integration fixture hands the staged artifact to the VMW-01 classifier, proving VMW-03 can quarantine it without inferring a second filename convention.

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
