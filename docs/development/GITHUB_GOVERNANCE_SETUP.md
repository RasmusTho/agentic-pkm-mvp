State: Development reference. Not an auto-loaded instruction file.
# GitHub Governance Setup

This document defines the repo-external GitHub configuration that must match the repo-side governance files.

Owner contract:
- Repo-side contract lives in `.github/github-governance.yml`.
- Repo-enforced pieces in this change:
  - `.github/ISSUE_TEMPLATE/task.yml`
  - `.github/ISSUE_TEMPLATE/config.yml`
  - `.github/pull_request_template.md`
  - `.github/workflows/issue-pr-governance.yml`
- Platform-side pieces must be applied in GitHub UI / GitHub CLI / GraphQL because the available connector for this change does not expose write endpoints for labels or Projects v2.

## Exact label set

Keep only these labels for the delivery control plane taxonomy:

- `type:task`
- `type:bug`
- `type:refactor`
- `prio:high`
- `prio:med`
- `prio:low`
- `agent:ready`
- `agent:blocked`
- `agent:needs-human`

## Project contract

Project name:
- `Agent Delivery Control Plane`

Required fields:
- `Status`: `Backlog`, `Ready`, `In Progress`, `Review`, `Done`
- `Agent State`: `Idle`, `Running`, `Waiting`

Required views:
- `Kanban` grouped by `Status`
- `Agent Queue` filtered to `label:agent:ready` and `Status = Ready`

Required automation:
- new issue -> `Status=Backlog`
- PR opened -> `Status=In Progress`
- PR review requested -> `Status=Review`
- PR merged -> `Status=Done`

## Enforcement intent

- Issues are the canonical delivery task contract.
- PRs must reference an Issue using `Fixes #<id>`, `Closes #<id>`, or `Resolves #<id>`.
- Agents only pick Issues labeled `agent:ready`.
- Agents must stay within Issue scope, constraints, and acceptance criteria.
- Blank/free-form Issues are disabled at repo level.

## Existing-state findings from the March 30, 2026 audit

- Existing Issues are present, but titles/bodies are free-form and not normalized to a machine-readable task contract.
- The repo did not contain a task Issue form.
- The repo did not contain a PR template requiring Issue linkage.
- Recent PRs show inconsistent branch naming and inconsistent Issue-linking practice.
- CI workflows exist and are substantial, but there was no dedicated workflow enforcing Issue/PR governance.
- The available connector did not expose label enumeration/writes or Project v2 writes, so platform-side GitHub state could not be fully inspected or mutated from this run.

## Required follow-up outside the repo

1. Normalize labels to the exact set above.
2. Create/update the Project v2 board and fields.
3. Wire Project automation to the stated lifecycle.
4. Optionally add branch protection or repository rules that require the governance workflow to pass before merge.

## Governance receipts

Backlog receipt:
- Repo-side governance rollout was captured as GitHub Issue `#226`.
- Owner-doc migration was captured as GitHub Issue `#224`.
- Platform-side GitHub setup remains tracked as GitHub Issue `#225`.

Delivery receipt:
- On 2026-03-30, the owner-doc migration from `docs/development/GITHUB_GOVERNANCE_PATCHES.md` was applied, so builder/runtime governance wording now lives in the owning docs instead of only in the staging patch document.
- This setup document remains the reference for the still-pending platform-side label/Project/application work.
