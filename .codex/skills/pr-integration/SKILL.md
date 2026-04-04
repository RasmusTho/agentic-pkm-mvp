---
name: pr-integration
description: "Prepare a slice-implementation PR for verification by resolving merge conflicts, enforcing PR contract metadata, and ensuring CI is green on the latest head SHA."
---

# PR Integration

Use this skill after `issue-to-code` implementation work and before the verification stage.

Goal:
produce a mergeable, policy-compliant PR with CI **green** on the latest head SHA so verification can run on truthful state.

This skill does NOT merge the PR. Merge is owned by the verification skill after it confirms the delivery contract is satisfied.

## Canonical workflow position

`Docs -> Feature issue -> Slice issue -> Agent -> PR -> PR integration -> CI -> Slice verification -> Merge -> Feature validation -> Acceptance -> Owner Doc`

## First context to load

- `AGENTS.md`
- `docs/development/DEV_WORKFLOW.md`
- `.github/pull_request_template.md`
- `.github/workflows/issue-pr-governance.yml`
- `.github/workflows/project-status-reconcile.yml`

## Entry conditions

- A bounded governing slice implementation Issue exists.
- A PR exists (draft or ready) and links the governing branch.
- Implementation changes are already in place.

## Exit conditions

ALL of these must be true before handing off to verification:

- PR `mergeable` state is `MERGEABLE`, confirmed by local merge simulation.
- No unresolved merge conflicts remain.
- PR body/classification satisfies governance contract.
- CI/checks are attached to the current head SHA and **all required checks have completed successfully**.
- All review comments are addressed or explicitly marked as out-of-scope.

If any exit condition is not met, do not hand off. Loop or block.

## Required gates

### 1) Contract and metadata gate

- Confirm PR lane classification is truthful:
  - implementation lane must include `Fixes #<id>`, `Closes #<id>`, or `Resolves #<id>` for the governing slice issue
  - docs/governance lanes must follow allowed-surface constraints from workflow policy
- Ensure PR template checklists are not left in contradictory states.
- Ensure linked Issue still matches actual scope; if scope drift occurred, stop and route through Issue maintenance.

Operational checks:

- `gh pr view <pr> --json number,state,isDraft,mergeable,headRefOid,baseRefName,labels,body,statusCheckRollup`
- `gh pr checks <pr>`

### 2) Mergeability gate

**Critical: Never trust the GitHub API `mergeable` field alone.** GitHub returns `null` while computing and `dirty` for multiple unrelated reasons. Always verify locally.

Required verification steps:

1. `git fetch origin main` to get latest base.
2. Run `git merge-tree $(git merge-base origin/main HEAD) origin/main HEAD` to simulate the merge locally.
3. If the output contains `CONFLICT`, the PR has real merge conflicts — do not declare the gate passed.
4. Only after a clean local simulation, check the GitHub API `mergeable` field as a secondary confirmation.

If merge conflicts exist:

- Sync with latest base branch (`main`).
- Rebase or merge base into the PR branch (follow repository norm).
- Resolve conflicts without expanding scope beyond the governing Issue.
- Rerun focused validation for touched surfaces.
- Push updated branch.
- **Re-run the local merge simulation again** to confirm the conflict is resolved. Do not trust the push alone.

If mergeability remains blocked, mark as `blocked-merge-conflict` and hand off with explicit conflict context.

### 3) CI attachment gate

- Verify checks are attached to the current PR head SHA.
- If checks are missing on current head, wait and retry:
  - Poll every 15 seconds for up to 2 minutes.
  - If still missing after 2 minutes, retrigger by pushing a minimal deterministic change (empty commit with message explaining the retrigger).
  - Poll again for up to 3 minutes after retrigger.
  - If checks are still missing after retrigger, mark as `blocked-ci-failure` with explicit context about missing CI attachment.
- Do not proceed to the CI result gate until at least one check-run is attached to the current head SHA.

### 4) CI result gate

**Critical: Do not hand off while checks are pending or absent.** Wait until all required checks reach a terminal state (success or failure).

Required behavior:

1. Poll check status every 30 seconds.
2. Continue polling until ALL checks reach a terminal state (`success`, `failure`, `cancelled`, `timed_out`). Maximum wait: 15 minutes.
3. If all checks pass: proceed to review comment gate.
4. If any check fails:
   - Capture failing job names, conclusions, and log URLs.
   - Analyze whether the failure is fixable within the governing Issue scope.
   - If fixable: fix, push, and **restart from the mergeability gate** (since the head SHA changed).
   - If not fixable within scope: mark as `blocked-ci-failure` with concrete failing jobs and log pointers.
5. If checks do not reach terminal state within 15 minutes: mark as `blocked-ci-failure` with "CI timed out" context.

Never declare `ready-for-verification` while any check is still `queued`, `in_progress`, or absent.

### 5) Review comment detection and addressing gate

**Purpose**: Surface and address any review feedback before handoff to avoid back-and-forth delays.

**Detection**:
- `gh pr view <pr> --json reviews` to fetch all reviews
- `gh api repos/{owner}/{repo}/pulls/{pr}/comments` to get inline comments
- Identify unresolved and actionable comments

**Classification**:
- **Actionable within scope**: Feedback that improves the Issue implementation without expanding scope
  - Examples: missing edge case, clearer wording, additional validation
  - Action: Make the change, push, re-run focused CI, and add review comment explaining the fix
- **Out-of-scope**: Feedback that requires Issue expansion or different strategy
  - Examples: feature requests, alternative approaches, future improvements
  - Action: Document in PR comment why it's out-of-scope, reference Issue boundaries, suggest follow-up Issue
- **Blocking**: Feedback indicating Issue requirements are not met or contract is violated
  - Action: Stop and route through Issue maintenance if contract truly requires the change

**Response workflow**:
1. For each unresolved review comment:
   - Evaluate whether it's actionable within Issue scope
   - If actionable: implement fix, test, push, add PR comment explaining the change
   - If out-of-scope: add PR comment with clear rationale and scope reference
   - If blocking: stop and hand off with explicit context
2. Re-run focused validation after any code changes
3. If code was pushed, **restart from the mergeability gate** (head SHA changed)
4. Update PR body if scope interpretation needed clarification

## Gate re-entry after pushes

Any push to the PR branch changes the head SHA. After a push:

1. Restart from the mergeability gate (step 2).
2. Wait for CI to attach to the new SHA (step 3).
3. Wait for CI to complete on the new SHA (step 4).
4. Re-check review comments (step 5).

Do not carry forward check results from a previous SHA.

## Lifecycle truth rules during integration

- Keep Issue/Project state truthful:
  - active work remains `In Progress`
  - move to `Review` only when review handoff is explicit (normally after review requested)
- Do not mark lifecycle `Done` in this stage.
- Do not close the governing Issue in this stage.
- Do not merge the PR in this stage.

## Output format

1. PR Integration Inputs
2. Contract Gate Result
3. Mergeability Actions (including local merge simulation output)
4. CI Attachment and Status (including poll attempts and final check results)
5. Review Comment Detection and Response
6. Handoff Decision

Handoff decision must be exactly one of:

- `ready-for-verification` — all gates pass: mergeable confirmed locally, CI green on current SHA, review feedback addressed
- `blocked-merge-conflict` — merge conflicts remain unresolved after rebase/merge attempt
- `blocked-ci-failure` — required CI checks failing or not attaching
- `blocked-contract-drift` — PR body or scope no longer matches Issue contract
- `blocked-review-feedback` — unresolved blocking review comments found

**`ready-for-verification` requires ALL of:**
- Local merge simulation clean (no CONFLICT output)
- GitHub API `mergeable` is `true` or `MERGEABLE`
- All CI checks in terminal success state on current head SHA
- No unresolved blocking review comments
