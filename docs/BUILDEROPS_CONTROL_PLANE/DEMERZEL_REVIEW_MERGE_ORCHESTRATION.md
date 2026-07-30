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
existing_pr_status: merged
---

# Demerzel Review And Merge Orchestration

## Purpose

Issue #3603 owns Demerzel review/repair/verification/merge orchestration. PR #3620 merged on
2026-07-15 and delivers the repo-side consumer, retries, recovery, idempotent ingest, attempt ledger,
and verification-gated merge baseline; later correctness repairs are also on `main`. That baseline
extends dispatcher SQLite, which ADR-0062 retires as production authority. This task is the migration
delta for delivered work, not a duplicate orchestrator and not a request to reopen the merged PR.
The repo-side API/PostgreSQL/outbox adapter and privileged merge-effect fence are now implemented;
the installed-main Demerzel cycle and its parent-hub receipt remain the final acceptance gate.

## What This Task Does

- migrate the delivered #3603 / PR #3620 orchestration so claims and attempt/result/receipt state
  pass through the BCP-02 API and BCP-01 PostgreSQL/outbox;
- run the privileged executor on Demerzel with host-local model sessions and the narrowest practical
  repo-scoped GitHub credential;
- bind every attempt to `RepoRef`, governing Issue, PR, exact head SHA, workflow/model identity,
  lease/fencing token, and deterministic operation key;
- independently load the delivery manifest from the target repository's protected default branch/
  base SHA, bind its hash to the attempt/head, and select only the host credential mapping authorized
  for that `RepoRef`;
- bind the privileged effect to a GitHub-enforced protected-base/manifest conditional or merge-queue
  fence so policy changes after final validation invalidate the attempt instead of racing the merge;
- retain bounded independent review/repair loops and restart recovery from durable API state;
- execute merge only after required CI, local review gate, repository protection, current SHA, and
  scope checks pass;
- reconcile timed-out GitHub operations and record authoritative readback before terminal receipt;
  and
- feed post-merge closure recovery (#3604) from the same receipt/outbox chain.

## Concretely

The delivered #3603 consumer is retained, but its dispatcher store port is replaced by an API client.
It claims a task bound to issue/PR/SHA, runs its bounded reviewer and repair policy without ambient
GitHub write credentials, persists each attempt through the API, and commits a distinct exact-head
`verified`/merge-ready receipt. The host executor then re-resolves protected-base repo policy plus
host credential mapping, binds a GitHub-enforced authorization fence over protected-base OID +
manifest blob/hash + PR head OID + `RepoRef` + credential generation, and submits the task-bound
merge intent through the repo's conditional or merge-queue path. The outbox executor reconciles
GitHub (including process-loss recovery) and commits a readback receipt before completion.

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

- Keep #3603 as the governing workstream and PR #3620 as immutable delivered history. Land the
  storage/client migration in later bounded PR work after BCP-02/04; do not create a second
  verification orchestrator or rewrite the merged PR.
- The executor is an API client and never opens PostgreSQL/SQLite directly.
- Before a GitHub/model call, the executor commits a fenced pre-effect attempt/receipt in the local
  PostgreSQL authority; the local commit is the eligibility gate (ADR-0062 A1). An uncommitted
  attempt leaves the external system untouched.
- General clients and Product Runtime never receive model or merge credentials.
- The executor resolves GitHub/model credentials from host-secret references at effect time. Raw
  material never enters API requests, PostgreSQL, outbox payloads, receipts, artifacts, logs, or
  backups.
- Client-supplied delivery policy/routing is advisory. Immediately before privileged execution, the
  executor resolves the manifest from the protected default branch/base SHA, binds manifest hash +
  base/head SHA + `RepoRef`, and rejects any host credential mapping or requested action outside
  that repo policy.
- The GitHub effect itself must be conditional on the same protected-base OID and manifest blob/hash,
  or run through a merge queue/merge group that revalidates the fence and repository gates against
  its queue-selected base. If the base/manifest changes after final validation or while the
  pre-effect attempt becomes durable, GitHub must reject/invalidate the attempt; without an enforced
  conditional/queue path, direct merge fails closed.
- A merge receipt binds the exact current SHA and GitHub readback; a local success return is
  insufficient.
- Existing CI + review + protection gates are not weakened by autonomous execution.
- Rate limiting/backoff follows the shared API-budget contract; no tight GraphQL polling.

## Acceptance Criteria

- [x] The existing verification consumer ingests, claims, heartbeats, records attempts, and resumes
  exclusively through BuilderOps API state, with no dispatcher SQLite ledger.
  Verify: `tests/dispatcher/test_verification_consumer.py::test_consumer_uses_builderops_api_for_durable_state`.
- [x] Restart after reviewer/repair success does not repeat a committed attempt and resumes unknown
  external effects through reconciliation.
  Verify: `tests/dispatcher/test_verification_recovery.py::test_restart_resumes_from_api_receipts_without_duplicate_attempt`.
- [x] External-effect eligibility is the locally committed fenced pre-effect attempt (ADR-0062 A1):
  an uncommitted attempt performs no GitHub/model call, and a crash between claim and attempt-commit
  leaves the external system untouched.
  Verify: `tests/dispatcher/test_verification_recovery.py::test_fenced_attempt_commit_gates_external_effect`.
- [x] Merge is rejected for stale SHA, missing required CI/review/protection gate, expired fencing,
  repo scope mismatch, client-vs-protected manifest mismatch, stale base/manifest hash, or host
  credential mapping outside the target `RepoRef` policy.
  Verify: `tests/dispatcher/test_verification_merge.py::test_merge_revalidates_protected_manifest_and_repo_credential_binding`.
- [x] Advancing the protected base or changing/revoking its delivery manifest after final validation
  but before the external effect invalidates the GitHub conditional/merge-group authorization fence
  and performs no merge; a new attempt requires fresh policy, credential, and gate validation.
  Verify: `tests/dispatcher/test_verification_merge.py::test_merge_rejects_base_or_manifest_change_after_final_validation`.
- [x] A timed-out merge reconciles GitHub state before retry and emits one terminal readback receipt.
  Verify: `tests/dispatcher/test_verification_merge.py::test_timed_out_merge_reconciles_before_retry`.
- [x] Executor credentials are host-local and privileged-scope-only; API/status/logs and all durable
  state/backups contain only non-secret references/scope metadata, never token or model session
  material.
  Verify: `tests/security/test_builderops_executor_credentials.py::test_executor_secrets_are_referenced_not_persisted`.
- [ ] The delivered flow runs one real/dry-run-safe review→repair/verify→merge-or-no-merge cycle on
  Demerzel and posts its receipt to the parent validation hub.
  Verify: runtime receipt on the BuilderOps control-plane parent issue, bound to issue/PR/SHA.

## Out of Scope

- building another review algorithm or generic agent loop;
- weakening existing verification-and-closure policy;
- MacBook-held merge credentials; and
- final authority cutover/Product route removal.

## How to Verify (Pre-Merge)

- retain and migrate the existing #3603/#3620 test suite instead of replacing it;
- test crashes before/after attempt commit, provider result, GitHub call, and readback;
- verify REST-vs-GraphQL budget behavior; and
- run one Demerzel acceptance receipt before BCP-06.

## Related Docs

- issue #3603 / merged PR #3620
- issue #3224 and issue #3604
- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`
- `docs/BUILDEROPS_CONTROL_PLANE/README.md`

## Related GitHub Issues

- Existing implementation issue #3603 and merged PR #3620; keep the issue as the migration and host
  acceptance workstream rather than creating a BCP-05 duplicate or rewriting the merged PR.
- Post-merge closure recovery remains issue #3604; parent validation context remains issue #3224.
