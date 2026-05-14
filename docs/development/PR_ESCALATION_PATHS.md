State: Development reference. Escalation-only PR workflow reference.
Doc role: Escalation reference
Authority: Conditional procedures for PR delivery. Do not read or execute these sections unless `PR_HOT_PATH.md` says a trigger applies.
Owner: Builder-agent governance
Temporal class: operational

# PR Escalation Paths

This document exists to keep the default PR hot path short.
Do not read or execute these sections unless a trigger in [`PR_HOT_PATH.md`](PR_HOT_PATH.md) applies.

## 1) CI Failure Investigation

Use when a required check fails, is missing on the current head SHA, or is stale.

- caused-by-PR -> fix the code, config, or test, then rerun the relevant checks before merge
- pre-existing-with-evidence -> link the follow-up, record the waiver or receipt, and do not claim the failure as resolved by this PR
- unresolved -> block merge

If a pytest failure mentions an unavailable plugin flag, treat that as a check-loading issue only when the PR actually touches the pytest invocation and the plugin is part of the expected environment.

## 2) Merge-Ref Validation

Use after a review-fix push when CI may differ on the GitHub merge ref.

- fetch `refs/pull/<PR>/merge`
- inspect the touched symbols in the merge ref, not only the branch head
- run at least one targeted smoke or regression test against a temporary worktree for the merge ref
- if the merge ref fails, do not declare `ready-for-verification`

## 3) Branch Drift Recovery

Use when local HEAD, the tracked remote branch, and the PR head SHA do not match, or when the active worktree is not the PR worktree.

- stop committing until branch truth is restored
- isolate unrelated local drift explicitly
- preserve any necessary backup state before re-pointing the PR branch
- re-check branch, worktree, and SHA truth before any new push

## 4) Dependency Issue Scan

Use after merge or after verification when the delivered work unblocks other issues.

- scan for issues that explicitly depend on the delivered issue
- remove `agent:blocked` and add `agent:ready` only when the dependency is truly satisfied
- do not unblock issues whose real dependency is still missing

## 5) Owner-Doc Check

Use after merge when shipped behavior, contracts, or architecture may have changed owner-doc truth.

- run the post-merge owner-doc check on the merged PR
- if the wording change is clear, open a docs-only PR
- if wording needs judgment, open one bounded follow-up issue
- if no owner-doc change is implied, leave the no-change receipt

## 6) Heavy Review / Comment Loop

Use when review feedback is blocking, repetitive, or clearly requires more than a quick hot-path reply.

- classify the feedback first
- blocking regression risk -> fix before merge
- valid non-blocking improvement -> fix if cheap, otherwise follow up
- out-of-scope -> short response only
- incorrect or not applicable -> short response only
- if the loop keeps expanding, stop and classify the PR as blocked rather than dragging the hot path into a governance cycle

## 7) GitHub Project / Board Cleanup

Use when lifecycle state is truthful in GitHub content but the board projection is stale.

- correct terminal work to `Done`
- correct open work to the state implied by its current labels and PR state
- do not treat board cleanup as a reason to block a delivered PR if the delivery itself is sound

## 8) Full Governance Receipt Repair

Use when the delivery trail is incomplete, stale, or contradictory.

- repair issue/PR traceability
- repair missing or stale receipts
- route terminal closure work through verification-and-closure or issue maintenance instead of padding the hot path
