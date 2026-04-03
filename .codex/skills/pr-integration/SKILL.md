---
name: pr-integration
description: "Prepare a slice-implementation PR for verification by resolving merge conflicts, enforcing PR contract metadata, and ensuring CI is attached to the latest head."
---

# PR Integration

Use this skill after `issue-to-code` implementation work and before the verification stage.

Goal:
produce a mergeable, policy-compliant PR with CI attached to the latest head SHA so verification can run on truthful state.

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

- PR `mergeable` state is `MERGEABLE`.
- No unresolved merge conflicts remain.
- PR body/classification satisfies governance contract.
- CI/checks are attached to the current head SHA and either:
  - green and ready for verification handoff, or
  - explicitly blocked with concrete failing jobs/log pointers.

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

- Query PR mergeability and head SHA first.
- If merge conflicts exist:
  - sync with latest base branch (`main`)
  - rebase or merge base into the PR branch (follow repository norm)
  - resolve conflicts without expanding scope beyond the governing Issue
  - rerun focused validation for touched surfaces
  - push updated branch and re-check mergeability
- If mergeability remains blocked due ambiguity, mark as blocked and hand off with explicit conflict context.

### 3) CI attachment gate

- Verify checks are attached to the current PR head SHA.
- If checks are missing on current head after a short wait, retrigger by a minimal deterministic change (for example an empty commit) or another allowed PR event.
- Do not run verification against stale check results from an older SHA.

### 4) CI result gate

- Wait for required checks to complete.
- If checks fail:
  - capture failing jobs and log URLs
  - fix within bounded scope when safe
  - push and re-evaluate from mergeability + CI attachment gates
- If checks pass, hand off to verification.

## Lifecycle truth rules during integration

- Keep Issue/Project state truthful:
  - active work remains `In Progress`
  - move to `Review` only when review handoff is explicit (normally after review requested)
- Do not mark lifecycle `Done` in this stage.
- Do not close the governing Issue in this stage.

## Output format

1. PR Integration Inputs
2. Contract Gate Result
3. Mergeability Actions
4. CI Attachment and Status
5. Handoff Decision

Handoff decision must be exactly one of:

- `ready-for-verification`
- `blocked-merge-conflict`
- `blocked-ci-failure`
- `blocked-contract-drift`
