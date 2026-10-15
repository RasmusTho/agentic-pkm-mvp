---
name: Dispatch And Reconcile Post-Merge Closure
description: Turn merged PRs into idempotent closure cases and recover missed or partial terminal work.
task_id: AVC-01
github_issue: 3604
source_anchor: docs/AUTONOMOUS_PR_CLOSURE/README.md :: Post-merge reconciliation and orphan recovery
parent_capability: Autonomous PR verification and closure
prerequisites: ["consumer/pilot: VM102 qualification and canonical-writer cutover evidence"]
depends_on: [../BUILDEROPS_CONTROL_PLANE/INDEPENDENT_AUTHENTICATED_DEPLOYMENT.md]
can_parallelize_with: []
---

# Dispatch and reconcile post-merge closure

## Purpose

Merge is not a terminal delivery event. This task reuses #3604 to turn each merged PR into a single
durable closure case and recover cases left part-complete by an interrupted coordinator or a merge
outside the verifier.

## What This Task Does

Deliver two separable boundaries under #3604: an artifact-only merge/reconciliation producer,
then a credentialed VM102 consumer for `stage=closure`. #3603 closed topology reconciliation only;
it did not deliver an admitted host consumer. The producer does not need that consumer to emit
inert requests. Consumer activation and pilot acceptance still require exact runtime evidence.

## Concretely

For `repository + PR + merge SHA + closure stage`, event delivery and scheduled recovery collapse
to one case. The closer re-fetches exact merge and Issue authority, receipt, label, parent,
owner-document, and optional Project evidence. It may close only the authenticated Issue set in the
existing closure sequence; terminal lane release requires the required owner-document receipt. A
replay of completed state makes no GitHub write.

## Why This Matters

Without this task, the interval after a merge still depends on someone remembering to close Issues,
clear claims, prove owner-document disposition, and repair residue. It is also the only safe route
to recover an orphaned merge without treating CI green or an old comment as closure authority.

## Artifact-only producer slice

This is the bounded repository-executable subset authorized by #3604's 2026-09-28 maintenance
receipt. A child Issue may implement it after this source contract merges; it must leave the
remaining #3604 acceptance open.

- Add a deterministic `closure_dispatch_request.v1` builder keyed by repository, PR number,
  exact merge SHA, `closure` stage and contract version, with a bounded link to the existing
  post-merge docs classification. Event and recovery builders use the identical identity.
- Extend `.github/workflows/post-merge-docs-classifier.yml` or add the smallest companion merged-PR
  artifact workflow. Enumerate that entrypoint and the scheduled/manual reconciliation workflow
  in the child. Merged PRs emit requests; closed-unmerged PRs emit none. No consumer is invoked.
- Implement `merged_closure_pending` as a deterministic read-only classifier over explicit
  PR/Issue/label/receipt evidence and supplied authoritative dispatcher/Project evidence when
  applicable. Missing, unavailable or conflicting evidence is unknown/pending, never proof of
  completion. Actions must not impersonate private host evidence or provision access to it.
- Add bounded scheduled and `workflow_dispatch` recovery with a finite lookback/page/request cap,
  a validated cursor/window, and REST backoff. Missing/invalid cursor state cannot expand into an
  unbounded scan; overflow must be reported and resumed within the declared bounds. Reuse existing
  artifact/cursor conventions; no new queue, task store, registry or lifecycle authority.
- Actions use only the read permissions and artifact upload needed for this work. They must not
  close Issues, edit labels/Projects, write comments, push branches, invoke agents/models, use SSH,
  load subscription credentials, or mark a delivery terminal. Replay may emit the same identity;
  durable claim/run deduplication remains the consumer's responsibility.
- Preserve the existing post-merge classifier/watchdog/owner-doc decisions. The producer adds a
  request and read-only recovery evidence, not a second closure policy or watchdog.

Producer acceptance is repo-verifiable with these committed test commitments:

- Verify: `tests/governance/test_closure_dispatch_request.py::test_schema_and_merge_idempotency_are_deterministic`
- Verify: `tests/governance/test_post_merge_closure_dispatch_workflow.py::test_only_merged_pr_emits_linked_closure_request`
- Verify: `tests/governance/test_post_merge_closure_dispatch_workflow.py::test_workflows_are_artifact_only_and_least_privilege`
- Verify: `tests/governance/test_closure_pending_classifier.py::test_pending_and_terminal_cases_are_classified_from_evidence`
- Verify: `tests/governance/test_closure_pending_classifier.py::test_missing_or_conflicting_evidence_cannot_prove_terminal`
- Verify: `tests/governance/test_post_merge_closure_reconciliation.py::test_bounded_recovery_rediscovers_orphaned_merge`
- Verify: `tests/governance/test_post_merge_closure_reconciliation.py::test_cursor_overflow_and_backoff_preserve_scan_bounds`

## Delivered repository producer

The repository producer is implemented by
`.github/workflows/post-merge-closure-dispatch.yml`,
`.github/workflows/post-merge-closure-reconcile.yml`,
`scripts/build_closure_dispatch_request.py`, and
`scripts/reconcile_post_merge_closure.py`. The event path consumes the existing
post-merge docs classification and emits an inert `closure_dispatch_request.v1` artifact for a
merged PR. The scheduled/manual path scans a finite closed-PR window and preserves a validated
continuation cursor when the page or request cap is reached. Both paths have read-only GitHub
permissions and upload artifacts only; they do not invoke the VM102 consumer or mutate Issues,
labels, Projects, comments, branches, or delivery state.

The request identity is `repository + PR number + exact merge SHA + closure stage + contract
version`. Event and recovery requests therefore converge on the same idempotency key. The
classifier keeps missing, unavailable, or conflicting terminal evidence pending. The producer
does not establish the VM102 consumer, durable consumer deduplication, owner-doc terminal receipt,
lane release, or the governed live pilot/replay; those remain open acceptance gates on #3604.

## VM102 consumer and remaining acceptance

The separate consumer target is VM102 (`bob-1`, guest identity `builder-system`), subject to #5181's
complete candidate/source/model/system qualification and operator gates and #3793's canonical-writer
no-fallback cutover. #5056 bounded component activation does not qualify the executor. Preserve
`forced_login_method = "chatgpt"`, keyring credential storage, `codex login status` preflight,
`codex exec --json --sandbox workspace-write --output-schema`, and no copying/logging auth files.
Subscription exhaustion keeps one durable pending request with bounded backoff; no API-key/provider
fallback or duplicate active chain is allowed.

Reuse existing BuilderOps API/PostgreSQL/outbox claim, fencing and receipt authority. #4897 owns
post-effect recovery, v2 phase and watchdog authority; #4893 owns native single-closer integration.
#3604 consumes their exact evidence and does not rebuild those mechanisms. Its full consumer,
terminal owner-doc receipt, active-delivery lane release and governed pilot/replay criteria remain
incomplete until verified; an artifact-only child cannot close #3604.

## Acceptance Criteria

- [ ] Merged PR event and recovery paths produce the same deterministic closure request identity;
  closed-unmerged PRs produce none.
  - Verify: `tests/governance/test_post_merge_closure_dispatch_workflow.py::test_only_merged_pr_emits_linked_closure_request`
- [ ] `merged_closure_pending` is derived from live terminal evidence and excludes already complete
  direct-repair/Issue cases.
  - Verify: `tests/governance/test_closure_pending_classifier.py::test_pending_and_terminal_cases_are_classified_from_evidence`
- [ ] Event and scheduled recovery requests collapse to one durable case and terminal receipt.
  - Verify: `tests/dispatcher/test_closure_dispatch.py::test_event_and_recovery_requests_are_idempotent`
- [ ] The closure consumer re-fetches live truth, performs only missing authorized steps, and a
  completed replay makes zero GitHub mutations.
  - Verify: `tests/dispatcher/test_closure_consumer.py::test_terminal_repair_is_stepwise_and_replay_is_noop`
- [ ] Missing or ambiguous authority produces exactly one governed block/Human Exception packet;
  it never fabricates terminal success.
  - Verify: `tests/dispatcher/test_closure_consumer.py::test_ambiguous_or_partial_truth_routes_one_owner_decision`
- [ ] A pilot proves merge through terminal lifecycle/owner-document receipt and a replay no-op.
  - Verify: runtime receipt: `autonomous_pr_closure_pilot.v1`

## How to Verify (Pre-Merge)

- Run #3604's request/workflow/classifier/reconciliation tests and the named dispatcher tests.
- Exercise missed-event, crash-after-merge, duplicate-event, subscription-backoff, owner-document
  missing, conflicting closure-authority, and completed-replay fixtures.
- On the governed pilot, record the exact PR and merge SHA, request/case/receipt identities,
  lifecycle readback, owner-document result, and duplicate-free replay on #3604 and #3224.

## Out of Scope

- Pre-merge topology reconciliation already recorded by #3603; executor qualification belongs to
  #5181 and canonical-writer cutover to #3793.
- Source-code repair, a second closure policy or queue, CI mutation, API-key fallback, Product/Runtime
  deployment or unrelated PR changes.

## Related Docs

- [Capability README](README.md)
- `docs/AGENT_ISSUE_DISPATCHER.md :: Verification dispatch consumer`
- `docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md :: Closure Eligibility`
- `.codex/skills/verification-and-closure/SKILL.md`

## Related GitHub Issues

- Existing implementation contract: [#3604](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3604)
- Existing prerequisite: [#3603](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3603)
- Existing validation hub: [#3224](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3224)
