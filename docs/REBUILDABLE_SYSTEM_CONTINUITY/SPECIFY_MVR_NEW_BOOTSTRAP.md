---
name: Specify MVR New Bootstrap
description: Amend the existing Multi-Vault Runtime contract for loss of journal, lease, ownership, and recovery lineage.
task_id: RSC-05
github_issue:
source_anchor: "docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md :: instance state"
parent_capability: Rebuildable System Continuity
prerequisites: [RSC-01]
depends_on: [RSC-01]
can_parallelize_with: []
---

# Specify MVR New Bootstrap

## Purpose

Resolve the operational-state exception inside the existing MVR authority before any recovery code
is added.

## What This Task Does

Amend the existing MVR specification and live dependency chain with a new-epoch state machine:
inactive fence, source/config discovery, host/external readback, ownership conflict refusal,
receipt-bound convergence, and explicit activation. Preserve journals/backups when present, but do
not require them to fabricate restoration after total loss.

## Concretely

Contract tests parse the MVR transition table and prove missing lineage has no transition directly
to active, owned, or effect-capable state.

## Why This Matters

Operational records can protect partial failure without becoming an irreplaceable second source of
truth, but only if their loss has an explicit fail-closed path.

## Acceptance Criteria

- [ ] The MVR owner contract defines a fresh bootstrap epoch and forbids direct activation when
  journal, lease, ownership, or recovery lineage is missing.
  - Verify: `tests/instance/test_mvr_bootstrap_contract.py::test_missing_operational_lineage_requires_fresh_fenced_epoch`
- [ ] Readback sources, conflict outcomes, convergence receipt, and activation preconditions are
  owner-native and explicit; no ownership or prior effect result is invented.
  - Verify: `tests/instance/test_mvr_bootstrap_contract.py::test_bootstrap_contract_requires_authoritative_readback_and_receipt`
- [ ] #2143 and applicable #3863–#3869 contracts are reconciled without a parallel registry,
  journal, supervisor, or recovery Issue chain.
  - Verify: doc writeback at `docs/MULTI_VAULT_RUNTIME/README.md :: Reconciliation — do not duplicate`

## How To Verify Pre-Merge

- `pytest -q tests/instance/test_mvr_bootstrap_contract.py`
- Validate all touched MVR specification links and Issue references.

## Out Of Scope

- Runtime implementation, host operations, backup deletion, or activation of dormant MVR paths.

## Related Docs

- `docs/MULTI_VAULT_RUNTIME/README.md`
- `docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md`

## Related GitHub Issues

Parent #2143 and children #3863–#3869 retain delivery authority.
