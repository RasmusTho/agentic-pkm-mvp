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
  - `.github/workflows/project-status-reconcile.yml`
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

Status meanings:
- `Backlog`: tracked work that is not yet ready for agent execution or has been moved out of active execution
- `Ready`: bounded, testable, unblocked work that is eligible for pickup and labeled `agent:ready`
- `In Progress`: active implementation issue state; on PR items this means draft/rework phase
- `Review`: PR/project-item review/integration gate and default state for normal open PRs
- `Done`: merged or otherwise fully delivered work; the Issue is closed and no `agent:*` labels remain

Agent-label meanings:
- `agent:ready`: queue-eligible work; use only with `Status=Ready`
- `agent:blocked`: blocked by dependency or setup; normally pair with a non-active status such as `Backlog`
- `agent:needs-human`: blocked on human decision or missing authority; normally pair with a non-active status such as `Backlog`
- open implementation Issues should normally carry exactly one truthful agent-state label

Interpretation rule:
- GitHub Project `Status` is the preferred operational projection of lifecycle state, not the hardest source of truth.
- GitHub Issue state, agent labels, linked PR state, and merge/delivery reality outrank Project state when they disagree.
- Agent labels qualify pickup or blocker state; they do not replace Issue/PR lifecycle truth.

Required views:
- `Kanban` grouped by `Status`
- `Agent Queue` filtered to `label:agent:ready` and `Status = Ready`

Required automation:
- new issue -> `Status=Backlog`
- issue reopened or agent-label changed -> reconcile `Status` from the current Issue state and truthful agent label
- PR opened/reopened (non-draft) -> `Status=Review`
- PR opened/reopened (draft) -> `Status=In Progress`
- PR marked ready for review -> `Status=Review`
- PR converted to draft -> `Status=In Progress`
- PR merged -> `Status=Done`
- PR closed -> `Status=Done` when the PR is terminal and no longer active
- issue and PR Project items are reconciled by repo-side workflow so merged PR cards and closed Issue cards do not drift

Interpretation note:
- These automation targets describe the intended Project projection.
- They should be treated as best-effort synchronization, not as a repository-local hard guarantee when the Project lives on a personal account or another platform surface with limited automation credentials.

Lifecycle guardrails:
- active implementation must not remain `Ready`
- issues should not move to `Review` only because a PR exists; issue state remains claim/execution truth
- normal open PRs should default to `Review`; draft is opt-in and should be used only with an explicit reason
- closed issues must not retain `agent:ready`, `agent:blocked`, or `agent:needs-human`
- merged or otherwise closed terminal PR items must not remain unset or non-terminal in the Project; they should reconcile to `Done`

Projection rule:
- When Project state disagrees with Issue state, PR state, or merged delivery reality, treat the Issue/PR state as authoritative and correct the Project opportunistically.
- Do not block delivery solely because a personal Project v2 card could not be updated by repo automation.

## Shared operational lease boundary

GitHub Issues, labels, PRs, and Project status are the shared human-visible lifecycle projection.
They are not the live operational store for fast multi-agent exclusion. Multiple agent
environments should use only a minimal shared lease layer for operational coordination:

- issue claims such as `issue:<number>`
- lane claims such as `lane:<id>`
- TTL, heartbeat/renewal, and explicit release by `execution_id`
- optional branch or worktree reservation when needed to avoid active-work collision

The lease layer must stay behind a tiny deterministic API or tool surface such as `claim_issue`,
`release_issue`, `claim_lane`, `renew_lease`, and `get_claim`. Agents and skills should consume
that surface instead of querying a backend store directly. This boundary excludes a general
workflow metadata registry, repo-file-based live status, a large operational database model,
MCP-first control-plane behavior, and free-form agent queries over operational data.

Git hygiene remains local first. Hot-path preflight is read-only and checks dirty tree,
in-progress git operations, branch/worktree mismatch, and relevant lease conflicts before local
mutation. Broader cleanup belongs to a cold-path janitor flow that reports stale merged branches,
orphaned worktrees, old stashes, and prune candidates while respecting active leases. Destructive
cleanup is not automatic in v1.

## Enforcement intent

- Issues are the canonical delivery task contract for implementation work.
- GitHub Project is an operating view over Issue and PR truth, not a stronger authority than them.
- Implementation PRs must reference an Issue using `Fixes #<id>`, `Closes #<id>`, or `Resolves #<id>`.
- Docs-authoring PRs may omit an Issue reference only when they are explicitly classified as docs authoring and remain limited to approved docs-authoring surfaces.
- Governance-lane PRs may omit an Issue reference only when they are explicitly classified as governance lane and remain limited to approved governance surfaces.
- Agents only pick Issues labeled `agent:ready`.
- Agents only pick Issues when `Status=Ready` and the Issue is labeled `agent:ready`.
- Issue claim (`Ready` -> `In Progress` plus `agent:ready` removal) remains a synchronous skill action, not PR automation.
- Agents must stay within Issue scope, constraints, and acceptance criteria.
- Blank/free-form Issues are disabled at repo level.

## Docs-authoring PR lane

Docs authoring is the separate PR lane for docs-only changes that evolve or clarify authoritative repo docs before backlog extraction.

Approved docs-authoring surfaces:

- `docs/**`
- `README.md`
- `AGENTS.md`
- `CLAUDE.md`
- `.codex/AGENTS.md`
- `.github/github-governance.yml`
- `.github/ISSUE_TEMPLATE/*.yml`
- `.github/pull_request_template.md`
- `.github/workflows/issue-pr-governance.yml`

Rules:

- docs-authoring PRs are docs-only and must not change code, runtime behavior, contracts, or shipped reality
- docs-authoring PRs must be explicitly classified in the PR body
- docs-authoring PRs do not automatically create backlog items or Project state
- once authored docs become implementation work, the repo returns to the normal Issue-first lane

## Governance PR lane

Governance lane is the separate PR path for bounded repository-governance changes that are not product/runtime implementation but are broader than docs-only authoring.
This includes repo-meta enforcement code and focused tests when they change governance behavior rather than shipped system behavior.

Approved governance surfaces:

- `docs/**`
- `AGENTS.md`
- `CLAUDE.md`
- `.codex/AGENTS.md`
- `.codex/skills/**`
- `.github/github-governance.yml`
- `.github/ISSUE_TEMPLATE/*.yml`
- `.github/pull_request_template.md`
- `.github/workflows/issue-pr-governance.yml`
- `scripts/docs_guard.py`
- `scripts/git_hygiene.py`
- `scripts/git_hygiene_preflight.py`
- `scripts/git_hygiene_janitor.py`
- `scripts/reconcile_project_status.py`
- `scripts/validate_source_anchors.py`
- `tests/ops/test_git_hygiene.py`
- `tests/ops/test_project_status_reconcile.py`

Rules:

- governance-lane PRs may change repo-local skills and lightweight governance enforcement
- governance-lane PRs may include repo-meta enforcement code and focused regression tests for governance behavior
- governance-lane PRs must be explicitly classified in the PR body
- governance-lane PRs may omit an Issue reference when they stay within the approved governance surfaces
- governance-lane PRs must not change product/runtime implementation or shipped feature behavior
- once a governance change becomes implementation work, the repo returns to the normal Issue-first lane

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
- Issues define bounded backlog task truth
- Project reflects lifecycle as an operational projection when available
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

- backlog state: GitHub Issue first; Project when available as the shared operational board
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
- repo-local automation may not have durable write authority to a personal Project v2 board, so Project reconciliation should be treated as best effort unless stronger credentials or an org-owned Project surface are adopted
- branch protection was not adopted in the initial rollout; required status checks were added later (see delivery receipt below)

## Required follow-up outside the repo

~~1. Optionally add branch protection or repository rules that require the governance workflow to pass before merge.~~
Branch protection with required status checks is now active on `stable` (delivered 2026-05-10, issue #844).

## Governance receipts

Backlog receipt:
- Repo-side governance rollout was captured as GitHub Issue `#226`.
- Owner-doc migration was captured as GitHub Issue `#224`.
- Platform-side GitHub setup remains tracked as GitHub Issue `#225`.

Delivery receipt:
- On 2026-03-30, the owner-doc migration from `docs/development/GITHUB_GOVERNANCE_PATCHES.md` was applied, so builder/runtime governance wording now lives in the owning docs instead of only in the staging patch document.
- On 2026-03-30, the repository labels, Project v2 board, linked repository, required status taxonomy, custom `Agent State` field, and initial item states were applied on the GitHub platform.
- On 2026-03-30, the required `Kanban` and `Agent Queue` views plus the built-in Project lifecycle automation were completed manually in the GitHub UI after the repo and field baseline was applied.
- On 2026-05-10, required status checks (`smoke`, `smoke-docker`, `pr-contract`, `strict=true`) were added to `stable` branch protection via issue #844. A PR targeting `stable` now requires all three checks to pass before merge is permitted.
