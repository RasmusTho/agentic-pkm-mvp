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
