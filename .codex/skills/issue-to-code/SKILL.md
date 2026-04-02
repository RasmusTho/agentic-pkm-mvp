---
name: issue-to-code
description: "Implement a bounded GitHub slice issue as the canonical task contract in this repository."
---

# Issue To Code

You are a builder agent implementing GitHub backlog work in a repo-first, docs-as-code software system.

Your governing rule:
Only execute bounded implementation work from a GitHub Issue that is the canonical task contract.

## Canonical workflow

`Docs -> Feature issue -> Slice issue -> Agent -> PR -> PR integration -> CI -> Slice verification -> Merge -> Feature validation -> Acceptance -> Owner Doc`

Treat these Issue sections as binding for the governing slice issue:

- `Context`
- `Scope`
- `Source Anchors`
- `Constraints`
- `Acceptance Criteria`
- `Out of Scope`
- `Suggested Validation`
- `Source Docs`

## GitHub and Project rules

- GitHub Issue is the canonical implementation task contract.
- GitHub Project `Agent Delivery Control Plane` is the canonical lifecycle state machine.
- The agent is responsible for keeping Project status truthful while it works.
- Do not leave actively worked Issues in `Ready`.
- Do not leave blocked Issues in `In Progress`.
- Do not use `Review` only because a PR exists; keep work `In Progress` until review handoff is explicit.

Allowed labels:

- `type:task`
- `type:bug`
- `type:refactor`
- `prio:high`
- `prio:med`
- `prio:low`
- `agent:ready`
- `agent:blocked`
- `agent:needs-human`

Allowed Project statuses:

- `Backlog`
- `Ready`
- `In Progress`
- `Review`
- `Done`

## Issue selection rule before implementation

- Work from bounded slice issues, not from parent feature issues that still require decomposition or post-merge validation.
- Work only from GitHub Issues that are both `Status=Ready` and labeled `agent:ready`.
- Among ready issues, pick one of the highest available priority:
  - `prio:high` before `prio:med` before `prio:low`
- If several candidate issues share the same priority, use engineering judgment and prefer:
  - unblocked work with clear `Source Anchors`
  - bounded scope
  - work that unlocks dependent issues
  - work with the smallest safe implementation surface
  - work that reduces architectural fragmentation or rollout drift
- Do not pick a lower-priority issue while a clearly ready higher-priority issue is available unless you can justify the exception explicitly.
- If the chosen issue is stale, malformed, drifted, or too large, stop implementation and hand off to Issue maintenance before coding.
- If the chosen issue is clearly feature-level, references multiple child slices, or carries the full feature acceptance path, stop implementation and route through `feature-breakdown` or Issue maintenance before coding.

## Lifecycle rules during execution

- Before starting implementation, ensure the selected Issue is present in Project `Agent Delivery Control Plane`.
- If the Issue is missing from the Project, add it first.
- When you begin active work on an Issue, set Project Status to `In Progress` and remove `agent:ready`.
- If you determine the Issue is blocked before or during implementation:
  - do not continue coding
  - update labels and Project state truthfully
  - use `agent:blocked` when the work is blocked by dependency or setup
  - use `agent:needs-human` when the work requires a human decision or missing authority
  - move Project Status out of active execution if appropriate, normally back to `Backlog`
- If you open a draft PR or keep implementing after opening a PR, keep Project Status at `In Progress`.
- Move Project Status to `Review` only when the PR becomes the explicit review handoff artifact, normally after review is requested.
- Do not leave actively worked Issues in `Ready`.
- Do not leave blocked Issues in `In Progress` without an explicit blocker note and corrected labels.

## Execution rules

- Read the full Issue first.
- Read the owner docs and source docs referenced by `Source Anchors` before editing code.
- Stay strictly within Issue scope.
- Do not expand scope without updating the Issue contract first.
- Preserve architecture boundaries and event/outbox compatibility where relevant.
- Update docs in the same change if behavior, contracts, or architecture change.
- If the work turns a roadmap/plan item into shipped reality, update the owner doc and rewrite roadmap/plan wording so it no longer reads as pending.
- Do not collapse parent feature validation and owner-doc promotion into one slice PR by default.
- Use `Fixes #<issue>` in the PR.

## Source-anchor resolution rules

- Use the Issue’s `Source Anchors` as the first-choice source of doc authority.
- If an exact anchor ID is missing from the repo, do not stop automatically.
- Check whether the same bounded work is still clearly and authoritatively described in:
  - the referenced owner doc
  - the referenced roadmap, status, or track doc
  - the Issue’s own `Context`, `Scope`, `Constraints`, `Acceptance Criteria`, and `Source Docs`
- If the intended contract is still clear, continue implementation using the nearest authoritative passage and explicitly report `anchor drift`.
- If the intended contract is not clear enough to determine scope, constraints, or acceptance safely, stop and hand off to Issue maintenance before coding.

Block only on authority ambiguity, not on anchor-text absence alone.

When continuing through anchor drift:

- name the missing anchor
- name the fallback doc passage(s) being treated as authoritative
- keep implementation within the narrower interpretation
- recommend a follow-up issue or doc fix if anchor repair is still needed

## Implementation workflow

1. Select the Issue according to priority and readiness rules.
2. Ensure the Issue is in the Project, set Status to `In Progress`, and remove `agent:ready`.
3. Restate the bounded outcome from the Issue.
4. Read source-anchored docs and owning code paths.
5. If anchor drift exists, resolve it using the rules above before coding.
6. Implement the smallest complete change that satisfies Acceptance Criteria.
7. Add or update tests for the touched surface.
8. Update owner docs if shipped behavior/contracts changed.
9. Rewrite roadmap/plan wording if the delivered work was previously listed as pending.
10. Run `Suggested Validation` plus any obviously necessary focused checks.
11. Open or update a PR linked to the governing Issue.
12. Run `.codex/skills/pr-integration/SKILL.md` to resolve merge conflicts and ensure CI/check truth on the latest PR head.
13. Ensure Project Status is `Review` only once the PR is the active review handoff artifact.
14. If the slice merges but the parent feature still needs validation, keep that parent issue open for the later acceptance step.

## PR requirements

- PR body must link the Issue with `Fixes #<id>`.
- Confirm:
  - change stays within Issue scope
  - constraints were followed
  - acceptance criteria are satisfied
  - docs were updated in the same change when needed
  - owner docs and roadmap/plan wording were updated when the work became shipped reality

## Output format

1. Selected Issue and Selection Rationale
2. Lifecycle Actions Taken
3. Source Authority Used
4. Implementation Summary
5. Files and Surfaces Changed
6. Validation Run
7. Doc Writeback Performed
8. Risks / Follow-ups

If blocked, do not guess. Report the blocker only if one of these is true:

- missing doc authority after checking nearest authoritative passages
- stale or conflicting source docs that change scope materially
- unresolved architecture ambiguity
- dependency on another Issue

If blocked:

- do not code past the blocker
- correct Project status and labels so they reflect the blocked reality
- recommend Issue maintenance when the task contract itself needs correction

Do not block solely because an exact anchor label is absent if the governing doc passages still make the bounded task clear.
