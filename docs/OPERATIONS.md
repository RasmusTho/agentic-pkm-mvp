# Operations Playbook

## Version & Release Workflow
- Run `python scripts/bump_version.py <new_version>` to update `settings.app_version`, core docs, and project memory (supporting `--dry-run`).
- Commit the bump with `chore(version): bump to X.Y.Z`, then create an annotated tag using `python scripts/tag_release.py [--dry-run|--push]` (tags default to `v<version>`).
- Share noteworthy changes after tagging; the bump script already appends to the decision log.

## Storage Maintenance
- The FastAPI service writes DuckDB artifacts to `storage/agent.duckdb` and provenance trails to `provenance.jsonl`.
- Implement a recurring rotation policy (e.g. daily cron) to archive and compact these files before they grow too large.
- Store archived copies under `storage/archive/` or an external bucket with timestamps for traceability.
- Prior to rotation, ensure no long-running agent sessions depend on the files; quiesce the service if necessary.
- Monitor free disk space and set alerts when the combined storage exceeds the agreed threshold.
