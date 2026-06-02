State: Canonical builder-agent instruction file for this repository.
# Builder-Agent Instructions

This file applies to development-time builder agents and repo automation that modify, review, or validate this repository.

It does not apply to runtime/system agents that exist inside the product. Runtime/system-agent semantics live in `docs/AGENTS.md`, `docs/ARCHITECTURE.md`, and the concept contracts under `docs/CONCEPTS/`.

## Reading order

1. Read this file first.
2. Use `.codex/skills/README.md` to identify the repo-local skill path that matches the task.
3. Use `docs/DOCS_INDEX.md` to identify the owner document for the area you are touching.
4. Read the owner document before editing code or nearby docs.
5. Use `docs/development/DEV_WORKFLOW.md` for the working loop and validation expectations.
6. Use `docs/development/AGENT_INSTRUCTION_GOVERNANCE.md` for maintenance rules, rationale, and compatibility-entrypoint policy.
7. Before producing implementation guidance or touching code, apply `docs/development/AGENT_OPERATING_PROTOCOL.md` to classify the task, identify artifact class and channel risk, and confirm stop conditions are clear.

## Repo-local skill routing

Repo-local workflow helpers live under `.codex/skills/`. They do not replace this file, but agents should load the matching skill before substantial work when the task fits one of these routes:

- General repo dev work in this repository:
  `.codex/skills/agentic-pkm/SKILL.md`
- GitHub implementation work from a bounded Issue:
  `.codex/skills/issue-to-code/SKILL.md`
- Issue, PR, label, or Project lifecycle correction:
  `.codex/skills/issue-maintenance-change-control/SKILL.md`
- Epic, parent feature issue, Kanban/Project lane, or larger ready-issue set review, pickup planning, and delivery orchestration:
  `.codex/skills/deliver-issue-set/SKILL.md`
- Docs-only authoritative spec work:
  `.codex/skills/docs-authoring/SKILL.md`
- Convert active docs into bounded GitHub backlog:
  `.codex/skills/docs-to-issue/SKILL.md`
- Temporal current-state doc audit / freshness work:
  `.codex/skills/temporal-doc-governance/SKILL.md`
- Codex app automation cwd drift inspection / maintenance:
  `.codex/skills/automation-maintenance/SKILL.md`
- Branch / commit / push / PR publication after local work is ready:
  `.codex/skills/publish-pr/SKILL.md`
- PR mergeability / CI attachment before verification:
  `.codex/skills/pr-integration/SKILL.md`
- Delivery verification and feedback-loop closure:
  `.codex/skills/verification-and-closure/SKILL.md`
- Capture a BuilderOps learning signal for a divergence from plan:
  `.codex/skills/capture-learning/SKILL.md`
- Retrospective over BuilderOps learning signals to improve upstream artifacts:
  `.codex/skills/learning-retrospective/SKILL.md`
- Promote a reviewed commit from dev to stable prod (produce plan):
  `.codex/skills/prepare-promotion/SKILL.md`
- Execute an operator-acknowledged promotion plan:
  `.codex/skills/execute-promotion/SKILL.md`
- Verify prod health after promotion or rollback:
  `.codex/skills/verify-promotion/SKILL.md`
- Roll prod back to the previous stable ref:
  `.codex/skills/rollback-promotion/SKILL.md`

For GitHub implementation work, loading `.codex/skills/issue-to-code/SKILL.md` is mandatory before coding.
That skill owns the pickup rule:
when active work begins, move the governing Issue/Project state to `In Progress` and remove `agent:ready` before local edits so another agent does not pick up the same task.

Execution discipline:

- When a task clearly matches a repo-local workflow skill, load that skill before workflow-boundary actions in that lane.
- Publication actions (branch creation, commit creation, push, PR creation/update) route through `.codex/skills/publish-pr/SKILL.md` as the canonical publication boundary.
- Do not perform ad hoc publication flow first and retroactively map it to a skill; route through the matching skill before executing boundary actions.

Workflow state model:

- Issue state is for claim/active/block/closure flow: `Ready`, `In Progress`, `Blocked`, `Done`.
- PR/Project-item state is for review/integration/delivery projection: `Review`, `In Progress`, `Blocked`, `Done`.
- Default PR mode is open (non-draft). Draft PR is opt-in and requires an explicit reason.
- `Review` is the agent-review phase before verification; it is not a human-waiting synonym.
- PR/project `Done` should be projected by automation where possible; skills should only fallback-correct when projection drifts.
- `pr-integration` is a conditional repair/readiness step, not a mandatory hop after every publish.

BuilderOps Vault workflow boundary:

- BuilderOps Vault governs builder-operations material only. It does not change product/runtime truth, repo owner docs, code, tests, ADRs, or runtime contracts unless material is explicitly promoted through the normal GitHub/PR/repo authority path.
- Use BuilderOps records instead of direct repo-doc edits for operational state: `AgentWorklog` for raw builder-agent work notes, `LearningSignal` for delivery divergences, `DocsFreshnessRecord` for high-churn docs freshness state, `RoadmapExecutionItem` for roadmap execution movement, `PromotionIntent` for staged cross-surface proposals, and `BuilderOpsReceipt` for transitions, projections, promotions, supersessions, or discards.
- GitHub Issues remain the executable task-contract surface. Create or update an Issue when BuilderOps material becomes bounded implementation, governance, docs, or follow-up work that needs backlog ownership and `Verify:` targets.
- Open a PR only when repo-governed artifacts must change: code, tests, authoritative docs, ADRs, `.codex/skills/**`, `AGENTS.md`, or generated projections committed to the repo. A BuilderOps record alone is not a repo change.
- Use `PromotionIntent` before crossing authority classes. Promotion targets include GitHub Issue, PR/branch proposal, ADR/decision doc proposal, owner-doc or skill/AGENTS writeback proposal, generated projection, or discard receipt. Promotion is a reviewed boundary crossing, not automatic synchronization.
- Generated BuilderOps projections are repo-readable views, not source of truth. If a projection is stale, regenerate or reconcile from BuilderOps Vault; do not hand-edit the projection as authority.

## Change classification

Before editing, classify the change:

- `current-state correction`
  - Align code, tests, or docs to already-intended current behavior.
  - Update the owning current-state docs if reality changed or documentation was wrong.
- `enabling change`
  - Add bounded support that prepares a later target state without claiming that target state already exists.
  - Keep current-state docs honest about what is shipped now.
- `target-state / future-state work`
  - Do not write desired future behavior into current-state docs as if it were already true.
  - Put future-state intent in the relevant roadmap/plan docs and keep implementation claims explicit.

## Required rules

- Keep code, tests, and docs consistent in the same change.
- When behavior, architecture, or contracts change, update the owning docs in the same change.
- Keep normative content in the owner document; link instead of duplicating it.
- Do not turn `AGENTS.md` or `CLAUDE.md` into architecture, index, roadmap, or historical recordkeeping files.
- Keep builder-agent guidance separate from runtime/system-agent documentation.

## Docs authoring lane

Docs-only changes that evolve authoritative specification, roadmap, ADR, plan, human-flow, or governance surfaces may use the explicit docs-authoring PR lane without a governing GitHub Issue.

Rules:

- Use docs authoring only when the change is limited to approved docs-authoring surfaces and does not change code, runtime behavior, contracts, or shipped reality.
- Docs authoring prepares or clarifies authoritative repo docs; it does not replace later `docs-to-issue` backlog extraction.
- If the change affects implementation or delivered behavior, use the Issue-first implementation lane instead.

For longer explanations, maintenance rules, and compatibility-file policy, use the docs under `docs/development/`.

## Governance lane

Bounded repository-governance changes may use the explicit governance PR lane without a governing GitHub Issue.

The governance lane is a distinct work-stream for changes to delivery-system artifacts: skills, `AGENTS.md`, templates, and conventions. It is labeled `lane:governance` on Issues and PRs and has a filter view on the Project board.

Target artifacts:

- repo-local skills under `.codex/skills/**`
- pull request / issue governance surfaces under `.github/**`
- lightweight enforcement for docs/governance workflows such as `scripts/docs_guard.py`
- focused governance tests such as `tests/architecture/test_agent_skill_entrypoints.py`
- companion governance docs under `docs/**`

Governance specs live under `docs/development/`.

Acceptance shape: adoption evidence, not behavioral tests. Typical `Verify:` targets are doc presence, label existence, or observed adoption across the next N deliveries — not test-suite assertions.

Rules:

- Use governance lane only when the change is limited to repository governance, agent workflow, or lightweight enforcement.
- Do not use governance lane for product/runtime implementation or shipped feature behavior.
- Keep the change inside approved governance surfaces.
- If the change starts affecting product behavior, contracts, or delivered runtime capability, use the Issue-first implementation lane instead.

## GitHub delivery governance

For implementation work, GitHub Issues are the canonical task contract.

Builder-agent rules:

- Only pick work from a GitHub Issue that is both `Status=Ready` and labeled `agent:ready`.
- Read the full Issue before editing.
- Treat `Context`, `Scope`, `Source Anchors`, `Constraints`, `Acceptance Criteria`, `Out of Scope`, `Suggested Validation`, and `Source Docs` as binding.
- Every `Acceptance Criterion` must declare its verification inline with a `Verify:` marker: a concrete test pointer (`tests/...::test_name`) for behavioral criteria, or a concrete non-test target (doc writeback path plus anchor, runtime receipt, roadmap diff) for non-behavioral criteria. ACs without a resolvable `Verify:` target are not executable and the Issue must not be `agent:ready`.
- Link the PR back to the governing Issue using `Fixes #<id>`, `Closes #<id>`, or `Resolves #<id>`.
- If a PR changes files under `app/` or `tests/`, run `ruff check app tests` before merge and include the lint output or tooling limitation in the PR body. Docs-only PRs can keep validation lightweight and should not run full smoke by default unless the touched surface requires it.
- Do not treat chat-only requests as canonical implementation tasks when an Issue is expected.
- Do not expand scope beyond the Issue without updating the task contract first.
- Do not create new backlog work in GitHub without stable `Source Anchors` that point to the most local governing doc items.
- Prefer stable anchor IDs over prose fragments when the source doc is likely to produce multiple Issues over time.
- Treat GitHub Issues as the canonical backlog receipt. GitHub Project is the shared operating board when available; inline doc markers such as `Tracked by: #...` are secondary convenience notes only.
- Prefer Issues plus truthful agent labels and linked PR state as harder authority than Project state if they drift.
- Use Project `Status` as the pickup and coordination projection. `agent:ready` is only the pickup qualifier for `Status=Ready`; blocked labels belong on non-active work, and closed issues must not retain `agent:*` labels.
- When a PR delivers a tracked backlog item, update the owner doc to describe shipped reality and rewrite roadmap/plan wording so it no longer reads as pending work.
- Prefer GitHub REST endpoints for routine issue/label/PR operations; use GraphQL when REST does not express the required operation.
- When GraphQL is required, resolve stable identifiers once per run and reuse cached values instead of repeating lookup queries.
- Batch project-field GraphQL mutations into one bounded pass near workflow completion, rather than interleaving repeated mutations throughout intake.

## Dispatcher policy

The Agent Issue Dispatcher is an operational coordination layer for multi-agent issue pickup and execution.

**Database location:**
- Local dispatcher state lives in `runtime/dispatcher/dispatcher.sqlite3` (configurable via `DISPATCHER_STATE_DIR` env var).
- Dispatcher state directory is `.gitignore`'d and is not committed.

**Agent loop (normal case, dispatcher available):**
1. **Status check**: `dispatcher status --json` — verify `db_exists: true`; if false or exit non-zero, fall back to GitHub-label-only claim (see below).
2. **Next**: `dispatcher next --json --agent <agent_id>` — request next eligible `ready` task.
3. **Claim**: `dispatcher claim <task_id> --agent <agent_id> --ttl-minutes 90 --json` — acquire 90-minute lease.
4. **Confirm**: `gh issue edit <issue_number> --remove-label agent:ready` — confirm claim in GitHub (unchanged from current behaviour).
5. **Work**: execute issue scope (implementation, testing, doc updates).
6. **Heartbeat** (every ~30 min during active work): `dispatcher heartbeat <task_id> --agent <agent_id> --json` — renew lease before 90-min expiry.
7. **Closure**: `dispatcher complete <task_id> --agent <agent_id> --json` (successful work) or `dispatcher release <task_id> --agent <agent_id> --json` (abandoned/blocked).

**TTL and heartbeat cadence:**
- Lease TTL: **90 minutes** (default).
- Heartbeat interval: **~30 minutes** of active execution (before 90-min expiry).
- Agents must heartbeat before expiry or the dispatcher will mark the lease expired and the task becomes claimable by others.

**Fallback (dispatcher unavailable):**
- If `dispatcher status --json` returns `db_exists: false` or exits non-zero (missing DB, corrupted state, network failure, etc.):
  - Skip dispatcher entirely.
  - Use GitHub-label-only claim: `gh issue edit <issue_number> --remove-label agent:ready` (current behaviour, unchanged).
  - No dispatcher heartbeat or completion — GitHub label state is the only record.
  - **Log the fallback in the PR body** with the failure reason (e.g., "Dispatcher unavailable (db_exists: false) — used GitHub-label-only claim").
- If any dispatcher command fails during work (non-zero exit from heartbeat, update, etc.):
  - Log the failure, continue with local work, do not retry dispatcher commands in a loop.
  - At closure, attempt `dispatcher complete`; if it fails, continue with PR closure via GitHub.

**Multi-agent collision handling:**
- Dispatcher claims are atomic per lease and per agent ID.
- If two agents attempt to claim the same task, the dispatcher responds with a clear conflict error; the agent must fall back to GitHub-label-only or re-request `next`.
