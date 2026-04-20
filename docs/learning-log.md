State: Append-only delivery learning log
Doc role: Reference
Authority: Canonical log of plan divergences across delivery. Does not override issue contracts or skill prompts.
Owner: docs/development/DELIVERY_FEEDBACK_LOOP.md
Temporal class: operational
Review cadence: per retrospective
Source of truth: this file
Last reviewed: 2026-04-20
Last verified against: docs/development/DELIVERY_FEEDBACK_LOOP.md, PR #523, current repo state at 17eef96 on 2026-04-20

# Learning Log

Append-only flat file. One entry per divergence from plan. Do not edit past entries.

## Entry shape

```markdown
## YYYY-MM-DD — #<issue> (<slice title>)
**Source:** <skill name or "human">
**Diverged:** <one sentence: the plan said X, reality was Y>
**Upstream artifact:** <path or section — e.g. AGENTS.md §X, .codex/skills/issue-to-code/, task-contract template>
```

## Trigger heuristic

Log only when you did something you did not expect to do, or discovered an earlier artifact was wrong. Not when work went as planned.

If the next agent doing a similar task would benefit from an upstream artifact being different, log it — otherwise don't.

The "name an artifact" gate: you cannot log without proposing where the fix lives. If genuinely unknown, write `"unknown — flag for retro"`.

## Retrospective marker shape

Retrospective completions append:

```
--- retro YYYY-MM-DD: applied N/M proposals ---
```

This lets `learning-retrospective` scope its next read to entries since the last marker.

---

## 2026-04-19 — #514 (Delivery feedback loop — governance lane delivery)
**Source:** human (observed during issue creation)
**Diverged:** The issue-creation workflow made multiple GraphQL calls (label lookup, issue creation, project board operations) and hit the per-hour GraphQL rate limit mid-run, blocking project board assignment.
**Upstream artifact:** `.codex/skills/` — all skills that interact with GitHub; prefer REST endpoints over GraphQL; resolve GraphQL identifiers once per run and cache in variables; defer project board mutations to a single batched pass at the end.
