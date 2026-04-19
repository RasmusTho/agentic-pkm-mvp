# Delivery Feedback Loop

## Problem

The `verification-validation-feedback` skill closes issues and updates project state but does not feed signal back into upstream artifacts. Every delivery is amnesiac: contract defects, process friction, and agent-behavior surprises die in the PR and never improve the system.

The loop must be pipeline-wide, not owned by verification alone. Any skill that encounters a divergence from plan holds signal worth capturing.

## Design

```
Docs → Feature → Slice → Agent → PR → CI → Verification → Merge
         ↑                    ↓ (any skill, on divergence)
         │              docs/learning-log.md
         │                    ↓
         └──── learning-retrospective (cadence-triggered)
                              ↓
               Edits to upstream artifacts:
               AGENTS.md · skill prompts · slice template
               task-contract template · owner-doc conventions
```

## Components

### 1. `capture-learning` skill

Single-job micro-skill. Appends one structured entry to `docs/learning-log.md`.

**Inputs (required):**
- **what diverged** — one sentence: the plan said X, reality was Y
- **upstream artifact** — the named artifact that could absorb the fix (`AGENTS.md §X`, `.codex/skills/issue-to-code/`, task-contract template, etc.). Must be named. If genuinely unknown, write `"unknown — flag for retro"`.
- **source** — which skill or moment noticed it

**Entry shape:**
```markdown
## YYYY-MM-DD — #<issue> (<slice title>)
**Source:** <skill name or "human">
**Diverged:** <one sentence>
**Upstream artifact:** <path or section>
```

**Trigger rule (the important part):** invoke only when you do something you did not expect to do, or discover an earlier artifact was wrong. Not when work went as planned. The heuristic: *if the next agent doing a similar task would benefit from an upstream artifact being different, log it — otherwise don't.*

**The "name an artifact" gate** kills venting. You cannot log without proposing where the fix lives.

### 2. `docs/learning-log.md`

Append-only flat file. No schema beyond the entry shape above. No database, no YAML frontmatter beyond the entry headers.

Retrospective completions append a marker line:
```
--- retro YYYY-MM-DD: applied N/M proposals ---
```

This lets the retrospective skill scope its next read to entries since the last marker.

### 3. `learning-retrospective` skill

Cadence-triggered (manual, or roughly every 10 deliveries). Reads `docs/learning-log.md` since the last retro marker.

**What it does:**
1. Clusters signals by upstream artifact.
2. Proposes **concrete edits** (diffs or specific line additions) to those artifacts — not vague recommendations.
3. Does NOT execute edits. Outputs proposals for human review.
4. Accepted proposals are committed as ordinary governance-lane PRs.
5. Appends a retro marker to the log.

**Success signal for the retrospective itself:** upstream artifacts carry dated edits traceable to log entries. If AGENTS.md and skill prompts are static while the log grows, the retrospective step is broken.

### 4. Governance lane

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

### 5. "Applies learning" slot in task-contract template

Optional section at the bottom of every slice issue:

```markdown
## Applies learning (optional)
<!-- Link to a retrospective outcome this slice is exercising. -->
<!-- Fills in when the slice was shaped by a prior retro edit. -->
```

Usually blank. When filled, enables tracing whether retro edits actually improved delivery. This is the honest end-to-end success test.

## Trigger heuristic for all skills

Every skill in `.codex/skills/` carries this addendum:

> **Capturing learning:** if during this work you notice a divergence from plan — you did something you didn't expect to do, or discovered an earlier artifact was wrong — invoke `capture-learning` before continuing. Do not batch to end of task; context is freshest now. Only log if you can name an upstream artifact that could absorb the fix.

## What this is not

- Not a metrics dashboard
- Not structured telemetry or auto-classification
- Not a blocking gate in the delivery path — the loop is asynchronous, delivery velocity is unchanged
- Not a second Project board or new agent
- Not mandatory per-delivery — log only on divergence

## Success criteria

After 3–4 retrospectives:
- `AGENTS.md` and skill prompts carry dated edits traceable to specific log entries
- At least one delivered slice has the "applies learning" slot filled
- Signal volume in the log reflects real divergences, not noise

If those artifacts are static while the log grows: fix the retrospective step.
If the log is empty while deliveries ship: fix the skill addendums.
Either failure mode is diagnosable from two files.
