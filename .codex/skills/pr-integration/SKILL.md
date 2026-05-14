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

- A bounded governing slice implementation Issue exists.
- A PR exists and links the governing branch.
- The PR was just created or updated by `publish-pr` or equivalent truthful publication flow.
- Implementation changes are already in place.
- Use this skill when the PR still needs mergeability, CI attachment, or review-feedback repair before verification.

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
- Verify branch/worktree/current-SHA sanity before any commit or push.
- Run only the relevant checks for the lane and risk.
- Triage review feedback into blocking, cheap fix, out-of-scope, or incorrect/not-applicable.
- Write the minimal delivery receipt before handoff.
- If CI fails, review blocks, branch drifts, or the PR is large or mixed-scope, stop and read `PR_ESCALATION_PATHS.md`.

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

**Capturing learning:** if during this work you notice a divergence from plan — you did something you did not expect to do, or discovered an earlier artifact was wrong — invoke `capture-learning` before continuing. Do not batch to end of task. Only log if you can name an upstream artifact that could absorb the fix.
