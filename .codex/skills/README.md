State: Repo-local skill index for builder agents working in this repository.

# Repo-local Skills

Use this file after reading the repository root `AGENTS.md`.

These skills are workflow helpers, not replacements for the canonical builder-agent policy.
They are Builder System artifacts: durable repo-governed workflow instructions for development-time
agents, not Product/Runtime System agents and not runtime CAO/MEM capability contracts. For
Product/Runtime work, route SBS impact through `docs/architecture/SBS_OPERATING_MODEL.md`. For skill,
workflow, issue/PR, CI, release, BuilderOps, learning, or TCD work, route through the Builder System
boundary and artifact map in `docs/architecture/SBS_OPERATING_MODEL.md`.

## Portable skill dependencies

`.codex/skills/portable-skills.list` is the single repo registry for skills whose method is maintained
outside this repository. Their method text is not vendored or duplicated here. The default portable
source root is `~/.local/share/agent-skills`; set `PKM_PORTABLE_SKILLS_DIR` when the platform uses a
different source root.

`scripts/install_skills.sh` installs both repo-local skills and every registered portable dependency
into the configured Claude skill directory. It fails closed when a registered source is absent. Codex
discovers the same portable source root directly. A repo skill may require a portable method only
when its dependency is registered here and the environment has completed that provisioning step.

## Workflow map

Hot path:
`Docs -> Issue -> issue-to-code claim + implementation -> Publish PR -> CI -> Verification -> Merge -> closure -> Owner Doc`

Conditional / maintenance path:
`Issue maintenance -> Agent` for stale or false backlog state, and `Publish PR -> pr-integration` only when readiness/repair work is still needed before verification.

This file owns the canonical workflow chain. Skills reference this chain instead of redefining it; if a skill's inline chain disagrees with this file, this file wins. Issue maintenance is part of the conditional path, not the hot path.

Delivery depth is tiered (`AGENTS.md :: Proportional delivery`): single-issue (or issue-free) Tier 1 and Tier 2 PRs take the light path — required CI green, self-verified `Verify:` targets, `Final-Review-Rounds: 0`, plain merge with native closing keywords — while Tier 3, multi-issue, and TCD high-risk PRs run the full review + verified-merge ceremony in `verification-and-closure`.

## BuilderOps Vault routing

BuilderOps Vault is the operational plane for the building system. BuilderOps records are not
product/runtime truth unless explicitly promoted through the appropriate authority path.

- Raw builder-agent working notes, handoffs, recovery notes, and temporary evidence -> `AgentWorklog`
- Delivery divergences that name an upstream artifact -> `LearningSignal`
- High-churn docs freshness observations or review queues -> `DocsFreshnessRecord`
- Roadmap execution movement, active issue movement, blockers, or shipped refs -> `RoadmapExecutionItem`
- Requests to cross into GitHub Issue, PR/branch proposal, ADR/decision doc, owner-doc or skill/AGENTS writeback, generated projection, or discard handling -> `PromotionIntent`
- State transitions, retrospective completions, projections, promotions, supersessions, and discards -> `BuilderOpsReceipt`

Create GitHub Issues from BuilderOps material only when it has become bounded executable work with
`Verify:` targets. Open PRs only for repo-governed artifact changes. Do not edit canonical docs
just to capture operational state that belongs in BuilderOps Vault.

## BuilderOps workflow checkpoints

The routing decision must live in the skills and automation prompts that agents already execute.
Do not rely on a human remembering where BuilderOps material belongs.

1. **Start checkpoint:** before implementation, maintenance, or audit work becomes durable, classify
   any raw notes, recovery context, docs freshness state, roadmap movement, learning, or proposed
   authority crossing. Create the matching BuilderOps record when the material is not already fully
   represented by a GitHub Issue, PR, or reviewed repo artifact.
2. **Divergence checkpoint:** whenever a plan, issue, doc, or skill turns out to be wrong while work
   is active, invoke `capture-learning` immediately and create a `LearningSignal` instead of saving
   the observation for a later human memory pass.
3. **Publication checkpoint:** Tier 2+ PR bodies must state the BuilderOps routing outcome: records
   created, projections or receipts updated, or `none` with a short reason. Tier 1 PRs
   (docs-authoring or governance lane, per `docs/development/GOVERNANCE_PROPORTIONALITY.md`) may omit
   the section entirely when nothing was routed — absence means `none`; a present but unfilled
   section is still a contract violation.
4. **Closure checkpoint:** before merge or delivery receipt, unresolved adoption, retro, freshness,
   roadmap, or promotion observations must be represented by a BuilderOps record, a bounded GitHub
   Issue with `Verify:` targets, or an explicit `none` reason.
5. **Automation checkpoint:** recurring Codex automations for this repo must read the relevant
   workflow skill and route high-churn operational material to BuilderOps first. `docs/learning-log.md`
   is historical/fallback only; generated projections are readable views only.
6. **Analysis checkpoint (no PR in flight):** the checkpoints above are anchored to work that is
   already implementation-, delivery-, or automation-bound. A standalone research pass, prior-art
   sweep, architecture analysis, or other chat-turn work product that answers a question but produces
   no PR still needs a home — it does not get a pass just because none of checkpoints 1-5 fired. Before
   treating that thread as closed, create the matching BuilderOps record (usually `AgentWorklog`) for
   any findings, sources, or process narrative worth keeping, unless the material is trivial enough
   that losing it costs nothing.
7. **Deliberation discovery checkpoint:** at substantial session close, interrupted-work resume,
   larger delivery review/closure, and epic/parent closure, search through
   `builder-vault-deliberation` for threads matching the current Issue, PR, commit, doc, design, or
   BuilderOps refs. Reply or disposition only when useful; no match is normal and never weakens the
   governing delivery authority. Run `builder-vault-review` on the configured weekly/threshold
   cadence or immediately on a conflict/orphan. Never write live content into the repository
   `vault/` fixture.

## Skill routing

Shared contracts: `.codex/skills/_shared/` holds the canonical contract files that skills reference
instead of carrying inline copies — `ISSUE_CONTRACT.md` (Issue section list + `Verify:` rule),
`LABEL_TAXONOMY.md` (canonical labels + narrow `lane:governance` and
`state:known-defect` exceptions), `LIFECYCLE_TRUTH_MATRIX.md`
(optional legacy Project projection per Issue/PR state), `BRANCH_TRUTH_GATE.md` (publication workspace gate),
`PROJECT_STATUS_OPERATIONS.md` (Project GraphQL operations), `CI_WAIT_CONTRACT.md` (how to wait
on CI checks — and the optional `--codex` verdict path — via REST without draining the shared API budget),
`BUILDER_VAULT_DELIBERATION_CONTRACT.md` (non-authoritative shared-file deliberation, immutable
entries, hash/conflict rules, and existing promotion boundaries), and `READ_SCOPE.md` (how much of a
cited document to read). A reference like
`_shared/<FILE>.md :: <section>` resolves there. `_shared/` is not a skill directory.

Read scope: a `FILE :: Section` citation anywhere in this repo's instruction chain means **read that
section only**; a citation with no `::` is a whole-file read and requires a stated reason at the
citation site. `_shared/READ_SCOPE.md` is the canonical protocol, including the rule that
`docs/DOCS_INDEX.md` is grep-only and that conditional reads key off the actual diff
(`git diff --name-only origin/main...HEAD`), not the issue's declared scope.

- `agentic-pkm`
  - default repo-dev context for code, tests, docs, and SoT reading order in this repository
- `resume-work`
  - dev-time recovery for interrupted Codex/Claude/ChatGPT sessions (quota, network, hung command, tool failure, context loss); check resumable orchestration journals/runs before git reconstruction, use git reconstruction as the fallback, keep a lightweight `.codex-tmp/HANDOFF.md`, continue when clear, and escalate only on destructive or contract/SoT ambiguity; not a runtime/product feature
- `builder-vault-deliberation`
  - create, discover, read, search, reply to, correct, resolve, and archive attributed asynchronous BuilderOps deliberations as immutable shared-vault entries; never delivery or promotion authority
- `builder-vault-review`
  - weekly, threshold, or conflict-triggered health review of stale, unanswered, duplicated, promotion-pending, conflicted, and orphaned deliberations; uses the deliberation skill for any entry mutation
- `issue-to-code`
  - implementation entrypoint for bounded GitHub Issue work
  - classifies the issue as Product/Runtime System, Builder System, or boundary work before pickup
  - before coding, use its pickup wrapper to acquire the available dispatcher lease or durable
    GitHub-label-only fallback and remove `agent:ready`
- `builder-thread`
  - attributed, shared-non-sensitive Builder Thread capture through the one designated serialized
    BuilderOps writer; never a direct shared-vault write path or delivery authority
- `builder-inbox`
  - bounded read-only Builder Thread discovery through the same writer endpoint; never a backlog,
    authority, or mutation surface
- `start-model-inquiry`
  - launch a durable pre-ticket Fable/GPT inquiry exactly once through the sanctioned host-local
    subscription launcher; the dormant provider-API launcher has a distinct identity, and issue
    promotion remains a separate governed step
- `issue-maintenance-change-control`
  - repair stale or false Issue / PR / label state before or during execution, plus optional
    Project projection when explicitly in scope
- `deliver-issue-set`
  - review, plan, make ready, and deliver an epic, parent feature issue, Kanban/Project lane, or larger ready-issue set; use `issue-to-code` and `verification-and-closure` as the main lenses; if the ready pool is too small, repair or create bounded ready issues through `issue-maintenance-change-control`, `docs-to-issue`, or `feature-breakdown`; may claim multiple issues only for rational parallel sub-agent delivery with isolated worktrees and explicit receipts
  - for larger `type:bug` sets, follow `AGENTS.md :: Transition-period bug-delivery policy`
- `docs-governance`
  - decision and routing skill for docs-as-code ownership, anti-sprawl, DOCS_INDEX impact, and narrower docs workflow selection
- `yggdrasil-design-handoff`
  - prepare, run, revise, validate, or archive Claude Design and other UI/component handoffs;
    fail closed unless the live Yggdrasil Design System is selected or attached and its token sheet
    matches the repo's binding source
- `docs-authoring`
  - docs-only authoritative authoring lane
- `docs-to-issue`
  - convert active docs into bounded backlog Issues
- `feature-breakdown`
  - break one docs-defined capability into a specification directory plus a parent feature issue and bounded child slice issues
- `architecture-research`
  - deliberate evidence-based research pass over the live system: parallel subsystem explorers with `file:line`-anchored evidence-only briefs, cross-system synthesis, research-question resolution, invariant extraction with enforcement categories, then backlog handoff via `feature-breakdown` (reconcile against open epics, never duplicate); output is an advisory audit doc in `docs/audits/` plus an optional specification directory
- `bug-to-issue`
  - route a discovered defect to a normal bounded GitHub bug Issue or, for confirmed deferred
    P2 review findings, to the deterministic rolling Known Defects registry; classify
    Product/Runtime vs Builder System vs boundary before promotion chooses labels, owner docs, and
    SBS Impact
- `temporal-doc-governance`
  - audit and refresh time-sensitive current-state docs
- `automation-maintenance`
  - inspect Codex app automations for this repository, detect redirect/stale `cwds`, use the Codex app automation update tool when available, and report exact pending changes when local automation state cannot be safely updated
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
  - micro-skill: create one BuilderOps `LearningSignal` when a builder-workflow plan divergence occurs; invoke on divergence, not on normal work; use `docs/learning-log.md` only as historical/compatibility fallback; never treat builder learning as runtime/user memory without Product System authority
- `owner-decision-brief`
  - thin Yggdrasil profile: invoke at the moment any workflow is about to ask the owner for a decision (`agent:needs-human`, an operator ask, an inline question); load the portable `decision-quality` skill as the single decision method, preserve contractual operator and local vault-binding gates, apply repo authority and no-parallel-store constraints, and render the resulting owner ask as one standalone plain-language brief
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

Product-lane app-agent skills (runtime client operating instructions, not Builder System
workflow — see `## App-agent skill family (product-lane)` below for the full description):

- `mimer-governed-boundary`
  - shared contract skill for the app-agent family; loaded by reference, never invoked directly
- `mimer-capture`
  - governed intake write to the vault inbox
- `mimer-retrieve`
  - read-only vault search
- `mimer-ask`
  - grounded Q&A over the vault with citations
- `mimer-vault-workspace`
  - direct-filesystem drafting/synthesis/editing under human delegation

## Connected execution paths

- Implementation path:
  `agentic-pkm -> issue-to-code -> publish-pr -> [pr-integration when repair/readiness is needed] -> verification-and-closure -> post-merge-owner-doc`
- Drift-correction path:
  `issue-maintenance-change-control -> issue-to-code` when the Issue becomes executable again
- Epic / Kanban issue-set delivery path:
  `deliver-issue-set -> (issue-maintenance-change-control | docs-to-issue | feature-breakdown) -> issue-to-code -> publish-pr -> pr-integration as needed -> verification-and-closure`
- Docs backlog path:
  `docs-governance -> (docs-authoring | docs-to-issue | feature-breakdown)`
- Design handoff path:
  `yggdrasil-design-handoff -> governed exploration/handoff -> disposition (PromotionIntent when crossing authority classes) -> (Companion UI: Crossing B -> normalized spec | other surface: local owner doc/spec) -> docs-to-issue`
- Architecture research path:
  `architecture-research -> feature-breakdown -> issue-to-code` (audit doc publishes via `publish-pr`; findings reconcile against open epics instead of creating parallel hubs)
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
- `scripts/agent_workspace_preflight.sh` (with the report entrypoint
  `scripts/git_hygiene_preflight.py`) is the read-only hot-path check for dirty tree, in-progress
  git operations, branch/worktree mismatch, and relevant lease conflicts. This is a script, not a
  skill.
- `scripts/agent_worktree.py` owns lifecycle registration plus the report-first cold-path cleanup
  guard. Apply requires explicit generation-bound lifecycle, reloadable active-lease, and PR-state
  authority. Fetch and planning do not retain the lifecycle lock; lease plus live
  path/branch/HEAD/generation authority are reread at the targeted removal boundary, and the
  lifecycle lock spans only that command. It durably records a generation-bound `removal_pending`
  transition before Git removal; successful removal retires the exact generation before branch
  deletion, and restart reconciliation completes only pending transitions. Ordinary missing
  lifecycle records remain preservation evidence. Broad metadata pruning remains report-only. The compatibility
  `scripts/git_hygiene_janitor.py` entrypoint refuses destructive cleanup. These are scripts, not
  skills.

## Cross-cutting invariant: Total Cost of Development (capability routing)

Capability routing across the whole chain follows `AGENTS.md :: Total Cost of Development`: each
stage picks the cheapest *acceptable* capability (workflow/skill + model + reasoning effort + context
discipline + tools + verification + review gate) for the lowest expected total cost per accepted
delivery. Choose model and reasoning effort actively. Context/input-token accounting, the
root-coordinator → issue-agent → optional issue-helper hierarchy, escalation/de-escalation triggers,
and model/reasoning policy live once in `AGENTS.md`, not in each skill.

The policy attaches to the stages that actually choose capability; it does not change the chain:

- Research (`architecture-research`): emit a `tcd_plan`; keep synthesis in the root coordinator and
  give independent read-only explorers bounded subsystem contexts.
- Decompose / plan (`feature-breakdown`, `deliver-issue-set`): emit a `tcd_plan`, choose inline vs.
  fresh issue context, and route serial-vs-concurrent scheduling as a separate expected-cost
  decision.
- Implement (`agentic-pkm`, `issue-to-code`): one fresh issue agent owns each non-trivial Issue end
  to end; it picks model/reasoning from risk and may use one bounded issue-local helper only under
  `AGENTS.md :: Parallel-agent execution`.
- Integrate / verify (`pr-integration`, `verification-and-closure`): keep repair context issue-local,
  scale review and verification to risk, and let `verification-and-closure` emit the terminal
  `tcd_review`; `pr-integration` supplies compact evidence rather than a second review block.
- Retrospect (`learning-retrospective`): emit a `tcd_retrospective` when a learning cluster shows a
  routing or context-topology mistake, and feed the fix back into `AGENTS.md`.

Mechanical, deterministic, or operator-gated skills (publication, promotion and rollback, issue/bug/
learning intake, docs and backlog maintenance) do not choose capability and carry no TCD block.

## App-agent skill family (product-lane)

The five `mimer-*` skills are **runtime client operating instructions**, not Builder System
workflow skills. They instruct external app agents (Claude app, Codex app, and peers) how to
operate Mimer and the Obsidian vault as governed clients — no GitHub, no PRs, no issues. They are
governed by `docs/contracts/MIMER_CLIENT_CONTRACT.md` (enacted by
`docs/adr/ADR-0056-mimer-client-contract-and-transports.md`), not by this file's workflow map.

The canonical workflow chain, BuilderOps Vault routing, and BuilderOps workflow checkpoints
sections above do **not** apply to this family — it has no Issues, no PRs, no lifecycle states,
and no BuilderOps routing obligation. Do not route app-agent skill work through
`issue-to-code`/`publish-pr`/`verification-and-closure`; those are for changes to the skill files
themselves (a Builder System docs-authoring or governance-lane change), not for the app-agent's
own runtime operation.

- `mimer-governed-boundary`
  - the shared contract skill: the three hard invariants, the exclusion list, the provenance
    frontmatter block, and error-surfacing duties every other skill in this family inherits by
    reference; never invoked directly for a human request
- `mimer-capture`
  - friction-free intake into the vault inbox via the governed capture endpoint; the only skill in
    this family that performs a durable vault write
- `mimer-retrieve`
  - read-only vault search; find existing material by title/uuid, with filesystem enrichment as
    the sanctioned fallback for the uuid-to-path gap
- `mimer-ask`
  - grounded Q&A over the vault with per-source citations; never blends the agent's own knowledge
    in unmarked
- `mimer-vault-workspace`
  - direct-filesystem participation (AGENT-FLOWS mode c): drafting/synthesis in declared workspace
    roots, and human-directed edits to existing notes under full write discipline
