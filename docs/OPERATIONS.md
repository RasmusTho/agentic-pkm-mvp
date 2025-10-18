# Operations Playbook

## Version Bump Workflow
- Run `python scripts/bump_version.py <new_version>` to update `settings.app_version`, core docs, and project memory.
- Use `--dry-run` first to verify affected files, then review the diff and commit with a message like `chore(version): bump to X.Y.Z`.
- After merge, tag the release and share any breaking changes; the script appends the decision log entry automatically.

## Storage Maintenance
- The FastAPI service writes DuckDB artifacts to `storage/agent.duckdb` and provenance trails to `provenance.jsonl`.
- Implement a recurring rotation policy (e.g. daily cron) to archive and compact these files before they grow too large.
- Store archived copies under `storage/archive/` or an external bucket with timestamps for traceability.
- Prior to rotation, ensure no long-running agent sessions depend on the files; quiesce the service if necessary.
- Monitor free disk space and set alerts when the combined storage exceeds the agreed threshold.
