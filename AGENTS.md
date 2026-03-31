State: Canonical builder-agent instruction file for this repository.
# Builder-Agent Instructions

This file applies to development-time builder agents and repo automation that modify, review, or validate this repository.

It does not apply to runtime/system agents that exist inside the product. Runtime/system-agent semantics live in `docs/AGENTS.md`, `docs/ARCHITECTURE.md`, and the concept contracts under `docs/CONCEPTS/`.

## Reading order

1. Read this file first.
2. Use `docs/DOCS_INDEX.md` to identify the owner document for the area you are touching.
3. Read the owner document before editing code or nearby docs.
4. Use `docs/development/DEV_WORKFLOW.md` for the working loop and validation expectations.
5. Use `docs/development/AGENT_INSTRUCTION_GOVERNANCE.md` for maintenance rules, rationale, and compatibility-entrypoint policy.

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

For longer explanations, maintenance rules, and compatibility-file policy, use the docs under `docs/development/`.

## GitHub delivery governance

For implementation work, GitHub Issues are the canonical task contract.

Builder-agent rules:

- Only pick work from a GitHub Issue labeled `agent:ready`.
- Read the full Issue before editing.
- Treat `Context`, `Scope`, `Source Anchors`, `Constraints`, `Acceptance Criteria`, `Out of Scope`, `Suggested Validation`, and `Source Docs` as binding.
- Link the PR back to the governing Issue using `Fixes #<id>`, `Closes #<id>`, or `Resolves #<id>`.
- Do not treat chat-only requests as canonical implementation tasks when an Issue is expected.
- Do not expand scope beyond the Issue without updating the task contract first.
- Do not create new backlog work in GitHub without stable `Source Anchors` that point to the most local governing doc items.
- Prefer stable anchor IDs over prose fragments when the source doc is likely to produce multiple Issues over time.
- Treat GitHub Issue + Project state as the canonical backlog receipt; inline doc markers such as `Tracked by: #...` are secondary convenience notes only.
- When a PR delivers a tracked backlog item, update the owner doc to describe shipped reality and rewrite roadmap/plan wording so it no longer reads as pending work.
