# Claude Code Instructions — Agentic PKM / Yggdrasil

These instructions govern how Claude Code should work in this repository.
The full contributor policy lives in `.codex/AGENTS.md` and is authoritative.
This file is a short compatibility entrypoint so development-time agents follow the same rules.

## Role

You are a development-time coding assistant for this repository.

Your scope is strictly:
- editing code, tests, and documentation,
- maintaining alignment with the current SoT,
- proposing SoT changes in a controlled, documented way.

You are not:
- a runtime/system agent,
- an execution authority inside the PKM runtime,
- a substitute for the repo’s architectural source of truth.

## Reading Order

Start here only as a pointer.
For actual policy and repo instructions, read in this order:

1. `.codex/AGENTS.md`
2. `docs/DOCS_INDEX.md`
3. `docs/DESIGN_PRINCIPLES.md`
4. `docs/STATUS.md`
5. `docs/ARCHITECTURE.md`

Then continue into the owning docs for the subsystem you are touching.

## Required Working Rules

- Treat `docs/DESIGN_PRINCIPLES.md` as the owner of stable design rules.
- Treat `docs/ARCHITECTURE.md` as the owner of structure and invariants.
- Treat `docs/ROADMAP.md` as sequencing, not as a backlog board.
- Treat `docs/STATUS.md` as present-tense truth.
- Put detailed implementation planning into `docs/plans/*` or `docs/tracks/*`, not into top-level SoT docs.
- Update `docs/DOCS_INDEX.md` whenever a new durable document or instruction entrypoint is added.

## Instruction Boundary

Development-time guidance lives in:
- `.codex/AGENTS.md`
- `docs/DEV_WORKFLOW.md`

Runtime/system-agent guidance lives in:
- `docs/AGENTS.md`
- `docs/CONCEPTS/AGENT_ONTOLOGY_CONTRACT.md`

Do not conflate the two.
