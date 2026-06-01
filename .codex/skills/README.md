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
  - micro-skill: create one BuilderOps `LearningSignal` when a plan divergence occurs; invoke on divergence, not on normal work; use `docs/learning-log.md` only as historical/compatibility fallback
- `learning-retrospective`
  - cadence-triggered: read BuilderOps `LearningSignal` records and the generated learning-summary projection, include historical `docs/learning-log.md` compatibility entries only when needed, cluster by upstream artifact, and propose concrete edits for human review; when explicitly requested, run autonomous maintenance by applying safe governance fixes, creating Issues for unresolved work, and recording a BuilderOps retrospective receipt
- `learning-to-issue`
  - convert retrospective learnings (BuilderOps LearningSignals, historical learning-log compatibility entries, live PR/CI divergences) into canonical bounded GitHub Issues; also normalizes raw-intake issues created outside the standard contract
- `promote-to-test`
  - release-channel staged workflow: move a candidate commit into the isolated test channel; runs test-scoped channel-isolation preflight, prepare, execute, and verify; produces a durable test verification receipt required by `promote-test-to-prod`; fail-closed on channel binding mismatches
- `promote-test-to-prod`
  - release-channel staged workflow: promote a test-verified candidate to prod/stable; requires a PASS receipt from `promote-to-test` or an explicit emergency bypass receipt with operator risk note; orchestrates `prepare-promotion → execute-promotion → verify-promotion`; direct dev→prod is emergency bypass only and always produces a risk receipt
- `prepare-promotion`
  - release-channel low-level skill: produce a promotion plan diffing the candidate ref against the current stable/baseline with code delta, migration delta (reversible vs forward-only), config delta, and risk notes; used internally by the staged workflows; governed by `docs/RELEASE_CHANNELS/DEFINE_PROMOTION_PLAN_CONTRACT.md`
- `execute-promotion`
  - release-channel low-level skill: consume a reviewed and operator-acknowledged promotion plan; move the `stable` ref, apply migrations to the target DB, restart the target channel; used by `promote-test-to-prod`; always follow with `verify-promotion`
- `verify-promotion`
  - release-channel low-level skill: verify a channel is healthy after `execute-promotion` or `rollback-promotion`; runs health, status, settings-explain, and smoke checks; appends a verification receipt to the promotion plan; PASS/FAIL only; used by both staged workflows
- `rollback-promotion`
  - release-channel low-level skill: restore `stable` to `stable-prev`, reverse reversible migrations, restart prod; real prod vault is never rewound by rollback; call after `execute-promotion` failure or `verify-promotion` FAIL; always follow with `verify-promotion`; governed by `docs/RELEASE_CHANNELS/DEFINE_ROLLBACK_CONTRACT.md`

## Connected execution paths

- Implementation path:
  `agentic-pkm -> issue-to-code -> publish-pr -> pr-integration -> verification-and-closure -> post-merge-owner-doc`
- Drift-correction path:
  `issue-maintenance-change-control -> issue-to-code` when the Issue becomes executable again
- Docs backlog path:
  `docs-authoring -> docs-to-issue`
- Maintenance-learning intake path:
  `capture-learning -> learning-to-issue` (when the signal is ready for the backlog) or `learning-retrospective -> learning-to-issue` (when batched retro signals mature into bounded issues)
- Temporal audit path:
  `temporal-doc-governance` and, when GitHub state is involved, `backlog-reconciliation-drift-audit`
- Release-channel promotion path (normal — two-stage):
  `promote-to-test -> (test PASS receipt) -> promote-test-to-prod`
  where `promote-test-to-prod` internally runs: `prepare-promotion -> (operator review) -> execute-promotion -> verify-promotion`; on failure: `rollback-promotion -> verify-promotion`
- Release-channel promotion path (emergency bypass — direct dev→prod):
  `promote-test-to-prod --bypass-test-receipt --risk-note "<reason>"` — requires written operator risk note; produces a bypass receipt instead of a test verification receipt; not the default path

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
