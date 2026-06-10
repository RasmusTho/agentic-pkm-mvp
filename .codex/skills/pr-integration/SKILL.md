---
name: pr-integration
description: "Prepare a PR for verification by following the default hot path, escalating only when triggered, and preserving current SHA truth, branch/worktree sanity, and traceability."
---

# PR Integration

Use this skill when a PR needs readiness or repair before verification.
Default to [`docs/development/PR_HOT_PATH.md`](../../../docs/development/PR_HOT_PATH.md) for normal delivery.
Read [`docs/development/PR_ESCALATION_PATHS.md`](../../../docs/development/PR_ESCALATION_PATHS.md) only when a trigger in the hot path applies.
Merge remains owned by `verification-and-closure`.

⚠️ **CRITICAL: Integration actions must be executed with explicit git/gh/API commands and verified. Do not describe them as theory. Preserve current SHA truth, branch/worktree sanity, required-check freshness, blocking review classification, minimal receipts, and issue/PR traceability. Avoid heavyweight governance checks for low-risk PRs.**

## Canonical workflow position

Hot path:
`Docs -> Feature issue -> Slice issue -> Agent -> Publish PR -> CI -> Slice verification -> Merge -> Feature validation -> Acceptance -> Owner Doc`

Conditional readiness-repair path:
`Docs -> Feature issue -> Slice issue -> Agent -> Publish PR -> PR integration -> CI -> Slice verification -> Merge -> Feature validation -> Acceptance -> Owner Doc`

## First context to load

- `AGENTS.md`
- `docs/development/DEV_WORKFLOW.md`
- `docs/development/PR_HOT_PATH.md`
- `docs/development/PR_ESCALATION_PATHS.md` only if a hot-path trigger applies

## Entry conditions

- Either:
  - an issue-backed PR exists with a bounded governing slice Issue, or
  - a bounded direct repair PR exists whose body contains a complete `Direct Repair` block.
- A PR exists and links the governing branch.
- The PR was just created or updated by `publish-pr` or equivalent truthful publication flow.
- Implementation changes are already in place.
- Use this skill when the PR still needs mergeability, CI attachment, branch drift repair, review-feedback repair, or other triggered integration work before verification.

## Exit conditions

Hand off only when all of these are true:

- the PR is ready for verification on the current head SHA
- branch/worktree/current-SHA truth is intact
- required checks are known, current, and attached
- all blocking review feedback is addressed or explicitly classified
- no escalation trigger remains unresolved

If any condition fails, stop and use the relevant escalation path.

## Hot-Path Execution

- Classify the PR with the hot-path fields from `PR_HOT_PATH.md`.
- Verify branch/worktree/current-SHA sanity before any commit or push. The active worktree must be the PR worktree, the branch name must match the PR head branch before commit/push, and local `HEAD`, tracked remote branch, and PR head SHA must agree before trusting CI attachment or merge readiness. [branch-truth-gate]
- Run only the relevant checks for the lane and risk.
- Triage review feedback into blocking, cheap fix, out-of-scope, or incorrect/not-applicable.
- For review-feedback repairs, verify the fixing commit is reachable from the target base branch before declaring the repair complete. If the repair addresses an earlier review thread, reply with the fixing PR or merge commit and resolve the original thread. [base-branch-truth] [review-thread-closure]
- On resume or recovery, re-check the current branch, `origin/main`, relevant merged PRs, and expected implementation files before continuing publication, integration, or reimplementation. [post-resume-current-state-gate]
- Write the minimal delivery receipt before handoff.
- A governing issue is required for normal planned workflow; a bounded direct repair PR may proceed without one if the PR body includes a complete `Direct Repair` block.
- Do not require a separate governance/docs lane checkbox when the `Direct Repair` block already states `Type` and `Validation`.
- Missing issue traceability is an escalation trigger only when the PR is neither issue-backed nor a valid direct repair PR.
- If CI fails, review blocks, branch drifts, or the PR is large or mixed-scope, stop and read `PR_ESCALATION_PATHS.md`.
- If CI reports an unavailable pytest flag such as `-n`/`--dist`, check for `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` and require an explicit `-p <plugin_name>` load before adding or changing dependencies. [plugin-load-guard]
- After a review-fix push where GitHub's merge ref may differ from branch HEAD, fetch `refs/pull/<PR>/merge`, inspect touched symbols in that tree, and run at least one targeted test against the merge-ref worktree before declaring `ready-for-verification`. [merge-ref-validation]

## Escalation References

Use `PR_ESCALATION_PATHS.md` for:

- CI failure investigation
- merge-ref validation
- branch drift recovery
- dependency issue scan
- owner-doc check
- heavy review/comment loops
- GitHub Project / board cleanup
- full governance receipt repair

## Handoff Decision

Declare exactly one outcome:

- `ready-for-verification`
- `blocked-merge-conflict`
- `blocked-ci-failure`
- `blocked-contract-drift`
- `blocked-review-feedback`

## Lifecycle Truth Rules During Integration

- active work remains `In Progress`
- move to `Review` only when review handoff is explicit
- do not mark lifecycle `Done` in this stage
- do not close the governing Issue in this stage
- do not merge the PR in this stage

## Output Format

1. PR Integration Inputs
2. Contract Gate Result
3. Mergeability / Branch Truth Result
4. CI / Review Result
5. Explicit Handoff Decision

## Capturing learning

**Capturing learning:** if during this work you notice a divergence from plan — you did something you did not expect to do, or discovered an earlier artifact was wrong — route it through `capture-learning`, which owns the invocation timing: invoke immediately only when the divergence needs upstream repair now; otherwise note the signal for `learning-retrospective`. Only log if you can name an upstream artifact that could absorb the fix.
