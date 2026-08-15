State: Canonical builder-agent instruction file for this repository.
# Builder-Agent Instructions

This file applies to development-time builder agents and repo automation that modify, review, or validate this repository.

It does not apply to runtime/system agents that exist inside the product. Runtime/system-agent semantics live in `docs/AGENTS.md`, `docs/ARCHITECTURE.md`, and the concept contracts under `docs/CONCEPTS/`.

## Reading order

Citations in this file follow `.codex/skills/_shared/READ_SCOPE.md`: a `FILE :: Section` citation
means **read that section only**, a citation with no `::` is a whole-file read and states why, and a
citation under a condition is read only when the condition holds. Conditions key off the actual diff
(`git diff --name-only origin/main...HEAD`), not the issue's declared scope.

Required at session entry, before the task type is known:

1. This file's `Reading order`, `Repo-local skill routing`, `Required rules`,
   `Total Cost of Development` (any agent choosing its own capability), and
   `Proportional delivery` sections. Read the remaining sections of this file only under the
   conditions below.
2. `.codex/skills/README.md :: Skill routing` to identify the repo-local skill path that matches the
   task, then load that skill. The skill states what else it needs.

Read on condition, not by default:

3. `docs/DOCS_INDEX.md` — **grep-only**. It is ~250 KB / 700 rows; `grep` it for the work area to
   locate the owner document. Never read it whole. Then read the owner document itself before
   editing code or nearby docs.
4. `docs/development/DEV_WORKFLOW.md :: Validation baseline` before running or reporting validation,
   and `:: Working loop` when the loop itself is unclear. Other sections of that file are
   reference material for the workflows that own them.
5. `AGENTS.md :: Change classification` when the change touches a current-state doc, roadmap, or
   status surface.
6. `AGENTS.md :: Docs authoring lane` or `:: Governance lane` when the work will be published without
   a governing Issue; `AGENTS.md :: GitHub delivery governance` when publishing an issue-backed PR.
7. `AGENTS.md :: Communicating with the owner` before writing a report or escalation to the owner,
   and `:: Specialist subagent roles` before dispatching subagents.
8. `docs/development/AGENT_INSTRUCTION_GOVERNANCE.md :: Maintenance rules` and
   `:: Canonical entrypoints` (compatibility-entrypoint policy) when the diff changes an
   instruction artifact (`AGENTS.md`, `CLAUDE.md`, `.codex/AGENTS.md`, `.codex/skills/**`). Note the
   `Maintenance rules` requirement that a change to canonical entrypoints, reading order, or doc
   roles updates `docs/DOCS_INDEX.md` in the same change.
9. `docs/development/AGENT_OPERATING_PROTOCOL.md :: Required pre-implementation checks`,
   `:: Behavioral rules`, and `:: Stop conditions` before producing implementation guidance or
   touching code, when the loaded skill does not already inline that classification step.
   `issue-to-code` inlines all three.

## Repo-local skill routing

Repo-local workflow helpers live under `.codex/skills/`. They do not replace this file, but agents should load the matching skill before substantial work when the task fits one of these routes:

- General repo dev work in this repository:
  `.codex/skills/agentic-pkm/SKILL.md`
- Resume interrupted dev/build work after a session breaks (quota, network, hung command, tool failure, context loss):
  `.codex/skills/resume-work/SKILL.md`
- GitHub implementation work from a bounded Issue:
  `.codex/skills/issue-to-code/SKILL.md`
- Issue, PR, label, or Project lifecycle correction:
  `.codex/skills/issue-maintenance-change-control/SKILL.md`
- Epic, parent feature issue, Kanban/Project lane, or larger ready-issue set review, pickup planning, and delivery orchestration:
  `.codex/skills/deliver-issue-set/SKILL.md`
- Docs-as-code ownership, anti-sprawl, DOCS_INDEX impact, or docs workflow routing decisions:
  `.codex/skills/docs-governance/SKILL.md`
- Claude Design projects, UI/component prototypes, visual audits, and governed design handoffs:
  `.codex/skills/yggdrasil-design-handoff/SKILL.md`
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
when active work begins, acquire the dispatcher claim when available and remove `agent:ready` before local edits so another agent does not pick up the same task. GitHub Project Status is an optional projection, not a pickup dependency.

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

`C_context` includes input tokens, repeated instruction and owner-doc loads, context-pack size,
tool output retained in the active buffer, compaction/reload cost, and the defect risk of a crowded
context window. `C_parallelization` includes the duplicated input context plus model/tool work of
every agent start. Delegation is cheaper only when the saved human time, delay, rework, or defect
risk exceeds those incremental costs; a fresh context can improve quality while still increasing
total tokens.

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

Model + reasoning policy — Codex: read the actual repo/session/config for the current Codex model and reasoning level; do not assume hardcoded values. OpenAI model names carry a durable capability tier (**Sol** = highest ceiling, **Terra** = balanced default, **Luna** = fast/cheap; introduced with GPT-5.6) that advances across generations — route by tier the same way the Claude ladder routes by model, resolving the tier to the current generation's model id at config time:

- **Luna / minimal–low reasoning** — mechanical, low-risk, auto-verifiable transforms (mirrors Haiku). Never for architecture, unclear requirements, or hidden correctness risk.
- **Terra / medium reasoning** — DEFAULT for normal development: implementation, refactor, test fixes, small refactors, normal review (mirrors Sonnet/medium).
- **Terra / high reasoning** — hard debugging, multi-file/multi-layer, test strategy, design trade-offs, risky review (mirrors Sonnet/high).
- **Sol / high–xhigh reasoning** — architecture, migrations, auth/security/data, concurrency, external APIs, long autonomous tasks, complex orchestration/workflow design, or when human steering would likely exceed 10–15 min (mirrors Opus).

The tier bullets above are authoritative for the reasoning ladder as well (minimal–xhigh, unchanged semantics); do not maintain a separate reasoning table. Propose a Codex model/reasoning change only when TCD justifies it.

Escalation triggers (raise model and/or reasoning, or route to a more specialized skill) — any of:

- two failed attempts, or a reviewer reject twice
- requirements unclear; tests missing or hard to interpret
- output would need more than ~10 minutes of human steering
- multiple layers, hidden invariants, or high defect blast radius
- auth / security / data / migration / concurrency / payments / external API touched
- non-trivial CI failure; residual risk hard to assess.

For auth, security, data, migration, concurrency, external-API, credential-durability, or explicit
state-machine work, put the cheapest adequate mechanism/convergence review before an expensive
full-suite or CI handoff. If one review round reports multiple blockers in the same stateful
mechanism, or a later round finds an adjacent blocker in that mechanism, stop point-fixing and run
the mechanism-level convergence gate in
`docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md` before another expensive proof cycle.
This gate does not replace current-SHA CI or the final independent review gate, and it does not reset
repair history or finding/mechanism binding.

De-escalation triggers (lower model/reasoning, narrow context) — when:

- the plan is clear and decomposed into mechanical steps
- the change is local and a test verifies the output
- risk is low, output is quickly reviewable, and no hidden correctness risk remains.

Budget posture: when usage limits are not near, prefer the stronger model/reasoning if it saves human time or cuts defect risk. When limits are near, reserve strong capability for planning and review, run mechanical execution on cheaper/lower-reasoning capability, cut context, split work into focused steps, and avoid sub-agent fan-out. External provider capacity is a Builder System scheduling signal: when available capacity is low or uncertain, preserve high-capability capacity for high-priority or time-critical delivery and required verification, and pause, defer, or safely downgrade lower-priority work before it risks that reserve. Record a visible capacity decision or deferral with freshness and uncertainty; follow `docs/architecture/SBS_OPERATING_MODEL.md :: Provider-Capacity Admission Policy` for its evidence, boundary, and deferred-scope rules.

Tools & GitHub: use shell, `gh`/REST, CI data, Issues, and PR context when they lower TCD — allowed *and* appropriate *and* necessary — not merely because they are available. Always read `git status` before changes and review `git diff` before reporting a code change. Do not push, force-push, delete branches/tags, release, or publish unless the task requires it. Propose CI/GitHub Actions improvements when they reduce TCD; when CI/test results already exist locally or on GitHub, use them as the verification source.

### Agency default (minimize human time)

Human time is the dominant TCD term, so the default posture is to **act**, not to ask. Skills reference this as `AGENTS.md :: Agency default`. Within the guardrails, prefer **Act** (do it, log it, let Git be the audit trail) or **agent-review** (a second agent verifies) over **ask-the-owner**.

- Escalate to the human (`agent:needs-human` / "ask you") **only** for decisions that are irreversible, external-facing, or genuinely ambiguous in authority — not for work that is merely non-trivial. `agent:needs-human` on a buildable, bounded slice is usually defensive posture: classify on evidence first, and defer only when a named human decision, missing input, or authority question actually blocks the work.
- `log + Git` is the safety net, not a human gate. Reversible, in-scope, bounded work proceeds without asking.
- A retry count, a failed local/CI/type check, a host/tool compatibility failure, or a safe fail-closed pause is **not** by itself an owner decision. Route it through the autonomous escalation classifier in `docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md`; only its explicit authority categories may create `agent:needs-human`.
- Owner asks route through `.codex/skills/owner-decision-brief`, the thin Yggdrasil profile for the
  portable `decision-quality` method: discretionary escalations re-test this gate first (contractual
  operator gates are never re-tested away — they fire as their skills define), and every ask that
  reaches the owner is delivered as one standalone plain-language decision brief.
- **Autonomous delivery** runs its tier's gate chain unattended per `AGENTS.md :: Proportional delivery`: on the light path (single-issue or issue-free Tier 1/2), wait for required CI green with self-verified `Verify:` targets, then merge; on the full path (Tier 3, multi-issue, TCD high-risk surfaces), also resolve the local review gate (`verification-and-closure :: Running the local review gate`) before merging — the owner is not asked to babysit either way. The governing tier's gate is never waived (an unprotected branch does not relax it); only the human *watching* is removed. Quality is preserved by the gate plus cheap reverts on an always-releasable main, not by the wait.

This is human-first, not human-absent: the owner still owns irreversible, external, and strategic calls — agents just stop interrupting for reversible ones.

### Parallel-agent execution (minimize coordination cost and error)

Many agents run against this repo at once. C_coordination, C_delay, and C_rework dominate when they collide, so isolation is the default, not an upgrade. Skills reference this as `AGENTS.md :: Parallel-agent execution`.

- **Dedicated worktree by default.** Any concurrent implementation or publication runs in its own `git worktree`, never the shared root worktree. Do not edit, commit, or push from the shared root checkout while other agents may be active. The publish/claim boundary (`scripts/agent_workspace_preflight.sh`) enforces this by default and refuses the shared root worktree — set `PKM_ALLOW_SHARED_ROOT=1` for deliberate solo work in the root.
- **Register the full worktree lifecycle.** After claim, register the dedicated checkout with `scripts/agent_worktree.py register`; heartbeat it during active work and review-fix waits, then record `release` or `complete` explicitly. Cleanup is report-only by default and may remove a worktree only when its generation-bound lifecycle record is expired, the live path/branch/HEAD still match, the checkout is clean and unlocked, no active lease remains, and merge/closure eligibility is proven. Active, locked, dirty, mismatched, replaced-generation, orphaned, or unregistered worktrees are preservation evidence, never cleanup candidates. Cleanup must not hold the lifecycle lock across fetch or planning; it revalidates lifecycle authority under a short lock held through each targeted worktree removal so a timely heartbeat can establish preservation authority. Before Git removal it durably records a generation-bound `removal_pending` transition. Successful removal durably retires that exact generation before branch deletion; restart reconciliation completes only a pending transition and never infers removal from an ordinary missing lifecycle record. Broad metadata pruning remains report-only.
- **Branch deletion needs path *and* branch authority, on every invocation.** Deleting a branch after its worktree was removed is irreversible (`git branch -D` under a merged/closed-PR proof), so cleanup revalidates both the `worktree:<path>` and the `branch:<branch>` lease identity immediately before the delete and fails closed if either is claimed — including a path lease acquired after the removal, up to that revalidation. The revalidation reads a foreign lease file it cannot lock, so it is a check-then-act guard, not mutual exclusion: a lease that first becomes active in the sub-window between that read and the delete is not seen. Path identity is not spelling-bound — raw, canonical, case-folded and Unicode-normalised spellings all match, because the default developer filesystem treats them as one directory. Removal tombstones the lifecycle record instead of dropping it, so the path→branch association outlives the checkout: a later cleanup run still binds that branch to its former worktree path and preserves it while the path lease is active, rather than reclassifying it as an ordinary local branch. Because the registry is keyed by path, re-registering that path for a new branch would otherwise replace the tombstone; the displaced binding is carried forward on the new record (`prior_bindings`, deduplicated by branch and bounded to the 8 most recent), so the former branch keeps that path's lease authority across path reuse. The whole guarantee is bound to that durable registry, so `--apply` refuses to run at all when the registry is missing or corrupt.
- **Never switch the shared root worktree's branch out from under a concurrent agent.** Branch switches happen in your own worktree. The shared-root HEAD thrash is a real, recurring loss — uncommitted work rides an unexpected checkout.
- **Branch-truth before write.** Capture `EXPECTED_BRANCH` / `EXPECTED_WORKTREE` at branch creation and run the branch-truth gate before commit and before push (`_shared/BRANCH_TRUTH_GATE.md`). Proportionality never relaxes this.
- **Smallest shared lease, then local.** Claim the issue/lane with the minimal shared handshake (dispatcher lease when available; otherwise remove `agent:ready` and post a claimant receipt), then keep execution local and deterministic. One active lease per issue.
- **Context ownership hierarchy.** For issue-set delivery, the root delivery session is the
  coordinator. It retains only cross-issue scope, dependencies, readiness, dispatch/slot decisions,
  live lifecycle truth, typed conflicts, and compact receipts. Every independent non-trivial Issue
  runs end to end in a fresh issue agent and isolated worktree, whether the queue is serial or
  concurrent. The coordinator may execute only deterministic scripts or work explicitly classified
  `inline-local-cheaper`; do not insert a separate coordinator subagent between the root and issue
  agents. Fresh-context isolation is distinct from concurrency.
- **Bounded issue-local help.** A complex issue agent may run at most one active depth-2 helper at a
  time when a bounded independent read-heavy investigation, source check, test/log analysis, or
  fresh review lowers expected TCD. The issue agent remains the sole claim, lifecycle, write,
  integration, and receipt owner. The helper receives only issue-local context, is read-only by
  default, may not mutate GitHub/Project lifecycle, publish or merge, write owner docs, coordinate
  with sibling issue agents, or spawn another agent. It consumes a global slot and must not displace
  ready issue work without an explicit context/token, delay, or quality benefit. Tier 1/2 light-path
  work normally has helper budget zero, and budget one requires a bounded complexity/TCD rationale.
  Native Codex `max_threads = 3` is a per-primary-session subagent cap; separate `codex exec`
  primary sessions do not thereby share one native pool. Repository scheduling intentionally exposes
  only two usable non-root slots so one remains available for verification/recovery. Within that
  policy budget, any active issue agent with helper budget one reduces concurrent issue-agent
  capacity to one; a two-worker wave requires both helper budgets to be zero until a slot is released.
- **Compact boundaries.** Cross-issue context enters an issue agent only as exact dependency
  receipts, current authority references, shared constraints, and the bounded issue contract. Raw
  sibling transcripts, exploration, test logs, and implementation reasoning stay issue-local. The
  issue agent returns a compact terminal receipt; reopen raw context only when the receipt is
  incomplete, contradictory, or fails live GitHub/Git/CI/review readback. Resume an agent only for
  the same Issue and unchanged authority; never reuse it for a sibling Issue.
- **Right-size fan-out.** Give each independent non-trivial Issue a fresh agent, then decide
  separately whether those agents should run serially or concurrently. Concurrent waves require
  isolated worktrees, explicit receipts, typed conflict checks, and a token/quality/delay rationale.
  Over-fanning raises C_context and C_coordination faster than it cuts C_delay; reserve capacity for
  verification/recovery and use fewer simultaneous agents when evidence is weak.
- **Reconcile races on evidence, do not redo.** On a claim or delivery collision, the latest unreleased lease governs; verify on `origin/main` and close your duplicate rather than re-implementing.
- **Shared-budget awareness.** The GitHub API budget (5,000/hr) is shared across every concurrent agent, and GraphQL exhausts first. A tool call's real cost is its *marginal cost to all agents*, not to your task — so never busy-wait on a shared budget, prefer the transport that spares the scarce bucket (REST `gh api` over GraphQL `gh pr`/`gh issue`/`gh repo`; `git push --delete` over the API for branch ops), and read the free `gh api rate_limit` endpoint before assuming exhaustion. The same rule covers any pooled resource (CI runners, the embedding/Ollama queue). For waiting on CI checks (and the optional `--codex` verdict path, inactive as the default gate) specifically, follow `_shared/CI_WAIT_CONTRACT.md` — a tight `gh pr checks` loop drains the shared GraphQL bucket to zero and stalls every other agent.
- **Atomically lease host-global validation.** Run repo-wide local suites and other host-global
  commands through `scripts/run_with_host_lease.py`; the repo-common kernel file lock is the
  exclusion authority across worktrees. Chat reservations, process census, polling, and
  quiet-period observations are advisory only and must not authorize a run. If the lease is held,
  fail or wait boundedly; never interrupt the holder. Do not background a leased command.
- **Fail-closed gate composition.** Any command whose exit code gates a subsequent action (commit, push, merge, receipt) must run bare with its status captured directly (`rc=$?`) — never composed with `|| echo`, `| tail`, `| grep`, backgrounding, or anything that substitutes another command's exit status for the gate's. A gate whose failure mode is silent success is not a gate. (Instances: BRANCH_TRUTH_GATE `|| echo` 2026-06-13; PR #2759 pipe-masked merge gate 2026-07-02.)

### Transition-period bug-delivery policy

This is Builder System transition-period delivery policy only. It does not describe
Product/Runtime truth and does not claim that a future deterministic orchestrator is shipped.

For larger `type:bug` issue sets, use a minimal-context coordinator/dispatcher: Codex Luna / low
reasoning is appropriate for deterministic read-only intake, live classification, lifecycle
snapshots, and task dispatch; use Terra / medium only when that coordination requires judgment.
The coordinator does not implement claimed bugs. Each claimed bug runs end-to-end in its own Codex
task/session and isolated worktree. Default to serial delivery: no more than one active bug
implementation. An independent wave may exceed that only with an explicit TCD rationale covering
independence, coordination cost, isolated worktrees, and expected quality or delay benefit.

Each bug implementation normally uses Codex Terra / medium. Escalate to Terra / high or Sol /
high–xhigh only under the existing TCD escalation triggers or protected P0/P1/high-risk surfaces;
resolve tier names to the current generation rather than hardcoding a generation-specific model.
Severity and deferred-defect authority remain in
`docs/development/AUTONOMOUS_REVIEW_REPAIR_GATE_CONTRACTS.md` and `bug-to-issue`: only P0/P1
findings enter repair/re-review; a confirmed P2 leaves the active PR unchanged and is recorded in
the rolling Known Defects registry Issue #4172 with a `deferred` disposition and reply on the
original review thread; P3 is informational/non-defect. Protected AC, data, authority, invariant,
and other protected findings cannot be downgraded to P2/P3.

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
  execution_context: coordinator_only|inline_deterministic|fresh_issue_agent
  issue_local_helper_budget: 0|1
  context_cost:
    measurement: estimated|actual|proxy
    input_tokens: <integer|unknown(reason)>
    agent_starts: <integer>
    context_pack_bytes: <integer|unknown(reason)>
    compactions: <integer|unknown(reason)>
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
  context_cost:
    measurement: actual|proxy
    input_tokens: <integer|unknown(reason)>
    agent_starts: <integer>
    context_pack_bytes: <integer|unknown(reason)>
    compactions: <integer|unknown(reason)>
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
  context_cost:
    measurement: actual|proxy
    input_tokens: <integer|unknown(reason)>
    agent_starts: <integer>
    context_pack_bytes: <integer|unknown(reason)>
    compactions: <integer|unknown(reason)>
  under_modeling_detected: true|false
  over_modeling_detected: true|false
  missed_risk:
  routing_policy_update_recommendation:
  skill_update_recommendation:
```

## Proportional delivery (chain depth and solution size)

TCD chooses capability *inside* the delivery chain; this section chooses how much chain and how much solution a change pays for. Skills reference it as `AGENTS.md :: Proportional delivery`; the per-tier mechanics live in `docs/development/GOVERNANCE_PROPORTIONALITY.md` and are not restated here. This is a single-operator system: function over ceremony, ready over perfect.

- **Delivery depth follows the risk tier.** Single-issue (or issue-free) Tier 1 and Tier 2 PRs take the light path: required CI green plus self-verified `Verify:` targets on the head SHA, then plain merge with `Final-Review-Rounds: 0` — no independent review round, no verified-merge ceremony. The full chain (one independent local review gate with `Final-Review-Rounds: 1`, verified-merge sequence) applies only to Tier 3 work, multi-issue PRs, and PRs touching a TCD high-risk *surface* (auth / security / data / migration / concurrency / payments / external API). A P0/P1 repair invalidates the prior review authority and requires one new clean independent review on the repaired current head SHA. Process outcomes in the escalation-trigger list — a failed attempt, a CI flake, a reviewer nit — escalate capability, never delivery depth or the number of consecutive clean final reviews.
- **Reviewed issue-free compatibility.** Do not rewrite an already-authenticated issue-free Tier 1 docs-authoring or governance PR from `Final-Review-Rounds: 1` to reach the light path. Its existing explicit review decision routes through `verification-and-closure :: Issue-free reviewed lane compatibility path`, which preserves no Issue authority and compensates only a GitHub-attributed closure race. This narrow compatibility path does not authorize new issue-free PRs to select a review round or relax any current-head CI/review gate.
- **Right-size default.** Build the most boring solution that satisfies the acceptance criteria. A new gate, receipt, ledger, registry, config surface, abstraction layer, or enterprise-grade pattern (high availability, multi-tenancy, pluggable providers, defense-in-depth beyond the single-operator trust model) requires an explicit demand in the governing contract — never default posture. "A simpler mechanism satisfies the contract" is a valid blocking review finding. A new permanent governance mechanism must name what it replaces or carry an explicit review-by date.
- **Budget and stop-loss.** A delivery gets 2 CI-repair rounds per failure mechanism. That CI stop-loss does not cap the separate P0/P1 review-repair loop: `verification-and-closure` uses evidence-based convergence, TCD capability escalation, fresh independent re-review, and classifier-based non-progress/technical/scope/authority stops. Findings are never rebound to reset accounting. Light work runs without sub-agent fan-out. Repeated failure on a bounded change usually means the solution is too big — shrink it before escalating capability.
- **Do not pay twice for irrelevant base drift.** Branch freshness and validation freshness are
  separate questions. After a proof-complete local SHA is rebased only because `origin/main`
  advanced, carry expensive review/validation evidence forward when
  `docs/development/GOVERNANCE_PROPORTIONALITY.md :: Post-validation base-drift evidence reuse`
  proves the patch byte-identical and the incoming base semantically irrelevant. Relevant source,
  dependency, contract, configuration, migration, test-selection, or toolchain drift still requires
  fresh affected-surface proof. Current-head CI and every required final review remain current-SHA
  gates.

## Communicating with the owner

The owner is the operator and decision-maker. Human-first means optimizing for the owner's time **and cognitive load**: fast decision support, low running cost, and the fewest things he must hold in his head — not narrating how you got there. Cognitive load is a real cost (part of C_human), not just clock-time.

- Lead with next steps and the answer. Keep responses concise and scannable; do not include a verbose reasoning trace.
- **Minimize cognitive load.** Bundle coherent work into one PR/thread instead of scattering it; collapse options to a recommendation plus the one fork that is genuinely the owner's; never make him reconstruct context or track machinery he does not need.
- When a decision is the owner's to make, present it as: clear **Problem → Options → Consequences** (the consequences of each choice matter most). Surface the decisions that are genuinely his explicitly rather than burying them — without manufacturing choices he should not have to make. The operational Yggdrasil profile for that ask is `.codex/skills/owner-decision-brief`; it uses the portable `decision-quality` skill as the single decision method.
- Keep durable audit artifacts complete but separate from the human-facing summary: BuilderOps receipts, `Verify:` markers, and traceability live in the record, not in the lead. Do not add machinery whose only purpose is to capture reasoning for audit.

## Specialist subagent roles

Specialist subagents are execution roles, not workflow contracts. Repo-local skills remain canonical: a subagent run never replaces the matching `.codex/skills/**/SKILL.md`. When a task uses subagents, the coordinator and every worker must still load `AGENTS.md` and the relevant skill before workflow-boundary actions.

- Use `docs/development/BUILDER_SUBAGENT_ROLES.md` for the shared role inventory, the skill-to-role routing matrix, the bounded-loop policy, and the handoff-receipt template. Keep that detail in the reference doc, not here.
- Codex project-scoped custom agents live under `.codex/agents/**` and Codex agent settings in `.codex/config.toml`. They are Codex-specific execution-role adapters and must not duplicate skill contract text; each adapter must explicitly load the skills it needs, because Codex does not auto-discover this repo's `.codex/skills/**`.
- Claude compatibility stays routed through `AGENTS.md`, `CLAUDE.md`, and the shared role doc. Do not assume Claude consumes Codex TOML, and do not add `.claude/agents/**` adapters without a separate decision.
- Subagent loops are verifier-driven repair loops only. The one bounded issue-local helper permitted
  by `AGENTS.md :: Parallel-agent execution` is the maximum depth; it cannot spawn again. No generic
  looping agent or broader recursive fan-out.

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
- Codex specialist subagent role adapters under `.codex/agents/**` and Codex agent settings in `.codex/config.toml`
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

- Only pick work from a GitHub Issue carrying a strictly valid `agent:ready` label; strict contract validation must pass before the label is applied.
- Read the full Issue before editing.
- Treat `Context`, `Scope`, `Source Anchors`, `Constraints`, `Acceptance Criteria`, `Out of Scope`, `Suggested Validation`, and `Source Docs` as binding.
- Every `Acceptance Criterion` must declare its verification inline with a `Verify:` marker: a concrete test pointer (`tests/...::test_name`) for behavioral criteria, or a concrete non-test target (doc writeback path plus anchor, runtime receipt, roadmap diff) for non-behavioral criteria. ACs without a resolvable `Verify:` target are not executable and the Issue must not be `agent:ready`.
- Link every issue-backed PR with exactly one `Governing-Issue: #<id>` line and at least one
  `Fixes #<id>`, `Closes #<id>`, or `Resolves #<id>` line for work fully delivered by the PR. In
  the normal single-Issue case the governing and closing identities are the same. In an approved
  multi-Issue PR, the governing parent may remain open and be named with `Refs #<id>` while closing
  keywords name only the fully delivered issues; follow
  `docs/development/PR_HOT_PATH.md :: Multi-Issue PR Scope`.
- At verification, resolve every AC/`Verify:` target on the exact closing issues. When an approved
  multi-Issue PR has a distinct open governing parent, validate that parent as the issue-set contract
  (batch authorization, child/scope map, shared constraints, source anchors, validation path, and
  exact authority identities); unfinished feature-level ACs on the open parent do not block delivery
  of fully verified closing children.
- The verified-merge ceremony in this bullet applies to full-path deliveries only (Tier 3, multi-issue, or TCD high-risk per `AGENTS.md :: Proportional delivery`); light-path PRs merge plainly and let native closing keywords close the single governing issue, verified after merge. On the full path: before an issue-backed merge, neutralize authenticated body closers to evidence-only `Refs`,
  revalidate the live exact head/body/empty closing-link set, merge with a fixed non-closing message,
  and explicitly close only the authenticated issue set. Preserve the exact v2 authority and repair
  budget in a trusted durable receipt and advance a continuous prepared -> merged -> reconciled ->
  restored `verified_issue_set_merge_phase.v1` ledger with
  `scripts/build_verified_issue_set_merge_phase.py`. A crashed exact-head merge resumes idempotently
  from that ledger and live merge truth; terminal delivery additionally proves that every and only
  authenticated issue is closed with closure attribution to this delivery. Detect race-added closing
  references and reopen only closures GitHub attributes to that PR before restoring the authenticated
  body.
- The post-merge owner-doc result is PR-specific. Record it on every exact closed issue and also on a
  distinct open governing parent; issue-free lanes record it on the PR. A generic receipt or one for
  another PR does not satisfy the closure gate.
- If a PR changes files under `app/` or `tests/`, run `ruff check app tests` before merge and include the lint output or tooling limitation in the PR body. Docs-only PRs can keep validation lightweight and should not run full smoke by default unless the touched surface requires it.
- Do not treat chat-only requests as canonical implementation tasks when an Issue is expected.
- Do not expand scope beyond the Issue without updating the task contract first.
- Do not create new backlog work in GitHub without stable `Source Anchors` that point to the most local governing doc items.
- Prefer stable anchor IDs over prose fragments when the source doc is likely to produce multiple Issues over time.
- Treat GitHub Issues as the canonical backlog receipt. GitHub Project is an optional legacy projection when available; inline doc markers such as `Tracked by: #...` are secondary convenience notes only.
- Prefer Issues plus truthful agent labels, linked PR state, and CI as harder authority than Project state if they drift.
- Use `agent:ready` as the external pickup qualifier without requiring GitHub Project Status. The dispatcher claim is the collision guard when available; blocked labels belong on non-active work, and closed issues must not retain `agent:*` labels.
- When a PR delivers a tracked backlog item, update the owner doc to describe shipped reality and rewrite roadmap/plan wording so it no longer reads as pending work.
- Prefer GitHub REST endpoints for routine issue/label/PR operations; use GraphQL when REST does not express the required operation.
- When GraphQL is required, resolve stable identifiers once per run and reuse cached values instead of repeating lookup queries.
- Batch project-field GraphQL mutations into one bounded pass near workflow completion, rather than interleaving repeated mutations throughout intake.

## Dispatcher policy

**Superseded as an operational procedure — do not read this section to perform a pickup.**
`scripts/issue_pickup_claim.sh`, driven by
`.codex/skills/issue-to-code/SKILL.md :: Dispatcher Integration`, is the only claim entrypoint, and
it supersedes every hand-run `dispatcher next` / `dispatcher claim` / `gh issue edit` sequence.
Reconstructing that handshake by hand is forbidden, so reading a procedure for it makes an agent
more likely to be wrong, not less. What remains below is the authority statement the wrapper
implements — read it only when reasoning about dispatcher authority, never to execute a claim.

The dispatcher is an optional collision guard for issue pickup, not lifecycle authority.

- Use `issue-to-code` and its single `scripts/issue_pickup_claim.sh` entrypoint; do not reconstruct
  the claim handshake with ad hoc dispatcher and label commands.
- GitHub Issue state and labels remain durable truth. A verified dispatcher lease augments that
  truth while it is live; dispatcher unavailability selects the wrapper's durable
  GitHub-label-only fallback.
- Heartbeat, complete, block, release, fallback receipts, TTL, and recovery semantics are owned by
  `.codex/skills/issue-to-code/SKILL.md` and `docs/AGENT_ISSUE_DISPATCHER.md`.
- Project Status is not part of claim and never gates pickup.
