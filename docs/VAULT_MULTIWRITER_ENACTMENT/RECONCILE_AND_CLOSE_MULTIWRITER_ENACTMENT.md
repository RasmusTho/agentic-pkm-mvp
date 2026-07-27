---
name: Reconcile and close multiwriter enactment
description: Verify the delivered mechanism, update invariant truth, and close the parent feature hub.
task_id: VMW-04
source_anchor: "docs/testing/invariant-tests.md :: INV-VW1, INV-VW3"
parent_capability: VAULT_MULTIWRITER_ENACTMENT
prerequisites: [VMW-02, VMW-03]
depends_on: [REWRITTEN_NOTE_CONFLICT_STAGING.md, ICLOUD_CONFLICT_QUARANTINE.md]
can_parallelize_with: []
---

# Reconcile and Close Multiwriter Enactment

State: Implemented by issue #3453 after VMW-01 #3450 / PR #3457, VMW-02 #3451 / PR #4133, and VMW-03 #3452 / PR #4126.

## Purpose

Turn merged child evidence into a truthful #3132 acceptance verdict and invariant-registry writeback.

## What This Task Does

Verify VMW-01 through VMW-03 against #3132, update INV-VW1/INV-VW3 from target/absent wording to shipped enforcement only when tests prove the production paths, and post the parent receipt.

## Concretely

Read the merged child PRs and their current-base test evidence. If either behavior is missing, leave the invariant target wording and parent open; do not close based on code presence alone.

## Why This Matters

The registry is an owner-facing truth surface. Premature promotion would recreate the audit drift this feature exists to remove.

## Verification ledger

| Slice | Delivered evidence | Current-base verification | Accepted truth |
| --- | --- | --- | --- |
| VMW-01 | #3450 / PR #3457; reviewed head `5d5a87f186abe8f31904f77b2ee0f7688d3651f6`; merge `99ce217797393c366739b7684a8752f755b21035` | The five declared VMW-01 selectors pass in `tests/invariants/test_vault_multiwriter.py`; their parametrized cases are included in the 23-test child-AC run. | The shared classifier, expected-version request, conflict-artifact grammar, and writer/timestamp receipts are shipped. Enforcement is deliberately opt-in: versionless rewritten writes remain allowed and observable; #3570 tracks their progressive migration. |
| VMW-02 | #3451 / PR #4133; reviewed head `a5c26cb0f6be49f9d19837f973fdc632d53f97e1`; merge `eb9f88dad31403121c1c16cafacb3ca046e521a9` | The four declared VMW-02 selectors pass in `tests/invariants/test_vault_multiwriter.py`; the complete invariant module passes 69 tests and its composition with `tests/knowledge` passes 138 tests on the reconciliation base. | Initially stale opted-in rewritten proposals are durably staged with provenance without replacing canonical content; matching writes use the hardened atomic seam; receiptless post-linearization races do not acknowledge success. |
| VMW-03 | #3452 / PR #4126; reviewed head `77774aef321fb0afa343729d66d49c6b6a416d10`; merge `c546096f1cb169210c9dacbc43c5738962cd493a` | The four declared VMW-03 selectors pass through the production vault iterator; they are included in the 23-test child-AC run, and the current watcher suite passes 155 tests. | iCloud and runtime-staged conflict artifacts are preserved and quarantined before ordinary watcher/ingest/index parsing, while normal Markdown siblings remain visible. |
| VMW-04 | #3453 | `python3 scripts/docs_guard.py`, `ruff check app tests`, the 23-test child-AC selector run, the 69-test invariant module, the 138-test invariant/knowledge composition, and the 155-test watcher suite on the exact delivery tree. | INV-VW1 and INV-VW3 now describe only the enforcement proven above; the parent receipt owns closure. |

## Transition debt and residual risk

- #3570 remains open as progressive migration of versionless rewritten writers. It is not a VMW-01 promotion or #3132 closure blocker under the 2026-07-13 owner decision; until a caller supplies `expected_version`, that caller can still resolve a concurrent rewrite as last-write-wins.
- SBS transition debt D11 remains `Containing`: this Product owner-doc reconciliation used the Issue/PR authority path and did not turn Builder workflow artifacts into Product runtime subsystems or MEM/HKA authority.
- SBS transition debt D12 remains `Containing`: delivery evidence stays in GitHub Issues/PRs and the already-recorded BuilderOps evidence; this reconciliation found no new learning or reevaluation signal requiring a separate record.
- #3129 / INV-VW2 is already delivered independently and is not reopened or absorbed here.

## Acceptance Criteria

- [x] INV-VW1 names the shipped opt-in stale-detection/conflict-staging enforcement and its current tests. Verify: doc writeback at `docs/testing/invariant-tests.md :: stale_write_rejected_for_rewritten_notes`
- [x] INV-VW3 names the shipped quarantine enforcement and its current tests. Verify: doc writeback at `docs/testing/invariant-tests.md :: icloud_conflict_artifacts_never_silently_ingested`
- [x] #3132 contains child PR, validation, owner-doc, and unresolved-risk receipts before closure. Verify: parent #3132 delivery receipt

## How to Verify (Pre-Merge)

Run all child `Verify:` commands, `ruff check app tests`, and inspect #3132 plus merged PR heads.

## Out of Scope

New runtime behavior and #3129.

## Related Docs

`docs/testing/invariant-tests.md`; ADR-0055; #3132.

## Related GitHub Issues

Final child of #3132; high reasoning because it controls acceptance and closure truth.
