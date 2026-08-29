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
against its ChannelManifest, binds the runner report and migration set to that exact candidate, and
emits one durable terminal receipt for an exact attempt. `python -m app.release_channels.promotion_receipt
validate-prod-activation ...` accepts only a current, unrevoked PASS whose
artifact/config/test/vault/schema identities match. The second command only returns admission
evidence with state `validated_not_activated`; it performs no activation. P5 owns the future
side-effecting caller and must invoke this boundary immediately before activation.

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
