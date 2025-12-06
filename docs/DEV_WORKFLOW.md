# Developer Workflow — SoT v4.10

## Development Loop (order of operations)
1) **Update SoT/docs first when behavior changes** — `docs/ARCHITECTURE.md`, `docs/HUMAN-FLOWS.md`, `docs/AGENTS.md`, `docs/EVENTS.md` stay authoritative. If code and docs disagree, fix the docs or mark the delta.
2) **Add/adjust tests before coding** — follow `docs/TESTING.md` and `docs/CI.md`; write or extend unit/contract/e2e/eval tests that express the intended change.
3) **Implement within the documented architecture** — respect Stores/Outbox/Index layers and existing agent flows.
4) **Run tests/evals** — at minimum `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg"`; add targeted suites (e.g., `tests/api`, eval harnesses) when retrieval/reasoning or surfaces change.
5) **Reflect progress** — update `docs/STATUS.md` or `docs/ROADMAP.md` when the SoT shifts.

## AI-assisted development
- AI/code agents are accelerators, not architects; the SoT docs and tests stay in charge.
- Follow `docs/AI_DEVELOPMENT.md` for dev-layer guardrails (scope, constraints, required tests).
- Keep runtime prompts/behavior separate from dev prompts; runtime lives in `docs/ARCHITECTURE.md` / `docs/AGENTS.md`.

## Branch Strategy
- main → stable
- feature/* → short-lived, scoped changes

## Coding Discipline
- Deterministic: no randomness
- Explicit: every write must be visible in audit
- Transparent: logs include agent, action, trace_id
- Modular: agents are replaceable

## Debugging
tail -n 50 /tmp/agent.log
docker compose logs -f api
