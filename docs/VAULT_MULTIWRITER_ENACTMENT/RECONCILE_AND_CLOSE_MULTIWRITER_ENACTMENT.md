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

## Purpose

Turn merged child evidence into a truthful #3132 acceptance verdict and invariant-registry writeback.

## What This Task Does

Verify VMW-01 through VMW-03 against #3132, update INV-VW1/INV-VW3 from target/absent wording to shipped enforcement only when tests prove the production paths, and post the parent receipt.

## Concretely

Read the merged child PRs and their current-base test evidence. If either behavior is missing, leave the invariant target wording and parent open; do not close based on code presence alone.

## Why This Matters

The registry is an owner-facing truth surface. Premature promotion would recreate the audit drift this feature exists to remove.

## Acceptance Criteria

- [ ] INV-VW1 names the shipped stale-detection/conflict-staging enforcement and its current test. Verify: doc writeback at `docs/testing/invariant-tests.md :: stale_write_rejected_for_rewritten_notes`
- [ ] INV-VW3 names the shipped quarantine enforcement and its current test. Verify: doc writeback at `docs/testing/invariant-tests.md :: icloud_conflict_artifacts_never_silently_ingested`
- [ ] #3132 contains child PR, validation, owner-doc, and unresolved-risk receipts before closure. Verify: parent #3132 delivery receipt

## How to Verify (Pre-Merge)

Run all child `Verify:` commands, `ruff check app tests`, and inspect #3132 plus merged PR heads.

## Out of Scope

New runtime behavior and #3129.

## Related Docs

`docs/testing/invariant-tests.md`; ADR-0055; #3132.

## Related GitHub Issues

Final child of #3132; high reasoning because it controls acceptance and closure truth.

