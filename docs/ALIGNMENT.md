# Alignment Guide

## Why This Exists
- Keep the Agentic PKM API and agent tools aligned with the "Second-Brain" project goals.
- Protect the user's preferred way of working: short, concrete steps; iterate safely; default to open-source friendly solutions.
- Make expectations explicit so new changes can be checked against them quickly.

## Current Stage (Oct 2025)
- FastAPI backend in `app/` exposes `/`, `/items`, and `/context`.
- Agent workflow lives under `app/agent/`; `run_agent.py` is the CLI entry point.
- Data/context JSON drives memory and preferences for the agent.
- Alembic migrations are current with baseline `3ddfc7237248_baseline.py`.

## Near-Term Focus
- Finish CLI upgrades for `run_agent.py` (`--task`, `--input`, `--dry-run`).
- Add `/health` and `/version` endpoints for ops readiness.
- Keep `/items` tests passing; consider router split when CRUD grows.
- Bring in CI (pytest) plus linting (Ruff) and typing (mypy).

## Operating Principles
- Bias for maintainable, well-tested changes; add tests when behavior shifts or bugs are fixed.
- Prefer configuration via environment variables and `.env`, never check secrets into git.
- Leverage DuckDB locally (`storage/agent.duckdb`) unless requirements change.
- Document new behaviors (README, docs/) alongside code so the agent's memory stays current.

## Collaboration Norms
- Communication: respond in Swedish or English; keep replies kort & konkret.
- Process: one focused change at a time, TDD där det passar.
- Privacy: inga hemligheter i prompts; stay within opened context when possible.

## Decision Log
- 2025-10-18: Context loader added exposing repo memory through `/context`.
- 2025-10-18: Launch configuration standardized on debugpy attach at port `15678`.
