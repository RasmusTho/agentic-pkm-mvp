# Continuous Integration — SoT v4.2

## CI Stack
- GitHub Actions: `.github/workflows/ci.yml`
- Steps:
  1. Checkout repo
  2. Set up Python
  3. Install dependencies
  4. Lint: ruff, mypy
  5. Test: pytest -q (fast agents only)
  6. Validate migrations: alembic upgrade head --sql

## Local lint/test
ruff check app tests
mypy app
pytest -q

## Conventions
- All migrations must apply cleanly to an empty DB.
- CI rejects commits that break black/ruff/mypy rules.
- Test artifacts (`.pytest_cache`, `__pycache__`) are ignored in git.
