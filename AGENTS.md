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
- Publication actions (branch creation, commit creation, push, PR creation/update) route through `.codex/skills/publish-pr/SKILL.md` as the canonical publication boundary. This applies to every lane — implementation, feature-breakdown, docs-authoring, and governance — not only `issue-to-code`.
- The publication boundary enforces the branch-truth gate before commit and before push via `scripts/agent_workspace_preflight.sh --allow-dirty` (branch + worktree drift detection; dirty tree is expected at publish time). The boundary now **refuses** the shared root worktree by default — set `PKM_ALLOW_SHARED_ROOT=1` for deliberate solo work in the root.
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
- Repo-local workflow skills and Codex app automation prompts must carry BuilderOps routing checks directly. Do not rely on a human remembering where learning logs, docs freshness notes, roadmap movement, or worklog material should go.

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
- **Invariant → producers rule:** when you add a runtime precondition (a new invariant the runtime fail-exits without), update *every producer* of the guarded resource (init/bootstrap scripts, existing-resource migration, in-process test fixtures) **and** add a fail-loud preflight, in the same change. A precondition without migrated producers is a latent outage (the #1991 vault-init half-application caused the 2026-06-14 promotion slog). See `.codex/skills/prepare-promotion/SKILL.md :: Invariant → producers rule` and the `harness-selfverify` CI gate.
- Keep normative content in the owner document; link instead of duplicating it.
- Do not turn `AGENTS.md` or `CLAUDE.md` into architecture, index, roadmap, or historical recordkeeping files.
- Keep builder-agent guidance separate from runtime/system-agent documentation.

## Total Cost of Development (capability routing)

TCD is the standard principle for all agentic development work in this repo. Every workflow chooses a *capability* — not just a model — to minimize the expected **total cost per accepted delivery**, not the cost of the cheapest single model run. Existing repo-local skills stay the primary workflow entrypoints; this policy chooses capability *within* them. Skills reference this section as `AGENTS.md :: Total Cost of Development`; they must not restate it.

Capability = workflow/skill + model + reasoning effort + context discipline + tool choice + verification level + review gate. Choose model **and** reasoning effort actively; never leave both on default.

TCD = C_model + C_reasoning + C_context + C_tools + C_parallelization + C_human + C_rework + C_defect + C_delay + C_coordination.

Human time is the dominant term: **R_human = 100 USD/hour** (1 min ≈ 1.67 USD; 10 min ≈ 16.7 USD; 15 min ≈ 25 USD). The owner runs x5 Codex and x5 Claude subscriptions, so budget pressure is **medium-low but not zero**.

Decision rule — spend more capability (stronger model, higher reasoning, more specialized workflow, deeper review) when:

`ΔC_AI_capability  <  100 · ΔT_human(hours)  +  ΔC_rework  +  ΔC_defect  +  ΔC_delay  +  ΔC_coordination`

- Do not under-model: a too-weak model or too-low reasoning is *expensive* through extra iterations and human steering.
- Do not over-model: Opus/xhigh on trivial, locally verifiable work burns budget and latency for no gain.
- Optimize for accepted delivery, not the cheapest single run.

Primary optimization order: 1) cut human time, 2) cut rework, 3) cut hidden defects, 4) cut interruptions/delay, 5) cut unnecessary model/reasoning spend.

Model + reasoning policy — Claude:

- **Haiku / low effort** — mechanical, low-risk, trivial transforms, easily verifiable output. Never for architecture, unclear requirements, or hidden correctness risk.
- **Sonnet / medium effort** — DEFAULT for normal development: implementation, refactor, normal debugging, test creation, normal review, docs where quality matters.
- **Sonnet / high effort** — multiple files, real design choices, unclear test strategy, review with non-trivial risk, or a prior attempt failed.
- **Opus / high–xhigh effort** — architecture, unclear requirements, high defect cost, hard bugs, risk review, system/agent/workflow design, complex dependencies, or when human review would otherwise be expensive.
- **Opus + Ultra Code / xhigh–max effort** — complex orchestration, repo-wide design, and security / data / migration / auth / concurrency / payments / external-API work, where the wrong direction costs more than the extra model spend.

Model + reasoning policy — Codex: read the actual repo/session/config for the current Codex model and reasoning level; do not assume hardcoded values. Normal coding = standard Codex model + **medium** reasoning. Reasoning ladder: **minimal** (strict mechanics, search/replace, formatting, auto-tested output) · **low** (simple local low-risk) · **medium** (default interactive coding, test fixes, small refactors) · **high** (hard debugging, multi-file/multi-layer, test strategy, design trade-offs, risky review) · **xhigh** (architecture, migrations, auth/security/data, concurrency, external APIs, long autonomous tasks, complex workflow design, or when human steering would likely exceed 10–15 min). Propose a Codex model/reasoning change only when TCD justifies it.

Escalation triggers (raise model and/or reasoning, or route to a more specialized skill) — any of:

- two failed attempts, or a reviewer reject twice
- requirements unclear; tests missing or hard to interpret
- output would need more than ~10 minutes of human steering
- multiple layers, hidden invariants, or high defect blast radius
- auth / security / data / migration / concurrency / payments / external API touched
- non-trivial CI failure; residual risk hard to assess.

De-escalation triggers (lower model/reasoning, narrow context) — when:

- the plan is clear and decomposed into mechanical steps
- the change is local and a test verifies the output
- risk is low, output is quickly reviewable, and no hidden correctness risk remains.

Budget posture: when usage limits are not near, prefer the stronger model/reasoning if it saves human time or cuts defect risk. When limits are near, reserve strong capability for planning and review, run mechanical execution on cheaper/lower-reasoning capability, cut context, split work into focused steps, and avoid sub-agent fan-out.

Tools & GitHub: use shell, `gh`/REST, CI data, Issues, and PR context when they lower TCD — allowed *and* appropriate *and* necessary — not merely because they are available. Always read `git status` before changes and review `git diff` before reporting a code change. Do not push, force-push, delete branches/tags, release, or publish unless the task requires it. Propose CI/GitHub Actions improvements when they reduce TCD; when CI/test results already exist locally or on GitHub, use them as the verification source.

### Agency default (minimize human time)

Human time is the dominant TCD term, so the default posture is to **act**, not to ask. Skills reference this as `AGENTS.md :: Agency default`. Within the guardrails, prefer **Act** (do it, log it, let Git be the audit trail) or **agent-review** (a second agent verifies) over **ask-the-owner**.

- Escalate to the human (`agent:needs-human` / "ask you") **only** for decisions that are irreversible, external-facing, or genuinely ambiguous in authority — not for work that is merely non-trivial. `agent:needs-human` on a buildable, bounded slice is usually defensive posture: classify on evidence first, and defer only when a named human decision, missing input, or authority question actually blocks the work.
- `log + Git` is the safety net, not a human gate. Reversible, in-scope, bounded work proceeds without asking.
- **Autonomous delivery** runs the full gate chain unattended: wait for CI green and resolve Codex review, then merge — the owner is not asked to babysit. The CI + review gate is never waived (an unprotected branch does not relax it); only the human *watching* is removed. Quality is preserved by the gate, not by the wait.

This is human-first, not human-absent: the owner still owns irreversible, external, and strategic calls — agents just stop interrupting for reversible ones.

### Parallel-agent execution (minimize coordination cost and error)

Many agents run against this repo at once. C_coordination, C_delay, and C_rework dominate when they collide, so isolation is the default, not an upgrade. Skills reference this as `AGENTS.md :: Parallel-agent execution`.

- **Dedicated worktree by default.** Any concurrent implementation or publication runs in its own `git worktree`, never the shared root worktree. Do not edit, commit, or push from the shared root checkout while other agents may be active. The publish/claim boundary (`scripts/agent_workspace_preflight.sh`) enforces this by default and refuses the shared root worktree — set `PKM_ALLOW_SHARED_ROOT=1` for deliberate solo work in the root.
- **Never switch the shared root worktree's branch out from under a concurrent agent.** Branch switches happen in your own worktree. The shared-root HEAD thrash is a real, recurring loss — uncommitted work rides an unexpected checkout.
- **Branch-truth before write.** Capture `EXPECTED_BRANCH` / `EXPECTED_WORKTREE` at branch creation and run the branch-truth gate before commit and before push (`_shared/BRANCH_TRUTH_GATE.md`). Proportionality never relaxes this.
- **Smallest shared lease, then local.** Claim the issue/lane with the minimal shared handshake (`Ready -> In Progress`, remove `agent:ready`), then keep execution local and deterministic. One active lease per issue.
- **Right-size fan-out.** Parallelize only independent issues with isolated worktrees, explicit return receipts, and an explicit token/quality rationale. Over-fanning raises C_coordination faster than it cuts C_delay — when in doubt, fewer agents.
- **Reconcile races on evidence, do not redo.** On a claim or delivery collision, the latest unreleased lease governs; verify on `origin/main` and close your duplicate rather than re-implementing.
- **Shared-budget awareness.** The GitHub API budget (5,000/hr) is shared across every concurrent agent, and GraphQL exhausts first. A tool call's real cost is its *marginal cost to all agents*, not to your task — so never busy-wait on a shared budget, prefer the transport that spares the scarce bucket (REST `gh api` over GraphQL `gh pr`/`gh issue`/`gh repo`; `git push --delete` over the API for branch ops), and read the free `gh api rate_limit` endpoint before assuming exhaustion. The same rule covers any pooled resource (CI runners, the embedding/Ollama queue). For waiting on CI checks and the Codex verdict specifically, follow `_shared/CI_WAIT_CONTRACT.md` — a tight `gh pr checks` loop drains the shared GraphQL bucket to zero and stalls every other agent.

### TCD output blocks

Planning/decomposition, review/verification, and retrospective skills reference these blocks by name instead of restating the policy. Emit only the block a skill calls for, and fill only the fields that skill's own output already implies.

`tcd_plan` — planning / decomposition:

```yaml
tcd_plan:
  task_summary:
  assumptions:
  complexity: low|medium|high|very_high
  risk: low|medium|high|critical
  verification_difficulty: easy|moderate|hard
  human_review_burden: low|medium|high
  defect_blast_radius: low|medium|high|critical
  budget_pressure: low|medium|high
  recommended_capability:
    workflow_or_skill:
    model_family:
    reasoning_effort:
    tools:
    github_context_required: true|false
  cheapest_acceptable_path:
  escalation_triggers:
  deescalation_triggers:
  review_gate:
```

`tcd_review` — review / verification, or any skill that produces or gates a code change:

```yaml
tcd_review:
  verdict: accept|reject|accept_with_risk
  risk_level: low|medium|high|critical
  model_used:
  reasoning_effort_used:
  under_modeling_detected: true|false
  over_modeling_detected: true|false
  blocking_issues:
  non_blocking_issues:
  missing_tests:
  hidden_defect_risks:
  recommended_fixes:
  recommended_model_for_fix:
  recommended_reasoning_for_fix:
  residual_risk:
```

`tcd_retrospective` — retrospective:

```yaml
tcd_retrospective:
  task:
  chosen_route:
  actual_iterations:
  estimated_human_minutes:
  model_used:
  reasoning_effort_used:
  under_modeling_detected: true|false
  over_modeling_detected: true|false
  missed_risk:
  routing_policy_update_recommendation:
  skill_update_recommendation:
```

## Communicating with the owner

The owner is the operator and decision-maker. Human-first means optimizing for the owner's time **and cognitive load**: fast decision support, low running cost, and the fewest things he must hold in his head — not narrating how you got there. Cognitive load is a real cost (part of C_human), not just clock-time.

- Lead with next steps and the answer. Keep responses concise and scannable; do not include a verbose reasoning trace.
- **Minimize cognitive load.** Bundle coherent work into one PR/thread instead of scattering it; collapse options to a recommendation plus the one fork that is genuinely the owner's; never make him reconstruct context or track machinery he does not need.
- When a decision is the owner's to make, present it as: clear **Problem → Options → Consequences** (the consequences of each choice matter most). Surface the decisions that are genuinely his explicitly rather than burying them — without manufacturing choices he should not have to make.
- Keep durable audit artifacts complete but separate from the human-facing summary: BuilderOps receipts, `Verify:` markers, and traceability live in the record, not in the lead. Do not add machinery whose only purpose is to capture reasoning for audit.

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
