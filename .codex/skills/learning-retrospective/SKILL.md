---
name: learning-retrospective
description: "Read docs/learning-log.md since the last retro marker, cluster signals by upstream artifact, propose concrete edits for human review, then append a retro marker. Does NOT auto-execute edits."
---

# Learning Retrospective

Periodic maintenance pass. Reads batched divergence signals logged since the last retrospective and converts them into concrete, actionable edit proposals for upstream artifacts.

**Does NOT execute edits.** All proposals go to human review first.

## Trigger

Run when the human requests a retrospective, or after approximately 10 deliveries have accumulated entries in `docs/learning-log.md`.

This is a cold-path repair step, not a hot-path delivery routine.

## Workflow

### Step 1: Read the log since last retro marker

```bash
cat docs/learning-log.md
```

Find the last line matching `--- retro YYYY-MM-DD: applied N/M proposals ---`. Read all entries after that marker. If no marker exists, read from the top of the file.

If there are fewer than 3 entries since the last marker, note this and ask whether to proceed or wait for more signal.

### Step 2: Cluster by upstream artifact

Group entries by their `**Upstream artifact:**` field. Example clusters:

- `AGENTS.md §X` — entries pointing to AGENTS.md
- `.codex/skills/issue-to-code/SKILL.md` — entries pointing to the issue-to-code skill
- `task-contract template` — entries pointing to the issue body template
- `unknown — flag for retro` — entries where the artifact was unresolved at log time

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

### Step 5: Append retro marker

After human responds (regardless of how many proposals are accepted), append to `docs/learning-log.md`:

```
--- retro YYYY-MM-DD: applied N/M proposals ---
```

Where N = accepted proposals, M = total proposals made.

Accepted proposals should be committed as governance-lane PRs — either by the human or a follow-up agent run using the `publish-pr` skill.

## Success signal

After each retrospective, at least one upstream artifact should carry a dated edit traceable to a log entry. If `AGENTS.md` and skill prompts are static while the log grows, the retrospective step is broken.

## Capturing learning

**Capturing learning:** if during this work you notice a divergence from plan — you did something you did not expect to do, or discovered an earlier artifact was wrong — invoke `capture-learning` before continuing. Do not batch to end of task; context is freshest now. Only log if you can name an upstream artifact that could absorb the fix.

## Output format

1. Log scope (entries read, date range, last retro marker if any)
2. Clusters formed (upstream artifact → entry count)
3. Proposals (numbered, concrete, with artifact path and exact edit text)
4. Retro marker appended
