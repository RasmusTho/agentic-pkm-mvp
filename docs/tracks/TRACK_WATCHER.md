State: v5.4 delivered (watcher MVP + hardening); v5.5D auto-exec gated on concurrency guards.
# Track — Watcher (v5.1–v5.4 delivered)

Scope: snapshot-based vault watcher CLI/daemon, policy-gated panel auto-runs, ergonomics (dry-run, max-notes), Docker-first deployment.

## Delivered (v5.1–v5.4)
- Targeted ingest: `ingest-vault-paths` ingests specific markdown files (reused by watcher) — v5.1.
- Panel run-many CLI: `panel run-many` runs parse/runtime for multiple notes; watcher uses the same entrypoint — v5.1.
- Watcher MVP: `vault-watcher-run` performs snapshot diff, runs ingest for changed notes, optionally panel runtime, prints summary, refreshes snapshot — v5.2.
- Auto-panel policy: frontmatter `ai_panel_auto_run: watcher` (or `ai_panel: { auto_run: watcher }`) gates watcher-driven panel runs; manual CLI is always allowed — v5.3.
- Hardening & ergonomics: `--dry-run`, `--max-notes` + `--force`, structured summaries, policy skip counters — v5.4.
- Deployment: `vault-watcher-daemon` for Docker-first polling with snapshot at `/state/vault_watcher_state.json`; host service fallback (launchd/systemd) for unreliable mounts.

## v5.5D: Auto-exec Safety (CRITICAL)
- Concurrency & Idempotency Guards MUST be green before watcher auto-exec is enabled.
- Deduplicate concurrent watcher runs and auto-exec triggers to avoid duplicate events/intents.
- Note writes MUST use optimistic locking; conflicts fail safe with no corruption.
- Panel actions MUST be idempotent (`ai:id` executes at most once).
- Reference: `docs/CONCURRENCY.md`.

## Operational notes
- Watcher remains polling/snapshot-based (no OS file events).
- Policy defaults to manual/skip; watcher only runs panels when explicitly allowed.
- Summaries report changed, ingest_attempted/ingested, panel_candidates/runs, skipped_policy/limit, promotions, errors, dry_run flag.

## Links
- Forward plan items: see `docs/ROADMAP.md` (Now/Next).
- Human flow/UAT: `docs/HUMAN-FLOWS.md`.
- Observability counters: `docs/OBSERVABILITY.md` (watcher_runs, panel_runs, promotion intents/executions).
