# Claude Code Instructions

`AGENTS.md` is the canonical builder-agent instruction file for this repository. At session entry read
`AGENTS.md :: Reading order` — it is the scoped entry list and names which of its own sections and
which external documents are required now versus only under a stated condition. Do not read
`AGENTS.md` whole by default.

Then use `.codex/skills/README.md` (specifically `:: Skill routing`) to choose the repo-local workflow skill for the task.
For GitHub implementation work, load `.codex/skills/issue-to-code/SKILL.md` before coding; that skill states every further read it needs.
For specialist subagent roles, use `docs/development/BUILDER_SUBAGENT_ROLES.md`; do not treat `.codex/agents/*.toml` as Claude authority.

Read scope for every citation in this chain is `.codex/skills/_shared/READ_SCOPE.md`: `FILE :: Section` means read that section only, a citation with no `::` is a whole-file read that must state its reason, and `docs/DOCS_INDEX.md` is grep-only.

This file is only a Claude compatibility entrypoint. If a Claude-specific workflow note is ever needed, keep it here and keep `AGENTS.md` authoritative.
