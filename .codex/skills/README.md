State: Repo-local skill index for builder agents working in this repository.

# Repo-local Skills

Use this file after reading the repository root `AGENTS.md`.

These skills are workflow helpers, not replacements for the canonical builder-agent policy.

## Workflow map

Hot path:
`Docs -> Issue -> Project -> Issue maintenance -> Agent -> issue-to-code fast claim -> Publish PR -> CI -> Verification -> Merge -> Project/doc closure -> Owner Doc`

Conditional / maintenance path:
`Issue maintenance -> Agent` for stale or false backlog state, and `Publish PR -> pr-integration` only when readiness/repair work is still needed before verification.

## Skill routing

- `agentic-pkm`
  - default repo-dev context for code, tests, docs, and SoT reading order in this repository
- `issue-to-code`
  - implementation entrypoint for bounded GitHub Issue work
  - before coding, update lifecycle state truthfully: move active work to `In Progress` and remove `agent:ready`
  - use that transition as the minimal shared claim/lease compatibility signal in multi-agent environments
- `issue-maintenance-change-control`
  - repair stale or false Issue / PR / label / Project state before or during execution
- `docs-authoring`
  - docs-only authoritative authoring lane
- `docs-to-issue`
  - convert active docs into bounded backlog Issues
- `temporal-doc-governance`
  - audit and refresh time-sensitive current-state docs
- `publish-pr`
  - publication boundary for branch, commit, push, and PR creation after local work is ready
- `pr-integration`
  - readiness/repair path after `publish-pr` when the PR still needs mergeability, CI attachment, or review-feedback repair before verification
- `verification-and-closure`
  - final verification, merge, and delivery-state closure after implementation / PR work; honors automation-driven `Done` projection and only fallback-writes it when needed
- `post-merge-owner-doc`
  - invoked by `verification-and-closure` at merge time; reads the diff and decides whether any owner doc needs promotion, then acts on it
- `backlog-reconciliation-drift-audit`
  - backlog and GitHub-state reconciliation support when doc/backlog drift is the main problem
- `capture-learning`
  - micro-skill: append one structured divergence entry to `docs/learning-log.md` when a plan divergence occurs; invoke on divergence, not on normal work
- `learning-retrospective`
  - cadence-triggered: read `docs/learning-log.md` since last retro marker, cluster by upstream artifact, propose concrete edits for human review, append retro marker after human response

## Connected execution paths

- Implementation path:
  `agentic-pkm -> issue-to-code -> publish-pr -> pr-integration -> verification-and-closure -> post-merge-owner-doc`
- Drift-correction path:
  `issue-maintenance-change-control -> issue-to-code` when the Issue becomes executable again
- Docs backlog path:
  `docs-authoring -> docs-to-issue`
- Temporal audit path:
  `temporal-doc-governance` and, when GitHub state is involved, `backlog-reconciliation-drift-audit`

If multiple skills seem relevant, prefer the narrower workflow skill over the generic repo-dev skill.

## Cross-cutting invariant: acceptance verifiability

Every Acceptance Criterion in a GitHub Issue must declare its verification inline with a `Verify:` marker — a test pointer for behavioral ACs, a concrete doc anchor / roadmap diff / runtime receipt for non-behavioral ACs. See `docs/development/DEV_WORKFLOW.md` ("Acceptance verifiability") for the canonical rule.

The invariant is enforced across the chain:

- Creation: `docs-to-issue`, `feature-breakdown`, `bug-to-issue` produce `Verify:`-bearing ACs.
- Repair: `issue-maintenance-change-control` treats missing `Verify:` as malformed contract.
- Consumption: `issue-to-code` gates on `Verify:` presence and runs test-first for behavioral ACs.
- Closure: `verification-and-closure` resolves every `Verify:` target before merge.
