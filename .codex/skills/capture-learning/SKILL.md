---
name: capture-learning
description: "Append one structured divergence entry to docs/learning-log.md when a concrete divergence is worth immediate upstream repair; defer low-signal cases to retrospective batching."
---

# Capture Learning

Maintenance-path repair skill. Appends one entry to `docs/learning-log.md` when a plan divergence is concrete enough to name an upstream artifact now.

## When to invoke

Invoke only when:
- you did something you did not expect to do, OR
- you discovered an earlier artifact was wrong

Do NOT invoke when work went exactly as planned.

This is not a hot-path routine for every small divergence. If the signal is minor, repetitive, or not yet actionable, batch it for `learning-retrospective` instead of interrupting the current task.

The "name an artifact" gate: you must name an upstream artifact before logging. If you cannot name one, do not log.

## Required inputs

All three are required:

1. **What diverged** — one sentence: "the plan said X, reality was Y"
2. **Upstream artifact** — the named artifact that could absorb the fix. Examples:
   - `AGENTS.md §Governance lane`
   - `.codex/skills/issue-to-code/SKILL.md`
   - `docs/templates/ task-contract template`
   - `"unknown — flag for retro"` (last resort only)
3. **Source** — which skill or moment noticed it (e.g. `issue-to-code`, `verification-and-closure`, `human`)

## Behavior

Append one entry to `docs/learning-log.md` in this exact shape:

```markdown
## YYYY-MM-DD — #<issue> (<slice title>)
**Source:** <skill name or "human">
**Diverged:** <one sentence>
**Upstream artifact:** <path or section>
```

Append after the last existing entry (or after the `---` separator if the log is empty). Do not edit prior entries.

## Timing

Invoke before continuing only when the divergence needs immediate upstream repair. Otherwise, collect the signal and let the next retrospective convert batched notes into a concrete edit.

## Output format

1. Entry appended (show the appended text)
2. Upstream artifact named
3. Continue with interrupted task
