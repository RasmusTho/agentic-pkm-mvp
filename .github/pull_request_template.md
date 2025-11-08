## Title
chore: repo hygiene, CI smoke guard, semantic merge driver mapping

## Summary
- Ignore `logs/**`; keep `logs/.gitkeep`.
- Map `*.md`/`*.mdx` to `merge=semanticmd`; add `make setup-merge-driver`.
- CI: Python 3.12, matrix {memory, pg}, Postgres 16, Alembic on pg, `scripts/check_code_fences.py`, `pytest -q`.
- Fix doc links to `docs/diagrams/architecture.mmd`.

## How to Verify
- PR Actions: two green jobs: `ci-smoke / test (memory)` and `ci-smoke / test (pg)`.
- `git ls-files logs` shows only `logs/.gitkeep`.
- README and `docs/ARCHITECTURE.md` link works.

## Post-merge (manual)
- Default branch = `main`.
- Branch protection on `main`: require both ci-smoke jobs + PR review.
