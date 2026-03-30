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
- Platform-side pieces were applied where the available GitHub CLI and GraphQL surfaces exposed supported write paths. Project views and built-in project automation were not exposed for creation/update in this session and therefore remain manual GitHub UI follow-up.

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

## Applied platform state on 2026-03-30

Applied successfully:
- the exact delivery-control-plane labels were created in the repository
- GitHub Project v2 `Agent Delivery Control Plane` was created for user `RasmusTho`
- the project was linked to repository `RasmusTho/agentic-pkm-mvp`
- the built-in `Status` field was updated to `Backlog`, `Ready`, `In Progress`, `Review`, `Done`
- custom field `Agent State` was created with `Idle`, `Running`, `Waiting`
- active governance items were added to the project and seeded with initial states:
  - issue `#225` -> `Status=In Progress`, `Agent State=Running`
  - issue `#224` -> `Status=Review`
  - issue `#226` -> `Status=Review`
  - PR `#223` -> `Status=Review`

GitHub platform limitations observed in this session:
- the exposed GitHub CLI/GraphQL surface did not provide a supported create/update path for Project views, so `Kanban` and `Agent Queue` still need to be created manually in the GitHub UI
- the exposed GraphQL schema included workflow deletion but no supported creation mutation for built-in Project workflows, so the status automations remain manual GitHub UI setup
- branch protection was not adopted in this change; if enabled later, the required checks should be documented together with that rollout

## Required follow-up outside the repo

1. Create the `Kanban` and `Agent Queue` project views in the GitHub UI.
2. Configure built-in Project automation for issue/PR lifecycle transitions in the GitHub UI.
3. Optionally add branch protection or repository rules that require the governance workflow to pass before merge.

## Governance receipts

Backlog receipt:
- Repo-side governance rollout was captured as GitHub Issue `#226`.
- Owner-doc migration was captured as GitHub Issue `#224`.
- Platform-side GitHub setup remains tracked as GitHub Issue `#225`.

Delivery receipt:
- On 2026-03-30, the owner-doc migration from `docs/development/GITHUB_GOVERNANCE_PATCHES.md` was applied, so builder/runtime governance wording now lives in the owning docs instead of only in the staging patch document.
- On 2026-03-30, the repository labels, Project v2 board, linked repository, required status taxonomy, custom `Agent State` field, and initial item states were applied on the GitHub platform.
- Project views, built-in automation, and any future branch protection remain explicit follow-up work because they were not exposed as supported write paths in this session.
