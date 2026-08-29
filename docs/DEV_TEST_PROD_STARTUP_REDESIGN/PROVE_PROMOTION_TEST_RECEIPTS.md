---
name: Prove Promotion-Test Receipts
description: Produce and validate durable content-addressed PASS or FAIL receipts for exact promotion candidates.
task_id: STARTUP-04
github_issue: 4917
source_anchor: docs/DEV_TEST_PROD_STARTUP_REDESIGN/README.md :: Verification and acceptance
parent_capability: DEV_TEST_PROD_STARTUP_REDESIGN
prerequisites: [STARTUP-01, STARTUP-02, STARTUP-03]
depends_on: [FREEZE_CHANNEL_MANIFEST_AND_OPERATION_CONTRACT.md, BUILD_IMMUTABLE_ARTIFACT_GRAPH.md, IMPLEMENT_READ_ONLY_ORDINARY_BOOT.md]
can_parallelize_with: []
---

State: Implemented in the repository by issue #4917. This state covers the receipt writer and
prod admission validator only; no promotion-test run, prod promotion, activation, or owner
acceptance is claimed.

# Prove Promotion-Test Receipts

## Purpose

Make test a first-class promotion gate and make prod receipt validation deterministic.

## What This Task Does

Runs one exact digest against the declared prod-compatible baseline; records migration journal, readiness/version/UI/smoke checks, and a durable content-addressed PASS/FAIL receipt outside resettable test volumes. Prod rejects absent, stale, revoked, or mismatched receipts.

## Concretely

`python -m app.release_channels.promotion_receipt promotion-test-verify ...` validates a P2 render
against its ChannelManifest, verifies an independently provisioned issuer trust root, derives the
complete migration delta from the prod-admission baseline and candidate Git objects, binds the
runner report and classified delta to that exact candidate, and emits one durable terminal receipt
for an exact attempt. The writer may add an issued receipt entry to the existing registry but never
creates that registry or enrolls a caller-supplied trusted key. Registry issue and revocation writes
are serialized through the receipt-store writer lock; revocation uses
`revoke_promotion_test_receipt(...)` and never edits `registry.json` directly. `python -m app.release_channels.promotion_receipt
validate-prod-activation ...` accepts only a current, unrevoked PASS whose
artifact/config/test/vault/schema identities match. It requires the exact check report and compares
its canonical digest, migration-set identity, and migration baseline to the signed v2 receipt; the
baseline must match the fixed canonical repository's authoritative current promotion ref
(`refs/heads/main`, exposed locally as `origin/main` in the current interim model) and the
independently supplied prod-admission context. The second command only returns admission
evidence with state `validated_not_activated`; it performs no activation. P5 owns the future
side-effecting caller and must invoke this boundary immediately before activation.

## Mechanism Convergence Contract

The protected invariant is: a receipt can authorize only the exact signed candidate, migration
delta, check report, and current canonical prod baseline, and a revoked receipt can never be
re-issued by a racing writer.

- Baseline authority is fetched fresh for every binding from the fixed repository URL and
  `refs/heads/main`. Git configuration, replace refs, object overlays, and interactive transport
  settings are removed from the child environment. The caller-selected source repository supplies
  only immutable candidate objects; it cannot select the baseline.
- Valid terminal states are `PASS` and `FAIL`; an issued registry entry may transition once to
  `revoked`. Receipt, attempt, reservation, and registry records are durable before the final
  registry issue boundary. Replays of the same attempt are idempotent; conflicting or revoked
  records fail closed.
- The receipt-store `.writer.lock` serializes every registry writer. Issue, revoke, crash recovery,
  and retry all re-read and validate the registry while holding that lock, then replace and fsync
  the canonical file before releasing it. The prod validator is read-only and accepts only an
  issued entry with a valid signature and matching identities.

Focused proof matrix:

| Invariant / transition | Proof |
| --- | --- |
| Fresh canonical baseline and sanitized Git authority | `tests/runtime/test_startup_artifact_call_sites.py::test_authoritative_baseline_fetch_is_fresh_and_ignores_git_config` |
| Candidate cannot masquerade as the prod baseline | `tests/runtime/test_startup_artifact_call_sites.py::test_promotion_test_rejects_candidate_as_prod_migration_baseline` |
| Complete baseline-to-candidate migration delta | `tests/runtime/test_startup_artifact_call_sites.py::test_promotion_test_derives_complete_migration_delta_from_candidate_git` |
| Issue and revoke cannot lose one another's registry update | `tests/runtime/test_startup_artifact_call_sites.py::test_promotion_registry_serializes_issue_and_revocation_updates` |
| Crash/restart recovery at reservation, receipt, attempt, and registry boundaries | `tests/runtime/test_startup_artifact_call_sites.py::test_promotion_test_recovers_linked_temp_before_terminal_success` and adjacent terminal-binding tests |
| Missing, stale, revoked, mismatched, and non-PASS admission | `tests/runtime/test_startup_artifact_call_sites.py::test_prod_receipt_validator_is_invoked_before_activation` |

## Why This Matters

A healthy local test does not authorize a different prod artifact or configuration.

## Acceptance Criteria

- [x] Receipt validation rejects each missing, stale, revoked, digest/config/test/schema mismatch. Verify: `tests/runtime/test_startup_artifact_call_sites.py::test_prod_receipt_validator_is_invoked_before_activation`.
- [x] PASS and FAIL are both durable terminal evidence outside resettable test volumes. Verify: `tests/runtime/test_startup_artifact_call_sites.py::test_promotion_test_writes_one_durable_terminal_receipt`.

## How to Verify (Pre-Merge)

Replace strict-xfail skeletons and run receipt fixture plus runtime-path tests.

## Out of Scope

Production activation or accepting an emergency bypass as a normal receipt.

## Related Docs

`docs/RELEASE_CHANNELS/README.md`.

## Related GitHub Issues

Filed ownership: #4917 (P4), under parent validation hub #4913. The parent/child overlap was resolved before filing; this task owns durable promotion-test receipt proof for the newer chain.
