---
name: Dispatch And Reconcile Post-Merge Closure
description: Turn merged PRs into idempotent closure cases and recover missed or partial terminal work.
task_id: AVC-01
github_issue: 3604
source_anchor: docs/AUTONOMOUS_PR_CLOSURE/README.md :: Post-merge reconciliation and orphan recovery
parent_capability: Autonomous PR verification and closure
prerequisites: [BCP-05]
depends_on: [../BUILDEROPS_CONTROL_PLANE/DEMERZEL_REVIEW_MERGE_ORCHESTRATION.md]
can_parallelize_with: []
---

# Dispatch and reconcile post-merge closure

## Purpose

Merge is not a terminal delivery event. This task reuses #3604 to turn each merged PR into a single
durable closure case and recover cases left part-complete by an interrupted coordinator or a merge
outside the verifier.

## What This Task Does

Define the artifact-only merge dispatch and bounded cursor-aware reconciliation path, then extend
the existing #3603 consumer to handle `stage=closure`. It derives pending work from current terminal
evidence, runs only still-missing `verification-and-closure` steps, and records a terminal
readback/receipt or one concrete governed block.

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

- Pre-merge consumer migration/authority, owned by canonical BCP-05 / #3603.
- Source-code repair, a second closure policy or queue, CI mutation, API-key fallback, Product/Runtime
  deployment, or changing the two currently open docs-only PRs.

## Related Docs

- [Capability README](README.md)
- `docs/AGENT_ISSUE_DISPATCHER.md :: Verification dispatch consumer`
- `docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md :: Closure Eligibility`
- `.codex/skills/verification-and-closure/SKILL.md`

## Related GitHub Issues

- Existing implementation contract: [#3604](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3604)
- Existing prerequisite: [#3603](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3603)
- Existing validation hub: [#3224](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3224)
