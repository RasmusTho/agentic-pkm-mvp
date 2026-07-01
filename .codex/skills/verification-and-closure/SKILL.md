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
- `docs/architecture/SBS_OPERATING_MODEL.md` when the work has Product/Runtime SBS impact, Builder
  System impact, or a boundary between the two
- roadmap / status / plan docs
- CI results
- merge state if already merged
- current `origin/main` / target-base reachability for any resumed, chained, or review-repair work

## Validation Rules

- Compare code and docs to the governing issue's `Scope`, `Source Anchors`, `Constraints`, `Acceptance Criteria`, and `Suggested Validation`
- Verify the PR's Product/Runtime System vs Builder System vs boundary classification. Product work
  must satisfy the SBS impact and owner-doc path; Builder work must route through the Builder System
  boundary/artifact map; boundary work must name and satisfy both sides.
- Run the exact `Suggested Validation` commands where possible
- Add focused extra checks if the touched surface obviously needs them
- For every AC, resolve the declared `Verify:` target on the current PR head SHA
- If a behavioral `Verify:` test is missing, skipped, xfailed, or excluded from the CI suite that ran, do not treat the AC as satisfied
- If a non-behavioral `Verify:` target is absent, do not merge until the writeback exists
- If any AC lacks a `Verify:` marker, route through issue maintenance before proceeding
- Verify owner-doc writeback if shipped behavior or contracts changed and acceptance is complete
- Verify Builder System work did not claim runtime/user memory or Product MEM/HKA authority unless a
  Product System authority path is present in the issue/PR evidence.
- Verify roadmap or plan wording was cleaned up if the item is now delivered
- Verify no duplicate `planned` and `shipped` statements remain active at once
- Verify the BuilderOps routing outcome per tier (`docs/development/GOVERNANCE_PROPORTIONALITY.md`):
  Tier 2+ PR bodies must carry the routing outcome; on Tier 1 (docs/governance lane) PRs a missing
  `## BuilderOps Routing` section means `none` and does not block merge. At every tier, unresolved
  learning, docs freshness, roadmap execution, promotion, projection, or receipt material must be
  represented by a BuilderOps record, a bounded GitHub Issue, or an explicit `none` reason
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

For autonomous delivery, run the full gate chain unattended per `AGENTS.md :: Agency default`: wait for required checks to go green and resolve the local review gate, then merge — do not ask the owner to babysit. The prerequisites below are never waived (an unprotected branch does not relax them); only the human watching is removed.

Wait **how** matters for CI: follow `_shared/CI_WAIT_CONTRACT.md` — use the shared `app.dispatcher.poll_backoff` helper through `scripts/await_pr_checks.sh <PR>` (no `--codex`; the review gate now runs locally per `Running the local review gate` below, not through the shared verdict poller), REST check-runs only, interval + cap + exponential backoff, honor `Retry-After` and x-ratelimit-reset headers, sleep the bulk of CI up front, and back off ≥60–120s. Never tight-poll `gh pr checks` or `gh pr view --json mergeStateStatus`; they are GraphQL and drain the budget shared by every concurrent agent.

Prerequisites for merge:

- current SHA truth is intact
- required checks are green on the current head SHA
- no unresolved blocking review comments remain
- the local review gate is resolved (see `Running the local review gate` below) — a clean run, or a run whose findings are all fixed or explicitly waived by the owner, is a pass; any unresolved finding blocks until addressed
- when a review-thread closure trigger applies, no addressed review thread remains unresolved without a reply naming the fixing PR or merge commit
- no scope drift remains
- the PR fits one of the two verification modes above
- if issue-backed, all acceptance criteria from the governing Issue are satisfied and every AC's `Verify:` target resolves green on the current head SHA
- if direct repair, the `Direct Repair` block and `Validation` are satisfied on the current head SHA
- if the direct repair expands beyond bounded scope, stop and require, create, or link an issue before merge

### Running the local review gate 🤖

The PR review gate runs locally via the built-in `/code-review` skill instead of waiting on an
external GitHub-native reviewer bot. Run it once the PR's required checks are green (per
`_shared/CI_WAIT_CONTRACT.md`, without `--codex`) and before merge:

- Invoke `/code-review` (the code-reviewer subagent) against the PR's diff, with `--comment` so
  findings post as inline PR comments — this keeps the review visible on the PR itself, matching the
  old externally-visible verdict.
- Effort level follows `AGENTS.md :: Total Cost of Development` — default to `medium`/`high` per the
  PR's risk; escalate to `high`-`max` for security/data/migration/auth/concurrency/external-API
  surfaces per the TCD model+reasoning policy.
- Run the reviewer as a fresh subagent with no memory of the implementation reasoning, so it verifies
  independently rather than rubber-stamping its own prior work.

Resolve the verdict:

- **Pass** — the run reports no findings, or every finding it reported has since been fixed (verify
  the fix against the current head SHA) or explicitly waived by the owner with a stated reason.
- **Blocking** — any unresolved finding from the run blocks merge until addressed, fixed-and-reverified,
  or waived.
- Record the run's outcome (clean / findings-fixed / owner-waived) in the delivery receipt so the gate
  is auditable after merge.
- Do not block indefinitely on a stalled or failed review run: if the reviewer subagent cannot complete
  (tool failure, timeout, repeated crash), surface the stall to the owner as a merge-gate decision
  rather than retrying forever. A demonstrable tooling outage is input, not an absolute block — but the
  waiver is the owner's call, not a silent default.

### Reading the Codex verdict 🤖 (inactive — kept for reactivation)

> **Inactive as of the local-review-gate swap above.** This is not the current merge gate; it is kept
> intact so Codex review can be reactivated later without reconstructing this section. `_shared/CI_WAIT_CONTRACT.md`'s
> `--codex` flag still resolves this verdict for callers that opt into it, but `verification-and-closure`'s
> default flow no longer requires it.

Codex (`chatgpt-codex-connector[bot]`) reviews PRs in this repo automatically and often signals its
verdict with an **emoji reaction on the PR itself**, not a formal review or comment. Checking only
`/pulls/<n>/reviews` and `/comments` will miss it and read as "Codex hasn't reviewed yet."

Resolve the verdict through `_shared/CI_WAIT_CONTRACT.md` / `app.dispatcher.poll_backoff` so the
reactions, reviews, pull comments, and issue comments are read with one combined query where GitHub
supports it. The surfaces remain:

- Reactions (primary): `gh api repos/<owner>/<repo>/issues/<pr>/reactions --jq '.[] | select(.user.login=="chatgpt-codex-connector[bot]") | .content'`
  - 👍 `+1` (also `heart` ❤️, `hooray` 🎉, `rocket` 🚀, `laugh` 😄) → reviewed, no blocking findings → **pass**.
  - 👎 `-1` or `confused` 😕 → **blocking**: treat as requested changes until addressed.
- Reviews: `gh api repos/<owner>/<repo>/pulls/<pr>/reviews` — a `CHANGES_REQUESTED` from Codex blocks; `COMMENTED` with substantive findings blocks until each is addressed or replied to.
- Comments: `gh api repos/<owner>/<repo>/issues/<pr>/comments` and `/pulls/<pr>/comments` — Codex posts detailed findings here when it has them.

Rules:

- A 👍/`+1` reaction is a sufficient Codex pass even when there is no formal review or comment.
- Do not block indefinitely on a missing verdict: if Codex has posted no reaction, review, or comment
  and recent sibling PRs show the same silence (a repo-wide Codex stall), surface the stall to the
  owner as a merge-gate decision rather than waiting forever. A demonstrable outage is input, not an
  absolute block — but the waiver is the owner's call, not a silent default.

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

Before merging or writing the delivery receipt, resolve BuilderOps routing: for each record type in
`.codex/skills/README.md :: BuilderOps Vault routing`, confirm the matching record exists (or the
receipt states none) for any divergence, docs-freshness finding, operational roadmap movement,
proposed authority crossing, or processed/promoted/superseded/discarded material noticed during
delivery.

If none apply, the delivery receipt may state `BuilderOps routing: none` with the reason. On Tier 1
PRs (`docs/development/GOVERNANCE_PROPORTIONALITY.md`), an absent `## BuilderOps Routing` section is
read as `none` — do not block closure on its absence. Do not use `docs/learning-log.md` as the
primary closure surface.

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

On a plan divergence (you did something unexpected, or discovered an earlier artifact was wrong), route it through `capture-learning` — it owns the invocation timing and the "name an upstream artifact or don't log" gate.

## Output Format

Lead with the human summary; include later sections only when they have content, scaled to the tier (`docs/development/GOVERNANCE_PROPORTIONALITY.md`). For Tier 1, the summary plus the delivery receipt line is enough.

### 1. Summary For The Human

2–4 sentences: what was verified and merged, what remains, what needs a decision.

### 2. Delivery Verdict

AC-by-AC resolution: state whether each `Verify:` target resolves green and why.

For Tier-2/Tier-3 work, alongside the AC-by-AC verdict, emit a `tcd_review` block (fields per `AGENTS.md :: Total Cost of Development`): verdict, risk_level, blocking vs non-blocking issues, missing tests, residual risk, and under/over-modeling. On Tier-1 / trivial / docs-only verifications a one-line capability + residual-risk note suffices — do not pay a fixed audit-block tax on cheap work. Use the same policy for when to escalate verification depth versus stay on the hot path; do not restate the triggers or any model matrix here.

### 3. State Changes Executed

List every lifecycle mutation that ran.
Include the delivery receipt line.

### 4. Follow-up Issues

If work is partial, do not merge. Create bounded follow-up Issue(s) using the exact task-contract shape.
