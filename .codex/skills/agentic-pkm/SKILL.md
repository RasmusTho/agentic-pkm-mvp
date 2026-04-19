---
name: agentic-pkm
description: "Dev-time work in the agentic-pkm-mvp repo (Agentic PKM / Yggdrasil). Use when editing code, tests, or docs in this repo and following SoT v5.5 baseline hierarchy, dev workflow, and architecture constraints."
---

# Agentic PKM Dev Skill

## First context to load

- Always read `agentic-pkm-mvp/AGENTS.md` first. It is the canonical repo builder-agent policy.
- Prefer SoT docs over README. The README may be stale.
- Use `docs/DOCS_INDEX.md` and `docs/PROJECT_KERNEL.md` as the entry points for current documentation.

## SoT hierarchy (summary)

1. Current SoT docs (identified via `docs/DOCS_INDEX.md` after reading `AGENTS.md`)
2. Dev policy and workflow: `AGENTS.md`, `docs/development/DEV_WORKFLOW.md`
3. Domain chapters: `docs/DATA_MODEL.md`, `docs/FRONTMATTER.md`, etc.
4. Historical or archived docs: `docs/archive/*`, `docs/legacy/*`

## Default working loop

1. Identify which subsystems are touched.
2. Open relevant SoT docs and tests.
3. Propose a short plan (files, tests, docs).
4. Implement minimal changes that follow Store/Outbox/Components boundaries.
5. Update docs and tests in the same change.
6. Recommend focused test commands.

## Common entry points

- Code: `app/`, `api/`, `scripts/`, `run_agent.py`
- Docs: `docs/`, `AGENTS.md`
- Ops: `Makefile`, `docker-compose.yaml`
- Tests: `tests/`

## Typical commands (verify before running)

- Install: `python -m pip install -e .`
- Tests: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg"`
- Alpha runtime: `make alpha-up` then `python -m scripts.alpha_e2e`

## Capturing learning

**Capturing learning:** if during this work you notice a divergence from plan — you did something you did not expect to do, or discovered an earlier artifact was wrong — invoke `capture-learning` before continuing. Do not batch to end of task; context is freshest now. Only log if you can name an upstream artifact that could absorb the fix.
