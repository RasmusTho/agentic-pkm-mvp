State: Development governance reference for delivery learning capture, continuous improvement, and periodic reevaluation.
Doc role: Reference
Authority: Defines the Builder System continuous improvement and reevaluation loop for builder-agent governance; does not override `AGENTS.md`, GitHub issue contracts, or runtime/system-agent docs.
Owner: Builder-agent governance
Temporal class: operational
Review cadence: per retrospective
Source of truth: BuilderOps Vault LearningSignal records for operational learning; this document defines workflow
Last reviewed: 2026-07-09
Last verified against: issues #1506/#1509/#3138/#3224/#3229/#3260-#3266, docs/learning-log.md, docs/development/BUILDER_SYSTEM_PROCESS_MAP.md, docs/architecture/SBS_OPERATING_MODEL.md, docs/CAPABILITY_KNOWLEDGE_MODEL/README.md, docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md, docs/builderops/BUILDEROPS_VAULT_PROJECTIONS.md, .codex/skills/capture-learning/SKILL.md, .codex/skills/learning-retrospective/SKILL.md

# Continuous Improvement And Reevaluation Loop

## Problem

The `verification-and-closure` skill closes issues and updates project state but does not feed signal back into upstream artifacts. Every delivery is amnesiac: contract defects, process friction, and agent-behavior surprises die in the PR and never improve the system.

The loop must be pipeline-wide, not owned by verification alone. Any skill that encounters a divergence from plan holds signal worth capturing.

Delivery feedback is only half the loop. The Builder System must also periodically reevaluate whether
its own process, guardrails, issue contracts, evidence surfaces, fitness rules, and capability model
still match observed delivery reality. That reevaluation is not part of the hot delivery path, but it
is part of the Builder System's supported operating model.

## Design

```text
Docs -> Feature -> Slice -> Agent -> PR -> CI -> Review -> Merge -> Closure
         ^                    |        |       |          |
         |                    |        |       |          v
         |                    |        |       +---- PR evidence / review findings
         |                    |        +------------ CI failure context
         |                    +--------------------- LearningSignal on divergence
         |                                          TCD signal on high cost/rework
         |                                          CKM/evaluation input when capability evidence changes
         |
         +---- continuous improvement / reevaluation
                              |
                              v
               learning-summary projection · CKM projections · evidence packs
                              |
                              v
               learning-retrospective / reevaluation pass
                              |
                              v
               One closed-loop outcome per signal:
               applied governance edit · already satisfied · GitHub Issue
               PromotionIntent · fitness rule/debt update · discard/supersession receipt
```

Loop invariant:
every captured improvement or reevaluation signal in scope must eventually be represented by one
closed-loop outcome. A signal may not remain as chat context, unprocessed prose, or an implied future
todo after the retrospective or reevaluation pass has claimed it.

## BuilderOps operating-plane boundary

BuilderOps records are operational builder-system material. They are not product/runtime truth and
do not change repo authority unless they are explicitly promoted through GitHub Issues, PRs, ADR or
owner-doc proposals, generated projections, or discard receipts.

### raw-agent-worklog-boundary

Raw builder-agent work notes belong in BuilderOps Vault as `AgentWorklog` records by default.
They do not belong in reviewed repo docs, `$CODEX_HOME`, or repo-local ignored state as the durable
default. Local scratch may exist only as transient execution state.

Promotion path:

```text
AgentWorklog
  -> LearningSignal, when the note contains durable workflow learning
  -> PromotionIntent, when the note should cross into GitHub, PR, ADR, owner-doc, skill, AGENTS, generated projection, or discard handling
  -> BuilderOpsReceipt, when the note is processed, superseded, projected, promoted, or discarded
```

Create or update a GitHub Issue only when the promoted material becomes bounded executable work
with `Verify:` targets. Open a PR only when repo-governed artifacts need to change. Direct edits to
repo docs are not the capture path for raw working notes, docs freshness queues, roadmap execution
movement, or unresolved learning.

This section is the raw-worklog storage decision for #1495: BuilderOps Vault is the durable
operational surface, and explicit promotion is the only path into GitHub/repo authority.

## Components

### 1. `capture-learning` skill

Single-job micro-skill. Creates one `LearningSignal` record in BuilderOps Vault when a divergence
is concrete enough to name an upstream artifact now.

**Inputs (required):**
- **what diverged** — one sentence: the plan said X, reality was Y
- **upstream artifact** — the named artifact that could absorb the fix (`AGENTS.md §X`, `.codex/skills/issue-to-code/`, task-contract template, etc.). Must be named. If genuinely unknown, write `"unknown — flag for retro"`.
- **source** — which skill or moment noticed it

**LearningSignal content shape:**
```text
Issue/context: #<issue> (<slice title>)
Source: <skill name or "human">
Diverged: <one sentence>
Upstream artifact: <path or section>
```

**Trigger rule (the important part):** invoke only when you do something you did not expect to do, or discover an earlier artifact was wrong. Not when work went as planned. The heuristic: *if the next agent doing a similar task would benefit from an upstream artifact being different, log it — otherwise don't.*

**The "name an artifact" gate** kills venting. You cannot log without proposing where the fix lives.

### 2. BuilderOps `LearningSignal` records

Primary operational source for delivery learning after #1506.

The record must carry:

- `object_type: LearningSignal`
- `signal_type: workflow_divergence` or a similarly specific workflow signal type
- `source_refs` pointing to the issue/PR/review thread and the upstream artifact named by the signal
- `content` containing the source, divergence, and proposed upstream artifact

Raw `AgentWorklog` records may be cited through `source_refs`, but raw worklogs are provenance and
working material, not authoritative learning truth.

### 3. `docs/learning-log.md`

Historical compatibility view. It preserves pre-BuilderOps entries and explicit fallback entries
when a BuilderOps write is unavailable. It is no longer the primary operational learning store.

Retrospective completions append a marker line:
```
--- retro YYYY-MM-DD: applied N/M proposals ---
```

This marker remains for historical compatibility entries only. Retrospectives over BuilderOps
LearningSignals should record their completion with a `BuilderOpsReceipt` that targets the processed
LearningSignal records.

### 4. `learning-retrospective` skill

Cadence-triggered (manual, after an epic closes, or roughly every 10 delivery-learning records).
Reads BuilderOps `LearningSignal`
records and may generate the `learning-summary` projection for a repo-readable view. It reads
`docs/learning-log.md` only for historical compatibility entries that have not yet been represented
as BuilderOps records.

**What it does by default:**
1. Clusters signals by upstream artifact.
2. Proposes **concrete edits** (diffs or specific line additions) to those artifacts — not vague recommendations.
3. Does NOT execute edits. Outputs proposals for human review.
4. Accepted proposals are committed as ordinary governance-lane PRs.
5. Records the retrospective outcome with a `BuilderOpsReceipt` over the processed LearningSignals.

When the human explicitly asks the agent to handle the retro end to end, the retrospective may run in autonomous maintenance mode: verify which LearningSignals or compatibility entries are already satisfied by current repo reality, apply safe governance-lane edits for clearly named artifacts, create GitHub Issues or PromotionIntents for unresolved or decision-bearing work, route repeated patterns to debt/fitness where appropriate, discard or supersede obsolete signals with a receipt, and record a BuilderOps retrospective receipt only after every signal in scope has a terminal outcome under §4b.

**Success signal for the retrospective itself:** upstream artifacts carry dated edits traceable to LearningSignals, BuilderOps receipts, or historical compatibility entries. If AGENTS.md and skill prompts are static while LearningSignals accumulate, the retrospective step is broken.

### 4a. Continuous reevaluation inputs

Reevaluation uses a wider input set than `LearningSignal` records:

- PR evidence packs and CI failure context artifacts from Builder System automation.
- Review findings, repeated repair classes, and Human Exception packets.
- TCD signals: high human steering, high context reload, over-fanning, repeated model under-use or
  over-use, and avoidable coordination cost.
- Transition-debt and fitness-rule outcomes from `docs/architecture/SBS_TRANSITION_DEBT.md` and
  `docs/architecture/SBS_FITNESS_RULES.md`.
- CKM/Kvasir projections once the CKM MVP exists: capability maturity, missing evidence, stale
  assessment, unlinked artifact, and gap/tension findings.

These inputs do not automatically create work. A reevaluation pass classifies them, then routes each
actionable item through the same governed destinations as learning: issue, PR, fitness rule, debt
row, `PromotionIntent`, or receipt. CKM output remains projection-only and never becomes product or
runtime truth by itself.

The observe-only BuilderOps helper `python -m app.builderops builderops evidence-bridge classify`
bridges PR evidence packs, CI failure context, review findings, missing evidence, and Human
Exception causes into reevaluation candidates. Its report keeps `observed`, `unknown`, and
`candidate` fields separate; candidates require `source_refs` plus a named upstream artifact, unless
they are explicitly held in an `unknown_for_retro` bucket. First rollout is artifact/comment-only:
the helper does not push, merge, label, update Project state, write Product docs, or change
Product/Runtime behavior.

### 4b. Retrospective closure rule

A retrospective or reevaluation pass is not complete until every in-scope signal has one of these
terminal outcomes:

- **applied** - a governance/docs/skill/template change was merged or is in the current PR.
- **already_satisfied** - current repo reality already contains the intended improvement.
- **issue_created** - a bounded GitHub Issue exists with `Source Anchors` and `Verify:` targets.
- **promotion_pending** - a `PromotionIntent` exists for a boundary-crossing proposal.
- **debt_or_fitness_recorded** - a transition-debt row, fitness-rule backlog item, or rule update
  records the repeatable failure mode.
- **discarded_or_superseded** - a `BuilderOpsReceipt` explains why the signal is obsolete, invalid,
  or replaced by newer material.

The closure receipt names the outcome for each processed signal. Proposal-only mode may still stop
for human review, but once a pass is accepted for execution it must not leave claimed signals in an
implicit "later" state.

The observe-only BuilderOps helper `python -m app.builderops builderops retrospective-closure check`
builds the terminal-outcome ledger used before recording a retrospective completion receipt. It
reports incomplete passes by listing `unresolved_signals`; it does not mutate BuilderOps records,
GitHub, repo docs, Product/Runtime behavior, or runtime/user memory.

Epic-run-state candidate ledgers use this same vocabulary. Missing outcome means unresolved; unknown
outcome strings are not terminal.

### 5. Governance lane

A distinct work-stream on the Project board for changes to delivery-system artifacts.

**Distinguishing features:**
- **Target:** `.codex/skills/`, `AGENTS.md`, task-contract template, `docs/development/`, Project configuration
- **Acceptance shape:** adoption evidence, not behavioral tests (e.g., "the next 3 slices used the new slot")
- **Source of work:** primarily retrospective output; secondarily human architect
- **Cadence:** pull-based by log volume, not roadmap

**Mechanism (minimal):**
- Label `lane:governance` on issues and PRs
- Filter view on existing Project board — not a second board
- Governance specs live under `docs/development/`
- Verification skill treats `lane:governance` issues with relaxed behavioral-AC rules — non-behavioral `Verify:` targets (adoption evidence, doc presence) are the norm

### 6. "Applies learning" slot in task-contract template

The task-contract template is defined in `.codex/skills/docs-to-issue/SKILL.md` (the "Issue body must contain exactly these sections" list). Agents creating new Issues from docs must follow that template.

Optional section at the bottom of every slice issue:

```markdown
## Applies learning (optional)
<!-- Link to a retrospective outcome this slice is exercising. -->
<!-- Fills in when the slice was shaped by a prior retro edit. -->
```

Usually blank. When filled, enables tracing whether retro edits actually improved delivery. This is the honest end-to-end success test.

## Trigger heuristic for all skills

Every skill in `.codex/skills/` carries this addendum:

> **Capturing learning:** if during this work you notice a divergence from plan — you did something you didn't expect to do, or discovered an earlier artifact was wrong — invoke `capture-learning` before continuing. Capture a BuilderOps `LearningSignal`; use `docs/learning-log.md` only as an explicit compatibility fallback. Do not batch to end of task; context is freshest now. Only capture if you can name an upstream artifact that could absorb the fix.

## Workflow and automation enforcement

BuilderOps adoption is enforced at workflow boundaries, not by human recall.

- `issue-to-code` runs a BuilderOps routing checkpoint before implementation context becomes hidden
  local memory and again before PR handoff.
- `publish-pr` requires a `BuilderOps Routing` section in every Tier 2+ PR body; Tier 1
  docs/governance-lane PRs may omit it when nothing was routed
  (`docs/development/GOVERNANCE_PROPORTIONALITY.md`).
- `verification-and-closure` verifies that unresolved BuilderOps material is represented by a
  BuilderOps record, a bounded GitHub Issue, or an explicit `none` reason before merge.
- `automation-maintenance` audits recurring Codex app prompts for BuilderOps-first routing.
- Learning-retro automations must read `LearningSignal` records and generated learning projections
  first, using `docs/learning-log.md` only for historical or explicit compatibility fallback entries.
- Epic-runner automation must preserve improvement inputs in run-state when they are discovered
  during issue-set delivery: review findings, repeated constraints, TCD signals, learning
  candidates, CKM/reevaluation candidates, unresolved follow-ups, and terminal closure outcome.
- Review/repair automation must expose reusable findings as learning or reevaluation candidates
  rather than rediscovering the same rule in each PR.
- CKM reevaluation output is projection-only. It may recommend issues, fitness rules, roadmap
  correction, or owner-doc proposals, but action still crosses through GitHub/PR/BuilderOps
  promotion gates.
- Temporal-doc automations must route high-churn docs freshness and roadmap execution state to
  `DocsFreshnessRecord` and `RoadmapExecutionItem` records before considering repo-doc writeback.

## What this is not

- Not a metrics dashboard
- Not product telemetry, runtime memory, or auto-classification authority
- Not a blocking gate in the delivery path — the loop is asynchronous, delivery velocity is unchanged
- Not a second Project board or new agent
- Not mandatory per-delivery — log only on divergence
- Not product/runtime memory; BuilderOps learning governs the building system only

## Success criteria

After 3–4 retrospectives:
- `AGENTS.md` and skill prompts carry dated edits traceable to specific log entries
- At least one delivered slice has the "applies learning" slot filled
- At least one repeated review/CI/TCD pattern has been routed to a durable outcome: issue, skill
  edit, fitness-rule candidate, transition-debt row, or discard/supersession receipt
- Once CKM projections exist, at least one reevaluation pass has compared CKM maturity/gap evidence
  against active Builder System backlog or fitness-rule coverage without treating CKM output as
  authority
- Signal volume in the log reflects real divergences, not noise

If those artifacts are static while LearningSignals accumulate: fix the retrospective step.
If LearningSignals are empty while deliveries ship with real divergences: fix the skill addendums.
If evidence packs, review findings, TCD signals, or CKM gaps accumulate without terminal outcomes:
fix the reevaluation step.
Historical compatibility entries in `docs/learning-log.md` should trend toward zero after #1506.
