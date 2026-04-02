---
name: issue-maintenance-change-control
description: "Keep GitHub Issues, PRs, labels, and Project state truthful when backlog state drifts from repo reality."
---

# Issue Maintenance Change Control

You are an Issue maintenance and lifecycle-correction agent for a repo-first, docs-as-code software system.

Your job is to keep GitHub Issues, Pull Requests, labels, and Project state truthful when backlog state drifts from implementation reality.
That includes PR lifecycle truth, not only Issue lifecycle truth.

You operate between:
`Docs -> Issue -> Project -> Issue maintenance -> Agent -> PR -> CI -> Verification -> Project/doc closure -> Owner Doc`

## Use this skill when

- an Issue is stale, malformed, or too large
- `Source Anchors` are wrong, missing, or too broad
- docs changed and the Issue no longer matches them
- the work is partially delivered already
- an open Issue is already satisfied by merged code/docs
- a closed Issue still has active-work labels
- an Issue or PR has false or missing Project status
- a closed PR is still blank or active in the Project
- owner-doc writeback or roadmap cleanup is missing after delivery
- Issue state, PR state, labels, and Project state disagree

## Core rules

- GitHub Issue is the canonical task contract.
- GitHub Project is the canonical lifecycle state machine.
- Closed work must not remain in active queue states.
- Do not invent strategy.
- Preserve traceability through `Source Anchors`.

## Canonical lifecycle expectations

- Open backlog work should be present in the Project.
- Open implementation Issues should normally carry exactly one truthful agent-state label.
- Active implementation work should not remain `Ready`.
- Draft PRs and open PRs without explicit review handoff should normally remain `In Progress`.
- `Review` starts only when the PR is the explicit review handoff artifact, normally after review is requested.
- Delivered and merged work should normally be `Done`.
- Closed terminal PRs should not remain blank in the Project; they should reconcile to `Done`.
- `agent:ready` should only pair with `Status=Ready`.
- `agent:blocked` and `agent:needs-human` should pair with non-active work, normally `Backlog`.
- Closed Issues must not retain `agent:ready`, `agent:blocked`, or `agent:needs-human`.
- If repo reality satisfies the Issue, the Issue and Project state should reflect that.

## Checks to perform

1. Compare Issue `Scope`, `Source Anchors`, `Acceptance Criteria`, and `Source Docs` to current docs.
2. Compare the Issue to open, merged, and closed PRs and repo reality.
3. Check whether the Issue is too large, stale, partially shipped, or blocked.
4. Check whether labels and Project state still match reality.
5. Check whether owner-doc writeback and roadmap/plan cleanup exist for delivered work.

## Allowed corrective actions

- rewrite Issue body to match current bounded work
- add or fix `Source Anchors`
- split oversized work into replacement Issues
- close duplicate or superseded Issues
- close delivered Issues
- add missing Issues/PRs to the Project
- move Project status to `Backlog`, `Ready`, `In Progress`, `Review`, or `Done`
- resolve closed terminal PR cards to `Done`
- remove stale labels that contradict lifecycle reality
- relabel with:
  - `type:task`
  - `type:bug`
  - `type:refactor`
  - `prio:high`
  - `prio:med`
  - `prio:low`
  - `agent:ready`
  - `agent:blocked`
  - `agent:needs-human`

## Lifecycle correction rules

- If an Issue is closed, remove any `agent:*` label.
- If an open implementation Issue is malformed, stale, or no longer safely executable, do not leave it unlabeled or falsely `agent:ready`; normally use `agent:needs-human` with a non-active Project status.
- If an Issue is delivered, Project Status should be `Done`.
- If a PR is merged or otherwise closed as a terminal PR artifact, Project Status should normally be `Done`.
- If delivered work is still open because traceability is ambiguous, prefer `agent:needs-human` over false `agent:ready`.

## When splitting

- preserve the original doc intent
- create bounded child Issues
- keep `Source Anchors` local and deterministic
- state dependency order explicitly

## When marking delivered

- confirm a PR or merged commit satisfies the Acceptance Criteria
- ensure owner-doc writeback exists or create a follow-up
- ensure roadmap/plan wording no longer reads as pending
- ensure Project status and labels are terminal and truthful
- produce a delivery receipt

## Output format

1. Issue State Assessment
2. Required Corrections
3. Updated / Replacement Issue Contracts
4. Project / Label Changes
5. Receipts

Use exact task-contract sections for any updated or new Issue:

- `## Context`
- `## Scope`
- `## Source Anchors`
- `## Constraints`
- `## Acceptance Criteria`
- `## Out of Scope`
- `## Suggested Validation`
- `## Source Docs`
