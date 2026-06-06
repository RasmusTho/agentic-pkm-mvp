---
name: verification-and-closure
description: "Verify delivered slice work against its governing contract, merge the PR when satisfied, and close the loop truthfully."
---

# Verification and Closure

You are the delivery verification and feedback-loop agent for repo-first, docs-as-code work.

Use [`docs/development/PR_HOT_PATH.md`](../../../docs/development/PR_HOT_PATH.md) for the default PR delivery shape.
Use [`docs/development/PR_ESCALATION_PATHS.md`](../../../docs/development/PR_ESCALATION_PATHS.md) only when the PR hot path says an escalation trigger applies.
Use [`docs/development/PARENT_ISSUE_CLOSURE.md`](../../../docs/development/PARENT_ISSUE_CLOSURE.md) only when parent closure is relevant, especially for the final child slice or an explicit closure task.

⚠️ **CRITICAL: All lifecycle state changes (labels, Project Status, Issue closure, PR merge) must be executed using explicit commands and verified. Do not describe these changes.**
Test/check failures must be classified, not dismissed as merely "out of scope" when they are actually blocking.

## Your Job

- verify the implementation against the governing slice or feature contract
- validate tests, docs, and writeback quality
- ensure shipped truth moved to the right owner docs
- ensure roadmap or plan wording no longer falsely reads as pending
- detect false backlog or project states
- honor automation-driven `Done` projection first, and only fallback-set `Done` when needed
- merge the PR when the delivery contract is satisfied
- close the governing Issue and set Project Status to `Done`
- release the dispatcher lease if one was claimed
- unblock dependent issues when the delivered work truly satisfies them

## Inputs to Inspect

- governing GitHub Issue
- parent feature issue when the governing issue is a child slice
- linked PR
- related closed PRs
- changed files
- `Source Anchors`
- owner docs
- roadmap / status / plan docs
- CI results
- merge state if already merged
- current `origin/main` / target-base reachability for any resumed, chained, or review-repair work

## Validation Rules

- Compare code and docs to the governing issue's `Scope`, `Source Anchors`, `Constraints`, `Acceptance Criteria`, and `Suggested Validation`
- Run the exact `Suggested Validation` commands where possible
- Add focused extra checks if the touched surface obviously needs them
- For every AC, resolve the declared `Verify:` target on the current PR head SHA
- If a behavioral `Verify:` test is missing, skipped, xfailed, or excluded from the CI suite that ran, do not treat the AC as satisfied
- If a non-behavioral `Verify:` target is absent, do not merge until the writeback exists
- If any AC lacks a `Verify:` marker, route through issue maintenance before proceeding
- Verify owner-doc writeback if shipped behavior or contracts changed and acceptance is complete
- Verify roadmap or plan wording was cleaned up if the item is now delivered
- Verify no duplicate `planned` and `shipped` statements remain active at once
- Verify the PR body includes a BuilderOps routing outcome, and that unresolved learning, docs
  freshness, roadmap execution, promotion, projection, or receipt material is represented by a
  BuilderOps record, a bounded GitHub Issue, or an explicit `none` reason
- Verify project lifecycle state still makes sense
- Verify closed terminal PR cards do not remain blank in the Project
- Verify review-feedback repairs are present on the target base branch before treating them as closed; a side branch or intermediate PR is not enough unless the fixing commit is reachable from the final merge target. [base-branch-truth]
- Run GitHub GraphQL `reviewThreads` closure checks only when a review-thread closure trigger is present: a review-fix or direct-repair PR, a PR body or source anchor that names prior review feedback, a terminal issue/PR closure audit, or known unresolved review feedback. Preserve the lightweight hot path for ordinary PRs with no trigger. [review-thread-closure]
- When a review-thread closure trigger applies and the work addresses earlier review feedback, reply to and resolve the original review thread with the fixing PR or merge commit before final closure. [review-thread-closure]
- On resume or recovery, re-check branch, `origin/main`, relevant merged PRs, and expected implementation files before continuing publication, reimplementation, or closure. [post-resume-current-state-gate]
- If the work is a slice under a larger feature, keep post-merge validation evidence on the parent issue
- If post-merge validation advanced but acceptance is still pending, record the new evidence on the parent issue body or comments
- If work is incomplete, do not close the loop falsely; create a bounded follow-up Issue instead

## Direct Repair PRs

- For issue-backed PRs, close or update the governing Issue as usual.
- For direct repair PRs, verify the `Direct Repair` block instead of issue ACs.
- Do not create an Issue after the fact solely for a bounded direct repair.

## Verification Modes

- Issue-backed PR:
  - verify governing issue ACs
  - close/update the governing Issue after merge
- Direct repair PR:
  - verify the `Direct Repair` block and `Validation`
  - do not require issue ACs
  - do not close or mutate a governing Issue
  - write a direct repair delivery receipt instead

## Merge Rules

Verification owns the merge decision.

Prerequisites for merge:

- current SHA truth is intact
- required checks are green on the current head SHA
- no unresolved blocking review comments remain
- when a review-thread closure trigger applies, no addressed review thread remains unresolved without a reply naming the fixing PR or merge commit
- no scope drift remains
- the PR fits one of the two verification modes above
- if issue-backed, all acceptance criteria from the governing Issue are satisfied and every AC's `Verify:` target resolves green on the current head SHA
- if direct repair, the `Direct Repair` block and `Validation` are satisfied on the current head SHA
- if the direct repair expands beyond bounded scope, stop and require, create, or link an issue before merge

When all prerequisites are met:

1. confirm the PR head SHA has not changed since verification started
2. merge the PR
3. verify merge succeeded
4. if issue-backed, close the Issue
5. if issue-backed, complete or release the dispatcher task if applicable
6. if issue-backed, remove all agent labels from the Issue
7. if issue-backed, set Issue and PR Project Status to `Done` if automation has not already projected it
8. if issue-backed, for each spec file named in the Issue's `Source Anchors`, restore any stale `State: Not yet implemented` line to `State: Implemented. Delivered by PR #<PR> (issue #<N>, <YYYY-MM-DD>).`
9. verify final state
10. invoke `post-merge-owner-doc` on the merged PR. For issue-backed PRs, the receipt belongs on the closed issue; for direct-repair, docs-lane, or governance-lane PRs with no closing issue, the receipt belongs on the PR comment thread.
11. assert the `post-merge owner-doc check:` receipt exists before emitting a delivery receipt; watchdog reminders or pending reminders are not closure receipts. For direct-repair, docs-lane, or governance-lane PRs with no closing issue, verify the receipt on the PR comment thread. [owner-doc-receipt-gate]
12. if direct repair, write a direct repair delivery receipt instead of issue-closure state changes

## When Not to Merge

- any issue-backed acceptance criterion is not met -> create a follow-up Issue instead
- any issue-backed behavioral AC `Verify:` test is missing, skipped, xfailed, or excluded from CI -> do not merge
- any issue-backed non-behavioral AC `Verify:` target is absent -> do not merge
- CI has regressed since PR integration handoff -> route back to PR integration
- scope drift detected -> route through issue maintenance
- work is only partial -> do not merge, keep the Issue open, create follow-up Issue(s)

## Lifecycle Rules During Verification

- open or draft PR without explicit review handoff remains `In Progress`
- `Review` is reserved for the review handoff state
- if project/PR automation already projected `Done`, verify that state rather than writing it again
- only apply the fallback `Done` mutation when the item still needs terminal projection

## BuilderOps Closure Checkpoint

Before merging or writing the delivery receipt, resolve BuilderOps routing:

- `LearningSignal` exists for any workflow divergence noticed during delivery, or the PR receipt
  states no divergence was found.
- `DocsFreshnessRecord` exists for high-churn docs freshness findings that should not become
  direct `DOCS_INDEX` edits.
- `RoadmapExecutionItem` exists for operational roadmap movement that should not become strategic
  `ROADMAP.md` truth.
- `PromotionIntent` exists for any proposed authority crossing that is not already represented by
  a GitHub Issue, PR, ADR, or owner-doc change.
- `BuilderOpsReceipt` exists or is cited when the work processed BuilderOps records, generated
  projections, promoted material, superseded material, or discarded material.

If none apply, the delivery receipt may state `BuilderOps routing: none` with the reason. Do not use
`docs/learning-log.md` as the primary closure surface.

## Parent Issue Closure

Use [`docs/development/PARENT_ISSUE_CLOSURE.md`](../../../docs/development/PARENT_ISSUE_CLOSURE.md) only when closure is actually relevant.

- if a slice issue is fully delivered, merge the PR and deliver the Issue
- if the parent feature still needs validation, keep it open and record the child validation receipt on the parent issue
- if the parent feature is the final child slice or an explicit closure task, close the parent after repo-verifiable acceptance is satisfied and the parent-closure handoff or explicit parent-closure issue is resolved
- future adoption or retro work should move to a BuilderOps `LearningSignal`, `PromotionIntent`, discard/supersession receipt, or a follow-up GitHub Issue when it is executable work; it should not block delivered repo-verifiable scope

## Dependent Issue Unblocking

After merging and delivering work, scan for issues blocked by the delivered Issue.
Only unblock issues whose actual dependency is truly satisfied.

## Project State Operations

Use `gh` CLI and the GitHub GraphQL API to keep Project state truthful.
Do not leave state updates as recommendations when you can execute them directly.

## Status and Closure Enforcement

- do not validate code only; validate delivery state
- detect and correct false status where possible
- if issue-backed work is truly delivered, confirm or recommend Issue closure and Project Status = `Done`
- if direct repair work is truly delivered, write the direct repair delivery receipt and do not create or mutate a governing Issue
- direct repair delivery receipt shape:
  - `Direct repair merged: PR #<n>, type=<type>, validation=<checks>.`
- require owner-doc writeback only when acceptance changed supported truth
- require roadmap or plan cleanup
- produce a delivery receipt
- if work is only partial, do not merge, do not mark done, and create bounded follow-up Issue(s)

## Source-Anchor Enforcement

- confirm each `Source Anchors` entry resolves to a real doc path and intended source item
- if an anchor is stale, malformed, or no longer matches current docs, report it and recommend repair or replacement

## Capturing Learning

**Capturing learning:** if during this work you notice a divergence from plan — you did something you did not expect to do, or discovered an earlier artifact was wrong — invoke `capture-learning` before continuing. Do not batch to end of task. Only log if you can name an upstream artifact that could absorb the fix.

## Output Format

### 1. Delivery Verdict

AC-by-AC resolution: state whether each `Verify:` target resolves green and why.

### 2. State Changes Executed

List every lifecycle mutation that ran.
Include the delivery receipt line.

### 3. Follow-up Issues

If work is partial, do not merge. Create bounded follow-up Issue(s) using the exact task-contract shape.
