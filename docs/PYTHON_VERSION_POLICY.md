State: SoT v5.5 baseline (descriptive). The repo targets Python >=3.12; CI smoke is pinned to 3.12 as the floor.

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run remains off unless allowlisted; LangGraph/Reasoning rollout is opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.


# Python Version Policy (Current Reality)

## Targets
- **Repo minimum:** Python **3.12**
  - Enforced by `pyproject.toml` (`requires-python = ">=3.12"`).
- **CI smoke floor:** Python **3.12**
  - CI uses 3.12 as the compatibility guardrail / floor.

## Guardrails
- Keep core code compatible with 3.12.
- Use the local scripts below to validate compatibility when needed.

## Local checks (optional, on demand)

### 3.12 syntax tripwire (compile only)
Uses a Python 3.12 Docker image to compile the code, catching syntax that requires 3.13/3.14.

- `scripts/py312_compile_check.sh`

### 3.12 smoke test (optional)
Runs a minimal test pass in Python 3.12 (slower; only run when needed).

- `scripts/py312_smoke_test.sh`
