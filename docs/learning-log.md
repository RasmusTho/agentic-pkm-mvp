# Learning Log

Append-only signal log. One entry per divergence from plan. Do not edit past entries.

**Entry shape:**
```
## YYYY-MM-DD — #<issue> (<slice title>)
**Source:** <skill name or "human">
**Diverged:** <one sentence — the plan said X, reality was Y>
**Upstream artifact:** <named path or section>
```

**Trigger rule:** log only when you did something you did not expect to do, or discovered an earlier artifact was wrong. Name an upstream artifact — if you cannot, do not log.

---

## 2026-04-19 — #514 (Delivery feedback loop — governance lane delivery)
**Source:** human (observed during issue creation)
**Diverged:** The issue-creation workflow made multiple GraphQL calls (label lookup, issue creation, project board operations) and hit the per-hour GraphQL rate limit mid-run, blocking project board assignment.
**Upstream artifact:** `.codex/skills/` — all skills that interact with GitHub; prefer REST endpoints over GraphQL; resolve GraphQL identifiers once per run and cache in variables; defer project board mutations to a single batched pass at the end.
