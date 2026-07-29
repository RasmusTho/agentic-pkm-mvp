State: Compatibility pointer. Canonical builder-agent instructions now live in the repository root `AGENTS.md`.

# Codex Compatibility Pointer

This file is not the canonical builder-agent policy surface.

At session entry read `AGENTS.md :: Reading order` — it is the scoped entry list and names which of
its own sections and which external documents are required now versus only under a stated condition.
Do not read `AGENTS.md` whole by default.

Then use `.codex/skills/README.md :: Skill routing` to load the repo-local workflow skill that matches the task.
For GitHub implementation work, load `.codex/skills/issue-to-code/SKILL.md` before coding; that skill states every further read it needs.
Use `docs/development/DEV_WORKFLOW.md :: Validation baseline` before running or reporting validation, and `:: Working loop` when the loop is unclear.
Use `docs/development/AGENT_INSTRUCTION_GOVERNANCE.md :: Maintenance rules` and `:: Canonical entrypoints` when the diff changes an instruction artifact.

Read scope for every citation in this chain is `.codex/skills/_shared/READ_SCOPE.md`: `FILE :: Section` means read that section only, a citation with no `::` is a whole-file read that must state its reason, and `docs/DOCS_INDEX.md` is grep-only.
