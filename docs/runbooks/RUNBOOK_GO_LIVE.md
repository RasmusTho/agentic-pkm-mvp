# Go-Live Checklist (P0)
State: draft

Use this checklist to validate a deployment before enabling full ingest + panel actions. All steps are safe-by-default and should be run from the `work` branch.

## 1) Backups and prerequisites
- Back up the vault and outbox location (snapshots or git tag).
- Confirm environment variables are set for the target environment (at minimum: `VAULT_ROOT`, `INDEX_OUTBOX_PATH`, provider credentials, tracing/observability endpoints if used).
- Ensure networked dependencies (LLM provider, database) are reachable from the host.

## 2) Dry-run health checks
- Run `python -m app.cli go-live-check` (defaults to dry-run) to verify vault root resolution, settings load, and watcher readiness.
- If you want to target a specific profile, pass explicit paths: `python -m app.cli go-live-check --vault-root <path> --settings-path <path> --outbox-path <file>`.
- Review the watcher summary; address any errors before proceeding.

## 3) Small-scope UAT
- Run `python -m app.cli vault-watcher-run --dry-run --max-notes 10` to sample a small set of changes.
- Inspect emitted messages and ensure classification/panel policies match expectations.

## 4) Gradual rollout
- Start runtime with a low `max-notes` and `--force` disabled to prevent bulk ingestion surprises.
- Increase scope incrementally only after observing clean runs (no errors, no limit-exceeded).

## 5) Rollback posture
- If ingest produces incorrect outputs, pause watcher runs and restore from the vault/outbox backups.
- Re-run `go-live-check` after any rollback to ensure settings and paths are still valid.

## 6) Post-go-live hygiene
- Keep `LLM_TRACE_ENABLE=1` only when troubleshooting; traces are now hashed (no raw prompts/responses).
- Document any environment-specific overrides in the settings surface (vault `_system/settings/system-settings.yaml`).
