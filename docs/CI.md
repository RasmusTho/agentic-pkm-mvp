State: SoT v4.10 Reality-MVP (current core).
# Continuous Integration — SoT v4.2

## CI Stack
- GitHub Actions: `.github/workflows/ci.yml`
- Steps:
  1. Checkout repo
  2. Set up Python
  3. Install dependencies
  4. Lint: ruff, mypy
  5. Fast tests: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not eval"` (unit/contract/e2e without eval)
  6. Validate migrations: alembic upgrade head --sql

## Local lint/test
ruff check app tests
mypy app
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not eval"

## Reality smoke (local)
Deterministic runtime smoke with POLICY_ENFORCE=1, memory store, vault writes, outbox events, and a run2 no-op check:
- `scripts/reality_smoke.sh` (runs settings validate, smoke CLI `--runs 2`, verifier) writes to `tmp/vault_smoke` and `tmp/index-outbox.smoke.jsonl`.
- Manual run:
  - `python -m app.cli settings validate`
  - `POLICY_ENFORCE=1 STORE_BACKEND=memory PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 INDEX_OUTBOX_PATH=tmp/index-outbox.smoke.jsonl PANEL_AGENT_PIPELINE=planner LLM_PROVIDER=mock EMBED_DIM=1536 python -m app.cli smoke reality --vault tmp/vault_smoke --outbox tmp/index-outbox.smoke.jsonl --runs 2`
  - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 STORE_BACKEND=memory POLICY_ENFORCE=1 PANEL_AGENT_PIPELINE=planner LLM_PROVIDER=mock EMBED_DIM=1536 python scripts/verify_reality_smoke.py --vault tmp/vault_smoke --outbox tmp/index-outbox.smoke.jsonl`

## ASK smoke (local)
Deterministic ASK slice with POLICY_ENFORCE=1, seeded corpus, ASK graph run, and vault append with provenance:
- `scripts/ask_smoke.sh` seeds a tiny corpus into memory, runs `python -m app.cli smoke ask`, appends an ASK Answer section to the vault, and verifies provenance with `scripts/verify_ask_smoke.py`.
- Manual run:
  - `python -m app.cli settings validate`
  - `POLICY_ENFORCE=1 STORE_BACKEND=memory PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PANEL_AGENT_PIPELINE=planner LLM_PROVIDER=mock EMBED_DIM=1536 INDEX_OUTBOX_PATH=tmp/index-outbox.smoke.jsonl python -m app.cli smoke ask --vault tmp/vault_smoke --outbox tmp/index-outbox.smoke.jsonl --json`
  - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 STORE_BACKEND=memory POLICY_ENFORCE=1 PANEL_AGENT_PIPELINE=planner LLM_PROVIDER=mock EMBED_DIM=1536 python scripts/verify_ask_smoke.py --vault tmp/vault_smoke --outbox tmp/index-outbox.smoke.jsonl`

## Live watcher (local)
Guardrailed continuous watcher for real vaults with kill switch, scope, and rate limiting:
- Feature flags (defaults in parentheses):
  - `WATCHER_ENABLE` (0), `WATCHER_VAULT_PATH` (required when enabled), `WATCHER_SCOPE_GLOB` (${VAULT_INBOX_DIR_REL}/**)
  - `WATCHER_DEBOUNCE_MS` (1500), `WATCHER_RATE_LIMIT_PER_MIN` (30), `WATCHER_BACKOFF_SECONDS` (10)
  - Kill switch: `tmp/WATCHER_STOP` (or override via `WATCHER_STOP_FILE`) pauses the loop with a once-per-minute warning.
- Script: `VAULT=/path/to/vault scripts/run_live_watcher.sh` (sets POLICY_ENFORCE=1, WATCHER_ENABLE=1, and prints outbox/stopfile locations).
- Manual run:
  - `python -m app.cli settings validate`
  - `POLICY_ENFORCE=1 WATCHER_ENABLE=1 WATCHER_VAULT_PATH=/path/to/vault WATCHER_SCOPE_GLOB="${VAULT_INBOX_DIR_REL}/**" WATCHER_DEBOUNCE_MS=1500 WATCHER_RATE_LIMIT_PER_MIN=30 WATCHER_BACKOFF_SECONDS=10 INDEX_OUTBOX_PATH=tmp/index-outbox.live.jsonl python -m app.cli watcher run`
  - Single tick for debugging: same env + `python -m app.cli watcher once`
- State is auto-migrated to drop legacy monotonic timestamps; delete `tmp/watcher_state.json` to fully reset watcher memory when troubleshooting.

## Conventions
- All migrations must apply cleanly to an empty DB.
- CI rejects commits that break black/ruff/mypy rules.
- Test artifacts (`.pytest_cache`, `__pycache__`) are ignored in git.

## Eval tests (opt-in / separate job)
- LLM eval suites live under `tests/eval/` and are marked `@pytest.mark.eval` (see `docs/eval.md`).
- Run manually or in a separate job when LLM/vector backends are available, e.g.:
  - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "eval"`
  - `pytest -q -m "eval" tests/eval/test_ask_deepeval.py`
  - `pytest -q -m "eval" tests/eval/test_rag_ragas.py`
- Intended as quality diagnostics (answer relevancy, faithfulness); not required on every PR until datasets/thresholds are stable.
