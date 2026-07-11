State: Specification for feature issue #3132. The parent is a validation hub; only its child slices are pickup candidates.

# Vault Multiwriter Enactment

This capability enacts ADR-0055's local-file safety posture without changing its authority model: rewritten notes detect a stale version and preserve the losing content, append-only operations stay append-only, and iCloud conflict copies never enter ordinary ingest.

## Execution order

1. [WRITE_RECEIPT_PROVENANCE](WRITE_RECEIPT_PROVENANCE.md) (VMW-01)
2. [REWRITTEN_NOTE_CONFLICT_STAGING](REWRITTEN_NOTE_CONFLICT_STAGING.md) (VMW-02) and [ICLOUD_CONFLICT_QUARANTINE](ICLOUD_CONFLICT_QUARANTINE.md) (VMW-03), in parallel after VMW-01
4. [RECONCILE_AND_CLOSE_MULTIWRITER_ENACTMENT](RECONCILE_AND_CLOSE_MULTIWRITER_ENACTMENT.md) (VMW-04), after VMW-02 and VMW-03

## Cross-Task Invariants / Interaction Safety

- The published #3131 classification contract is authoritative. Runtime classification may represent it for execution, but parity tests must cover every decided row and no writer may add a private policy.
- VMW-01 owns the shared expected-version request field and conflict-artifact grammar/classifier. VMW-02 must stage only through that grammar; VMW-03 must quarantine the same grammar before normal ingestion.
- A stale rewritten write is terminal only once its losing content is staged with provenance; an exception or a receipt alone must not discard it.
- Append-only body operations are never redirected into whole-note stale detection. Mixed notes classify by operation: rewritten frontmatter/full-note update versus append-only body operation.
- A quarantined iCloud conflicted copy is never yielded to ordinary ingest or retrieval. If staging succeeds but watcher filtering has not landed, the capability is incomplete and VMW-04 must not promote INV-VW3.

## Capability acceptance

- [ ] Every ADR-0055 rewritten/append-only class is covered by the runtime classifier and parity tests. Verify: VMW-01/02 child receipts and `tests/invariants/test_vault_multiwriter.py`.
- [ ] A stale rewritten write stages the losing content and provenance instead of silently overwriting or dropping it. Verify: VMW-02 production-path test.
- [ ] Both iCloud copies and VMW-02-staged artifacts are excluded before ordinary ingestion. Verify: VMW-03 fixture and staging-to-quarantine integration tests.
- [ ] INV-VW1 and INV-VW3 describe shipped enforcement only after the two behavior slices merge. Verify: VMW-04 writeback and parent #3132 receipt.

## Relationship to GitHub issues

Feature parent: #3132. Child issue numbers are added here when filed. #3129 remains a separate INV-VW2 repair and is not part of this capability.
