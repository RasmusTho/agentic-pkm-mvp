# Operations Playbook

## Version Bump Workflow
- Update `settings.app_version` in `app/settings.py` when releasing new backend capabilities.
- Reflect the new version in any API documentation (e.g. README) and communicate client-impacting changes.
- Commit with a clear message (`chore(version): bump to X.Y.Z`) and tag the corresponding git commit.
- Record noteworthy changes in `docs/ALIGNMENT.md` under the decision log to keep the agent memory aligned.

## Storage Maintenance
- The FastAPI service writes DuckDB artifacts to `storage/agent.duckdb` and provenance trails to `provenance.jsonl`.
- Implement a recurring rotation policy (e.g. daily cron) to archive and compact these files before they grow too large.
- Store archived copies under `storage/archive/` or an external bucket with timestamps for traceability.
- Prior to rotation, ensure no long-running agent sessions depend on the files; quiesce the service if necessary.
- Monitor free disk space and set alerts when the combined storage exceeds the agreed threshold.
