---
name: verification-and-closure
description: "Verify coverage, merge the current candidate, and reconcile its exact delivery scope."
---

# Verification and Closure

This skill declares `execution_selection_intent: verification`. It owns merge and delivery closure,
not deployment. User authority, exact scope, current-head checks, and truthful effects remain gates.

## Routing

Choose once, before collecting evidence:

- **Native delivery:** an interactive Builder session owns the PR, with no dispatched executor,
  authenticated verified-merge attempt, or release operation in progress. Applies to issue-free,
  single-Issue, and approved bounded multi-Issue PRs. Review depth is independent of merge mechanics.
- **Executor/in-flight delivery:** a dispatched verification context or host-fenced executor owns
  the effects, a verified-merge authority/phase receipt already exists, the governing contract
  explicitly requires that protocol, or this is a release/promotion operation. Read
  `.codex/skills/verification-and-closure/FULL_PATH.md :: Merge Rules` and the conditional sections relevant to that execution. Never
  switch an in-flight attempt to native delivery to escape a refusal.

`scripts/closure.py plan/apply` still supports only its existing single-Issue Tier 1/2,
`Final-Review-Rounds: 0` subset. Its refusal is not permission to bypass it; choose the applicable
route before invoking it. Other native deliveries use the procedure below. A generated dispatch
artifact is not a transfer of ownership; do not enqueue it for a session-owned native delivery.

## Inputs

Read the live PR identity, base, head, title/body, complete changed-file list, checks, and actionable
review feedback once. Read the governing contract and exact closing Issues; use an existing scoped
context when still current. A governing parent not in the closing set stays open. Issue-free work
uses the PR's lane or Direct Repair contract. Do not create an Issue after the fact solely for a
bounded direct repair. Compare source anchors and scope; stop on ambiguous authority.

Apply `_shared/BLOCKER_ACTION_CONTRACT.md` only when blocker/action labels need reconciliation.
Apply `.codex/skills/_shared/BRANCH_TRUTH_GATE.md :: Procedure` before publication effects.

## Validation

- Resolve every AC's `Verify:` target from applicable existing results. Use
  `docs/development/GOVERNANCE_PROPORTIONALITY.md :: Evidence reuse and stop rule`.
- Missing, failed, skipped, xfailed, or excluded required tests do not satisfy an AC. Missing required
  doc writeback does not satisfy it either. Run the missing or affected checks, not the whole
  implementation validation again. Required current-head CI cannot be replaced by local evidence.
- Confirm scope, Builder/Product ownership, owner-doc writeback and acceptance claims. Do this once
  and retain the inspected paths and conclusion in the PR's existing Validation section.
- If acceptance requires a post-merge producer, keep its parent or explicit acceptance Issue open;
  do not pretend a pre-merge test proves the later outcome.
- For pre-API startup failures, read `.codex/skills/verification-and-closure/FULL_PATH.md :: Pre-API startup failure classification`.
- For a resumed run or owner handoff, read `.codex/skills/verification-and-closure/FULL_PATH.md :: Current SHA truth and scope drift`.

## Review

Tier 1/2 defaults to self-review and `Final-Review-Rounds: 0`. High-risk changes or an explicit review
request require one independent current-head review and `Final-Review-Rounds: 1`; read
`.codex/skills/verification-and-closure/FULL_PATH.md :: Running the local review gate 🤖`, `:: Severity routing`, and
`:: Re-triggering after a fix` for that review only. These reads do not select executor merge
mechanics. Keep P0/P1 repairs and fresh independent review mandatory. P2 needs a durable defect
reference in rolling Known Defects registry Issue #4172 and disposition; P3 is informational. No second consecutive clean review is required.

After two independent change-request rounds apply
`docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md :: PR-Level Scope Revalidation Gate`.

When prior review threads are implicated, retain their original IDs, disposition each finding,
and re-read those same threads before terminal closure. Do not scan unrelated historical reviews.

## Native merge procedure

1. Confirm the exact closing set and all its ACs, current head, relevant required/repo-standard CI,
   review disposition, and owner-doc conclusion. Approved multi-Issue work must satisfy
   `docs/development/PR_HOT_PATH.md :: Multi-Issue PR Scope`; Issue count alone adds no review round.
2. Immediately before merge, refresh head/base/title/body and GitHub closing references. Compare
   with the inspected authority and exact closing set; reject unexpected refs, scope, or head drift.
   Inspect commit messages for unintended closing keywords. On drift, stop the effect and resolve
   only the affected evidence. Never mutate or neutralize the body to manufacture readiness.
3. Merge using an expected-head guard, for example `gh pr merge <PR> --squash --match-head-commit
   <verified-sha> --subject <non-closing-title> --body <non-closing-summary>`. Do not use admin bypass.
   Native GitHub closing keywords close the declared fully delivered Issues. This route accepts
   GitHub's native PR-body authority model; use the executor path when the contract needs stronger
   cross-surface fencing or independent closure authority.
4. Read back the merge result and each exact closing Issue. Confirm the merged candidate, merge
   SHA and closure attribution. An API success or green checks alone do not prove delivery. If
   an Issue remains open, diagnose the native closure result before any explicitly scoped repair.
   Preserve an open governing parent. Do not close newly discovered or partially delivered Issues.
5. Remove terminal agent/action labels and complete the active dispatcher lease, if any. Repair
   Project projection only when explicitly in scope. Check only known dependent Issues; a backlog
   scan is a separate maintenance task.
6. Reuse the owner-doc assessment when the merged change matches the assessed candidate; invoke
   `post-merge-owner-doc :: Reuse an existing assessment`. Preserve the existing PR-specific receipt
   prefix on every exact closed Issue and distinct open governing parent, or the PR if issue-free.
7. Report the result in 2–4 sentences with one receipt/link: PR, merged SHA, checks, scope, and any
   remaining acceptance. Store logs and structured evidence in existing artifacts; do not paste
   another copy into chat or repeat an AC-by-AC table already recorded on the PR.

## Stop and recovery

A failed gate stops its effect, not authorized diagnosis and repair. Follow
`docs/development/GOVERNANCE_PROPORTIONALITY.md :: Delivery budgets and stop-loss`. Do not waive a
required check, unresolved protected finding, scope boundary, or operator gate to save tokens.
For a parent acceptance decision read `docs/development/PARENT_ISSUE_CLOSURE.md`; for executor
recovery stay in `FULL_PATH.md`. Do not invoke an independent reviewer, owner-doc re-audit, new Issue,
or full suite merely because the previous stage finished.

## Workflow continuation

Follow `.codex/skills/README.md :: Workflow continuation` through observed merge and reconciliation.
Invoke `klart` once at session closeout. Queued work and a verification verdict are intermediate.
