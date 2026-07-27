State: Implemented through VMW-01..04 by issue #3453 / PR #4148. GitHub parent #3132 remains the lifecycle authority for terminal validation and closure; its terminal receipt is a governed post-merge effect and is not claimed by this document.

# Vault Multiwriter Enactment

This capability enacts ADR-0055's local-file safety posture without changing its authority model: rewritten-note callers that supply `expected_version` detect an initially stale version and preserve the proposal, append-only operations stay append-only, and iCloud conflict copies never enter ordinary ingest. Remaining versionless rewritten writers retain the explicit #3570 migration posture.

## Execution order

1. [WRITE_RECEIPT_PROVENANCE](WRITE_RECEIPT_PROVENANCE.md) (VMW-01, delivered by #3450 / PR #3457)
2. [REWRITTEN_NOTE_CONFLICT_STAGING](REWRITTEN_NOTE_CONFLICT_STAGING.md) (VMW-02, delivered by #3451 / PR #4133) and [ICLOUD_CONFLICT_QUARANTINE](ICLOUD_CONFLICT_QUARANTINE.md) (VMW-03, delivered by #3452 / PR #4126)
3. [RECONCILE_AND_CLOSE_MULTIWRITER_ENACTMENT](RECONCILE_AND_CLOSE_MULTIWRITER_ENACTMENT.md) (VMW-04, delivered by #3453 / PR #4148)

## Cross-Task Invariants / Interaction Safety

- The published #3131 classification contract is authoritative. Runtime classification may represent it for execution, but parity tests must cover every decided row and no writer may add a private policy.
- VMW-01 owns the shared expected-version request field and conflict-artifact grammar/classifier. VMW-02 must stage only through that grammar; VMW-03 must quarantine the same grammar before normal ingestion.
- A stale rewritten write is terminal only once its losing content is staged with provenance; an exception or a receipt alone must not discard it.
- Append-only body operations are never redirected into whole-note stale detection. Mixed notes classify by operation: rewritten frontmatter/full-note update versus append-only body operation.
- A quarantined iCloud conflicted copy is never yielded to ordinary ingest or retrieval. If staging succeeds but watcher filtering has not landed, the capability is incomplete and VMW-04 must not promote INV-VW3.

## Capability acceptance

- [x] Every ADR-0055 rewritten/append-only class is covered by the runtime classifier and parity tests. Verify: VMW-01/02 child receipts and `tests/invariants/test_vault_multiwriter.py`. Rewritten-note stale enforcement is opt-in for callers that supply `expected_version`; #3570 tracks progressive migration of remaining versionless writers.
- [x] An initially stale opted-in rewritten write stages the losing content and provenance instead of silently overwriting or dropping it. Verify: VMW-02 production-path tests in `tests/invariants/test_vault_multiwriter.py`.
- [x] Both iCloud copies and VMW-02-staged artifacts are excluded before ordinary ingestion. Verify: VMW-03 tests in `tests/watcher/test_vault_conflict_quarantine.py`.
- [x] INV-VW1 and INV-VW3 describe shipped enforcement after the two behavior slices merged. Verify: VMW-04 doc writeback.
- [ ] Closure-time effect: parent #3132 receives the terminal validation and closure receipt after PR #4148 merges. Verify: parent #3132 terminal receipt.

## Relationship to GitHub issues

Feature parent: #3132. Children: VMW-01 #3450, VMW-02 #3451, VMW-03 #3452, and VMW-04 #3453. #3129 remains a separate INV-VW2 repair and is not part of this capability.
