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
- Platform-side pieces are now applied for labels, Project fields, required views, and lifecycle automation. Branch protection remains an optional follow-up because it is a separate repository policy decision.

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

## Source-anchor contract

Backlog state must live in GitHub, not only in inline doc edits.

Required rule for new backlog work:

- every new implementation Issue must include a `Source Anchors` section
- `Source Anchors` must identify the most local backlog-worthy doc item that justified the Issue
- the anchor should be stable across wording cleanups so duplicate extraction is easy to detect later

Recommended syntax in the Issue body:

- `docs/PANEL_AGENT.md :: PA2-FREEFORM`
- `docs/ROADMAP.md :: ORCHV2-TDD`
- `docs/STATUS.md :: SETTINGS-PROVENANCE`

Recommended source-anchor style in docs when a stable item ID is warranted:

- use a short, deterministic identifier on roadmap/plan/checklist items that are likely to be converted into Issues
- keep the identifier semantically narrow and track-scoped
- avoid renumbering or date-based IDs

This contract is intentionally GitHub-first:

- docs define intent and architecture
- Issues/Project define backlog lifecycle state
- PRs and merge history define delivery state
- owner docs define lasting shipped truth

Inline markers such as `Tracked by: #123` and `Backlog: #123` are now secondary convenience notes.
They may still be used sparingly where helpful, but they are not the primary deduplication or backlog-state mechanism.

## Issue contract additions

New Issue contracts must include these sections in addition to the original bounded-task fields:

- `Source Anchors`
- `Suggested Validation`
- `Source Docs`

Why:

- `Source Anchors` makes the doc-to-issue mapping deterministic
- `Suggested Validation` keeps the task executable by humans and agents
- `Source Docs` keeps the governing authority explicit when multiple docs are involved

## Receipt model

Preferred tracking split:

- backlog receipt: GitHub Issue created, labeled, and placed in the Project
- delivery receipt: merged PR plus owner-doc update

Preferred write locations:

- backlog state: GitHub Issue + Project
- delivery state: PR + merge commit + CI + owner doc
- optional scan surface: generated receipt page derived from GitHub data

Do not require a source doc edit just to make backlog creation visible to collaborators.
If a source doc is not being otherwise updated, it is acceptable for the initial backlog receipt to exist only in GitHub as long as the Issue carries stable `Source Anchors`.

## Generated receipt page shape

If the repo later adopts generated backlog receipts, keep the output as a derived summary, for example:

```md
# Backlog Receipts

## Open
- `PA2-FREEFORM` -> Issue #241 (`Ready`)
- `ORCHV2-TDD` -> Issue #250 (`Ready`)

## Delivered
- `SETTINGS-PROVENANCE` -> Issue #238 / PR #___ / commit <sha>
```

This page should be treated as a convenience projection from GitHub, not as the canonical task state store.

## Migration rule

Use this migration posture from March 30, 2026 onward:

- existing inline `Tracked by` / `Backlog` markers may remain until the surrounding docs are naturally edited
- new backlog extraction should prefer `Source Anchors` in GitHub Issues
- delivered work must still be written back into owner docs in the merge that ships the behavior
- roadmap and plan docs should not keep delivered items phrased as pending
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
- required views `Kanban` and `Agent Queue` were created in the project
- built-in Project lifecycle automation was configured for issue/PR state transitions
- active governance items were added to the project and seeded with initial states:
  - issue `#225` -> `Status=Review`, `Agent State=Idle`
  - issue `#224` -> `Status=Review`
  - issue `#226` -> `Status=Review`
  - PR `#223` -> `Status=Review`

GitHub platform limitations observed in this session:
- Project views and built-in Project workflows were completed manually in the GitHub UI because the exposed CLI/GraphQL surface did not provide a supported creation path for those resources
- branch protection was not adopted in this change; if enabled later, the required checks should be documented together with that rollout

## Required follow-up outside the repo

1. Optionally add branch protection or repository rules that require the governance workflow to pass before merge.

## Governance receipts

Backlog receipt:
- Repo-side governance rollout was captured as GitHub Issue `#226`.
- Owner-doc migration was captured as GitHub Issue `#224`.
- Platform-side GitHub setup remains tracked as GitHub Issue `#225`.

Delivery receipt:
- On 2026-03-30, the owner-doc migration from `docs/development/GITHUB_GOVERNANCE_PATCHES.md` was applied, so builder/runtime governance wording now lives in the owning docs instead of only in the staging patch document.
- On 2026-03-30, the repository labels, Project v2 board, linked repository, required status taxonomy, custom `Agent State` field, and initial item states were applied on the GitHub platform.
- On 2026-03-30, the required `Kanban` and `Agent Queue` views plus the built-in Project lifecycle automation were completed manually in the GitHub UI after the repo and field baseline was applied.
- Branch protection remains optional follow-up work because it is a separate repository policy decision.
