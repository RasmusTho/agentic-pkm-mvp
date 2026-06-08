---
name: Define Rollback Contract
description: Specify how prod returns to a previous known-good state, including previous-stable resolution, migration reversal, vault immutability, and what rollback does not attempt.
task_id: RELEASE_CHANNELS-06
source_anchor: docs/RELEASE_CHANNELS/README.md :: Rollback posture
parent_capability: RELEASE_CHANNELS
prerequisites: [RELEASE_CHANNELS-01, RELEASE_CHANNELS-02, RELEASE_CHANNELS-04]
depends_on: [DEFINE_CHANNEL_IDENTITY.md, SPLIT_POSTGRES_PER_CHANNEL.md, DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md]
can_parallelize_with: [DEFINE_PROMOTION_PLAN_CONTRACT, DEFINE_CONCURRENCY_RULE]
---

# Define Rollback Contract

## Purpose

Turn rollback from an improvised recovery into a first-class operation. If a promotion fails verification or the operator discovers a regression later, there must be a bounded, previously-specified path back to the prior stable state. This task specifies the contract: what rollback restores, what it cannot restore, and what the operator must acknowledge.

## What This Task Does

This task produces the rollback contract as a docs artifact under `docs/RELEASE_CHANNELS/`. It:

- Specifies the previous-stable resolution rule: the prior `stable` ref is always recoverable.
- Specifies the migration reversal path: reversible migrations reverse in reverse order; forward-only migrations are acknowledged as non-reversing at promotion time.
- States vault immutability: rollback does not rewind the operator's real vault.
- Specifies the runtime-artifact posture: runtime artifacts under the prod channel's directory are regenerated after rollback; they are not restored to a prior snapshot.
- States what rollback explicitly does not do: recover from vault data loss, undo external side-effects (messages sent, files written outside the vault/DB/artifacts scope), or restore lost operator authored content.

## Protected-branch rollback

`origin/stable` is a protected branch (`enforce_admins: true`; required status checks: `smoke`, `smoke-docker`, `pr-contract`; PR required). **Direct pushes and refs-API updates to `stable` are rejected.** This constraint applies equally to rollback: a rollback cannot directly write to the protected `stable` ref.

Rollback under branch protection proceeds as follows:

1. `rollback-promotion` opens a **revert PR** targeting `stable` (reverting the promotion merge commit, or targeting `stable-prev` via a dedicated rollback branch).
2. The revert PR must pass all three required status checks: `smoke`, `smoke-docker`, `pr-contract`.
3. An operator reviews and merges the revert PR. After merge, `origin/stable` points to the protected rollback head. That head may be a merge commit whose tree restores the previous stable state.
4. Prod fetches and checks out the merged `origin/stable` rollback commit before any reversible prod migrations are reversed.
5. The rollback receipt records the revert PR URL, the `stable-prev` target/anchor, and the merged `origin/stable` rollback SHA as ref-restoration evidence.

This contract does **not** promise a direct protected-branch write as a rollback path. Any instruction that would require bypassing branch protection to complete rollback is outside this contract.

## Concretely

- **Previous-stable resolution**: `execute-promotion` records the previous `stable` commit as `stable-prev` (pointer file in `ops/promotions/`). `rollback-promotion` resolves the previous-stable without ambiguity from this record.
- **Ref movement**: rollback restores `stable` through a governed revert PR targeting `stable` (see Protected-branch rollback above). `stable-prev` is the rollback target/anchor, while the prod checkout's HEAD is updated to the merged `origin/stable` rollback commit after the revert PR merges.
- **Migration reversal**: migrations flagged reversible per `DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION` are reversed in the reverse order they were applied, but only after prod is running code from the merged `origin/stable` rollback commit. Migrations flagged forward-only were already acknowledged by the operator at promotion time; rollback does not attempt to reverse them, and the operator understands that the DB shape may not return to its pre-promotion state.
- **Vault**: the real vault is not rewound. The operator's authored content during the promoted period remains intact. Note-level undo is a vault concern.
- **Runtime artifacts**: prod's runtime artifacts (`tmp/`) are allowed to be regenerated; no rollback-specific snapshot/restore of these artifacts is required.
- **External effects**: anything the promoted code caused outside the prod channel's scope (e.g. notifications sent, files written outside the vault/DB/artifacts boundary) is not reversed by rollback. If such side-effects exist, they should be called out as risk notes in the promotion plan.
- **Post-rollback verification**: `verify-promotion` runs after rollback against the restored prod; rollback is not accepted until verification passes.

## Why This Matters

Every release-channel system without a rollback contract eventually becomes a system where rollback is verbally described but never rehearsed. By the time the operator needs it, they are assembling it live during an incident. This contract makes rollback bounded and rehearsable: it states precisely what returns and what does not, so the operator has no surprises during recovery.

## Acceptance Criteria

- [ ] The contract specifies the previous-stable resolution rule.
  Verify: `rg -n "previous-stable|previous stable|stable-prev" docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md`.
- [ ] The contract specifies the migration reversal path, deferring reversibility classification to `DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION`.
  Verify: `rg -n "reverse order|reversal|reversibility|DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION" docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md`.
- [ ] The contract states vault immutability during rollback.
  Verify: `rg -n "vault|immutable|not rewound|not rewind" docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md`.
- [ ] The contract lists what rollback explicitly does not do (external side-effects, vault data loss, lost authored content).
  Verify: `rg -n "does not|external|side-effects|authored content" docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md`.
- [ ] The contract requires `verify-promotion` to pass after rollback before acceptance.
  Verify: `rg -n "verify-promotion|after rollback|not accepted" docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md`.
- [ ] The contract does not prescribe the storage mechanism for previous-stable (tag, pointer, receipt file) but requires one.
  Verify: doc review; spec names three candidate shapes without mandating one.

## How to Verify (Pre-Merge)

- Confirm the rollback contract and the promotion contract reference each other consistently.
- Confirm forward-only migrations are handled honestly: rollback does not promise what it cannot deliver.
- Confirm vault immutability is stated without exceptions.

## Out of Scope

- Implementing the `rollback-promotion` skill (governance-lane follow-up).
- Vault-level undo or history restoration.
- Recovery from external-system side-effects.
- Disaster-recovery posture beyond the release-channel scope.

## Related Docs

- [docs/RELEASE_CHANNELS/README.md](README.md) :: Rollback posture
- [docs/RELEASE_CHANNELS/DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md](DEFINE_MIGRATION_REVERSIBILITY_CLASSIFICATION.md)
- [docs/RELEASE_CHANNELS/DEFINE_PROMOTION_PLAN_CONTRACT.md](DEFINE_PROMOTION_PLAN_CONTRACT.md)

## Related GitHub Issues

When promoted: "Implements RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT." Follow-up: the `rollback-promotion` skill authors the operational sequence; that is governance-lane work.
