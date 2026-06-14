State: Legacy (archived).
# Decision Log Archive – October 2025 (Early Updates)

- 2025-10-18: Context loader added exposing repo memory through `/context`.
- 2025-10-18: Launch configuration standardized on debugpy attach at port `15678`.
- 2025-10-19: `run_agent.py` CLI now supports `--task`, `--input`, and `--dry-run` flags (plus tests).
- 2025-10-19: Added `/health` (DB ping) and `/version` endpoints with tests.
- 2025-10-19: FastAPI startup migrated to lifespan handler that ensures tables exist.
- 2025-10-19: `/health` now validates DuckDB connectivity and provenance.jsonl access.
- 2025-10-19: `/items` endpoints extracted to router with expanded coverage.
- 2025-10-19: CI pipeline (pytest, Ruff, mypy) established with supporting configs.
- 2025-10-19: Operations playbook dokumenterar versionering + lagringsrotation.
- 2025-10-19: `scripts/bump_version.py` infördes för att automatisera versionsflödet.
- 2025-10-19: `scripts/tag_release.py` automatiserar annoterade release-taggar.
- 2025-10-19: `scripts/rotate_storage.py` roterar DuckDB och provenance-loggar.
- 2025-10-19: Projektöversikt dokumenterad i `docs/PROJECT_OVERVIEW.md`.
- 2025-10-19: Auth + rate limiting strategi dokumenterad i `docs/AUTH_RATE_LIMITING.md`.
