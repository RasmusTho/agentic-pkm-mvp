---
name: learning-retrospective
description: "Read BuilderOps LearningSignal records, include historical docs/learning-log.md compatibility entries when needed, cluster signals by upstream artifact, and propose concrete edits or execute explicit autonomous maintenance when requested."
---

# Learning Retrospective

Periodic maintenance pass. Reads batched BuilderOps `LearningSignal` records and converts them into
concrete, actionable edit proposals for upstream artifacts.

`docs/learning-log.md` is historical/compatibility material after #1506. Read it only for
pre-BuilderOps entries or explicit compatibility fallback entries that are not yet represented as
`LearningSignal` records.

Default mode is proposal-only: do not execute edits unless the human explicitly asks the agent to handle the retro, apply safe workflow fixes, or create Issues for unresolved work.

## Trigger

Run when the human requests a retrospective, or after approximately 10 delivery-learning
`LearningSignal` records have accumulated since the last retrospective receipt.

This is a cold-path repair step, not a hot-path delivery routine.

## Workflow

### Step 1: Read BuilderOps learning material

```bash
python -m app.cli builderops list --type LearningSignal --json
python -m app.cli builderops list --type BuilderOpsReceipt --json
python -m app.cli builderops generate-projections \
  --type learning-summary \
  --output-dir tmp/builderops-learning-retro \
  --json
cat tmp/builderops-learning-retro/learning-summary.md
```

Use the generated `learning-summary` projection as the repo-readable review view, but treat
BuilderOps Vault as the source of truth. Projection Markdown is non-authoritative.
Before deciding which signals are unprocessed, filter the `BuilderOpsReceipt` records to
`event_type=learning_retrospective` and inspect their `target_refs` for already-processed
`LearningSignal` IDs. `LearningSignal` records are not mutated when a retrospective receipt is
appended, so the receipt stream is the processing ledger.

If there are fewer than 3 unprocessed LearningSignals since the last retrospective receipt, note
this and ask whether to proceed or wait for more signal.

Do not use raw `AgentWorklog` records as authoritative learning material. A raw worklog may support
a signal through `source_refs`; if it contains a durable learning, create or request a
`LearningSignal` first.

### Step 1b: Read historical compatibility entries only when needed

```bash
cat docs/learning-log.md
```

Find the last line matching `--- retro YYYY-MM-DD: applied N/M proposals ---`. Read entries after
that marker only if they are historical pre-BuilderOps entries or explicit compatibility fallbacks
not yet represented by `LearningSignal` records.

### Step 2: Cluster by upstream artifact

Group signals by their `Upstream artifact` content or equivalent structured field. Example
clusters:

- `AGENTS.md §X` — entries pointing to AGENTS.md
- `.codex/skills/issue-to-code/SKILL.md` — entries pointing to the issue-to-code skill
- `task-contract template` — entries pointing to the issue body template
- `unknown — flag for retro` — signals where the artifact was unresolved at capture time

Prefer batching similar low-signal entries into one repair proposal when they point at the same upstream artifact.

### Step 3: Propose concrete edits

For each cluster with 2 or more entries (or 1 entry with a strong, specific signal):

Write a concrete proposal. A proposal is one of:
- **Diff**: show the exact lines to add, remove, or change in the upstream artifact
- **Specific insertion**: quote the exact paragraph to add and state where it goes (before/after which section)

Do NOT write vague recommendations like "consider improving X" or "the skill could be clearer about Y". Every proposal must be concrete enough to be committed as a governance-lane PR without further design work.

Mark each proposal with:
- `[PROPOSE #N]` — numbered for human response
- The upstream artifact path
- The concrete edit text

### Step 4: Present proposals for human review

Output all proposals clearly. State:
- How many entries were read
- How many clusters were formed
- How many proposals are being made

Wait for human response (which proposals to accept, which to reject).

### Step 5: Autonomous maintenance mode

Use this mode only when the human explicitly asks the agent to handle the retro end to end, improve the workflow, or create Issues for unresolved learnings.

In autonomous maintenance mode:
- apply only safe governance-lane edits whose upstream artifact is named by the LearningSignal or compatibility entry and whose exact repair is clear;
- verify whether any proposals were already applied by current repo reality before editing again;
- create canonical GitHub Issues via `learning-to-issue` for unresolved work, storage decisions, or changes that need human authority;
- do not change product/runtime behavior;
- do not record a retrospective completion receipt until every LearningSignal in scope is either applied, already satisfied by repo reality, or represented by an Issue.

### Step 6: Record retrospective completion

After human responds (regardless of how many proposals are accepted), append a BuilderOps receipt
targeting the processed LearningSignals:

```bash
python -m app.cli builderops append-receipt \
  --summary "Learning retrospective YYYY-MM-DD" \
  --event-type learning_retrospective \
  --actor codex \
  --occurred-at "<UTC timestamp>" \
  --target-ref "builderops_object:<learning-signal-id>" \
  --action retrospective_review \
  --receipt-body "Applied N/M proposals; unresolved items: <summary>." \
  --idempotency-key "learning-retro:<YYYY-MM-DD>:<scope>" \
  --source-ref "builderops_object:<learning-signal-id>" \
  --json
```

Repeat `--target-ref` and `--source-ref` for each processed LearningSignal when practical. Where
N = accepted proposals and M = total proposals made.

Append the old `--- retro YYYY-MM-DD: applied N/M proposals ---` marker to `docs/learning-log.md`
only when the retrospective processed historical compatibility entries from that file.

In autonomous maintenance mode, N = entries resolved directly or already satisfied by repo reality; M = entries considered. Accepted proposals should be committed as governance-lane PRs — either by the human or a follow-up agent run using the `publish-pr` skill.

## Success signal

After each retrospective, at least one upstream artifact should carry a dated edit traceable to a
LearningSignal, retrospective receipt, compatibility entry, or generated projection. If `AGENTS.md`
and skill prompts are static while LearningSignals accumulate, the retrospective step is broken.

## Capturing learning

**Capturing learning:** if during this work you notice a divergence from plan — you did something
you did not expect to do, or discovered an earlier artifact was wrong — invoke `capture-learning`
before continuing. Create a BuilderOps `LearningSignal`; use `docs/learning-log.md` only as an
explicit compatibility fallback. Do not batch to end of task; context is freshest now. Only capture
if you can name an upstream artifact that could absorb the fix.

## Output format

1. BuilderOps learning scope (LearningSignals read, date range, last retrospective receipt if known, historical compatibility marker if used)
2. Clusters formed (upstream artifact → entry count)
3. Proposals or autonomous actions (numbered, concrete, with artifact path and exact edit text or Issue receipt)
4. BuilderOps retrospective receipt, plus historical compatibility marker only if `docs/learning-log.md` entries were processed
