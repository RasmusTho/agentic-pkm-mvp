---
name: agentic-pkm
description: "Dev-time work in the agentic-pkm-mvp repo (Agentic PKM / Yggdrasil). Use when editing code, tests, or docs in this repo and following SoT v5.5 baseline hierarchy, dev workflow, and architecture constraints."
---

# Agentic PKM Dev Skill

This is a Builder System workflow; Product/Runtime SBS impact routes via
`docs/architecture/SBS_OPERATING_MODEL.md` (see `.codex/skills/README.md`).

## First context to load

- Always read `AGENTS.md` first. It is the canonical repo builder-agent policy.
- Follow `AGENTS.md :: Reading order` for the order in which to load context; do not restate that sequence here.
- Prefer SoT docs over README. The README may be stale.
- Use `docs/DOCS_INDEX.md` and `docs/PROJECT_KERNEL.md` as the entry points for current documentation.

## SoT precedence (which source wins on conflict)

1. Current SoT docs (identified via `docs/DOCS_INDEX.md` after reading `AGENTS.md`)
2. Dev policy and workflow: `AGENTS.md`, `docs/development/DEV_WORKFLOW.md`
3. Domain chapters: `docs/DATA_MODEL.md`, `docs/FRONTMATTER.md`, etc.
4. Historical or archived docs: `docs/archive/*`

## Default working loop

1. Identify which subsystems are touched.
2. Open relevant SoT docs and tests.
3. Propose a short plan (files, tests, docs).
   - Before committing to the plan, route capability per `AGENTS.md :: Total Cost of Development`: pick the cheapest acceptable model, reasoning effort, verification, and review for the task. Escalation and de-escalation triggers live there.
   - When invoked from issue-set coordination, work from the fresh issue context and its minimal
     authority pack. Do not absorb sibling Issue history or implement a non-trivial child inline in
     the coordinator. Use one bounded issue-local helper only when `AGENTS.md :: Parallel-agent
     execution` makes its incremental input/context cost cheaper than keeping the work local.
4. Implement minimal changes that follow Store/Outbox/Components boundaries.
5. Update docs and tests in the same change.
6. Recommend focused test commands.

## Common entry points

- Code: `app/`, `api/`, `scripts/`
- Docs: `docs/`, `AGENTS.md`
- Ops: `Makefile`, `docker-compose.yaml`
- Tests: `tests/`

## Typical commands (verify before running)

- Install: `python -m pip install -e .`
- Validation baseline (required pre-merge gate for code-affecting changes; see
  `docs/development/DEV_WORKFLOW.md :: Validation baseline`): `ruff check app tests`, `mypy app`,
  the governing Issue's `Verify:` targets, and focused tests for the affected subsystem. Escalate to
  the host-leased repo-wide non-PG suite only when the contract names it or cross-system blast radius
  requires it.
- When `.codex/skills/**` changed: `python3 scripts/lint_skills_consistency.py`
- Alpha runtime: `make alpha-up` then `python -m scripts.alpha_e2e`

## Capturing learning

On a plan divergence (you did something unexpected, or discovered an earlier artifact was wrong), route it through `capture-learning` — it owns the invocation timing and the "name an upstream artifact or don't log" gate.
