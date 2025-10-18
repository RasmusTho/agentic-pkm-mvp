# Operations Playbook

## Version & Release Workflow
- Run `python scripts/bump_version.py <new_version>` to update `settings.app_version`, core docs, and project memory (supporting `--dry-run`).
- Commit the bump with `chore(version): bump to X.Y.Z`, then create an annotated tag using `python scripts/tag_release.py [--dry-run|--push]` (tags default to `v<version>`).
- Share noteworthy changes after tagging; the bump script already appends to the decision log.

## Storage Maintenance
- The FastAPI service writes DuckDB artifacts to `storage/agent.duckdb` and provenance trails to `provenance.jsonl`.
- Rotate them with `python scripts/rotate_storage.py [--dry-run|--copy|--truncate]`, which archives into `storage/archive/` by default and keeps a bounded history (`--max-backups`).
- Schedule the script (cron/systemd/GitHub Actions) to run routinely; review `--copy/--truncate` flags depending on whether live readers expect files to remain.
- Prior to rotation, ensure no long-running agent sessions depend on the files; quiesce the service if necessary.
- Monitor free disk space and set alerts when the combined storage exceeds the agreed threshold.

## Auth & Rate Limiting
- Refer to `docs/AUTH_RATE_LIMITING.md` for implementation guidance (API key dependency + `slowapi` limiter).
- Store the API key in environment or secret manager; rotate by updating deployments and monitoring logs for legacy usage.
- Run Redis (or alternative backend) alongside FastAPI to support shared rate-limit counters; configure via env in future work.

## Observability
- Logs: JSON-formatted via `app/observability.setup_logging()`. Hook into your logging stack (CloudWatch, ELK, etc.).
- Metrics: enable `METRICS_ENABLED=1` to expose Prometheus metrics under `/metrics` using `prometheus-fastapi-instrumentator` (secure access appropriately).
