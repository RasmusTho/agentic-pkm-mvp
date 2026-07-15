---
name: Demerzel Review And Merge Orchestration
description: Adapt existing review/repair/verification/merge work to the BuilderOps API and outbox.
task_id: BCP-05
source_anchor: docs/BUILDEROPS_CONTROL_PLANE/README.md :: Backlog reconciliation
parent_capability: BuilderOps independent control plane
prerequisites: [BCP-02, BCP-04]
depends_on: [INDEPENDENT_AUTHENTICATED_DEPLOYMENT.md, API_ONLY_CLIENT_CUTOVER.md]
can_parallelize_with: []
existing_issue: 3603
existing_pr: 3620
---

# Demerzel Review And Merge Orchestration

## Purpose

Issue #3603 and PR #3620 already own Demerzel review/repair/verification/merge orchestration,
including authenticated host execution, retries, recovery, idempotent ingest, attempt ledgers, and
verification-gated merge. They currently extend dispatcher SQLite, which ADR-0062 retires as
production authority. This task is the contract delta for that existing work, not a duplicate issue.

## What This Task Does

- rebase/adapt #3603 / PR #3620 orchestration to claim work and persist attempts/results/receipts
  through the BCP-02 API and BCP-01 PostgreSQL/outbox;
- run the privileged executor on Demerzel with host-local model sessions and the narrowest practical
  repo-scoped GitHub credential;
- bind every attempt to `RepoRef`, governing Issue, PR, exact head SHA, workflow/model identity,
  lease/fencing token, and deterministic operation key;
- retain bounded independent review/repair loops and restart recovery from durable API state;
- execute merge only after required CI, local review gate, repository protection, current SHA, and
  scope checks pass;
- reconcile timed-out GitHub operations and record authoritative readback before terminal receipt;
  and
- feed post-merge closure recovery (#3604) from the same receipt/outbox chain.

## Concretely

The existing #3603 consumer claims an API task bound to issue/PR/SHA, runs its bounded reviewer and
repair policy, persists each attempt through the API, and submits a gated merge intent. The outbox
executor reconciles GitHub and commits a readback receipt before completion.

## Why This Matters

This is the high-privilege path and the largest defect blast radius. Reusing its orchestration while
replacing the SQLite ledger avoids both duplicate machinery and a privileged bypass around the new
authority boundary.

## Source Anchors

- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md :: 6. State Machines`
- `docs/AGENT_ISSUE_DISPATCHER.md :: Current-State Honesty`
- `AGENTS.md :: Agency default (minimize human time)`

## SBS Impact

Builder System orchestration work. It exercises repo/GitHub delivery gates but does not own or
weaken them and does not enter Product Runtime.

## Constraints

- Update existing #3603 / PR #3620; do not create a second verification orchestrator.
- The executor is an API client and never opens PostgreSQL/SQLite directly.
- General clients and Product Runtime never receive model or merge credentials.
- A merge receipt binds the exact current SHA and GitHub readback; a local success return is
  insufficient.
- Existing CI + review + protection gates are not weakened by autonomous execution.
- Rate limiting/backoff follows the shared API-budget contract; no tight GraphQL polling.

## Acceptance Criteria

- [ ] The existing verification consumer ingests, claims, heartbeats, records attempts, and resumes
  exclusively through BuilderOps API state, with no dispatcher SQLite ledger.
  Verify: `tests/dispatcher/test_verification_consumer.py::test_consumer_uses_builderops_api_for_durable_state`.
- [ ] Restart after reviewer/repair success does not repeat a committed attempt and resumes unknown
  external effects through reconciliation.
  Verify: `tests/dispatcher/test_verification_recovery.py::test_restart_resumes_from_api_receipts_without_duplicate_attempt`.
- [ ] Merge is rejected for stale SHA, missing required CI/review/protection gate, expired fencing,
  or repo scope mismatch.
  Verify: `tests/dispatcher/test_verification_merge.py::test_merge_requires_current_sha_all_gates_fencing_and_repo_scope`.
- [ ] A timed-out merge reconciles GitHub state before retry and emits one terminal readback receipt.
  Verify: `tests/dispatcher/test_verification_merge.py::test_timed_out_merge_reconciles_before_retry`.
- [ ] Executor credentials are host-local and privileged-scope-only; API/status/logs reveal neither
  token nor model session material.
  Verify: `tests/security/test_builderops_executor_credentials.py::test_executor_secrets_are_scoped_and_redacted`.
- [ ] The delivered flow runs one real/dry-run-safe review→repair/verify→merge-or-no-merge cycle on
  Demerzel and posts its receipt to the parent validation hub.
  Verify: runtime receipt on the BuilderOps control-plane parent issue, bound to issue/PR/SHA.

## Out of Scope

- building another review algorithm or generic agent loop;
- weakening existing verification-and-closure policy;
- MacBook-held merge credentials; and
- final authority cutover/Product route removal.

## How to Verify (Pre-Merge)

- retain and adapt the existing #3603 test suite instead of replacing it;
- test crashes before/after attempt commit, provider result, GitHub call, and readback;
- verify REST-vs-GraphQL budget behavior; and
- run one Demerzel acceptance receipt before BCP-06.

## Related Docs

- issue #3603 / PR #3620
- issue #3224 and issue #3604
- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`
- `docs/BUILDEROPS_CONTROL_PLANE/README.md`

## Related GitHub Issues

- Existing implementation issue #3603 and PR #3620; update rather than create a BCP-05 duplicate.
- Post-merge closure recovery remains issue #3604; parent validation context remains issue #3224.
