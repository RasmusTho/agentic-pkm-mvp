State: Canonical builder-agent instruction file for this repository.
# Builder-Agent Instructions

This file applies to development-time builder agents and repo automation that modify, review, or validate this repository.

It does not apply to runtime/system agents that exist inside the product. Runtime/system-agent semantics live in `docs/AGENTS.md`, `docs/ARCHITECTURE.md`, and the concept contracts under `docs/CONCEPTS/`.

## Reading order

1. Read this file first.
2. Use `.codex/skills/README.md` to identify the repo-local skill path that matches the task.
3. Use `docs/DOCS_INDEX.md` to identify the owner document for the area you are touching.
4. Read the owner document before editing code or nearby docs.
5. Use `docs/development/DEV_WORKFLOW.md` for the working loop and validation expectations.
6. Use `docs/development/AGENT_INSTRUCTION_GOVERNANCE.md` for maintenance rules, rationale, and compatibility-entrypoint policy.

## Repo-local skill routing

Repo-local workflow helpers live under `.codex/skills/`. They do not replace this file, but agents should load the matching skill before substantial work when the task fits one of these routes:

- General repo dev work in this repository:
  `.codex/skills/agentic-pkm/SKILL.md`
- GitHub implementation work from a bounded Issue:
  `.codex/skills/issue-to-code/SKILL.md`
- Issue, PR, label, or Project lifecycle correction:
  `.codex/skills/issue-maintenance-change-control/SKILL.md`
- Docs-only authoritative spec work:
  `.codex/skills/docs-authoring/SKILL.md`
- Convert active docs into bounded GitHub backlog:
  `.codex/skills/docs-to-issue/SKILL.md`
- Temporal current-state doc audit / freshness work:
  `.codex/skills/temporal-doc-governance/SKILL.md`
- Branch / commit / push / PR publication after local work is ready:
  `.codex/skills/publish-pr/SKILL.md`
- PR mergeability / CI attachment before verification:
  `.codex/skills/pr-integration/SKILL.md`
- Delivery verification and feedback-loop closure:
  `.codex/skills/verification-validation-feedback/SKILL.md`

For GitHub implementation work, loading `.codex/skills/issue-to-code/SKILL.md` is mandatory before coding.
That skill owns the pickup rule:
when active work begins, move the governing Issue/Project state to `In Progress` and remove `agent:ready` before local edits so another agent does not pick up the same task.

## Change classification

Before editing, classify the change:

- `current-state correction`
  - Align code, tests, or docs to already-intended current behavior.
  - Update the owning current-state docs if reality changed or documentation was wrong.
- `enabling change`
  - Add bounded support that prepares a later target state without claiming that target state already exists.
  - Keep current-state docs honest about what is shipped now.
- `target-state / future-state work`
  - Do not write desired future behavior into current-state docs as if it were already true.
  - Put future-state intent in the relevant roadmap/plan docs and keep implementation claims explicit.

## Required rules

- Keep code, tests, and docs consistent in the same change.
- When behavior, architecture, or contracts change, update the owning docs in the same change.
- Keep normative content in the owner document; link instead of duplicating it.
- Do not turn `AGENTS.md` or `CLAUDE.md` into architecture, index, roadmap, or historical recordkeeping files.
- Keep builder-agent guidance separate from runtime/system-agent documentation.

## Docs authoring lane

Docs-only changes that evolve authoritative specification, roadmap, ADR, plan, human-flow, or governance surfaces may use the explicit docs-authoring PR lane without a governing GitHub Issue.

Rules:

- Use docs authoring only when the change is limited to approved docs-authoring surfaces and does not change code, runtime behavior, contracts, or shipped reality.
- Docs authoring prepares or clarifies authoritative repo docs; it does not replace later `docs-to-issue` backlog extraction.
- If the change affects implementation or delivered behavior, use the Issue-first implementation lane instead.

For longer explanations, maintenance rules, and compatibility-file policy, use the docs under `docs/development/`.

## Governance lane

Bounded repository-governance changes may use the explicit governance PR lane without a governing GitHub Issue.

Use this lane for:

- repo-local skills under `.codex/skills/**`
- pull request / issue governance surfaces under `.github/**`
- lightweight enforcement for docs/governance workflows such as `scripts/docs_guard.py`
- companion governance docs under `docs/**`

Rules:

- Use governance lane only when the change is limited to repository governance, agent workflow, or lightweight enforcement.
- Do not use governance lane for product/runtime implementation or shipped feature behavior.
- Keep the change inside approved governance surfaces.
- If the change starts affecting product behavior, contracts, or delivered runtime capability, use the Issue-first implementation lane instead.

## GitHub delivery governance

For implementation work, GitHub Issues are the canonical task contract.

Builder-agent rules:

- Only pick work from a GitHub Issue that is both `Status=Ready` and labeled `agent:ready`.
- Read the full Issue before editing.
- Treat `Context`, `Scope`, `Source Anchors`, `Constraints`, `Acceptance Criteria`, `Out of Scope`, `Suggested Validation`, and `Source Docs` as binding.
- Link the PR back to the governing Issue using `Fixes #<id>`, `Closes #<id>`, or `Resolves #<id>`.
- Do not treat chat-only requests as canonical implementation tasks when an Issue is expected.
- Do not expand scope beyond the Issue without updating the task contract first.
- Do not create new backlog work in GitHub without stable `Source Anchors` that point to the most local governing doc items.
- Prefer stable anchor IDs over prose fragments when the source doc is likely to produce multiple Issues over time.
- Treat GitHub Issues as the canonical backlog receipt. GitHub Project is the shared operating board when available; inline doc markers such as `Tracked by: #...` are secondary convenience notes only.
- Prefer Issues plus truthful agent labels and linked PR state as harder authority than Project state if they drift.
- Use Project `Status` as the pickup and coordination projection. `agent:ready` is only the pickup qualifier for `Status=Ready`; blocked labels belong on non-active work, and closed issues must not retain `agent:*` labels.
- When a PR delivers a tracked backlog item, update the owner doc to describe shipped reality and rewrite roadmap/plan wording so it no longer reads as pending work.
