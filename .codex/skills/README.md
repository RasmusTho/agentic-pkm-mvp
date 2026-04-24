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
- `prepare-promotion`
  - release-channel operator skill: produce a promotion plan diffing `main` against `stable` with code delta, migration delta (reversible vs forward-only), config delta, and risk notes; always runs before `execute-promotion`; governed by `docs/RELEASE_CHANNELS/DEFINE_PROMOTION_PLAN_CONTRACT.md`
- `execute-promotion`
  - release-channel operator skill: consume a reviewed and operator-acknowledged promotion plan; move the `stable` ref, apply migrations to the prod DB, restart the prod process; always follow with `verify-promotion`
- `verify-promotion`
  - release-channel operator skill: verify prod is healthy after `execute-promotion` or `rollback-promotion`; runs health, status, settings-explain, and smoke checks; appends a verification receipt to the promotion plan; PASS/FAIL only
- `rollback-promotion`
  - release-channel operator skill: restore `stable` to `stable-prev`, reverse reversible migrations, restart prod; call after `execute-promotion` failure or `verify-promotion` FAIL; always follow with `verify-promotion`; governed by `docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md`

## Connected execution paths

- Implementation path:
  `agentic-pkm -> issue-to-code -> publish-pr -> pr-integration -> verification-and-closure -> post-merge-owner-doc`
- Drift-correction path:
  `issue-maintenance-change-control -> issue-to-code` when the Issue becomes executable again
- Docs backlog path:
  `docs-authoring -> docs-to-issue`
- Temporal audit path:
  `temporal-doc-governance` and, when GitHub state is involved, `backlog-reconciliation-drift-audit`
- Release-channel promotion path:
  `prepare-promotion -> (operator review) -> execute-promotion -> verify-promotion`; on failure: `rollback-promotion -> verify-promotion`

If multiple skills seem relevant, prefer the narrower workflow skill over the generic repo-dev skill.

## Cross-cutting invariant: acceptance verifiability

Every Acceptance Criterion in a GitHub Issue must declare its verification inline with a `Verify:` marker — a test pointer for behavioral ACs, a concrete doc anchor / roadmap diff / runtime receipt for non-behavioral ACs. See `docs/development/DEV_WORKFLOW.md` ("Acceptance verifiability") for the canonical rule.

The invariant is enforced across the chain:

- Creation: `docs-to-issue`, `feature-breakdown`, `bug-to-issue` produce `Verify:`-bearing ACs.
- Repair: `issue-maintenance-change-control` treats missing `Verify:` as malformed contract.
- Consumption: `issue-to-code` gates on `Verify:` presence and runs test-first for behavioral ACs.
- Closure: `verification-and-closure` resolves every `Verify:` target before merge.

## Cross-cutting invariant: minimal shared leases

GitHub lifecycle state remains the human-visible projection, not the live operational store for
multi-agent exclusion. Hot-path workflows should use the smallest available shared issue or lane
lease check, then keep the rest of execution local and deterministic.

- `issue-to-code` owns fast issue claiming and should consult shared issue/lane leases when that
  surface is available.
- `publish-pr` and lane-aware workflows may consult lane or branch/worktree reservations when they
  share an active PR or workspace.
- `git-hygiene-preflight` is the read-only hot-path check for dirty tree, in-progress git
  operations, branch/worktree mismatch, and relevant lease conflicts.
- `git-hygiene-janitor` is a cold-path, report-first cleanup helper. It must respect active leases
  and must not perform destructive cleanup automatically in v1.
