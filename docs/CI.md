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
Deterministic runtime smoke with POLICY_ENFORCE=1, memory store, vault writes, and outbox events:
- `scripts/reality_smoke.sh` (runs settings validate, smoke CLI, verifier) writes to `tmp/vault_smoke` and `tmp/index-outbox.smoke.jsonl`.
- Manual run:
  - `python -m app.cli settings validate`
  - `POLICY_ENFORCE=1 STORE_BACKEND=memory PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 INDEX_OUTBOX_PATH=tmp/index-outbox.smoke.jsonl python -m app.cli smoke reality --vault tmp/vault_smoke --outbox tmp/index-outbox.smoke.jsonl`
  - `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 STORE_BACKEND=memory POLICY_ENFORCE=1 python scripts/verify_reality_smoke.py --vault tmp/vault_smoke --outbox tmp/index-outbox.smoke.jsonl`

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
