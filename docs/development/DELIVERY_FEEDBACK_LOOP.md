State: Development governance reference for delivery learning capture and retrospective feedback.
Doc role: Reference
Authority: Defines the delivery feedback loop for builder-agent governance; does not override `AGENTS.md`, GitHub issue contracts, or runtime/system-agent docs.
Owner: Builder-agent governance
Temporal class: operational
Review cadence: per retrospective
Source of truth: BuilderOps Vault LearningSignal records for operational learning; this document defines workflow
Last reviewed: 2026-06-01
Last verified against: issue #1506, docs/learning-log.md, docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md, docs/builderops/BUILDEROPS_VAULT_PROJECTIONS.md, .codex/skills/capture-learning/SKILL.md, .codex/skills/learning-retrospective/SKILL.md

# Delivery Feedback Loop

## Problem

The `verification-and-closure` skill closes issues and updates project state but does not feed signal back into upstream artifacts. Every delivery is amnesiac: contract defects, process friction, and agent-behavior surprises die in the PR and never improve the system.

The loop must be pipeline-wide, not owned by verification alone. Any skill that encounters a divergence from plan holds signal worth capturing.

## Design

```text
Docs -> Feature -> Slice -> Agent -> PR -> CI -> Verification -> Merge
         ^                    | (any skill, on divergence)
         |                    v
         |              BuilderOps LearningSignal
         |                    |
         |                    v
         |              learning-summary projection
         |                    |
         +---- learning-retrospective (cadence-triggered)
                              |
                              v
               Edits to upstream artifacts:
               AGENTS.md · skill prompts · slice template
               task-contract template · owner-doc conventions
```

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

Cadence-triggered (manual, or roughly every 10 deliveries). Reads BuilderOps `LearningSignal`
records and may generate the `learning-summary` projection for a repo-readable view. It reads
`docs/learning-log.md` only for historical compatibility entries that have not yet been represented
as BuilderOps records.

**What it does by default:**
1. Clusters signals by upstream artifact.
2. Proposes **concrete edits** (diffs or specific line additions) to those artifacts — not vague recommendations.
3. Does NOT execute edits. Outputs proposals for human review.
4. Accepted proposals are committed as ordinary governance-lane PRs.
5. Records the retrospective outcome with a `BuilderOpsReceipt` over the processed LearningSignals.

When the human explicitly asks the agent to handle the retro end to end, the retrospective may run in autonomous maintenance mode: verify which LearningSignals or compatibility entries are already satisfied by current repo reality, apply safe governance-lane edits for clearly named artifacts, create GitHub Issues for unresolved or decision-bearing work, and record a BuilderOps retrospective receipt only after every signal in scope is either applied, already satisfied, or represented by an Issue.

**Success signal for the retrospective itself:** upstream artifacts carry dated edits traceable to LearningSignals, BuilderOps receipts, or historical compatibility entries. If AGENTS.md and skill prompts are static while LearningSignals accumulate, the retrospective step is broken.

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

## What this is not

- Not a metrics dashboard
- Not structured product telemetry or auto-classification
- Not a blocking gate in the delivery path — the loop is asynchronous, delivery velocity is unchanged
- Not a second Project board or new agent
- Not mandatory per-delivery — log only on divergence
- Not product/runtime memory; BuilderOps learning governs the building system only

## Success criteria

After 3–4 retrospectives:
- `AGENTS.md` and skill prompts carry dated edits traceable to specific log entries
- At least one delivered slice has the "applies learning" slot filled
- Signal volume in the log reflects real divergences, not noise

If those artifacts are static while LearningSignals accumulate: fix the retrospective step.
If LearningSignals are empty while deliveries ship with real divergences: fix the skill addendums.
Historical compatibility entries in `docs/learning-log.md` should trend toward zero after #1506.
