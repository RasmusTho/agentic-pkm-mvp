State: v5.5 baseline aligned (legacy sections retained where noted; registry watcher default, DB outbox canonical, JSONL audit log non-canonical; watcher auto-run gated; LangGraph planner opt-in).

## v5.5 Baseline Delta (Current Reality)
- Registry watcher is the runtime default; legacy snapshot watcher is dev-only.
- DB outbox (Postgres) is the canonical queue; JSONL audit log is non-canonical and used for lag inspection.
- Watcher auto-run remains off unless allowlisted; LangGraph/Reasoning rollout is opt-in.
- See `docs/STATUS.md` and `docs/ARCHITECTURE.md` for the current baseline and forward line.


# Python Version Policy

## Targets
- **Primary local runtime target:** Python **3.14**
  - This is the main development environment.
  - Local tests and workflows should assume 3.14 unless explicitly stated otherwise.

- **CI smoke floor:** Python **3.12**
  - CI uses 3.12 as a compatibility guardrail.
  - CI is not the primary runtime target; it is a “tripwire” to avoid accidentally relying on 3.13/3.14-only syntax or behavior.

## Guardrails
- Keep core code compatible with 3.12 unless a feature is explicitly scoped to 3.14+ and gated (feature flag, isolated module, or excluded from CI).
- Use the local scripts below to validate compatibility when needed.

## Local checks (optional, on demand)

### 3.12 syntax tripwire (compile only)
Uses a Python 3.12 Docker image to compile the code, catching syntax that requires 3.13/3.14.

- `scripts/py312_compile_check.sh`

### 3.12 smoke test (optional)
Runs a minimal test pass in Python 3.12 (slower; only run when needed).

- `scripts/py312_smoke_test.sh`