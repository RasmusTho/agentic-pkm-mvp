---
name: capture-learning
description: "Append one structured divergence entry to docs/learning-log.md. Invoke when you do something you did not expect to do, or discover an earlier artifact was wrong — not on normal work."
---

# Capture Learning

Single-job micro-skill. Appends one entry to `docs/learning-log.md` when a plan divergence occurs during delivery.

## When to invoke

Invoke only when:
- you did something you did not expect to do, OR
- you discovered an earlier artifact was wrong

Do NOT invoke when work went exactly as planned.

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

Invoke before continuing with remaining task work. Context is freshest at the moment of divergence — do not batch to end of task.

## Output format

1. Entry appended (show the appended text)
2. Upstream artifact named
3. Continue with interrupted task
