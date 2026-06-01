---
name: capture-learning
description: "Create one BuilderOps LearningSignal when a concrete divergence is worth immediate upstream repair; use docs/learning-log.md only as a historical compatibility fallback."
---

# Capture Learning

Maintenance-path repair skill. Creates one BuilderOps `LearningSignal` record when a plan
divergence is concrete enough to name an upstream artifact now.

`docs/learning-log.md` is historical/compatibility material after #1506. Do not treat it as the
primary operational learning store.

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

Create one `LearningSignal` through the BuilderOps CLI. Use `signal_type=workflow_divergence`
unless a more specific workflow signal type is clearly better.

Suggested command shape:

```bash
python -m app.cli builderops create-learning-signal \
  --summary "<short divergence summary>" \
  --content "Issue/context: #<issue> (<slice title>)
Source: <skill name or human>
Diverged: <one sentence>
Upstream artifact: <path or section>" \
  --signal-type workflow_divergence \
  --source-ref "github_issue:#<issue>" \
  --source-ref "repo_doc:<upstream-artifact-path>" \
  --created-by codex \
  --idempotency-key "learning:<YYYY-MM-DD>:<issue-or-context>:<short-slug>" \
  --json
```

Use JSON `--source-ref` values when a source needs a `locator`, URL, or non-file authority surface.
Source refs are provenance only; they do not transfer authority.

If the BuilderOps write is genuinely unavailable, append an explicit compatibility fallback entry to
`docs/learning-log.md` in this shape:

```markdown
## YYYY-MM-DD — #<issue> (<slice title>)
**Source:** <skill name or "human">
**Diverged:** <one sentence>
**Upstream artifact:** <path or section>
**Compatibility fallback:** BuilderOps LearningSignal write unavailable: <brief reason>
```

Append fallback entries after the last existing entry (or after the `---` separator if the log is
empty). Do not edit prior entries. Fallback entries should be converted into `LearningSignal`
records before they are treated as current operational learning.

## Timing

Invoke before continuing only when the divergence needs immediate upstream repair. Otherwise, collect the signal and let the next retrospective convert batched notes into a concrete edit.

## Output format

1. BuilderOps `LearningSignal` id and JSON summary, or the explicit compatibility fallback entry
2. Upstream artifact named
3. Continue with interrupted task
